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

from ..auth import enforce_separation_of_duties, require_roles
from ..cnmc import ConflictError, is_valid, issue_code
from ..db import get_db
from ..models import Cluster, ClusterMember, Cnmc, GoldenRecord, User

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

    # §0.9: whoever proposed or edited this record may not also approve it.
    # Checked before issuance because separation of duties is an authorisation
    # question, not a data question.
    enforce_separation_of_duties(golden, user)

    try:
        return issue_code(db, golden, user)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


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
