"""Golden-record standardization — spec §2D.

The three things §2D names as acceptance criteria:
  * the golden record carries per-field provenance
  * re-running on unchanged data produces byte-identical descriptions
  * a conflict on an identity_critical attribute blocks auto-approval
"""

from datetime import date

import pytest

from app.standardize import (
    RULE_MAJORITY,
    RULE_PRECISE,
    RULE_RECENT,
    RULE_SOLE,
    RULE_SOURCE,
    Member,
    format_value,
    fuse_attribute,
    render_description,
    standardization_delta,
    standardize,
)
from app.taxonomy import get_schema

BEARING = get_schema("bearing.ball.deep_groove")
VALVE = get_schema("valve.gate")

FULL = {
    "bore_mm": 25, "outer_dia_mm": 52, "width_mm": 15,
    "seal_type": "ZZ", "load_rating_kg": 500, "temp_max_c": 120, "brand": "SKF",
}


def member(item_id, attrs, sources=None, text="BEARING BALL 6205", purchased=None):
    return Member(
        id=item_id, attrs=attrs, sources=sources or {}, norm_text=text, last_purchase=purchased
    )


class TestValueFormatting:
    """Determinism starts here: 25 and 25.0 must render the same way."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(25, "25"), (25.0, "25"), (4.5, "4.5"), (0.5, "0.5"), ("ZZ", "ZZ"), (None, "")],
    )
    def test_values_render_canonically(self, value, expected):
        assert format_value(value) == expected

    def test_no_scientific_notation_creeps_in(self):
        assert "e" not in format_value(0.0001).lower()


class TestRendering:
    def test_a_full_attribute_set_renders_the_whole_template(self):
        text = render_description(FULL, BEARING, mpn="6205-2Z")
        assert text == "BEARING, BALL DEEP GROOVE, 25MM BORE, 52MM OD, 15MM W, ZZ, SKF 6205-2Z"

    def test_unfilled_segments_are_dropped_not_left_hollow(self):
        """Never "BEARING, , 52MM OD"."""
        text = render_description({"bore_mm": 25, "brand": "SKF"}, BEARING)
        assert "{" not in text and ", ," not in text
        assert text == "BEARING, BALL DEEP GROOVE, 25MM BORE, SKF"

    def test_casing_follows_the_schema(self):
        assert render_description(FULL, BEARING) == render_description(FULL, BEARING).upper()

    def test_output_respects_the_length_budget(self):
        text = render_description(FULL, get_schema("ppe.helmet"), mpn="X" * 200)
        assert len(text) <= get_schema("ppe.helmet").max_len

    def test_rendering_is_a_pure_function_of_its_inputs(self):
        assert render_description(FULL, BEARING, "6205-2Z") == render_description(
            FULL, BEARING, "6205-2Z"
        )

    def test_attribute_order_does_not_change_the_output(self):
        """The template fixes the order, not the dict."""
        reversed_attrs = dict(reversed(list(FULL.items())))
        assert render_description(FULL, BEARING) == render_description(reversed_attrs, BEARING)


class TestFusionRules:
    """§2D resolves conflicting source values in a stated order."""

    def test_a_single_value_is_taken_as_is(self):
        fused, conflict = fuse_attribute("bore_mm", [member(1, {"bore_mm": 25})])
        assert fused.value == 25 and fused.rule == RULE_SOLE and conflict is None

    def test_agreement_across_members_is_a_majority(self):
        members = [member(1, {"bore_mm": 25}), member(2, {"bore_mm": 25.0})]
        fused, conflict = fuse_attribute("bore_mm", members)
        assert fused.rule == RULE_MAJORITY and conflict is None

    def test_rule_1_the_higher_confidence_source_wins(self):
        """A parsed designation outranks a value scraped from free text."""
        members = [
            member(1, {"bore_mm": 30}, {"bore_mm": "text"}),
            member(2, {"bore_mm": 25}, {"bore_mm": "designation"}),
        ]
        fused, _ = fuse_attribute("bore_mm", members)
        assert fused.value == 25 and fused.rule == RULE_SOURCE
        assert fused.source_member_id == 2

    def test_rule_2_majority_vote_within_the_best_source(self):
        members = [
            member(1, {"seal_type": "ZZ"}, {"seal_type": "text"}),
            member(2, {"seal_type": "ZZ"}, {"seal_type": "text"}),
            member(3, {"seal_type": "2RS"}, {"seal_type": "text"}),
        ]
        fused, _ = fuse_attribute("seal_type", members)
        assert fused.value == "ZZ" and fused.rule == RULE_MAJORITY

    def test_rule_2b_a_tie_is_broken_by_the_most_recent_purchase(self):
        members = [
            member(1, {"seal_type": "ZZ"}, {"seal_type": "text"}, purchased=date(2024, 1, 1)),
            member(2, {"seal_type": "2RS"}, {"seal_type": "text"}, purchased=date(2026, 1, 1)),
        ]
        fused, _ = fuse_attribute("seal_type", members)
        assert fused.value == "2RS" and fused.rule == RULE_RECENT

    def test_rule_3_the_more_precise_value_wins_an_unbreakable_tie(self):
        members = [
            member(1, {"seal_type": "ZZ APPROX"}, {"seal_type": "text"}),
            member(2, {"seal_type": "ZZ"}, {"seal_type": "text"}),
        ]
        fused, conflict = fuse_attribute("seal_type", members)
        assert fused.rule == RULE_PRECISE
        assert conflict is not None and conflict["attr"] == "seal_type"

    def test_an_absent_attribute_produces_nothing(self):
        assert fuse_attribute("bore_mm", [member(1, {})]) == (None, None)

    def test_every_candidate_is_recorded_for_the_evidence_panel(self):
        members = [member(1, {"bore_mm": 25}), member(2, {"bore_mm": 30})]
        fused, _ = fuse_attribute("bore_mm", members)
        assert {c["value"] for c in fused.candidates} == {"25", "30"}
        assert {c["member_id"] for c in fused.candidates} == {1, 2}


class TestConflictBlocksApproval:
    """§2D rule 4 — the acceptance criterion."""

    def test_an_identity_critical_disagreement_blocks_auto_approval(self):
        members = [
            member(1, {"bore_mm": 25, "seal_type": "ZZ"}, {"bore_mm": "text"}),
            member(2, {"bore_mm": 30, "seal_type": "ZZ"}, {"bore_mm": "text"}),
        ]
        result = standardize(members, BEARING)
        assert result.status == "conflict"
        assert not result.auto_approvable
        assert any(c["attr"] == "bore_mm" and c["blocking"] for c in result.conflicts)

    def test_a_cosmetic_disagreement_does_not_block(self):
        members = [
            member(1, {"bore_mm": 25, "brand": "SKF"}, {"brand": "text"}),
            member(2, {"bore_mm": 25, "brand": "FAG"}, {"brand": "text"}),
        ]
        result = standardize(members, BEARING)
        assert result.status == "draft" and result.auto_approvable

    def test_a_clean_cluster_is_approvable(self):
        members = [member(1, dict(FULL)), member(2, dict(FULL))]
        assert standardize(members, BEARING).auto_approvable


class TestProvenance:
    def test_every_fused_field_records_its_member_and_rule(self):
        result = standardize([member(1, dict(FULL)), member(2, dict(FULL))], BEARING)
        assert result.provenance
        for fused in result.provenance:
            assert fused.field in BEARING.attributes
            assert fused.source_member_id in (1, 2)
            assert fused.rule


class TestDelta:
    def test_the_delta_reports_what_standardization_changed(self):
        legacy = member(1, {}, text="VLV GATE 150NB CL 150 CAST IRON THRD FLOWSERVE")
        delta = standardization_delta(legacy, "VALVE, GATE, 150NB, CLASS 150, CI, THREADED")
        assert "CI" in delta["tokens_added"]
        assert "CAST" in delta["tokens_dropped"]
        assert delta["unchanged"] is False

    def test_separators_are_not_reported_as_changes(self):
        """The template adds commas; that is not a content change."""
        legacy = member(1, {}, text="VALVE GATE 150NB")
        delta = standardization_delta(legacy, "VALVE, GATE, 150NB")
        assert delta["tokens_added"] == [] and delta["tokens_dropped"] == []


class TestDeterminism:
    """§2D: the same cluster must always yield byte-identical text."""

    def test_repeated_standardization_is_byte_identical(self):
        members = [member(1, dict(FULL)), member(2, dict(FULL))]
        first = standardize(members, BEARING, "6205-2Z").std_description
        for _ in range(5):
            assert standardize(members, BEARING, "6205-2Z").std_description == first

    def test_member_order_does_not_change_the_description(self):
        members = [member(1, dict(FULL)), member(2, {**FULL, "load_rating_kg": 500})]
        assert (
            standardize(members, BEARING, "6205-2Z").std_description
            == standardize(list(reversed(members)), BEARING, "6205-2Z").std_description
        )

    def test_int_and_float_spellings_of_one_value_agree(self):
        a = standardize([member(1, {**FULL, "bore_mm": 25})], BEARING).std_description
        b = standardize([member(1, {**FULL, "bore_mm": 25.0})], BEARING).std_description
        assert a == b


class TestValveTemplate:
    def test_a_second_class_renders_from_its_own_grammar(self):
        attrs = {
            "size_nb_mm": 150, "pressure_class": "150", "body_material": "CI",
            "end_connection": "THREADED", "pressure_bar": 19.6, "temp_max_c": 200,
        }
        text = render_description(attrs, VALVE, mpn="FLO-GV01634")
        assert text == "VALVE, GATE, 150NB, CLASS 150, CI, THREADED, FLO-GV01634"
