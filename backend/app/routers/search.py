"""Catalogue search — spec §5, §6.3.

Paginated server-side with a total count (§8A): the result set is the whole
estate, and a 150k-row table cannot be shipped to the browser to be filtered
there.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Cluster, ClusterMember, Cnmc, Cpse, GoldenRecord, Item, RawItem
from ..taxonomy import load_schemas

router = APIRouter(tags=["search"])

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]*")


@router.get("/items")
def search_items(
    search: str | None = None,
    cpse: str | None = None,
    class_code: str | None = Query(default=None, alias="class"),
    has_cnmc: bool | None = None,
    limit: int = Query(default=25, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    """Search normalized text, legacy codes and anchor keys, with filters."""
    query = (
        select(
            Item.id,
            Item.norm_text,
            Item.class_code,
            Item.mpn_norm,
            Item.attrs_json,
            RawItem.legacy_code,
            RawItem.description,
            Cpse.code,
            ClusterMember.cluster_id,
        )
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .outerjoin(ClusterMember, ClusterMember.item_id == Item.id)
    )

    tokens = _TOKEN.findall((search or "").upper())[:6]
    if tokens:
        # Every token must appear, so "6205 SKF" narrows rather than widens,
        # and each must start a token in the text. A plain substring match
        # returns a cable whose barcode happens to contain 6205; padding the
        # field and anchoring to a token start is what keeps "6205" meaning the
        # bearing designation and still matching "6205-2Z" and "6205ZZ".
        padded_text = func.concat(" ", Item.norm_text, " ")
        padded_code = func.concat(" ", RawItem.legacy_code, " ")
        for token in tokens:
            starts = f"% {token}%"
            query = query.where(
                or_(
                    padded_text.like(starts),
                    padded_code.like(starts),
                    Item.mpn_norm.like(f"{token}%"),
                )
            )
    if cpse:
        query = query.where(Cpse.code == cpse.upper())
    if class_code:
        query = query.where(Item.class_code == class_code)
    if has_cnmc is not None:
        coded = select(GoldenRecord.cluster_id).join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
        query = query.where(
            ClusterMember.cluster_id.in_(coded)
            if has_cnmc
            else ClusterMember.cluster_id.notin_(coded)
        )

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0

    # Shorter descriptions rank first: a row that is mostly the searched term is
    # a better answer than one that merely contains it.
    ordering = (func.length(Item.norm_text), Item.id) if tokens else (Item.id,)
    rows = db.execute(query.order_by(*ordering).offset(offset).limit(limit)).all()

    cluster_ids = [row[8] for row in rows if row[8]]
    codes = (
        dict(
            db.execute(
                select(GoldenRecord.cluster_id, Cnmc.code)
                .join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
                .where(GoldenRecord.cluster_id.in_(cluster_ids))
            ).all()
        )
        if cluster_ids
        else {}
    )
    sizes = (
        dict(
            db.execute(
                select(ClusterMember.cluster_id, func.count(ClusterMember.item_id))
                .where(ClusterMember.cluster_id.in_(cluster_ids))
                .group_by(ClusterMember.cluster_id)
            ).all()
        )
        if cluster_ids
        else {}
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "query": {"search": search, "cpse": cpse, "class": class_code, "has_cnmc": has_cnmc},
        "items": [
            {
                "item_id": row[0],
                "normalized": row[1],
                "class_code": row[2],
                "mpn_norm": row[3],
                "brand": json.loads(row[4] or "{}").get("brand"),
                "legacy_code": row[5],
                "description": row[6],
                "cpse": row[7],
                "cluster_id": row[8],
                "cluster_size": sizes.get(row[8], 1),
                "cnmc": codes.get(row[8]),
            }
            for row in rows
        ],
    }


@router.get("/facets")
def facets(db: Session = Depends(get_db)) -> dict:
    """The filter options a search screen needs, from the data itself."""
    return {
        "cpses": [
            {"code": code, "name": name, "items": count}
            for code, name, count in db.execute(
                select(Cpse.code, Cpse.name, func.count(RawItem.id))
                .join(RawItem, RawItem.cpse_id == Cpse.id)
                .group_by(Cpse.code, Cpse.name)
                .order_by(Cpse.code)
            ).all()
        ],
        "classes": [
            {"class_code": class_code, "label": load_schemas()[class_code].label
             if class_code in load_schemas() else class_code, "items": count}
            for class_code, count in db.execute(
                select(Item.class_code, func.count(Item.id))
                .group_by(Item.class_code)
                .order_by(func.count(Item.id).desc())
            ).all()
        ],
        "totals": {
            "items": db.execute(select(func.count(Item.id))).scalar() or 0,
            "clusters": db.execute(select(func.count(Cluster.id))).scalar() or 0,
            "cnmcs": db.execute(select(func.count(Cnmc.id))).scalar() or 0,
        },
    }
