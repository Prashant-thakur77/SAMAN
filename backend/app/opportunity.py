"""Commercial analytics over historical procurement — spec §6.8, §9A.

§9A is explicit that purchase history must be *used*, not merely stored, so
everything here reads `purchase_history` (the authoritative source for price
analytics per §4) rather than the point-in-time `raw_item.price` snapshot:

    joint tenders    items two or more CPSEs bought inside a rolling 12-month
                     window, with their combined volume and price spread
    price variance   the same material bought at different prices, normalized
                     to price per base unit so a box of 100 is not compared
                     with a single piece
    vendor overlap   several CPSEs buying one item from different vendors

Every savings figure states its assumption inline rather than presenting a
modelled number as a measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ClusterMember,
    Cnmc,
    Cpse,
    GoldenRecord,
    Item,
    PurchaseHistory,
    RawItem,
)
from .visibility import Scope, price_band

#: The demand-aggregation window (§9A).
WINDOW_MONTHS = 12

#: Share of an observed price spread assumed to be capturable at combined
#: volume. Stated in the response so no figure travels without its assumption.
DEFAULT_CAPTURE = 0.60


@dataclass
class Purchase:
    cluster_id: int
    cpse: str
    po_date: date
    qty: float
    unit_price: float
    pack_qty: float
    vendor: str

    @property
    def price_per_base_unit(self) -> float:
        """§2A.1 / §9A: a box of 100 is not comparable with a single piece."""
        return self.unit_price / max(self.pack_qty or 1.0, 1.0)

    @property
    def base_qty(self) -> float:
        return self.qty * max(self.pack_qty or 1.0, 1.0)


#: ABC by consumption value: the top of the ranked list that carries 70% of a
#: CPSE's annual spend is A, the next 20% is B, the long tail is C. Classic
#: Pareto cut-offs, stated here rather than assumed.
ABC_A_SHARE = 0.70
ABC_B_SHARE = 0.90


def abc_classes(purchases: list[Purchase]) -> dict[tuple[int, str], dict]:
    """(cluster_id, cpse) -> ABC class from the purchases in the window.

    Ranked within each CPSE, because a material that is a rounding error for
    one refinery can be a tenth of another's spend. Materials with no purchase
    in the window are absent here and read as C where a class is shown.
    """
    value: dict[tuple[int, str], float] = {}
    for purchase in purchases:
        key = (purchase.cluster_id, purchase.cpse)
        value[key] = value.get(key, 0.0) + purchase.qty * purchase.unit_price
    by_cpse: dict[str, list[tuple[float, int]]] = {}
    for (cluster_id, cpse), total in value.items():
        by_cpse.setdefault(cpse, []).append((total, cluster_id))
    out: dict[tuple[int, str], dict] = {}
    for cpse, rows in by_cpse.items():
        rows.sort(reverse=True)
        total = sum(v for v, _ in rows) or 1.0
        running = 0.0
        for annual_value, cluster_id in rows:
            running += annual_value
            share = running / total
            klass = "A" if share <= ABC_A_SHARE else "B" if share <= ABC_B_SHARE else "C"
            out[(cluster_id, cpse)] = {
                "abc": klass,
                "annual_value": round(annual_value, 2),
                "share_of_cpse_spend": round(annual_value / total, 4),
            }
    return out


def abc_for(db: Session, cluster_id: int | None, cpse: str) -> str | None:
    """The ABC class of one material at one CPSE, or None without purchases."""
    if cluster_id is None:
        return None
    entry = abc_classes(load_purchases(db)).get((cluster_id, cpse))
    return entry["abc"] if entry else None


def _window_start(today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=WINDOW_MONTHS * 31)


def load_purchases(db: Session, since: date | None = None) -> list[Purchase]:
    since = since or _window_start()
    rows = db.execute(
        select(
            ClusterMember.cluster_id,
            Cpse.code,
            PurchaseHistory.po_date,
            PurchaseHistory.qty,
            PurchaseHistory.unit_price,
            Item.pack_qty,
            PurchaseHistory.vendor,
        )
        .join(Item, Item.id == PurchaseHistory.item_id)
        .join(ClusterMember, ClusterMember.item_id == Item.id)
        .join(Cpse, Cpse.id == PurchaseHistory.cpse_id)
        .where(PurchaseHistory.po_date >= since)
    ).all()
    return [Purchase(*row) for row in rows]


def _group(purchases: list[Purchase]) -> dict[int, list[Purchase]]:
    grouped: dict[int, list[Purchase]] = {}
    for purchase in purchases:
        grouped.setdefault(purchase.cluster_id, []).append(purchase)
    return grouped


def _describe(db: Session, cluster_ids: list[int]) -> dict[int, dict]:
    if not cluster_ids:
        return {}
    rows = db.execute(
        select(GoldenRecord.cluster_id, GoldenRecord.std_description, Cnmc.code)
        .outerjoin(Cnmc, Cnmc.golden_id == GoldenRecord.id)
        .where(GoldenRecord.cluster_id.in_(cluster_ids))
    ).all()
    return {
        cluster_id: {"description": description, "cnmc": code}
        for cluster_id, description, code in rows
    }


def joint_tender_candidates(
    db: Session, scope: Scope, capture: float = DEFAULT_CAPTURE, limit: int = 25
) -> dict:
    """Items bought by two or more CPSEs in the window (§9A demand aggregation)."""
    grouped = _group(load_purchases(db))
    candidates = []

    for cluster_id, purchases in grouped.items():
        by_cpse: dict[str, list[Purchase]] = {}
        for purchase in purchases:
            by_cpse.setdefault(purchase.cpse, []).append(purchase)
        if len(by_cpse) < 2:
            continue

        unit_prices = [p.price_per_base_unit for p in purchases if p.price_per_base_unit > 0]
        if not unit_prices:
            continue
        low, high = min(unit_prices), max(unit_prices)
        spread = high - low
        combined_qty = sum(p.base_qty for p in purchases)
        # Consolidating at the best observed price is the ceiling; the capture
        # assumption is what turns that into an estimate.
        opportunity = spread * combined_qty
        candidates.append(
            {
                "cluster_id": cluster_id,
                "cpses": sorted(by_cpse),
                "cpse_count": len(by_cpse),
                "orders": len(purchases),
                "combined_qty": round(combined_qty, 1),
                "price_low": round(low, 2),
                "price_high": round(high, 2),
                "price_spread": round(spread, 2),
                "spread_pct": round(100 * spread / high, 1) if high else 0.0,
                "estimated_saving": round(opportunity * capture, 2),
                "max_opportunity": round(opportunity, 2),
                "per_cpse": [
                    {
                        "cpse": cpse,
                        "orders": len(rows),
                        "qty": round(sum(r.base_qty for r in rows), 1),
                        "unit_price": round(
                            sum(r.price_per_base_unit for r in rows) / len(rows), 2
                        ),
                    }
                    for cpse, rows in sorted(by_cpse.items())
                ],
            }
        )

    candidates.sort(key=lambda c: c["estimated_saving"], reverse=True)
    # Totalled before redaction, for the same reason as the transfer figures.
    total_saving = round(sum(c["estimated_saving"] for c in candidates), 2)
    top = candidates[:limit]
    described = _describe(db, [c["cluster_id"] for c in top])
    for candidate in top:
        candidate.update(described.get(candidate["cluster_id"], {}))
        if not scope.sees_all_prices:
            # A steward sees the band, not who paid what (§0.9b).
            band = price_band([row["unit_price"] for row in candidate["per_cpse"]])
            for row in candidate["per_cpse"]:
                if not scope.owns(row["cpse"]):
                    row["unit_price"] = None
                    row["price_withheld"] = True
            candidate["market_band"] = band

    return {
        "window_months": WINDOW_MONTHS,
        "capture_assumption": capture,
        "assumption_note": (
            f"Assumes {round(capture * 100)}% of the observed price spread is "
            "capturable at combined volume."
        ),
        "candidates_found": len(candidates),
        "total_estimated_saving": total_saving,
        "candidates": top,
    }


def price_variance(db: Session, scope: Scope, limit: int = 20) -> dict:
    """The same material bought at very different prices per base unit (§6.8b)."""
    grouped = _group(load_purchases(db))
    rows = []

    for cluster_id, purchases in grouped.items():
        by_cpse: dict[str, list[float]] = {}
        for purchase in purchases:
            if purchase.price_per_base_unit > 0:
                by_cpse.setdefault(purchase.cpse, []).append(purchase.price_per_base_unit)
        if len(by_cpse) < 2:
            continue
        averages = {cpse: sum(v) / len(v) for cpse, v in by_cpse.items()}
        low_cpse = min(averages, key=lambda c: averages[c])
        high_cpse = max(averages, key=lambda c: averages[c])
        low, high = averages[low_cpse], averages[high_cpse]
        if high <= 0:
            continue
        rows.append(
            {
                "cluster_id": cluster_id,
                "cpse_count": len(by_cpse),
                "lowest": {"cpse": low_cpse, "unit_price": round(low, 2)},
                "highest": {"cpse": high_cpse, "unit_price": round(high, 2)},
                "variance_pct": round(100 * (high - low) / high, 1),
                "prices": [
                    {"cpse": cpse, "unit_price": round(value, 2)}
                    for cpse, value in sorted(averages.items())
                ],
            }
        )

    rows.sort(key=lambda r: r["variance_pct"], reverse=True)
    top = rows[:limit]
    described = _describe(db, [r["cluster_id"] for r in top])
    for row in top:
        row.update(described.get(row["cluster_id"], {}))
        if not scope.sees_all_prices:
            band = price_band([p["unit_price"] for p in row["prices"]])
            row["market_band"] = band
            row["prices"] = [
                p if scope.owns(p["cpse"]) else {**p, "unit_price": None, "price_withheld": True}
                for p in row["prices"]
            ]
            for side in ("lowest", "highest"):
                if not scope.owns(row[side]["cpse"]):
                    row[side] = {**row[side], "cpse": "withheld", "unit_price": None}

    return {
        "note": "Prices are normalized to price per base unit, so pack sizes compare.",
        "items_with_variance": len(rows),
        "rows": top,
    }


def vendor_overlap(db: Session, limit: int = 15) -> dict:
    """Several CPSEs buying one item from different vendors (§9A d)."""
    grouped = _group(load_purchases(db))
    rows = []
    for cluster_id, purchases in grouped.items():
        vendors: dict[str, set[str]] = {}
        for purchase in purchases:
            vendors.setdefault(purchase.vendor, set()).add(purchase.cpse)
        cpses = {p.cpse for p in purchases}
        if len(cpses) < 2 or len(vendors) < 2:
            continue
        rows.append(
            {
                "cluster_id": cluster_id,
                "cpse_count": len(cpses),
                "vendor_count": len(vendors),
                "vendors": [
                    {"vendor": vendor, "cpses": sorted(buyers)}
                    for vendor, buyers in sorted(vendors.items())
                ],
            }
        )
    rows.sort(key=lambda r: (r["vendor_count"], r["cpse_count"]), reverse=True)
    top = rows[:limit]
    described = _describe(db, [r["cluster_id"] for r in top])
    for row in top:
        row.update(described.get(row["cluster_id"], {}))
    return {
        "note": "The same material bought from different vendors by different CPSEs.",
        "items_found": len(rows),
        "rows": top,
    }


def last_purchase_and_trend(db: Session, item_id: int, scope: Scope) -> dict:
    """Last purchase price and its direction, for the item page (§9A c)."""
    rows = db.execute(
        select(
            PurchaseHistory.po_date,
            PurchaseHistory.unit_price,
            PurchaseHistory.qty,
            PurchaseHistory.vendor,
            Cpse.code,
        )
        .join(Cpse, Cpse.id == PurchaseHistory.cpse_id)
        .join(Item, Item.id == PurchaseHistory.item_id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .where(PurchaseHistory.item_id == item_id)
        .order_by(PurchaseHistory.po_date)
    ).all()
    if not rows:
        return {"orders": 0, "history": [], "last": None, "trend": None}

    pack = db.execute(select(Item.pack_qty).where(Item.id == item_id)).scalar() or 1.0
    history = [
        {
            "po_date": po_date.isoformat(),
            "unit_price": round(unit_price / max(pack, 1.0), 2),
            "qty": qty,
            "vendor": vendor,
            "cpse": cpse,
        }
        for po_date, unit_price, qty, vendor, cpse in rows
    ]
    first, last = history[0]["unit_price"], history[-1]["unit_price"]
    visible = scope.sees_all_prices or scope.owns(history[-1]["cpse"])
    return {
        "orders": len(history),
        "history": history if visible else [],
        "last": history[-1] if visible else None,
        "trend": (
            {
                "from": first,
                "to": last,
                "change_pct": round(100 * (last - first) / first, 1) if first else 0.0,
                "direction": "up" if last > first else "down" if last < first else "flat",
            }
            if visible and len(history) > 1
            else None
        ),
        "price_band": None if visible else price_band([h["unit_price"] for h in history]),
    }
