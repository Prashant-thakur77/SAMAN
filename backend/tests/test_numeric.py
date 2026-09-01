"""Numeric parsing edge cases — spec §2A.1."""

import pytest

from app.numeric import find_number, parse_number
from app.units import UnitError, convert


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,200", 1200.0),      # thousand separator
        ("1/2", 0.5),           # fraction
        ("1-1/2", 1.5),         # mixed fraction, hyphenated
        ("1 1/2", 1.5),         # mixed fraction, spaced
        ("25.4", 25.4),
        ("-20", -20.0),
    ],
)
def test_scalar_forms(text, value):
    assert parse_number(text).value == value


def test_tolerance_expands_into_a_band():
    p = parse_number("25±0.05")
    assert (p.value, p.low, p.high, p.tolerance) == (25.0, 24.95, 25.05, 0.05)


def test_ascii_tolerance_spelling():
    assert parse_number("25 +/- 0.05").tolerance == 0.05


@pytest.mark.parametrize("text", ["-20 to 120", "-20..120", "-20~120"])
def test_range_forms(text):
    p = parse_number(text)
    assert (p.low, p.high, p.is_range) == (-20.0, 120.0, True)


def test_fit_class_carries_no_magnitude():
    p = parse_number("H7")
    assert p.fit_class == "H7" and p.value == 0.0


@pytest.mark.parametrize("text", ["", "   ", "abc", None])
def test_unparseable_input_returns_none(text):
    assert parse_number(text) is None


def test_zero_denominator_does_not_raise():
    assert parse_number("1/0") is None


class TestFindNumberInFreeText:
    def test_fraction_wins_over_its_leading_digit(self):
        """The parts of a fraction must not be read as a standalone number."""
        assert find_number("BEARING BORE 1/2 INCH").value == 0.5

    def test_range_is_taken_whole(self):
        p = find_number("VALVE -20 to 120 C RATING")
        assert (p.low, p.high) == (-20.0, 120.0)

    def test_tolerance_is_taken_whole(self):
        assert find_number("SHAFT 25±0.05 MM").tolerance == 0.05


class TestUnits:
    @pytest.mark.parametrize(
        ("value", "src", "dst", "expected"),
        [(0.5, "inch", "mm", 12.7), (1, "m", "mm", 1000.0), (1, "kg", "kg", 1.0)],
    )
    def test_factor_conversions(self, value, src, dst, expected):
        assert convert(value, src, dst) == pytest.approx(expected)

    def test_offset_scale_is_not_treated_as_a_factor(self):
        assert convert(212, "degF", "degC") == pytest.approx(100.0)

    def test_pint_handles_units_outside_the_fast_table(self):
        assert convert(1, "yard", "mm") == pytest.approx(914.4)

    def test_incompatible_units_raise_rather_than_return_a_wrong_number(self):
        with pytest.raises(UnitError):
            convert(1, "kg", "mm")

    def test_a_tolerance_converts_as_a_width_not_a_point(self):
        p = parse_number("1±0.5").to_unit("inch", "mm")
        assert p.tolerance == pytest.approx(12.7)
