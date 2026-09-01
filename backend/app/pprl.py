"""Privacy-preserving record linkage — restricted mode (spec §5, M10).

The problem this solves is political before it is technical. A CPSE may be
willing to learn that another CPSE stocks the same bearing without being
willing to hand over its catalogue to find out. Restricted mode lets two
organisations compute that overlap while exchanging **no plaintext at all**:
each encodes its own descriptions locally, and only the encodings are compared.

The construction is the standard Bloom-filter PPRL scheme (Schnell et al.):

1. Normalize the description with SAMAN's own normalizer, so the two sides
   agree on abbreviation expansion, transliteration and units before anything
   is hashed. This matters more than the cryptography — two catalogues that
   disagree on "SS316" versus "S.S.316" will not match however they are hashed.
2. Cut the record into features.
3. Set *k* bits per feature in an *m*-bit filter, at positions derived by keyed
   HMAC-SHA256. The key is shared between the participating CPSEs and never
   leaves them.
4. Compare two filters with the Dice coefficient over set bits.

**Two feature modes, and why the default is not the obvious one.** The
literature — and the specification — encodes character 3-grams. Measured here,
that tops out at **F1 0.78** whatever the filter size, and the reason is
structural: a 25 mm bore and a 30 mm bore differ in two characters out of
seventy, while the same bearing written in two CPSE house styles differs in
thirty. The n-grams cannot see the distinction that matters and are dominated
by the one that does not.

Encoding the *extracted attributes* instead — `class=bearing.ball.deep_groove`,
`bore_mm=25`, `seal_type=ZZ` — reaches **F1 0.93** on the same data, because a
bore difference is now a whole feature rather than a rounding error. Both sides
run SAMAN's own extractor before hashing, so both derive the same feature
vocabulary without exchanging anything. This is the advantage of doing PPRL
inside the platform that already understands the records, and it is why
`attribute` is the default. `ngram` remains available and measured, so the
comparison is on the table rather than asserted.

**What this does and does not protect.** It removes plaintext from the wire,
which is the requirement. It is not anonymity: Bloom-filter PPRL is known to be
vulnerable to frequency and pattern analysis by a determined adversary who
holds many encodings, and the literature has practical attacks. The keyed hash
raises the cost of a dictionary attack but does not eliminate it. Saying so is
part of the deliverable -- a privacy claim that oversells itself is worse than
none, because someone will rely on it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Cpse, Item, RawItem
from .normalize import normalize_row

#: N-gram size. 3 is what the literature uses and what SAMAN's TF-IDF fallback
#: uses, so the two are looking at the same features.
GRAM = 3

#: Per-mode parameters, each swept against the seeded ground truth. A material
#: description yields ~72 3-grams but only ~8 attribute features, so the two
#: modes need different filters and different thresholds; sharing one set would
#: have handicapped whichever mode did not choose it.
MODES = {
    # 512 bits at 30 hashes fills the filter to ~38%, which is deliberate. A
    # sparse filter is a worse hiding place: with only ~8 features set across
    # 2048 bits there are almost no collisions to shelter behind. Denser costs
    # about 0.01 of F1 and makes the payload a quarter of the size.
    "attribute": {"bits": 512, "hashes": 30, "threshold": 0.88, "report": 0.75},
    "ngram": {"bits": 1024, "hashes": 10, "threshold": 0.90, "report": 0.80},
}
DEFAULT_MODE = "attribute"

#: Kept as module constants because the API and the tests both quote them.
FILTER_BITS = MODES[DEFAULT_MODE]["bits"]
HASHES_PER_GRAM = MODES[DEFAULT_MODE]["hashes"]
MATCH_THRESHOLD = MODES[DEFAULT_MODE]["threshold"]

#: Below this the pair is not reported at all -- a wire full of 0.3 similarities
#: is a frequency-analysis gift and tells the recipient nothing.
REPORT_THRESHOLD = MODES[DEFAULT_MODE]["report"]


def params(mode: str) -> dict:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODES)}")
    return MODES[mode]


@dataclass(frozen=True)
class Encoding:
    """One encoded record. Carries no plaintext and no legacy code."""

    #: Stable pseudonym for the record within this exchange. The owning CPSE can
    #: resolve it; the other side cannot.
    ref: str
    bits: bytes

    def as_dict(self) -> dict:
        return {"ref": self.ref, "bloom": base64.b64encode(self.bits).decode()}

    @classmethod
    def from_dict(cls, payload: dict) -> Encoding:
        return cls(ref=str(payload["ref"]), bits=base64.b64decode(payload["bloom"]))


def new_key() -> str:
    """A fresh exchange key. Both parties must use the same one."""
    return secrets.token_hex(32)


def grams(text: str, n: int = GRAM) -> list[str]:
    """Character n-grams, padded so short strings still produce features."""
    padded = f"  {text.strip()}  " if len(text.strip()) < n else text.strip()
    return [padded[i : i + n] for i in range(max(0, len(padded) - n + 1))]


def attribute_features(class_code: str, attrs: dict, mpn: str | None) -> list[str]:
    """The feature set for `attribute` mode.

    Internal keys (`_sources`, `_conflicts`) are excluded: they describe how the
    value was obtained, not what the item is, and they differ between catalogues
    for reasons that have nothing to do with whether this is the same bearing.
    """
    features = [f"class={class_code}"]
    features += [
        f"{key}={value}"
        for key, value in sorted(attrs.items())
        if not key.startswith("_") and value is not None
    ]
    if mpn:
        features.append(f"mpn={mpn}")
    return features


def encode_features(features: list[str], key: str, mode: str = DEFAULT_MODE) -> bytes:
    """Bloom-encode a feature list under an exchange key."""
    settings = params(mode)
    bits, hashes = settings["bits"], settings["hashes"]
    filter_bytes = bytearray(bits // 8)
    secret = key.encode()
    for feature in features:
        digest = hmac.new(secret, feature.encode("utf-8"), hashlib.sha256).digest()
        # Double hashing: two independent values from one HMAC give k positions
        # without k separate HMAC calls, which is the standard construction.
        h1 = int.from_bytes(digest[:8], "big")
        h2 = int.from_bytes(digest[8:16], "big") | 1  # odd, so it generates
        for i in range(hashes):
            position = (h1 + i * h2) % bits
            filter_bytes[position // 8] |= 1 << (position % 8)
    return bytes(filter_bytes)


def encode_text(text: str, key: str, mode: str = "ngram") -> bytes:
    """Bloom-encode one already-normalized string, character n-gram mode."""
    return encode_features(grams(text), key, mode)


def popcount(bits: bytes) -> int:
    return sum(byte.bit_count() for byte in bits)


def dice(a: bytes, b: bytes) -> float:
    """Dice coefficient over set bits. 1.0 is identical, 0.0 is disjoint."""
    if len(a) != len(b):
        raise ValueError("encodings have different filter lengths")
    total = popcount(a) + popcount(b)
    if total == 0:
        return 0.0
    shared = sum((x & y).bit_count() for x, y in zip(a, b, strict=True))
    return 2 * shared / total


def encode_catalogue(
    db: Session,
    cpse_code: str,
    key: str,
    limit: int | None = None,
    mode: str = DEFAULT_MODE,
) -> dict:
    """Encode one CPSE's catalogue. Returns encodings and nothing else.

    The normalizer and extractor run first deliberately: the encoding is only as
    good as the agreement between the two sides on what the record *is*, and
    SAMAN already knows how to expand `BRG`, transliterate `बेयरिंग`,
    canonicalise units and read a bore out of a designation.
    """
    settings = params(mode)
    cpse = db.execute(select(Cpse).where(Cpse.code == cpse_code)).scalar_one_or_none()
    if cpse is None:
        raise ValueError(f"unknown CPSE {cpse_code!r}")

    query = (
        select(
            RawItem.id,
            RawItem.description,
            RawItem.uom,
            Item.norm_text,
            Item.class_code,
            Item.attrs_json,
            Item.mpn_norm,
        )
        .join(Item, Item.raw_item_id == RawItem.id, isouter=True)
        .where(RawItem.cpse_id == cpse.id)
        .order_by(RawItem.id)
    )
    if limit:
        query = query.limit(limit)

    encodings = []
    for raw_id, description, uom, norm_text, class_code, attrs_json, mpn in db.execute(
        query
    ).all():
        if mode == "attribute" and class_code:
            features = attribute_features(
                class_code, json.loads(attrs_json or "{}"), mpn
            )
        else:
            # No class, or n-gram mode: fall back to the text. A catalogue that
            # has not been through the pipeline still encodes.
            features = grams(norm_text or normalize_row(description or "", uom).norm_text)
        encodings.append(
            Encoding(
                ref=_pseudonym(key, cpse_code, raw_id),
                bits=encode_features(features, key, mode),
            )
        )

    return {
        "cpse": cpse_code,
        "mode": mode,
        "records": len(encodings),
        "filter_bits": settings["bits"],
        "hashes_per_feature": settings["hashes"],
        "gram": GRAM if mode == "ngram" else None,
        "encodings": [e.as_dict() for e in encodings],
        "note": (
            "Bloom-filter encodings under a shared key. No description, legacy "
            "code, attribute value or price is present in this payload."
        ),
    }


def _pseudonym(key: str, cpse_code: str, raw_id: int) -> str:
    """A per-exchange pseudonym. Only the owner can map it back to a row."""
    return hmac.new(
        key.encode(), f"{cpse_code}:{raw_id}".encode(), hashlib.sha256
    ).hexdigest()[:16]


def resolve(key: str, cpse_code: str, raw_id: int) -> str:
    """The pseudonym for one of your own records, so you can find it again."""
    return _pseudonym(key, cpse_code, raw_id)


def compare(
    left: list[dict],
    right: list[dict],
    threshold: float | None = None,
    report_threshold: float | None = None,
    limit: int = 200,
    mode: str = DEFAULT_MODE,
) -> dict:
    """Dice-compare two encoding sets and report the overlap.

    Quadratic by construction: PPRL cannot block on plaintext, because there is
    none. That is a real cost of the privacy guarantee rather than an oversight,
    and it is why restricted mode is offered as a periodic overlap report and
    not as the live matching path.
    """
    settings = params(mode)
    threshold = settings["threshold"] if threshold is None else threshold
    report_threshold = settings["report"] if report_threshold is None else report_threshold

    a = [Encoding.from_dict(e) for e in left]
    b = [Encoding.from_dict(e) for e in right]
    if not a or not b:
        return _empty_report(len(a), len(b), threshold, mode)

    matches: list[dict] = []
    matched_left: set[str] = set()
    matched_right: set[str] = set()

    for one in a:
        for other in b:
            score = dice(one.bits, other.bits)
            if score < report_threshold:
                continue
            matches.append(
                {
                    "left_ref": one.ref,
                    "right_ref": other.ref,
                    "dice": round(score, 4),
                    "verdict": "match" if score >= threshold else "possible",
                }
            )
            if score >= threshold:
                matched_left.add(one.ref)
                matched_right.add(other.ref)

    matches.sort(key=lambda m: m["dice"], reverse=True)
    return {
        "left_records": len(a),
        "right_records": len(b),
        "comparisons": len(a) * len(b),
        "overlap_records_left": len(matched_left),
        "overlap_records_right": len(matched_right),
        "overlap_pct_left": round(100 * len(matched_left) / len(a), 2),
        "overlap_pct_right": round(100 * len(matched_right) / len(b), 2),
        "possible_matches": sum(1 for m in matches if m["verdict"] == "possible"),
        "mode": mode,
        "threshold": threshold,
        "report_threshold": report_threshold,
        "matches": matches[:limit],
        "truncated": len(matches) > limit,
        "note": (
            "Computed entirely from encodings. Neither side learned a "
            "description; each recognises only its own pseudonyms."
        ),
    }


def _empty_report(left: int, right: int, threshold: float, mode: str) -> dict:
    return {
        "left_records": left,
        "right_records": right,
        "comparisons": 0,
        "overlap_records_left": 0,
        "overlap_records_right": 0,
        "overlap_pct_left": 0.0,
        "overlap_pct_right": 0.0,
        "possible_matches": 0,
        "mode": mode,
        "threshold": threshold,
        "report_threshold": params(mode)["report"],
        "matches": [],
        "truncated": False,
        "note": "One side is empty, so there is nothing to compare.",
    }
