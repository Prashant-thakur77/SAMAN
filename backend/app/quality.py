"""Data quality by CPSE: the scorecard behind "improved material master data
quality" (SIH26099, expected impact).

The problem statement promises better data; this is how the promise is
measured. Every rate is computed from the tables the pipeline already keeps,
per CPSE, so a steward can see their own catalogue's weaknesses and the
registrar can see whose need the most work. Nothing here is a price, so the
scorecard needs no visibility scope.

The six rates, each in [0, 1]:

    classified   rows the classifier placed in a real class
    attributes   identity-critical attributes present, averaged over classified rows
    uom          rows with a canonical base unit
    mpn          rows carrying a manufacturer part number
    unique       1 - internal duplicates (two rows of the same CPSE in one cluster)
    active       1 - rows with no purchase and no stock movement in 24 months

The score is a weighted sum. The weights are stated in the response so the
number is never a mystery.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ClusterMember, Cpse, Item, PurchaseHistory, RawItem, Stock
from .taxonomy import UNCLASSIFIED, get_schema

WEIGHTS = {
    "classified": 0.25,
    "attributes": 0.25,
    "uom": 0.15,
    "mpn": 0.10,
    "unique": 0.15,
    "active": 0.10,
}
#: A row nobody has bought or moved in this long is a candidate for retirement,
#: and a catalogue full of them is a catalogue nobody is maintaining.
STALE_MONTHS = 24


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _rates(entry: dict) -> dict:
    items = entry["items"] or 1
    internal_duplicates = sum(n - 1 for n in entry["clusters"].values() if n > 1)
    rates = {
        "classified": entry["classified"] / items,
        "attributes": (entry["attr_sum"] / entry["attr_n"]) if entry["attr_n"] else 0.0,
        "uom": entry["uom"] / items,
        "mpn": entry["mpn"] / items,
        "unique": 1.0 - internal_duplicates / items,
        "active": 1.0 - entry["stale"] / items,
    }
    score = sum(WEIGHTS[k] * v for k, v in rates.items())
    return {
        "cpse": entry["cpse"],
        "name": entry["name"],
        "items": entry["items"],
        "internal_duplicates": internal_duplicates,
        "stale_rows": entry["stale"],
        "rates": {k: round(v, 4) for k, v in rates.items()},
        "score": round(score, 4),
    }


def scorecard(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    cutoff = today - timedelta(days=STALE_MONTHS * 30)

    rows = db.execute(
        select(
            Cpse.code,
            Cpse.name,
            Item.id,
            Item.class_code,
            Item.attrs_json,
            Item.uom_base,
            Item.mpn_norm,
        )
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .order_by(Cpse.code)
    ).all()
    cluster_of = dict(db.execute(select(ClusterMember.item_id, ClusterMember.cluster_id)).all())
    last_po = {
        item_id: _as_date(value)
        for item_id, value in db.execute(
            select(PurchaseHistory.item_id, func.max(PurchaseHistory.po_date)).group_by(
                PurchaseHistory.item_id
            )
        ).all()
    }
    last_move = {
        item_id: _as_date(value)
        for item_id, value in db.execute(
            select(Stock.item_id, func.max(Stock.last_movement_date)).group_by(Stock.item_id)
        ).all()
    }

    per: dict[str, dict] = {}
    for code, name, item_id, class_code, attrs_json, uom, mpn in rows:
        entry = per.setdefault(
            code,
            {
                "cpse": code,
                "name": name,
                "items": 0,
                "classified": 0,
                "attr_sum": 0.0,
                "attr_n": 0,
                "uom": 0,
                "mpn": 0,
                "stale": 0,
                "clusters": {},
            },
        )
        entry["items"] += 1
        if class_code and class_code != UNCLASSIFIED:
            entry["classified"] += 1
            identity = get_schema(class_code).identity_critical
            if identity:
                attrs = json.loads(attrs_json or "{}")
                present = sum(1 for a in identity if attrs.get(a.name) not in (None, ""))
                entry["attr_sum"] += present / len(identity)
                entry["attr_n"] += 1
        if uom:
            entry["uom"] += 1
        if mpn:
            entry["mpn"] += 1
        cluster = cluster_of.get(item_id)
        if cluster is not None:
            entry["clusters"][cluster] = entry["clusters"].get(cluster, 0) + 1
        bought = last_po.get(item_id)
        moved = last_move.get(item_id)
        if not ((bought and bought >= cutoff) or (moved and moved >= cutoff)):
            entry["stale"] += 1

    cpses = [_rates(entry) for entry in per.values()]

    # National: every row counted once, not an average of averages.
    national = {
        "cpse": "ALL",
        "name": "All CPSEs",
        "items": 0,
        "classified": 0,
        "attr_sum": 0.0,
        "attr_n": 0,
        "uom": 0,
        "mpn": 0,
        "stale": 0,
        "clusters": {},
    }
    for entry in per.values():
        for key in ("items", "classified", "attr_sum", "attr_n", "uom", "mpn", "stale"):
            national[key] += entry[key]
        # Internal duplicates stay internal: a cluster shared by two CPSEs is
        # the platform working, not a defect, so the clusters are keyed by CPSE.
        for cluster, n in entry["clusters"].items():
            national["clusters"][(entry["cpse"], cluster)] = n
    return {
        "weights": WEIGHTS,
        "stale_months": STALE_MONTHS,
        "cpses": cpses,
        "national": _rates(national) if national["items"] else None,
        "note": (
            "Six rates per catalogue, each 0 to 1, weighted into one score. Internal "
            "duplicates are two rows of the same CPSE in one cluster; a row is stale "
            f"after {STALE_MONTHS} months without a purchase or a stock movement."
        ),
    }
