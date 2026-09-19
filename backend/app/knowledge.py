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

from . import llm
from .config import REPO_ROOT
from .normalize import apply_hindi_terms, expand_abbreviations, transliterate_devanagari

#: Documents worth reading, in the order a reader would.
SOURCES: tuple[tuple[str, Path], ...] = (
    ("README", REPO_ROOT / "README.md"),
    ("Known gaps", REPO_ROOT / "KNOWN_GAPS.md"),
    ("Build spec", REPO_ROOT / "SAMAN_CLAUDE_CODE_SPEC.md"),
    ("SAP integration", REPO_ROOT / "docs" / "sap-integration.md"),
    ("Roadmap", REPO_ROOT / "docs" / "ROADMAP.md"),
    ("Refinement plan", REPO_ROOT / "docs" / "REFINEMENT_PLAN.md"),
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
- Answer in the language the question was asked in: English, Hindi in
  Devanagari, or Hinglish. Keep technical terms (CNMC, SAP, veto) as they are.
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
    """A model is configured and reachable (see `llm`)."""
    return llm.available()


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
    # The passages are English; a question may be Hindi, Hinglish or house
    # abbreviations. Read it the way a description is read before searching,
    # so "वाल्व" finds the valve passages and "BRG" the bearing ones.
    readable = expand_abbreviations(transliterate_devanagari(apply_hindi_terms(question)))
    scores = (matrix @ vectorizer.transform([f"{question} {readable}"]).T).toarray().ravel()
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
    """Every figure in the text, with thousands separators and a sentence's
    trailing full stop removed, so "0.9775." at the end of the model's sentence
    is the "0.9775" in the passage and not an invented number."""
    return {m.replace(",", "").rstrip(".") for m in re.findall(r"\d[\d,.]*", text)}


def _call_model(question: str, passages: list[tuple[Chunk, float]]) -> str:
    context = "\n\n".join(
        f"[{i + 1}] ({c.source} · {c.heading}) {c.text}" for i, (c, _) in enumerate(passages)
    )
    return llm.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT.format(dont_know=DONT_KNOW)},
            {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.1,
        timeout=60.0,
        max_tokens=260,
    )


def answer(question: str) -> Grounded | None:
    """A grounded answer, or None when there is nothing safe to say.

    None means: no model, no relevant passages, the model declined, or the
    model's answer failed the checks. The caller falls back to its own words.
    Answers are memoised per question and model for the life of the process:
    the same question asked twice in a demo costs one model call, and a local
    3B model's seven seconds happen once.
    """
    if not available():
        return None
    key = (" ".join(question.lower().split()), llm.provider(), llm.model_name())
    if key in _answers:
        return _answers[key]
    result = _answer(question)
    if result is not None and not result.refused:
        _answers[key] = result
    return result


_answers: dict[tuple[str, str, str], Grounded] = {}


def forget_answers() -> None:
    _answers.clear()


def _answer(question: str) -> Grounded | None:
    passages = retrieve(question)
    if not passages:
        llm.record("assistant", "no_passages")
        return None
    try:
        text = _call_model(question, passages)
    except Exception as exc:
        llm.record("assistant", "unavailable")
        return Grounded(
            "", mode="llm", note=f"model unavailable ({type(exc).__name__})", refused=True
        )

    if not text or DONT_KNOW.lower() in text.lower():
        llm.record("assistant", "declined")
        return None
    if len(text) > MAX_ANSWER_CHARS:
        llm.record("assistant", "too_long")
        return None
    context_text = " ".join(c.text for c, _ in passages)
    invented = _numbers(text) - _numbers(context_text) - _numbers(question)
    if invented:
        llm.record("assistant", "invented_figure")
        return Grounded(
            "",
            note=f"the model introduced figures not in the documents: {sorted(invented)[:3]}",
            refused=True,
        )
    llm.record("assistant", "accepted")
    sources = [
        {"source": c.source, "heading": c.heading, "score": round(s, 3)} for c, s in passages[:3]
    ]
    return Grounded(text, sources=sources, mode="llm")
