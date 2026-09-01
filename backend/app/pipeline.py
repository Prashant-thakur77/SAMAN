"""Pipeline orchestration — normalize -> extract -> (embed -> match -> cluster).

M2 registers the first two stages; M3 appends the rest. Progress is exposed
through `GET /api/pipeline/status` so the UI can show a determinate bar rather
than an indefinite spinner (spec §8A "long-job UX").

State is process-local and deliberately simple: one pipeline run at a time,
which is what a single-laptop prototype needs.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from .extract import extract
from .models import Item, RawItem
from .normalize import normalize_gtin, normalize_mpn, normalize_row

BATCH = 1000


@dataclass
class PipelineStatus:
    state: str = "idle"  # idle|running|done|error
    stage: str | None = None
    stages_done: list[str] = field(default_factory=list)
    rows_done: int = 0
    rows_total: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None

    @property
    def eta_seconds(self) -> float | None:
        """Linear ETA from observed throughput. Honest about being an estimate."""
        if not self.started_at or self.rows_done <= 0 or self.state != "running":
            return None
        elapsed = time.time() - self.started_at
        rate = self.rows_done / elapsed
        remaining = max(self.rows_total - self.rows_done, 0)
        return round(remaining / rate, 1) if rate > 0 else None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "stage": self.stage,
            "stages_done": list(self.stages_done),
            "rows_done": self.rows_done,
            "rows_total": self.rows_total,
            "percent": round(100 * self.rows_done / self.rows_total, 1)
            if self.rows_total
            else 0.0,
            "eta_seconds": self.eta_seconds,
            "elapsed_seconds": round(time.time() - self.started_at, 1)
            if self.started_at
            else None,
            "error": self.error,
        }


_status = PipelineStatus()
_lock = threading.Lock()


def get_status() -> PipelineStatus:
    return _status


def reset_status() -> None:
    global _status
    with _lock:
        _status = PipelineStatus()


# --------------------------------------------------------------------------
# Stage: normalize + extract
# --------------------------------------------------------------------------


def build_items(
    db: Session,
    raw_item_ids: list[int] | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    """Create an `item` row for every raw row that does not have one.

    Resumable by construction: it only processes raw rows with no item yet, so a
    crashed run restarts where it stopped rather than from zero (spec §8A).
    """
    stmt = select(RawItem.id, RawItem.description, RawItem.uom).outerjoin(
        Item, Item.raw_item_id == RawItem.id
    ).where(Item.id.is_(None))
    if raw_item_ids is not None:
        stmt = stmt.where(RawItem.id.in_(raw_item_ids))

    rows = db.execute(stmt).all()
    created = 0
    buffer: list[dict] = []

    for raw_id, description, uom in rows:
        norm = normalize_row(description or "", uom)
        ex = extract(norm.norm_text)

        attrs = dict(ex.attrs)
        if ex.designation:
            attrs["_designation"] = ex.designation
        if ex.conflicts:
            # §2A.1: a parsed designation disagreeing with the free text is a
            # review flag, not something to resolve by silently picking one.
            attrs["_conflicts"] = ex.conflicts

        buffer.append(
            {
                "raw_item_id": raw_id,
                "norm_text": norm.norm_text,
                "norm_hash": norm.norm_hash,
                "lang": norm.lang,
                "class_code": ex.class_code,
                "class_confidence": ex.class_confidence,
                "mpn_norm": normalize_mpn(ex.mpn),
                "gtin": normalize_gtin(None),
                "uom_base": norm.uom_base,
                "pack_qty": norm.pack_qty,
                "attrs_json": json.dumps(attrs, sort_keys=True, default=str),
            }
        )

        if len(buffer) >= BATCH:
            db.execute(insert(Item), buffer)
            db.commit()
            created += len(buffer)
            buffer.clear()
            if on_progress:
                on_progress(created)

    if buffer:
        db.execute(insert(Item), buffer)
        db.commit()
        created += len(buffer)
        if on_progress:
            on_progress(created)

    return created


# --------------------------------------------------------------------------
# Stage registry
# --------------------------------------------------------------------------

#: Stage name -> callable(db, status). M3 appends embed/match/cluster here.
STAGES: dict[str, Callable[[Session, PipelineStatus], None]] = {}


def register_stage(name: str):
    def wrap(fn):
        STAGES[name] = fn
        return fn

    return wrap


@register_stage("normalize+extract")
def _stage_normalize_extract(db: Session, status: PipelineStatus) -> None:
    pending = db.execute(
        select(RawItem.id).outerjoin(Item, Item.raw_item_id == RawItem.id).where(Item.id.is_(None))
    ).scalars().all()
    status.rows_total = len(pending)
    status.rows_done = 0
    build_items(db, pending, on_progress=lambda n: setattr(status, "rows_done", n))


def run_pipeline(db: Session, stages: list[str] | None = None) -> PipelineStatus:
    """Run the registered stages in order, recording progress as we go."""
    status = get_status()
    with _lock:
        if status.state == "running":
            return status
        status.state = "running"
        status.started_at = time.time()
        status.finished_at = None
        status.error = None
        status.stages_done = []

    names = stages if stages is not None else list(STAGES)
    try:
        for name in names:
            fn = STAGES.get(name)
            if fn is None:
                continue
            status.stage = name
            fn(db, status)
            status.stages_done.append(name)
        status.state = "done"
    except Exception as exc:  # a failed run must report, never take the app down
        status.state = "error"
        status.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        status.stage = None
        status.finished_at = time.time()
    return status
