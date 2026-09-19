"""One document per CPSE: what SAMAN found in their catalogue, and what it is
worth to them.

The dashboards answer the ministry's question, how far the estate has come.
A steward's question is narrower and more urgent: what did the platform find
in *my* rows, what is waiting for *my* people, and what is it worth to *us*.
This module answers it in one document, on demand or on a schedule, so that
a CPSE that never opens the platform still receives the case for doing so.

Two rules from the dashboards carry over unchanged. Every figure is computed
from the database by the same functions the dashboards call, so a number in
the report reconciles with the number on the screen; and every modelled sum
(a saving, an avoided purchase) travels with the assumption that produced it
(§10). A third rule is the report's own: it is written as the CPSE's steward
would see the platform, whoever asks for it. The registrar may see every
price nationally, but a document that leaves the building must not, so the
redaction scope is always `Scope("steward", code)` (§0.9b), and a report
about CPCL never carries IOCL's price for a bearing, only the anonymised band.

Delivery is by SMTP when the installation has a relay and otherwise an
RFC-822 file in `data/outbox/`, so an offline installation and the demo both
produce the artefact; either way the send is an audit event carrying the
document's hash.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import smtplib
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import audit, cache, inventory, opportunity, quality
from .config import get_settings
from .models import (
    AuditEvent,
    ClusterMember,
    Cnmc,
    Cpse,
    Decision,
    GoldenRecord,
    Item,
    Pair,
    PurchaseHistory,
    RawItem,
    Relation,
    ReviewTask,
    SmartCreateCheck,
    Stock,
    User,
)
from .visibility import Scope, price_band

#: The audit action a delivery records, and the entity the last-sent lookup
#: reads it back by.
ACTION_SENT = "report.sent"

#: How many example pairs, transfers, tenders and variance rows the document
#: carries. It is a report, not a listing; the platform holds the rest.
EXAMPLES = 10

SYNTHETIC_NOTE = (
    "The demo estate is synthetic: catalogue rows, prices, stock and purchase "
    "history are generated, and the near-uniform overlap between CPSEs is the "
    "generator's, not a finding. Every figure below is computed from the database "
    "by the same functions the dashboards use."
)

#: What lifts each quality rate, in the steward's terms. The scorecard names
#: the weakest rate; this says what to do about it.
QUALITY_ADVICE = {
    "classified": (
        "Rows the classifier could not place in a class. Descriptions that name the "
        "noun first (BEARING, VALVE, GASKET) classify; codes and abbreviations alone "
        "do not."
    ),
    "attributes": (
        "Identity-critical attributes missing from classified rows: a bore without an "
        "outside diameter, a valve without a pressure class. Complete them at source "
        "and the matcher can decide instead of holding the pair for review."
    ),
    "uom": (
        "Rows without a canonical base unit. Unit words the catalogue uses (NOS, PCS, "
        "MTRS) map to EA and M when they are present; blank units cannot."
    ),
    "mpn": (
        "Rows without a manufacturer part number. A part number is the strongest "
        "identity key the platform has; where the nameplate carries one, record it."
    ),
    "unique": (
        "Two of your own rows describing one material. Confirming the merges in the "
        "review queue retires the duplicate code."
    ),
    "active": (
        f"Rows with no purchase and no stock movement in {quality.STALE_MONTHS} months. "
        "Candidates for retirement rather than migration."
    ),
}

RATE_LABELS = {
    "classified": "classified",
    "attributes": "identity attributes complete",
    "uom": "canonical unit",
    "mpn": "part number present",
    "unique": "no internal duplicates",
    "active": f"active in {quality.STALE_MONTHS} months",
}


def _cpse(db: Session, code: str) -> Cpse | None:
    return db.execute(select(Cpse).where(Cpse.code == code.upper())).scalar_one_or_none()


def cpse_report(
    db: Session, cpse_code: str, scope: Scope | None = None, today: date | None = None
) -> dict:
    """The report for one CPSE, memoised on the estate's version like a
    dashboard. `scope` is who asked, recorded on the document; the figures
    are redacted as the CPSE's own steward would see them regardless."""
    cpse = _cpse(db, cpse_code)
    if cpse is None:
        raise LookupError(f"Unknown CPSE {cpse_code!r}.")
    today = today or date.today()
    asked_by = scope.role if scope else "system"
    return cache.memo(
        db,
        ("report", cpse.code, today.isoformat(), asked_by),
        lambda: _report(db, cpse, asked_by, today),
    )


def _report(db: Session, cpse: Cpse, asked_by: str, today: date) -> dict:
    code = cpse.code
    redaction = Scope(role="steward", cpse_code=code)
    window_start = opportunity._window_start(today)
    purchases = opportunity.load_purchases(db, window_start)

    catalogue = _catalogue(db, cpse)
    duplicates = _duplicates(db, cpse)
    review = _review(db, cpse, window_start)
    quality_section = _quality(db, code, today)
    inventory_section = _inventory(db, cpse, redaction, purchases)
    procurement = _procurement(db, redaction, purchases)
    prevention = _prevention(db, cpse)
    report = {
        "cpse": {"code": code, "name": cpse.name, "contact_email": cpse.contact_email},
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "requested_by": asked_by,
        "period": {
            "from": window_start.isoformat(),
            "to": today.isoformat(),
            "months": opportunity.WINDOW_MONTHS,
            "note": (
                f"Purchases, decisions and savings are counted over the last "
                f"{opportunity.WINDOW_MONTHS} months; catalogue, review queue, stock "
                "and quality are as of the day the report was generated."
            ),
        },
        "synthetic_note": SYNTHETIC_NOTE,
        "visibility": redaction.as_dict(),
        "catalogue": catalogue,
        "duplicates": duplicates,
        "review": review,
        "quality": quality_section,
        "inventory": inventory_section,
        "procurement": procurement,
        "prevention": prevention,
    }
    report["actions"] = _actions(report)
    return report


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


def _catalogue(db: Session, cpse: Cpse) -> dict:
    rows = (
        db.execute(select(func.count(RawItem.id)).where(RawItem.cpse_id == cpse.id)).scalar() or 0
    )
    in_cluster = (
        db.execute(
            select(func.count(func.distinct(Item.id)))
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .join(ClusterMember, ClusterMember.item_id == Item.id)
            .where(RawItem.cpse_id == cpse.id)
        ).scalar()
        or 0
    )
    # The same join the executive dashboard's per_cpse progress uses, so the
    # two agree by construction.
    coded = (
        db.execute(
            select(func.count(func.distinct(Item.id)))
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .join(ClusterMember, ClusterMember.item_id == Item.id)
            .join(GoldenRecord, GoldenRecord.cluster_id == ClusterMember.cluster_id)
            .join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
            .where(RawItem.cpse_id == cpse.id)
        ).scalar()
        or 0
    )
    by_class = [
        {"class_code": class_code, "rows": n}
        for class_code, n in db.execute(
            select(Item.class_code, func.count(Item.id))
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .where(RawItem.cpse_id == cpse.id)
            .group_by(Item.class_code)
            .order_by(func.count(Item.id).desc(), Item.class_code)
        ).all()
    ]
    return {
        "rows": rows,
        "in_cluster": in_cluster,
        "coded": coded,
        "coded_share": round(coded / rows, 4) if rows else 0.0,
        "by_class": by_class,
        "note": (
            "A row is one entry of your catalogue. It is in a cluster once the matcher "
            "has grouped it with the other names of the same material, and coded once "
            "that cluster's golden record carries a CNMC."
        ),
    }


def _member_rows(db: Session):
    """Every clustered row in the estate with its CPSE: the one read the
    duplicate sections share."""
    return db.execute(
        select(
            ClusterMember.cluster_id,
            Item.id,
            RawItem.cpse_id,
            RawItem.legacy_code,
            RawItem.description,
        )
        .join(Item, Item.id == ClusterMember.item_id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .order_by(ClusterMember.cluster_id, Item.id)
    ).all()


def _duplicates(db: Session, cpse: Cpse) -> dict:
    names = dict(db.execute(select(Cpse.id, Cpse.code)).all())
    clusters: dict[int, list] = defaultdict(list)
    for cluster_id, item_id, cpse_id, legacy, description in _member_rows(db):
        clusters[cluster_id].append((item_id, cpse_id, legacy, description))

    internal_clusters = 0
    internal_rows = 0
    surplus = 0
    examples: list[dict] = []
    cross_rows = 0
    cross_clusters = 0
    per_other: dict[str, Counter] = defaultdict(Counter)
    for members in clusters.values():
        mine = [m for m in members if m[1] == cpse.id]
        if not mine:
            continue
        if len(mine) > 1:
            internal_clusters += 1
            internal_rows += len(mine)
            surplus += len(mine) - 1
            if len(examples) < EXAMPLES:
                a, b = mine[0], mine[1]
                examples.append(
                    {
                        "a": {"legacy_code": a[2], "description": a[3]},
                        "b": {"legacy_code": b[2], "description": b[3]},
                        "rows_in_cluster": len(mine),
                    }
                )
        others = {m[1] for m in members} - {cpse.id}
        if others:
            cross_rows += len(mine)
            cross_clusters += 1
            for other in others:
                per_other[names[other]]["materials"] += 1
                per_other[names[other]]["rows"] += len(mine)

    equivalents = dict(
        db.execute(
            select(Relation.status, func.count(func.distinct(Relation.id)))
            .join(
                Item,
                or_(Item.id == Relation.item_a, Item.id == Relation.item_b),
            )
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .where(
                Relation.rel_type.in_(("equivalent", "supersedes")),
                RawItem.cpse_id == cpse.id,
            )
            .group_by(Relation.status)
        ).all()
    )
    return {
        "internal": {
            "rows": internal_rows,
            "clusters": internal_clusters,
            "surplus_rows": surplus,
            "examples": examples,
            "note": (
                "Two or more of your own rows in one cluster: one material under more "
                "than one of your codes. Surplus rows are the codes that retire when the "
                "cluster is adopted, which is the scorecard's internal-duplicate count."
            ),
        },
        "cross_cpse": {
            "rows": cross_rows,
            "clusters": cross_clusters,
            "by_cpse": [
                {"cpse": other, "materials": counts["materials"], "rows": counts["rows"]}
                for other, counts in sorted(per_other.items())
            ],
            "note": (
                "Your rows whose material another CPSE also catalogues. A material shared "
                "with two CPSEs appears under both, so the per-CPSE counts overlap and "
                "are not meant to sum to the total."
            ),
        },
        "equivalents": {
            "proposed": equivalents.get("proposed", 0),
            "approved": equivalents.get("approved", 0),
            "rejected": equivalents.get("rejected", 0),
            "note": (
                "Functional equivalents and supersessions touching your rows: a different "
                "relation from duplication, decided by a technical authority."
            ),
        },
    }


def _review(db: Session, cpse: Cpse, since: date) -> dict:
    mine = (
        select(Item.id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .where(RawItem.cpse_id == cpse.id)
        .subquery()
    )
    pending_rows = db.execute(
        select(ReviewTask.band, Pair.verdict, func.count(ReviewTask.id))
        .join(Pair, Pair.id == ReviewTask.pair_id)
        .where(
            ReviewTask.state == "pending",
            or_(Pair.item_a.in_(select(mine.c.id)), Pair.item_b.in_(select(mine.c.id))),
        )
        .group_by(ReviewTask.band, Pair.verdict)
    ).all()
    by_band: Counter = Counter()
    conflicts = 0
    for band, verdict, n in pending_rows:
        by_band[band] += n
        if verdict == "conflict":
            conflicts += n
    decisions = dict(
        db.execute(
            select(Decision.action, func.count(Decision.id))
            .join(User, User.id == Decision.user_id)
            .where(
                User.cpse_id == cpse.id, Decision.ts >= datetime.combine(since, datetime.min.time())
            )
            .group_by(Decision.action)
        ).all()
    )
    return {
        "pending": {band: by_band.get(band, 0) for band in ("high", "grey", "low")},
        "pending_total": sum(by_band.values()),
        "conflicts": conflicts,
        "decisions_in_period": {
            "total": sum(decisions.values()),
            "by_action": dict(sorted(decisions.items())),
        },
        "note": (
            "Pending tasks are pairs in the review queue where one side is your row. "
            "High band: the machine is confident and asks for confirmation; grey: it "
            "cannot tell; conflicts differ on an identity attribute and need an "
            "approver. Decisions are those made by your own users in the period."
        ),
    }


def _quality(db: Session, code: str, today: date) -> dict:
    card = quality.scorecard(db, today)
    mine = next((row for row in card["cpses"] if row["cpse"] == code), None)
    if mine is None:
        return {
            "row": None,
            "national": card["national"],
            "weakest": None,
            "weights": card["weights"],
        }
    weakest = min(mine["rates"], key=lambda k: mine["rates"][k])
    rates_ranked = sorted(card["cpses"], key=lambda r: r["score"], reverse=True)
    rank = next(i for i, r in enumerate(rates_ranked, 1) if r["cpse"] == code)
    return {
        "row": mine,
        "national": card["national"],
        "rank": {"position": rank, "of": len(card["cpses"])},
        "weakest": {
            "rate": weakest,
            "label": RATE_LABELS[weakest],
            "value": mine["rates"][weakest],
            "weight": card["weights"][weakest],
            "what_lifts_it": QUALITY_ADVICE[weakest],
        },
        "weights": card["weights"],
        "labels": RATE_LABELS,
        "note": card["note"],
    }


def _own_prices(db: Session, cpse: Cpse) -> dict[int, float]:
    """cluster_id -> this CPSE's latest price per base unit, from its own
    purchase history over all time. What a receiver would have paid."""
    rows = db.execute(
        select(
            ClusterMember.cluster_id,
            PurchaseHistory.unit_price,
            Item.pack_qty,
            PurchaseHistory.po_date,
        )
        .join(Item, Item.id == PurchaseHistory.item_id)
        .join(ClusterMember, ClusterMember.item_id == Item.id)
        .where(PurchaseHistory.cpse_id == cpse.id)
        .order_by(PurchaseHistory.po_date)
    ).all()
    latest: dict[int, float] = {}
    for cluster_id, unit_price, pack, _ in rows:
        latest[cluster_id] = unit_price / max(pack or 1.0, 1.0)
    return latest


def _inventory(db: Session, cpse: Cpse, scope: Scope, purchases: list) -> dict:
    code = cpse.code
    positions, qty, value = db.execute(
        select(
            func.count(Stock.id),
            func.sum(Stock.qty_on_hand),
            func.sum(Stock.qty_on_hand * Stock.unit_value),
        ).where(Stock.cpse_id == cpse.id)
    ).one()

    # Dead stock by the rule `inventory.dead_stock` applies, restricted to this
    # CPSE's positions; the sum over every CPSE is the dashboard's tile.
    stale_before = inventory._cutoff(inventory.DEAD_STOCK_MONTHS)
    dead_positions = 0
    dead_value = 0.0
    dead_materials: set[int] = set()
    for cluster_id, holder, _plant, on_hand, _reserved, unit_value, moved in inventory._stock_rows(
        db
    ):
        if holder != code or moved is None or moved >= stale_before or (on_hand or 0.0) <= 0:
            continue
        dead_positions += 1
        dead_value += (on_hand or 0.0) * (unit_value or 0.0)
        dead_materials.add(cluster_id)

    transfers = inventory.transfer_suggestions(db, scope, limit=10**6)
    own_price = _own_prices(db, cpse)
    band_by_cluster: dict[int, dict | None] = {}
    by_cluster: dict[int, list[float]] = defaultdict(list)
    for purchase in purchases:
        if purchase.price_per_base_unit > 0:
            by_cluster[purchase.cluster_id].append(purchase.price_per_base_unit)
    as_source: list[dict] = []
    as_receiver: list[dict] = []
    source_value = 0.0
    receiver_value = 0.0
    receiver_unvalued = 0
    for s in transfers["suggestions"]:
        if s["from"]["cpse"] == code:
            as_source.append(
                {
                    "cluster_id": s["cluster_id"],
                    "cnmc": s.get("cnmc"),
                    "description": s.get("description"),
                    "to_cpse": s["to"]["cpse"],
                    "qty": s["qty"],
                    "unit_value": s["unit_value"],
                    "value": s["avoided_purchase_value"],
                    "idle_since": s["idle_since"],
                    "abc": s["from"]["abc"],
                    "critical_spare": s["critical_spare_at_source"],
                }
            )
            source_value += s["avoided_purchase_value"] or 0.0
        elif s["to"]["cpse"] == code:
            # The other side's price is withheld (§0.9b); the purchase this
            # CPSE avoids is valued at what it last paid for the material, or
            # failing that at the market band's mean when the band is more
            # than one CPSE wide.
            price = own_price.get(s["cluster_id"])
            basis = "your last purchase price"
            if price is None:
                band = band_by_cluster.setdefault(
                    s["cluster_id"], price_band(by_cluster.get(s["cluster_id"], []))
                )
                if band and band["n"] >= 2:
                    price = band["mean"]
                    basis = f"band mean, n={band['n']}"
            value_here = round(s["qty"] * price, 2) if price is not None else None
            if value_here is None:
                receiver_unvalued += 1
            receiver_value += value_here or 0.0
            as_receiver.append(
                {
                    "cluster_id": s["cluster_id"],
                    "cnmc": s.get("cnmc"),
                    "description": s.get("description"),
                    "from_cpse": s["from"]["cpse"],
                    "qty": s["qty"],
                    "your_available": s["to"]["available"],
                    "value": value_here,
                    "valued_at": basis if value_here is not None else None,
                }
            )
    as_source.sort(key=lambda r: r["value"] or 0.0, reverse=True)
    as_receiver.sort(key=lambda r: r["value"] or 0.0, reverse=True)

    return {
        "positions": positions or 0,
        "qty_on_hand": round(qty or 0.0, 1),
        "value_inr": round(value or 0.0, 2),
        "dead_stock": {
            "rule_months": inventory.DEAD_STOCK_MONTHS,
            "positions": dead_positions,
            "materials": len(dead_materials),
            "value_inr": round(dead_value, 2),
            "note": (
                f"Positions with quantity on hand and no movement in "
                f"{inventory.DEAD_STOCK_MONTHS} months, at your own unit values."
            ),
        },
        "transfers": {
            "as_source": {
                "count": len(as_source),
                "value_inr": round(source_value, 2),
                "rows": as_source[:EXAMPLES],
                "note": (
                    "Idle surplus of yours that another CPSE is short of. Value is your "
                    "own unit value times the movable quantity: what the receiver "
                    "would not have to buy."
                ),
            },
            "as_receiver": {
                "count": len(as_receiver),
                "avoidable_purchase_inr": round(receiver_value, 2),
                "unvalued": receiver_unvalued,
                "rows": as_receiver[:EXAMPLES],
                "assumption": (
                    "Another CPSE holds idle surplus of a material you are short of. The "
                    "avoidable purchase is valued at your own last price for the material, "
                    "or at the anonymised market band's mean where you have none; the "
                    "holder's price is never shown (§0.9b). Distance and transport cost "
                    "are out of scope."
                ),
            },
            "thresholds": {
                "surplus_qty": transfers["surplus_threshold_qty"],
                "shortage_qty": transfers["shortage_threshold_qty"],
            },
        },
    }


def _procurement(db: Session, scope: Scope, purchases: list) -> dict:
    code = scope.cpse_code
    tenders = opportunity.joint_tender_candidates(db, scope, limit=10**6, purchases=purchases)
    capture = tenders["capture_assumption"]

    orders = sum(1 for p in purchases if p.cpse == code)
    spend = sum(p.qty * p.unit_price for p in purchases if p.cpse == code)
    materials = len({p.cluster_id for p in purchases if p.cpse == code})

    rows: list[dict] = []
    shared_orders = 0
    shared_spend = 0.0
    attributable = 0.0
    for candidate in tenders["candidates"]:
        if code not in candidate["cpses"]:
            continue
        mine = next(r for r in candidate["per_cpse"] if r["cpse"] == code)
        my_spend = sum(
            p.qty * p.unit_price
            for p in purchases
            if p.cluster_id == candidate["cluster_id"] and p.cpse == code
        )
        share = mine["qty"] / candidate["combined_qty"] if candidate["combined_qty"] else 0.0
        saving = round(candidate["estimated_saving"] * share, 2)
        shared_orders += mine["orders"]
        shared_spend += my_spend
        attributable += saving
        rows.append(
            {
                "cluster_id": candidate["cluster_id"],
                "cnmc": candidate.get("cnmc"),
                "description": candidate.get("description"),
                "cpse_count": candidate["cpse_count"],
                "your_orders": mine["orders"],
                "your_qty": mine["qty"],
                "your_unit_price": mine["unit_price"],
                "your_spend_inr": round(my_spend, 2),
                "market_band": candidate.get("market_band"),
                "combined_qty": candidate["combined_qty"],
                "your_share_of_volume": round(share, 4),
                "estimated_saving_all_inr": candidate["estimated_saving"],
                "estimated_saving_yours_inr": saving,
            }
        )
    rows.sort(key=lambda r: r["estimated_saving_yours_inr"], reverse=True)

    variance = opportunity.price_variance(db, scope, limit=10**6)
    above: list[dict] = []
    highest = 0
    for row in variance["rows"]:
        mine = next((p for p in row["prices"] if p["cpse"] == code), None)
        band = row.get("market_band")
        if mine is None or band is None or mine["unit_price"] is None:
            continue
        if mine["unit_price"] <= band["mean"]:
            continue
        is_highest = row["highest"]["cpse"] == code
        highest += is_highest
        above.append(
            {
                "cluster_id": row["cluster_id"],
                "cnmc": row.get("cnmc"),
                "description": row.get("description"),
                "cpse_count": row["cpse_count"],
                "your_unit_price": mine["unit_price"],
                "market_band": band,
                "premium_over_mean_pct": round(
                    100 * (mine["unit_price"] - band["mean"]) / band["mean"], 1
                )
                if band["mean"]
                else None,
                "you_pay_the_most": is_highest,
            }
        )
    above.sort(key=lambda r: r["premium_over_mean_pct"] or 0.0, reverse=True)

    return {
        "window_months": tenders["window_months"],
        "your_orders": orders,
        "your_materials": materials,
        "your_spend_inr": round(spend, 2),
        "joint_tenders": {
            "materials": len(rows),
            "your_orders": shared_orders,
            "your_spend_inr": round(shared_spend, 2),
            "capture_assumption": capture,
            "estimated_saving_yours_inr": round(attributable, 2),
            "rows": rows[:EXAMPLES],
            "assumption": (
                f"{tenders['assumption_note']} Each material's estimate is attributed to "
                "you in proportion to your share of the combined volume. Other CPSEs' "
                "prices are shown as an anonymised band (§0.9b). Not a forecast."
            ),
        },
        "price_variance": {
            "materials_above_band_mean": len(above),
            "materials_where_you_pay_the_most": highest,
            "rows": above[:EXAMPLES],
            "note": (
                f"{variance['note']} Listed where your average price per base unit in the "
                "window is above the market band's mean; the band is the anonymised "
                "range of what every buyer paid."
            ),
        },
    }


def _prevention(db: Session, cpse: Cpse) -> dict:
    counts = dict(
        db.execute(
            select(SmartCreateCheck.outcome, func.count(SmartCreateCheck.id))
            .where(SmartCreateCheck.cpse_id == cpse.id)
            .group_by(SmartCreateCheck.outcome)
        ).all()
    )
    prevented = counts.get("prevented", 0)
    created = counts.get("created_anyway", 0)
    decided = prevented + created
    return {
        "checks": sum(counts.values()),
        "prevented": prevented,
        "created_anyway": created,
        "open": counts.get("open", 0),
        "prevention_rate": round(prevented / decided, 4) if decided else None,
        "note": (
            "Smart-Create checks run by your users. Prevented: the requester reused an "
            "existing material instead of creating a new code. Created anyway: they "
            "overrode a confident match, with the reason recorded."
        ),
    }


def _actions(report: dict) -> list[dict]:
    """Concrete next steps, each with the count that produced it. A CPSE with
    nothing waiting gets an empty list, not encouragement."""
    actions: list[dict] = []
    review = report["review"]
    high = review["pending"]["high"]
    if high:
        actions.append(
            {
                "key": "confirm_high",
                "text": f"Confirm {high:,} high-band merges in the Workbench: the machine is "
                "confident and each one retires a duplicate code.",
                "count": high,
            }
        )
    if review["conflicts"]:
        actions.append(
            {
                "key": "conflicts",
                "text": f"Bring {review['conflicts']:,} conflicts to an approver: the pairs "
                "differ on an identity attribute and only an approver may close them.",
                "count": review["conflicts"],
            }
        )
    grey = review["pending"]["grey"]
    if grey:
        actions.append(
            {
                "key": "grey",
                "text": f"Review {grey:,} grey-band pairs the machine cannot tell apart; "
                "each answer also trains the learned model.",
                "count": grey,
            }
        )
    internal = report["duplicates"]["internal"]
    if internal["surplus_rows"]:
        actions.append(
            {
                "key": "internal",
                "text": f"Retire {internal['surplus_rows']:,} of your own codes that duplicate "
                f"another of yours across {internal['clusters']:,} materials.",
                "count": internal["surplus_rows"],
            }
        )
    receiver = report["inventory"]["transfers"]["as_receiver"]
    if receiver["count"]:
        actions.append(
            {
                "key": "transfers_in",
                "text": f"{receiver['count']:,} materials you are short of sit idle at a sister "
                f"CPSE: {_inr(receiver['avoidable_purchase_inr'])} of purchase avoidable, "
                "valued at your own prices.",
                "count": receiver["count"],
            }
        )
    source = report["inventory"]["transfers"]["as_source"]
    if source["count"]:
        actions.append(
            {
                "key": "transfers_out",
                "text": f"Offer {source['count']:,} idle positions worth "
                f"{_inr(source['value_inr'])} to the CPSEs that are short of them.",
                "count": source["count"],
            }
        )
    tenders = report["procurement"]["joint_tenders"]
    if tenders["materials"]:
        actions.append(
            {
                "key": "joint_tenders",
                "text": f"Take {tenders['materials']:,} materials to a joint tender: "
                f"{_inr(tenders['estimated_saving_yours_inr'])} attributable to you at "
                f"{round(tenders['capture_assumption'] * 100)}% capture (an assumption, not "
                "a forecast).",
                "count": tenders["materials"],
            }
        )
    variance = report["procurement"]["price_variance"]
    if variance["materials_where_you_pay_the_most"]:
        actions.append(
            {
                "key": "price_variance",
                "text": f"Renegotiate {variance['materials_where_you_pay_the_most']:,} materials "
                "where you pay the most of any buyer.",
                "count": variance["materials_where_you_pay_the_most"],
            }
        )
    weakest = report["quality"].get("weakest")
    if weakest and weakest["value"] < 0.9:
        actions.append(
            {
                "key": "quality",
                "text": f"Lift the weakest quality rate, {weakest['label']} at "
                f"{round(weakest['value'] * 100)}%: {weakest['what_lifts_it']}",
                "count": round(weakest["value"] * 100),
            }
        )
    dead = report["inventory"]["dead_stock"]
    if dead["positions"]:
        actions.append(
            {
                "key": "dead_stock",
                "text": f"Review {dead['positions']:,} stock positions ({_inr(dead['value_inr'])}) "
                f"with no movement in {dead['rule_months']} months.",
                "count": dead["positions"],
            }
        )
    return actions


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _inr(value: float | None) -> str:
    """Rupees the way an Indian reader groups them, compact above a lakh."""
    if value is None:
        return "withheld"
    if value >= 1e7:
        return f"₹{value / 1e7:,.2f} cr"
    if value >= 1e5:
        return f"₹{value / 1e5:,.2f} lakh"
    return f"₹{value:,.0f}"


def _price(value: float | None) -> str:
    """A unit price: paise matter below a thousand rupees, not above."""
    if value is None:
        return "withheld"
    return f"₹{value:,.0f}" if value >= 1000 else f"₹{value:,.2f}"


def _n(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.1f}"
    return f"{value:,}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


class _Raw(str):
    """A cell already escaped and marked up."""


def _band(band: dict | None) -> str:
    if not band:
        return "—"
    return _Raw(
        f'<span class="nowrap">{_price(band["min"])}–{_price(band["max"])}</span><br>'
        f'<span class="nowrap note">mean {_price(band["mean"])} · n={band["n"]}</span>'
    )


#: Column kinds: how a cell is aligned and whether it may wrap. Numbers,
#: dates and CPSE codes never break; a CNMC or legacy code breaks only after a
#: hyphen; a description takes whatever width the others leave.
Col = tuple[str, str]


def _table(columns: list[Col], rows: list[list], empty: str = "Nothing to list.") -> str:
    if not rows:
        return f'<p class="empty">{_e(empty)}</p>'
    head = "".join(f'<th class="{kind}">{_e(label)}</th>' for label, kind in columns)
    body = []
    for row in rows:
        cells = []
        for (_, kind), cell in zip(columns, row, strict=True):
            text = cell if isinstance(cell, _Raw) else _e(cell)
            if kind == "code" and not isinstance(cell, _Raw):
                text = text.replace("-", "-\u200b")
            cells.append(f'<td class="{kind}">{text}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _tile(label: str, value: str, note: str | None = None) -> str:
    return (
        f'<div class="tile"><div class="label">{_e(label)}</div>'
        f'<div class="value">{_e(value)}</div>'
        + (f'<div class="note">{_e(note)}</div>' if note else "")
        + "</div>"
    )


def _assumption(text: str) -> str:
    return f'<p class="assumption"><strong>Assumption.</strong> {_e(text)}</p>'


CSS = """
@page { size: A4; margin: 16mm 14mm; }
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 0; font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  color: #111; background: #fff; font-size: 10.5pt; line-height: 1.45; }
.page { max-width: 200mm; margin: 0 auto; padding: 12mm 6mm 16mm; }
header { border-bottom: 2px solid #111; padding-bottom: 8px; margin-bottom: 14px; }
.mono, header .kicker, .tile .value, td.code, td.num, th.num, .nowrap {
  font-family: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
header .kicker { font-size: 8.5pt; letter-spacing: .12em; text-transform: uppercase; color: #555; }
header h1 { margin: 4px 0 2px; font-size: 20pt; font-weight: 600; letter-spacing: -0.01em; }
header .meta { font-size: 9pt; color: #555; }
.synthetic { border: 1px solid #111; padding: 8px 10px; font-size: 9pt; margin: 12px 0 16px; }
section { margin: 18px 0 0; }
section h2 { font-size: 9pt; letter-spacing: .12em; text-transform: uppercase; color: #555;
  border-bottom: 1px solid #bbb; padding-bottom: 4px; margin: 0 0 10px; font-weight: 600;
  page-break-after: avoid; }
section h3 { font-size: 10.5pt; margin: 14px 0 6px; font-weight: 600; page-break-after: avoid; }
p { margin: 6px 0; }
p.note, .note { font-size: 9pt; color: #555; }
p.empty { font-size: 9.5pt; color: #555; font-style: italic; }
.assumption { font-size: 9pt; color: #333; border-left: 3px solid #111; padding: 4px 8px;
  margin: 8px 0; background: #f4f4f4; page-break-inside: avoid; }
.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: #bbb;
  border: 1px solid #bbb; margin: 8px 0; page-break-inside: avoid; }
.tile { background: #fff; padding: 8px 10px; min-width: 0; }
.tile .label { font-size: 8pt; letter-spacing: .08em; text-transform: uppercase; color: #555; }
.tile .value { font-size: 13.5pt; margin-top: 2px; white-space: nowrap; }
.tile .note { font-size: 8.5pt; color: #555; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; font-size: 8.5pt; margin: 6px 0 4px; }
th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid #ddd; vertical-align: top; }
th { font-size: 7.5pt; letter-spacing: .06em; text-transform: uppercase; color: #555;
  border-bottom: 1px solid #111; font-weight: 600; }
tr { page-break-inside: avoid; }
td.num, td.tag, td.cpse, td.date { white-space: nowrap; }
td.num, th.num { text-align: right; }
td.desc { min-width: 12em; }
td.code { font-size: 8pt; overflow-wrap: normal; }
.nowrap { white-space: nowrap; }
ol.actions { padding-left: 20px; margin: 6px 0; }
ol.actions li { margin: 4px 0; }
.bar { display: inline-block; height: 8px; background: #111; vertical-align: middle; }
.bar-track { display: inline-block; width: 80px; height: 8px; background: #e6e6e6;
  vertical-align: middle; margin-right: 6px; }
footer { margin-top: 24px; border-top: 1px solid #bbb; padding-top: 8px; font-size: 8.5pt;
  color: #555; }
@media print { .page { max-width: none; padding: 0; } a { color: inherit; text-decoration: none; } }
@media (max-width: 640px) { .tiles { grid-template-columns: repeat(2, 1fr); } }
"""


def render_html(report: dict) -> str:
    """The report as one self-contained HTML document: inline CSS, no
    external requests, monochrome, prints on A4."""
    cpse = report["cpse"]
    cat = report["catalogue"]
    dup = report["duplicates"]
    rev = report["review"]
    qual = report["quality"]
    inv = report["inventory"]
    proc = report["procurement"]
    prev = report["prevention"]
    period = report["period"]
    parts: list[str] = []

    parts.append(
        "<header>"
        f'<div class="kicker">SAMAN · catalogue report · {_e(cpse["code"])}</div>'
        f"<h1>{_e(cpse['name'])}</h1>"
        f'<div class="meta">Generated {_e(report["generated_at"])} · period '
        f'{_e(period["from"])} to {_e(period["to"])} ({period["months"]} months) · '
        f'requested by {_e(report["requested_by"])}</div>'
        "</header>"
    )
    parts.append(f'<div class="synthetic">{_e(report["synthetic_note"])}</div>')

    # Actions first: the page a steward reads if they read one.
    parts.append("<section><h2>What to do next</h2>")
    if report["actions"]:
        parts.append(
            '<ol class="actions">'
            + "".join(f"<li>{_e(a['text'])}</li>" for a in report["actions"])
            + "</ol>"
        )
    else:
        parts.append('<p class="empty">Nothing is waiting on you.</p>')
    parts.append("</section>")

    parts.append("<section><h2>Your catalogue</h2>")
    in_cluster_share = _pct(cat["in_cluster"] / cat["rows"]) if cat["rows"] else None
    parts.append(
        '<div class="tiles">'
        + _tile("rows", _n(cat["rows"]))
        + _tile("in a cluster", _n(cat["in_cluster"]), in_cluster_share)
        + _tile("carrying a CNMC", _n(cat["coded"]), _pct(cat["coded_share"]))
        + _tile("classes", _n(len(cat["by_class"])))
        + "</div>"
    )
    parts.append(f'<p class="note">{_e(cat["note"])}</p>')
    parts.append(
        _table(
            [("Class", "code"), ("Rows", "num")],
            [[c["class_code"], _n(c["rows"])] for c in cat["by_class"][:12]],
        )
    )
    parts.append("</section>")

    internal, cross, equiv = dup["internal"], dup["cross_cpse"], dup["equivalents"]
    parts.append("<section><h2>Duplicates found</h2>")
    parts.append(
        '<div class="tiles">'
        + _tile(
            "your rows duplicating yours",
            _n(internal["rows"]),
            f"in {_n(internal['clusters'])} materials",
        )
        + _tile("codes that would retire", _n(internal["surplus_rows"]))
        + _tile(
            "rows another CPSE also has", _n(cross["rows"]), f"{_n(cross['clusters'])} materials"
        )
        + _tile("equivalents proposed", _n(equiv["proposed"]), f"{_n(equiv['approved'])} approved")
        + "</div>"
    )
    parts.append(f'<p class="note">{_e(internal["note"])}</p>')
    parts.append("<h3>Inside your catalogue: example pairs</h3>")
    parts.append(
        _table(
            [("Code", "code"), ("Description", "desc"), ("Code", "code"), ("Description", "desc")],
            [
                [
                    ex["a"]["legacy_code"],
                    ex["a"]["description"],
                    ex["b"]["legacy_code"],
                    ex["b"]["description"],
                ]
                for ex in internal["examples"]
            ],
            "No two of your rows describe the same material.",
        )
    )
    parts.append("<h3>Shared with other CPSEs</h3>")
    parts.append(
        _table(
            [("CPSE", "code"), ("Materials in common", "num"), ("Your rows", "num")],
            [[r["cpse"], _n(r["materials"]), _n(r["rows"])] for r in cross["by_cpse"]],
            "None of your materials is catalogued by another CPSE.",
        )
    )
    parts.append(f'<p class="note">{_e(cross["note"])}</p>')
    parts.append("</section>")

    parts.append("<section><h2>Review queue</h2>")
    parts.append(
        '<div class="tiles">'
        + _tile("high band", _n(rev["pending"]["high"]), "confirm")
        + _tile("grey band", _n(rev["pending"]["grey"]), "decide")
        + _tile("conflicts", _n(rev["conflicts"]), "approver")
        + _tile(
            "decisions by your users",
            _n(rev["decisions_in_period"]["total"]),
            f"last {period['months']} months",
        )
        + "</div>"
    )
    parts.append(f'<p class="note">{_e(rev["note"])}</p>')
    parts.append("</section>")

    parts.append("<section><h2>Data quality</h2>")
    row = qual.get("row")
    if row:
        national = qual.get("national") or {}
        rank = qual.get("rank") or {}
        parts.append(
            '<div class="tiles">'
            + _tile(
                "your score",
                f"{row['score'] * 100:.1f}",
                f"rank {rank.get('position')} of {rank.get('of')}",
            )
            + _tile("national", f"{national.get('score', 0) * 100:.1f}" if national else "—")
            + _tile("internal duplicates", _n(row["internal_duplicates"]))
            + _tile("stale rows", _n(row["stale_rows"]), f"{quality.STALE_MONTHS} months")
            + "</div>"
        )
        table_rows = []
        for key, label in qual["labels"].items():
            mine_v = row["rates"][key]
            nat_v = (national.get("rates") or {}).get(key)
            bar = _Raw(
                '<span class="bar-track">'
                f'<span class="bar" style="width:{round(mine_v * 80)}px"></span></span>'
                f'<span class="mono">{mine_v * 100:.0f}%</span>'
            )
            national_cell = f"{nat_v * 100:.0f}%" if nat_v is not None else "—"
            table_rows.append([label, bar, national_cell, f"{qual['weights'][key]:.2f}"])
        parts.append(
            _table(
                [("Rate", "desc"), ("Yours", "tag"), ("National", "num"), ("Weight", "num")],
                table_rows,
            )
        )
        weakest = qual["weakest"]
        parts.append(
            f"<p><strong>Weakest: {_e(weakest['label'])} at "
            f"{weakest['value'] * 100:.0f}%.</strong> {_e(weakest['what_lifts_it'])}</p>"
        )
        parts.append(f'<p class="note">{_e(qual["note"])}</p>')
    else:
        parts.append('<p class="empty">No rows to score.</p>')
    parts.append("</section>")

    parts.append("<section><h2>Inventory</h2>")
    dead = inv["dead_stock"]
    tr = inv["transfers"]
    parts.append(
        '<div class="tiles">'
        + _tile("stock positions", _n(inv["positions"]), f"{_n(inv['qty_on_hand'])} units")
        + _tile("stock value", _inr(inv["value_inr"]), "your own unit values")
        + _tile(
            "dead stock",
            _inr(dead["value_inr"]),
            f"{_n(dead['positions'])} positions, {dead['rule_months']}+ months",
        )
        + _tile(
            "avoidable purchase",
            _inr(tr["as_receiver"]["avoidable_purchase_inr"]),
            f"{_n(tr['as_receiver']['count'])} transfers in",
        )
        + "</div>"
    )
    parts.append(f'<p class="note">{_e(dead["note"])}</p>')
    parts.append("<h3>Transfers in: what you are short of that sits idle elsewhere</h3>")
    parts.append(_assumption(tr["as_receiver"]["assumption"]))
    parts.append(
        _table(
            [
                ("CNMC", "code"),
                ("Material", "desc"),
                ("From", "cpse"),
                ("Qty", "num"),
                ("You hold", "num"),
                ("Avoidable purchase", "num"),
                ("Valued at", "text"),
            ],
            [
                [
                    r["cnmc"] or "—",
                    r["description"],
                    r["from_cpse"],
                    _n(r["qty"]),
                    _n(r["your_available"]),
                    _inr(r["value"]),
                    r["valued_at"] or "no price; band too narrow",
                ]
                for r in tr["as_receiver"]["rows"]
            ],
            "No sister CPSE holds idle surplus of anything you are short of.",
        )
    )
    parts.append("<h3>Transfers out: your idle surplus another CPSE is short of</h3>")
    parts.append(f'<p class="note">{_e(tr["as_source"]["note"])}</p>')
    parts.append(
        _table(
            [
                ("CNMC", "code"),
                ("Material", "desc"),
                ("To", "cpse"),
                ("Qty", "num"),
                ("Unit value", "num"),
                ("Value", "num"),
                ("Idle since", "date"),
                ("ABC", "tag"),
            ],
            [
                [
                    r["cnmc"] or "—",
                    r["description"],
                    r["to_cpse"],
                    _n(r["qty"]),
                    _price(r["unit_value"]),
                    _inr(r["value"]),
                    r["idle_since"] or "—",
                    r["abc"] + (" · critical spare" if r["critical_spare"] else ""),
                ]
                for r in tr["as_source"]["rows"]
            ],
            "None of your idle surplus matches another CPSE's shortage.",
        )
    )
    parts.append("</section>")

    jt = proc["joint_tenders"]
    pv = proc["price_variance"]
    parts.append("<section><h2>Procurement</h2>")
    parts.append(
        '<div class="tiles">'
        + _tile(
            "your orders",
            _n(proc["your_orders"]),
            f"{_n(proc['your_materials'])} materials, {proc['window_months']} months",
        )
        + _tile("your spend", _inr(proc["your_spend_inr"]))
        + _tile(
            "joint-tender materials",
            _n(jt["materials"]),
            f"{_inr(jt['your_spend_inr'])} of your spend",
        )
        + _tile(
            "saving attributable to you",
            _inr(jt["estimated_saving_yours_inr"]),
            f"at {round(jt['capture_assumption'] * 100)}% capture",
        )
        + "</div>"
    )
    parts.append(_assumption(jt["assumption"]))
    parts.append("<h3>Joint-tender candidates</h3>")
    parts.append(
        _table(
            [
                ("CNMC", "code"),
                ("Material", "desc"),
                ("Your orders", "num"),
                ("Your price", "num"),
                ("Market band", "band"),
                ("Your share", "num"),
                ("Saving, yours", "num"),
            ],
            [
                [
                    r["cnmc"] or "—",
                    r["description"],
                    _n(r["your_orders"]),
                    _price(r["your_unit_price"]),
                    _band(r["market_band"]),
                    _pct(r["your_share_of_volume"]),
                    _inr(r["estimated_saving_yours_inr"]),
                ]
                for r in jt["rows"]
            ],
            "No material you bought in the window was also bought by another CPSE.",
        )
    )
    parts.append("<h3>Where you pay above the market band</h3>")
    parts.append(f'<p class="note">{_e(pv["note"])}</p>')
    parts.append(
        _table(
            [
                ("CNMC", "code"),
                ("Material", "desc"),
                ("Your price", "num"),
                ("Market band", "band"),
                ("Above mean", "num"),
                ("Highest?", "tag"),
            ],
            [
                [
                    r["cnmc"] or "—",
                    r["description"],
                    _price(r["your_unit_price"]),
                    _band(r["market_band"]),
                    f"+{r['premium_over_mean_pct']}%"
                    if r["premium_over_mean_pct"] is not None
                    else "—",
                    "yes" if r["you_pay_the_most"] else "",
                ]
                for r in pv["rows"]
            ],
            "You pay at or below the market mean for every shared material.",
        )
    )
    parts.append(
        f'<p class="note">{_n(pv["materials_above_band_mean"])} materials above the band mean; '
        f'{_n(pv["materials_where_you_pay_the_most"])} where you pay the most of any buyer.</p>'
    )
    parts.append("</section>")

    parts.append("<section><h2>Duplicates prevented at source</h2>")
    rate = _pct(prev["prevention_rate"]) if prev["prevention_rate"] is not None else "—"
    parts.append(
        '<div class="tiles">'
        + _tile("checks", _n(prev["checks"]))
        + _tile("prevented", _n(prev["prevented"]))
        + _tile("created anyway", _n(prev["created_anyway"]))
        + _tile("prevention rate", rate, f"{_n(prev['open'])} open")
        + "</div>"
    )
    parts.append(f'<p class="note">{_e(prev["note"])}</p>')
    parts.append("</section>")

    parts.append(
        "<footer>"
        f"{_e(report['visibility']['note'])} {_e(report['period']['note'])} "
        "Figures reconcile with the executive and opportunity dashboards for the same day."
        "</footer>"
    )

    title = f"{cpse['code']} catalogue report · {period['to']}"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head>"
        f'<body><div class="page">{"".join(parts)}</div></body></html>'
    )


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------


def outbox_dir() -> Path:
    """Where an installation without SMTP keeps its sent reports: beside the
    database, or wherever SAMAN_OUTBOX_DIR points."""
    override = os.environ.get("SAMAN_OUTBOX_DIR")
    path = Path(override) if override else get_settings().db_file.parent / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _message(report: dict, html_body: str, to: list[str]) -> EmailMessage:
    settings = get_settings()
    cpse = report["cpse"]
    msg = EmailMessage()
    msg["Subject"] = f"SAMAN catalogue report · {cpse['code']} · {report['period']['to']}"
    msg["From"] = settings.saman_smtp_from
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="saman.local")
    actions = "\n".join(f"  {i}. {a['text']}" for i, a in enumerate(report["actions"], 1))
    msg.set_content(
        f"SAMAN catalogue report for {cpse['name']} ({cpse['code']}), "
        f"{report['period']['from']} to {report['period']['to']}.\n\n"
        f"What to do next:\n{actions or '  Nothing is waiting on you.'}\n\n"
        f"{report['synthetic_note']}\n\nThe full report is the HTML part of this message; "
        "the figures are attached as JSON.\n"
    )
    msg.add_alternative(html_body, subtype="html")
    msg.add_attachment(
        json.dumps(report, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=f"saman-report-{cpse['code']}-{report['period']['to']}.json",
    )
    return msg


def deliver(
    report: dict,
    html_body: str,
    to: list[str],
    db: Session | None = None,
    user: str = "system",
) -> dict:
    """Send the report, by SMTP when configured and otherwise into the outbox
    as an .eml. Records `report.sent` on the audit chain when given a session."""
    recipients = [addr.strip() for addr in to if addr and addr.strip()]
    if not recipients:
        raise ValueError("No recipient.")
    settings = get_settings()
    msg = _message(report, html_body, recipients)
    digest = hashlib.sha256(html_body.encode("utf-8")).hexdigest()
    code = report["cpse"]["code"]

    if settings.saman_smtp_host:
        with smtplib.SMTP(settings.saman_smtp_host, settings.saman_smtp_port, timeout=30) as smtp:
            if settings.saman_smtp_starttls:
                smtp.starttls()
            if settings.saman_smtp_user:
                smtp.login(settings.saman_smtp_user, settings.saman_smtp_password or "")
            smtp.send_message(msg)
        result = {"mode": "smtp", "host": settings.saman_smtp_host, "path": None}
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = outbox_dir() / f"{stamp}-{code}.eml"
        path.write_bytes(msg.as_bytes())
        result = {"mode": "outbox", "host": None, "path": str(path)}

    result.update(
        {
            "cpse": code,
            "to": recipients,
            "sha256": digest,
            "sent_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    if db is not None:
        audit.record(
            db,
            action=ACTION_SENT,
            entity=f"cpse:{code}",
            payload={
                "cpse": code,
                "to": recipients,
                "mode": result["mode"],
                "path": result["path"],
                "sha256": digest,
            },
            user=user,
        )
    return result


def last_sent(db: Session) -> dict[str, dict]:
    """cpse code -> the latest `report.sent` event's time and mode."""
    out: dict[str, dict] = {}
    for entity, ts, payload_json in db.execute(
        select(AuditEvent.entity, AuditEvent.ts, AuditEvent.payload_json)
        .where(AuditEvent.action == ACTION_SENT)
        .order_by(AuditEvent.seq)
    ).all():
        code = entity.split(":", 1)[1] if ":" in entity else entity
        payload = json.loads(payload_json or "{}")
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)  # the ledger stores UTC without saying so
        out[code] = {
            "at": ts.isoformat() if ts else None,
            "mode": payload.get("mode"),
            "to": payload.get("to", []),
        }
    return out


def listing(db: Session) -> dict:
    """Every CPSE with its contact address and when it was last sent a report."""
    sent = last_sent(db)
    rows = db.execute(
        select(Cpse.code, Cpse.name, Cpse.contact_email, func.count(RawItem.id))
        .outerjoin(RawItem, RawItem.cpse_id == Cpse.id)
        .group_by(Cpse.id)
        .order_by(Cpse.code)
    ).all()
    settings = get_settings()
    return {
        "delivery": "smtp" if settings.saman_smtp_host else "outbox",
        "outbox_dir": None if settings.saman_smtp_host else str(outbox_dir()),
        "cpses": [
            {
                "code": code,
                "name": name,
                "contact_email": email,
                "items": items,
                "last_sent": sent.get(code),
            }
            for code, name, email, items in rows
        ],
    }


# --------------------------------------------------------------------------
# The ministry roll-up: every CPSE on one page, attribution kept in bands
# --------------------------------------------------------------------------

#: What the roll-up tells a reader about each CPSE's money. The reader above
#: the CPSEs sees the estate's totals exactly; each CPSE's own savings and
#: spend are shown as a band among its peers, not as a number beside its
#: name, so the document ranks effort without publishing one company's
#: purchasing to another (§0.9b).
ROLLUP_BANDS = (
    (0.0, 0.25, "lowest quarter"),
    (0.25, 0.5, "second quarter"),
    (0.5, 0.75, "third quarter"),
    (0.75, 1.01, "top quarter"),
)


def _quarter(value: float, values: list[float]) -> str:
    """Which quarter of its peers a value sits in, as words."""
    if not values or value is None:
        return "—"
    below = sum(1 for v in values if v < value)
    share = below / max(len(values) - 1, 1)
    for low, high, label in ROLLUP_BANDS:
        if low <= share < high:
            return label
    return ROLLUP_BANDS[-1][2]


def rollup(db: Session, scope: Scope | None = None, today: date | None = None) -> dict:
    """The same report across every CPSE, for the reader above them.

    Built from the per-CPSE reports so no figure can disagree with the page a
    CPSE received. Totals are exact. Each CPSE's spend and attributable saving
    are shown as a quarter among its peers; the rest of its row (catalogue,
    coded share, duplicates, review queue, quality, prevention) is the
    coverage the ministry is entitled to read in full.
    """
    today = today or date.today()
    asked_by = scope.role if scope else "system"
    cpses = db.execute(select(Cpse).order_by(Cpse.code)).scalars().all()
    per = [cpse_report(db, c.code, scope, today) for c in cpses]
    spends = [r["procurement"]["your_spend_inr"] or 0.0 for r in per]
    savings = [r["procurement"]["joint_tenders"]["estimated_saving_yours_inr"] or 0.0 for r in per]
    rows = []
    for r, spend, saving in zip(per, spends, savings, strict=True):
        cat, dup, rev, qual, prev = (
            r["catalogue"],
            r["duplicates"],
            r["review"],
            r["quality"],
            r["prevention"],
        )
        rows.append(
            {
                "cpse": r["cpse"]["code"],
                "name": r["cpse"]["name"],
                "rows": cat["rows"],
                "coded": cat["coded"],
                "coded_share": cat["coded_share"],
                "internal_duplicate_rows": dup["internal"]["surplus_rows"],
                "shared_rows": dup["cross_cpse"]["rows"],
                "pending_review": rev["pending_total"],
                "conflicts": rev["conflicts"],
                "decisions_in_period": rev["decisions_in_period"]["total"],
                # A CPSE registered but not yet loaded has no scorecard row.
                "quality_score": (qual.get("row") or {}).get("score"),
                "quality_rank": qual.get("rank") or {"position": None, "of": None},
                "weakest": {
                    "label": (qual.get("weakest") or {}).get("label"),
                    "value": (qual.get("weakest") or {}).get("value"),
                },
                "prevented": prev["prevented"],
                "created_anyway": prev["created_anyway"],
                "spend_quarter": _quarter(spend, spends),
                "saving_quarter": _quarter(saving, savings),
                "actions": len(r["actions"]),
                "contact_email": r["cpse"]["contact_email"],
            }
        )
    # A pending pair touches two CPSEs and appears under both; the estate's
    # queue is counted once here rather than summed from the rows.
    pending_estate = (
        db.execute(select(func.count(ReviewTask.id)).where(ReviewTask.state == "pending")).scalar()
        or 0
    )
    conflicts_estate = (
        db.execute(
            select(func.count(ReviewTask.id))
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .where(ReviewTask.state == "pending", Pair.verdict == "conflict")
        ).scalar()
        or 0
    )
    totals = {
        "cpses": len(rows),
        "rows": sum(x["rows"] for x in rows),
        "coded": sum(x["coded"] for x in rows),
        "internal_duplicate_rows": sum(x["internal_duplicate_rows"] for x in rows),
        "pending_review": pending_estate,
        "conflicts": conflicts_estate,
        "decisions_in_period": sum(x["decisions_in_period"] for x in rows),
        "prevented": sum(x["prevented"] for x in rows),
        "created_anyway": sum(x["created_anyway"] for x in rows),
        "spend_inr": sum(spends),
        "estimated_saving_inr": sum(savings),
        "capture_assumption": per[0]["procurement"]["joint_tenders"]["capture_assumption"]
        if per
        else None,
    }
    totals["coded_share"] = totals["coded"] / totals["rows"] if totals["rows"] else 0.0
    period = per[0]["period"] if per else {"from": None, "to": today.isoformat(), "months": None}
    return {
        "kind": "rollup",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "requested_by": asked_by,
        "period": period,
        "synthetic_note": SYNTHETIC_NOTE,
        "redaction_note": (
            "Each CPSE's spend and attributable saving are shown as a quarter among "
            "its peers, never as a figure beside its name; the estate's totals are "
            "exact. Coverage, review and quality are shown in full. A pending pair "
            "touches two CPSEs and is listed under both, so the review column does "
            "not sum to the estate's queue."
        ),
        "totals": totals,
        "cpses": rows,
    }


def render_rollup_html(doc: dict) -> str:
    """The roll-up as one printable page, in the per-CPSE report's dress."""
    t = doc["totals"]
    period = doc["period"]
    parts: list[str] = []
    parts.append(
        "<header>"
        '<div class="kicker">SAMAN · ministry roll-up · every CPSE</div>'
        f"<h1>Catalogue harmonisation across {_n(t['cpses'])} CPSEs</h1>"
        f'<div class="meta">Generated {_e(doc["generated_at"])} · period '
        f'{_e(period.get("from"))} to {_e(period.get("to"))} · '
        f'requested by {_e(doc["requested_by"])}</div>'
        "</header>"
    )
    parts.append(f'<div class="synthetic">{_e(doc["synthetic_note"])}</div>')
    parts.append("<section><h2>The estate</h2>")
    parts.append(
        '<div class="tiles">'
        + _tile("catalogue rows", _n(t["rows"]))
        + _tile("coded", _n(t["coded"]), _pct(t["coded_share"]))
        + _tile("internal duplicate rows", _n(t["internal_duplicate_rows"]))
        + _tile("pending review", _n(t["pending_review"]), f"{_n(t['conflicts'])} conflicts")
        + _tile("decisions in period", _n(t["decisions_in_period"]))
        + _tile(
            "duplicates prevented",
            _n(t["prevented"]),
            f"{_n(t['created_anyway'])} created anyway",
        )
        + _tile("spend in window", _inr(t["spend_inr"]))
        + _tile(
            "estimated saving",
            _inr(t["estimated_saving_inr"]),
            f"at {_pct(t['capture_assumption'])} capture",
        )
        + "</div>"
    )
    parts.append(
        _assumption(
            "The saving assumes the stated share of the observed price spread is "
            "capturable at combined volume; it is an estimate, not a forecast."
        )
    )
    parts.append("</section>")

    parts.append("<section><h2>By CPSE</h2>")
    parts.append(f'<p class="note">{_e(doc["redaction_note"])}</p>')
    columns: list[Col] = [
        ("CPSE", "code"),
        ("Rows", "num"),
        ("Coded", "num"),
        ("Internal dup. rows", "num"),
        ("Shared rows", "num"),
        ("Pending review", "num"),
        ("Quality", "num"),
        ("Weakest rate", "desc"),
        ("Prevented / overrode", "num"),
        ("Spend among peers", "desc"),
        ("Saving among peers", "desc"),
        ("Actions", "num"),
    ]
    body = [
        [
            f"{row['cpse']}",
            _n(row["rows"]),
            f"{_n(row['coded'])} ({_pct(row['coded_share'])})",
            _n(row["internal_duplicate_rows"]),
            _n(row["shared_rows"]),
            f"{_n(row['pending_review'])} ({_n(row['conflicts'])} conflicts)",
            (
                f"{row['quality_score']:.3f} · #{row['quality_rank']['position']} "
                f"of {row['quality_rank']['of']}"
                if row["quality_score"] is not None
                else "no rows yet"
            ),
            (
                f"{row['weakest']['label']} {_pct(row['weakest']['value'])}"
                if row["weakest"]["label"]
                else "—"
            ),
            f"{_n(row['prevented'])} / {_n(row['created_anyway'])} overrode",
            row["spend_quarter"],
            row["saving_quarter"],
            _n(row["actions"]),
        ]
        for row in doc["cpses"]
    ]
    parts.append(_table(columns, body))
    parts.append("</section>")
    parts.append(
        "<footer>Every figure is computed from the database at generation time, from the "
        "same per-CPSE reports each company received; nothing on this page can disagree "
        "with theirs.</footer>"
    )
    title = f"Ministry roll-up · {period.get('to')}"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head>"
        f'<body><div class="page">{"".join(parts)}</div></body></html>'
    )
