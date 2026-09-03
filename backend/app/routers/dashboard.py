"""Executive and Opportunity dashboards — spec §6.7, §6.8, §2E, §9A.

Every figure is computed from the database. Nothing here is a constant, and
every modelled number (savings, avoided purchases) travels with the assumption
that produced it (§10).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from .. import inventory, opportunity, quality, smart_create
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
    MatchRun,
    Pair,
    RawItem,
    ReviewTask,
    User,
)
from ..visibility import scope_for

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
    scope = scope_for(user)

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

    bands = dict(db.execute(select(Pair.band, func.count(Pair.id)).group_by(Pair.band)).all())
    run = db.execute(select(MatchRun.stats_json).order_by(MatchRun.id.desc()).limit(1)).scalar()
    if run:
        import json

        bands = json.loads(run).get("bands", bands)
    total_pairs = sum(bands.values())
    automation = (bands.get("high", 0) + bands.get("low", 0)) / total_pairs if total_pairs else 0.0

    savings = opportunity.joint_tender_candidates(db, scope, limit=1)
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
                "value": savings["total_estimated_saving"],
                "format": "currency",
                "note": savings["assumption_note"],
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
        "trend": trend,
        "inventory": {
            "positions": stock["positions"],
            "total_value": stock["total_value"],
            "dead_stock_value": dead["total_value"],
            "dead_stock_materials": dead["materials_found"],
        },
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
    scope = scope_for(user)
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
