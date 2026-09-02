"""Attribute comparators and the hard-constraint veto layer — spec §2A.

Text similarity cannot tell a 25 mm bore from a 30 mm one, or a 200 kg rating
from a 500 kg one. This module is where that judgement is made, and **no
similarity score anywhere in the pipeline may override it**.

Three attribute roles, from the class schema:

    identity_critical  any mismatch vetoes the pair outright
    performance        compared inside a tolerance band; outside the band it is
                       not a duplicate, but may be a directed substitute (§2B)
    cosmetic           never vetoes; contributes to confidence only

An absent attribute never vetoes. Refusing a pair because we failed to extract
a value would turn every extraction gap into a false negative; the pair falls
through to the similarity tiers instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .numeric import ParsedNumber, parse_number
from .taxonomy import AttrSpec, ClassSchema
from .units import UnitError

#: Two floats within this are the same measurement, not a difference.
EPSILON = 1e-6


def values_equal(a, b) -> bool:
    """Are two attribute values the same, numerically first and textually after?

    The single home for a comparison this codebase has now got wrong three
    times in three different places: a bore read from "65MM BORE" is the float
    65.0, the same bore derived from designation 6313 is the int 65, and
    compared as strings they are not equal. It cost the fit-class comparison in
    M3, Smart-Create's retrieval key in M8, and the identity-signature blocking
    key after that.

    Two things it deliberately does *not* do. It does not parse a unit suffix —
    "25 MM" is compared as text, because unit-aware comparison belongs in
    `compare_attr` where the attribute's declared unit is known. And it never
    compares a fit class by magnitude: `parse_number("H7")` yields a value of
    0.0 with `fit_class="H7"`, so a naive numeric compare makes H7 and H6 equal.
    They are different fits. That bug has been fixed once already in
    `compare_attr`; it does not get to come back through here.
    """
    if a is None or b is None:
        return a is None and b is None

    left, right = parse_number(a), parse_number(b)
    if left is not None and right is not None:
        if left.fit_class or right.fit_class:
            # A fit class is a symbol, not a magnitude.
            return left.fit_class == right.fit_class
        return abs(left.value - right.value) <= EPSILON
    return str(a).strip().upper() == str(b).strip().upper()

MATCH = "match"
MISMATCH = "mismatch"
IN_BAND = "in_band"
OUT_OF_BAND = "out_of_band"
UNKNOWN = "unknown"


@dataclass
class AttrComparison:
    attr: str
    role: str
    value_a: Any
    value_b: Any
    result: str
    detail: str = ""

    @property
    def is_veto(self) -> bool:
        return (self.role == "identity_critical" and self.result == MISMATCH) or (
            self.role == "performance" and self.result == OUT_OF_BAND
        )


@dataclass
class CompareResult:
    """The verdict, plus everything needed to explain it in the UI."""

    verdict: str  # match | tolerance_match | veto
    per_attr: list[AttrComparison] = field(default_factory=list)
    vetoed_by: list[dict] = field(default_factory=list)
    matched_attrs: list[str] = field(default_factory=list)
    compared: int = 0
    #: Out-of-band on a directed performance attribute only — the pair is not a
    #: duplicate but may be a substitute (§2B).
    equivalence_candidate: bool = False
    #: "a_to_b" means B can substitute A (B meets or exceeds A everywhere).
    direction: str | None = None

    @property
    def is_veto(self) -> bool:
        return self.verdict == "veto"

    @property
    def agreement(self) -> float:
        """Share of comparable attributes that agreed. Feeds confidence only."""
        return len(self.matched_attrs) / self.compared if self.compared else 0.0

    def as_evidence(self) -> dict:
        """Persisted into `pair.veto_json` / shown on the evidence card."""
        return {
            "verdict": self.verdict,
            "agreement": round(self.agreement, 4),
            "matched_attrs": self.matched_attrs,
            "vetoed_by": self.vetoed_by,
            "equivalence_candidate": self.equivalence_candidate,
            "direction": self.direction,
            "per_attr": [
                {
                    "attr": c.attr,
                    "role": c.role,
                    "a": c.value_a,
                    "b": c.value_b,
                    "result": c.result,
                    "detail": c.detail,
                }
                for c in self.per_attr
            ],
        }


# --------------------------------------------------------------------------
# Value coercion
# --------------------------------------------------------------------------


def _as_number(value: Any, unit: str | None, target_unit: str | None) -> ParsedNumber | None:
    """Coerce a stored attribute value into a comparable number."""
    parsed = parse_number(value) if not isinstance(value, ParsedNumber) else value
    if parsed is None:
        return None
    if unit and target_unit and unit != target_unit:
        try:
            parsed = parsed.to_unit(unit, target_unit)
        except UnitError:
            return None
    return parsed


def _as_text(value: Any) -> str:
    return str(value).strip().upper()


# --------------------------------------------------------------------------
# Comparators
# --------------------------------------------------------------------------


def _tolerance_for(spec: AttrSpec, a: float, b: float) -> float:
    """Absolute tolerance in the attribute's own unit."""
    if spec.tolerance_pct:
        # Relative to the larger magnitude, so the band is symmetric.
        return abs(spec.tolerance_pct) / 100.0 * max(abs(a), abs(b))
    return abs(spec.tolerance or 0.0)


def compare_numeric(spec: AttrSpec, raw_a: Any, raw_b: Any) -> AttrComparison:
    a = _as_number(raw_a, spec.unit, spec.unit)
    b = _as_number(raw_b, spec.unit, spec.unit)
    if a is None or b is None:
        return AttrComparison(spec.name, spec.role, raw_a, raw_b, UNKNOWN, "not comparable")

    # A tolerance grade ("H7", "JS9") carries no magnitude, so it must be
    # compared as a symbol. Falling through to the numeric path would make
    # every fit class equal to every other one — and equal to the number 0 —
    # which on an identity_critical attribute is a silent failure to veto.
    if a.fit_class or b.fit_class:
        if not (a.fit_class and b.fit_class):
            return AttrComparison(
                spec.name, spec.role, raw_a, raw_b, UNKNOWN,
                "a tolerance grade cannot be compared with a magnitude",
            )
        if a.fit_class == b.fit_class:
            return AttrComparison(spec.name, spec.role, raw_a, raw_b, MATCH, "same fit class")
        result = MISMATCH if spec.vetoes else OUT_OF_BAND
        return AttrComparison(
            spec.name, spec.role, raw_a, raw_b, result,
            f"fit class {a.fit_class} vs {b.fit_class}",
        )

    # A stated range is satisfied by any overlap rather than by equal midpoints.
    if a.is_range or b.is_range:
        if a.overlaps(b):
            return AttrComparison(spec.name, spec.role, raw_a, raw_b, MATCH, "ranges overlap")
        result = MISMATCH if spec.vetoes else OUT_OF_BAND
        return AttrComparison(spec.name, spec.role, raw_a, raw_b, result, "ranges do not overlap")

    difference = abs(a.value - b.value)
    tolerance = _tolerance_for(spec, a.value, b.value)

    # Equal values are an exact match even where a band exists; only a genuine
    # difference that the band absorbs counts as in_band.
    if difference <= EPSILON:
        return AttrComparison(spec.name, spec.role, raw_a, raw_b, MATCH, "exact")
    if difference <= tolerance:
        band = f"{spec.tolerance_pct}%" if spec.tolerance_pct else f"{spec.tolerance}"
        return AttrComparison(
            spec.name, spec.role, raw_a, raw_b, IN_BAND,
            f"{difference:g} apart, inside the {band} band",
        )

    unit = f" {spec.unit}" if spec.unit and spec.unit != "dimensionless" else ""
    if spec.vetoes:
        return AttrComparison(
            spec.name, spec.role, raw_a, raw_b, MISMATCH,
            f"{a.value:g}{unit} vs {b.value:g}{unit}",
        )
    pct = difference / max(abs(a.value), abs(b.value), EPSILON) * 100
    return AttrComparison(
        spec.name, spec.role, raw_a, raw_b, OUT_OF_BAND,
        f"{a.value:g}{unit} vs {b.value:g}{unit} — {pct:.0f}% apart, outside the "
        f"{spec.tolerance_pct}% band",
    )


def compare_enum(spec: AttrSpec, raw_a: Any, raw_b: Any) -> AttrComparison:
    a, b = _as_text(raw_a), _as_text(raw_b)
    if a == b:
        return AttrComparison(spec.name, spec.role, raw_a, raw_b, MATCH, "identical")
    result = MISMATCH if spec.vetoes else OUT_OF_BAND if spec.role == "performance" else MISMATCH
    return AttrComparison(spec.name, spec.role, raw_a, raw_b, result, f"{a} vs {b}")


def compare_attr(spec: AttrSpec, raw_a: Any, raw_b: Any) -> AttrComparison:
    """Compare one attribute. Missing on either side is never a veto."""
    if raw_a is None or raw_b is None:
        return AttrComparison(spec.name, spec.role, raw_a, raw_b, UNKNOWN, "not stated on both")
    if spec.type == "numeric":
        return compare_numeric(spec, raw_a, raw_b)
    return compare_enum(spec, raw_a, raw_b)


# --------------------------------------------------------------------------
# The veto layer
# --------------------------------------------------------------------------


def _substitution_direction(
    schema: ClassSchema, attrs_a: dict, attrs_b: dict
) -> str | None:
    """Which way a substitution could run, if either.

    "a_to_b" means B meets or exceeds A on every directed attribute, so B can
    stand in for A. The reverse is unsafe and is never implied.
    """
    directed = [s for s in schema.performance if s.direction == "higher_ok"]
    if not directed:
        return None

    b_covers_a = a_covers_b = True
    seen = False
    for spec in directed:
        a = _as_number(attrs_a.get(spec.name), spec.unit, spec.unit)
        b = _as_number(attrs_b.get(spec.name), spec.unit, spec.unit)
        if a is None or b is None:
            continue
        seen = True
        if b.value < a.value - EPSILON:
            b_covers_a = False
        if a.value < b.value - EPSILON:
            a_covers_b = False

    if not seen:
        return None
    if b_covers_a and not a_covers_b:
        return "a_to_b"
    if a_covers_b and not b_covers_a:
        return "b_to_a"
    return None


def compare_attrs(attrs_a: dict, attrs_b: dict, schema: ClassSchema) -> CompareResult:
    """The §2A entry point: `{verdict, per_attr, vetoed_by}` for one pair.

    A veto short-circuits nothing in the reporting — every attribute is still
    compared, because the evidence card has to show *why* the pair was refused,
    not merely that it was.
    """
    result = CompareResult(verdict="match")

    for spec in schema.attributes.values():
        comparison = compare_attr(spec, attrs_a.get(spec.name), attrs_b.get(spec.name))
        result.per_attr.append(comparison)

        if comparison.result == UNKNOWN:
            continue
        result.compared += 1

        if comparison.result in (MATCH, IN_BAND):
            result.matched_attrs.append(spec.name)
        if comparison.is_veto:
            result.vetoed_by.append(
                {
                    "attr": spec.name,
                    "role": spec.role,
                    "a": comparison.value_a,
                    "b": comparison.value_b,
                    "reason": comparison.detail,
                }
            )

    if result.vetoed_by:
        result.verdict = "veto"
        # Refused only on a performance band, never on identity: the two items
        # are the same kind of thing at different ratings, which is exactly the
        # shape of a substitution (§2B).
        only_performance = all(v["role"] == "performance" for v in result.vetoed_by)
        if only_performance:
            direction = _substitution_direction(schema, attrs_a, attrs_b)
            if direction:
                result.equivalence_candidate = True
                result.direction = direction
    elif any(c.result == IN_BAND for c in result.per_attr):
        result.verdict = "tolerance_match"

    return result
