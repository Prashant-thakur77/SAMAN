"""Pipeline control — spec §5, §8A."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from .. import pipeline as pipeline_mod
from ..auth import require_roles
from ..db import get_db, session_scope
from ..models import User
from ..schemas import PipelineStatusOut

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run() -> None:
    """Background entry point — owns its own session, never the request's."""
    with session_scope() as db:
        try:
            pipeline_mod.run_pipeline(db)
        except Exception:
            # run_pipeline has already recorded the failure on the status
            # object; swallowing here keeps a bad run from killing the worker.
            pass


@router.post("/run", response_model=PipelineStatusOut)
def run(
    _user: Annotated[User, Depends(require_roles("registrar", "admin", "steward"))],
    background: BackgroundTasks,
    _db: Session = Depends(get_db),
) -> PipelineStatusOut:
    status = pipeline_mod.get_status()
    if status.state != "running":
        pipeline_mod.reset_status()
        background.add_task(_run)
    return PipelineStatusOut(**pipeline_mod.get_status().as_dict())


@router.get("/status", response_model=PipelineStatusOut)
def status() -> PipelineStatusOut:
    return PipelineStatusOut(**pipeline_mod.get_status().as_dict())
