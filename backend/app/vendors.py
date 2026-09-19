"""Vendor names as the catalogues wrote them, read as the companies they are.

"SKF INDIA LTD", "SKF India Limited", "M/s SKF India Pvt. Ltd." and
"SKF INDIA LIMITED." are one supplier. Vendor overlap and combined-volume
figures that match on the exact string undercount every such case, so the
name is reduced to a key before grouping: upper-cased, punctuation and
legal suffixes removed, a few house spellings folded. The raw spelling is
kept for display; the key is only for grouping, never shown as a name.
"""

from __future__ import annotations

import re
from collections import Counter

#: Legal and courtesy forms that do not distinguish one supplier from another.
_DROP = {
    "M/S",
    "MS",
    "MESSRS",
    "LTD",
    "LIMITED",
    "PVT",
    "PRIVATE",
    "CO",
    "COMPANY",
    "CORP",
    "CORPORATION",
    "INC",
    "INCORPORATED",
    "LLP",
    "LLC",
    "PLC",
    "GMBH",
    "AG",
    "SA",
    "THE",
}

#: Spellings that mean the same word inside a name.
_FOLD = {
    "ENGG": "ENGINEERING",
    "ENGRS": "ENGINEERS",
    "ENGR": "ENGINEER",
    "MFG": "MANUFACTURING",
    "INDS": "INDUSTRIES",
    "IND": "INDUSTRIES",
    "INTL": "INTERNATIONAL",
    "TECH": "TECHNOLOGIES",
    "TECHNOLOGY": "TECHNOLOGIES",
    "BROS": "BROTHERS",
    "&": "AND",
}

#: Known groups whose trading names differ more than a suffix. Keyed by the
#: normalised key of each spelling; the value is the group's key. Extended
#: by hand as a CPSE's vendor master is read; never guessed.
VENDOR_ALIASES: dict[str, str] = {
    "SKF BEARINGS INDIA": "SKF INDIA",
    "FAG BEARINGS INDIA": "SCHAEFFLER INDIA",
    "SCHAEFFLER": "SCHAEFFLER INDIA",
}

_PUNCT = re.compile(r"[^\w& ]+")


def vendor_key(name: str | None) -> str:
    """The grouping key for a vendor name; empty for an empty name."""
    if not name:
        return ""
    text = name.upper().replace("&", " & ")
    # "M/s" is a courtesy prefix, not a word; strip it before the slash goes.
    text = re.sub(r"^\s*M/S\.?\s+", " ", text)
    text = _PUNCT.sub(" ", text)
    words = [w for w in text.split() if w]
    words = [_FOLD.get(w, w) for w in words]
    words = [w for w in words if w not in _DROP]
    key = " ".join(words).strip()
    return VENDOR_ALIASES.get(key, key)


def canonical_names(names: list[str]) -> dict[str, str]:
    """For each key, the spelling most often used for it: what the screen
    shows in place of a normalised key."""
    spellings: dict[str, Counter] = {}
    for name in names:
        spellings.setdefault(vendor_key(name), Counter())[name.strip()] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in spellings.items() if key}
