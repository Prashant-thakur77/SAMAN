"""Privacy-preserving record linkage — restricted mode (spec §5, M10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import pprl
from ..auth import require_roles
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/pprl", tags=["pprl"])

ANALYST = ("registrar", "admin", "approver", "steward", "auditor")
NATIONAL = ("registrar", "admin", "auditor")


class EncodeIn(BaseModel):
    cpse: str = Field(min_length=1, max_length=16)
    key: str = Field(min_length=16, max_length=128)
    mode: str = Field(default=pprl.DEFAULT_MODE)
    limit: int = Field(default=500, ge=1, le=5_000)


class CompareIn(BaseModel):
    left: list[dict]
    right: list[dict]
    mode: str = Field(default=pprl.DEFAULT_MODE)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    limit: int = Field(default=200, ge=1, le=2_000)


@router.get("/key")
def key(_user: Annotated[User, Depends(require_roles(*ANALYST))]) -> dict:
    """A fresh exchange key. Both parties must agree on one before encoding."""
    return {
        "key": pprl.new_key(),
        "note": (
            "Share this out of band with the other CPSE. Encodings made under "
            "different keys cannot be compared, and the key is the only thing "
            "protecting the encodings from being inverted."
        ),
    }


@router.get("/modes")
def modes(_user: Annotated[User, Depends(require_roles(*ANALYST))]) -> dict:
    return {
        "default": pprl.DEFAULT_MODE,
        "modes": {
            name: {**settings, "description": _MODE_NOTES[name]}
            for name, settings in pprl.MODES.items()
        },
    }


_MODE_NOTES = {
    "attribute": (
        "Hashes the extracted class and attributes. Both sides run SAMAN's own "
        "extractor first, so a 25 mm bore and a 30 mm bore differ by a whole "
        "feature rather than two characters."
    ),
    "ngram": (
        "Hashes character 3-grams of the normalized description — the classic "
        "construction. Measurably weaker here, and kept so the comparison is "
        "on the table rather than asserted."
    ),
}


@router.post("/encode")
def encode(
    body: EncodeIn,
    user: Annotated[User, Depends(require_roles(*ANALYST))],
    db: Session = Depends(get_db),
) -> dict:
    """Encode a catalogue locally. The response carries no plaintext.

    A steward may encode their own CPSE and no other: restricted mode exists
    because organisations do not want to hand over catalogues, and an endpoint
    that let one of them encode a competitor's would defeat the point.
    """
    own = user.cpse.code if user.cpse else None
    if user.role not in NATIONAL and body.cpse.upper() != (own or "").upper():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only encode your own catalogue. Ask the other CPSE to "
            "encode theirs and send you the encodings.",
        )
    try:
        return pprl.encode_catalogue(db, body.cpse.upper(), body.key, body.limit, body.mode)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/compare")
def compare(
    body: CompareIn,
    _user: Annotated[User, Depends(require_roles(*ANALYST))],
) -> dict:
    """Dice-compare two encoding sets. No database is touched."""
    try:
        return pprl.compare(
            body.left, body.right, body.threshold, mode=body.mode, limit=body.limit
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/evaluate")
def evaluate(
    left: str,
    right: str,
    _user: Annotated[User, Depends(require_roles(*NATIONAL))],
    mode: str = pprl.DEFAULT_MODE,
    limit: int = 300,
    db: Session = Depends(get_db),
) -> dict:
    """What restricted mode costs, measured against the plaintext truth table.

    National roles only: it reads the ground truth, which no CPSE has.
    """
    from ..pprl_eval import evaluate as run

    try:
        return run(db, left.upper(), right.upper(), mode=mode, limit=limit)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
