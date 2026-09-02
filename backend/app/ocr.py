"""Reading a material's own marking (§5, camera input to Smart-Create).

A storekeeper holding an unlabelled part cannot type its description, but the
part usually states it: a bearing has `6205-2Z SKF` stamped on the race, a valve
carries a nameplate with size, class, body material and maker. This module turns
that photograph into text and hands it to Smart-Create, which already knows what
to do with a badly-typed description.

**It reads the marking; it does not recognise the part.** That distinction is
the whole design. A photograph cannot tell a 25 mm bore from a 30 mm one without
a reference scale, cannot see a seal type, and cannot distinguish a Class 300
valve from a Class 600 one — and those are precisely the identity-critical
attributes the §2A veto layer decides on. A classifier trained on shapes would
be confidently wrong about the only things that matter. Reading the
manufacturer's own stamped text is a claim the platform can actually stand
behind.

Nothing downstream is special-cased: the OCR output is just another description,
scored by the same tiers, refused by the same veto layer. Bad OCR produces a bad
query and Smart-Create answers "nothing matched", which is the correct behaviour
and not a new failure mode.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from functools import lru_cache

#: Below this a line is still included in the query -- dropping it could lose
#: the part number, which is the single most valuable token on a nameplate --
#: but it is flagged so a person can see what the reader was unsure of.
LOW_CONFIDENCE = 0.75

#: Refuse anything larger before decoding it. A phone photograph is a few MB; a
#: 200 MB TIFF is either a mistake or an attack, and either way decoding it
#: first to find out is the wrong order.
MAX_IMAGE_BYTES = 12 * 1024 * 1024

#: Longest edge fed to the reader. Phone cameras produce 4000px images; the
#: detector works on a resized copy anyway, and doing it once here keeps a
#: 12 MP photograph from costing seconds.
MAX_EDGE = 1600


@dataclass
class OcrLine:
    text: str
    confidence: float

    @property
    def uncertain(self) -> bool:
        return self.confidence < LOW_CONFIDENCE

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "uncertain": self.uncertain,
        }


#: A fragment this short beside a digit is a split, not a word. `63 13` is a
#: bearing designation the reader broke in half; `6313 2RS` is two real tokens.
_FRAGMENT = 2

#: An alphabetic run at least this long, immediately followed by digits, is two
#: tokens the reader ran together: `BUTTWELD51.1`. Shorter runs are left alone
#: because `SS316` and `SCH160` are single tokens and splitting them would
#: destroy a material grade and a pipe schedule.
_RUN = 5

_ALPHA_DIGIT = re.compile(rf"(?<=[A-Z]{{{_RUN}}})(?=\d)")


#: Unit and qualifier words a marking runs into its neighbour. Kept short and
#: explicit rather than derived, because a wrong entry here silently rewrites
#: catalogue text.
_UNIT_WORDS = frozenset(
    {"BAR", "MM", "KG", "NB", "PCT", "SQMM", "NOS", "EA", "PC", "LG", "OD", "THK"}
)


@lru_cache(maxsize=1)
def _vocabulary() -> frozenset[str]:
    """Words a split is allowed to produce: the class keywords and their nouns.

    Dictionary-driven, because a generic alpha-alpha split is not safe — nothing
    distinguishes `GATEVALVE` from a part number by shape alone. Requiring both
    halves to be words the taxonomy already knows makes the rule conservative by
    construction: it can only ever produce vocabulary the extractor understands.
    """
    from .taxonomy import real_classes

    words: set[str] = set(_UNIT_WORDS)
    for schema in real_classes():
        words.add(schema.noun.upper())
        for keyword in schema.keywords:
            words.update(part for part in keyword.upper().split() if len(part) > 2)
    return frozenset(words)


def _split_known(token: str) -> str:
    """Split a run-together token when both halves are known words.

    `KITZ -GATEVALVE` costs the class assignment entirely, and with it every
    attribute: the classifier looks for `gate` and `valve` as tokens and finds
    neither. One split recovers the whole record.
    """
    # The reader leaves punctuation attached — `-GATEVALVE` — so split the
    # alphabetic core and put the edges back.
    prefix, core, suffix = _peel(token)
    if len(core) < 6 or not core.isalpha():
        return token
    vocabulary = _vocabulary()
    if core in vocabulary:
        return token
    for cut in range(3, len(core) - 2):
        left, right = core[:cut], core[cut:]
        if left in vocabulary and right in vocabulary:
            return f"{prefix}{left} {right}{suffix}"
    return token


def _peel(token: str) -> tuple[str, str, str]:
    start, end = 0, len(token)
    while start < end and not token[start].isalpha():
        start += 1
    while end > start and not token[end - 1].isalpha():
        end -= 1
    return token[:start], token[start:end], token[end:]


def repair(text: str) -> str:
    """Undo the three ways this reader damages a marking.

    Measured on rendered plates, these three between them are nearly every
    failure: a designation split in half (`63 13`), a token split after a digit
    (`SS3 16-PTFE`), and `O` read for zero next to a digit (`17OMM`). All three
    are conservative on purpose — each was checked against the tokens it must
    *not* touch, because a repair that corrupts `SS316` into `SS 316` costs more
    than the misreads it fixes.
    """
    tokens = text.split()
    joined: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        if (
            nxt
            and token[-1:].isdigit()
            and nxt[:1].isdigit()
            and (len(token) <= _FRAGMENT or len(nxt) <= _FRAGMENT)
        ):
            joined.append(token + nxt)
            index += 2
            continue
        joined.append(token)
        index += 1

    out: list[str] = []
    for token in joined:
        if any(ch.isdigit() for ch in token):
            # O for zero, I and l for one — only where a digit sits beside them,
            # so `FLO-GV01634` keeps the O in FLO.
            chars = list(token)
            for i, ch in enumerate(chars):
                if ch not in "OIl":
                    continue
                before = chars[i - 1] if i else ""
                after = chars[i + 1] if i + 1 < len(chars) else ""
                if before.isdigit() or after.isdigit():
                    chars[i] = "0" if ch == "O" else "1"
            token = "".join(chars)
        token = _ALPHA_DIGIT.sub(" ", token)
        out.append(" ".join(_split_known(part) for part in token.split()))
    return " ".join(out)


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    seconds: float = 0.0
    engine: str = "rapidocr"

    @property
    def text(self) -> str:
        """The lines as one description, in reading order.

        Order barely matters downstream — Tier 1 compares token sets and the
        CPSE style profiles reorder attributes anyway — so no attempt is made to
        guess a nameplate's layout.
        """
        return repair(
            " ".join(line.text.strip() for line in self.lines if line.text.strip())
        )

    @property
    def mean_confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(line.confidence for line in self.lines) / len(self.lines)

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "text": self.text,
            "lines": [line.as_dict() for line in self.lines],
            "mean_confidence": round(self.mean_confidence, 4),
            "uncertain_lines": sum(1 for line in self.lines if line.uncertain),
            "seconds": round(self.seconds, 3),
        }


class OcrUnavailable(RuntimeError):
    """The reader is not installed. A stated absence, not a crash."""


def available() -> bool:
    """True only if the reader genuinely imports.

    A real import rather than `find_spec`, for the same reason capability
    detection uses one: a half-installed package advertises itself and then
    fails on use, which is worse than reporting the feature as absent.
    """
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


@lru_cache(maxsize=1)
def _reader():
    """The reader, loaded once. Models ship inside the wheel — nothing is
    downloaded, so this stays inside the offline guarantee (§9)."""
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def read(payload: bytes) -> OcrResult:
    """Read the text in an image. Raises `OcrUnavailable` if it cannot."""
    import time

    if not payload:
        raise ValueError("no image was sent")
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB"
        )
    if not available():
        raise OcrUnavailable(
            "The reader is not installed. Run `make deps-ocr`, or type the "
            "description instead; the check itself is the same either way."
        )

    import numpy as np
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
        image = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("that file is not an image the reader can open") from exc

    longest = max(image.size)
    if longest > MAX_EDGE:
        scale = MAX_EDGE / longest
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )

    started = time.perf_counter()
    raw, _ = _reader()(np.array(image))
    elapsed = time.perf_counter() - started

    lines = [
        OcrLine(text=str(text), confidence=float(score))
        for _box, text, score in (raw or [])
        if str(text).strip()
    ]
    return OcrResult(lines=lines, seconds=elapsed)
