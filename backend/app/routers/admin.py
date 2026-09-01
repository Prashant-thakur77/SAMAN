"""Administration — users, CPSEs, sovereign mode and health (spec §5, §6.13)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, smart_create
from ..auth import ROLES, hash_password, require_roles
from ..capabilities import detect, refresh
from ..config import get_settings, set_sovereign_mode, sovereign_mode
from ..db import get_db
from ..models import Cpse, RawItem, User

router = APIRouter(tags=["admin"])

ADMIN_ROLES = ("registrar", "admin")


class UserIn(BaseModel):
    email: str
    name: str
    role: str
    cpse_code: str | None = None
    password: str = "demo"


class UserPatch(BaseModel):
    role: str | None = None
    active: bool | None = None


class SovereignIn(BaseModel):
    enabled: bool


def _user_row(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "cpse_code": user.cpse.code if user.cpse else None,
        "active": user.active,
    }


@router.get("/users")
def list_users(
    _user: Annotated[User, Depends(require_roles(*ADMIN_ROLES))],
    db: Session = Depends(get_db),
) -> dict:
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return {"roles": list(ROLES), "count": len(users), "users": [_user_row(u) for u in users]}


@router.post("/users")
def create_user(
    body: UserIn,
    actor: Annotated[User, Depends(require_roles(*ADMIN_ROLES))],
    db: Session = Depends(get_db),
) -> dict:
    if body.role not in ROLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown role {body.role!r}; expected one of {', '.join(sorted(ROLES))}.",
        )
    email = body.email.strip().lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, f"{email} already has an account.")

    cpse_id = None
    if body.cpse_code:
        cpse = db.execute(
            select(Cpse).where(Cpse.code == body.cpse_code.upper())
        ).scalar_one_or_none()
        if cpse is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown CPSE {body.cpse_code!r}.")
        cpse_id = cpse.id

    user = User(
        email=email,
        name=body.name.strip(),
        role=body.role,
        password_hash=hash_password(body.password),
        cpse_id=cpse_id,
        active=True,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.create",
        entity=f"user:{user.id}",
        payload={"email": email, "role": body.role, "cpse": body.cpse_code},
        user=actor.email,
        commit=False,
    )
    db.commit()
    return _user_row(user)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserPatch,
    actor: Annotated[User, Depends(require_roles(*ADMIN_ROLES))],
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No user {user_id}.")
    if body.role is not None and body.role not in ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown role {body.role!r}.")
    if user.id == actor.id and body.active is False:
        # Locking yourself out is never the intent, and an admin who cannot
        # sign in cannot undo it either.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You cannot disable the account you are signed in with."
        )

    before = {"role": user.role, "active": user.active}
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active

    audit.record(
        db,
        action="user.update",
        entity=f"user:{user.id}",
        payload={"before": before, "after": {"role": user.role, "active": user.active}},
        user=actor.email,
        commit=False,
    )
    db.commit()
    return _user_row(user)


class CpseIn(BaseModel):
    code: str
    name: str


@router.get("/cpses")
def list_cpses(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Cpse.code, Cpse.name, func.count(RawItem.id))
        .outerjoin(RawItem, RawItem.cpse_id == Cpse.id)
        .group_by(Cpse.code, Cpse.name)
        .order_by(Cpse.code)
    ).all()
    return {"cpses": [{"code": c, "name": n, "items": i} for c, n, i in rows]}


@router.post("/cpses")
def create_cpse(
    body: CpseIn,
    actor: Annotated[User, Depends(require_roles(*ADMIN_ROLES))],
    db: Session = Depends(get_db),
) -> dict:
    """Register a CPSE so its catalogue can be onboarded (§6.11)."""
    code = body.code.strip().upper()
    if not code.isalnum() or not 2 <= len(code) <= 16:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A CPSE code is 2-16 alphanumeric characters, e.g. BPCL.",
        )
    if db.execute(select(Cpse).where(Cpse.code == code)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, f"{code} is already registered.")

    cpse = Cpse(code=code, name=body.name.strip() or code)
    db.add(cpse)
    db.flush()
    audit.record(
        db,
        action="cpse.create",
        entity=f"cpse:{code}",
        payload={"code": code, "name": cpse.name},
        user=actor.email,
        commit=False,
    )
    db.commit()
    return {"code": cpse.code, "name": cpse.name, "items": 0}


@router.post("/settings/sovereign")
def set_sovereign(
    body: SovereignIn,
    actor: Annotated[User, Depends(require_roles(*ADMIN_ROLES))],
    db: Session = Depends(get_db),
) -> dict:
    """Toggle sovereign mode (§6.13).

    When on, any configured Ollama endpoint is ignored and Tier 3 falls back to
    the deterministic adjudicator — the platform stays entirely local. The
    setting lives in the process for the prototype; a deployment would persist
    it, which is noted rather than pretended otherwise.
    """
    before = sovereign_mode()
    set_sovereign_mode(body.enabled)
    caps = refresh()

    audit.record(
        db,
        action="settings.sovereign",
        entity="settings",
        payload={"before": before, "after": body.enabled},
        user=actor.email,
    )
    return {
        "sovereign_mode": body.enabled,
        "capabilities": caps.as_dict(),
        "note": (
            "Sovereign mode is on: any configured local model is ignored and the "
            "copilot answers from reviewed queries alone."
            if body.enabled
            else "Sovereign mode is off. A local Ollama model will be used if configured."
        ),
        "persisted": False,
    }


@router.get("/settings/health")
def health_panel(
    _user: Annotated[User, Depends(require_roles(*ADMIN_ROLES))],
    db: Session = Depends(get_db),
) -> dict:
    """The admin health panel (§6.13): which engine is live in each tier."""
    from ..models import AuditEvent, Cluster, Cnmc, Item, Pair, RawItem, ReviewTask

    settings = get_settings()
    counts = {
        "raw_items": db.execute(select(func.count(RawItem.id))).scalar() or 0,
        "items": db.execute(select(func.count(Item.id))).scalar() or 0,
        "pairs": db.execute(select(func.count(Pair.id))).scalar() or 0,
        "clusters": db.execute(select(func.count(Cluster.id))).scalar() or 0,
        "cnmcs": db.execute(select(func.count(Cnmc.id))).scalar() or 0,
        "pending_review": db.execute(
            select(func.count(ReviewTask.id)).where(ReviewTask.state == "pending")
        ).scalar() or 0,
        "audit_events": db.execute(select(func.count(AuditEvent.id))).scalar() or 0,
    }
    prevention = smart_create.stats(db)
    counts["duplicates_prevented"] = prevention["prevented"]
    return {
        "capabilities": detect().as_dict(),
        "sovereign_mode": sovereign_mode(),
        "ollama_configured": bool(settings.ollama_url),
        "database": str(settings.db_file),
        "counts": counts,
        # §5: the counter belongs next to the engine health, because it is the
        # one number that says whether duplicates are still being created.
        "smart_create": prevention,
        "audit": audit.verify(db),
    }
