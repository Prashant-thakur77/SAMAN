"""Learning from the Workbench: the platform's own local model.

Every approve and reject in the Workbench is a label. This module turns those
labels into a small pairwise classifier over the evidence the pipeline already
stores for each pair (anchor, fuzzy, semantic, attribute agreement, which
roles agreed and which did not) and a few facts about the two items, trains
it, and keeps the result as a JSON file of weights that anyone can read.

What the model is allowed to do is deliberately narrow:

* It never changes a verdict. The veto layer (§2A) stays absolute and the
  pipeline's confidence stays the number a merge is judged by.
* It orders the review queue by uncertainty, so a reviewer's next ten minutes
  go to the pairs that teach the system the most.
* It shows its own probability beside the pipeline's on the card, and is
  measured against the held-out split, so the README can say honestly whether
  the reviewer-trained model beats the hand-tuned score.

It retrains itself as reviewer decisions accumulate, as a champion/challenger
loop: the new model replaces the old one only if it is not worse on the
held-out split, and every attempt is written down whether it won or not. The
same measurement produces threshold *suggestions* per class; they are never
applied, because a registrar changes thresholds deliberately.

Why not fine-tune the language model instead: the decisions that matter here
are pairwise and attribute-driven, and a 3B model cannot be audited. Two
dozen weights can. The labelled pairs are also exported as a corpus, which is
what a future LoRA on the local LLM would need and does not have today.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Cpse, Item, Pair, PairLabel, RawItem, TruthGroup

log = logging.getLogger(__name__)

#: Fewer labels than this and a fitted line is a guess wearing a lab coat.
MIN_LABELS = 40
#: Both answers must be represented; a model that has only seen "yes" learns
#: nothing about "no".
MIN_PER_CLASS = 10
#: Cross-validate only when there is enough to fold.
CV_FOLDS = 5
CV_MIN_LABELS = 50
#: A challenger may trail the champion by this much held-out AUC and still be
#: promoted: two models measured on the same few hundred grey pairs differ by
#: that much from noise alone, and a fresher model has seen more decisions.
PROMOTION_TOLERANCE = 0.005
#: Threshold suggestions need this many labelled pairs in a class, with both
#: answers present, before a cut is worth printing.
SUGGESTION_MIN_LABELS = 30

SOURCE_REVIEWER = "reviewer"
SOURCE_SIMULATED = "simulated"

#: Every feature is something a reviewer could check by hand from the card.
#: The first fifteen are the original set; a model saved with only those still
#: loads, because features are matched by name. Kept at or under two dozen on
#: purpose: a model that fits on one screen is a model that can be argued with.
FEATURES = (
    # the pipeline's own tiers
    "tier0_anchor",
    "has_anchor",
    "tier1_fuzzy",
    "tier2_semantic",
    "attribute_agreement",
    # the attribute comparison, by role and result
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
    # what else the stored evidence says
    "identity_coverage",
    "held_for_review",
    "equivalence_candidate",
    "brand_equal",
    "brand_differs",
    # the two items' own fields
    "same_cpse",
    "mpn_differs",
    "token_jaccard",
    "length_ratio",
)


def model_path() -> Path:
    """Beside the other local models; overridable so tests never touch it."""
    override = os.environ.get("SAMAN_LEARN_MODEL_PATH")
    if override:
        return Path(override)
    return Path(get_settings().db_file).resolve().parent / "models" / "pairwise.json"


def history_path() -> Path:
    """Every training attempt, one JSON line each, beside the model."""
    override = os.environ.get("SAMAN_LEARN_HISTORY_PATH")
    if override:
        return Path(override)
    path = model_path()
    return path.with_name(f"{path.stem}-history.jsonl")


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------


class ItemFacts(NamedTuple):
    """The few stored fields of an item the features read. Loaded in one
    query per batch; never a lookup per pair."""

    cpse_id: int | None
    class_code: str | None
    mpn_norm: str | None
    gtin: str | None
    tokens: frozenset[str]
    length: int


def item_facts(db: Session, item_ids: Iterable[int]) -> dict[int, ItemFacts]:
    """One query for a batch of items. A large batch reads the whole table
    rather than binding thousands of parameters to an IN clause."""
    ids = set(item_ids)
    if not ids:
        return {}
    query = select(
        Item.id, RawItem.cpse_id, Item.class_code, Item.mpn_norm, Item.gtin, Item.norm_text
    ).join(RawItem, RawItem.id == Item.raw_item_id)
    if len(ids) <= 500:
        query = query.where(Item.id.in_(ids))
    out: dict[int, ItemFacts] = {}
    for item_id, cpse_id, class_code, mpn, gtin, text in db.execute(query).all():
        if item_id not in ids:
            continue
        text = text or ""
        out[item_id] = ItemFacts(cpse_id, class_code, mpn, gtin, frozenset(text.split()), len(text))
    return out


def features(
    tier_scores: dict,
    evidence: dict,
    veto: dict | None,
    a: ItemFacts | None = None,
    b: ItemFacts | None = None,
) -> dict[str, float | None]:
    """One row of the design matrix, keyed by feature name.

    Deterministic and dependency-free, so the same function serves training,
    scoring and the tests that pin its behaviour. The item-derived features
    are ``None`` when the items' facts were not supplied; a model treats an
    unknown value as its training mean, so an old caller still gets an answer.
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
    brand = None
    for entry in per_attr:
        key = (entry.get("role"), entry.get("result"))
        if key in counts:
            counts[key] += 1
        elif entry.get("role") == "performance" and entry.get("result") == "match":
            counts[("performance", "in_band")] += 1
        if entry.get("attr") == "brand":
            brand = entry.get("result")
    vetoed = bool(veto and veto.get("vetoed_by"))
    identity_seen = (
        counts[("identity_critical", "match")]
        + counts[("identity_critical", "mismatch")]
        + counts[("identity_critical", "unknown")]
    )
    identity_compared = identity_seen - counts[("identity_critical", "unknown")]
    row: dict[str, float | None] = {
        "tier0_anchor": float(tier_scores.get("tier0_anchor") or 0.0),
        "has_anchor": 1.0 if tier_scores.get("tier0_key") else 0.0,
        "tier1_fuzzy": float(tier_scores.get("tier1_fuzzy") or 0.0),
        "tier2_semantic": float(tier_scores.get("tier2_semantic") or 0.0),
        "attribute_agreement": float(
            tier_scores.get("attribute_agreement") or attributes.get("agreement") or 0.0
        ),
        "identity_match": float(counts[("identity_critical", "match")]),
        "identity_mismatch": float(counts[("identity_critical", "mismatch")]),
        "identity_unknown": float(counts[("identity_critical", "unknown")]),
        "performance_in_band": float(counts[("performance", "in_band")]),
        "performance_out_of_band": float(counts[("performance", "out_of_band")]),
        "cosmetic_match": float(counts[("cosmetic", "match")]),
        "compared": float(len(per_attr)),
        "route_tiered": 1.0 if evidence.get("route") == "tiered" else 0.0,
        "conflict": 1.0 if evidence.get("conflict") else 0.0,
        "vetoed": 1.0 if vetoed else 0.0,
        # Share of the class's identity attributes that could actually be
        # compared: the pipeline's own "thin evidence" measure.
        "identity_coverage": (identity_compared / identity_seen) if identity_seen else 1.0,
        "held_for_review": 1.0 if evidence.get("held_for_review") else 0.0,
        "equivalence_candidate": 1.0 if evidence.get("equivalence") else 0.0,
        "brand_equal": 1.0 if brand == "match" else 0.0,
        "brand_differs": 1.0 if brand == "mismatch" else 0.0,
    }
    if a is None or b is None:
        row.update(same_cpse=None, mpn_differs=None, token_jaccard=None, length_ratio=None)
    else:
        union = a.tokens | b.tokens
        longest = max(a.length, b.length)
        row.update(
            same_cpse=1.0 if a.cpse_id == b.cpse_id else 0.0,
            mpn_differs=1.0 if (a.mpn_norm and b.mpn_norm and a.mpn_norm != b.mpn_norm) else 0.0,
            token_jaccard=(len(a.tokens & b.tokens) / len(union)) if union else 0.0,
            length_ratio=(min(a.length, b.length) / longest) if longest else 1.0,
        )
    return row


def pair_features(
    pair: Pair, facts: dict[int, ItemFacts] | None = None
) -> dict[str, float | None] | None:
    """None when the pipeline kept no evidence for the pair (§8A trims the low
    band), because a row of zeros would teach the model the wrong lesson."""
    evidence = json.loads(pair.evidence_json or "{}")
    if not evidence:
        return None
    facts = facts or {}
    return features(
        json.loads(pair.tier_scores_json or "{}"),
        evidence,
        json.loads(pair.veto_json) if pair.veto_json else None,
        facts.get(pair.item_a),
        facts.get(pair.item_b),
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
    #: "reviewer" when the model was fitted on people's decisions alone,
    #: "all" when the simulated labels were still needed to make the numbers.
    trained_on: str = "all"

    def vector(self, x: dict[str, float | None] | list[float | None]) -> list[float | None]:
        """A row in this model's feature order. A dict is matched by name, so
        a model saved with fewer features scores a richer row and vice versa;
        a list is taken as already in order."""
        if isinstance(x, dict):
            return [x.get(name) for name in self.features]
        return list(x)

    def probability(self, x: dict[str, float | None] | list[float | None]) -> float:
        z = self.intercept
        for value, mean, scale, weight in zip(
            self.vector(x), self.mean, self.scale, self.coef, strict=True
        ):
            if value is None:
                # Unknown: the training mean, which standardises to zero.
                continue
            z += weight * ((value - mean) / scale if scale else 0.0)
        z = max(-40.0, min(40.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def weights(self) -> dict[str, float]:
        """Standardised weights: the size says how much each feature moves the answer."""
        return {name: round(w, 4) for name, w in zip(self.features, self.coef, strict=True)}

    def holdout_auc(self) -> float | None:
        return (self.holdout or {}).get("model_auc")

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
            "trained_on": self.trained_on,
        }


class ModelRejected(ValueError):
    """A saved model this code cannot score; the message says to retrain."""


_cache: tuple[float, Model] | None = None
#: Why the saved model was refused, if it was, for the status page.
_load_error: str | None = None


def _validate(raw: dict) -> Model:
    missing = [k for k in ("features", "mean", "scale", "coef", "intercept") if k not in raw]
    if missing:
        raise ModelRejected(f"saved model lacks {', '.join(missing)}; retrain")
    names = list(raw["features"])
    lengths = {len(names), len(raw["mean"]), len(raw["scale"]), len(raw["coef"])}
    if len(lengths) != 1:
        raise ModelRejected("saved model's features and weights disagree in length; retrain")
    unknown = [name for name in names if name not in FEATURES]
    if unknown:
        raise ModelRejected(
            f"saved model uses features this version does not compute "
            f"({', '.join(unknown[:3])}{'...' if len(unknown) > 3 else ''}); retrain"
        )
    return Model(**{k: raw[k] for k in Model.__dataclass_fields__ if k in raw})


def load_model() -> Model | None:
    global _cache, _load_error
    path = model_path()
    if not path.exists():
        _cache = None
        _load_error = None
        return None
    mtime = path.stat().st_mtime
    if _cache and _cache[0] == mtime:
        return _cache[1]
    try:
        model = _validate(json.loads(path.read_text()))
    except (ModelRejected, ValueError, TypeError) as exc:
        _cache = None
        _load_error = (
            str(exc) if isinstance(exc, ModelRejected) else f"unreadable model: {exc}; retrain"
        )
        log.warning("pairwise model at %s refused: %s", path, _load_error)
        return None
    _cache = (mtime, model)
    _load_error = None
    return model


def save_model(model: Model) -> Path:
    global _cache
    path = model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.as_dict(), indent=2))
    _cache = None
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


def _latest_labels(db: Session) -> list[tuple[PairLabel, Pair]]:
    """Every labelled pair with its latest answer and its current pair row. A
    pair labelled twice keeps its latest answer, so a reviewer who changes
    their mind is heard."""
    latest: dict[tuple[int, int], PairLabel] = {}
    for row in db.execute(select(PairLabel).order_by(PairLabel.id)).scalars():
        latest[(row.item_a, row.item_b)] = row
    pairs = _current_pairs(db, list(latest.values()))
    return [(row, pairs[row.id]) for row in latest.values() if row.id in pairs]


def labelled(db: Session) -> list[tuple[int, dict[str, float | None], bool, str]]:
    """Every label with its pair's features."""
    rows = _latest_labels(db)
    facts = item_facts(db, {p.item_a for _, p in rows} | {p.item_b for _, p in rows})
    out = []
    for row, pair in rows:
        x = pair_features(pair, facts)
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


def _matrix(rows: list[dict[str, float | None]], names: tuple[str, ...] | list[str]):
    """Rows keyed by name into a dense array in feature order. An unknown
    value takes its column's mean over the rows that have one, which is the
    same convention the model applies when it scores."""
    import numpy as np

    X = np.full((len(rows), len(names)), np.nan, dtype=float)
    for i, row in enumerate(rows):
        for j, name in enumerate(names):
            value = row.get(name)
            if value is not None:
                X[i, j] = value
    for j in range(X.shape[1]):
        column = X[:, j]
        known = column[~np.isnan(column)]
        column[np.isnan(column)] = known.mean() if len(known) else 0.0
    return X


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


def _pair_class(pair: Pair, facts: dict[int, ItemFacts]) -> str:
    a, b = facts.get(pair.item_a), facts.get(pair.item_b)
    if a is None or b is None:
        return "unknown"
    return a.class_code if a.class_code == b.class_code else "cross-class"


def evaluate_holdout(db: Session, model: Model) -> dict:
    """The model against the held-out split, beside the pipeline's own score.

    Same pairs, same truth, two rankings: does the reviewer-trained model
    separate duplicates from non-duplicates better than the hand-tuned
    confidence? Reported as AUC so the threshold is not part of the answer,
    overall, in the grey band alone, and per class.
    """
    from sklearn.metrics import precision_score, recall_score, roc_auc_score

    truth = _truth(db, "holdout")
    pairs = [
        pair
        for pair in db.execute(
            select(Pair).where(Pair.evidence_json != "{}").order_by(Pair.id)
        ).scalars()
        if pair.item_a in truth and pair.item_b in truth
    ]
    facts = item_facts(db, {p.item_a for p in pairs} | {p.item_b for p in pairs})
    y, model_scores, pipeline_scores, bands, classes = [], [], [], [], []
    for pair in pairs:
        x = pair_features(pair, facts)
        if x is None:
            continue
        y.append(1 if truth[pair.item_a] == truth[pair.item_b] else 0)
        model_scores.append(model.probability(x))
        pipeline_scores.append(pair.confidence)
        bands.append(pair.band)
        classes.append(_pair_class(pair, facts))

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

    per_class = []
    for class_code in sorted(set(classes)):
        mask = [c == class_code for c in classes]
        class_model, class_pipeline, n_class = auc(mask)
        ys = [v for v, m in zip(y, mask, strict=True) if m]
        predicted = [1 if v >= 0.5 else 0 for v, m in zip(model_scores, mask, strict=True) if m]
        per_class.append(
            {
                "class_code": class_code,
                "pairs": n_class,
                "positives": sum(ys),
                "model_auc": class_model,
                "pipeline_auc": class_pipeline,
                "precision": round(float(precision_score(ys, predicted, zero_division=0)), 4),
                "recall": round(float(recall_score(ys, predicted, zero_division=0)), 4),
            }
        )
    return {
        "pairs": n,
        "positives": sum(y),
        "model_auc": overall_model,
        "pipeline_auc": overall_pipeline,
        "grey_pairs": n_grey,
        "grey_model_auc": grey_model,
        "grey_pipeline_auc": grey_pipeline,
        "per_class": per_class,
    }


class NotEnoughLabels(ValueError):
    pass


def _enough(rows) -> bool:
    y = [1 if label else 0 for _, _, label, _ in rows]
    return len(rows) >= MIN_LABELS and min(sum(y), len(y) - sum(y)) >= MIN_PER_CLASS


def training_rows(db: Session) -> tuple[list, str]:
    """The labels a model should learn from, and which set that is.

    Simulated labels exist so the demo has a model on day one. Once people's
    own decisions outnumber them and are enough to train on by themselves,
    the simulated ones are left out: a model judged on reviewers should be a
    model taught by reviewers, and the generator's answers stop shaping it.
    Until then every label counts, and the model says so (`trained_on`).
    """
    rows = labelled(db)
    reviewer = [row for row in rows if row[3] == SOURCE_REVIEWER]
    simulated = len(rows) - len(reviewer)
    if len(reviewer) > simulated and _enough(reviewer):
        return reviewer, SOURCE_REVIEWER
    return rows, "all"


def fit(db: Session) -> Model:
    """Fit a model on the training labels; nothing is saved and nothing is
    measured against the held-out split. `train` and the retrain loop build
    on this."""
    rows, trained_on = training_rows(db)
    y = [1 if label else 0 for _, _, label, _ in rows]
    n_pos, n_neg = sum(y), len(y) - sum(y)
    if not _enough(rows):
        raise NotEnoughLabels(
            f"{len(rows)} labelled pairs ({n_pos} yes, {n_neg} no); training needs at least "
            f"{MIN_LABELS} with {MIN_PER_CLASS} of each. Decide more pairs in the Workbench."
        )
    X = _matrix([x for _, x, _, _ in rows], FEATURES)
    cv = _cross_validate(X, y)
    mean, scale, coef, intercept = _fit(X, y)
    by_source: dict[str, int] = {}
    for _, _, _, source in rows:
        by_source[source] = by_source.get(source, 0) + 1
    return Model(
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
        trained_on=trained_on,
    )


#: Fewer reviewer labels than this and a confusion matrix is noise; the page
#: shows nothing rather than a 3×3 that a judge would read as a result.
CONFUSION_MIN_LABELS = 20


def reviewer_confusion(db: Session) -> dict | None:
    """How the model does on people's own decisions, out of sample.

    Cross-validated predictions over the reviewer labels alone (five folds,
    each label predicted by a model that never saw it), read as a confusion
    matrix at 0.5: duplicates the model agreed were duplicates, the ones it
    would have called distinct, and the other way round. None until there
    are enough real labels with both answers present; simulated labels never
    enter it, since they are the generator's decisions, not people's.
    """
    import numpy as np
    from sklearn.model_selection import StratifiedKFold

    rows = [row for row in labelled(db) if row[3] == SOURCE_REVIEWER]
    y = np.asarray([1 if label else 0 for _, _, label, _ in rows], dtype=int)
    if len(rows) < CONFUSION_MIN_LABELS or min(int(y.sum()), int(len(y) - y.sum())) < CV_FOLDS:
        return None
    X = np.asarray(_matrix([x for _, x, _, _ in rows], FEATURES), dtype=float)
    predicted = np.zeros(len(y), dtype=int)
    for train_idx, test_idx in StratifiedKFold(CV_FOLDS, shuffle=True, random_state=0).split(X, y):
        mean, scale, coef, intercept = _fit(X[train_idx], y[train_idx])
        model = Model(list(FEATURES), mean, scale, coef, intercept, "", 0)
        predicted[test_idx] = [
            1 if model.probability(list(row)) >= 0.5 else 0 for row in X[test_idx]
        ]
    tp = int(((predicted == 1) & (y == 1)).sum())
    tn = int(((predicted == 0) & (y == 0)).sum())
    fp = int(((predicted == 1) & (y == 0)).sum())
    fn = int(((predicted == 0) & (y == 1)).sum())
    return {
        "labels": int(len(y)),
        "folds": CV_FOLDS,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "agreement": round((tp + tn) / len(y), 4),
        "note": (
            "Reviewer labels only, each predicted by a model that never saw it "
            f"({CV_FOLDS} folds). Rows are what the reviewer said; columns are what the "
            "model would have said at 0.5."
        ),
    }


def train(db: Session) -> Model:
    """Manual training: fit, measure, and save whatever came out. The person
    asking has decided; the attempt is still written to the history."""
    model = fit(db)
    model.holdout = evaluate_holdout(db, model)
    champion = load_model()
    save_model(model)
    _record_attempt(
        _attempt_entry(
            model,
            trigger="manual",
            promoted=True,
            reason="manual training always promotes",
            champion_auc=champion.holdout_auc() if champion else None,
        )
    )
    return model


# --------------------------------------------------------------------------
# Champion / challenger
# --------------------------------------------------------------------------

_retrain_lock = threading.Lock()
_retrain_thread: threading.Thread | None = None
#: The newest label the last recorded attempt had seen, promoted or not, so a
#: kept challenger does not make the very next decision retrain again.
_attempt_watermark: int | None = None


def _attempt_entry(
    model: Model, trigger: str, promoted: bool, reason: str, champion_auc: float | None
) -> dict:
    holdout = model.holdout or {}
    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "trigger": trigger,
        "n_labels": model.n_labels,
        "labels": model.labels,
        "cv_auc": model.cv.get("auc"),
        "holdout_auc": holdout.get("model_auc"),
        "grey_auc": holdout.get("grey_model_auc"),
        "holdout_pairs": holdout.get("pairs"),
        "champion_auc": champion_auc,
        "promoted": promoted,
        "reason": reason,
        "last_label_id": model.last_label_id,
        "weights": model.weights() if promoted else None,
    }


def _record_attempt(entry: dict) -> None:
    global _attempt_watermark
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    _attempt_watermark = max(_attempt_watermark or 0, int(entry.get("last_label_id") or 0))


def history(limit: int = 20) -> list[dict]:
    """The last attempts, newest first; a line that will not parse is skipped."""
    path = history_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(entries[-limit:])) if limit else list(reversed(entries))


def forget_history() -> None:
    global _attempt_watermark
    _attempt_watermark = None
    path = history_path()
    if path.exists():
        path.unlink()


def _watermark(champion: Model | None) -> int:
    global _attempt_watermark
    if _attempt_watermark is None:
        last = history(limit=1)
        _attempt_watermark = int(last[0].get("last_label_id") or 0) if last else 0
    return max(champion.last_label_id if champion else 0, _attempt_watermark)


def auto_retrain_status(db: Session) -> dict:
    """Is a retrain due? Only reviewer labels count: the simulator can add
    four hundred in a second and would otherwise retrain on its own echo."""
    settings = get_settings()
    since = (
        db.execute(
            select(func.count(PairLabel.id)).where(
                PairLabel.source == SOURCE_REVIEWER, PairLabel.id > _watermark(load_model())
            )
        ).scalar()
        or 0
    )
    every = max(1, int(settings.saman_retrain_every))
    return {
        "enabled": bool(settings.saman_auto_retrain),
        "every": every,
        "labels_since": since,
        "due": bool(settings.saman_auto_retrain) and since >= every,
        "running": _retrain_lock.locked(),
    }


def _champion_auc(db: Session, champion: Model | None, challenger_holdout: dict) -> float | None:
    """The champion's held-out AUC on the same pairs the challenger was
    measured on. Its stored number is reused when the held-out set has not
    changed size since; otherwise it is measured again, so a pipeline rerun
    does not let a stale number defend the title."""
    if champion is None:
        return None
    stored = champion.holdout or {}
    if stored.get("model_auc") is not None and stored.get("pairs") == challenger_holdout.get(
        "pairs"
    ):
        return stored["model_auc"]
    return evaluate_holdout(db, champion).get("model_auc")


def _retrain(db: Session, trigger: str) -> dict:
    from . import audit

    champion = load_model()
    try:
        challenger = fit(db)
    except NotEnoughLabels as exc:
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "trigger": trigger,
            "n_labels": None,
            "labels": label_counts(db),
            "cv_auc": None,
            "holdout_auc": None,
            "grey_auc": None,
            "holdout_pairs": None,
            "champion_auc": champion.holdout_auc() if champion else None,
            "promoted": False,
            "reason": str(exc),
            "last_label_id": db.execute(select(func.max(PairLabel.id))).scalar() or 0,
            "weights": None,
        }
        _record_attempt(entry)
        audit.record(db, action="model.kept", entity="model:pairwise", payload=entry, user="system")
        return entry

    challenger.holdout = evaluate_holdout(db, challenger)
    champion_auc = _champion_auc(db, champion, challenger.holdout)
    challenger_auc = challenger.holdout_auc()
    if challenger_auc is None:
        promoted = False
        reason = "held-out split has no pairs with both outcomes; nothing to measure"
    elif challenger_auc < 0.5:
        promoted, reason = False, f"challenger held-out AUC {challenger_auc} is below chance"
    elif champion is None or champion_auc is None:
        promoted, reason = True, "no champion to beat"
    elif challenger_auc >= champion_auc - PROMOTION_TOLERANCE:
        promoted, reason = (
            True,
            f"challenger {challenger_auc} vs champion {champion_auc}: "
            f"not worse by more than {PROMOTION_TOLERANCE}",
        )
    else:
        promoted, reason = (
            False,
            f"challenger {challenger_auc} vs champion {champion_auc}: "
            f"worse by more than {PROMOTION_TOLERANCE}, champion kept",
        )
    if promoted:
        save_model(challenger)
    entry = _attempt_entry(challenger, trigger, promoted, reason, champion_auc)
    _record_attempt(entry)
    audit.record(
        db,
        action="model.retrained" if promoted else "model.kept",
        entity="model:pairwise",
        payload=entry,
        user="system",
    )
    return entry


def maybe_retrain(db: Session | None = None, trigger: str = "auto") -> dict | None:
    """One champion/challenger round. Returns the recorded attempt, or a note
    that another round was already running. With no session, opens one: the
    caller is usually a background thread."""
    if not _retrain_lock.acquire(blocking=False):
        return {"skipped": "a retrain is already running"}
    try:
        if db is not None:
            return _retrain(db, trigger)
        from .db import SessionLocal

        with SessionLocal() as own:
            return _retrain(own, trigger)
    except Exception:
        log.exception("pairwise retrain failed")
        return None
    finally:
        _retrain_lock.release()


def schedule_retrain(db: Session) -> threading.Thread | None:
    """After a reviewer's decision: if enough have accumulated, retrain in a
    background thread. Never raises; the decision is already committed and
    is not this function's to spoil."""
    global _retrain_thread
    try:
        state = auto_retrain_status(db)
    except Exception:
        log.exception("could not check whether a retrain is due")
        return None
    if not state["due"] or state["running"]:
        return None
    thread = threading.Thread(
        target=maybe_retrain, kwargs={"trigger": "auto"}, name="saman-retrain", daemon=True
    )
    _retrain_thread = thread
    thread.start()
    return thread


def wait_for_retrain(timeout: float = 60.0) -> None:
    """Block until the last scheduled retrain finishes (tests, shutdown)."""
    thread = _retrain_thread
    if thread is not None:
        thread.join(timeout)


# --------------------------------------------------------------------------
# Threshold suggestions: computed, shown, never applied
# --------------------------------------------------------------------------


def suggest_thresholds(db: Session, min_labels: int = SUGGESTION_MIN_LABELS) -> dict:
    """Per class, the pipeline-confidence cut that would maximise F1 on the
    labelled pairs, beside the current T_HIGH and the precision each gives.

    These are suggestions. Nothing here writes to match.py: thresholds were
    tuned on the tuning split and frozen (§0.6), and a registrar changes them
    deliberately, with the number in front of them and a reason on record.
    """
    from .match import T_HIGH

    rows = _latest_labels(db)
    facts = item_facts(db, {p.item_a for _, p in rows} | {p.item_b for _, p in rows})
    by_class: dict[str, list[tuple[float, int]]] = {}
    for row, pair in rows:
        if not pair.evidence_json or pair.evidence_json == "{}":
            continue
        by_class.setdefault(_pair_class(pair, facts), []).append(
            (float(pair.confidence), 1 if row.label else 0)
        )

    def prf(points: list[tuple[float, int]], cut: float) -> tuple[float, float, float]:
        tp = sum(1 for c, y in points if c >= cut and y)
        fp = sum(1 for c, y in points if c >= cut and not y)
        fn = sum(1 for c, y in points if c < cut and y)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return precision, recall, f1

    classes = []
    for class_code, points in sorted(by_class.items()):
        positives = sum(y for _, y in points)
        if len(points) < min_labels or positives == 0 or positives == len(points):
            continue
        best_cut, best = None, (0.0, 0.0, -1.0)
        for cut in sorted({c for c, _ in points}):
            candidate = prf(points, cut)
            if candidate[2] > best[2]:
                best_cut, best = cut, candidate
        at_current = prf(points, T_HIGH)
        classes.append(
            {
                "class_code": class_code,
                "labelled_pairs": len(points),
                "positives": positives,
                "suggested_t_high": round(best_cut, 4),
                "suggested_precision": round(best[0], 4),
                "suggested_recall": round(best[1], 4),
                "suggested_f1": round(best[2], 4),
                "current_t_high": T_HIGH,
                "current_precision": round(at_current[0], 4),
                "current_recall": round(at_current[1], 4),
                "applied": False,
            }
        )
    return {
        "applied": False,
        "current_t_high": T_HIGH,
        "min_labels": min_labels,
        "classes": classes,
        "note": (
            "Suggested, not applied. Thresholds are tuned on the tuning split and frozen in "
            "match.py; a registrar changes them deliberately, with these numbers in view."
        ),
    }


# --------------------------------------------------------------------------
# Serving
# --------------------------------------------------------------------------


def score(
    pair: Pair,
    model: Model | None = None,
    db: Session | None = None,
    facts: dict[int, ItemFacts] | None = None,
) -> dict | None:
    """What the model thinks of one pair, for the card. None without a model
    or without evidence. Pass `facts` for a batch, or `db` to look the two
    items up; without either the item-derived features take their means."""
    model = model or load_model()
    if model is None:
        return None
    if facts is None and db is not None:
        facts = item_facts(db, (pair.item_a, pair.item_b))
    x = pair_features(pair, facts)
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
    if model is None and _load_error:
        note = f"The saved model was refused: {_load_error}. Train now to replace it."
    elif model is None:
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
                "trained_on": model.trained_on,
                "path": str(model_path()),
            }
            if model
            else None
        ),
        "labels": counts,
        # How the model does on people's own decisions; None while there are
        # too few to say. Simulated labels never enter it.
        "reviewer_confusion": reviewer_confusion(db),
        "next_training_uses": training_rows(db)[1],
        "labels_since_training": since,
        "min_labels": MIN_LABELS,
        "decides": False,
        "note": note,
        "load_error": _load_error,
        "auto_retrain": auto_retrain_status(db),
        "history": history(20),
        "suggestions": suggest_thresholds(db),
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
