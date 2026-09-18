"""GET /api/scan/lookup — what a scanned code is (see `scan`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import scan
from ..auth import require_user
from ..db import get_db
from ..models import User
from ..visibility import scope_for

router = APIRouter(prefix="/scan", tags=["scan"])


@router.get("/lookup")
def lookup(
    user: Annotated[User, Depends(require_user)],
    code: Annotated[str, Query(min_length=1, max_length=scan.MAX_CODE_LENGTH)],
    db: Session = Depends(get_db),
) -> dict:
    """Resolve a barcode, a label or a typed code to the material it names.

    Every signed-in role may ask; other CPSEs' valuations in the stock
    positions are withheld from a steward the way they are everywhere else.
    """
    return scan.lookup(db, code, scope_for(user))
