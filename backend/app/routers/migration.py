"""ERP migration endpoints — spec §5, §2C, §6.12."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import erp, migration, visibility
from ..auth import require_roles
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/migration", tags=["migration"])

REGISTRAR = ("registrar", "admin")
PLANNER = ("registrar", "admin", "approver", "steward")


class Selection(BaseModel):
    cluster_ids: list[int] | None = None


class PlanIn(Selection):
    """Reading a plan is windowed; applying one never is.

    A full rollout plans one change per catalogue row, so the response and the
    DOM both need a bound — but an apply that silently acted on page one only
    would be a data-integrity bug, so `ApplyIn` deliberately has no window.
    """

    limit: int = Field(default=migration.DEFAULT_PAGE, ge=1, le=migration.MAX_PAGE)
    offset: int = Field(default=0, ge=0)


class ApplyIn(Selection):
    #: Held records are excluded by default; overriding is a deliberate act.
    include_held: bool = False


@router.get("/erp")
def erp_state(
    _user: Annotated[User, Depends(require_roles(*PLANNER))],
) -> dict:
    """What the mock ERP currently holds, so the write-back is visible."""
    with erp.connect() as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in erp.TABLES
        }
        blocked = conn.execute("SELECT COUNT(*) FROM mara WHERE lvorm = 'X'").fetchone()[0]
        coded = conn.execute("SELECT COUNT(*) FROM mara WHERE zz_cnmc <> ''").fetchone()[0]
        sample = [
            dict(row)
            for row in conn.execute(
                "SELECT matnr, lvorm, zz_cnmc, zz_supersedes FROM mara "
                "WHERE zz_cnmc <> '' OR lvorm = 'X' ORDER BY matnr LIMIT 10"
            )
        ]
    return {
        "system": "mock SAP (MARA / MAKT / EKPO / MARD / MBEW)",
        "database": str(erp.erp_path()),
        "counts": counts,
        "materials_blocked": blocked,
        "materials_cross_referenced": coded,
        "fingerprint": erp.fingerprint(),
        "sample": sample,
        "note": (
            "A superseded material is blocked, never deleted — the row and its "
            "history stay, which is how a real consolidation is done."
        ),
    }


def _scoped(planned: dict, user: User) -> dict:
    """Apply the §0.9b price policy to a migration plan.

    A plan names every duplicate across every CPSE, so it would otherwise hand
    a steward the stock valuation of a competitor's warehouse. The rows stay --
    seeing that four CPSEs hold the same bearing is the point -- but the money
    goes through the same gate as the dashboards and the Copilot.
    """
    scope = visibility.scope_for(user)
    planned["changes"] = visibility.redact_prices(planned["changes"], scope)
    planned["visibility"] = scope.as_dict()
    return planned


@router.post("/plan")
def plan(
    body: PlanIn,
    user: Annotated[User, Depends(require_roles(*PLANNER))],
    db: Session = Depends(get_db),
) -> dict:
    planned = migration.plan(db, body.cluster_ids)
    return _scoped(migration.paginate(planned, body.limit, body.offset), user)


@router.post("/dryrun")
def dryrun(
    body: PlanIn,
    user: Annotated[User, Depends(require_roles(*PLANNER))],
    db: Session = Depends(get_db),
) -> dict:
    planned = migration.dry_run(db, body.cluster_ids)
    return _scoped(migration.paginate(planned, body.limit, body.offset), user)


@router.post("/apply")
def apply(
    body: ApplyIn,
    user: Annotated[User, Depends(require_roles(*REGISTRAR))],
    db: Session = Depends(get_db),
) -> dict:
    """Registrar-only, batch-scoped (§2C)."""
    return migration.apply(db, user, body.cluster_ids, body.include_held)


@router.post("/rollback/{batch_id}")
def rollback(
    batch_id: int,
    user: Annotated[User, Depends(require_roles(*REGISTRAR))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return migration.rollback(db, batch_id, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/batches")
def batches(
    _user: Annotated[User, Depends(require_roles(*PLANNER))],
    db: Session = Depends(get_db),
) -> dict:
    return migration.batches(db)


@router.get("/batches/{batch_id}")
def batch_detail(
    batch_id: int,
    _user: Annotated[User, Depends(require_roles(*PLANNER))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return migration.batch_detail(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
