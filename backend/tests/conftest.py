"""Shared fixtures.

The database path is set BEFORE any app module is imported, because
`app.db` builds its engine at import time from the settings singleton.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "saman-test.db"
os.environ["SAMAN_DB_PATH"] = str(TEST_DB)
os.environ["SAMAN_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_database  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _fresh_database():
    for suffix in ("", "-wal", "-shm"):
        Path(str(TEST_DB) + suffix).unlink(missing_ok=True)
    reset_db()
    yield
    for suffix in ("", "-wal", "-shm"):
        Path(str(TEST_DB) + suffix).unlink(missing_ok=True)


@pytest.fixture(scope="session")
def seeded():
    """A small seeded estate, shared across the session — seeding is the slow part.

    Invariants that later tests could disturb (the ingest tests add rows to the
    same database) are measured here, immediately after seeding, and handed to
    the tests as part of the summary. Absolute row counts taken later would be
    order-dependent and would fail for reasons that have nothing to do with the
    generator.
    """
    from sqlalchemy import func, select

    from app.models import Cpse, Item, RawItem, TruthGroup, User

    with SessionLocal() as db:
        summary = seed_database(db, profile="test")

        summary["orphan_raw_items"] = db.execute(
            select(func.count(RawItem.id))
            .outerjoin(Item, Item.raw_item_id == RawItem.id)
            .where(Item.id.is_(None))
        ).scalar()
        summary["cpses_at_seed"] = db.execute(select(func.count(Cpse.id))).scalar()
        summary["users_at_seed"] = db.execute(select(func.count(User.id))).scalar()
        summary["raw_without_truth"] = db.execute(
            select(func.count(RawItem.id))
            .outerjoin(TruthGroup, TruthGroup.raw_item_id == RawItem.id)
            .where(TruthGroup.id.is_(None))
        ).scalar()
    return summary


@pytest.fixture(scope="session")
def pipeline_run(seeded):
    """Seed, then run the whole pipeline once for the session.

    The matching stages are the slow part, so tests that need clusters, golden
    records or metrics share a single run.
    """
    from app.metrics import compute_metrics
    from app.pipeline import run_pipeline

    with SessionLocal() as db:
        status = run_pipeline(db)
        assert status.state == "done", status.error
        return {"summary": seeded, "metrics": compute_metrics(db)}


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def as_steward(client, seeded):
    r = client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def as_registrar(client, seeded):
    r = client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def as_viewer(client, seeded):
    r = client.post("/api/auth/login", json={"email": "viewer@min.gov.in", "password": "demo"})
    assert r.status_code == 200, r.text
    return client
