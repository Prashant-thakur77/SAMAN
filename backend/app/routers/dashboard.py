"""Executive and Opportunity dashboards — spec §6.7, §6.8, §2E, §9A.

Every figure is computed from the database. Nothing here is a constant, and
every modelled number (savings, avoided purchases) travels with the assumption
that produced it (§10). The executive page's eight explanatory sections are
computed in `analytics`; this module reads the headline figures and wires the
sections in.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from .. import analytics, cache, inventory, opportunity, quality, smart_create
from ..auth import current_user_optional
from ..db import get_db
from ..models import (
    Cluster,
    ClusterMember,
    Cnmc,
    Cpse,
    Decision,
    GoldenRecord,
    Item,
    Pair,
    RawItem,
    ReviewTask,
    User,
)
from ..visibility import Scope, scope_for

router = APIRouter(prefix="/dashboard", tags=["dashboards"])


@router.get("/executive")
def executive(
    user: Annotated[User | None, Depends(current_user_optional)],
    db: Session = Depends(get_db),
) -> dict:
    """Harmonization progress across CPSEs (§6.7).

    The KPIs reconcile with `/api/metrics`: both read the same tables, and the
    duplicate count here is the same pairwise notion the metrics report.
    """
    return executive_for(db, scope_for(user))


def executive_for(db: Session, scope: Scope) -> dict:
    """The executive dashboard as `scope` sees it, memoised on the estate's
    version (see `cache`): computed once per change, not once per visitor."""
    return cache.memo(db, ("executive", scope.role, scope.cpse_code), lambda: _executive(db, scope))


def _executive(db: Session, scope: Scope) -> dict:
    items_total = db.execute(select(func.count(Item.id))).scalar() or 0
    clusters_total = db.execute(select(func.count(Cluster.id))).scalar() or 0
    codes_issued = db.execute(select(func.count(Cnmc.id))).scalar() or 0
    decisions_made = db.execute(select(func.count(Decision.id))).scalar() or 0

    # A "confirmed duplicate" is a member beyond the first in its cluster: the
    # rows that would collapse if the cluster were adopted.
    multi = (
        db.execute(
            select(func.count(ClusterMember.item_id))
            .select_from(ClusterMember)
            .group_by(ClusterMember.cluster_id)
            .having(func.count(ClusterMember.item_id) > 1)
        )
        .scalars()
        .all()
    )
    duplicates_confirmed = sum(size - 1 for size in multi)

    # Band totals come from the run record: the pair table keeps only the
    # decisions worth showing, so counting it would understate the refusals.
    run = analytics.latest_run(db)
    bands = run.stats.get("bands") if run else None
    if not bands:
        bands = dict(db.execute(select(Pair.band, func.count(Pair.id)).group_by(Pair.band)).all())
    total_pairs = sum(bands.values())
    automation = (bands.get("high", 0) + bands.get("low", 0)) / total_pairs if total_pairs else 0.0

    # The window's purchases are read once and shared by the savings ladder,
    # the KPI it ends in, and the stock-age demand signal.
    purchases = opportunity.load_purchases(db)
    savings_ladder = analytics.savings_ladder(db, scope, purchases)
    savings = next(rung for rung in savings_ladder["rungs"] if rung["key"] == "estimate")
    stock = inventory.stock_totals(db)
    dead = inventory.dead_stock(db, scope, limit=1)

    # Per-CPSE progress: how much of each catalogue now sits under a cluster
    # that carries a code.
    per_cpse = []
    for code, name in db.execute(select(Cpse.code, Cpse.name).order_by(Cpse.code)).all():
        total = (
            db.execute(select(func.count(RawItem.id)).join(Cpse).where(Cpse.code == code)).scalar()
            or 0
        )
        coded = (
            db.execute(
                select(func.count(distinct(Item.id)))
                .join(RawItem, RawItem.id == Item.raw_item_id)
                .join(Cpse, Cpse.id == RawItem.cpse_id)
                .join(ClusterMember, ClusterMember.item_id == Item.id)
                .join(GoldenRecord, GoldenRecord.cluster_id == ClusterMember.cluster_id)
                .join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
                .where(Cpse.code == code)
            ).scalar()
            or 0
        )
        per_cpse.append(
            {
                "cpse": code,
                "name": name,
                "items": total,
                "coded": coded,
                "progress": round(coded / total, 4) if total else 0.0,
            }
        )

    # Class x CPSE heatmap, rendered as grayscale intensity in the UI.
    heat = db.execute(
        select(Item.class_code, Cpse.code, func.count(Item.id))
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .group_by(Item.class_code, Cpse.code)
    ).all()
    classes = sorted({row[0] for row in heat})
    cpses = sorted({row[1] for row in heat})
    counts = {(row[0], row[1]): row[2] for row in heat}
    peak = max(counts.values(), default=0)

    pending = db.execute(
        select(ReviewTask.band, func.count(ReviewTask.id))
        .where(ReviewTask.state == "pending")
        .group_by(ReviewTask.band)
    ).all()

    # Harmonization activity over time, from what actually happened. Empty
    # until the first code is issued, which is the honest state (§10).
    issued_by_day = db.execute(
        select(func.date(Cnmc.issued_at), func.count(Cnmc.id))
        .group_by(func.date(Cnmc.issued_at))
        .order_by(func.date(Cnmc.issued_at))
    ).all()
    decided_by_day = db.execute(
        select(func.date(Decision.ts), func.count(Decision.id))
        .group_by(func.date(Decision.ts))
        .order_by(func.date(Decision.ts))
    ).all()
    days = sorted({str(d) for d, _ in issued_by_day} | {str(d) for d, _ in decided_by_day})
    issued_map = {str(d): n for d, n in issued_by_day}
    decided_map = {str(d): n for d, n in decided_by_day}
    running = 0
    trend = []
    for day in days:
        running += issued_map.get(day, 0)
        trend.append(
            {
                "date": day,
                "cnmcs_issued": issued_map.get(day, 0),
                "cnmcs_total": running,
                "decisions": decided_map.get(day, 0),
            }
        )

    prevention = smart_create.stats(db)

    # Three disjoint parts over every catalogue row, decided row by row and
    # summed: the donut is the family bars added up, so the two reconcile.
    by_class = analytics.by_class(db)
    harmonisation = analytics.harmonisation(by_class)

    # The two sections that can only be measured while the pipeline runs read
    # what it recorded; an older run falls back to the stored pairs and says so.
    tally = analytics.tally_for(db, run)
    evaluation = analytics.evaluation(db, run)

    return {
        "kpis": [
            {"key": "items", "label": "Catalogue rows", "value": items_total},
            {"key": "clusters", "label": "Materials identified", "value": clusters_total},
            {
                "key": "duplicates",
                "label": "Duplicates confirmed",
                "value": duplicates_confirmed,
                "note": "Rows that collapse when their cluster is adopted.",
            },
            {"key": "cnmcs", "label": "CNMCs issued", "value": codes_issued},
            {
                "key": "automation",
                "label": "Decided without a human",
                "value": round(automation, 4),
                "format": "percent",
            },
            {
                "key": "savings",
                "label": "Savings identified",
                "value": savings["value_inr"],
                "format": "currency",
                "note": savings["assumption"],
            },
            {
                # The only KPI that counts duplicates that never happened. The
                # rest of this dashboard measures cleaning up; this one measures
                # the mess not being made.
                "key": "prevented",
                "label": "Duplicates prevented at source",
                "value": prevention["prevented"],
                "note": "Checks where the requester reused an existing material.",
            },
        ],
        "per_cpse": per_cpse,
        "heatmap": {
            "classes": classes,
            "cpses": cpses,
            "peak": peak,
            "cells": [
                {
                    "class_code": class_code,
                    "cpse": cpse,
                    "count": counts.get((class_code, cpse), 0),
                    "intensity": round(counts.get((class_code, cpse), 0) / peak, 4)
                    if peak
                    else 0.0,
                }
                for class_code in classes
                for cpse in cpses
            ],
        },
        "review": {
            "pending": dict(pending),
            "decisions_made": decisions_made,
        },
        # The promised "improved data quality", measured per catalogue.
        "quality": quality.scorecard(db),
        # Where the estate stands, as three disjoint parts of one whole. The
        # KPIs count things; this says what share of the catalogue is actually
        # through the process, which is the question the dashboard exists for.
        "harmonisation": harmonisation,
        # The same three parts per material family, and how many CPSEs
        # describe each material: where the estate stands, one level down.
        "by_class": by_class,
        "by_cpse_count": analytics.by_cpse_count(db),
        # How the machine decided: the ladder of pairs, what vetoed the
        # look-alikes, why pairs wait for a human, and the held-out scorecard.
        "pipeline": analytics.pipeline(db, run),
        "veto_attributes": analytics.veto_attributes(db, run, tally),
        "held_for_review": analytics.held_for_review(db, run, evaluation, tally),
        "evaluation": evaluation,
        "trend": trend,
        # What it is worth: the ladder the savings KPI is the bottom rung of,
        # and the stock that has stopped moving, with the dead-stock rule drawn.
        "savings_ladder": savings_ladder,
        "inventory": {
            "positions": stock["positions"],
            "total_value": stock["total_value"],
            "dead_stock_value": dead["total_value"],
            "dead_stock_materials": dead["materials_found"],
        },
        "stock_age": analytics.stock_age(db, purchases),
        "visibility": scope.as_dict(),
    }


@router.get("/opportunity")
def opportunity_dashboard(
    user: Annotated[User | None, Depends(current_user_optional)],
    capture: float = Query(default=opportunity.DEFAULT_CAPTURE, ge=0.4, le=0.8),
    db: Session = Depends(get_db),
) -> dict:
    """Joint tenders, price variance and inventory sharing (§6.8, §2E).

    `capture` is the what-if slider's discount assumption. It is a parameter
    rather than a constant precisely because it is an assumption, and the
    response repeats it so no figure travels without it.
    """
    return opportunity_for(db, scope_for(user), capture)


def opportunity_for(
    db: Session, scope: Scope, capture: float = opportunity.DEFAULT_CAPTURE
) -> dict:
    return cache.memo(
        db,
        ("opportunity", scope.role, scope.cpse_code, capture),
        lambda: _opportunity(db, scope, capture),
    )


def _opportunity(db: Session, scope: Scope, capture: float) -> dict:
    return {
        "joint_tenders": opportunity.joint_tender_candidates(db, scope, capture=capture),
        "price_variance": opportunity.price_variance(db, scope),
        "vendor_overlap": opportunity.vendor_overlap(db),
        "inventory": {
            "transfers": inventory.transfer_suggestions(db, scope),
            "dead_stock": inventory.dead_stock(db, scope),
            "totals": inventory.stock_totals(db),
        },
        "visibility": scope.as_dict(),
    }
