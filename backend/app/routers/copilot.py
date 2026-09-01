"""Copilot endpoint — spec §5, §6.9."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import copilot
from ..auth import current_user_optional
from ..capabilities import detect
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..visibility import scope_for

router = APIRouter(prefix="/copilot", tags=["copilot"])


class Query(BaseModel):
    question: str


@router.get("/suggestions")
def suggestions() -> dict:
    """The prompt row on the copilot screen, drawn from the whitelist itself."""
    settings = get_settings()
    return {
        "prompts": copilot.suggested_prompts(),
        "templates": [
            {"key": t.key, "description": t.description, "example": t.example}
            for t in copilot.TEMPLATES
        ],
        "mode": detect().llm_mode,
        "sovereign_mode": settings.saman_sovereign_mode,
        "note": (
            "Questions never become SQL. Each one selects a reviewed query and "
            "its parameters, or searches the golden records."
        ),
    }


@router.post("/query")
def query(
    body: Query,
    user: Annotated[User | None, Depends(current_user_optional)] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Answer one question, guarded and scoped to the viewer's role (§0.9b)."""
    settings = get_settings()
    scope = scope_for(user)
    answer = copilot.answer(db, body.question, scope, use_llm=settings.llm_enabled)

    payload = answer.as_dict()
    if settings.llm_enabled and not answer.refused:
        composed, rejection = copilot.compose_with_llm(
            body.question, answer.text, answer.rows
        )
        payload["answer"] = composed
        payload["mode"] = "template" if rejection else "llm"
        if rejection:
            payload["llm_rejected"] = rejection
    else:
        payload["mode"] = "template"

    payload["scope"] = scope.as_dict()
    payload["engine"] = detect().llm_mode
    return payload
