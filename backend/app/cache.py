"""A memo for the dashboards, keyed on the state of the estate.

The executive dashboard is thirty-odd queries and some Python: half a second
on a laptop, and ten seconds on the tenth of a CPU a free host gives away.
The figures change only when the estate does, and every change to the estate
is either an audited action or a pipeline run, so the memo is keyed on the
audit ledger's head, the latest run, and the day (the dead-stock and purchase
windows are anchored to today). A handful of row counts join the key so that
a table edited behind the ledger's back, as tests do, still misses. Anything
that would change a figure therefore changes the key, and a stale answer
cannot be served: the dashboard is exactly as fresh as the last event.

One process, one memo. The compose stack and the single-container image both
run one API process, which is what login throttling already assumes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    Cnmc,
    Decision,
    Item,
    MatchRun,
    PairLabel,
    PurchaseHistory,
    Relation,
    Stock,
    SubstituteApproval,
)

log = logging.getLogger("saman.cache")

T = TypeVar("T")

_guard = threading.Lock()
_entries: dict[tuple, tuple[tuple, object]] = {}
_computing: dict[tuple, threading.Lock] = {}


def version(db: Session) -> tuple:
    """Everything a dashboard figure can depend on, as one comparable key."""
    counts = tuple(
        db.execute(select(func.count()).select_from(table)).scalar() or 0
        for table in (
            Item,
            Cnmc,
            Decision,
            Stock,
            PurchaseHistory,
            Relation,
            SubstituteApproval,
            PairLabel,
        )
    )
    return (
        date.today().isoformat(),
        db.execute(select(func.max(AuditEvent.seq))).scalar() or 0,
        db.execute(select(func.max(MatchRun.id))).scalar() or 0,
        *counts,
    )


def memo(db: Session, key: tuple, compute: Callable[[], T]) -> T:
    """The value for `key` at the estate's current version, computed at most
    once per version even when two requests ask at the same moment."""
    current = version(db)
    with _guard:
        hit = _entries.get(key)
        lock = _computing.setdefault(key, threading.Lock())
    if hit is not None and hit[0] == current:
        return hit[1]  # type: ignore[return-value]
    with lock:
        with _guard:
            hit = _entries.get(key)
        if hit is not None and hit[0] == current:
            return hit[1]  # type: ignore[return-value]
        value = compute()
        with _guard:
            _entries[key] = (current, value)
        return value


def stamped(db: Session, compute: Callable[[], dict]) -> dict:
    """`compute()`, with a `provenance` block on the result: when it was
    computed, how long it took, which version of the estate it read (the
    audit sequence and match run the memo is keyed on) and how many rows.
    Every dashboard figure can then say where it came from; a reader who
    asks "as of when?" is answered by the page itself."""
    import time
    from datetime import UTC, datetime

    started = time.perf_counter()
    value = compute()
    current = version(db)
    counts = dict(
        zip(
            (
                "items",
                "cnmcs",
                "decisions",
                "stock_rows",
                "purchases",
                "relations",
                "substitute_approvals",
                "labels",
            ),
            current[3:],
            strict=True,
        )
    )
    value["provenance"] = {
        "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - started, 2),
        "audit_seq": current[1],
        "match_run": current[2],
        "rows": counts,
        "note": (
            "Computed from the database at this audit sequence and kept until the "
            "estate changes; every figure on the page reconciles with the API. "
            "The estate is synthetic."
        ),
    }
    return value


def clear() -> None:
    with _guard:
        _entries.clear()


def warm(jobs: list[tuple[str, Callable[[], object]]]) -> threading.Thread:
    """Compute the given dashboards once, in the background, so the first
    visitor after a start does not pay for them. Each job opens its own
    session; a failure is logged and skipped, never raised into the server."""

    def run() -> None:
        for name, job in jobs:
            try:
                job()
                log.info("warmed %s", name)
            except Exception:  # warming is best effort by design
                log.exception("could not warm %s", name)

    thread = threading.Thread(target=run, name="saman-warm", daemon=True)
    thread.start()
    return thread
