"""Session auth and role enforcement — spec §0.9.

Deliberately lightweight (no Keycloak in the prototype): a signed session
cookie carrying a user id, seeded users, and role dependencies enforced on the
API. The UI guards routes too, but the API is the boundary that counts.

**Separation of duties** is the part that matters for evaluation: whoever
proposes or edits a golden record may not be the one who approves it. That is
enforced here, in one place, so no endpoint can forget it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import GoldenRecord, User

SESSION_COOKIE = "saman_session"

#: How long a session is valid, enforced *inside the signature* and not only by
#: the cookie's max-age. A browser honours max-age; a copied token does not, so
#: a signature without a timestamp is a credential that never expires.
SESSION_MAX_AGE = 60 * 60 * 12

ROLES = ("registrar", "admin", "approver", "steward", "engineer", "auditor", "viewer")

_PBKDF2_ROUNDS = 120_000


# --------------------------------------------------------------------------
# Passwords (stdlib PBKDF2 — no extra dependency, no GPL surface)
# --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# --------------------------------------------------------------------------
# Session cookie
# --------------------------------------------------------------------------


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().saman_secret_key, salt="saman-session")


def issue_session(response: Response, user: User) -> None:
    token = _serializer().dumps({"uid": user.id})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        # Off by default because the demo is served over plain HTTP on
        # localhost, where a Secure cookie would simply never be sent.
        secure=get_settings().saman_secure_cookies,
        max_age=SESSION_MAX_AGE,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _user_from_token(token: str | None, db: Session) -> User | None:
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        # SignatureExpired is a subclass of BadSignature, but naming it says
        # that expiry is deliberate rather than incidental.
        return None
    user = db.get(User, payload.get("uid"))
    return user if user and user.active else None


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------


def api_keys() -> dict[str, str]:
    """key -> user email, from SAMAN_API_KEYS ("email=key,email2=key2")."""
    out: dict[str, str] = {}
    for entry in (get_settings().saman_api_keys or "").split(","):
        email, _, key = entry.strip().partition("=")
        if email and key:
            out[key] = email.strip().lower()
    return out


def _user_from_api_key(key: str | None, db: Session) -> User | None:
    """A machine caller (the SAP-side hook) acting as a named user.

    Compared in constant time against every configured key, so a wrong key
    costs the same as a right one."""
    if not key:
        return None
    email = None
    for candidate, owner in api_keys().items():
        if hmac.compare_digest(candidate, key):
            email = owner
    if email is None:
        return None
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    return user if user and user.active else None


def current_user_optional(
    saman_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    saman_key: Annotated[str | None, Header(alias="X-SAMAN-Key")] = None,
    db: Session = Depends(get_db),
) -> User | None:
    return _user_from_token(saman_session, db) or _user_from_api_key(saman_key, db)


def require_user(user: Annotated[User | None, Depends(current_user_optional)]) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


def require_roles(*roles: str):
    """Dependency factory: allow only the named roles."""
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"unknown role(s): {sorted(unknown)}")

    def dependency(user: Annotated[User, Depends(require_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action requires one of: {', '.join(sorted(roles))}. "
                f"You are signed in as {user.role}.",
            )
        return user

    return dependency


# --------------------------------------------------------------------------
# Separation of duties (§0.9)
# --------------------------------------------------------------------------


class SelfApprovalError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status.HTTP_409_CONFLICT, detail)


def enforce_separation_of_duties(golden: GoldenRecord, approver: User) -> None:
    """Refuse self-approval with 409 and an explanation (spec §0.9).

    Recording `proposed_by` and `approved_by` separately is what makes this
    checkable after the fact; refusing here is what makes it true.
    """
    if golden.proposed_by is not None and golden.proposed_by == approver.id:
        raise SelfApprovalError(
            "Separation of duties: you proposed this golden record, so you cannot "
            "also approve it. Another approver or the registrar must confirm it."
        )


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.active:
        return None
    return user if verify_password(password, user.password_hash) else None


# --------------------------------------------------------------------------
# Login throttling
# --------------------------------------------------------------------------

#: Failed attempts allowed per (client, email) before the pair is locked out.
LOGIN_ATTEMPTS = 8

#: How long the window lasts, and therefore how long a lockout lasts.
LOGIN_WINDOW_SECONDS = 300

#: In-process, because SAMAN is a single-process deployment by design. A real
#: multi-worker deployment would put this in shared storage; what must not
#: happen either way is an unlimited-guess password endpoint.
_FAILURES: dict[tuple[str, str], list[float]] = {}


def _prune(bucket: list[float], now: float) -> list[float]:
    return [t for t in bucket if now - t < LOGIN_WINDOW_SECONDS]


def login_blocked(client: str, email: str) -> int:
    """Seconds remaining on a lockout, or 0 if the attempt may proceed."""
    key = (client, email.lower())
    now = time.time()
    bucket = _prune(_FAILURES.get(key, []), now)
    _FAILURES[key] = bucket
    if len(bucket) < LOGIN_ATTEMPTS:
        return 0
    return max(1, int(LOGIN_WINDOW_SECONDS - (now - bucket[0])))


def record_login_failure(client: str, email: str) -> None:
    key = (client, email.lower())
    now = time.time()
    _FAILURES[key] = [*_prune(_FAILURES.get(key, []), now), now]


def clear_login_failures(client: str, email: str) -> None:
    """A success wipes the slate: the throttle exists to stop guessing, not to
    punish someone who mistyped their password twice."""
    _FAILURES.pop((client, email.lower()), None)


def reset_login_throttle() -> None:
    _FAILURES.clear()
