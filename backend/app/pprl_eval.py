"""Measure restricted mode against the plaintext ground truth (§0.6, M10).

A privacy-preserving matcher that nobody has measured is a claim, not a
feature. This scores both feature modes against `truth_group` so the cost of
the privacy guarantee is a number rather than an impression.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import pprl
from .models import Cpse, Item, RawItem, TruthGroup


def _catalogue(db: Session, cpse_code: str, key: str, mode: str, limit: int):
    cpse_id = db.execute(select(Cpse.id).where(Cpse.code == cpse_code)).scalar_one()
    rows = db.execute(
        select(
            RawItem.id,
            Item.class_code,
            Item.attrs_json,
            Item.mpn_norm,
            Item.norm_text,
            TruthGroup.group_id,
        )
        .join(Item, Item.raw_item_id == RawItem.id)
        .join(TruthGroup, TruthGroup.raw_item_id == RawItem.id)
        .where(RawItem.cpse_id == cpse_id)
        .order_by(RawItem.id)
        .limit(limit)
    ).all()

    out = []
    for _raw_id, class_code, attrs_json, mpn, norm_text, group in rows:
        if mode == "attribute" and class_code:
            features = pprl.attribute_features(
                class_code, json.loads(attrs_json or "{}"), mpn
            )
        else:
            features = pprl.grams(norm_text or "")
        out.append((group, pprl.encode_features(features, key, mode)))
    return out


def evaluate(
    db: Session,
    left_cpse: str,
    right_cpse: str,
    mode: str = pprl.DEFAULT_MODE,
    limit: int = 300,
    key: str = "saman-evaluation-key",
) -> dict:
    """Precision, recall and F1 for restricted mode against the truth table."""
    settings = pprl.params(mode)
    a = _catalogue(db, left_cpse, key, mode, limit)
    b = _catalogue(db, right_cpse, key, mode, limit)
    truth = sum(1 for ga, _ in a for gb, _ in b if ga == gb)

    tp = fp = 0
    for group_a, bits_a in a:
        for group_b, bits_b in b:
            if pprl.dice(bits_a, bits_b) >= settings["threshold"]:
                if group_a == group_b:
                    tp += 1
                else:
                    fp += 1

    predicted = tp + fp
    precision = tp / predicted if predicted else 0.0
    recall = tp / truth if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "mode": mode,
        "pair": f"{left_cpse}×{right_cpse}",
        "left_records": len(a),
        "right_records": len(b),
        "truth_pairs": truth,
        "predicted_pairs": predicted,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "threshold": settings["threshold"],
        "filter_bits": settings["bits"],
        "hashes_per_feature": settings["hashes"],
    }
