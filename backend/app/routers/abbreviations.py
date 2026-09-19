"""The house abbreviation dictionary (see `abbreviations`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import abbreviations
from ..auth import require_roles, require_user
from ..db import get_db
from ..models import User
from ..normalize import normalize_row

router = APIRouter(prefix="/abbreviations", tags=["taxonomy"])

EDITORS = ("steward", "approver", "registrar", "admin")


class AbbreviationIn(BaseModel):
    token: str = Field(min_length=1, max_length=32)
    expansion: str = Field(min_length=1, max_length=128)
    cpse_code: str | None = Field(default=None, max_length=16)
    note: str | None = Field(default=None, max_length=300)


class PreviewIn(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    cpse_code: str | None = Field(default=None, max_length=16)


@router.get("")
def list_abbreviations(
    _user: Annotated[User, Depends(require_user)],
    cpse: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return abbreviations.listing(db, cpse)


@router.post("")
def add_abbreviation(
    body: AbbreviationIn,
    user: Annotated[User, Depends(require_roles(*EDITORS))],
    db: Session = Depends(get_db),
) -> dict:
    """Teach the platform a word. A steward teaches their own CPSE's; a
    registrar or admin may teach every catalogue. Audited."""
    try:
        row = abbreviations.add(db, user, body.token, body.expansion, body.cpse_code, body.note)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"added": row.id, **abbreviations.listing(db, body.cpse_code)}


@router.delete("/{abbreviation_id}")
def retire_abbreviation(
    abbreviation_id: int,
    user: Annotated[User, Depends(require_roles(*EDITORS))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = abbreviations.retire(db, user, abbreviation_id)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"retired": row.id}


@router.post("/preview")
def preview(
    body: PreviewIn,
    _user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """How a description normalises with the house words in force, beside how
    it normalises without them: what a new word will change."""
    from sqlalchemy import select

    from ..models import Cpse

    cpse_id = (
        db.execute(select(Cpse.id).where(Cpse.code == body.cpse_code.upper())).scalar()
        if body.cpse_code
        else None
    )
    with_house = normalize_row(body.description, None, abbreviations.for_cpse(db, cpse_id))
    without = normalize_row(body.description, None, None)
    return {
        "description": body.description,
        "built_in_only": without.norm_text,
        "with_house_words": with_house.norm_text,
        "changed": with_house.norm_text != without.norm_text,
    }
