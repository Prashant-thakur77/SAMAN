"""Files attached to a golden record: datasheets, drawings, photographs (§6.6).

Stored under the data directory by content hash, one copy per distinct
file; served back with the hash re-checked; removed by voiding the row, never
by deleting the file, so an audit can still find what an approver looked at
when they approved.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .models import GoldenAttachment, GoldenRecord, User

#: What may be attached. A material's evidence is a document or a picture;
#: anything executable has no place on a golden record.
ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "text/plain": ".txt",
}
MAX_BYTES = 25 * 1024 * 1024
KINDS = ("datasheet", "drawing", "photo", "certificate", "other")


def uploads_dir() -> Path:
    directory = get_settings().db_file.parent / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _path(sha256: str, content_type: str) -> Path:
    return uploads_dir() / f"{sha256}{ALLOWED_TYPES.get(content_type, '.bin')}"


def attach(
    db: Session,
    golden: GoldenRecord,
    user: User,
    filename: str,
    content_type: str,
    payload: bytes,
    kind: str = "datasheet",
    note: str | None = None,
) -> GoldenAttachment:
    if content_type not in ALLOWED_TYPES:
        raise ValueError(
            f"{content_type or 'that type'} cannot be attached; PDF, PNG, JPEG, WebP, SVG or text."
        )
    if len(payload) > MAX_BYTES:
        raise ValueError(f"The file exceeds {MAX_BYTES // (1024 * 1024)} MB.")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    digest = hashlib.sha256(payload).hexdigest()
    target = _path(digest, content_type)
    if not target.exists():
        target.write_bytes(payload)
    row = GoldenAttachment(
        golden_id=golden.id,
        filename=Path(filename or "attachment").name[:255],
        content_type=content_type,
        size=len(payload),
        sha256=digest,
        kind=kind,
        note=note,
        uploaded_by=user.id,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        action="attachment.add",
        entity=f"golden:{golden.id}",
        payload={
            "attachment_id": row.id,
            "filename": row.filename,
            "kind": kind,
            "size": len(payload),
            "sha256": digest,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return row


def listing(db: Session, golden_id: int) -> list[dict]:
    rows = db.execute(
        select(GoldenAttachment, User.name)
        .join(User, User.id == GoldenAttachment.uploaded_by)
        .where(GoldenAttachment.golden_id == golden_id, GoldenAttachment.voided_at.is_(None))
        .order_by(GoldenAttachment.id)
    ).all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "content_type": a.content_type,
            "size": a.size,
            "sha256": a.sha256,
            "kind": a.kind,
            "note": a.note,
            "uploaded_by": name,
            "uploaded_at": a.uploaded_at.isoformat(),
        }
        for a, name in rows
    ]


def open_file(db: Session, attachment_id: int) -> tuple[GoldenAttachment, Path]:
    row = db.get(GoldenAttachment, attachment_id)
    if row is None or row.voided_at is not None:
        raise LookupError("No such attachment.")
    path = _path(row.sha256, row.content_type)
    if not path.exists():
        raise LookupError("The file is missing from the uploads directory.")
    # Re-check on the way out: a file changed on disk is not the one attached.
    if hashlib.sha256(path.read_bytes()).hexdigest() != row.sha256:
        raise LookupError("The stored file no longer matches its recorded hash.")
    return row, path


def void(db: Session, attachment_id: int, user: User, reason: str | None) -> GoldenAttachment:
    row = db.get(GoldenAttachment, attachment_id)
    if row is None or row.voided_at is not None:
        raise LookupError("No such attachment.")
    row.voided_at = datetime.now(UTC)
    audit.record(
        db,
        action="attachment.void",
        entity=f"golden:{row.golden_id}",
        payload={"attachment_id": row.id, "filename": row.filename, "reason": reason},
        user=user.email,
        commit=False,
    )
    db.commit()
    return row
