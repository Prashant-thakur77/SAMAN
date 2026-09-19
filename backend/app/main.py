"""SAMAN FastAPI application."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from . import __version__
from .audit import ensure_genesis
from .auth import require_user
from .config import get_settings
from .db import SessionLocal, init_db
from .routers import (
    admin,
    assistant,
    auth,
    autoissue,
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
    reports,
    scan,
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


@app.middleware("http")
async def security_headers(request, call_next):
    """The response headers a public link should carry.

    The frontend is same-origin and never framed, so framing is refused; the
    browser must not sniff a type we did not declare; referrers stop at the
    origin; the camera and microphone are for this origin only (Smart-Create's
    scan and the assistant's voice). HSTS only once cookies are marked secure,
    which is the deployment's way of saying HTTPS is in front.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(self), microphone=(self), geolocation=(), payment=()"
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if settings.saman_secure_cookies:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The front door. Four routers answer without a session: the health page,
# sign-in itself, the empty-database bootstrap (which refuses once anyone
# exists) and the assistant, which answers a visitor differently. Everything
# else is behind a session, whatever the individual
# endpoint says: the roles an endpoint names decide *which* signed-in user may
# call it, never whether a stranger may. A catalogue is a CPSE's commercial
# record, and even the aggregate dashboards are a ministry's, not the public's.
app.include_router(health.router, prefix="/api")
app.include_router(bootstrap.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
# The assistant meets visitors on the front page: its query and suggestions
# answer without a session (and answer differently, see assistant.answer);
# its speech endpoints carry their own session dependency.
app.include_router(assistant.router, prefix="/api")

SIGNED_IN = [Depends(require_user)]
for signed_in_router in (
    ingest.router,
    pipeline.router,
    metrics.router,
    cnmc.router,
    clusters.router,
    relations.router,
    workbench.router,
    dashboard.router,
    copilot.router,
    search.router,
    admin.router,
    migration.router,
    smart_create.router,
    pprl.router,
    learn.router,
    substitutes.router,
    scan.router,
    reports.router,
    autoissue.router,
):
    app.include_router(signed_in_router, prefix="/api", dependencies=SIGNED_IN)


@app.on_event("startup")
def _startup() -> None:
    """Create tables if the database file is new, so a fresh clone can boot
    straight into empty states rather than a 500 (spec §8A), and open the audit
    ledger so its first real event has a genesis to chain from (§0.9a)."""
    init_db()
    with SessionLocal() as db:
        ensure_genesis(db)
    if settings.saman_warm_dashboards:
        warm_dashboards()


def warm_dashboards():
    """The dashboards, computed once before anyone asks (see `cache`).

    A free host's CPU makes the executive dashboard a ten-second wait the
    first time; this pays it at start, for the two viewers a demo has, the
    signed-out visitor and the registrar. Every other role fills the memo on
    its own first request. Best effort: a failure is logged, never fatal.
    """
    from . import cache
    from .routers.dashboard import executive_for, opportunity_for
    from .routers.metrics import metrics_for
    from .visibility import ANONYMOUS, Scope

    registrar = Scope(role="registrar", cpse_code=None)

    def job(fn, *args):
        def run():
            with SessionLocal() as db:
                fn(db, *args)

        return run

    from .smart_create import probe_embedder

    jobs = [
        ("executive (visitor)", job(executive_for, ANONYMOUS)),
        ("executive (registrar)", job(executive_for, registrar)),
        ("metrics", job(metrics_for)),
        ("opportunity (registrar)", job(opportunity_for, registrar)),
        # Smart-Create's probe embedder: the pipeline's saved fit, loaded
        # once here rather than on the first requester's click.
        ("smart-create embedder", job(probe_embedder)),
    ]
    if get_settings().saman_warm_answers:
        jobs.append(("assistant answers", warm_answers))
    return cache.warm(jobs)


def warm_answers() -> int:
    """Answer the demo's document questions once, into the memo, so the first
    person to ask gets the sentence at once rather than after the model's
    cold start. Nothing when no model is configured; each question is one
    call, and a refusal is simply not memoised."""
    from . import knowledge
    from .assistant import WARM_QUESTIONS

    if not knowledge.available():
        return 0
    warmed = 0
    for question in WARM_QUESTIONS:
        try:
            if knowledge.answer(question) is not None:
                warmed += 1
        except Exception:  # pragma: no cover - best effort, logged by cache.warm
            continue
    return warmed


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
    # A hashed asset that no longer exists is a 404, never the shell: a browser
    # holding yesterday's shell would otherwise run HTML as JavaScript and show
    # a white page instead of reloading.
    if path.startswith("assets/") or path.startswith("ocr/"):
        return None
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
