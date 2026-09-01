"""Numeric parsing for messy catalogue text — spec §2A.1.

The edge cases the spec names, each with a test:
  fractions           "1/2 inch", "1-1/2", "1 1/2"
  ranges              "-20 to 120 C", "-20..120", "-20~120"
  tolerances          "25±0.05", "25 +/- 0.05"
  thousand separators "1,200"
  fit classes         "H7", "h6"  (a tolerance grade, not a value)

Everything returns a ParsedNumber so the comparator can reason about a band
rather than pretending a range is a point value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .units import convert

# 1,200.50 | .5 | 25 | -20
_NUM = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[-+]?\.\d+"

# _NUM is a top-level alternation, so it MUST be wrapped before being
# interpolated into a larger pattern — otherwise the `|` escapes its intended
# scope and the pattern degenerates into "match a bare number".
_N = f"(?:{_NUM})"

_FIT_CLASS = re.compile(r"^[A-Za-z]{1,2}\d{1,2}$")  # H7, h6, JS9
_MIXED_FRACTION = re.compile(rf"^({_NUM})[\s-](\d+)\s*/\s*(\d+)$")
_FRACTION = re.compile(r"^(\d+)\s*/\s*(\d+)$")
_TOLERANCE = re.compile(rf"^({_NUM})\s*(?:±|\+/-|\+\-)\s*({_NUM})$")
_RANGE = re.compile(rf"^({_NUM})\s*(?:to|\.\.|~|—|–)\s*({_NUM})$", re.IGNORECASE)
_PLAIN = re.compile(rf"^({_NUM})$")


@dataclass(frozen=True)
class ParsedNumber:
    """A number that may be a point, a band, or a range."""

    value: float  # representative value (midpoint of a range)
    low: float
    high: float
    is_range: bool = False
    tolerance: float | None = None
    fit_class: str | None = None
    raw: str = ""

    def to_unit(self, from_unit: str | None, to_unit: str | None) -> "ParsedNumber":
        """Convert every bound. Raises units.UnitError if the units are incompatible."""
        if from_unit == to_unit or to_unit is None or from_unit is None:
            return self
        return ParsedNumber(
            value=convert(self.value, from_unit, to_unit),
            low=convert(self.low, from_unit, to_unit),
            high=convert(self.high, from_unit, to_unit),
            is_range=self.is_range,
            tolerance=(
                # A tolerance is a width, not a point, so convert it as a delta.
                abs(convert(self.tolerance, from_unit, to_unit) - convert(0, from_unit, to_unit))
                if self.tolerance is not None
                else None
            ),
            fit_class=self.fit_class,
            raw=self.raw,
        )

    def overlaps(self, other: "ParsedNumber") -> bool:
        return self.low <= other.high and other.low <= self.high


def _to_float(token: str) -> float:
    return float(token.replace(",", ""))


def parse_number(text: str | float | int | None) -> ParsedNumber | None:
    """Parse one numeric expression. Returns None when there is no number in it."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        v = float(text)
        return ParsedNumber(value=v, low=v, high=v, raw=str(text))

    s = str(text).strip()
    if not s:
        return None

    # A fit class ("H7") carries a tolerance grade but no magnitude.
    if _FIT_CLASS.match(s) and not _PLAIN.match(s):
        return ParsedNumber(value=0.0, low=0.0, high=0.0, fit_class=s.upper(), raw=s)

    if m := _TOLERANCE.match(s):
        v, tol = _to_float(m.group(1)), abs(_to_float(m.group(2)))
        return ParsedNumber(value=v, low=v - tol, high=v + tol, tolerance=tol, raw=s)

    if m := _RANGE.match(s):
        a, b = _to_float(m.group(1)), _to_float(m.group(2))
        lo, hi = min(a, b), max(a, b)
        return ParsedNumber(value=(lo + hi) / 2, low=lo, high=hi, is_range=True, raw=s)

    if m := _MIXED_FRACTION.match(s):  # "1-1/2" or "1 1/2"
        whole, num, den = _to_float(m.group(1)), float(m.group(2)), float(m.group(3))
        if den == 0:
            return None
        sign = -1.0 if whole < 0 else 1.0
        v = whole + sign * (num / den)
        return ParsedNumber(value=v, low=v, high=v, raw=s)

    if m := _FRACTION.match(s):
        num, den = float(m.group(1)), float(m.group(2))
        if den == 0:
            return None
        v = num / den
        return ParsedNumber(value=v, low=v, high=v, raw=s)

    if m := _PLAIN.match(s):
        v = _to_float(m.group(1))
        return ParsedNumber(value=v, low=v, high=v, raw=s)

    return None


def find_number(text: str) -> ParsedNumber | None:
    """Pull the first parseable numeric expression out of free text."""
    if not text:
        return None
    # Longest-first so "1-1/2" is not shortened to "1", and "25±0.05" stays whole.
    patterns = [
        rf"{_N}\s*(?:±|\+/-|\+\-)\s*{_N}",
        rf"{_N}\s*(?:to|\.\.|~)\s*{_N}",
        rf"{_N}[\s-]\d+\s*/\s*\d+",
        r"\d+\s*/\s*\d+",
        _NUM,
    ]
    for pat in patterns:
        if m := re.search(pat, text, re.IGNORECASE):
            if parsed := parse_number(m.group(0)):
                return parsed
    return None
