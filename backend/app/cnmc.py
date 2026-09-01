"""Common National Material Code — issuance and check digit (spec §5).

Format: ``CCCC-SSS-NNNNNN-K``

    CCCC    four-letter class family (BRNG, VALV, GSKT, ...)
    SSS     three-digit segment within the family
    NNNNNN  six-digit serial, unique within the family
    K       Damm check digit

Damm is used rather than Luhn because it detects **all** single-digit errors
and all adjacent transpositions — including the 0/9 transposition Luhn misses —
with a single digit and no positional weighting. For a code that will be
keyed by hand into ERP screens across dozens of organisations, that matters.
"""

from __future__ import annotations

import re

#: Totally anti-symmetric quasigroup of order 10 (Damm, 2004).
DAMM_MATRIX: tuple[tuple[int, ...], ...] = (
    (0, 3, 1, 7, 5, 9, 8, 6, 4, 2),
    (7, 0, 9, 2, 1, 5, 4, 8, 6, 3),
    (4, 2, 0, 6, 8, 7, 1, 3, 5, 9),
    (1, 7, 5, 0, 9, 8, 3, 4, 2, 6),
    (6, 1, 2, 3, 0, 4, 5, 9, 7, 8),
    (3, 6, 7, 4, 2, 0, 9, 5, 8, 1),
    (5, 8, 6, 9, 7, 2, 0, 1, 3, 4),
    (8, 9, 4, 5, 3, 6, 2, 0, 1, 7),
    (9, 4, 3, 8, 6, 1, 7, 2, 0, 5),
    (2, 5, 8, 1, 4, 3, 6, 7, 9, 0),
)

CODE_PATTERN = re.compile(r"^([A-Z]{4})-(\d{3})-(\d{6})-(\d)$")

#: Class code -> four-letter family. Stable: a CNMC must never change meaning.
FAMILY_BY_CLASS: dict[str, str] = {
    "bearing.ball.deep_groove": "BRNG",
    "valve.gate": "VALV",
    "gasket.spiral_wound": "GSKT",
    "pipe.seamless": "PIPE",
    "fastener.bolt.hex": "FAST",
    "cable.power": "CABL",
    "chemical.reagent": "CHEM",
    "ppe.helmet": "PPEQ",
    "unclassified": "MISC",
}

#: Segment within a family, so the code carries a little structure.
SEGMENT_BY_CLASS: dict[str, str] = {
    "bearing.ball.deep_groove": "010",
    "valve.gate": "020",
    "gasket.spiral_wound": "030",
    "pipe.seamless": "040",
    "fastener.bolt.hex": "050",
    "cable.power": "060",
    "chemical.reagent": "070",
    "ppe.helmet": "080",
    "unclassified": "999",
}


def _digits(text: str) -> list[int]:
    """Project the code body onto digits so Damm can run over letters too."""
    out: list[int] = []
    for ch in text:
        if ch.isdigit():
            out.append(int(ch))
        elif ch.isalpha():
            out.append((ord(ch.upper()) - 65) % 10)
        # separators carry no information and are skipped
    return out


def damm_check_digit(payload: str) -> int:
    """Compute the Damm check digit for a code body."""
    interim = 0
    for digit in _digits(payload):
        interim = DAMM_MATRIX[interim][digit]
    return interim


def is_valid(code: str) -> bool:
    """True when `code` is well-formed and its check digit verifies."""
    match = CODE_PATTERN.match((code or "").strip().upper())
    if not match:
        return False
    family, segment, serial, check = match.groups()
    return damm_check_digit(f"{family}{segment}{serial}") == int(check)


def format_code(family: str, segment: str, serial: int) -> str:
    """Assemble a code and append its check digit."""
    family = family.upper()
    if not re.fullmatch(r"[A-Z]{4}", family):
        raise ValueError(f"family must be four letters, got {family!r}")
    if not re.fullmatch(r"\d{3}", segment):
        raise ValueError(f"segment must be three digits, got {segment!r}")
    if not 0 <= serial <= 999_999:
        raise ValueError(f"serial out of range: {serial}")
    body = f"{family}{segment}{serial:06d}"
    return f"{family}-{segment}-{serial:06d}-{damm_check_digit(body)}"


def family_for(class_code: str) -> tuple[str, str]:
    return (
        FAMILY_BY_CLASS.get(class_code, "MISC"),
        SEGMENT_BY_CLASS.get(class_code, "999"),
    )


def next_code(class_code: str, existing_serials: set[int]) -> str:
    """Issue the next unused code for a class family."""
    family, segment = family_for(class_code)
    serial = 1
    while serial in existing_serials:
        serial += 1
    if serial > 999_999:
        raise ValueError(f"serial space exhausted for family {family}")
    return format_code(family, segment, serial)


def serial_of(code: str) -> int | None:
    match = CODE_PATTERN.match((code or "").strip().upper())
    return int(match.group(3)) if match else None
