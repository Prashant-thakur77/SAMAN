"""SAMAN FastAPI application."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .audit import ensure_genesis
from .config import get_settings
from .db import SessionLocal, init_db
from .routers import (
    admin,
    assistant,
    auth,
    bootstrap,
    clusters,
    cnmc,
    copilot,
    dashboard,
    health,
    ingest,
    learn,
    metrics,
    migration,
    pipeline,
    pprl,
    relations,
    search,
    smart_create,
    substitutes,
    workbench,
)

settings = get_settings()

if settings.saman_secret_key == "saman-dev-secret-change-me" and settings.saman_secure_cookies:
    # Secure cookies mean a real deployment; a known signing key would let
    # anyone forge a session. Loud, early, and impossible to miss in the logs.
    logging.getLogger("saman").warning(
        "SAMAN_SECRET_KEY is the development default. Set a long random value "
        "in deploy/.env before exposing this instance."
    )

app = FastAPI(
    title="SAMAN API",
    description=(
        "Standardised Asset & Material Analysis Network. Harmonizes material codes "
        "across Indian CPSEs and issues the Common National Material Code (CNMC)."
    ),
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(bootstrap.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(cnmc.router, prefix="/api")
app.include_router(clusters.router, prefix="/api")
app.include_router(relations.router, prefix="/api")
app.include_router(workbench.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(copilot.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(migration.router, prefix="/api")
app.include_router(smart_create.router, prefix="/api")
app.include_router(pprl.router, prefix="/api")
app.include_router(assistant.router, prefix="/api")
app.include_router(learn.router, prefix="/api")
app.include_router(substitutes.router, prefix="/api")


@app.on_event("startup")
def _startup() -> None:
    """Create tables if the database file is new, so a fresh clone can boot
    straight into empty states rather than a 500 (spec §8A), and open the audit
    ledger so its first real event has a genesis to chain from (§0.9a)."""
    init_db()
    with SessionLocal() as db:
        ensure_genesis(db)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"app": settings.app_name, "tagline": settings.tagline, "docs": "/api/docs"}
