"""Directed functional equivalence — spec §2B.

The distinction this file protects: a duplicate is symmetric and gets merged;
an equivalent is directed and keeps its own CNMC. Collapsing the two is the
failure §2B exists to prevent.
"""

import pytest

from app import equivalence
from app.equivalence import (
    BASIS_CONFIDENCE,
    Candidate,
    Condition,
    build_crossref_index,
    by_crossref,
    by_designation,
    by_rule,
    evaluate,
    evaluate_condition,
    parse_rules,
)
from app.taxonomy import get_schema

BEARING = get_schema("bearing.ball.deep_groove")
VALVE = get_schema("valve.gate")
FASTENER = get_schema("fastener.bolt.hex")

BEARING_RULES = parse_rules(
    """
- class: bearing.ball.deep_groove
  equivalent_if: [bore_mm ==, outer_dia_mm ==, width_mm ==, seal_type ==]
  substitutable_if: [load_rating_kg >=, temp_max_c >=]
  never_if: [material !=]
"""
)
VALVE_RULES = parse_rules(
    """
- class: valve.gate
  equivalent_if: [size_nb_mm ==, body_material ==, end_connection ==]
  substitutable_if: [pressure_bar >=, temp_max_c >=]
  never_if: [body_material !=, end_connection !=]
"""
)

BASE = {
    "bore_mm": 25, "outer_dia_mm": 52, "width_mm": 15,
    "seal_type": "ZZ", "load_rating_kg": 500, "temp_max_c": 120,
}


def bearing(item_id, text="BEARING BALL 6205 ZZ", mpn=None, **overrides):
    return Candidate(item_id, "bearing.ball.deep_groove", text, mpn, {**BASE, **overrides})


def valve(item_id, text="VALVE GATE 50NB CLASS 300 SS316 FLANGED", **overrides):
    attrs = {
        "size_nb_mm": 50, "pressure_class": "300", "body_material": "SS316",
        "end_connection": "FLANGED", "pressure_bar": 51.1, "temp_max_c": 250,
    }
    return Candidate(item_id, "valve.gate", text, None, {**attrs, **overrides})


class TestRuleDsl:
    """§2B: rules are data, edited by stewards — not code."""

    def test_a_rule_parses_into_its_three_clauses(self):
        rule = BEARING_RULES[0]
        assert rule.class_code == "bearing.ball.deep_groove"
        assert Condition("bore_mm", "==") in rule.equivalent_if
        assert Condition("load_rating_kg", ">=") in rule.substitutable_if
        assert Condition("material", "!=") in rule.never_if

    @pytest.mark.parametrize("text", ["", "%%% not yaml", "just a string", "[]"])
    def test_unparseable_input_yields_no_rules_rather_than_raising(self, text):
        """A steward's typo must not take the pipeline down."""
        assert parse_rules(text) == []

    def test_a_malformed_condition_is_skipped_not_fatal(self):
        rules = parse_rules(
            "- class: x\n  equivalent_if: [bore_mm ==, nonsense, width_mm ==]"
        )
        assert [str(c) for c in rules[0].equivalent_if] == ["bore_mm ==", "width_mm =="]

    def test_a_single_mapping_is_accepted_as_well_as_a_list(self):
        assert parse_rules("class: x\nequivalent_if: [a ==]")[0].class_code == "x"


class TestConditions:
    @pytest.mark.parametrize(
        ("op", "a", "b", "expected"),
        [
            ("==", 25, 25.0, True), ("==", 25, 30, False),
            ("!=", 25, 30, True), ("!=", "ZZ", "zz", False),
            (">=", 200, 500, True), (">=", 500, 200, False),
            ("<=", 500, 200, True),
        ],
    )
    def test_operators(self, op, a, b, expected):
        assert evaluate_condition(Condition("x", op), {"x": a}, {"x": b}) is expected

    def test_a_missing_value_is_undecidable_not_false(self):
        """Undecidable and false are different: one is ignorance."""
        assert evaluate_condition(Condition("x", "=="), {}, {"x": 1}) is None

    def test_a_non_numeric_comparison_is_undecidable(self):
        assert evaluate_condition(Condition("x", ">="), {"x": "ZZ"}, {"x": "2RS"}) is None


class TestCrossref:
    def test_a_published_interchange_is_the_strongest_basis(self):
        index = build_crossref_index([("6205-2Z", "6205-2ZR")])
        verdict = by_crossref(bearing(1, mpn="62052Z"), bearing(2, mpn="62052ZR"), index)
        assert verdict.basis == "crossref"
        assert verdict.confidence == BASIS_CONFIDENCE["crossref"]

    def test_the_index_is_symmetric(self):
        index = build_crossref_index([("6205-2Z", "6205-2ZR")])
        assert "62052ZR" in index["62052Z"] and "62052Z" in index["62052ZR"]

    def test_unlisted_part_numbers_produce_nothing(self):
        assert by_crossref(bearing(1, mpn="AAAA1"), bearing(2, mpn="BBBB2"), {}) is None


class TestDesignation:
    def test_two_designations_that_agree_are_the_same_specification(self):
        verdict = by_designation(
            bearing(1, "BEARING BALL 6205 ZZ SKF"),
            bearing(2, "BRG BALL 6205 ZZ NSK"),
            BEARING,
        )
        assert verdict.basis == "designation"

    def test_different_designations_produce_nothing(self):
        assert (
            by_designation(
                bearing(1, "BEARING BALL 6205 ZZ"),
                bearing(2, "BEARING BALL 6305 ZZ", bore_mm=25, outer_dia_mm=62, width_mm=17),
                BEARING,
            )
            is None
        )

    def test_a_designation_is_not_evidence_about_what_it_does_not_encode(self):
        """A metric thread says nothing about a bolt's grade or material."""
        a = Candidate(1, "fastener.bolt.hex", "HEX BOLT M10X1.5 30MM LG GRADE 4.6 SS304",
                      None, {"thread": "M10X1.5", "length_mm": 30, "grade": "4.6", "material": "SS304"})
        b = Candidate(2, "fastener.bolt.hex", "HEX BOLT M10X1.5 30MM LG GRADE 12.9 SS304",
                      None, {"thread": "M10X1.5", "length_mm": 30, "grade": "12.9", "material": "SS304"})
        assert by_designation(a, b, FASTENER) is None
        assert evaluate(a, b, FASTENER, [], {}) is None


class TestSubstitutionRules:
    def test_a_higher_rated_item_substitutes_a_lower_rated_one(self):
        verdict = by_rule(
            bearing(1, load_rating_kg=200), bearing(2, load_rating_kg=500), BEARING_RULES
        )
        assert verdict.rel_type == "supersedes" and verdict.direction == "a_to_b"

    def test_the_reverse_substitution_is_never_implied(self):
        """A 500 bar valve replaces a 300 bar requirement; not the reverse."""
        verdict = by_rule(
            bearing(1, load_rating_kg=500), bearing(2, load_rating_kg=200), BEARING_RULES
        )
        assert verdict.direction == "b_to_a"

    def test_equal_ratings_are_interchangeable_both_ways(self):
        verdict = by_rule(bearing(1), bearing(2), BEARING_RULES)
        assert verdict.rel_type == "equivalent" and verdict.direction == "bidirectional"

    def test_never_if_ends_it(self):
        a = bearing(1, material="SS316")
        b = bearing(2, load_rating_kg=900, material="CS")
        assert by_rule(a, b, BEARING_RULES) is None

    def test_a_different_identity_attribute_prevents_the_base_clause(self):
        assert by_rule(bearing(1), bearing(2, bore_mm=30), BEARING_RULES) is None

    def test_a_rule_for_another_class_is_not_applied(self):
        assert by_rule(valve(1), valve(2), BEARING_RULES) is None


class TestDirectionIsSettledByRatings:
    """Whatever source fires, the ratings decide which way substitution runs."""

    def test_a_shared_designation_with_unequal_ratings_is_directed(self):
        """The bug this guards: designation agreement is not interchangeability."""
        verdict = evaluate(
            bearing(1, load_rating_kg=200), bearing(2, load_rating_kg=500),
            BEARING, BEARING_RULES, {},
        )
        assert verdict.rel_type == "supersedes" and verdict.direction == "a_to_b"

    def test_a_shared_designation_with_equal_ratings_stays_symmetric(self):
        verdict = evaluate(bearing(1, mpn="A1"), bearing(2, mpn="A1"), BEARING, BEARING_RULES, {})
        assert verdict.direction == "bidirectional"

    def test_a_valve_class_upgrade_is_a_directed_substitution(self):
        verdict = evaluate(
            valve(1),
            valve(2, pressure_class="600", pressure_bar=102.1),
            VALVE, VALVE_RULES, {},
        )
        assert verdict.rel_type == "supersedes" and verdict.direction == "a_to_b"

    def test_an_identity_mismatch_is_not_an_equivalence(self):
        assert evaluate(bearing(1), bearing(2, bore_mm=30), BEARING, BEARING_RULES, {}) is None

    def test_different_classes_never_relate(self):
        assert evaluate(bearing(1), valve(2), BEARING, BEARING_RULES, {}) is None


class TestRowNormalisation:
    def test_direction_flips_when_the_pair_is_stored_the_other_way_round(self):
        verdict = evaluate(
            bearing(9, load_rating_kg=200), bearing(2, load_rating_kg=500),
            BEARING, BEARING_RULES, {},
        )
        row = verdict.as_row(9, 2)
        assert (row["item_a"], row["item_b"]) == (2, 9)
        # 9 was superseded by 2, so stored the other way round it reads b_to_a.
        assert row["direction"] == "b_to_a"

    def test_a_symmetric_relation_is_unaffected_by_ordering(self):
        verdict = evaluate(bearing(9, mpn="A1"), bearing(2, mpn="A1"), BEARING, BEARING_RULES, {})
        assert verdict.as_row(9, 2)["direction"] == "bidirectional"


class TestRatingBasis:
    """§2B source 3, derived from the class schema rather than a written rule.

    When two items agree on every identity-critical attribute they state and
    differ only on a performance attribute the schema marks `higher_ok`, the
    higher-rated one substitutes the lower. `classes.yaml` said so when it
    declared the direction; nobody had to write a rule.
    """

    def _compare(self, a: dict, b: dict, class_code="chemical.reagent"):
        from app.compare import compare_attrs
        from app.taxonomy import get_schema

        schema = get_schema(class_code)
        return compare_attrs(a, b, schema), schema

    def test_a_higher_concentration_supersedes_a_lower_one(self):
        comparison, schema = self._compare(
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 50.0},
        )
        verdict = equivalence.by_rating(comparison, schema)
        assert verdict is not None
        assert verdict.rel_type == "supersedes"
        assert verdict.direction == "a_to_b", "B is the stronger one"
        assert verdict.basis == "rating"

    def test_the_direction_is_never_implied_backwards(self):
        """The unsafe direction is the whole reason §2B stores one."""
        comparison, schema = self._compare(
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 50.0},
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
        )
        assert equivalence.by_rating(comparison, schema).direction == "b_to_a"

    def test_an_identity_difference_produces_nothing(self):
        comparison, schema = self._compare(
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
            {"substance": "TOLUENE", "grade": "TECH", "concentration_pct": 50.0},
        )
        assert equivalence.by_rating(comparison, schema) is None

    def test_an_unreadable_identity_attribute_produces_nothing(self):
        """A substitution is a safety claim. "We could not read the grade" is
        not a basis for telling a buyer the parts interchange."""
        comparison, schema = self._compare(
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
            {"substance": "XYLENE", "concentration_pct": 50.0},
        )
        assert equivalence.by_rating(comparison, schema) is None

    def test_agreement_alone_is_not_a_substitution(self):
        """Identical ratings are a duplicate question, not a substitution one."""
        comparison, schema = self._compare(
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
        )
        assert equivalence.by_rating(comparison, schema) is None

    def test_a_difference_inside_the_tolerance_band_is_not_a_substitution(self):
        comparison, schema = self._compare(
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.2},
        )
        assert equivalence.by_rating(comparison, schema) is None

    def test_it_is_the_last_source_consulted(self):
        """A crossref, a designation or a steward's rule all outrank a
        direction inferred from the schema."""
        assert equivalence.BASIS_PRIORITY.index("rating") > equivalence.BASIS_PRIORITY.index(
            "rule"
        )
        assert (
            equivalence.BASIS_CONFIDENCE["rating"] < equivalence.BASIS_CONFIDENCE["rule"]
        )

    def test_the_evidence_names_what_agreed_and_what_differed(self):
        comparison, schema = self._compare(
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 50.0},
        )
        evidence = equivalence.by_rating(comparison, schema).evidence
        assert "substance" in evidence["agreed_on"]
        assert evidence["rating_difference"]
        assert "schema" in evidence["source"]
