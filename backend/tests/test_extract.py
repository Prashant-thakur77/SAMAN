"""Classification and attribute extraction — spec §2 (M2), §2A.1, §2B."""

import pytest

from app.extract import (
    CLASS_CONFIDENCE_MIN,
    classify,
    extract,
    parse_bearing_designation,
    parse_metric_thread,
)
from app.normalize import normalize_row
from app.taxonomy import UNCLASSIFIED, get_schema, real_classes


def norm(text: str) -> str:
    return normalize_row(text, "NOS").norm_text


CLASS_EXAMPLES = [
    ("BALL BEARING SKF 6205-2Z", "bearing.ball.deep_groove"),
    ("VLV,GT,50NB,CL300,SS316,FLGD,KITZ", "valve.gate"),
    ("GASKET SPIRAL WOUND 80 NB CLASS 150 SS316-GRAPHITE 3MM THK 550 C", "gasket.spiral_wound"),
    ("PIPE SEAMLESS 100NB SCH40 CS-A106B 60.0 BAR JINDAL", "pipe.seamless"),
    ("HEX BOLT M12X1.75 80MM LG GRADE 8.8 SS316 UNBRAKO", "fastener.bolt.hex"),
    ("CABLE POWER 3C X 25 SQMM COPPER XLPE 1100V 90 C POLYCAB", "cable.power"),
    ("CHEMICAL SODIUM HYDROXIDE AR GRADE 50 PCT MERCK", "chemical.reagent"),
    ("HELMET SAFETY CLASS A HDPE RATCHET 4-POINT VENTED PEAK IS2925 KARAM", "ppe.helmet"),
]


@pytest.mark.parametrize(("text", "expected"), CLASS_EXAMPLES)
def test_every_class_is_reachable(text, expected):
    assert classify(norm(text)).class_code == expected


def test_all_eight_classes_are_covered_by_the_examples():
    assert {c for _, c in CLASS_EXAMPLES} == {s.code for s in real_classes()}


class TestClassConfidenceGate:
    """§2A.1: a misclassified item silently loses its veto attributes."""

    def test_unrecognisable_text_is_unclassified(self):
        assert classify(norm("MISCELLANEOUS ITEM XYZ")).class_code == UNCLASSIFIED

    def test_unclassified_carries_no_identity_critical_fields(self):
        assert get_schema(UNCLASSIFIED).identity_critical == []

    def test_confident_classification_clears_the_gate(self):
        guess = classify(norm("BALL BEARING SKF 6205-2Z"))
        assert guess.confidence >= CLASS_CONFIDENCE_MIN and guess.is_confident

    def test_empty_text_does_not_raise(self):
        assert classify("").class_code == UNCLASSIFIED


class TestDesignationParsing:
    """§2B evidence source 1: designations are self-describing."""

    def test_iso_bearing_designation_yields_geometry(self):
        d = parse_bearing_designation("BALL BEARING SKF 6205-2Z")
        assert d.attrs["bore_mm"] == 25
        assert d.attrs["outer_dia_mm"] == 52
        assert d.attrs["width_mm"] == 15
        assert d.attrs["seal_type"] == "ZZ"

    @pytest.mark.parametrize(
        ("text", "seal"), [("6205-2Z", "ZZ"), ("6205ZZ", "ZZ"), ("6205-2RS", "2RS"), ("6205", "OPEN")]
    )
    def test_manufacturer_seal_suffixes_map_onto_one_enum(self, text, seal):
        assert parse_bearing_designation(text).attrs["seal_type"] == seal

    def test_designation_recovers_geometry_absent_from_the_text(self):
        """'बेयरिंग 6205' states no dimensions, yet all three are recoverable."""
        attrs = extract(norm("बेयरिंग 6205")).attrs
        assert attrs["bore_mm"] == 25 and attrs["outer_dia_mm"] == 52

    def test_metric_thread_parsing(self):
        d = parse_metric_thread("HEX BOLT M12X1.75")
        assert d.attrs["thread"] == "M12X1.75"
        assert d.attrs["thread_pitch_mm"] == 1.75

    def test_non_designation_text_returns_none(self):
        assert parse_bearing_designation("GASKET 80NB") is None


class TestMpnPrecision:
    """A false MPN becomes a Tier-0 anchor and merges unrelated items."""

    @pytest.mark.parametrize(
        "text",
        [
            "VLV,GT,50NB,CL300,SS316,FLGD,KITZ",
            "PIPE SEAMLESS 100NB SCH40 CS-A106B JINDAL",
            "HELMET SAFETY CLASS A HDPE RATCHET IS2925 KARAM",
            "GASKET SPIRAL WOUND 80 NB CLASS 150 SS316-GRAPHITE 3MM THK",
        ],
    )
    def test_specification_vocabulary_is_never_taken_as_an_mpn(self, text):
        assert extract(norm(text)).mpn is None

    def test_explicit_marker_is_honoured(self):
        e = extract(norm("VALVE GATE 50NB CLASS 300 SS316 FLANGED KITZ PART NO KTZ-GV50-300"))
        assert e.mpn == "KTZ-GV50-300"

    def test_designation_is_preferred_as_the_anchor(self):
        assert extract(norm("BALL BEARING SKF 6205-2Z")).mpn == "6205-2Z"


class TestGtinAnchor:
    """§0.4 names GTIN as a Tier-0 anchor key alongside MPN."""

    def _gtin(self) -> str:
        from app.normalize import gtin_check_digit

        body = "890123456789"
        return body + str(gtin_check_digit(body))

    def test_a_labelled_gtin_is_extracted(self):
        gtin = self._gtin()
        assert extract(norm(f"BALL BEARING SKF 6205-2Z EAN {gtin}")).gtin == gtin

    def test_a_bare_thirteen_digit_run_is_extracted(self):
        gtin = self._gtin()
        assert extract(norm(f"BALL BEARING SKF 6205-2Z {gtin}")).gtin == gtin

    def test_a_bad_check_digit_is_not_accepted_as_an_anchor(self):
        from app.normalize import gtin_check_digit

        body = "890123456789"
        bad = body + str((gtin_check_digit(body) + 1) % 10)
        assert extract(norm(f"BALL BEARING SKF 6205-2Z EAN {bad}")).gtin is None

    def test_ordinary_descriptions_carry_no_gtin(self):
        assert extract(norm("BALL BEARING SKF 6205-2Z")).gtin is None

    def test_a_part_number_is_not_mistaken_for_a_gtin(self):
        assert extract(norm("VALVE GATE 50NB PART NO KTZ-GV50-300")).gtin is None


class TestAttributeRecovery:
    def test_identity_critical_fields_are_recovered_for_each_class(self):
        for text, class_code in CLASS_EXAMPLES:
            attrs = extract(norm(text)).attrs
            required = {a.name for a in get_schema(class_code).identity_critical}
            missing = required - set(attrs)
            assert not missing, f"{class_code}: missing {sorted(missing)}"

    def test_only_schema_declared_attributes_are_kept(self):
        e = extract(norm("BALL BEARING SKF 6205-2Z"))
        allowed = set(get_schema(e.class_code).attributes) | {"_designation", "_conflicts"}
        assert set(e.attrs) <= allowed

    def test_cable_core_count_is_not_read_as_a_temperature(self):
        attrs = extract(norm("CABLE POWER 3C X 25 SQMM COPPER XLPE 1100V 90 C POLYCAB")).attrs
        assert attrs["cores"] == 3.0 and attrs["temp_max_c"] == 90.0


def test_designation_text_conflict_is_flagged_not_silently_resolved():
    """§2A.1: a parsed designation disagreeing with the text needs review."""
    e = extract(norm("BEARING BALL 6205 30MM BORE ZZ SKF"))
    assert e.conflicts, "a 6205 (25 mm bore) described as 30 mm must raise a conflict"
    conflict = e.conflicts[0]
    assert conflict["attr"] == "bore_mm"
    assert conflict["from_designation"] == 25 and conflict["from_text"] == 30.0
