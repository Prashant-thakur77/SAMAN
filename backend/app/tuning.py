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

from collections import Counter, defaultdict
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


def sweep(db: Session) -> tuple[list[SweepRow], float]:
    """Evaluate every candidate threshold on the tuning split."""
    items, truth, tuning_items, edges = _load(db)
    attrs_by_id = {i: v["attrs"] for i, v in items.items()}
    class_by_id = {i: v["class_code"] for i, v in items.items()}
    mpn_by_id = {i: v["mpn"] for i, v in items.items()}
    all_ids = list(items)

    rows: list[SweepRow] = []
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
        rows.append(
            SweepRow(threshold, result.precision, result.recall, result.f1, cluster_id)
        )

    eligible = [r for r in rows if r.precision >= PRECISION_FLOOR]
    best = max(eligible or rows, key=lambda r: (r.f1, r.recall))
    return rows, best.threshold


def report(db: Session) -> dict:
    rows, chosen = sweep(db)
    return {
        "split": TUNING,
        "precision_floor": PRECISION_FLOOR,
        "sweep": [r.as_dict() for r in rows],
        "recommended_T_HIGH": chosen,
        "note": (
            "Chosen on the tuning split only. Freeze this value in match.T_HIGH "
            "and report held-out metrics from GET /api/metrics."
        ),
    }
