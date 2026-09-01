"""CSV ingest with a validation report — spec §5, §6.11.

Column names differ across CPSEs, so the header is auto-mapped against a set of
known aliases. The onboarding wizard (M7) lets a user override that mapping;
this endpoint accepts the override through `mapping`.

`dry_run` returns exactly the same report without writing, which is what the
wizard's step 3 shows before the user commits.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from .. import audit
from ..auth import require_roles
from ..db import get_db
from ..extract import extract
from ..models import Cpse, RawItem, User
from ..normalize import normalize_row
from ..schemas import IngestReport, RejectedRow, SampleNormalization

router = APIRouter(tags=["ingest"])

MAX_UPLOAD_BYTES = 64 * 1024 * 1024

#: Target field -> header spellings seen in real CPSE extracts.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "legacy_code": (
        "legacy_code", "material_code", "material", "matnr", "code", "item_code",
        "material number", "material no", "sap code", "part code",
    ),
    "description": (
        "description", "material_description", "desc", "maktx", "item_description",
        "long text", "short text", "material text",
    ),
    "uom": ("uom", "unit", "unit_of_measure", "meins", "base uom", "uom_code"),
    "plant": ("plant", "werks", "location", "site", "store"),
    "price": ("price", "unit_price", "rate", "value", "moving average price", "map"),
    "qty_on_hand": ("qty_on_hand", "qty", "quantity", "stock", "on_hand", "labst"),
}

REQUIRED = ("legacy_code", "description")


def guess_mapping(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map file headers onto our fields, returning (mapping, unmapped headers)."""
    normalized = {h: h.strip().lower().replace("-", " ").replace("_", " ") for h in headers}
    mapping: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for header, norm in normalized.items():
            if header in mapping.values():
                continue
            if norm in {a.replace("_", " ") for a in aliases}:
                mapping[field] = header
                break
    unmapped = [h for h in headers if h not in mapping.values()]
    return mapping, unmapped


def _to_float(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


@router.post("/ingest", response_model=IngestReport)
async def ingest(
    _user: Annotated[User, Depends(require_roles("registrar", "admin", "steward"))],
    cpse_code: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    dry_run: Annotated[bool, Form()] = False,
    mapping: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
) -> IngestReport:
    cpse = db.execute(select(Cpse).where(Cpse.code == cpse_code.upper())).scalar_one_or_none()
    if cpse is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown CPSE code {cpse_code!r}.")

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds 64 MB.")

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Indian ERP extracts are frequently cp1252; fall back rather than reject.
        text = payload.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    if not headers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file has no header row.")

    column_mapping, unmapped = guess_mapping(headers)
    if mapping:
        try:
            override = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "mapping must be JSON.") from exc
        column_mapping.update({k: v for k, v in override.items() if v in headers})
        unmapped = [h for h in headers if h not in column_mapping.values()]

    missing = [f for f in REQUIRED if f not in column_mapping]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Could not identify required column(s): {', '.join(missing)}. "
            f"File headers were: {', '.join(headers)}.",
        )

    existing = set(
        db.execute(
            select(RawItem.legacy_code).where(RawItem.cpse_id == cpse.id)
        ).scalars()
    )

    accepted: list[dict] = []
    rejected: list[RejectedRow] = []
    samples: list[SampleNormalization] = []
    seen_in_file: set[str] = set()
    duplicates_in_file = 0
    already_present = 0
    rows_read = 0

    for row_number, row in enumerate(reader, start=2):  # row 1 is the header
        rows_read += 1
        legacy = (row.get(column_mapping["legacy_code"]) or "").strip()
        description = (row.get(column_mapping["description"]) or "").strip()

        if not legacy:
            rejected.append(
                RejectedRow(
                    row_number=row_number, reason="Missing material code.", raw=dict(row)
                )
            )
            continue
        if not description:
            rejected.append(
                RejectedRow(
                    row_number=row_number, reason="Missing description.", raw=dict(row)
                )
            )
            continue
        if legacy in seen_in_file:
            duplicates_in_file += 1
            rejected.append(
                RejectedRow(
                    row_number=row_number,
                    reason=f"Duplicate code {legacy!r} in this file.",
                    raw=dict(row),
                )
            )
            continue
        if legacy in existing:
            already_present += 1
            rejected.append(
                RejectedRow(
                    row_number=row_number,
                    reason=f"Code {legacy!r} already exists for {cpse.code}.",
                    raw=dict(row),
                )
            )
            continue

        seen_in_file.add(legacy)
        uom = (row.get(column_mapping.get("uom", "")) or "").strip() or None
        accepted.append(
            {
                "cpse_id": cpse.id,
                "legacy_code": legacy,
                "description": description,
                "uom": uom,
                "plant": (row.get(column_mapping.get("plant", "")) or "").strip() or None,
                "price": _to_float(row.get(column_mapping.get("price", ""))),
                "qty_on_hand": _to_float(row.get(column_mapping.get("qty_on_hand", ""))),
            }
        )

        # A handful of worked examples so the wizard can show what normalization
        # will actually do to this file, before anything is written.
        if len(samples) < 8:
            norm = normalize_row(description, uom)
            ex = extract(norm.norm_text)
            samples.append(
                SampleNormalization(
                    legacy_code=legacy,
                    original=description,
                    normalized=norm.norm_text,
                    class_code=ex.class_code,
                    class_confidence=ex.class_confidence,
                    attrs=ex.attrs,
                )
            )

    if accepted and not dry_run:
        for i in range(0, len(accepted), 1000):
            db.execute(insert(RawItem), accepted[i : i + 1000])
        audit.record(
            db,
            action="ingest",
            entity=f"cpse:{cpse.code}",
            payload={
                "cpse": cpse.code,
                "file": file.filename,
                "rows_read": rows_read,
                "rows_accepted": len(accepted),
                "rows_rejected": len(rejected),
                "column_mapping": column_mapping,
            },
            user=_user.email,
            commit=False,
        )
        db.commit()

    return IngestReport(
        cpse_code=cpse.code,
        dry_run=dry_run,
        rows_read=rows_read,
        rows_accepted=len(accepted),
        rows_rejected=len(rejected),
        duplicates_in_file=duplicates_in_file,
        already_present=already_present,
        column_mapping=column_mapping,
        unmapped_columns=unmapped,
        rejected=rejected[:50],  # enough to diagnose without returning the file back
        samples=samples,
    )
