"""Tiered matching engine — spec §0.4, §2A.

Tier 0  exact anchor keys: normalized MPN, GTIN, normalized-text hash
Tier 1  probabilistic linkage: splink Fellegi-Sunter match weight when it is
        available, otherwise rapidfuzz token_set_ratio (spec §0.4)
Tier 2  semantic similarity over the embedding vectors
VETO    §2A hard constraints, applied to candidates from EVERY tier
Tier 3  adjudication of the grey band (deterministic, or Ollama when configured)

Two rules do most of the precision work, and neither is a similarity score:

* **The veto.** Any identity_critical mismatch refuses the pair outright. An
  anchor-key match that is vetoed is not silently dropped either — same part
  number with conflicting specifications is a data-quality error, so it is
  raised as `conflict` for review with both values shown (§0.4).

* **The distinct-manufacturer rule.** Two items that each carry a part number,
  from different manufacturers, are not the same material record even when
  every technical attribute agrees — brand is cosmetic for *vetoing* but two
  OEM part numbers are two catalogue entries. They are interchangeable, which
  is a §2B relation, not a merge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from rapidfuzz import fuzz

from .compare import CompareResult, compare_attrs
from .embed import cosine
from .taxonomy import UNCLASSIFIED, get_schema

if TYPE_CHECKING:  # avoids importing splink's stack unless it is actually used
    from .linkage import LinkageResult

# --------------------------------------------------------------------------
# Thresholds. Tuned on the 60% tuning split only (§0.6), then frozen.
# --------------------------------------------------------------------------

#: At or above this a pair is auto-accepted as a duplicate.
#: Chosen by `python -m app.cli tune`, which sweeps thresholds on the 60%
#: tuning split only and reports the table. Frozen here; never re-tuned against
#: the held-out numbers (§0.6).
T_HIGH = 0.86
#: Below this a pair is auto-rejected without human review.
T_LOW = 0.45

#: Contribution weights for the evidence score. They sum to 1.
W_FUZZY = 0.34
W_SEMANTIC = 0.24
W_ATTRIBUTE = 0.42

#: An anchor key is strong evidence on its own; the remaining mass still has to
#: be earned from the other tiers, so a vetoed anchor never reaches the top.
ANCHOR_BASE = 0.74

#: A same-class pair needs at least this many identity_critical attributes
#: compared before attribute agreement is treated as real support.
MIN_IDENTITY_ATTRS = 1


@dataclass
class MatchCandidate:
    """Everything the matcher needs about one item."""

    id: int
    class_code: str
    class_confidence: float
    norm_text: str
    norm_hash: str
    mpn_norm: str | None
    gtin: str | None
    attrs: dict
    vector: np.ndarray | None = None

    @property
    def brand(self) -> str | None:
        value = self.attrs.get("brand")
        return str(value).upper() if value else None

    @property
    def is_classified(self) -> bool:
        return self.class_code != UNCLASSIFIED


@dataclass
class MatchResult:
    item_a: int
    item_b: int
    verdict: str  # duplicate | conflict | distinct
    band: str  # high | grey | low
    confidence: float
    tier_scores: dict = field(default_factory=dict)
    veto: dict | None = None
    equivalence: dict | None = None
    evidence: dict = field(default_factory=dict)

    @property
    def needs_review(self) -> bool:
        return self.band == "grey" or self.verdict == "conflict"


# --------------------------------------------------------------------------
# Tier scoring
# --------------------------------------------------------------------------


def tier0_anchor(a: MatchCandidate, b: MatchCandidate) -> tuple[float, str | None]:
    """Exact keys, in descending order of real-world precision."""
    if a.mpn_norm and b.mpn_norm and a.mpn_norm == b.mpn_norm:
        return 1.0, "mpn"
    if a.gtin and b.gtin and a.gtin == b.gtin:
        return 1.0, "gtin"
    if a.norm_hash == b.norm_hash:
        return 0.95, "norm_text"
    return 0.0, None


def tier1_fuzzy(a: MatchCandidate, b: MatchCandidate) -> float:
    """token_set_ratio absorbs word order and the abbreviation noise.

    The Tier-1 fallback when splink is not installed, and the value the
    evidence card falls back to showing.
    """
    return fuzz.token_set_ratio(a.norm_text, b.norm_text) / 100.0


def tier1_linkage(
    a: MatchCandidate, b: MatchCandidate, linkage: LinkageResult | None
) -> tuple[float, str, dict | None]:
    """Tier-1 score, preferring learned match weights over a raw string ratio.

    Returns (score, engine, waterfall). splink only emits pairs its own
    blocking produced, so a pair it never saw falls back to rapidfuzz rather
    than being scored as though it had failed.
    """
    if linkage is not None:
        probability = linkage.score(a.id, b.id)
        if probability is not None:
            return probability, "splink", linkage.waterfall(a.id, b.id)
    return tier1_fuzzy(a, b), "rapidfuzz", None


def tier2_semantic(a: MatchCandidate, b: MatchCandidate) -> float:
    return cosine(a.vector, b.vector)


def distinct_manufacturers(a: MatchCandidate, b: MatchCandidate) -> str | None:
    """Are these two different manufacturers' catalogue records?

    SKF 6205-2Z and FAG 6205-2ZR share every technical attribute. They are
    interchangeable, not identical: a material master record is per
    manufacturer, so merging them into one CNMC would erase a distinction CPSE
    masters genuinely carry (§2B).

    Note this does not contradict §2A treating brand as `cosmetic`. Brand never
    vetoes on *specification* — two items may be technically equivalent — but
    equivalence is a directed relation, not a merge.

    Returns the strength of the evidence, or None. Both brands must be present
    and recognised: a missing or misspelled brand extracts as None and the rule
    stays silent rather than costing recall.
    """
    if not (a.brand and b.brand and a.brand != b.brand):
        return None
    if a.mpn_norm and b.mpn_norm and a.mpn_norm != b.mpn_norm:
        return "brand+mpn"
    return "brand"


def _evidence_score(fuzzy: float, semantic: float, comparison: CompareResult | None) -> float:
    if comparison is None or comparison.compared == 0:
        # No attribute evidence at all: redistribute its weight over the two
        # similarity tiers rather than scoring the pair as if it had failed.
        total = W_FUZZY + W_SEMANTIC
        return (W_FUZZY * fuzzy + W_SEMANTIC * semantic) / total
    return W_FUZZY * fuzzy + W_SEMANTIC * semantic + W_ATTRIBUTE * comparison.agreement


def _band(confidence: float) -> str:
    if confidence >= T_HIGH:
        return "high"
    if confidence < T_LOW:
        return "low"
    return "grey"


# --------------------------------------------------------------------------
# The matcher
# --------------------------------------------------------------------------


def match_pair(
    a: MatchCandidate,
    b: MatchCandidate,
    linkage: LinkageResult | None = None,
) -> MatchResult:
    """Score and adjudicate one candidate pair, with its evidence."""
    anchor, anchor_kind = tier0_anchor(a, b)
    fuzzy, tier1_engine, waterfall = tier1_linkage(a, b, linkage)
    semantic = tier2_semantic(a, b)

    tier_scores = {
        "tier0_anchor": round(anchor, 4),
        "tier0_key": anchor_kind,
        "tier1_fuzzy": round(fuzzy, 4),
        "tier1_engine": tier1_engine,
        "tier2_semantic": round(semantic, 4),
    }
    if waterfall:
        tier_scores["tier1_waterfall"] = waterfall

    # --- the schema-less pool (§2A.1) -----------------------------------
    # Without a class we have no identity_critical fields, so the veto layer
    # cannot protect the pair. Only an exact anchor key is allowed to merge.
    schema_less = not a.is_classified or not b.is_classified or a.class_code != b.class_code
    if schema_less:
        confidence = anchor if anchor_kind else 0.0
        verdict = "duplicate" if anchor_kind else "distinct"
        return MatchResult(
            a.id, b.id, verdict, _band(confidence), round(confidence, 4), tier_scores,
            evidence={
                "route": "anchor_only",
                "reason": (
                    "class uncertain — only an exact anchor key may match here"
                    if not (a.is_classified and b.is_classified)
                    else "different classes — only an exact anchor key may match here"
                ),
                "class_a": a.class_code,
                "class_b": b.class_code,
                "class_confidence": [a.class_confidence, b.class_confidence],
            },
        )

    schema = get_schema(a.class_code)
    comparison = compare_attrs(a.attrs, b.attrs, schema)
    tier_scores["attribute_agreement"] = round(comparison.agreement, 4)

    evidence: dict = {
        "route": "tiered",
        "class": a.class_code,
        "anchor": anchor_kind,
        "attributes": comparison.as_evidence(),
    }

    equivalence = None
    if comparison.equivalence_candidate:
        equivalence = {
            "basis": "rule",
            "direction": comparison.direction,
            "reason": comparison.vetoed_by,
        }

    # --- the veto short-circuits every similarity score (§2A) -------------
    if comparison.is_veto:
        if anchor_kind in ("mpn", "gtin"):
            # Same part number, conflicting specifications. Neither a match nor
            # something to discard quietly — it is a data-quality defect (§0.4).
            return MatchResult(
                a.id, b.id, "conflict", "grey", round(anchor, 4), tier_scores,
                veto=comparison.as_evidence(),
                equivalence=equivalence,
                evidence={
                    **evidence,
                    "conflict": (
                        f"Both rows carry {anchor_kind.upper()} "
                        f"{a.mpn_norm or a.gtin}, but their specifications disagree."
                    ),
                },
            )
        return MatchResult(
            a.id, b.id, "distinct", "low", 0.0, tier_scores,
            veto=comparison.as_evidence(), equivalence=equivalence, evidence=evidence,
        )

    # --- distinct manufacturers are not one record (§2B) ------------------
    manufacturer_evidence = distinct_manufacturers(a, b)
    if manufacturer_evidence:
        return MatchResult(
            a.id, b.id, "distinct", "low", 0.0, tier_scores,
            equivalence={
                "basis": "crossref",
                "direction": "bidirectional",
                "reason": [
                    {
                        "attr": "manufacturer",
                        "a": f"{a.brand} {a.mpn_norm or ''}".strip(),
                        "b": f"{b.brand} {b.mpn_norm or ''}".strip(),
                        "evidence": manufacturer_evidence,
                        "reason": "different manufacturers — interchangeable, not identical",
                    }
                ],
            },
            evidence={
                **evidence,
                "refused": "different manufacturers; recorded as an equivalence instead",
            },
        )

    score = _evidence_score(fuzzy, semantic, comparison)
    identity_compared = sum(
        1
        for c in comparison.per_attr
        if c.role == "identity_critical" and c.result != "unknown"
    )

    if anchor_kind:
        confidence = min(1.0, ANCHOR_BASE + (1.0 - ANCHOR_BASE) * score)
    else:
        confidence = score
        # Attribute agreement with nothing identifying behind it is weak
        # evidence; hold the pair back for review rather than auto-merging.
        if identity_compared < MIN_IDENTITY_ATTRS:
            confidence = min(confidence, T_HIGH - 0.01)

    band = _band(confidence)
    verdict = "duplicate" if band == "high" else "distinct" if band == "low" else "duplicate"
    if band == "grey":
        verdict = "review"

    return MatchResult(
        a.id, b.id, verdict, band, round(confidence, 4), tier_scores,
        equivalence=equivalence,
        evidence={**evidence, "identity_attributes_compared": identity_compared},
    )


def candidate_from_row(row) -> MatchCandidate:
    """Build a candidate from an `item` row tuple."""
    (item_id, class_code, class_confidence, norm_text, norm_hash, mpn, gtin, attrs_json, blob) = row
    from .embed import unpack

    return MatchCandidate(
        id=item_id,
        class_code=class_code,
        class_confidence=class_confidence or 0.0,
        norm_text=norm_text or "",
        norm_hash=norm_hash or "",
        mpn_norm=mpn,
        gtin=gtin,
        attrs=json.loads(attrs_json or "{}"),
        vector=unpack(blob),
    )
