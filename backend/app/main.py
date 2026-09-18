"""SAMAN FastAPI application."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

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


#: Where the built frontend lives when this process serves it itself, which
#: is how the single-container image runs: one process, one port, no web
#: server in front. Unset in development (Vite serves and proxies) and in the
#: compose stack (Caddy does), where this API answers only under /api.
FRONTEND_DIR = Path(settings.saman_static_dir).resolve() if settings.saman_static_dir else None
if FRONTEND_DIR is not None:
    app.add_middleware(GZipMiddleware, minimum_size=1024)


def _frontend_file(path: str) -> Path | None:
    """The built file for a path, or the app shell for a client-side route.

    The shell answers every path that is not a file, because the router in
    the browser owns those routes and a reload on /workbench must not 404.
    Anything under /api that reached here matched no endpoint and is a real
    404, never the shell dressed up as a page.
    """
    if FRONTEND_DIR is None or path == "api" or path.startswith("api/"):
        return None
    candidate = (FRONTEND_DIR / path).resolve() if path else FRONTEND_DIR / "index.html"
    if candidate.is_relative_to(FRONTEND_DIR) and candidate.is_file():
        return candidate
    index = FRONTEND_DIR / "index.html"
    return index if index.is_file() else None


@app.get("/", include_in_schema=False, response_model=None)
def root() -> FileResponse | dict:
    if (page := _frontend_file("")) is not None:
        return FileResponse(page)
    return {"app": settings.app_name, "tagline": settings.tagline, "docs": "/api/docs"}


@app.get("/{path:path}", include_in_schema=False, response_model=None)
def frontend(path: str) -> FileResponse:
    page = _frontend_file(path)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    # Hashed assets may be cached for good; the shell must always be fresh,
    # or a redeploy leaves a browser asking for assets that no longer exist.
    if page.name == "index.html":
        return FileResponse(page, headers={"Cache-Control": "no-cache"})
    return FileResponse(page, headers={"Cache-Control": "public, max-age=31536000, immutable"})
