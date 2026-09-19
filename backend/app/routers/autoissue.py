"""Automatic code issue under a registrar's policy (see `autoissue`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import autoissue, cache
from ..auth import require_roles
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/autoissue", tags=["cnmc"])

REGISTRAR = ("registrar",)


class PolicyIn(BaseModel):
    enabled: bool
    min_precision: float = Field(default=autoissue.DEFAULT_MIN_PRECISION, ge=0.9, le=1.0)


class RunIn(BaseModel):
    dry_run: bool = True
    family: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)


@router.get("/status")
def read_status(
    _user: Annotated[User, Depends(require_roles("registrar", "admin", "auditor"))],
    db: Session = Depends(get_db),
) -> dict:
    """Per family: the policy, the class precision it is judged on, and how
    many clusters would issue today. Readable by those who audit as well as
    the one who sets it."""
    # Every draft cluster is gated; memoised on the estate's version, which
    # a policy change, a decision or an issue moves.
    return cache.memo(db, ("autoissue.status",), lambda: autoissue.status(db))


@router.put("/policy/{family}")
def set_policy(
    family: str,
    body: PolicyIn,
    user: Annotated[User, Depends(require_roles(*REGISTRAR))],
    db: Session = Depends(get_db),
) -> dict:
    """Turn a family's automatic issue on or off, with the precision it must
    show. Registrar only: this is the policy the codes will carry their name on."""
    try:
        policy = autoissue.set_policy(db, family.upper(), body.enabled, body.min_precision, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        "family": policy.family,
        "enabled": policy.enabled,
        "min_precision": policy.min_precision,
        "set_by": policy.set_by,
        "set_at": policy.set_at.isoformat() if policy.set_at else None,
    }


@router.post("/run")
def run(
    body: RunIn,
    _user: Annotated[User, Depends(require_roles(*REGISTRAR))],
    db: Session = Depends(get_db),
) -> dict:
    """Issue every eligible code now, or list what would issue (`dry_run`).
    The nightly cron calls the same function through the CLI."""
    return autoissue.run(db, dry_run=body.dry_run, limit=body.limit, family=body.family)
