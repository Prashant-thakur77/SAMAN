"""Hash-chained audit log — spec §0.8 and §0.9a.

Every mutation appends an event whose hash covers its sequence number, the
previous event's hash, and a canonical serialisation of its payload:

    hash = sha256(seq || prev_hash || canonical_json(payload))

Including `seq` is what makes the chain resist **reordering** as well as
tampering. A chain built only from `prev_hash + payload` can have two events
transposed if their payloads are swapped together with their links; binding each
event to its own position closes that.

Deletions are never physical. Removing a row would break the chain by
construction, so a retraction is a `void` event that references the original —
the record of what happened stays, and the record of it being withdrawn is
appended after it.

`verify()` re-walks the chain and reports the sequence number of the first
break, so an auditor is told *where* the ledger stops being trustworthy rather
than merely that it does.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuditEvent

#: The chain starts from a fixed, well-known value rather than an empty string,
#: so a truncated chain cannot be passed off as a fresh one.
GENESIS_PREV_HASH = "0" * 64
GENESIS_ACTION = "genesis"

ACTION_VOID = "void"


def canonical_json(payload: Any) -> str:
    """Stable serialisation: sorted keys, no incidental whitespace.

    The hash is only meaningful if the same payload always serialises to the
    same bytes.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(seq: int, prev_hash: str, payload_json: str) -> str:
    return hashlib.sha256(f"{seq}|{prev_hash}|{payload_json}".encode()).hexdigest()


def _head(db: Session) -> AuditEvent | None:
    return db.execute(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)
    ).scalar_one_or_none()


def ensure_genesis(db: Session) -> AuditEvent:
    """Create the first event if the ledger is empty."""
    head = _head(db)
    if head is not None:
        return head
    payload_json = canonical_json({"note": "SAMAN audit ledger opened"})
    event = AuditEvent(
        seq=0,
        user="system",
        action=GENESIS_ACTION,
        entity="ledger",
        payload_json=payload_json,
        prev_hash=GENESIS_PREV_HASH,
        hash=compute_hash(0, GENESIS_PREV_HASH, payload_json),
    )
    db.add(event)
    db.commit()
    return event


#: Attempts to claim the next sequence number when writers collide.
APPEND_ATTEMPTS = 8


def record(
    db: Session,
    action: str,
    entity: str,
    payload: dict,
    user: str = "system",
    commit: bool = True,
) -> AuditEvent:
    """Append one event to the chain.

    `commit=False` lets a caller append inside a larger transaction so the
    mutation and its audit record land together or not at all.

    Two writers can read the same head and claim the same sequence number —
    the pipeline runs in a background task while a reviewer is deciding. The
    unique index on `seq` makes that fail rather than fork the chain, and the
    append is retried inside a SAVEPOINT so a collision rolls back only this
    insert, never the caller's own work.
    """
    payload_json = canonical_json(payload)

    for attempt in range(APPEND_ATTEMPTS):
        head = _head(db) or ensure_genesis(db)
        seq = head.seq + 1
        event = AuditEvent(
            seq=seq,
            user=user,
            action=action,
            entity=entity,
            payload_json=payload_json,
            prev_hash=head.hash,
            hash=compute_hash(seq, head.hash, payload_json),
        )
        try:
            with db.begin_nested():
                db.add(event)
                db.flush()
        except IntegrityError:
            db.expire_all()
            if attempt == APPEND_ATTEMPTS - 1:
                raise
            continue
        if commit:
            db.commit()
        return event

    raise RuntimeError("could not append to the audit chain")  # unreachable


def void(db: Session, seq: int, reason: str, user: str = "system") -> AuditEvent:
    """Retract an earlier event without removing it (§0.9a)."""
    original = db.execute(
        select(AuditEvent).where(AuditEvent.seq == seq)
    ).scalar_one_or_none()
    if original is None:
        raise ValueError(f"no audit event at seq {seq}")
    return record(
        db,
        action=ACTION_VOID,
        entity=original.entity,
        payload={"voids_seq": seq, "voids_hash": original.hash, "reason": reason},
        user=user,
    )


@dataclass
class ChainBreak:
    seq: int
    reason: str

    def as_dict(self) -> dict:
        return {"seq": self.seq, "reason": self.reason}


def verify(db: Session) -> dict:
    """Re-walk the chain, reporting the first break and where it is."""
    events = db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars().all()
    if not events:
        return {
            "valid": True,
            "events": 0,
            "first_break": None,
            "note": "The ledger is empty; nothing has been recorded yet.",
        }

    expected_prev = GENESIS_PREV_HASH
    break_found: ChainBreak | None = None

    for expected_seq, event in enumerate(events):
        if event.seq != expected_seq:
            break_found = ChainBreak(
                event.seq,
                f"sequence jumps to {event.seq} where {expected_seq} was expected — "
                "an event was removed or reordered",
            )
            break
        if event.prev_hash != expected_prev:
            break_found = ChainBreak(
                event.seq, "previous-hash link does not match the preceding event"
            )
            break
        recomputed = compute_hash(event.seq, event.prev_hash, event.payload_json)
        if recomputed != event.hash:
            break_found = ChainBreak(
                event.seq, "payload does not match its recorded hash — the entry was altered"
            )
            break
        expected_prev = event.hash

    voided = {
        json.loads(e.payload_json).get("voids_seq")
        for e in events
        if e.action == ACTION_VOID
    }

    return {
        "valid": break_found is None,
        "events": len(events),
        "head_seq": events[-1].seq,
        "head_hash": events[-1].hash,
        "voided_events": sorted(v for v in voided if v is not None),
        "first_break": break_found.as_dict() if break_found else None,
        "note": (
            "Every event's hash covers its own sequence number, so the chain "
            "detects reordering as well as tampering."
        ),
    }


def stats(db: Session) -> dict:
    rows = db.execute(
        select(AuditEvent.action, func.count(AuditEvent.id)).group_by(AuditEvent.action)
    ).all()
    return {action: count for action, count in rows}
