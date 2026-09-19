"""POST /api/assistant/query — the floating site assistant.

The assistant is the one part of the application a visitor meets before
signing in: it stands on the front page and the sign-in page, explains the
system from its documents, and answers a request to go inside with the
sign-in page first. The database is never opened for a visitor (see
`assistant.answer`), and the speech engines stay behind a session.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import assistant, knowledge, llm, stt, tts
from ..auth import current_user_optional, require_user
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
        "model": {
            "available": knowledge.available(),
            "name": llm.model_name() if knowledge.available() else None,
            "remote": llm.provider() == llm.REMOTE,
            "grounded_on": [label for label, _ in knowledge.SOURCES],
        },
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
    reply = assistant.answer(
        db, body.question, scope, current_path=body.path, signed_in=user is not None
    )
    payload = reply.as_dict()
    payload["scope"] = scope.as_dict()
    payload["signed_in"] = user is not None
    return payload


async def _read_capped(upload: UploadFile, cap: int) -> bytes:
    """Read at most `cap` bytes; refuse rather than buffer an unbounded body."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(64 * 1024):
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "That recording is too long. Keep it to one question.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/voice")
def voice(user: Annotated[User | None, Depends(current_user_optional)] = None) -> dict:
    """Whether speech can be transcribed on this machine, and by what.

    The engines are reported as available only to a signed-in person: they
    are the ones who may call them (`/transcribe` and `/speak` need a
    session), and a visitor told otherwise would press the microphone and
    hear nothing back. A visitor's widget falls back to the browser's own
    engines where it has them, and says so where it has none.
    """
    signed_in = user is not None
    return {
        "available": stt.available() and signed_in,
        "mode": stt.mode() if signed_in else "browser",
        "engine": stt.engine_label() if signed_in else "sign in for the server's recogniser",
        "languages": list(stt.LANGUAGES),
        "signed_in": signed_in,
        "tts": {
            "available": tts.available() and signed_in,
            "mode": tts.mode(),
            "engine": tts.engine_label(),
            "note": (
                "Replies are synthesised on this server and never leave it."
                if tts.available()
                else "Local speech synthesis is not installed; run `make deps-tts`. "
                "The widget falls back to the browser's voices where it has any."
            ),
        },
        "note": (
            "Audio is transcribed on this server and never leaves it."
            if stt.available()
            else "Local speech recognition is not installed; run `make deps-stt`. "
            "The widget falls back to the browser's engine where one exists."
        ),
    }


@router.post("/transcribe")
async def transcribe(
    user: Annotated[User, Depends(require_user)],
    audio: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> dict:
    """One spoken utterance, as PCM WAV, to text. Local, or 503."""
    if not stt.available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Local speech recognition is not installed on this server (`make deps-stt`).",
        )
    payload = await _read_capped(audio, stt.MAX_AUDIO_BYTES)
    try:
        return stt.transcribe(payload, language=language)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


class Speak(BaseModel):
    text: str = Field(max_length=tts.MAX_CHARS)


@router.post("/speak")
def speak(body: Speak, user: Annotated[User, Depends(require_user)]) -> Response:
    """One reply, as PCM WAV, synthesised locally. 503 when the engine is absent."""
    if not tts.available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Local speech synthesis is not installed on this server (`make deps-tts`).",
        )
    try:
        audio = tts.synthesize(body.text)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
