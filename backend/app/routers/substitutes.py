"""Approved substitutes: the engineer's queue and decision."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import substitutes
from ..auth import require_user
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/substitutes", tags=["substitutes"])


@router.get("")
def list_substitutes(
    _user: Annotated[User, Depends(require_user)],
    status_filter: str = Query(default="proposed", alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    if status_filter not in (*substitutes.STATUSES, "all"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {', '.join(substitutes.STATUSES)} or all.",
        )
    return substitutes.list_relations(db, status_filter, limit, offset)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/{relation_id}/decide")
def decide(
    relation_id: int,
    body: DecisionIn,
    user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """Engineer, registrar or admin. The role check lives in the module so the
    error names the roles rather than saying only 403."""
    return substitutes.decide(db, relation_id, body.decision, body.reason, user)
