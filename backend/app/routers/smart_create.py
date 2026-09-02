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

from .. import ocr, ocr_eval, smart_create
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
    uom: str | None = None
    limit: int = Field(default=smart_create.TOP_N, ge=1, le=20)


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
        return smart_create.check(db, body.description, body.mpn, body.uom, user, body.limit)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


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
            db, body.create_token, body.legacy_code, body.description,
            body.uom, body.reason, user,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/stats")
def stats(
    _user: Annotated[User, Depends(require_roles(*CREATOR, "auditor", "viewer"))],
    db: Session = Depends(get_db),
) -> dict:
    return smart_create.stats(db)
