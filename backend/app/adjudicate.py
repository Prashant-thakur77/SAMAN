"""Tier 3 — adjudication of the grey band (spec §0.4).

Tiers 0–2 produce a number and the veto layer produces a refusal. Neither
explains a *grey* pair, and grey is precisely where a human is about to spend
their attention. This tier reads the same evidence a reviewer would and says
what it thinks and why, in a sentence, so the reviewer starts from a position
rather than from a score.

Three rules govern it, and they are the point:

1. **The recommendation is deterministic.** It comes from the attribute
   comparison, never from a model. An LLM that decides which materials are the
   same is an LLM that will eventually decide wrongly and unaccountably.
2. **It never decides.** A recommendation is not a verdict; the pair stays in
   the queue and a person still approves or rejects it. Nothing here writes a
   cluster.
3. **Ollama, when configured, only rephrases.** It is handed the deterministic
   reasons and asked for prose. If it introduces a fact that is not in the
   evidence, its output is discarded and the deterministic sentence stands —
   the same guard the Copilot uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from .compare import IN_BAND, MATCH, MISMATCH, UNKNOWN
from .config import get_settings

#: A grey pair whose identity-critical attributes all agree and whose remaining
#: disagreements are cosmetic. The strongest thing this tier can say.
LEAN_MERGE = "lean_merge"

#: Identity attributes agree as far as they were compared, but too little of the
#: item's identity was readable to be confident.
LEAN_REVIEW = "lean_review"

#: Something concrete argues against the merge.
LEAN_SPLIT = "lean_split"

#: The same part number on two conflicting specifications. Neither a match nor
#: something to discard: a data-quality defect for someone to fix at source.
FLAG_CONFLICT = "flag_conflict"


@dataclass
class Adjudication:
    recommendation: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    summary: str = ""
    #: "deterministic" or "ollama" — which one wrote `summary`. The
    #: recommendation itself is always deterministic.
    prose_by: str = "deterministic"
    prose_note: str | None = None

    def as_dict(self) -> dict:
        return {
            "recommendation": self.recommendation,
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
            "summary": self.summary,
            "prose_by": self.prose_by,
            "prose_note": self.prose_note,
            "decides": False,
            "note": (
                "A recommendation, not a decision. The pair stays in the queue "
                "until a person approves or rejects it."
            ),
        }


def adjudicate(
    evidence: dict,
    tier_scores: dict,
    confidence: float,
    verdict: str = "review",
    veto: dict | None = None,
    rephrase: bool = True,
) -> Adjudication:
    """Tier 3: a recommendation with its reasons, and optionally model prose.

    The decision is `_decide`, deterministic. The prose is a courtesy that costs
    a model call per card, so the queue asks for it only on the card in front of
    the reviewer; every other card carries the deterministic sentence, which
    says the same thing.
    """
    result = _decide(evidence, tier_scores, confidence, verdict, veto)
    if rephrase:
        _maybe_rephrase(result, evidence)
    else:
        result.prose_note = "deterministic sentence; model prose only on the current card"
    return result


def _decide(
    evidence: dict,
    tier_scores: dict,
    confidence: float,
    verdict: str = "review",
    veto: dict | None = None,
) -> Adjudication:
    """Read a grey pair's stored evidence and recommend a direction.

    Takes the persisted evidence rather than live objects so the workbench can
    adjudicate any pair it can display, including one scored by an earlier run.

    The veto is authoritative. An earlier draft of this re-derived disagreement
    from the per-attribute results and used result names that do not exist
    (`conflict`, `exact`), so every negative branch was unreachable and the
    adjudicator cheerfully recommended merging a pair the veto layer had
    refused. Reading `vetoed_by` — the list §2A already builds — removes the
    chance to disagree with it.
    """
    attributes = evidence.get("attributes") or {}
    per_attr = attributes.get("per_attr") or []
    vetoed_by = (veto or {}).get("vetoed_by") or attributes.get("vetoed_by") or []
    reasons: list[str] = []

    identity = [c for c in per_attr if c.get("role") == "identity_critical"]
    agreed = [c for c in identity if c.get("result") in (MATCH, IN_BAND)]
    unknown = [c for c in identity if c.get("result") == UNKNOWN]

    # --- a part number with conflicting specifications ------------------
    if verdict == "conflict":
        detail = evidence.get("conflict") or "The same part number carries two specifications."
        reasons.append(detail)
        reasons += [f"{_pretty(v['attr'])}: {v.get('reason', '')}".strip() for v in vetoed_by]
        return _finish(FLAG_CONFLICT, 0.9, reasons, evidence)

    # --- what the veto layer refused ------------------------------------
    if vetoed_by:
        first = vetoed_by[0]
        reasons.append(f"{_pretty(first['attr'])}: {first.get('reason', 'disagrees')}")
        if len(vetoed_by) > 1:
            reasons.append(
                "Also "
                + ", ".join(_pretty(v["attr"]) for v in vetoed_by[1:4])
                + "."
            )
        return _finish(LEAN_SPLIT, 0.8, reasons, evidence)

    # --- what argues for holding it back --------------------------------
    if not evidence.get("defining_attribute_compared", True):
        reasons.append(
            f"{_pretty(evidence.get('defining_attribute'))} could not be read from "
            "one of the two rows: the attribute that most decides identity here."
        )
        if agreed:
            reasons.append(
                "What could be compared agrees: "
                + ", ".join(_pretty(c["attr"]) for c in agreed[:4])
                + "."
            )
        return _finish(LEAN_REVIEW, 0.55, reasons, evidence)

    coverage = evidence.get("identity_coverage")
    if coverage is not None and coverage < 1.0:
        total = evidence.get("identity_attributes_total") or len(identity)
        compared = evidence.get("identity_attributes_compared") or len(agreed)
        missing = ", ".join(_pretty(c["attr"]) for c in unknown[:3]) or "some attributes"
        reasons.append(
            f"Only {compared} of {total} identity attributes could be compared; "
            f"{missing} is not stated on one side."
        )
        if agreed:
            reasons.append(f"Everything that could be compared agrees ({len(agreed)}).")
        return _finish(LEAN_REVIEW, 0.5 + 0.3 * coverage, reasons, evidence)

    # --- what argues for the merge --------------------------------------
    if agreed:
        reasons.append(
            f"All {len(agreed)} identity-critical attributes agree, and the veto "
            "layer refused nothing."
        )
    cosmetic = [
        c
        for c in per_attr
        if c.get("role") == "cosmetic" and c.get("result") == MISMATCH
    ]
    if cosmetic:
        reasons.append(
            "The only differences are cosmetic: "
            + ", ".join(_pretty(c["attr"]) for c in cosmetic[:3])
            + "."
        )
    anchor = tier_scores.get("tier0_key")
    if anchor:
        reasons.append(f"Both rows carry the same {anchor.upper()}.")
    if not reasons:
        reasons.append("Text and attributes agree, but no single field is decisive.")
    return _finish(LEAN_MERGE, min(0.95, 0.6 + confidence / 3), reasons, evidence)


def _pretty(name) -> str:
    return str(name or "a defining attribute").replace("_", " ")


HEADLINE = {
    LEAN_MERGE: "Probably the same material",
    LEAN_REVIEW: "Not enough to decide automatically",
    LEAN_SPLIT: "Probably two different materials",
    FLAG_CONFLICT: "One part number, two specifications",
}


def _finish(
    recommendation: str, confidence: float, reasons: list[str], _evidence: dict
) -> Adjudication:
    summary = f"{HEADLINE[recommendation]}. {reasons[0]}" if reasons else HEADLINE[
        recommendation
    ]
    return Adjudication(recommendation, confidence, reasons, summary)


_PROMPT = """You are helping a materials reviewer at an Indian public-sector company.

Rewrite the assessment below as one plain sentence for the reviewer. Do not add
any fact, number or attribute that is not already in the reasons. Do not change
the recommendation. Do not add a greeting or a preamble.

Recommendation: {headline}
Reasons:
{reasons}

One sentence:"""


@lru_cache(maxsize=512)
def _generate(url: str, model: str, prompt: str) -> str:
    """One model call per distinct prompt. The same pair rephrased the same
    way every time it is shown, and never twice."""
    import httpx

    response = httpx.post(
        f"{url}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}},
        timeout=8.0,
    )
    response.raise_for_status()
    return (response.json().get("response") or "").strip()


def _maybe_rephrase(result: Adjudication, _evidence: dict) -> None:
    """Let a local model polish the sentence, under the Copilot's guard."""
    settings = get_settings()
    if not settings.llm_enabled:
        result.prose_note = "no local model configured"
        return

    from .copilot import _numbers_in

    prompt = _PROMPT.format(
        headline=HEADLINE[result.recommendation],
        reasons="\n".join(f"- {reason}" for reason in result.reasons),
    )
    try:
        candidate = _generate(settings.ollama_url.rstrip("/"), settings.ollama_model, prompt)
    except Exception as exc:
        result.prose_note = f"local model unavailable ({type(exc).__name__})"
        return

    if not candidate:
        result.prose_note = "the model returned nothing"
        return
    invented = _numbers_in(candidate) - _numbers_in(" ".join(result.reasons))
    if invented:
        result.prose_note = (
            f"the model introduced figures that were not in the evidence: "
            f"{sorted(invented)[:3]}"
        )
        return
    if len(candidate) > 400:
        result.prose_note = "the model's answer was too long to be a rephrasing"
        return

    result.summary = candidate
    result.prose_by = "ollama"
