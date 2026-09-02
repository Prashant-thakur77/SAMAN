"""The hard-constraint veto layer — spec §2A.

These are the tests that protect the claim "similarity never overrides a veto".
"""

import pytest

from app.compare import (
    IN_BAND,
    MATCH,
    MISMATCH,
    OUT_OF_BAND,
    UNKNOWN,
    compare_attr,
    compare_attrs,
    values_equal,
)
from app.taxonomy import AttrSpec, get_schema

BEARING = get_schema("bearing.ball.deep_groove")
VALVE = get_schema("valve.gate")

BASE_BEARING = {
    "bore_mm": 25, "outer_dia_mm": 52, "width_mm": 15, "seal_type": "ZZ",
    "load_rating_kg": 500, "temp_max_c": 120, "brand": "SKF",
}
BASE_VALVE = {
    "size_nb_mm": 50, "pressure_class": "300", "body_material": "SS316",
    "end_connection": "FLANGED", "pressure_bar": 51.1, "temp_max_c": 250,
}


class TestIdentityCritical:
    def test_identical_attributes_match(self):
        assert compare_attrs(BASE_BEARING, dict(BASE_BEARING), BEARING).verdict == "match"

    @pytest.mark.parametrize(
        ("attr", "other"),
        [("bore_mm", 30), ("outer_dia_mm", 62), ("width_mm", 17), ("seal_type", "2RS")],
    )
    def test_any_identity_critical_mismatch_vetoes(self, attr, other):
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, attr: other}, BEARING)
        assert result.is_veto
        assert result.vetoed_by[0]["attr"] == attr

    def test_veto_reports_both_values_for_the_ui(self):
        """The demo moment is "not a duplicate: bore 25 mm vs 30 mm"."""
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, "bore_mm": 30}, BEARING)
        veto = result.vetoed_by[0]
        assert veto["a"] == 25 and veto["b"] == 30
        assert "25" in veto["reason"] and "30" in veto["reason"]

    def test_every_attribute_is_still_compared_after_a_veto(self):
        """The evidence card must show why, not merely that."""
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, "bore_mm": 30}, BEARING)
        assert len(result.per_attr) == len(BEARING.attributes)

    def test_a_missing_value_never_vetoes(self):
        """Refusing on absent evidence turns every extraction gap into a miss."""
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, "bore_mm": None}, BEARING)
        assert not result.is_veto
        assert any(c.result == UNKNOWN for c in result.per_attr)

    def test_cosmetic_difference_never_vetoes(self):
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, "brand": "FAG"}, BEARING)
        assert not result.is_veto


class TestPerformanceBands:
    def test_inside_the_band_is_still_a_duplicate(self):
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, "load_rating_kg": 490}, BEARING)
        assert result.verdict == "tolerance_match" and not result.is_veto

    def test_outside_the_band_is_refused(self):
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, "load_rating_kg": 200}, BEARING)
        assert result.is_veto
        assert result.vetoed_by[0]["attr"] == "load_rating_kg"

    def test_the_specs_worked_example(self):
        """200 kg vs 500 kg on the same designation: refused, but substitutable."""
        lower = {**BASE_BEARING, "load_rating_kg": 200}
        higher = {**BASE_BEARING, "load_rating_kg": 500}
        result = compare_attrs(lower, higher, BEARING)
        assert result.is_veto
        assert result.equivalence_candidate
        assert result.direction == "a_to_b"  # B (500 kg) can substitute A (200 kg)

    def test_valve_three_percent_is_in_band_forty_percent_is_not(self):
        in_band = compare_attrs(BASE_VALVE, {**BASE_VALVE, "pressure_bar": 52.6}, VALVE)
        out_of_band = compare_attrs(BASE_VALVE, {**BASE_VALVE, "pressure_bar": 71.5}, VALVE)
        assert not in_band.is_veto
        assert out_of_band.is_veto

    def test_equal_values_are_exact_not_merely_in_band(self):
        comparison = compare_attr(
            BEARING.attributes["load_rating_kg"], 500, 500
        )
        assert comparison.result == MATCH and comparison.detail == "exact"

    def test_in_band_difference_is_labelled_in_band(self):
        comparison = compare_attr(BEARING.attributes["load_rating_kg"], 500, 490)
        assert comparison.result == IN_BAND

    def test_identity_critical_never_reports_out_of_band(self):
        comparison = compare_attr(BEARING.attributes["bore_mm"], 25, 30)
        assert comparison.result == MISMATCH


class TestDirection:
    """§2B: equivalence is directed; the reverse substitution is unsafe."""

    def test_direction_is_asymmetric(self):
        low = {**BASE_BEARING, "load_rating_kg": 200}
        high = {**BASE_BEARING, "load_rating_kg": 500}
        assert compare_attrs(low, high, BEARING).direction == "a_to_b"
        assert compare_attrs(high, low, BEARING).direction == "b_to_a"

    def test_no_direction_when_neither_side_dominates(self):
        a = {**BASE_BEARING, "load_rating_kg": 500, "temp_max_c": 100}
        b = {**BASE_BEARING, "load_rating_kg": 200, "temp_max_c": 150}
        assert compare_attrs(a, b, BEARING).direction is None

    def test_identity_mismatch_is_not_an_equivalence_candidate(self):
        """A different bore is a different item, not a substitute."""
        result = compare_attrs(BASE_BEARING, {**BASE_BEARING, "bore_mm": 30}, BEARING)
        assert not result.equivalence_candidate


class TestComparators:
    def test_range_overlap_counts_as_agreement(self):
        spec = VALVE.attributes["temp_max_c"]
        assert compare_attr(spec, "-20 to 120", "100 to 200").result == MATCH

    def test_non_overlapping_ranges_disagree(self):
        spec = VALVE.attributes["temp_max_c"]
        assert compare_attr(spec, "-20 to 50", "100 to 200").result == OUT_OF_BAND

    def test_values_written_differently_still_compare(self):
        spec = BEARING.attributes["bore_mm"]
        assert compare_attr(spec, "25", 25.0).result == MATCH

    def test_enum_comparison_ignores_case_and_padding(self):
        spec = BEARING.attributes["seal_type"]
        assert compare_attr(spec, " zz ", "ZZ").result == MATCH


class TestFitClasses:
    """§2A names "tolerance-string parsing (±0.05, H7)" as a comparator.

    A fit class carries a tolerance grade but no magnitude. Comparing it
    numerically made every grade equal to every other one — and equal to zero —
    which on an identity_critical attribute is a silent failure to veto.
    """

    FIT = AttrSpec(name="fit", type="numeric", role="identity_critical", unit="mm", tolerance=0)

    def test_the_same_grade_matches(self):
        assert compare_attr(self.FIT, "H7", "H7").result == MATCH

    @pytest.mark.parametrize(("a", "b"), [("H7", "H6"), ("H7", "JS9"), ("h6", "H7")])
    def test_different_grades_are_refused(self, a, b):
        comparison = compare_attr(self.FIT, a, b)
        assert comparison.result == MISMATCH
        assert comparison.is_veto

    def test_a_grade_is_not_comparable_with_a_magnitude(self):
        """'H7' must not read as the number zero."""
        assert compare_attr(self.FIT, "H7", 0).result == UNKNOWN
        assert compare_attr(self.FIT, "H7", 25).result == UNKNOWN

    def test_a_performance_grade_reports_out_of_band(self):
        spec = AttrSpec(name="fit", type="numeric", role="performance", tolerance_pct=5)
        assert compare_attr(spec, "H7", "H6").result == OUT_OF_BAND


class TestEvidence:
    def test_evidence_object_is_serialisable_and_complete(self):
        evidence = compare_attrs(
            BASE_BEARING, {**BASE_BEARING, "bore_mm": 30}, BEARING
        ).as_evidence()
        assert evidence["verdict"] == "veto"
        assert evidence["vetoed_by"][0]["attr"] == "bore_mm"
        assert len(evidence["per_attr"]) == len(BEARING.attributes)

    def test_agreement_counts_only_comparable_attributes(self):
        sparse = {"bore_mm": 25, "seal_type": "ZZ"}
        result = compare_attrs(sparse, dict(sparse), BEARING)
        assert result.compared == 2 and result.agreement == 1.0


class TestValuesEqual:
    """One home for a comparison this codebase got wrong three times.

    A bore read from "65MM BORE" is the float 65.0; the same bore derived from
    designation 6313 is the int 65. Compared as strings they differ. It cost
    the fit-class comparison, then Smart-Create's retrieval key, then the
    identity-signature blocking key.
    """

    def test_an_int_and_a_float_agree(self):
        assert values_equal(65, 65.0)
        assert values_equal("65", 65.0)
        assert values_equal("65.0", "65")

    def test_a_unit_suffix_is_left_to_the_attribute_comparator(self):
        """Unit-aware comparison needs the attribute's declared unit, which
        this helper does not have. "25 MM" is text here, and `compare_attr` is
        where it becomes 25 millimetres."""
        assert not values_equal("25 MM", 25.0)
        assert values_equal("25 MM", " 25 mm ")

    def test_different_numbers_differ(self):
        assert not values_equal(25, 30)
        assert not values_equal("25.0", "25.1")

    def test_text_falls_back_to_text(self):
        assert values_equal("ss316", " SS316 ")

    def test_a_fit_class_is_a_symbol_not_a_magnitude(self):
        """`parse_number("H7")` yields value 0.0 with fit_class "H7", so a naive
        numeric compare makes every fit class equal to every other. Fixed once
        in `compare_attr`; it does not get to come back through here."""
        assert not values_equal("H7", "H6")
        assert values_equal("H7", "h7")
        assert not values_equal("H7", 0.0)

    def test_none_matches_only_none(self):
        assert values_equal(None, None)
        assert not values_equal(None, 25)
        assert not values_equal(25, None)

    def test_the_three_call_sites_share_it(self):
        """Three implementations of one idea is how the fourth bug happens."""
        from app import equivalence, smart_create

        assert equivalence._equal is values_equal
        assert smart_create._same_value(65, 65.0)
        assert not smart_create._same_value(None, None), (
            "an absent bore is not a reason to retrieve a row"
        )
