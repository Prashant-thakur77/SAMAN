"""Threshold tuning — spec §0.6.

Thresholds are chosen here, on the **tuning split only**, and then frozen into
`match.py`. Nothing in this module may read the held-out split: choosing a
threshold by its held-out score is how an honest-looking evaluation becomes a
dishonest one.

Run it with::

    python -m app.cli tune

It prints the sweep so the choice is auditable, and names the value to freeze.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .cluster import build_clusters, refine_clusters
from .metrics import Pairwise, pairwise
from .models import Item, Pair, TruthGroup

TUNING = "tuning"

#: Sweep range for the auto-accept threshold.
SWEEP = [round(0.40 + 0.02 * i, 2) for i in range(28)]

#: Precision floor used when choosing: the §8 gate is 0.92, and a threshold
#: chosen exactly at the gate on tuning data would sit on the wrong side of it
#: as often as not on held-out data.
PRECISION_FLOOR = 0.94


@dataclass
class SweepRow:
    threshold: float
    precision: float
    recall: float
    f1: float
    clusters: int

    def as_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "clusters": self.clusters,
        }


def _load(db: Session):
    import json

    items = {
        item_id: {
            "attrs": json.loads(attrs_json or "{}"),
            "class_code": class_code,
            "mpn": mpn,
        }
        for item_id, class_code, attrs_json, mpn in db.execute(
            select(Item.id, Item.class_code, Item.attrs_json, Item.mpn_norm)
        ).all()
    }

    raw_to_item = dict(db.execute(select(Item.raw_item_id, Item.id)).all())
    truth: dict[int, str] = {}
    tuning_items: set[int] = set()
    for raw_id, group_id, split in db.execute(
        select(TruthGroup.raw_item_id, TruthGroup.group_id, TruthGroup.split)
    ).all():
        item_id = raw_to_item.get(raw_id)
        if item_id is None:
            continue
        truth[item_id] = group_id
        if split == TUNING:
            tuning_items.add(item_id)

    # Only pairs that were not refused can ever become an edge.
    edges = db.execute(
        select(Pair.item_a, Pair.item_b, Pair.confidence).where(
            Pair.verdict.in_(("duplicate", "review"))
        )
    ).all()
    return items, truth, tuning_items, edges


#: A class needs this many tuning-split items before its own sweep means
#: anything; below it the per-class row is reported but not recommended.
CLASS_MIN_ITEMS = 40


def sweep(db: Session) -> tuple[list[SweepRow], float]:
    """Evaluate every candidate threshold on the tuning split."""
    rows, _by_class, chosen = _sweep(db)
    return rows, chosen


def _sweep(db: Session) -> tuple[list[SweepRow], dict[str, list[SweepRow]], float]:
    """The sweep, overall and per class, from one pass over the thresholds.

    Per class means: the same clustering at each threshold, scored over the
    tuning items of that class alone. Bearings and chemicals do not share one
    best cut, and this is how much a per-class cut would buy, measured before
    anyone builds it.
    """
    items, truth, tuning_items, edges = _load(db)
    attrs_by_id = {i: v["attrs"] for i, v in items.items()}
    class_by_id = {i: v["class_code"] for i, v in items.items()}
    mpn_by_id = {i: v["mpn"] for i, v in items.items()}
    all_ids = list(items)
    tuning_by_class: dict[str, set[int]] = {}
    for item in tuning_items:
        tuning_by_class.setdefault(class_by_id.get(item, "unclassified"), set()).add(item)

    rows: list[SweepRow] = []
    by_class: dict[str, list[SweepRow]] = {c: [] for c in tuning_by_class}
    for threshold in SWEEP:
        accepted = [(a, b) for a, b, c in edges if c >= threshold]
        degree: Counter[int] = Counter()
        for a, b in accepted:
            degree[a] += 1
            degree[b] += 1

        groups = build_clusters(accepted, all_ids)
        predicted: dict[int, int] = {}
        cluster_id = 0
        for members in groups.values():
            for part in refine_clusters(members, attrs_by_id, class_by_id, mpn_by_id, degree):
                cluster_id += 1
                for item in part:
                    predicted[item] = cluster_id

        result: Pairwise = pairwise(predicted, truth, tuning_items)
        rows.append(SweepRow(threshold, result.precision, result.recall, result.f1, cluster_id))
        for class_code, subset in tuning_by_class.items():
            r = pairwise(predicted, truth, subset)
            clusters = len({predicted[i] for i in subset if i in predicted})
            by_class[class_code].append(SweepRow(threshold, r.precision, r.recall, r.f1, clusters))

    eligible = [r for r in rows if r.precision >= PRECISION_FLOOR]
    best = max(eligible or rows, key=lambda r: (r.f1, r.recall))
    return rows, by_class, best.threshold


def _best(rows: list[SweepRow]) -> SweepRow:
    eligible = [r for r in rows if r.precision >= PRECISION_FLOOR]
    return max(eligible or rows, key=lambda r: (r.f1, r.recall))


def report(db: Session) -> dict:
    rows, by_class, chosen = _sweep(db)
    items, _truth, tuning_items, _edges = _load(db)
    counts: Counter[str] = Counter(items[i]["class_code"] for i in tuning_items if i in items)
    at_global = {r.threshold: r for r in rows}
    per_class = []
    for class_code, class_rows in sorted(by_class.items()):
        own = _best(class_rows)
        at_chosen = next((r for r in class_rows if r.threshold == chosen), None)
        enough = counts.get(class_code, 0) >= CLASS_MIN_ITEMS
        per_class.append(
            {
                "class_code": class_code,
                "tuning_items": counts.get(class_code, 0),
                "enough_items": enough,
                "at_global": at_chosen.as_dict() if at_chosen else None,
                "own_best": own.as_dict(),
                "f1_gain": round(own.f1 - at_chosen.f1, 4) if at_chosen else None,
                "recall_gain": round(own.recall - at_chosen.recall, 4) if at_chosen else None,
            }
        )
    return {
        "split": TUNING,
        "precision_floor": PRECISION_FLOOR,
        "sweep": [r.as_dict() for r in rows],
        "recommended_T_HIGH": chosen,
        "global_at_recommended": at_global[chosen].as_dict(),
        "per_class": per_class,
        "class_min_items": CLASS_MIN_ITEMS,
        "note": (
            "Chosen on the tuning split only. Freeze this value in match.T_HIGH "
            "and report held-out metrics from GET /api/metrics. The per-class rows say "
            "what a class's own cut would buy over the global one, on the tuning split; "
            "they are a measurement, not a setting: one T_HIGH stays in force until a "
            "gain is worth a per-class rule and a registrar chooses it."
        ),
    }
