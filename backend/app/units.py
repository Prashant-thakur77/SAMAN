"""Unit handling for the comparators (spec §2A).

`pint` is the authority, but constructing pint Quantities in a tight loop over
12k items is slow, so the handful of conversions this domain actually needs go
through a factor table first and fall back to pint for anything else.

Temperature is special-cased: degC/degF are offset scales, not factors.
"""

from __future__ import annotations

from functools import lru_cache

# Canonical unit per dimension. Class schemas declare these in classes.yaml.
CANONICAL = {
    "length": "mm",
    "mass": "kg",
    "pressure": "bar",
    "temperature": "degC",
    "voltage": "V",
    "area": "mm**2",
    "volume": "L",
    "percent": "percent",
    "dimensionless": "dimensionless",
}

# Aliases seen in real CPSE catalogues, mapped to pint-parseable unit names.
UNIT_ALIASES = {
    "mm": "mm", "millimetre": "mm", "millimeter": "mm",
    "cm": "cm", "m": "m", "mtr": "m", "mtrs": "m", "metre": "m", "meter": "m",
    "in": "inch", "inch": "inch", "inches": "inch", '"': "inch", "ft": "foot",
    "kg": "kg", "kgs": "kg", "g": "g", "gm": "g", "gram": "g", "lb": "pound", "lbs": "pound",
    "bar": "bar", "barg": "bar", "psi": "psi", "kpa": "kPa", "mpa": "MPa", "kgcm2": "kgf/cm**2",
    "c": "degC", "degc": "degC", "celsius": "degC", "f": "degF", "degf": "degF",
    "v": "V", "volt": "V", "volts": "V", "kv": "kV",
    "sqmm": "mm**2", "mm2": "mm**2", "sqm": "m**2",
    "l": "L", "ltr": "L", "litre": "L", "liter": "L", "ml": "mL",
    "pct": "percent", "%": "percent", "percent": "percent",
}

# value_in_target = value * FACTORS[(source, target)]
FACTORS: dict[tuple[str, str], float] = {
    ("mm", "mm"): 1.0,
    ("cm", "mm"): 10.0,
    ("m", "mm"): 1000.0,
    ("inch", "mm"): 25.4,
    ("foot", "mm"): 304.8,
    ("kg", "kg"): 1.0,
    ("g", "kg"): 0.001,
    ("pound", "kg"): 0.45359237,
    ("bar", "bar"): 1.0,
    ("psi", "bar"): 0.0689475729,
    ("kPa", "bar"): 0.01,
    ("MPa", "bar"): 10.0,
    ("kgf/cm**2", "bar"): 0.980665,
    ("V", "V"): 1.0,
    ("kV", "V"): 1000.0,
    ("mm**2", "mm**2"): 1.0,
    ("m**2", "mm**2"): 1_000_000.0,
    ("L", "L"): 1.0,
    ("mL", "L"): 0.001,
    ("percent", "percent"): 1.0,
    ("dimensionless", "dimensionless"): 1.0,
}


def canonical_unit_name(raw: str | None) -> str | None:
    """Map a catalogue unit string onto a pint-parseable name."""
    if not raw:
        return None
    return UNIT_ALIASES.get(raw.strip().lower().replace(".", ""))


@lru_cache
def _registry():
    """pint is imported lazily — it costs ~0.5s and most calls never need it."""
    from pint import UnitRegistry

    return UnitRegistry()


class UnitError(ValueError):
    """Raised when two values cannot be compared because their units differ."""


def convert(value: float, from_unit: str | None, to_unit: str | None) -> float:
    """Convert `value` from one unit to another, raising UnitError if impossible."""
    if to_unit is None or from_unit is None or from_unit == to_unit:
        return value

    src = canonical_unit_name(from_unit) or from_unit
    dst = canonical_unit_name(to_unit) or to_unit
    if src == dst:
        return value

    if (src, dst) in FACTORS:
        return value * FACTORS[(src, dst)]

    # Offset scales cannot use a factor.
    if {src, dst} <= {"degC", "degF", "kelvin", "K"}:
        if src == "degC" and dst == "degF":
            return value * 9 / 5 + 32
        if src == "degF" and dst == "degC":
            return (value - 32) * 5 / 9
        if src == dst:
            return value

    try:
        ureg = _registry()
        return (value * ureg(src)).to(dst).magnitude
    except Exception as exc:  # pint raises a family of errors; all mean "cannot compare"
        raise UnitError(f"cannot convert {from_unit!r} to {to_unit!r}") from exc
