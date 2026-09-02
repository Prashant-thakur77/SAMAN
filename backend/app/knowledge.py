"""Grounded answers about the system from a local model (§0.4 Tier 3, §6.9).

The deterministic assistant knows the screens and a page of facts. Everything
past that used to end in "I could not answer that". This module closes the gap
without opening the door the Copilot keeps shut: the model answers only from
passages retrieved out of the project's own documents, it is told to say so
when the passages do not contain the answer, and every figure it produces is
checked back against those passages. What it cannot do is decide anything about
the data; that path stays with the Copilot.

Retrieval is TF-IDF over paragraph chunks of README.md, KNOWN_GAPS.md, the build
spec and the assistant's own topic cards. All local, all offline. The model is
whatever Ollama serves at `OLLAMA_URL`; without one, `available()` is False and
the assistant behaves exactly as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx

from .config import REPO_ROOT, get_settings

#: Documents worth reading, in the order a reader would.
SOURCES: tuple[tuple[str, Path], ...] = (
    ("README", REPO_ROOT / "README.md"),
    ("Known gaps", REPO_ROOT / "KNOWN_GAPS.md"),
    ("Build spec", REPO_ROOT / "SAMAN_CLAUDE_CODE_SPEC.md"),
)
#: Top hits handed to the model, each with its following paragraph. Small,
#: so a 3B model stays on the point.
TOP_K = 4
#: Words per chunk, roughly a paragraph.
CHUNK_WORDS = 160
#: The model's answer is a paragraph, not an essay.
MAX_ANSWER_CHARS = 900
#: What the model is told to say when the passages do not cover the question.
DONT_KNOW = "I do not have that in the project's documents."

SYSTEM_PROMPT = """You are the assistant inside SAMAN, the Standardised Asset & Material
Analysis Network: a prototype for Smart India Hackathon 2026 (problem statement
SIH26099) that harmonises material master data across Indian public sector
undertakings and issues the Common National Material Code (CNMC).

Answer the user's question using ONLY the passages provided. Rules:
- If the passages do not contain the answer, reply exactly: "{dont_know}"
- Never invent numbers, names, screens or features. Every figure you state
  must appear in the passages.
- Be concrete and brief: two to five sentences, plain English, no headings,
  no bullet lists, no markdown.
- Stay close to the passages' own wording. Do not generalise, speculate, or
  add background the passages do not state.
- SAMAN is the platform; the CNMC is the code it issues. Do not confuse them.
- You cannot run queries or see live data. For questions about the data
  (counts, prices, which CPSE, stock), say the Copilot answers those.
"""


@dataclass
class Chunk:
    source: str
    heading: str
    text: str


@dataclass
class Grounded:
    text: str
    sources: list[dict] = field(default_factory=list)
    mode: str = "llm"
    note: str | None = None
    refused: bool = False


def available() -> bool:
    """A model is configured and reachable. Cheap: one probe, cached per process."""
    settings = get_settings()
    if not settings.llm_enabled:
        return False
    return _reachable(settings.ollama_url or "", settings.ollama_model)


@lru_cache(maxsize=4)
def _reachable(url: str, model: str) -> bool:
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=2.0)
        response.raise_for_status()
        names = {m.get("name", "") for m in response.json().get("models", [])}
    except Exception:
        return False
    return model in names or f"{model}:latest" in names or any(n.startswith(model) for n in names)


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def _chunk_markdown(source: str, text: str) -> list[Chunk]:
    """Split on headings, then into ~CHUNK_WORDS pieces, keeping the heading."""
    chunks: list[Chunk] = []
    heading = source
    buffer: list[str] = []

    def flush() -> None:
        words = " ".join(buffer).split()
        buffer.clear()
        for i in range(0, len(words), CHUNK_WORDS):
            piece = " ".join(words[i : i + CHUNK_WORDS]).strip()
            if len(piece) > 40:
                chunks.append(Chunk(source, heading, piece))

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip() or heading
            continue
        if line.startswith("![") or line.startswith("<"):
            continue
        buffer.append(re.sub(r"[`*_|]", " ", line))
    flush()
    return chunks


@lru_cache(maxsize=1)
def corpus() -> list[Chunk]:
    from .assistant import TOPICS

    chunks: list[Chunk] = []
    for label, path in SOURCES:
        if path.exists():
            chunks.extend(_chunk_markdown(label, path.read_text(encoding="utf-8", errors="ignore")))
    for topic in TOPICS:
        chunks.append(Chunk("Assistant", topic.key.replace("_", " "), topic.answer))
    return chunks


@lru_cache(maxsize=1)
def _index():
    from sklearn.feature_extraction.text import TfidfVectorizer

    docs = corpus()
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    matrix = vectorizer.fit_transform(f"{c.heading} {c.text}" for c in docs)
    return vectorizer, matrix


def retrieve(question: str, k: int = TOP_K) -> list[tuple[Chunk, float]]:
    """The best-matching passages, each with the paragraph that follows it.

    Chunking splits a paragraph from the sentence after it, and that sentence
    is often where the number lives: the sub-blocking note says what was tried
    in one chunk and by how much it moved recall in the next. The figure guard
    then refuses a correct answer for quoting the right document. Carrying the
    neighbour keeps the fact and its figure in the same context.
    """
    vectorizer, matrix = _index()
    scores = (matrix @ vectorizer.transform([question]).T).toarray().ravel()
    order = [int(i) for i in scores.argsort()[::-1][:k] if scores[i] > 0.02]
    docs = corpus()
    picked: list[tuple[Chunk, float]] = []
    seen: set[int] = set()
    for i in order:
        for j in (i, i + 1):
            if j in seen or j >= len(docs):
                continue
            if j != i and docs[j].source != docs[i].source:
                continue
            seen.add(j)
            picked.append((docs[j], float(scores[j]) if j == i else float(scores[i]) * 0.5))
        if len(picked) >= k * 2:
            break
    return picked


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*", text))


def _call_model(question: str, passages: list[tuple[Chunk, float]]) -> str:
    settings = get_settings()
    context = "\n\n".join(
        f"[{i + 1}] ({c.source} · {c.heading}) {c.text}" for i, (c, _) in enumerate(passages)
    )
    response = httpx.post(
        f"{(settings.ollama_url or '').rstrip('/')}/api/chat",
        json={
            "model": settings.ollama_model,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 260},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.format(dont_know=DONT_KNOW)},
                {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {question}"},
            ],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return (response.json().get("message", {}).get("content") or "").strip()


def answer(question: str) -> Grounded | None:
    """A grounded answer, or None when there is nothing safe to say.

    None means: no model, no relevant passages, the model declined, or the
    model's answer failed the checks. The caller falls back to its own words.
    """
    if not available():
        return None
    passages = retrieve(question)
    if not passages:
        return None
    try:
        text = _call_model(question, passages)
    except Exception as exc:
        return Grounded(
            "", mode="llm", note=f"local model unavailable ({type(exc).__name__})", refused=True
        )

    if not text or DONT_KNOW.lower() in text.lower() or len(text) > MAX_ANSWER_CHARS:
        return None
    context_text = " ".join(c.text for c, _ in passages)
    invented = _numbers(text) - _numbers(context_text) - _numbers(question)
    if invented:
        return Grounded(
            "",
            note=f"the model introduced figures not in the documents: {sorted(invented)[:3]}",
            refused=True,
        )
    sources = [
        {"source": c.source, "heading": c.heading, "score": round(s, 3)} for c, s in passages[:3]
    ]
    return Grounded(text, sources=sources, mode="llm")
