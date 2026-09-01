"""Normalization — spec §2 (M2) and the §2A.1 traps."""

import pytest

from app.data.abbreviations import ABBREVIATIONS, HINDI_TERMS
from app.normalize import (
    canonical_uom,
    expand_abbreviations,
    extract_pack_qty,
    gtin_check_digit,
    normalize_gtin,
    normalize_mpn,
    normalize_row,
    normalize_text,
    transliterate_devanagari,
)


def test_abbreviation_dictionary_meets_the_required_size():
    """Spec M2: abbreviation dict of at least 120 entries."""
    assert len(ABBREVIATIONS) >= 120


def test_abbreviations_expand_whole_tokens_only():
    """A substring rule would turn SS316 into 'STAINLESS STEEL316'."""
    assert expand_abbreviations("SS316") == "SS316"
    assert expand_abbreviations("SS") == "STAINLESS STEEL"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("BALL BEARING SKF 6205-2Z", "BRG,BALL,6205-2Z,SKF"),
        ("VLV,GT,50NB", "VALVE GATE 50NB"),
        ("S.S. GASKET", "STAINLESS STEEL GASKET"),
    ],
)
def test_style_variants_converge_on_shared_tokens(a, b):
    left, right = set(normalize_text(a).split()), set(normalize_text(b).split())
    assert left & right, f"{a!r} and {b!r} share no normalized tokens"


class TestTransliteration:
    """§2A.1: Hindi must resolve without a multilingual model."""

    def test_domain_term_lands_on_the_english_word(self):
        assert normalize_text("बेयरिंग 6205") == "BEARING 6205"

    def test_hindi_and_english_rows_normalize_identically(self):
        assert normalize_text("बेयरिंग 6205") == normalize_text("BEARING 6205")

    def test_unknown_devanagari_is_transliterated_not_dropped(self):
        out = transliterate_devanagari("बेयरिंग")
        assert out.isascii() and len(out) > 3

    def test_dictionary_covers_the_common_domain_nouns(self):
        for term in ("बेयरिंग", "वाल्व", "गैसकेट", "पाइप", "बोल्ट", "केबल"):
            assert term in HINDI_TERMS


class TestPackSize:
    """§2A.1: the same material at two pack bases must reconcile."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("BEARING 6205, BOX OF 100", 100),
            ("BOLT M12 PKT-50", 50),
            ("WASHER PACK: 25", 25),
            ("GASKET 100 NOS/BOX", 100),
            ("BEARING 6205", None),
        ],
    )
    def test_pack_quantity_is_extracted(self, text, expected):
        qty, _ = extract_pack_qty(text)
        assert qty == expected

    def test_box_and_each_produce_the_same_tier0_key(self):
        boxed = normalize_row("BEARING 6205, BOX OF 100", "BOX")
        singles = normalize_row("BEARING 6205", "EA")
        assert boxed.norm_hash == singles.norm_hash
        assert boxed.pack_qty == 100 and singles.pack_qty == 1
        assert boxed.uom_base == singles.uom_base == "EA"

    @pytest.mark.parametrize(
        ("uom", "expected"), [("NOS", "EA"), ("PC", "EA"), ("MTR", "M"), ("LTR", "L"), ("KGS", "KG")]
    )
    def test_unit_quirks_canonicalize(self, uom, expected):
        assert canonical_uom(uom, None)[0] == expected

    def test_container_unit_without_a_pack_size_is_not_guessed(self):
        """Inventing a pack quantity would corrupt every price-per-unit figure."""
        assert canonical_uom("BOX", None) == ("BOX", 1.0)


class TestAnchorKeys:
    def test_mpn_normalizes_across_punctuation(self):
        assert normalize_mpn("6205-2Z") == normalize_mpn("6205 2z") == "62052Z"

    def test_short_mpn_is_rejected(self):
        """A 2-character 'part number' would anchor thousands of unrelated rows."""
        assert normalize_mpn("AB") is None

    @pytest.mark.parametrize("length", [8, 12, 13, 14])
    def test_every_valid_gtin_length_is_accepted(self, length):
        body = "8901234567890123"[: length - 1]
        gtin = body + str(gtin_check_digit(body))
        assert normalize_gtin(gtin) == gtin

    def test_invalid_gtin_length_is_rejected(self):
        assert normalize_gtin("12345") is None

    def test_a_failed_check_digit_is_rejected(self):
        """A wrong GTIN would become a Tier-0 anchor and merge unrelated items."""
        body = "890123456789"
        good = body + str(gtin_check_digit(body))
        bad = body + str((gtin_check_digit(body) + 1) % 10)
        assert normalize_gtin(good) == good
        assert normalize_gtin(bad) is None

    def test_separators_are_stripped_before_validation(self):
        body = "890123456789"
        gtin = body + str(gtin_check_digit(body))
        assert normalize_gtin(f"{gtin[:3]}-{gtin[3:]}") == gtin


def test_normalization_is_idempotent():
    once = normalize_text("BRG,BALL,6205ZZ,SKF")
    assert normalize_text(once) == once


def test_empty_input_does_not_raise():
    row = normalize_row("", None)
    assert row.norm_text == "" and row.pack_qty == 1.0
