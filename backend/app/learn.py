"""Learning from the Workbench: the platform's own local model.

Every approve and reject in the Workbench is a label. This module turns those
labels into a small pairwise classifier over the evidence the pipeline already
stores for each pair (anchor, fuzzy, semantic, attribute agreement, which
roles agreed and which did not), trains it, and keeps the result as a JSON
file of weights that anyone can read.

What the model is allowed to do is deliberately narrow:

* It never changes a verdict. The veto layer (§2A) stays absolute and the
  pipeline's confidence stays the number a merge is judged by.
* It orders the review queue by uncertainty, so a reviewer's next ten minutes
  go to the pairs that teach the system the most.
* It shows its own probability beside the pipeline's on the card, and is
  measured against the held-out split, so the README can say honestly whether
  the reviewer-trained model beats the hand-tuned score.

Why not fine-tune the language model instead: the decisions that matter here
are pairwise and attribute-driven, and a 3B model cannot be audited. Fifteen
weights can. The labelled pairs are also exported as a corpus, which is what a
future LoRA on the local LLM would need and does not have today.
"""

from __future__ import annotations

import json
import math
import os
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Cpse, Item, Pair, PairLabel, RawItem, TruthGroup

#: Fewer labels than this and a fitted line is a guess wearing a lab coat.
MIN_LABELS = 40
#: Both answers must be represented; a model that has only seen "yes" learns
#: nothing about "no".
MIN_PER_CLASS = 10
#: Cross-validate only when there is enough to fold.
CV_FOLDS = 5
CV_MIN_LABELS = 50

SOURCE_REVIEWER = "reviewer"
SOURCE_SIMULATED = "simulated"

FEATURES = (
    "tier0_anchor",
    "has_anchor",
    "tier1_fuzzy",
    "tier2_semantic",
    "attribute_agreement",
    "identity_match",
    "identity_mismatch",
    "identity_unknown",
    "performance_in_band",
    "performance_out_of_band",
    "cosmetic_match",
    "compared",
    "route_tiered",
    "conflict",
    "vetoed",
)


def model_path() -> Path:
    """Beside the other local models; overridable so tests never touch it."""
    override = os.environ.get("SAMAN_LEARN_MODEL_PATH")
    if override:
        return Path(override)
    return Path(get_settings().db_file).resolve().parent / "models" / "pairwise.json"


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------


def features(tier_scores: dict, evidence: dict, veto: dict | None) -> list[float]:
    """One row of the design matrix, from what the pipeline stored for a pair.

    Deterministic and dependency-free, so the same function serves training,
    scoring and the tests that pin its behaviour.
    """
    attributes = evidence.get("attributes") or {}
    per_attr = attributes.get("per_attr") or []
    counts = {
        ("identity_critical", "match"): 0,
        ("identity_critical", "mismatch"): 0,
        ("identity_critical", "unknown"): 0,
        ("performance", "in_band"): 0,
        ("performance", "out_of_band"): 0,
        ("cosmetic", "match"): 0,
    }
    for entry in per_attr:
        key = (entry.get("role"), entry.get("result"))
        if key in counts:
            counts[key] += 1
        elif entry.get("role") == "performance" and entry.get("result") == "match":
            counts[("performance", "in_band")] += 1
    vetoed = bool(veto and veto.get("vetoed_by"))
    return [
        float(tier_scores.get("tier0_anchor") or 0.0),
        1.0 if tier_scores.get("tier0_key") else 0.0,
        float(tier_scores.get("tier1_fuzzy") or 0.0),
        float(tier_scores.get("tier2_semantic") or 0.0),
        float(tier_scores.get("attribute_agreement") or attributes.get("agreement") or 0.0),
        float(counts[("identity_critical", "match")]),
        float(counts[("identity_critical", "mismatch")]),
        float(counts[("identity_critical", "unknown")]),
        float(counts[("performance", "in_band")]),
        float(counts[("performance", "out_of_band")]),
        float(counts[("cosmetic", "match")]),
        float(len(per_attr)),
        1.0 if evidence.get("route") == "tiered" else 0.0,
        1.0 if evidence.get("conflict") else 0.0,
        1.0 if vetoed else 0.0,
    ]


def pair_features(pair: Pair) -> list[float] | None:
    """None when the pipeline kept no evidence for the pair (§8A trims the low
    band), because a row of zeros would teach the model the wrong lesson."""
    evidence = json.loads(pair.evidence_json or "{}")
    if not evidence:
        return None
    return features(
        json.loads(pair.tier_scores_json or "{}"),
        evidence,
        json.loads(pair.veto_json) if pair.veto_json else None,
    )


# --------------------------------------------------------------------------
# The model, as data
# --------------------------------------------------------------------------


@dataclass
class Model:
    features: list[str]
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    trained_at: str
    n_labels: int
    labels: dict[str, int] = field(default_factory=dict)
    cv: dict = field(default_factory=dict)
    holdout: dict | None = None
    #: The newest label the model has seen; "labels since" counts past it.
    last_label_id: int = 0

    def probability(self, x: list[float]) -> float:
        z = self.intercept
        for value, mean, scale, weight in zip(x, self.mean, self.scale, self.coef, strict=True):
            z += weight * ((value - mean) / scale if scale else 0.0)
        z = max(-40.0, min(40.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def weights(self) -> dict[str, float]:
        """Standardised weights: the size says how much each feature moves the answer."""
        return {name: round(w, 4) for name, w in zip(self.features, self.coef, strict=True)}

    def as_dict(self) -> dict:
        return {
            "features": self.features,
            "mean": self.mean,
            "scale": self.scale,
            "coef": self.coef,
            "intercept": self.intercept,
            "trained_at": self.trained_at,
            "n_labels": self.n_labels,
            "labels": self.labels,
            "cv": self.cv,
            "holdout": self.holdout,
            "last_label_id": self.last_label_id,
        }


_cache: tuple[float, Model] | None = None


def load_model() -> Model | None:
    global _cache
    path = model_path()
    if not path.exists():
        _cache = None
        return None
    mtime = path.stat().st_mtime
    if _cache and _cache[0] == mtime:
        return _cache[1]
    raw = json.loads(path.read_text())
    model = Model(**{k: raw[k] for k in Model.__dataclass_fields__ if k in raw})
    _cache = (mtime, model)
    return model


def save_model(model: Model) -> Path:
    path = model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.as_dict(), indent=2))
    return path


def forget_model() -> None:
    """Remove the trained model (tests, or an operator starting over)."""
    global _cache
    _cache = None
    path = model_path()
    if path.exists():
        path.unlink()


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def record_label(
    db: Session,
    pair: Pair,
    label: bool,
    user_id: int | None,
    source: str = SOURCE_REVIEWER,
) -> PairLabel:
    """Keyed by the two items: a pipeline rerun rebuilds the pair table, and
    the answer was about the items, not about a row id."""
    a, b = sorted((pair.item_a, pair.item_b))
    row = PairLabel(
        pair_id=pair.id, item_a=a, item_b=b, label=label, source=source, user_id=user_id
    )
    db.add(row)
    return row


def _current_pairs(db: Session, labels: list[PairLabel]) -> dict[int, Pair]:
    """The pair each label is about, found by its two items rather than by a
    pair id that a rerun of the match stage reassigns."""
    out: dict[int, Pair] = {}
    if not labels:
        return out
    item_ids = {row.item_a for row in labels} | {row.item_b for row in labels}
    by_items: dict[tuple[int, int], Pair] = {}
    for pair in db.execute(select(Pair).where(Pair.item_a.in_(item_ids))).scalars():
        by_items[tuple(sorted((pair.item_a, pair.item_b)))] = pair
    for pair in db.execute(select(Pair).where(Pair.item_b.in_(item_ids))).scalars():
        by_items.setdefault(tuple(sorted((pair.item_a, pair.item_b))), pair)
    for row in labels:
        pair = by_items.get((row.item_a, row.item_b))
        if pair is not None:
            out[row.id] = pair
    return out


def label_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(PairLabel.source, func.count(PairLabel.id)).group_by(PairLabel.source)
    ).all()
    return {source: count for source, count in rows}


def labelled(db: Session) -> list[tuple[int, list[float], bool, str]]:
    """Every label with its pair's features. A pair labelled twice keeps its
    latest answer, so a reviewer who changes their mind is heard."""
    latest: dict[tuple[int, int], PairLabel] = {}
    for row in db.execute(select(PairLabel).order_by(PairLabel.id)).scalars():
        latest[(row.item_a, row.item_b)] = row
    pairs = _current_pairs(db, list(latest.values()))
    out = []
    for row in latest.values():
        pair = pairs.get(row.id)
        if pair is None:
            continue
        x = pair_features(pair)
        if x is None:
            continue
        out.append((pair.id, x, bool(row.label), row.source))
    return out


def _truth(db: Session, split: str) -> dict[int, str]:
    """item_id -> truth group, for one split only."""
    rows = db.execute(
        select(Item.id, TruthGroup.group_id)
        .join(TruthGroup, TruthGroup.raw_item_id == Item.raw_item_id)
        .where(TruthGroup.split == split)
    ).all()
    return {item_id: group for item_id, group in rows}


def simulate_labels(db: Session, n: int = 400, seed: int = 20260903) -> dict:
    """Stand in for reviewers on the tuning split, for the demo.

    The seed's ground truth answers "same product or not" for pairs whose
    items are both in the **tuning** split. Labels are written with
    ``source="simulated"`` so they are never mistaken for a person's decision,
    and the held-out split is never read, so the evaluation stays honest.
    Balanced by construction: half yes, half no, as far as the pairs allow.
    """
    truth = _truth(db, "tuning")
    already = {
        (a, b) for a, b in db.execute(select(PairLabel.item_a, PairLabel.item_b).distinct()).all()
    }
    positives: list[int] = []
    negatives: list[int] = []
    # Every band with evidence, not only the review bands: a model that has
    # never seen a vetoed pair cannot learn what a veto looks like, and the
    # low band is where those live.
    rows = db.execute(
        select(Pair.id, Pair.item_a, Pair.item_b)
        .where(Pair.evidence_json != "{}")
        .order_by(Pair.id)
    ).all()
    for pair_id, a, b in rows:
        if tuple(sorted((a, b))) in already or a not in truth or b not in truth:
            continue
        (positives if truth[a] == truth[b] else negatives).append(pair_id)
    rng = random.Random(seed)
    rng.shuffle(positives)
    rng.shuffle(negatives)
    half = n // 2
    chosen = [(p, True) for p in positives[:half]] + [(p, False) for p in negatives[: n - half]]
    for pair_id, label in chosen:
        record_label(db, db.get(Pair, pair_id), label, None, SOURCE_SIMULATED)
    db.commit()
    return {
        "added": len(chosen),
        "positives": sum(1 for _, y in chosen if y),
        "negatives": sum(1 for _, y in chosen if not y),
        "available_positive": len(positives),
        "available_negative": len(negatives),
        "source": SOURCE_SIMULATED,
    }


# --------------------------------------------------------------------------
# Training and evaluation
# --------------------------------------------------------------------------


def _fit(X, y):
    """Logistic regression on standardised features; returns (mean, scale, coef, intercept)."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    X = np.asarray(X, dtype=float)
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1.0
    Z = (X - mean) / scale
    # liblinear: exact on a few hundred rows, deterministic, and quiet on
    # every scipy this project pins.
    clf = LogisticRegression(C=1.0, class_weight="balanced", solver="liblinear", max_iter=2000)
    clf.fit(Z, y)
    return mean.tolist(), scale.tolist(), clf.coef_[0].tolist(), float(clf.intercept_[0])


def _cross_validate(X, y) -> dict:
    import numpy as np
    from sklearn.metrics import precision_score, recall_score, roc_auc_score
    from sklearn.model_selection import StratifiedKFold

    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    if len(y) < CV_MIN_LABELS or min(y.sum(), len(y) - y.sum()) < CV_FOLDS:
        return {"folds": 0, "auc": None, "precision": None, "recall": None}
    aucs, precisions, recalls = [], [], []
    folds = StratifiedKFold(CV_FOLDS, shuffle=True, random_state=0)
    for train_idx, test_idx in folds.split(X, y):
        mean, scale, coef, intercept = _fit(X[train_idx], y[train_idx])
        model = Model(list(FEATURES), mean, scale, coef, intercept, "", 0)
        probs = np.array([model.probability(list(row)) for row in X[test_idx]])
        truth = y[test_idx]
        if len(set(truth.tolist())) == 2:
            aucs.append(roc_auc_score(truth, probs))
        predicted = (probs >= 0.5).astype(int)
        precisions.append(precision_score(truth, predicted, zero_division=0))
        recalls.append(recall_score(truth, predicted, zero_division=0))
    return {
        "folds": CV_FOLDS,
        "auc": round(float(sum(aucs) / len(aucs)), 4) if aucs else None,
        "precision": round(float(sum(precisions) / len(precisions)), 4),
        "recall": round(float(sum(recalls) / len(recalls)), 4),
    }


def evaluate_holdout(db: Session, model: Model) -> dict:
    """The model against the held-out split, beside the pipeline's own score.

    Same pairs, same truth, two rankings: does the reviewer-trained model
    separate duplicates from non-duplicates better than the hand-tuned
    confidence? Reported as AUC so the threshold is not part of the answer.
    """
    from sklearn.metrics import roc_auc_score

    truth = _truth(db, "holdout")
    y, model_scores, pipeline_scores, bands = [], [], [], []
    for pair in db.execute(
        select(Pair).where(Pair.evidence_json != "{}").order_by(Pair.id)
    ).scalars():
        if pair.item_a not in truth or pair.item_b not in truth:
            continue
        x = pair_features(pair)
        if x is None:
            continue
        y.append(1 if truth[pair.item_a] == truth[pair.item_b] else 0)
        model_scores.append(model.probability(x))
        pipeline_scores.append(pair.confidence)
        bands.append(pair.band)

    def auc(mask) -> tuple[float | None, float | None, int]:
        ys = [v for v, m in zip(y, mask, strict=True) if m]
        if len(set(ys)) < 2:
            return None, None, len(ys)
        ms = [v for v, m in zip(model_scores, mask, strict=True) if m]
        ps = [v for v, m in zip(pipeline_scores, mask, strict=True) if m]
        return (
            round(float(roc_auc_score(ys, ms)), 4),
            round(float(roc_auc_score(ys, ps)), 4),
            len(ys),
        )

    overall_model, overall_pipeline, n = auc([True] * len(y))
    # The grey band is where the model is actually used, and where the
    # pipeline's own score is by definition least sure; that is the number
    # that says whether the reviewers' labels added anything.
    grey_model, grey_pipeline, n_grey = auc([b == "grey" for b in bands])
    return {
        "pairs": n,
        "positives": sum(y),
        "model_auc": overall_model,
        "pipeline_auc": overall_pipeline,
        "grey_pairs": n_grey,
        "grey_model_auc": grey_model,
        "grey_pipeline_auc": grey_pipeline,
    }


class NotEnoughLabels(ValueError):
    pass


def train(db: Session) -> Model:
    rows = labelled(db)
    y = [1 if label else 0 for _, _, label, _ in rows]
    n_pos, n_neg = sum(y), len(y) - sum(y)
    if len(rows) < MIN_LABELS or min(n_pos, n_neg) < MIN_PER_CLASS:
        raise NotEnoughLabels(
            f"{len(rows)} labelled pairs ({n_pos} yes, {n_neg} no); training needs at least "
            f"{MIN_LABELS} with {MIN_PER_CLASS} of each. Decide more pairs in the Workbench."
        )
    X = [x for _, x, _, _ in rows]
    cv = _cross_validate(X, y)
    mean, scale, coef, intercept = _fit(X, y)
    by_source: dict[str, int] = {}
    for _, _, _, source in rows:
        by_source[source] = by_source.get(source, 0) + 1
    model = Model(
        features=list(FEATURES),
        mean=mean,
        scale=scale,
        coef=coef,
        intercept=intercept,
        trained_at=datetime.now(UTC).isoformat(timespec="seconds"),
        n_labels=len(rows),
        labels=by_source,
        cv=cv,
        last_label_id=db.execute(select(func.max(PairLabel.id))).scalar() or 0,
    )
    model.holdout = evaluate_holdout(db, model)
    save_model(model)
    global _cache
    _cache = None
    return model


# --------------------------------------------------------------------------
# Serving
# --------------------------------------------------------------------------


def score(pair: Pair, model: Model | None = None) -> dict | None:
    """What the model thinks of one pair, for the card. None without a model
    or without evidence."""
    model = model or load_model()
    if model is None:
        return None
    x = pair_features(pair)
    if x is None:
        return None
    p = model.probability(x)
    leans = "duplicate" if p >= 0.5 else "distinct"
    return {
        "probability": round(p, 4),
        "leans": leans,
        "agrees_with_pipeline": (pair.verdict == "duplicate") == (leans == "duplicate"),
        "uncertainty": round(1.0 - abs(p - 0.5) * 2, 4),
    }


def status(db: Session) -> dict:
    model = load_model()
    counts = label_counts(db)
    since = 0
    if model:
        since = (
            db.execute(
                select(func.count(PairLabel.id)).where(PairLabel.id > model.last_label_id)
            ).scalar()
            or 0
        )
    total = sum(counts.values())
    if model is None:
        note = (
            f"No model yet. {total} labelled pairs so far; training needs {MIN_LABELS}. "
            "Every approve or reject in the Workbench adds one."
        )
    else:
        note = f"Trained on {model.n_labels} labelled pairs. " + (
            f"{since} new labels since; retrain to use them." if since else "Up to date."
        )
    return {
        "trained": model is not None,
        "model": (
            {
                "trained_at": model.trained_at,
                "n_labels": model.n_labels,
                "labels": model.labels,
                "features": model.features,
                "weights": model.weights(),
                "cv": model.cv,
                "holdout": model.holdout,
                "path": str(model_path()),
            }
            if model
            else None
        ),
        "labels": counts,
        "labels_since_training": since,
        "min_labels": MIN_LABELS,
        "decides": False,
        "note": note,
    }


def corpus(db: Session) -> Iterator[str]:
    """The labelled pairs as JSON lines: both descriptions, the evidence and
    the answer. The training set a future fine-tune of the local LLM would
    need, kept in the open rather than promised."""
    labels = list(db.execute(select(PairLabel).order_by(PairLabel.id)).scalars())
    pairs = _current_pairs(db, labels)
    for row in labels:
        pair = pairs.get(row.id)
        if pair is None:
            continue
        sides = {}
        for side, item_id in (("a", pair.item_a), ("b", pair.item_b)):
            item = db.execute(
                select(
                    RawItem.description,
                    RawItem.legacy_code,
                    Cpse.code,
                    Item.norm_text,
                    Item.attrs_json,
                )
                .join(Item, Item.raw_item_id == RawItem.id)
                .join(Cpse, Cpse.id == RawItem.cpse_id)
                .where(Item.id == item_id)
            ).first()
            if item is None:
                continue
            attrs = json.loads(item[4] or "{}")
            sides[side] = {
                "cpse": item[2],
                "legacy_code": item[1],
                "description": item[0],
                "normalized": item[3],
                "attrs": {k: v for k, v in attrs.items() if not k.startswith("_")},
            }
        yield (
            json.dumps(
                {
                    "pair_id": pair.id,
                    "label": "duplicate" if row.label else "distinct",
                    "source": row.source,
                    "ts": row.ts.isoformat() if row.ts else None,
                    "pipeline": {"verdict": pair.verdict, "confidence": pair.confidence},
                    "tier_scores": json.loads(pair.tier_scores_json or "{}"),
                    "veto": json.loads(pair.veto_json) if pair.veto_json else None,
                    **sides,
                },
                sort_keys=True,
            )
            + "\n"
        )
