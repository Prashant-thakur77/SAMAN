"""The tiered matcher — spec §0.4, §2A, §2B."""

from typing import ClassVar

import numpy as np
import pytest

from app.match import (
    T_HIGH,
    T_LOW,
    MatchCandidate,
    distinct_manufacturers,
    match_pair,
    tier0_anchor,
    tier1_fuzzy,
)

BEARING = "bearing.ball.deep_groove"
ATTRS = {
    "bore_mm": 25, "outer_dia_mm": 52, "width_mm": 15, "seal_type": "ZZ",
    "load_rating_kg": 500, "temp_max_c": 120, "brand": "SKF",
}


def item(item_id, text, attrs=None, mpn=None, cls=BEARING, gtin=None, vector=None, conf=1.0):
    import hashlib

    return MatchCandidate(
        id=item_id,
        class_code=cls,
        class_confidence=conf,
        norm_text=text,
        norm_hash=hashlib.sha256(text.encode()).hexdigest(),
        mpn_norm=mpn,
        gtin=gtin,
        attrs=dict(ATTRS if attrs is None else attrs),
        vector=vector if vector is not None else np.array([1.0, 0.0], dtype=np.float32),
    )


class TestTierZero:
    def test_matching_mpn_is_the_strongest_anchor(self):
        score, kind = tier0_anchor(item(1, "A", mpn="62052Z"), item(2, "B", mpn="62052Z"))
        assert score == 1.0 and kind == "mpn"

    def test_gtin_also_anchors(self):
        _, kind = tier0_anchor(item(1, "A", gtin="12345678"), item(2, "B", gtin="12345678"))
        assert kind == "gtin"

    def test_identical_text_anchors_slightly_lower(self):
        score, kind = tier0_anchor(item(1, "SAME"), item(2, "SAME"))
        assert kind == "norm_text" and score < 1.0

    def test_nothing_shared_gives_no_anchor(self):
        assert tier0_anchor(item(1, "A"), item(2, "B"))[1] is None


class TestTierOne:
    def test_abbreviated_and_spelled_out_forms_score_high(self):
        score = tier1_fuzzy(
            item(1, "BEARING BALL 6205 ZZ SKF"), item(2, "BEARING BALL 6205ZZ SKF")
        )
        assert score > 0.8

    def test_unrelated_text_scores_low(self):
        assert tier1_fuzzy(item(1, "BEARING BALL 6205"), item(2, "HELMET SAFETY CLASS A")) < 0.5


class TestVetoOverridesSimilarity:
    """§2A: no similarity score may override a hard constraint."""

    def test_identical_text_is_still_refused_on_a_bore_mismatch(self):
        a = item(1, "BEARING BALL 6205 ZZ SKF")
        b = item(2, "BEARING BALL 6205 ZZ SKF", attrs={**ATTRS, "bore_mm": 30})
        result = match_pair(a, b)
        assert result.verdict == "distinct"
        assert result.veto["vetoed_by"][0]["attr"] == "bore_mm"

    def test_matching_mpn_with_conflicting_specs_is_a_conflict_not_a_merge(self):
        """§0.4: same part number, different specifications is a data-quality
        error — never silently merged and never silently dropped."""
        a = item(1, "A", mpn="62052Z")
        b = item(2, "B", attrs={**ATTRS, "bore_mm": 30}, mpn="62052Z")
        result = match_pair(a, b)
        assert result.verdict == "conflict"
        assert result.needs_review
        assert "62052Z" in result.evidence["conflict"]

    def test_a_refused_pair_still_carries_its_evidence(self):
        a = item(1, "A")
        b = item(2, "B", attrs={**ATTRS, "bore_mm": 30})
        result = match_pair(a, b)
        assert result.veto is not None
        assert result.veto["per_attr"]


class TestManufacturerRule:
    """§2B: interchangeable is not identical."""

    def test_different_brands_are_not_duplicates(self):
        a = item(1, "BEARING 6205 ZZ SKF", mpn="62052Z")
        b = item(2, "BEARING 6205 ZZ FAG", attrs={**ATTRS, "brand": "FAG"}, mpn="62052ZR")
        result = match_pair(a, b)
        assert result.verdict == "distinct"
        assert result.equivalence["basis"] == "crossref"

    def test_a_missing_brand_keeps_the_rule_silent(self):
        """A misspelled brand extracts as None; costing recall would be worse."""
        a = item(1, "A", mpn="62052Z")
        b = item(2, "B", attrs={k: v for k, v in ATTRS.items() if k != "brand"}, mpn="62052Z")
        assert distinct_manufacturers(a, b) is None

    def test_same_brand_is_unaffected(self):
        assert distinct_manufacturers(item(1, "A"), item(2, "B")) is None

    def test_brand_alone_is_enough_evidence(self):
        a = item(1, "A")
        b = item(2, "B", attrs={**ATTRS, "brand": "FAG"})
        assert distinct_manufacturers(a, b) == "brand"


class TestSchemaLessPool:
    """§2A.1: without a class there are no identity_critical fields to veto with."""

    def test_unclassified_items_may_only_match_on_an_anchor(self):
        a = item(1, "MYSTERY ITEM", cls="unclassified", conf=0.0)
        b = item(2, "OTHER MYSTERY", cls="unclassified", conf=0.0)
        result = match_pair(a, b)
        assert result.verdict == "distinct"
        assert result.evidence["route"] == "anchor_only"

    def test_an_anchor_key_still_matches_in_the_pool(self):
        a = item(1, "MYSTERY", cls="unclassified", mpn="ABC123", conf=0.0)
        b = item(2, "OTHER", cls="unclassified", mpn="ABC123", conf=0.0)
        assert match_pair(a, b).verdict == "duplicate"

    def test_cross_class_pairs_take_the_same_route(self):
        a = item(1, "X", cls=BEARING)
        b = item(2, "Y", cls="valve.gate")
        assert match_pair(a, b).evidence["route"] == "anchor_only"

    def test_the_reason_is_explained_for_the_workbench(self):
        a = item(1, "X", cls="unclassified", conf=0.1)
        b = item(2, "Y", cls="unclassified", conf=0.1)
        assert "class uncertain" in match_pair(a, b).evidence["reason"]


class TestThinEvidenceIsHeldBack:
    """A pair may not be merged on attributes that were never checked.

    Found by following an implausible dashboard number back to its cause: a
    typo turning "120.0 SQMM" into "120.0 QMM" destroyed `cores` and `csa_mm2`
    together, the three remaining identity attributes agreed, and a 5-core
    120mm² cable was merged with a 3-core 4mm² one.
    """

    CABLE = "cable.power"
    FULL_CABLE: ClassVar[dict] = {
        "cores": 3.0, "csa_mm2": 4.0, "voltage_v": 11000.0,
        "conductor": "AL", "insulation": "XLPE", "temp_max_c": 70.0,
    }

    def _cable(self, item_id, attrs, text="CABLE POWER 3C X 4.0 SQMM ALUMINIUM XLPE 11000V"):
        return item(item_id, text, attrs=attrs, cls=self.CABLE)

    def test_a_pair_missing_its_defining_attribute_is_not_auto_merged(self):
        damaged = {k: v for k, v in self.FULL_CABLE.items() if k not in ("cores", "csa_mm2")}
        result = match_pair(
            self._cable(1, dict(self.FULL_CABLE)),
            self._cable(2, damaged, "CABLE POWER 5C X 120.0 QMM ALUMINIUM XLPE 11000V"),
        )
        assert result.band != "high"
        assert result.verdict != "duplicate"
        assert "too little of what defines this item" in result.evidence["held_for_review"]

    def test_a_complete_pair_is_still_auto_merged(self):
        result = match_pair(
            self._cable(1, dict(self.FULL_CABLE)), self._cable(2, dict(self.FULL_CABLE))
        )
        assert result.band == "high"

    def test_the_evidence_records_what_could_not_be_compared(self):
        damaged = {k: v for k, v in self.FULL_CABLE.items() if k != "csa_mm2"}
        evidence = match_pair(
            self._cable(1, dict(self.FULL_CABLE)), self._cable(2, damaged)
        ).evidence
        assert evidence["defining_attribute"] == "csa_mm2"
        assert evidence["defining_attribute_compared"] is False

    def test_a_shared_part_number_is_itself_an_identity_claim(self):
        """An exact anchor is exempt: the manufacturer has already asserted it."""
        damaged = {k: v for k, v in self.FULL_CABLE.items() if k not in ("cores", "csa_mm2")}
        result = match_pair(
            item(1, "CABLE POWER 3C X 4.0 SQMM", attrs=dict(self.FULL_CABLE),
                 mpn="KEIPW00987", cls=self.CABLE),
            item(2, "CABLE POWER QMM", attrs=damaged, mpn="KEIPW00987", cls=self.CABLE),
        )
        assert result.band == "high"


class TestBandsAndConfidence:
    def test_identical_items_land_in_the_high_band(self):
        result = match_pair(item(1, "BEARING BALL 6205 ZZ SKF", mpn="62052Z"),
                            item(2, "BEARING BALL 6205 ZZ SKF", mpn="62052Z"))
        assert result.band == "high" and result.verdict == "duplicate"
        assert result.confidence >= T_HIGH

    def test_thresholds_are_ordered(self):
        assert 0 < T_LOW < T_HIGH < 1

    def test_tier_scores_are_recorded_for_the_evidence_card(self):
        scores = match_pair(item(1, "A", mpn="X1234"), item(2, "B", mpn="X1234")).tier_scores
        assert {"tier0_anchor", "tier1_fuzzy", "tier2_semantic"} <= set(scores)

    def test_a_grey_pair_is_routed_to_review_not_decided(self):
        result = match_pair(
            item(1, "BEARING BALL 6205 ZZ SKF"),
            item(2, "BEARING DEEP GROOVE ALTERNATE WORDING SKF",
                 attrs={"seal_type": "ZZ"},
                 vector=np.array([0.7, 0.714], dtype=np.float32)),
        )
        assert result.band == "grey" and result.verdict == "review" and result.needs_review

    @pytest.mark.parametrize("band", ["high", "grey", "low"])
    def test_every_band_is_reachable(self, band):
        pairs = {
            "high": (item(1, "BEARING BALL 6205 ZZ SKF", mpn="62052Z"),
                     item(2, "BEARING BALL 6205 ZZ SKF", mpn="62052Z")),
            # Reworded, no anchor key, only partial attribute evidence: the
            # shape of pair a human should look at rather than the engine
            # deciding alone.
            "grey": (item(1, "BEARING BALL 6205 ZZ SKF"),
                     item(2, "BEARING DEEP GROOVE ALTERNATE WORDING SKF",
                          attrs={"seal_type": "ZZ"},
                          vector=np.array([0.7, 0.714], dtype=np.float32))),
            "low": (item(1, "BEARING BALL 6205 ZZ SKF"),
                    item(2, "BEARING BALL 6205", attrs={**ATTRS, "bore_mm": 30})),
        }
        assert match_pair(*pairs[band]).band == band
