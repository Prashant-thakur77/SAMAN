"""GET /api/metrics — the §0.6 evaluation report."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import cache
from ..db import get_db
from ..metrics import compute_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict:
    """Held-out precision/recall/F1, B-cubed, blocking recall, veto precision,
    per-class breakdown with the worst class named, and a naive baseline."""
    return metrics_for(db)


def metrics_for(db: Session) -> dict:
    """Over a second of scoring, memoised on the estate's version (see `cache`)."""
    return cache.memo(db, ("metrics",), lambda: compute_metrics(db))
