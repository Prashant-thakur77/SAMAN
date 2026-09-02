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

import importlib
import importlib.util
from dataclasses import dataclass, field
from functools import lru_cache

from .config import get_settings, sovereign_mode


def _importable(module: str) -> bool:
    """True only if ``module`` genuinely imports.

    `find_spec` is cheaper, but it merely proves the package directory exists.
    A dependency installed without its own dependencies passes that check and
    then fails on use — so /api/health would advertise an engine that cannot
    run, which is worse than reporting the fallback. Since `detect()` is
    cached, the real import is paid once.
    """
    try:
        importlib.import_module(module)
    except Exception:
        # ImportError, but also anything a broken install raises at import time.
        return False
    return True


@dataclass(frozen=True)
class Capabilities:
    linkage_mode: str  # "splink" | "rapidfuzz"
    embedding_mode: str  # "sentence-transformers" | "tfidf"
    llm_mode: str  # "ollama" | "deterministic"
    sovereign_mode: bool
    #: "rapidocr" | "absent". Not a tier — reading a nameplate is an input to
    #: Smart-Create, not a stage of the matcher — but it is reported the same
    #: way so an operator can see in one place what this install can do.
    ocr_mode: str = "absent"
    stt_mode: str = "absent"
    degraded: list[str] = field(default_factory=list)
    #: True when Tier 1 is on the fallback because an operator chose it, not
    #: because splink is missing. A deliberate choice is not a degradation, and
    #: reporting it as one trains people to ignore the indicator.
    linkage_pinned: bool = False

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
                "degraded": self.linkage_mode != "splink" and not self.linkage_pinned,
                "selected_by": "operator" if self.linkage_pinned else "availability",
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
            "ocr": {
                "mode": self.ocr_mode,
                "engine": "rapidocr (PP-OCRv4, bundled weights)"
                if self.ocr_mode != "absent"
                else "not installed",
                "available": self.ocr_mode != "absent",
            },
            "stt": {
                "mode": self.stt_mode,
                "engine": "faster-whisper (local, CPU)" if self.stt_mode != "absent" else "none",
                "available": self.stt_mode != "absent",
            },
            "sovereign_mode": self.sovereign_mode,
            "degraded": self.degraded,
        }


@lru_cache
def detect() -> Capabilities:
    settings = get_settings()
    degraded: list[str] = []

    forced = settings.saman_disable_optional
    sovereign = sovereign_mode()
    #: Deliberate operator choices, reported but never counted as degradation.
    notes: list[str] = []

    pinned = (settings.saman_tier1_engine or "auto").strip().lower()
    linkage_pinned = False
    if pinned == "rapidfuzz":
        linkage = "rapidfuzz"
        linkage_pinned = True
        notes.append("Tier 1 pinned to rapidfuzz by SAMAN_TIER1_ENGINE")
    elif _importable("splink") and not forced:
        linkage = "splink"
    else:
        linkage = "rapidfuzz"
        if pinned == "splink":
            degraded.append("Tier 1 pinned to splink, but splink is not installed")
        degraded.append(
            "optional engines disabled — Tier 1 using rapidfuzz-only scoring"
            if forced
            else "splink unavailable — Tier 1 using rapidfuzz-only scoring"
        )

    if _importable("sentence_transformers") and not forced:
        embedding = "sentence-transformers"
    else:
        embedding = "tfidf"
        degraded.append(
            "optional engines disabled — Tier 2 using TF-IDF char 3-5grams"
            if forced
            else "sentence-transformers unavailable — Tier 2 using TF-IDF char 3-5grams"
        )

    # Not counted as a degradation: OCR is an optional input to one screen, and
    # the screen says so itself. Counting it would make the chip cry wolf on a
    # perfectly complete install.
    ocr = "rapidocr" if (_importable("rapidocr_onnxruntime") and not forced) else "absent"
    from . import stt as _stt

    stt_mode = _stt.mode()
    if stt_mode == "absent":
        notes.append(
            "local speech recognition absent (make deps-stt); voice falls back to the browser"
        )
    if ocr == "absent":
        notes.append(
            "OCR reader not installed — Smart-Create accepts typed descriptions only"
        )

    if settings.llm_enabled:
        llm = "ollama"
    else:
        llm = "deterministic"
        if sovereign:
            degraded.append("sovereign mode ON — Tier 3 forced to rule-based adjudicator")
        else:
            degraded.append("OLLAMA_URL unset — Tier 3 using rule-based adjudicator")

    return Capabilities(
        linkage_mode=linkage,
        embedding_mode=embedding,
        llm_mode=llm,
        ocr_mode=ocr,
        stt_mode=stt_mode,
        sovereign_mode=sovereign,
        # Notes about deliberate choices are worth showing on the health panel,
        # but they are not degradations and must not be counted as such.
        degraded=degraded + notes,
        linkage_pinned=linkage_pinned,
    )


def refresh() -> Capabilities:
    """Re-detect after a settings change (e.g. the /admin sovereign toggle)."""
    detect.cache_clear()
    get_settings.cache_clear()
    return detect()
