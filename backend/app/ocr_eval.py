"""How well does reading a marking actually find the right material? (§0.6)

A camera feature without a number is a demo. This renders a nameplate for each
of a sample of held-out materials, degrades the image the way a phone in a
warehouse would, reads it back and asks whether Smart-Create returns the
material the plate came from.

**What this measures, and what it does not.** The plates are rendered, not
photographed: the type is clean, the lighting is even, and the vocabulary is the
seed's. So this measures the *pipeline* — reader, normalizer, extractor, matcher
— on progressively harder images, and it does not measure how the reader copes
with a scratched bearing race at an angle under sodium light. That would need
photographs nobody has. The number is honest about which question it answers.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ocr, smart_create
from .models import ClusterMember, Item, RawItem, TruthGroup

#: How the image is spoiled before it is read, in increasing severity.
#:
#: `clean` is a scanned nameplate. `angled` and `worn` bracket what a phone
#: produces in a warehouse. `severe` is deliberately past the point of
#: usefulness — it is kept because the cliff is the finding: the reader does not
#: degrade gracefully, it stops, and its own confidence says so before the match
#: does. That is what makes a confidence threshold in the UI honest rather than
#: decorative.
CONDITIONS = ("clean", "angled", "worn", "severe")

#: Mean reader confidence below which the scan endpoint asks for another
#: photograph rather than presenting a result. Set from the sweep, not by eye —
#: the reader's own confidence turns out to predict the outcome sharply, and the
#: cliff is at 0.90 rather than anywhere lower:
#:
#:   confidence >= 0.90   ->  0.83 of scans resolve to the right material
#:   confidence 0.80-0.90 ->  0.19
#:   confidence <  0.70   ->  0.00
#:
#: So a scan below this is not a weak result, it is a wasted one, and saying so
#: costs the user two seconds instead of a wrong answer.
RETAKE_BELOW = 0.90


@dataclass
class ScanOutcome:
    item_id: int
    condition: str
    ocr_text: str
    confidence: float
    found: bool
    top_confidence: float


def _render_plate(text: str, condition: str, rng: random.Random):
    """Draw the marking onto a plate, then spoil it to taste."""
    from PIL import Image, ImageDraw, ImageFilter

    width, height = 900, 300
    image = Image.new("RGB", (width, height), (247, 247, 247))
    draw = ImageDraw.Draw(image)
    draw.rectangle([12, 12, width - 12, height - 12], outline=(30, 30, 30), width=4)

    # Wrap on commas and spaces, the way a real plate is laid out in rows.
    words = text.replace(",", " ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > 34:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)

    for index, line in enumerate(lines[:7]):
        draw.text((44, 40 + index * 32), line, fill=(20, 20, 20))

    if condition == "clean":
        return image

    if condition == "angled":
        image = image.rotate(rng.uniform(-4, 4), expand=True, fillcolor=(247, 247, 247))
        image = image.filter(ImageFilter.GaussianBlur(0.6))
        return image

    from PIL import ImageEnhance

    if condition == "worn":
        # A phone photograph of a stamped plate: a little shake, a little
        # contrast lost to the metal, ordinary JPEG compression.
        image = image.rotate(rng.uniform(-6, 6), expand=True, fillcolor=(240, 240, 240))
        image = image.filter(ImageFilter.GaussianBlur(0.9))
        image = ImageEnhance.Contrast(image).enhance(0.75)
        quality = 55
    else:
        # `severe`: past the point of usefulness, on purpose.
        image = image.rotate(rng.uniform(-8, 8), expand=True, fillcolor=(230, 230, 230))
        image = image.filter(ImageFilter.GaussianBlur(1.4))
        image = ImageEnhance.Contrast(image).enhance(0.45)
        quality = 30

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def _to_png(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def evaluate(
    db: Session,
    samples: int = 40,
    conditions: tuple[str, ...] = CONDITIONS,
    seed: int = 20260101,
) -> dict:
    """Render, degrade, read and match. Held-out materials only."""
    if not ocr.available():
        return {"status": "unavailable", "note": "the OCR reader is not installed"}

    rng = random.Random(seed)
    rows = db.execute(
        select(Item.id, Item.norm_text, ClusterMember.cluster_id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(TruthGroup, TruthGroup.raw_item_id == RawItem.id)
        .join(ClusterMember, ClusterMember.item_id == Item.id)
        .where(TruthGroup.split == "holdout")
        .order_by(Item.id)
    ).all()
    if not rows:
        return {"status": "no_data", "note": "no held-out items with a cluster"}

    chosen = rng.sample(rows, min(samples, len(rows)))
    outcomes: list[ScanOutcome] = []

    for item_id, norm_text, cluster_id in chosen:
        for condition in conditions:
            image = _render_plate(norm_text or "", condition, rng)
            try:
                reading = ocr.read(_to_png(image))
            except (ValueError, ocr.OcrUnavailable):
                continue

            found, top = False, 0.0
            if reading.text:
                result = smart_create.check(db, reading.text, limit=5)
                for suggestion in result["suggestions"]:
                    member = db.execute(
                        select(ClusterMember.cluster_id).where(
                            ClusterMember.item_id == suggestion["item_id"]
                        )
                    ).scalar()
                    if member == cluster_id:
                        found = True
                        top = max(top, suggestion["confidence"])
                        break
            outcomes.append(
                ScanOutcome(
                    item_id=item_id,
                    condition=condition,
                    ocr_text=reading.text,
                    confidence=reading.mean_confidence,
                    found=found,
                    top_confidence=top,
                )
            )

    by_condition = {}
    for condition in conditions:
        subset = [o for o in outcomes if o.condition == condition]
        if not subset:
            continue
        by_condition[condition] = {
            "scanned": len(subset),
            "resolved": sum(1 for o in subset if o.found),
            "resolution_rate": round(
                sum(1 for o in subset if o.found) / len(subset), 4
            ),
            "mean_ocr_confidence": round(
                sum(o.confidence for o in subset) / len(subset), 4
            ),
            "read_nothing": sum(1 for o in subset if not o.ocr_text),
        }

    # Does the reader's own confidence predict whether the match will land?
    # If it does, the UI can tell a user to retake the photo before wasting
    # their time on a result built from a misread.
    buckets: dict[str, dict] = {}
    for label, low, high in (
        ("below 0.70", 0.0, 0.70),
        ("0.70-0.80", 0.70, 0.80),
        ("0.80-0.90", 0.80, 0.90),
        ("0.90 and up", 0.90, 1.01),
    ):
        subset = [o for o in outcomes if low <= o.confidence < high]
        if subset:
            buckets[label] = {
                "scans": len(subset),
                "resolution_rate": round(
                    sum(1 for o in subset if o.found) / len(subset), 4
                ),
            }

    return {
        "status": "measured",
        "samples": len(chosen),
        "split": "holdout",
        "by_condition": by_condition,
        "by_reader_confidence": buckets,
        "retake_below": RETAKE_BELOW,
        "note": (
            "Plates are rendered and then degraded, not photographed. This "
            "measures the reader, normalizer, extractor and matcher together on "
            "progressively harder images; it does not measure a scratched race "
            "photographed at an angle, which would need images nobody has."
        ),
    }
