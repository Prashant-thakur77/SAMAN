"""Smart-Create endpoints — duplicate prevention at source (spec §5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import smart_create
from ..auth import require_roles
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/smart-create", tags=["smart-create"])

#: Anyone who can create a material can run the check. Viewers and auditors
#: cannot, because for them it would be a way to probe another CPSE's
#: catalogue by description.
CREATOR = ("registrar", "admin", "approver", "steward")


class CheckIn(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    mpn: str | None = None
    uom: str | None = None
    limit: int = Field(default=smart_create.TOP_N, ge=1, le=20)


class ReuseIn(BaseModel):
    check_id: int
    item_id: int


class CreateIn(BaseModel):
    create_token: str
    legacy_code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    uom: str | None = None
    reason: str | None = None


@router.post("/check")
def check(
    body: CheckIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return smart_create.check(db, body.description, body.mpn, body.uom, user, body.limit)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/reuse")
def reuse(
    body: ReuseIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return smart_create.reuse(db, body.check_id, body.item_id, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/create")
def create(
    body: CreateIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return smart_create.create_anyway(
            db, body.create_token, body.legacy_code, body.description,
            body.uom, body.reason, user,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/stats")
def stats(
    _user: Annotated[User, Depends(require_roles(*CREATOR, "auditor", "viewer"))],
    db: Session = Depends(get_db),
) -> dict:
    return smart_create.stats(db)
