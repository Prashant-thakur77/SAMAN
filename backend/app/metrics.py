"""Evaluation — spec §0.6.

Rules this module exists to enforce:

* **Held-out only.** Thresholds are tuned on the 60% tuning split; every number
  reported here comes from the 40% held-out split. A pair counts only when both
  of its items belong to held-out truth groups.
* **Never one averaged number.** Pairwise precision/recall/F1 can look superb
  while clusters are badly over-merged, so cluster-level B-cubed is reported
  beside it, together with blocking recall, veto precision, a per-class
  breakdown that names the worst class explicitly, and a naive baseline so the
  lift over "exact text match" is visible rather than implied.

The truth tables are read only here. Nothing in the pipeline may consult them.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .capabilities import detect
from .match import T_HIGH, T_LOW
from .models import (
    Cluster,
    ClusterMember,
    Item,
    MatchRun,
    Pair,
    TruthEquivalence,
    TruthGroup,
    TruthTrap,
)

HOLDOUT = "holdout"

#: The M3 gate (spec §8).
TARGETS = {
    "duplicate_precision": 0.92,
    "duplicate_recall": 0.80,
    "blocking_recall": 0.97,
    "veto_precision": 0.98,
}


def _choose2(n: int) -> int:
    return n * (n - 1) // 2


@dataclass
class Pairwise:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "true_positives": self.tp,
            "false_positives": self.fp,
            "false_negatives": self.fn,
        }


def pairwise(
    predicted: dict[int, int], truth: dict[int, str], subset: set[int]
) -> Pairwise:
    """Pairwise P/R over `subset`, without materializing any pair.

    Counting intersections of predicted clusters with truth groups is O(n);
    enumerating the pairs themselves would be O(n^2) and pointless.
    """
    by_cluster: dict[int, list[int]] = defaultdict(list)
    by_group: dict[str, list[int]] = defaultdict(list)
    for item in subset:
        if item in predicted:
            by_cluster[predicted[item]].append(item)
        if item in truth:
            by_group[truth[item]].append(item)

    predicted_positives = sum(_choose2(len(v)) for v in by_cluster.values())
    actual_positives = sum(_choose2(len(v)) for v in by_group.values())

    tp = 0
    for members in by_cluster.values():
        counts = Counter(truth[m] for m in members if m in truth)
        tp += sum(_choose2(n) for n in counts.values())

    return Pairwise(tp=tp, fp=predicted_positives - tp, fn=actual_positives - tp)


def bcubed(
    predicted: dict[int, int], truth: dict[int, str], subset: set[int]
) -> dict:
    """Cluster-level B-cubed precision and recall.

    Pairwise metrics are dominated by large clusters; B-cubed weights every
    item equally, which is what exposes a single catastrophic over-merge.
    """
    by_cluster: dict[int, set[int]] = defaultdict(set)
    by_group: dict[str, set[int]] = defaultdict(set)
    for item in subset:
        if item in predicted:
            by_cluster[predicted[item]].add(item)
        if item in truth:
            by_group[truth[item]].add(item)

    precision_sum = recall_sum = 0.0
    counted = 0
    for item in subset:
        if item not in predicted or item not in truth:
            continue
        cluster = by_cluster[predicted[item]]
        group = by_group[truth[item]]
        common = len(cluster & group)
        precision_sum += common / len(cluster)
        recall_sum += common / len(group)
        counted += 1

    if not counted:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "items": 0}

    p, r = precision_sum / counted, recall_sum / counted
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(2 * p * r / (p + r), 4) if (p + r) else 0.0,
        "items": counted,
    }


@dataclass
class Snapshot:
    """Everything the metrics need, read once."""

    item_to_group: dict[int, str] = field(default_factory=dict)
    item_to_split: dict[int, str] = field(default_factory=dict)
    item_to_class: dict[int, str] = field(default_factory=dict)
    item_to_hash: dict[int, str] = field(default_factory=dict)
    raw_to_item: dict[int, int] = field(default_factory=dict)
    predicted: dict[int, int] = field(default_factory=dict)
    holdout: set[int] = field(default_factory=set)


def _load(db: Session) -> Snapshot:
    snap = Snapshot()

    for item_id, raw_id, class_code, norm_hash in db.execute(
        select(Item.id, Item.raw_item_id, Item.class_code, Item.norm_hash)
    ).all():
        snap.raw_to_item[raw_id] = item_id
        snap.item_to_class[item_id] = class_code
        snap.item_to_hash[item_id] = norm_hash

    for raw_id, group_id, split in db.execute(
        select(TruthGroup.raw_item_id, TruthGroup.group_id, TruthGroup.split)
    ).all():
        item_id = snap.raw_to_item.get(raw_id)
        if item_id is None:
            continue
        snap.item_to_group[item_id] = group_id
        snap.item_to_split[item_id] = split
        if split == HOLDOUT:
            snap.holdout.add(item_id)

    for cluster_id, item_id in db.execute(
        select(ClusterMember.cluster_id, ClusterMember.item_id)
    ).all():
        snap.predicted[item_id] = cluster_id

    return snap


def _baseline_exact_text(snap: Snapshot) -> dict:
    """Naive baseline: cluster by identical normalized text.

    Reported alongside SAMAN so the lift is visible rather than asserted.
    """
    by_hash: dict[str, int] = {}
    predicted: dict[int, int] = {}
    for item_id in snap.holdout:
        digest = snap.item_to_hash.get(item_id)
        if digest is None:
            continue
        predicted[item_id] = by_hash.setdefault(digest, len(by_hash))
    return pairwise(predicted, snap.item_to_group, snap.holdout).as_dict()


def _per_class(snap: Snapshot) -> tuple[list[dict], str | None]:
    """Pairwise metrics per class, and the worst-performing class by name."""
    groups_by_class: dict[str, set[int]] = defaultdict(set)
    for item_id in snap.holdout:
        groups_by_class[snap.item_to_class.get(item_id, "unclassified")].add(item_id)

    rows: list[dict] = []
    for class_code, items in sorted(groups_by_class.items()):
        result = pairwise(snap.predicted, snap.item_to_group, items)
        if result.tp + result.fn == 0:
            continue  # no duplicate pairs to find in this class on held-out
        rows.append({"class_code": class_code, "items": len(items), **result.as_dict()})

    worst = min(rows, key=lambda r: r["f1"])["class_code"] if rows else None
    return sorted(rows, key=lambda r: r["f1"]), worst


def _veto_metrics(db: Session, snap: Snapshot) -> dict:
    """How the planted §2A traps were handled, on held-out only."""
    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    refusals_correct = refusals_total = 0
    inband_correct = inband_total = 0

    for raw_a, raw_b, kind, expect in db.execute(
        select(
            TruthTrap.raw_item_a,
            TruthTrap.raw_item_b,
            TruthTrap.trap_kind,
            TruthTrap.expect_duplicate,
        ).where(TruthTrap.split == HOLDOUT)
    ).all():
        a = snap.raw_to_item.get(raw_a)
        b = snap.raw_to_item.get(raw_b)
        if a is None or b is None:
            continue
        cluster_a = snap.predicted.get(a)
        merged = cluster_a is not None and cluster_a == snap.predicted.get(b)
        correct = merged if expect else not merged

        by_kind[kind]["total"] += 1
        by_kind[kind]["correct"] += int(correct)
        if expect:
            inband_total += 1
            inband_correct += int(correct)
        else:
            refusals_total += 1
            refusals_correct += int(correct)

    return {
        "precision": round(refusals_correct / refusals_total, 4) if refusals_total else 0.0,
        "traps_refused": refusals_correct,
        "traps_total": refusals_total,
        "in_band_accuracy": round(inband_correct / inband_total, 4) if inband_total else None,
        "in_band_total": inband_total,
        "by_kind": {
            kind: {
                **counts,
                "accuracy": round(counts["correct"] / counts["total"], 4)
                if counts["total"]
                else 0.0,
            }
            for kind, counts in sorted(by_kind.items())
        },
    }


def _equivalence_metrics(db: Session, snap: Snapshot) -> dict:
    """Directed equivalence (§2B), measured on held-out pairs.

    Ground truth is recorded once per *product* pair and expanded here across
    every rendering of those products, using truth_group. Recording it per
    rendering would multiply the table for no added information.
    """
    from .models import Relation

    predicted_rows = db.execute(
        select(Relation.item_a, Relation.item_b, Relation.direction, Relation.basis).where(
            Relation.rel_type.in_(("equivalent", "supersedes"))
        )
    ).all()

    truth_rows = db.execute(
        select(
            TruthEquivalence.raw_item_a,
            TruthEquivalence.raw_item_b,
            TruthEquivalence.direction,
        )
    ).all()

    items_by_group: dict[str, list[int]] = defaultdict(list)
    for item_id, group_id in snap.item_to_group.items():
        if item_id in snap.holdout:
            items_by_group[group_id].append(item_id)

    def key(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    truth: dict[tuple[int, int], str] = {}
    for raw_a, raw_b, direction in truth_rows:
        a = snap.raw_to_item.get(raw_a)
        b = snap.raw_to_item.get(raw_b)
        if a is None or b is None:
            continue
        group_a = snap.item_to_group.get(a)
        group_b = snap.item_to_group.get(b)
        if group_a is None or group_b is None or group_a == group_b:
            continue
        for item_a in items_by_group.get(group_a, ()):
            for item_b in items_by_group.get(group_b, ()):
                # `direction` is stated from product A to product B; flip it if
                # storing the pair the other way round.
                truth[key(item_a, item_b)] = (
                    direction if item_a < item_b else _flip(direction)
                )

    if not predicted_rows:
        return {
            "status": "not_built",
            "note": "The equivalence engine lands in M3.5; truth is seeded and ready.",
            "truth_pairs_holdout": len(truth),
        }

    predicted: dict[tuple[int, int], str] = {}
    basis_counts: Counter[str] = Counter()
    for a, b, direction, basis in predicted_rows:
        if a not in snap.holdout or b not in snap.holdout:
            continue
        predicted[key(a, b)] = direction if a < b else _flip(direction)
        basis_counts[basis] += 1

    # The equivalence analogue of blocking recall: a pair the matcher never
    # emitted is one the relation engine was never asked about, so reporting
    # recall without it would leave the ceiling invisible (§0.6).
    considered = {
        key(a, b)
        for a, b in db.execute(select(Pair.item_a, Pair.item_b)).all()
        if a in snap.holdout and b in snap.holdout
    }
    reachable = set(truth) & considered

    found = set(truth) & set(predicted)
    correct_direction = sum(1 for k in found if truth[k] == predicted[k])
    return {
        "status": "measured",
        "precision": round(len(found) / len(predicted), 4) if predicted else 0.0,
        "recall": round(len(found) / len(truth), 4) if truth else 0.0,
        "direction_accuracy": round(correct_direction / len(found), 4) if found else 0.0,
        "truth_pairs_holdout": len(truth),
        "predicted_pairs_holdout": len(predicted),
        "candidate_coverage": round(len(reachable) / len(truth), 4) if truth else 0.0,
        "recall_of_reachable": (
            round(len(found) / len(reachable), 4) if reachable else 0.0
        ),
        "by_basis": dict(basis_counts),
        "note": (
            "Equivalents keep distinct CNMCs; nothing here merges a cluster (§2B)."
        ),
    }


def _flip(direction: str) -> str:
    return {"a_to_b": "b_to_a", "b_to_a": "a_to_b"}.get(direction, direction)


def _automation(run_stats: dict, db: Session) -> dict:
    """Share of candidate pairs decided without a human (spec §7 KPI).

    Counted over every candidate the matcher saw, taken from the run record —
    not from the `pair` table, which deliberately keeps only decisions worth
    showing (accepted, vetoed, or awaiting review).
    """
    counts = Counter(run_stats.get("bands", {}))
    if not counts:
        counts = Counter(band for band, in db.execute(select(Pair.band)).all())
    total = sum(counts.values())
    auto = counts.get("high", 0) + counts.get("low", 0)
    return {
        "candidate_pairs_persisted": total,
        "auto_decided": auto,
        "needs_review": counts.get("grey", 0),
        "automation_rate": round(auto / total, 4) if total else 0.0,
        "by_band": dict(counts),
    }


def compute_metrics(db: Session) -> dict:
    """The full §0.6 report."""
    snap = _load(db)

    run = db.execute(select(MatchRun).order_by(desc(MatchRun.id)).limit(1)).scalar_one_or_none()
    run_stats = json.loads(run.stats_json) if run else {}
    blocking = run_stats.get("blocking", {})

    duplicate = pairwise(snap.predicted, snap.item_to_group, snap.holdout)
    per_class, worst_class = _per_class(snap)
    veto = _veto_metrics(db, snap)
    blocking_recall = blocking.get("recall_holdout")

    gate = {
        "duplicate_precision": duplicate.precision,
        "duplicate_recall": duplicate.recall,
        "blocking_recall": blocking_recall,
        "veto_precision": veto["precision"],
    }

    return {
        "split": HOLDOUT,
        "note": (
            "Thresholds are tuned on the 60% tuning split; every number below is "
            "measured on the 40% held-out split."
        ),
        "counts": {
            "items_total": len(snap.item_to_class),
            "items_holdout": len(snap.holdout),
            "clusters": db.execute(select(Cluster.id)).scalars().all().__len__(),
            "truth_groups_holdout": len(
                {
                    snap.item_to_group[i]
                    for i in snap.holdout
                    if i in snap.item_to_group
                }
            ),
        },
        "duplicate": {
            "pairwise": duplicate.as_dict(),
            "bcubed": bcubed(snap.predicted, snap.item_to_group, snap.holdout),
        },
        "baseline_exact_text": {
            "pairwise": _baseline_exact_text(snap),
            "note": "Naive: cluster rows with byte-identical normalized text.",
        },
        "blocking": {
            "recall": blocking_recall,
            "target": TARGETS["blocking_recall"],
            "stats": blocking,
        },
        "veto": {**veto, "target": TARGETS["veto_precision"]},
        "equivalence": _equivalence_metrics(db, snap),
        "per_class": per_class,
        "worst_class": worst_class,
        "automation": _automation(run_stats, db),
        # Which engine actually decided, not which is installed. A report that
        # does not say what produced it is hard to trust.
        "engines": {
            "tier1_linkage": run_stats.get("linkage", {}).get("engine", "rapidfuzz"),
            "tier2_embedding": detect().embedding_mode,
            "tier3_adjudication": detect().llm_mode,
        },
        "thresholds": {"high": T_HIGH, "low": T_LOW},
        "gate": {
            name: {
                "value": None if value is None else round(value, 4),
                "target": target,
                "pass": bool(value is not None and value >= target),
            }
            for name, target in TARGETS.items()
            for value in [gate[name]]
        },
        "gate_passed": all(
            gate[name] is not None and gate[name] >= target
            for name, target in TARGETS.items()
        ),
    }


def measure_blocking_recall(db: Session, candidates: set[tuple[int, int]]) -> dict:
    """What share of true duplicate pairs survived into candidate generation?

    Spec §2A.1 grades this separately, because a pair the blocker never emitted
    is invisible to precision and to matcher recall alike — the matcher is never
    even asked about it.

    This is the one evaluation measurement that has to happen inside the
    pipeline run, while the candidate set is still in memory. It reads the truth
    tables, which is why it lives here in `metrics` rather than in `match`:
    nothing that makes a matching *decision* may consult ground truth.
    """
    raw_to_item = dict(db.execute(select(Item.raw_item_id, Item.id)).all())

    by_group: dict[tuple[str, str], list[int]] = defaultdict(list)
    for raw_id, group_id, split in db.execute(
        select(TruthGroup.raw_item_id, TruthGroup.group_id, TruthGroup.split)
    ).all():
        item_id = raw_to_item.get(raw_id)
        if item_id is not None:
            by_group[(group_id, split)].append(item_id)

    totals = {"all": 0, HOLDOUT: 0, "tuning": 0}
    found = {"all": 0, HOLDOUT: 0, "tuning": 0}
    missed_examples: list[tuple[int, int]] = []

    for (_group_id, split), members in by_group.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                pair = (a, b) if a < b else (b, a)
                hit = pair in candidates
                totals["all"] += 1
                found["all"] += int(hit)
                bucket = HOLDOUT if split == HOLDOUT else "tuning"
                totals[bucket] += 1
                found[bucket] += int(hit)
                if not hit and len(missed_examples) < 20:
                    missed_examples.append(pair)

    return {
        "recall_all": round(found["all"] / totals["all"], 4) if totals["all"] else 0.0,
        "recall_holdout": round(found[HOLDOUT] / totals[HOLDOUT], 4) if totals[HOLDOUT] else 0.0,
        # Reported so a configuration choice can be justified on tuning data
        # alone; the held-out figure is the one reported, never the one tuned on.
        "recall_tuning": round(found["tuning"] / totals["tuning"], 4) if totals["tuning"] else 0.0,
        "true_pairs_all": totals["all"],
        "true_pairs_holdout": totals[HOLDOUT],
        "missed_all": totals["all"] - found["all"],
        "missed_examples": missed_examples,
    }
