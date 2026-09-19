"""Smart-Create endpoints — duplicate prevention at source (spec §5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, ocr, ocr_eval, smart_create
from ..auth import require_roles
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/smart-create", tags=["smart-create"])

#: Read in chunks and refuse early. The same ordering mistake the ingest
#: endpoint had: checking a length *after* buffering the whole body means the
#: check never runs on the upload that matters.
UPLOAD_CHUNK = 512 * 1024


async def _read_capped(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK):
        total += len(chunk)
        if total > ocr.MAX_IMAGE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"Image exceeds {ocr.MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


#: Anyone who can create a material can run the check. Viewers and auditors
#: cannot, because for them it would be a way to probe another CPSE's
#: catalogue by description.
CREATOR = ("registrar", "admin", "approver", "steward")


class CheckIn(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    mpn: str | None = None
    #: The barcode on the box, scanned or typed; its check digit is verified.
    gtin: str | None = Field(default=None, max_length=32)
    uom: str | None = None
    limit: int = Field(default=smart_create.TOP_N, ge=1, le=20)


class DraftIn(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    mpn: str | None = Field(default=None, max_length=64)
    gtin: str | None = Field(default=None, max_length=32)
    uom: str | None = Field(default=None, max_length=16)
    note: str | None = Field(default=None, max_length=500)
    #: The check this draft was saved from, if one ran.
    check_id: int | None = None


class DraftStatusIn(BaseModel):
    status: str  # submitted | discarded


class ReuseIn(BaseModel):
    check_id: int
    item_id: int


class CreateIn(BaseModel):
    create_token: str
    legacy_code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    uom: str | None = None
    reason: str | None = None


@router.post("/check")
def check(
    body: CheckIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return smart_create.check(
            db, body.description, body.mpn, body.uom, user, body.limit, gtin=body.gtin
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


# --------------------------------------------------------------------------
# Drafts: a request saved before it is decided
# --------------------------------------------------------------------------


def _draft_row(draft) -> dict:
    return {
        "id": draft.id,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
        "description": draft.description,
        "mpn": draft.mpn,
        "gtin": draft.gtin,
        "uom": draft.uom,
        "note": draft.note,
        "status": draft.status,
        "last_check_id": draft.last_check_id,
        "top_confidence": draft.top_confidence,
        "candidates": draft.candidates,
    }


@router.get("/drafts")
def list_drafts(
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    """The caller's open drafts, newest first. A steward sees their own; an
    approver, registrar or admin sees every open draft in the estate, since
    theirs is the desk the requests land on."""
    from sqlalchemy import select

    from ..models import SmartCreateDraft

    query = select(SmartCreateDraft).where(SmartCreateDraft.status == "draft")
    if user.role == "steward":
        query = query.where(SmartCreateDraft.user_id == user.id)
    rows = db.execute(query.order_by(SmartCreateDraft.updated_at.desc()).limit(50)).scalars()
    return {"drafts": [_draft_row(d) for d in rows]}


@router.post("/drafts")
def save_draft(
    body: DraftIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    """Save what was typed, and the headline of the last check, for later."""
    from datetime import UTC, datetime

    from ..models import SmartCreateCheck, SmartCreateDraft

    check_row = db.get(SmartCreateCheck, body.check_id) if body.check_id else None
    draft = SmartCreateDraft(
        user_id=user.id,
        cpse_id=user.cpse_id,
        description=body.description.strip(),
        mpn=(body.mpn or "").strip() or None,
        gtin=(body.gtin or "").strip() or None,
        uom=(body.uom or "").strip() or None,
        note=(body.note or "").strip() or None,
        last_check_id=check_row.id if check_row else None,
        top_confidence=check_row.top_confidence if check_row else None,
        candidates=check_row.candidates if check_row else None,
        updated_at=datetime.now(UTC),
    )
    db.add(draft)
    db.flush()
    audit.record(
        db,
        action="smart_create.draft",
        entity=f"draft:{draft.id}",
        payload={"description": draft.description, "check_id": draft.last_check_id},
        user=user.email,
        commit=False,
    )
    db.commit()
    return _draft_row(draft)


@router.patch("/drafts/{draft_id}")
def set_draft_status(
    draft_id: int,
    body: DraftStatusIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    """Close a draft: `submitted` once the request was decided (reused or
    created), `discarded` when it is no longer wanted."""
    from datetime import UTC, datetime

    from ..models import SmartCreateDraft

    if body.status not in ("submitted", "discarded"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "submitted or discarded")
    draft = db.get(SmartCreateDraft, draft_id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No draft {draft_id}.")
    if user.role == "steward" and draft.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That draft belongs to someone else.")
    draft.status = body.status
    draft.updated_at = datetime.now(UTC)
    db.commit()
    return _draft_row(draft)


@router.post("/scan")
async def scan(
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    file: Annotated[UploadFile, File()],
    uom: Annotated[str | None, Form()] = None,
    limit: Annotated[int, Form()] = smart_create.TOP_N,
    db: Session = Depends(get_db),
) -> dict:
    """Read a material's marking and run the same duplicate check on it.

    The photograph never reaches the matcher — only the text does, and that text
    is treated as an ordinary description. Nothing here is special-cased, which
    is why a misread produces "nothing matched" rather than a wrong merge.
    """
    payload = await _read_capped(file)
    try:
        reading = ocr.read(payload)
    except ocr.OcrUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if not reading.text:
        return {
            "ocr": reading.as_dict(),
            "suggestions": [],
            "equivalents": [],
            "ruled_out": [],
            "recommendation": {
                "action": "review",
                "reason": (
                    "Nothing legible was found in that image. Photograph the "
                    "stamped marking or the nameplate rather than the part, or "
                    "type the description instead."
                ),
                "override_requires_reason": False,
            },
        }

    result = smart_create.check(db, reading.text, None, uom, user, limit)
    result["ocr"] = reading.as_dict()
    result["scanned"] = True

    # Measured, not guessed: below this the reader's output resolves to the
    # right material 19% of the time, against 83% above it. Presenting such a
    # result as an answer would be presenting a coin toss as one.
    if reading.mean_confidence < ocr_eval.RETAKE_BELOW:
        result["recommendation"] = {
            "action": "review",
            "reason": (
                f"The marking was only read with {reading.mean_confidence:.0%} "
                "confidence. Anything found below 90% is usually wrong — move "
                "closer, steady the camera, or type the description instead."
            ),
            "override_requires_reason": True,
        }
        result["retake"] = True
    return result


@router.post("/reuse")
def reuse(
    body: ReuseIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return smart_create.reuse(db, body.check_id, body.item_id, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/create")
def create(
    body: CreateIn,
    user: Annotated[User, Depends(require_roles(*CREATOR))],
    db: Session = Depends(get_db),
) -> dict:
    try:
        return smart_create.create_anyway(
            db,
            body.create_token,
            body.legacy_code,
            body.description,
            body.uom,
            body.reason,
            user,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/stats")
def stats(
    _user: Annotated[User, Depends(require_roles(*CREATOR, "auditor", "viewer"))],
    db: Session = Depends(get_db),
) -> dict:
    return smart_create.stats(db)
