"""Tier-1 probabilistic linkage — spec §0.4.

The contract that matters is not that splink is fast or accurate: it is that
the engine produces the same *decisions* whether or not splink is present, and
that a failure inside it can never take the pipeline down.
"""

import pytest

from app.capabilities import refresh
from app.linkage import LinkageResult, run_linkage
from app.match import MatchCandidate, match_pair, tier1_fuzzy, tier1_linkage


def item(item_id, text, mpn=None, attrs=None):
    import hashlib

    import numpy as np

    return MatchCandidate(
        id=item_id,
        class_code="bearing.ball.deep_groove",
        class_confidence=1.0,
        norm_text=text,
        norm_hash=hashlib.sha256(text.encode()).hexdigest(),
        mpn_norm=mpn,
        gtin=None,
        attrs=attrs or {},
        vector=np.array([1.0, 0.0], dtype=np.float32),
    )


class TestLinkageResult:
    def test_lookup_is_order_independent(self):
        result = LinkageResult(probability={(1, 2): 0.9})
        assert result.score(1, 2) == result.score(2, 1) == 0.9

    def test_an_unscored_pair_returns_none(self):
        assert LinkageResult().score(1, 2) is None

    def test_waterfall_carries_the_per_comparison_contribution(self):
        """§9: the evidence card shows contributions, not a bare score."""
        result = LinkageResult(
            probability={(1, 2): 0.97},
            weight={(1, 2): 5.2},
            levels={(1, 2): {"mpn_norm": 1, "norm_text": 3}},
        )
        waterfall = result.waterfall(1, 2)
        assert waterfall["engine"] == "splink"
        assert waterfall["match_weight"] == 5.2
        assert waterfall["comparison_levels"]["mpn_norm"] == 1

    def test_no_waterfall_for_an_unscored_pair(self):
        assert LinkageResult().waterfall(1, 2) is None


class TestTierOneSelection:
    """splink when it scored the pair, rapidfuzz otherwise."""

    def test_splink_score_is_preferred_when_present(self):
        a, b = item(1, "BEARING BALL 6205 ZZ SKF"), item(2, "BRG BALL 6205ZZ SKF")
        linkage = LinkageResult(probability={(1, 2): 0.93}, weight={(1, 2): 4.0})
        score, engine, _ = tier1_linkage(a, b, linkage)
        assert engine == "splink" and score == 0.93

    def test_a_pair_splink_never_saw_falls_back(self):
        """splink's blocking is coarser than ours; unscored is not zero."""
        a, b = item(1, "BEARING BALL 6205 ZZ SKF"), item(2, "BRG BALL 6205ZZ SKF")
        score, engine, waterfall = tier1_linkage(a, b, LinkageResult())
        assert engine == "rapidfuzz"
        assert score == pytest.approx(tier1_fuzzy(a, b))
        assert waterfall is None

    def test_no_linkage_at_all_falls_back(self):
        a, b = item(1, "BEARING BALL 6205"), item(2, "BEARING BALL 6205")
        assert tier1_linkage(a, b, None)[1] == "rapidfuzz"

    def test_the_engine_used_is_recorded_on_every_pair(self):
        """A judge asking "which engine decided this?" gets an answer."""
        a, b = item(1, "BEARING BALL 6205 ZZ SKF"), item(2, "BEARING BALL 6205 ZZ SKF")
        assert match_pair(a, b).tier_scores["tier1_engine"] == "rapidfuzz"
        linked = match_pair(a, b, LinkageResult(probability={(1, 2): 0.99}))
        assert linked.tier_scores["tier1_engine"] == "splink"

    def test_the_waterfall_reaches_the_evidence(self):
        a, b = item(1, "BEARING BALL 6205 ZZ SKF"), item(2, "BEARING BALL 6205 ZZ SKF")
        linkage = LinkageResult(
            probability={(1, 2): 0.99}, weight={(1, 2): 6.1},
            levels={(1, 2): {"mpn_norm": 1}},
        )
        scores = match_pair(a, b, linkage).tier_scores
        assert scores["tier1_waterfall"]["match_weight"] == 6.1


class TestGracefulDegradation:
    """§9: a broken accelerator must never take the pipeline down."""

    def test_disabling_optional_engines_forces_the_fallback(self, monkeypatch, db):
        monkeypatch.setenv("SAMAN_DISABLE_OPTIONAL", "true")
        refresh()
        try:
            assert run_linkage(db) is None
        finally:
            monkeypatch.delenv("SAMAN_DISABLE_OPTIONAL", raising=False)
            refresh()

    def test_capabilities_report_the_forced_fallback(self, monkeypatch):
        monkeypatch.setenv("SAMAN_DISABLE_OPTIONAL", "true")
        try:
            caps = refresh()
            assert caps.linkage_mode == "rapidfuzz"
            assert caps.embedding_mode == "tfidf"
            assert any("disabled" in note for note in caps.degraded)
        finally:
            monkeypatch.delenv("SAMAN_DISABLE_OPTIONAL", raising=False)
            refresh()

    def test_a_failure_inside_splink_degrades_rather_than_raises(self, monkeypatch, db):
        """Whatever goes wrong in there, the pipeline keeps running."""
        import app.linkage as linkage_module

        monkeypatch.setattr(
            linkage_module, "_frame", lambda _db: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        refresh()
        assert run_linkage(db) is None

    def test_capability_detection_requires_a_real_import(self):
        """`find_spec` succeeds for a package installed without its own
        dependencies; /api/health must not advertise an engine that cannot run."""
        from app.capabilities import _importable

        assert _importable("json") is True
        assert _importable("a_module_that_does_not_exist") is False
