"""Capability detection must flip modes, not just always report 'degraded'.

The demo laptop usually lacks splink/sentence-transformers, so the degraded
path is what normally runs. These tests pin the *upgrade* path too, so a broken
detector cannot hide behind a permanently-degraded default (spec §0.4).
"""

import pytest

from app import capabilities
from app.config import Settings


@pytest.fixture(autouse=True)
def clear_caches():
    capabilities.detect.cache_clear()
    yield
    capabilities.detect.cache_clear()


def test_all_optional_present_upgrades_every_tier(monkeypatch):
    monkeypatch.setattr(capabilities, "_importable", lambda _module: True)
    monkeypatch.setattr(
        capabilities,
        "get_settings",
        lambda: Settings(ollama_url="http://localhost:11434", saman_sovereign_mode=False),
    )

    caps = capabilities.detect()
    assert caps.linkage_mode == "splink"
    assert caps.embedding_mode == "sentence-transformers"
    assert caps.llm_mode == "ollama"
    assert caps.degraded == []
    assert caps.all_optional_present


def test_nothing_present_degrades_every_tier(monkeypatch):
    monkeypatch.setattr(capabilities, "_importable", lambda _module: False)
    monkeypatch.setattr(capabilities, "get_settings", lambda: Settings(ollama_url=None))

    caps = capabilities.detect()
    assert caps.linkage_mode == "rapidfuzz"
    assert caps.embedding_mode == "tfidf"
    assert caps.llm_mode == "deterministic"
    assert len(caps.degraded) == 3


def test_sovereign_mode_overrides_ollama_url(monkeypatch):
    """Spec §6.13: with sovereign mode ON the Ollama flag is ignored."""
    from app.config import set_sovereign_mode

    monkeypatch.setattr(capabilities, "_importable", lambda _module: True)
    monkeypatch.setattr(
        capabilities,
        "get_settings",
        lambda: Settings(ollama_url="http://localhost:11434"),
    )
    set_sovereign_mode(True)
    try:
        caps = capabilities.detect()
        assert caps.llm_mode == "deterministic"
        assert caps.sovereign_mode is True
        assert any("sovereign" in note for note in caps.degraded)
    finally:
        set_sovereign_mode(None)


def test_the_runtime_toggle_survives_a_capability_refresh(monkeypatch):
    """The /admin toggle clears the capability cache; the choice must persist.

    Storing it on the cached Settings object lost it moments after it was set.
    """
    from app.config import set_sovereign_mode, sovereign_mode

    set_sovereign_mode(True)
    try:
        capabilities.refresh()
        assert sovereign_mode() is True
    finally:
        set_sovereign_mode(None)
        capabilities.refresh()


def test_broken_install_is_treated_as_absent(monkeypatch):
    """A partially-installed package raises on find_spec; that must degrade, not crash."""

    def explode(_name):
        raise ValueError("bad __spec__")

    monkeypatch.setattr(capabilities.importlib.util, "find_spec", explode)
    assert capabilities._importable("anything") is False
