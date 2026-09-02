"""POST /api/assistant/query — the floating site assistant."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import assistant
from ..auth import current_user_optional
from ..capabilities import detect
from ..db import get_db
from ..models import User
from ..visibility import scope_for

router = APIRouter(prefix="/assistant", tags=["assistant"])


class Query(BaseModel):
    question: str = Field(max_length=500)
    #: Where the asker is, so "open the workbench" from the workbench is
    #: answered rather than performed.
    path: str | None = Field(default=None, max_length=200)


@router.get("/suggestions")
def suggestions() -> dict:
    return {
        "prompts": list(assistant.SUGGESTIONS),
        "routes": [{"path": r.path, "label": r.label, "blurb": r.blurb} for r in assistant.ROUTES],
        "engine": detect().llm_mode,
    }


@router.post("/query")
def query(
    body: Query,
    user: Annotated[User | None, Depends(current_user_optional)] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Answer one utterance: navigate, explain, or hand it to the Copilot.

    Unauthenticated callers get the front page's scope, which is the most
    restricted one; the Copilot path applies it exactly as /api/copilot does.
    """
    scope = scope_for(user)
    reply = assistant.answer(db, body.question, scope, current_path=body.path)
    payload = reply.as_dict()
    payload["scope"] = scope.as_dict()
    return payload
