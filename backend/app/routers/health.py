"""GET /api/health — active engine modes and degradation notices (spec 0.4)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..capabilities import detect
from ..config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    caps = detect()
    return {
        "status": "ok",
        "app": settings.app_name,
        "long_name": settings.app_long_name,
        "version": __version__,
        "offline": True,
        "capabilities": caps.as_dict(),
    }
