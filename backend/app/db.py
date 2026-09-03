"""SQLite engine, session factory and declarative base (spec §0.2)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    # SQLite + FastAPI background tasks touch the connection from more than one
    # thread; the pool serialises access.
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    """WAL keeps reads unblocked while the pipeline writes (spec §8A)."""
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and background tasks."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from sqlalchemy import inspect, text

    from . import models  # noqa: F401  — register mappers before create_all

    # `pair_label` gained its item columns the day it was introduced; a
    # database from earlier that day has the old shape. Nothing else ever
    # wrote to it, so rebuilding it loses nothing.
    inspector = inspect(engine)
    if "pair_label" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("pair_label")}
        if "item_a" not in columns:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE pair_label"))
    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    """Drop and recreate every table. Used by `make seed` and the test fixtures."""
    from . import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def dispose_engine() -> None:
    """Close every pooled connection.

    Restoring a snapshot replaces the database file underneath us; a connection
    still holding the old file is how SQLite reports "database disk image is
    malformed". The pool reopens lazily on the next session.
    """
    engine.dispose()
