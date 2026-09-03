"""Learning from the Workbench: status, training, the demo's simulated labels,
and the labelled corpus as a download."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, learn
from ..auth import require_roles, require_user
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/learn", tags=["learn"])

#: Training rewrites the model every reviewer sees; that is a registrar's call.
TRAINER = ("registrar", "admin")
#: The corpus contains every reviewed pair; auditors may read it too.
READER = ("registrar", "admin", "auditor")


@router.get("/status")
def learn_status(
    _user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    return learn.status(db)


@router.post("/train")
def train(
    user: Annotated[User, Depends(require_roles(*TRAINER))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        model = learn.train(db)
    except learn.NotEnoughLabels as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.record(
        db,
        action="learn.train",
        entity="model:pairwise",
        payload={
            "labels": model.n_labels,
            "by_source": model.labels,
            "cv": model.cv,
            "holdout": model.holdout,
            "weights": model.weights(),
        },
        user=user.email,
    )
    return learn.status(db)


class SimulateIn(BaseModel):
    n: int = Field(default=400, ge=10, le=5000)


@router.post("/simulate")
def simulate(
    body: SimulateIn,
    user: Annotated[User, Depends(require_roles(*TRAINER))],
    db: Session = Depends(get_db),
) -> dict:
    """Demo only: answer tuning-split pairs from the seed's ground truth, as
    simulated reviewers. Never touches the held-out split, never a task."""
    result = learn.simulate_labels(db, body.n)
    audit.record(
        db,
        action="learn.simulate",
        entity="model:pairwise",
        payload=result,
        user=user.email,
    )
    return {"simulated": result, **learn.status(db)}


@router.get("/corpus")
def corpus(
    _user: Annotated[User, Depends(require_roles(*READER))],
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Every labelled pair as JSON lines: the training set a future fine-tune
    of the local language model would need."""
    lines = list(learn.corpus(db))
    return StreamingResponse(
        iter(lines),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="saman-pair-labels.jsonl"'},
    )
