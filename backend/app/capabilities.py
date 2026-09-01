"""Capability detection with graceful degradation (spec 0.4, 9).

SAMAN must never crash because an optional dependency is missing. Every tier
resolves to a working implementation; this module decides *which* one and makes
that decision visible at ``GET /api/health`` and on the /admin health panel.

    Tier 1  splink                 -> rapidfuzz-only scoring
    Tier 2  sentence-transformers  -> scikit-learn TF-IDF char 3-5grams
    Tier 3  Ollama                 -> deterministic rule-based adjudicator

Detection is import-only and cached: no work, no network, no model download
happens here. Ollama is probed lazily by the copilot/adjudicator, never at
startup, so a dead localhost daemon cannot slow or break boot.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from functools import lru_cache

from .config import get_settings


def _importable(module: str) -> bool:
    """True if ``module`` can be imported without actually importing it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        # A broken/partial install raises here. Treat as absent and degrade.
        return False


@dataclass(frozen=True)
class Capabilities:
    linkage_mode: str  # "splink" | "rapidfuzz"
    embedding_mode: str  # "sentence-transformers" | "tfidf"
    llm_mode: str  # "ollama" | "deterministic"
    sovereign_mode: bool
    degraded: list[str] = field(default_factory=list)

    @property
    def all_optional_present(self) -> bool:
        return not self.degraded

    def as_dict(self) -> dict:
        return {
            "linkage": {
                "mode": self.linkage_mode,
                "engine": "splink (Fellegi-Sunter, DuckDB)"
                if self.linkage_mode == "splink"
                else "rapidfuzz token_set_ratio",
                "degraded": self.linkage_mode != "splink",
            },
            "embedding": {
                "mode": self.embedding_mode,
                "engine": "sentence-transformers all-MiniLM-L6-v2"
                if self.embedding_mode == "sentence-transformers"
                else "scikit-learn TF-IDF char 3-5grams",
                "degraded": self.embedding_mode != "sentence-transformers",
            },
            "llm": {
                "mode": self.llm_mode,
                "engine": "ollama" if self.llm_mode == "ollama" else "rule-based adjudicator",
                "degraded": self.llm_mode != "ollama",
            },
            "sovereign_mode": self.sovereign_mode,
            "degraded": self.degraded,
        }


@lru_cache
def detect() -> Capabilities:
    settings = get_settings()
    degraded: list[str] = []

    if _importable("splink"):
        linkage = "splink"
    else:
        linkage = "rapidfuzz"
        degraded.append("splink unavailable — Tier 1 using rapidfuzz-only scoring")

    if _importable("sentence_transformers"):
        embedding = "sentence-transformers"
    else:
        embedding = "tfidf"
        degraded.append("sentence-transformers unavailable — Tier 2 using TF-IDF char 3-5grams")

    if settings.llm_enabled:
        llm = "ollama"
    else:
        llm = "deterministic"
        if settings.saman_sovereign_mode:
            degraded.append("sovereign mode ON — Tier 3 forced to rule-based adjudicator")
        else:
            degraded.append("OLLAMA_URL unset — Tier 3 using rule-based adjudicator")

    return Capabilities(
        linkage_mode=linkage,
        embedding_mode=embedding,
        llm_mode=llm,
        sovereign_mode=settings.saman_sovereign_mode,
        degraded=degraded,
    )


def refresh() -> Capabilities:
    """Re-detect after a settings change (e.g. the /admin sovereign toggle)."""
    detect.cache_clear()
    get_settings.cache_clear()
    return detect()
