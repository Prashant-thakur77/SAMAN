"""Text, unit and pack-size normalization — spec §2 (M2) and §2A.1.

Order matters. The pipeline is:

    NFKC  ->  Hindi domain terms  ->  Devanagari transliteration  ->  uppercase
      ->  pack-size extraction  ->  separator flattening  ->  abbreviation
      expansion  ->  whitespace collapse

Hindi domain terms are substituted *before* transliteration so that common
domain words land on the exact English term ("बेयरिंग 6205" -> "BEARING 6205")
rather than on a phonetic approximation. Everything else is transliterated
character by character, which is what makes the TF-IDF fallback path work at
all — spec §2A.1 is explicit that we must not rely on a multilingual model.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from .data.abbreviations import ABBREVIATIONS, HINDI_TERMS

# --------------------------------------------------------------------------
# Devanagari transliteration
# --------------------------------------------------------------------------

_DEV_CONSONANTS = {
    "क": "K", "ख": "KH", "ग": "G", "घ": "GH", "ङ": "NG",
    "च": "CH", "छ": "CHH", "ज": "J", "झ": "JH", "ञ": "NY",
    "ट": "T", "ठ": "TH", "ड": "D", "ढ": "DH", "ण": "N",
    "त": "T", "थ": "TH", "द": "D", "ध": "DH", "न": "N",
    "प": "P", "फ": "PH", "ब": "B", "भ": "BH", "म": "M",
    "य": "Y", "र": "R", "ल": "L", "ळ": "L", "व": "V",
    "श": "SH", "ष": "SH", "स": "S", "ह": "H",
    "क़": "Q", "ख़": "KH", "ग़": "G", "ज़": "Z", "ड़": "R", "ढ़": "RH", "फ़": "F",
}
_DEV_VOWELS = {
    "अ": "A", "आ": "AA", "इ": "I", "ई": "EE", "उ": "U", "ऊ": "OO",
    "ऋ": "RI", "ए": "E", "ऐ": "AI", "ओ": "O", "औ": "AU",
}
_DEV_MATRAS = {
    "ा": "AA", "ि": "I", "ी": "EE", "ु": "U", "ू": "OO",
    "ृ": "RI", "े": "E", "ै": "AI", "ो": "O", "ौ": "AU",
}
_DEV_SIGNS = {"ं": "N", "ः": "H", "ँ": "N"}
_DEV_DIGITS = {d: str(i) for i, d in enumerate("०१२३४५६७८९")}
_HALANT = "्"
_NUKTA = "़"

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text))


def transliterate_devanagari(text: str) -> str:
    """Character-level Devanagari -> Latin.

    A consonant carries an inherent 'A' unless a matra or a halant follows it,
    which is the rule that makes the output readable rather than a consonant
    soup ("बेयरिंग" -> "BEYARINGA", not "BYRNG").
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        # A nukta may follow its base letter as a separate combining char.
        if i + 1 < n and text[i + 1] == _NUKTA and (ch + _NUKTA) in _DEV_CONSONANTS:
            ch = ch + _NUKTA
            i += 1
        if ch == _NUKTA:
            i += 1
            continue

        if ch in _DEV_CONSONANTS:
            out.append(_DEV_CONSONANTS[ch])
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt == _HALANT:  # conjunct: suppress the inherent vowel
                i += 2
                continue
            if nxt in _DEV_MATRAS:
                out.append(_DEV_MATRAS[nxt])
                i += 2
                continue
            out.append("A")  # inherent vowel
            i += 1
            continue

        if ch in _DEV_VOWELS:
            out.append(_DEV_VOWELS[ch])
        elif ch in _DEV_SIGNS:
            out.append(_DEV_SIGNS[ch])
        elif ch in _DEV_DIGITS:
            out.append(_DEV_DIGITS[ch])
        elif ch in _DEV_MATRAS or ch == _HALANT:
            pass  # orphaned sign with no base consonant
        else:
            out.append(ch)
        i += 1

    return "".join(out)


# Longest first, so "बेयरिंग" is matched before any shorter substring of it.
_HINDI_SORTED = sorted(HINDI_TERMS.items(), key=lambda kv: -len(kv[0]))


def apply_hindi_terms(text: str) -> str:
    for term, english in _HINDI_SORTED:
        if term in text:
            text = text.replace(term, f" {english} ")
    return text


# --------------------------------------------------------------------------
# Units of measure and pack size
# --------------------------------------------------------------------------

#: Catalogue UoM spellings -> canonical base unit.
UOM_MAP = {
    "NOS": "EA", "NOS.": "EA", "NO": "EA", "NO.": "EA", "NG": "EA",
    "PC": "EA", "PCS": "EA", "PIECE": "EA", "PIECES": "EA",
    "EACH": "EA", "EA": "EA", "U": "EA", "UNIT": "EA", "UNITS": "EA",
    "M": "M", "MTR": "M", "MTRS": "M", "MTS": "M", "METER": "M", "METRE": "M", "RM": "M",
    "KG": "KG", "KGS": "KG", "KILO": "KG", "KILOGRAM": "KG",
    "L": "L", "LTR": "L", "LTRS": "L", "LIT": "L", "LITRE": "L", "LITER": "L",
    "M2": "M2", "SQM": "M2", "M3": "M3", "CUM": "M3",
    "PAIR": "PR", "PRS": "PR", "PR": "PR",
}

#: UoMs that denote a container rather than a base unit. With a known pack
#: quantity these normalize to EA; the pack size is kept separately so the
#: Opportunity engine can compare price per base unit (spec §2A.1).
PACK_UOMS = {
    "BOX", "BOXES", "PKT", "PACKET", "PACK", "CTN", "CARTON", "BAG", "CASE",
    "ROLL", "DRUM", "CAN", "BOTTLE", "TIN", "COIL", "BUNDLE", "SET",
}

_PACK_PATTERNS = [
    # "BOX OF 100", "PKT-50", "PACK: 25", "SET OF 4"
    re.compile(
        r"\b(?:BOX|BOXES|PKT|PACKET|PACK|CTN|CARTON|BAG|CASE|SET|ROLL|DRUM|CAN|BOTTLE|TIN|COIL|BUNDLE)"
        r"\s*(?:OF|-|:)?\s*(\d{1,6})\b"
    ),
    # "100 NOS/BOX", "50 PCS PER PACKET"
    re.compile(
        r"\b(\d{1,6})\s*(?:NOS|NO|PCS|PC|EA|EACH)?\s*(?:/|PER)\s*"
        r"(?:BOX|PKT|PACKET|PACK|CTN|CARTON|BAG|CASE|SET|ROLL|DRUM|CAN|BOTTLE|TIN|COIL|BUNDLE)\b"
    ),
]


def extract_pack_qty(text: str) -> tuple[float | None, str]:
    """Pull a pack quantity out of the description, returning (qty, text-without-phrase)."""
    for pattern in _PACK_PATTERNS:
        if m := pattern.search(text):
            try:
                qty = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if qty > 0:
                return qty, (text[: m.start()] + " " + text[m.end() :])
    return None, text


def canonical_uom(raw_uom: str | None, pack_qty: float | None) -> tuple[str | None, float]:
    """Resolve a catalogue UoM to (base_uom, pack_qty).

    A container UoM with a known pack size becomes EA at that pack size, which
    is what makes "BEARING 6205, BOX OF 100" (UoM BOX) comparable with
    "BEARING 6205" (UoM EA).
    """
    qty = pack_qty if pack_qty and pack_qty > 0 else 1.0
    if not raw_uom:
        return None, qty

    token = raw_uom.strip().upper()
    if token in UOM_MAP:
        return UOM_MAP[token], qty
    if token in PACK_UOMS:
        # Container unit: base is EA when we know the pack size, otherwise we
        # keep the container unit rather than guessing a quantity.
        return ("EA", qty) if pack_qty else (token, 1.0)
    return token or None, qty


# --------------------------------------------------------------------------
# Text normalization
# --------------------------------------------------------------------------

_SEPARATORS = re.compile(r"[,;:|()\[\]{}\"'`~]+")
_DANGLING_DASH = re.compile(r"(?<=\s)-+(?=\s)|(?<=\s)-+$|^-+(?=\s)")
_MULTISPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def expand_abbreviations(text: str) -> str:
    """Expand known abbreviations on whole tokens only.

    Token-wise is the point: a substring rule would turn "SS316" into
    "STAINLESS STEEL316".
    """
    out: list[str] = []
    for token in text.split():
        key = token
        # "NOS." -> "NOS", but never strip the dot from "1.5"
        if key.endswith(".") and not key[:-1].replace(".", "").isdigit():
            key = key.rstrip(".")
        out.append(ABBREVIATIONS.get(key, token))
    return " ".join(out)


def normalize_text(text: str) -> str:
    """Full normalization pipeline for a catalogue description."""
    if not text:
        return ""

    s = unicodedata.normalize("NFKC", text)
    s = apply_hindi_terms(s)
    if has_devanagari(s):
        s = transliterate_devanagari(s)
    s = s.upper()
    s = _SEPARATORS.sub(" ", s)
    s = _DANGLING_DASH.sub(" ", s)
    s = _MULTISPACE.sub(" ", s).strip()
    s = expand_abbreviations(s)
    return _MULTISPACE.sub(" ", s).strip()


def normalize_mpn(mpn: str | None) -> str | None:
    """Tier-0 anchor key: uppercase, alphanumerics only ("6205-2Z" -> "62052Z")."""
    if not mpn:
        return None
    cleaned = _NON_ALNUM.sub("", str(mpn).upper())
    # Too short to be a discriminating anchor; treat as absent rather than as a
    # key that would over-merge (a 2-character "MPN" matches thousands of rows).
    return cleaned if len(cleaned) >= 4 else None


def gtin_check_digit(digits: str) -> int:
    """GS1 mod-10: weights alternate 3 and 1 from the right of the payload."""
    total = 0
    for position, ch in enumerate(reversed(digits)):
        total += int(ch) * (3 if position % 2 == 0 else 1)
    return (10 - total % 10) % 10


def normalize_gtin(gtin: str | None) -> str | None:
    """GTIN-8/12/13/14, check digit verified.

    Validated rather than merely length-checked, for the same reason MPN
    extraction is precision-first: a wrong GTIN becomes a Tier-0 anchor key and
    merges unrelated items outright.
    """
    if not gtin:
        return None
    digits = re.sub(r"\D", "", str(gtin))
    if len(digits) not in (8, 12, 13, 14):
        return None
    return digits if gtin_check_digit(digits[:-1]) == int(digits[-1]) else None


def text_hash(norm_text: str) -> str:
    """Tier-0 exact-text key."""
    return hashlib.sha256(norm_text.encode("utf-8")).hexdigest()


def detect_lang(text: str) -> str:
    return "hi" if has_devanagari(text) else "en"


@dataclass(frozen=True)
class NormalizedRow:
    norm_text: str
    norm_hash: str
    lang: str
    uom_base: str | None
    pack_qty: float


def normalize_row(description: str, uom: str | None = None) -> NormalizedRow:
    """Normalize one catalogue row end to end."""
    lang = detect_lang(description or "")

    s = unicodedata.normalize("NFKC", description or "")
    s = apply_hindi_terms(s)
    if has_devanagari(s):
        s = transliterate_devanagari(s)
    s = s.upper()

    # Pack size is removed from the text before hashing so that the same item
    # at two pack bases produces the same Tier-0 key.
    pack_qty, s = extract_pack_qty(s)
    uom_base, pack_qty_resolved = canonical_uom(uom, pack_qty)

    s = _SEPARATORS.sub(" ", s)
    s = _DANGLING_DASH.sub(" ", s)
    s = _MULTISPACE.sub(" ", s).strip()
    s = expand_abbreviations(s)
    norm = _MULTISPACE.sub(" ", s).strip()

    return NormalizedRow(
        norm_text=norm,
        norm_hash=text_hash(norm),
        lang=lang,
        uom_base=uom_base,
        pack_qty=pack_qty_resolved,
    )
