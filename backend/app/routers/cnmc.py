"""CNMC issuance — spec §5.

Registrar-only. The code is issued against an approved golden record and is
immutable once issued: a material code that changes meaning is worse than no
code at all.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..cnmc import family_for, is_valid, next_code, serial_of
from ..db import get_db
from ..models import Cluster, ClusterMember, Cnmc, GoldenRecord, Item, User

router = APIRouter(prefix="/cnmc", tags=["cnmc"])


@router.post("/issue/{golden_id}")
def issue(
    golden_id: int,
    user: Annotated[User, Depends(require_roles("registrar"))],
    db: Session = Depends(get_db),
) -> dict:
    golden = db.get(GoldenRecord, golden_id)
    if golden is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No golden record {golden_id}.")

    existing = db.execute(
        select(Cnmc).where(Cnmc.golden_id == golden_id)
    ).scalar_one_or_none()
    if existing:
        # Issuance is idempotent rather than an error: a retried request must
        # never mint a second code for the same record.
        return {"code": existing.code, "golden_id": golden_id, "already_issued": True}

    if golden.status == "conflict":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This cluster has an unresolved conflict on an identity-critical "
            "attribute. Resolve it in the workbench before issuing a code.",
        )

    class_code = db.execute(
        select(Item.class_code)
        .join(ClusterMember, ClusterMember.item_id == Item.id)
        .where(ClusterMember.cluster_id == golden.cluster_id)
        .limit(1)
    ).scalar_one_or_none() or "unclassified"

    family, _segment = family_for(class_code)
    used = {
        serial
        for code in db.execute(select(Cnmc.code)).scalars()
        if code.startswith(family) and (serial := serial_of(code)) is not None
    }
    code = next_code(class_code, used)

    record = Cnmc(golden_id=golden_id, code=code, status="active", issued_by=user.id)
    db.add(record)
    if golden.status == "draft":
        golden.status = "approved"
        golden.approved_by = user.id
    db.commit()

    return {
        "code": code,
        "golden_id": golden_id,
        "class_code": class_code,
        "issued_by": user.name,
        "already_issued": False,
    }


@router.get("/validate/{code}")
def validate(code: str) -> dict:
    """Check a code's format and Damm check digit. Public: anyone with a code
    printed on a document should be able to verify it."""
    return {"code": code.upper(), "valid": is_valid(code)}


@router.get("/{code}")
def lookup(code: str, db: Session = Depends(get_db)) -> dict:
    normalized = code.strip().upper()
    if not is_valid(normalized):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Check digit does not verify.")
    record = db.execute(select(Cnmc).where(Cnmc.code == normalized)).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No item carries that code.")
    golden = db.get(GoldenRecord, record.golden_id)
    cluster = db.get(Cluster, golden.cluster_id) if golden else None
    members = (
        db.execute(
            select(ClusterMember.item_id).where(ClusterMember.cluster_id == cluster.id)
        ).scalars().all()
        if cluster
        else []
    )
    return {
        "code": record.code,
        "status": record.status,
        "golden_id": record.golden_id,
        "std_description": golden.std_description if golden else None,
        "member_count": len(members),
    }
