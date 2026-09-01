"""SAMAN FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .routers import health

settings = get_settings()

app = FastAPI(
    title="SAMAN API",
    description=(
        "Standardised Asset & Material Analysis Network — harmonizes material codes "
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


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"app": settings.app_name, "tagline": settings.tagline, "docs": "/api/docs"}
