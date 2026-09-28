"""A memo for the dashboards, keyed on the state of the estate.

The executive dashboard is thirty-odd queries and some Python: half a second
on a laptop, and ten seconds on the tenth of a CPU a free host gives away.
The figures change only when the estate does, and every change to the estate
is either an audited action or a pipeline run, so the memo is keyed on the
audit ledger's head, the latest run, and the day (the dead-stock and purchase
windows are anchored to today). A handful of row counts join the key so that
a table edited behind the ledger's back, as tests do, still misses. Anything
that would change a figure therefore changes the key.

After a change, the dashboards on a slow host would be a long wait for the
first reader (twelve seconds for the executive dashboard, thirty for the
learning status, measured on a tenth of a CPU). So a key that has a previous
value is recomputed in the background and the reader waits
`SAMAN_STALE_WAIT_S` (1.5 s) for it: fresh figures whenever the machine is
fast enough, otherwise the previous ones, marked stale, whose provenance
names the audit sequence they were computed at. The page says "updating" and
asks again until the fresh figures arrive. Nothing stale is ever unmarked.

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


#: Audited actions that change nothing a dashboard counts. A sign-in, a
#: snapshot, a wrong-item report or a scan count is on the ledger for the
#: record; keying the memo on it would recompute every dashboard after every
#: login, which on a tenth of a CPU is twenty seconds of "Loading…" for the
#: person who just signed in.
NOT_ESTATE = (
    "auth.login",
    "demo.snapshot",
    "scan.wrong_item",
    "stock.count",
    "bin.bind",
    "attachment.add",
    "attachment.void",
    "smart_create.draft",
    "abbreviation.upsert",
    "abbreviation.retire",
    "user.create",
    "user.update",
    "settings.sovereign",
)


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
        db.execute(
            select(func.max(AuditEvent.seq)).where(AuditEvent.action.not_in(NOT_ESTATE))
        ).scalar()
        or 0,
        db.execute(select(func.max(MatchRun.id))).scalar() or 0,
        *counts,
    )


#: key -> the thread recomputing it in the background, while one runs.
_refreshing: dict[tuple, threading.Thread] = {}


def _stale_wait() -> float:
    from .config import get_settings

    return get_settings().saman_stale_wait_s


def _refresh(key: tuple, lock: threading.Lock, refresh: Callable[[Session], T]) -> threading.Thread:
    """Recompute `key` in the background on a session of its own, unless a
    recompute of it is already running. Returns the thread doing the work."""
    with _guard:
        running = _refreshing.get(key)
        if running is not None and running.is_alive():
            return running

        def run() -> None:
            from .db import SessionLocal

            try:
                with lock, SessionLocal() as session:
                    current = version(session)
                    with _guard:
                        hit = _entries.get(key)
                    if hit is not None and hit[0] == current:
                        return
                    value = refresh(session)
                    with _guard:
                        _entries[key] = (current, value)
            except Exception:  # a failed refresh leaves the last value standing
                log.exception("could not refresh %s", key)

        thread = threading.Thread(target=run, name="saman-refresh", daemon=True)
        _refreshing[key] = thread
        thread.start()
        return thread


def _mark_stale(value):
    """The last value, saying so: the page shows it as updating."""
    if not isinstance(value, dict):
        return value
    if isinstance(value.get("provenance"), dict):
        return {**value, "provenance": {**value["provenance"], "stale": True}}
    return {**value, "stale": True}


def memo(
    db: Session,
    key: tuple,
    compute: Callable[[], T],
    refresh: Callable[[Session], T] | None = None,
) -> T:
    """The value for `key` at the estate's current version, computed at most
    once per version even when two requests ask at the same moment.

    With `refresh` (the same computation, taking a session of its own), a key
    whose figures the estate has moved past is recomputed in the background,
    and the request waits `SAMAN_STALE_WAIT_S` for it. On a fast machine the
    recompute finishes inside that and the reader gets fresh figures, exactly
    as without `refresh`. On a slow host (a tenth of a CPU recomputes the
    executive dashboard in about twelve seconds) the reader gets the previous
    figures at once, marked stale, whose provenance names the audit sequence
    they were computed at; the fresh ones replace them when they are ready.
    """
    current = version(db)
    with _guard:
        hit = _entries.get(key)
        lock = _computing.setdefault(key, threading.Lock())
    if hit is not None and hit[0] == current:
        return hit[1]  # type: ignore[return-value]
    if refresh is not None and hit is not None:
        _refresh(key, lock, refresh).join(timeout=_stale_wait())
        with _guard:
            newest = _entries.get(key)
        if newest is not None and newest[0] == current:
            return newest[1]  # type: ignore[return-value]
        return _mark_stale((newest or hit)[1])  # type: ignore[return-value]
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


def drain(timeout: float = 120.0) -> None:
    """Wait for every background refresh to finish (tests, and shutdown)."""
    with _guard:
        threads = list(_refreshing.values())
    for thread in threads:
        thread.join(timeout=timeout)


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
