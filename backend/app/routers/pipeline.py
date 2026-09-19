"""Pipeline control — spec §5, §8A."""

from __future__ import annotations

import contextlib
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from .. import pipeline as pipeline_mod
from ..auth import require_roles
from ..db import get_db, session_scope
from ..models import User
from ..schemas import PipelineStatusOut

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run(incremental: bool = False) -> None:
    """Background entry point — owns its own session, never the request's."""
    # run_pipeline records the failure on the status object before it raises;
    # suppressing here keeps a bad run from killing the worker.
    with session_scope() as db, contextlib.suppress(Exception):
        pipeline_mod.run_pipeline(db, incremental=incremental)


@router.post("/run", response_model=PipelineStatusOut)
def run(
    _user: Annotated[User, Depends(require_roles("registrar", "admin", "steward"))],
    background: BackgroundTasks,
    incremental: bool = False,
    _db: Session = Depends(get_db),
) -> PipelineStatusOut:
    """Run the pipeline in the background. `incremental=true` scores only the
    rows that arrived since the last run (an onboarding upload), which is
    seconds rather than a minute; it falls back to a full run, and says so,
    when there is no earlier run to build on."""
    status = pipeline_mod.get_status()
    if status.state != "running":
        pipeline_mod.reset_status()
        background.add_task(_run, incremental)
    return PipelineStatusOut(**pipeline_mod.get_status().as_dict())


@router.get("/status", response_model=PipelineStatusOut)
def status() -> PipelineStatusOut:
    return PipelineStatusOut(**pipeline_mod.get_status().as_dict())
