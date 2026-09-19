"""GET /api/scan/lookup — what a scanned code is (see `scan`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, scan
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


class WrongItemIn(BaseModel):
    code: str = Field(min_length=1, max_length=scan.MAX_CODE_LENGTH)
    matched_by: str | None = Field(default=None, max_length=32)
    cluster_id: int | None = None
    item_id: int | None = None
    cnmc: str | None = Field(default=None, max_length=32)
    #: What the person in front of the shelf saw instead, in their words.
    note: str | None = Field(default=None, max_length=500)


@router.post("/report")
def report_wrong_item(
    body: WrongItemIn,
    user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """ "Wrong item?": the scan resolved, but the part in hand is not the one
    on screen. Recorded on the audit chain with the code, what it resolved
    to and the reporter's words, so a steward can find the mislabelled bin or
    the wrong cross-reference. Nothing is changed by the report itself: a
    mistake at the shelf is a fact for a person to act on, not a merge or a
    split."""
    event = audit.record(
        db,
        action="scan.wrong_item",
        entity=f"cluster:{body.cluster_id}" if body.cluster_id else f"code:{body.code}",
        payload={
            "code": body.code,
            "matched_by": body.matched_by,
            "cluster_id": body.cluster_id,
            "item_id": body.item_id,
            "cnmc": body.cnmc,
            "note": body.note,
            "cpse_id": user.cpse_id,
        },
        user=user.email,
    )
    return {
        "recorded": True,
        "seq": event.seq,
        "note": (
            "Recorded on the ledger for a steward to look at. The material record is "
            "unchanged; if the bin is mislabelled, the label screen prints a new one."
        ),
    }
