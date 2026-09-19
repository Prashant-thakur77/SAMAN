"""The house dictionary: abbreviations a steward teaches the platform (§2D).

The built-in table (`app/data/abbreviations.py`, 198 rules) is ours. A CPSE's
extracts carry words that are theirs: a plant's own shorthand, a brand the
table never met. This module keeps those in the database, per CPSE or for
every catalogue, versioned by the audit chain, and hands the normaliser the
right dictionary for each row. A new word applies to rows normalised after it
was added; `make pipeline --incremental` or a rerun applies it to the rest,
and the screen says so rather than pretending the past changed.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .data.abbreviations import ABBREVIATIONS
from .models import Abbreviation, Cpse, User

_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9./-]*$")

_memo: tuple[tuple, dict[int | None, dict[str, str]]] | None = None


def _version(db: Session) -> tuple:
    return tuple(
        db.execute(select(func.count(Abbreviation.id), func.max(Abbreviation.id))).one()
    ) + tuple(
        db.execute(select(func.count(Abbreviation.id)).where(Abbreviation.active.is_(False))).one()
    )


def dictionaries(db: Session) -> dict[int | None, dict[str, str]]:
    """Active rows by CPSE id (None = every catalogue), memoised on the table."""
    global _memo
    version = _version(db)
    if _memo and _memo[0] == version:
        return _memo[1]
    out: dict[int | None, dict[str, str]] = {}
    for row in db.execute(
        select(Abbreviation).where(Abbreviation.active.is_(True)).order_by(Abbreviation.id)
    ).scalars():
        out.setdefault(row.cpse_id, {})[row.token] = row.expansion
    _memo = (version, out)
    return out


def for_cpse(db: Session, cpse_id: int | None) -> dict[str, str]:
    """The dictionary a row from this CPSE is normalised with: the global rows
    with the CPSE's own on top."""
    by = dictionaries(db)
    merged = dict(by.get(None, {}))
    if cpse_id is not None:
        merged.update(by.get(cpse_id, {}))
    return merged


def forget() -> None:
    global _memo
    _memo = None


def add(
    db: Session,
    user: User,
    token: str,
    expansion: str,
    cpse_code: str | None = None,
    note: str | None = None,
) -> Abbreviation:
    token = token.strip().upper()
    expansion = " ".join(expansion.strip().upper().split())
    if not _TOKEN.match(token) or len(token) > 32:
        raise ValueError("A token is one word of letters, digits, dots, slashes or dashes.")
    if not expansion or len(expansion) > 128:
        raise ValueError("An expansion is one to a few words.")
    if token == expansion:
        raise ValueError("The expansion is the token itself.")
    cpse = None
    if cpse_code:
        cpse = db.execute(select(Cpse).where(Cpse.code == cpse_code.upper())).scalar_one_or_none()
        if cpse is None:
            raise ValueError(f"Unknown CPSE {cpse_code!r}.")
    if user.role == "steward" and (user.cpse_id is None or cpse is None or cpse.id != user.cpse_id):
        raise PermissionError("A steward adds words for their own CPSE only.")
    existing = db.execute(
        select(Abbreviation).where(
            Abbreviation.token == token,
            Abbreviation.cpse_id == (cpse.id if cpse else None),
            Abbreviation.active.is_(True),
        )
    ).scalar_one_or_none()
    before = None
    if existing is not None:
        before = existing.expansion
        existing.active = False
    row = Abbreviation(
        token=token,
        expansion=expansion,
        cpse_id=cpse.id if cpse else None,
        note=note,
        added_by=user.id,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        action="abbreviation.upsert",
        entity=f"abbreviation:{cpse.code if cpse else 'ALL'}/{token}",
        payload={
            "token": token,
            "before": before,
            "after": expansion,
            "built_in": ABBREVIATIONS.get(token),
            "note": note,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    forget()
    return row


def retire(db: Session, user: User, abbreviation_id: int) -> Abbreviation:
    row = db.get(Abbreviation, abbreviation_id)
    if row is None or not row.active:
        raise LookupError("No such abbreviation.")
    if user.role == "steward" and row.cpse_id != user.cpse_id:
        raise PermissionError("A steward retires words for their own CPSE only.")
    row.active = False
    cpse = db.get(Cpse, row.cpse_id) if row.cpse_id else None
    audit.record(
        db,
        action="abbreviation.retire",
        entity=f"abbreviation:{cpse.code if cpse else 'ALL'}/{row.token}",
        payload={"token": row.token, "expansion": row.expansion},
        user=user.email,
        commit=False,
    )
    db.commit()
    forget()
    return row


def listing(db: Session, cpse_code: str | None = None) -> dict:
    query = (
        select(Abbreviation, Cpse.code, User.name)
        .outerjoin(Cpse, Cpse.id == Abbreviation.cpse_id)
        .join(User, User.id == Abbreviation.added_by)
        .where(Abbreviation.active.is_(True))
        .order_by(Cpse.code.nullsfirst(), Abbreviation.token)
    )
    if cpse_code:
        cpse_id = db.execute(select(Cpse.id).where(Cpse.code == cpse_code.upper())).scalar()
        query = query.where((Abbreviation.cpse_id == cpse_id) | (Abbreviation.cpse_id.is_(None)))
    rows = [
        {
            "id": a.id,
            "token": a.token,
            "expansion": a.expansion,
            "cpse": code,
            "note": a.note,
            "added_by": name,
            "added_at": a.added_at.isoformat(),
            "overrides_built_in": ABBREVIATIONS.get(a.token),
        }
        for a, code, name in db.execute(query).all()
    ]
    return {
        "built_in": len(ABBREVIATIONS),
        "house": rows,
        "note": (
            "House words are consulted before the built-in table and apply to rows "
            "normalised after they were added; rerun the pipeline to apply them to "
            "the rest."
        ),
    }
