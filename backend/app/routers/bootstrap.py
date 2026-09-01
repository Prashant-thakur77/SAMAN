"""First-run bootstrap — spec §8A.

A fresh database has no users, so nobody can sign in, so no role-gated button
can help. That is the one moment where an unauthenticated write is the right
answer, and the rule that makes it safe is narrow enough to state in a
sentence: **seeding is permitted only while the database contains no users at
all.** The first seed closes the door behind it, permanently, and the endpoint
answers 409 from then on.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import pipeline as pipeline_mod
from ..db import get_db, session_scope
from ..models import Cpse, RawItem, User
from ..seed import PROFILES

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])

#: The only profile the button offers. `large` exists for the §8A performance
#: run and would take a judge's browser somewhere they did not ask to go.
BOOTSTRAP_PROFILE = "demo"


class BootstrapIn(BaseModel):
    profile: str = Field(default=BOOTSTRAP_PROFILE)


def _user_count(db: Session) -> int:
    return int(db.execute(select(func.count(User.id))).scalar() or 0)


@router.get("/status")
def bootstrap_status(db: Session = Depends(get_db)) -> dict:
    """Whether this database has ever been seeded. Unauthenticated by design:
    the login screen asks before anyone can possibly be signed in."""
    users = _user_count(db)
    return {
        "empty": users == 0,
        "users": users,
        "cpses": int(db.execute(select(func.count(Cpse.id))).scalar() or 0),
        "raw_items": int(db.execute(select(func.count(RawItem.id))).scalar() or 0),
        "profile": BOOTSTRAP_PROFILE,
        "pipeline": pipeline_mod.get_status().as_dict(),
    }


def _load(profile: str) -> None:
    """Seed and run the pipeline in the background, on its own session.

    Deliberately the same sequence `make demo` runs, so a database loaded from
    the button and one loaded from the command line are the same database.
    """
    from ..erp import seed_from_catalogue
    from ..seed import (
        seed_database,
        seed_registry_activity,
        seed_smart_create_activity,
    )

    with session_scope() as db, contextlib.suppress(Exception):
        seed_database(db, profile=profile)
        seed_from_catalogue(db)
        pipeline_mod.run_pipeline(db)
        seed_registry_activity(db)
        seed_smart_create_activity(db)


@router.post("/demo-data")
def load_demo_data(
    body: BootstrapIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """Seed the demo estate. Allowed only while the database has no users."""
    if _user_count(db) > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This database is already populated. Seeding is only offered on a "
            "genuinely empty database; use `make demo` to rebuild one.",
        )
    if body.profile not in PROFILES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown profile {body.profile!r}; expected one of {sorted(PROFILES)}.",
        )
    if body.profile != BOOTSTRAP_PROFILE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Only the {BOOTSTRAP_PROFILE!r} profile can be loaded from the UI.",
        )

    background.add_task(_load, body.profile)
    return {
        "started": True,
        "profile": body.profile,
        "note": (
            "Seeding and running the pipeline. Watch /api/pipeline/status for "
            "progress; sign in as steward@cpcl.in / demo when it finishes."
        ),
    }
