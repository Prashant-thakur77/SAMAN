"""Authentication routes — spec §5."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    authenticate,
    clear_session,
    current_user_optional,
    issue_session,
    require_user,
)
from ..db import get_db
from ..models import User
from ..schemas import DemoUser, LoginRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        cpse_code=user.cpse.code if user.cpse else None,
    )


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = authenticate(db, body.email.strip().lower(), body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect user or password.")
    issue_session(response, user)
    return _to_out(user)


@router.post("/logout")
def logout(response: Response) -> dict:
    # Returns a body rather than 204 so the cookie-clearing headers ride on the
    # same response object FastAPI injected.
    clear_session(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(require_user)]) -> UserOut:
    return _to_out(user)


@router.get("/session", response_model=UserOut | None)
def session(user: Annotated[User | None, Depends(current_user_optional)]) -> UserOut | None:
    """Unauthenticated probe — returns null instead of 401 so the shell can
    render for a signed-out visitor without an error round-trip."""
    return _to_out(user) if user else None


@router.get("/demo-users", response_model=list[DemoUser])
def demo_users(db: Session = Depends(get_db)) -> list[DemoUser]:
    """Seeded users for the login picker (spec §6.1).

    Exposes name, role and CPSE only. Every seeded account uses the password
    `demo`, which is stated on the login screen — this is a local prototype
    with synthetic data, not a deployment.
    """
    users = db.execute(select(User).where(User.active.is_(True)).order_by(User.id)).scalars()
    return [
        DemoUser(
            email=u.email, name=u.name, role=u.role,
            cpse_code=u.cpse.code if u.cpse else None,
        )
        for u in users
    ]
