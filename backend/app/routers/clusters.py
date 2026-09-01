"""Cluster and golden-record detail — spec §5, §6.6, §2D.

`GET /api/clusters/{id}` is where §2D's acceptance criterion lands: the golden
record comes back with per-field provenance, so "where did this description
come from?" has an exact answer, and with a standardization delta per member,
because that delta is what a CPSE actually reviews.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Cluster,
    ClusterMember,
    Cnmc,
    Cpse,
    GoldenFieldProvenance,
    GoldenRecord,
    Item,
    RawItem,
)
from ..standardize import Member, standardization_delta, standardize
from ..taxonomy import get_schema

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("/{cluster_id}")
def get_cluster(cluster_id: int, db: Session = Depends(get_db)) -> dict:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No cluster {cluster_id}.")

    rows = db.execute(
        select(
            Item.id,
            Item.norm_text,
            Item.class_code,
            Item.attrs_json,
            Item.mpn_norm,
            RawItem.legacy_code,
            RawItem.description,
            RawItem.uom,
            RawItem.plant,
            Cpse.code,
        )
        .join(ClusterMember, ClusterMember.item_id == Item.id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .where(ClusterMember.cluster_id == cluster_id)
        .order_by(Item.id)
    ).all()

    golden = db.execute(
        select(GoldenRecord).where(GoldenRecord.cluster_id == cluster_id)
    ).scalar_one_or_none()

    code = (
        db.execute(select(Cnmc).where(Cnmc.golden_id == golden.id)).scalar_one_or_none()
        if golden
        else None
    )

    members = []
    fusion_members = []
    for (
        item_id, norm_text, class_code, attrs_json, mpn,
        legacy_code, description, uom, plant, cpse_code,
    ) in rows:
        attrs = json.loads(attrs_json or "{}")
        members.append(
            {
                "item_id": item_id,
                "cpse": cpse_code,
                "legacy_code": legacy_code,
                "description": description,
                "normalized": norm_text,
                "class_code": class_code,
                "mpn_norm": mpn,
                "plant": plant,
                "uom": uom,
                "attrs": {k: v for k, v in attrs.items() if not k.startswith("_")},
            }
        )
        fusion_members.append(
            Member(
                id=item_id,
                attrs={k: v for k, v in attrs.items() if not k.startswith("_")},
                sources=attrs.get("_sources", {}),
                norm_text=norm_text or "",
            )
        )

    # Re-run standardization to expose the candidate values behind each field.
    # The stored description is authoritative; this reproduces the reasoning.
    schema = get_schema(rows[0][2] if rows else "unclassified")
    recomputed = standardize(fusion_members, schema) if fusion_members else None

    stored_provenance = (
        db.execute(
            select(
                GoldenFieldProvenance.field,
                GoldenFieldProvenance.source_member_id,
                GoldenFieldProvenance.rule,
            ).where(GoldenFieldProvenance.golden_id == golden.id)
        ).all()
        if golden
        else []
    )
    candidates_by_field = (
        {f.field: f.candidates for f in recomputed.provenance} if recomputed else {}
    )

    return {
        "cluster_id": cluster_id,
        "status": cluster.status,
        "member_count": len(members),
        "class_code": schema.code,
        "golden": (
            {
                "id": golden.id,
                "std_description": golden.std_description,
                "attrs": json.loads(golden.attrs_json or "{}"),
                "status": golden.status,
                "template": schema.template,
                "proposed_by": golden.proposed_by,
                "approved_by": golden.approved_by,
            }
            if golden
            else None
        ),
        "cnmc": {"code": code.code, "status": code.status} if code else None,
        # §2D: every fused field, which member it came from and which rule chose it.
        "provenance": [
            {
                "field": field,
                "source_member_id": source_member_id,
                "rule": rule,
                "candidates": candidates_by_field.get(field, []),
            }
            for field, source_member_id, rule in stored_provenance
        ],
        "conflicts": recomputed.conflicts if recomputed else [],
        "members": members,
        # §2D: what changed from each legacy description to the golden text.
        "standardization_delta": (
            [
                standardization_delta(member, golden.std_description)
                for member in fusion_members
            ]
            if golden
            else []
        ),
    }
