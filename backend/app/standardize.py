"""Golden-record standardization — spec §2D.

Finding duplicates is half the job; the platform must also produce the clean,
canonical record that replaces them. Two pieces:

**Rendering** is a deterministic function of the class template and the fused
attributes. The same cluster always yields byte-identical text, which is what
makes the golden record a stable thing to key an ERP against. Nothing free-form
is ever written here — the local LLM may only polish a slot the template could
not fill, and its output is validated back against the template.

**Fusion** decides which value wins when cluster members disagree, in the order
§2D lays down:

    1. the highest-confidence extraction   (structured > designation > text > llm)
    2. majority vote across members, ties broken by most recent purchase
    3. the most complete/precise value
    4. an unresolved conflict on an identity_critical attribute does NOT
       auto-approve — the cluster is flagged and routed to a steward

Every fused field records which member it came from and which rule chose it, so
"where did this description come from?" has an exact answer.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .extract import SOURCE_PRIORITY
from .taxonomy import ClassSchema

#: Rule names persisted on `golden_field_provenance.rule`.
RULE_SOLE = "sole_value"
RULE_SOURCE = "highest_confidence_source"
RULE_MAJORITY = "majority_vote"
RULE_RECENT = "most_recent_purchase"
RULE_PRECISE = "most_precise_value"

_SLOT = re.compile(r"\{(\w+)\}")


@dataclass
class FusedField:
    field: str
    value: Any
    source_member_id: int | None
    rule: str
    #: every distinct value seen, for the evidence panel
    candidates: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "source_member_id": self.source_member_id,
            "rule": self.rule,
            "candidates": self.candidates,
        }


@dataclass
class Standardized:
    std_description: str
    attrs: dict[str, Any]
    provenance: list[FusedField]
    conflicts: list[dict]
    status: str  # draft | conflict

    @property
    def auto_approvable(self) -> bool:
        """§2D rule 4: an identity_critical conflict blocks auto-approval."""
        return self.status != "conflict"


# --------------------------------------------------------------------------
# Value formatting — determinism lives here
# --------------------------------------------------------------------------


def format_value(value: Any) -> str:
    """Render a value the same way every time.

    Numbers are the tricky part: 25 and 25.0 are the same measurement but
    different strings, and a golden description that flips between them is not
    a stable key.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, int | float):
        number = float(value)
        if number.is_integer():
            return str(int(number))
        # Trim trailing zeros without going through scientific notation.
        return f"{number:.4f}".rstrip("0").rstrip(".")
    return str(value).strip()


def _precision(value: Any) -> tuple[int, int]:
    """Rank a value's completeness: (has a unit-bearing form, string length).

    §2D rule 3 — "25.0 mm beats 25 mm approx, a value with units beats one
    without". Longer, more specific renderings win ties.
    """
    text = format_value(value)
    approximate = any(word in text.upper() for word in ("APPROX", "ABOUT", "~", "NOMINAL"))
    return (0 if approximate else 1, len(text))


# --------------------------------------------------------------------------
# Fusion
# --------------------------------------------------------------------------


@dataclass
class Member:
    """One cluster member, as fusion needs to see it."""

    id: int
    attrs: dict[str, Any]
    sources: dict[str, str]
    norm_text: str
    last_purchase: date | None = None


def _source_rank(source: str | None) -> int:
    try:
        return SOURCE_PRIORITY.index(source or "text")
    except ValueError:
        return len(SOURCE_PRIORITY)


def fuse_attribute(
    field_name: str, members: list[Member]
) -> tuple[FusedField | None, dict | None]:
    """Resolve one attribute across the cluster. Returns (fused, conflict)."""
    offered = [
        (m, m.attrs.get(field_name), m.sources.get(field_name, "text"))
        for m in members
        if m.attrs.get(field_name) is not None
    ]
    if not offered:
        return None, None

    candidates = [
        {"value": format_value(value), "member_id": m.id, "source": source}
        for m, value, source in offered
    ]
    distinct = {format_value(value) for _, value, _ in offered}

    if len(distinct) == 1:
        member, value, _ = offered[0]
        rule = RULE_SOLE if len(offered) == 1 else RULE_MAJORITY
        return FusedField(field_name, value, member.id, rule, candidates), None

    # --- rule 1: the highest-confidence extraction wins outright ---
    best_rank = min(_source_rank(source) for _, _, source in offered)
    top = [(m, v, s) for m, v, s in offered if _source_rank(s) == best_rank]
    if len({format_value(v) for _, v, _ in top}) == 1:
        member, value, _ = top[0]
        return FusedField(field_name, value, member.id, RULE_SOURCE, candidates), None

    # --- rule 2: majority vote among the best source tier ---
    votes = Counter(format_value(v) for _, v, _ in top)
    ranked = votes.most_common()
    if len(ranked) > 1 and ranked[0][1] > ranked[1][1]:
        winner = ranked[0][0]
        member, value, _ = next((m, v, s) for m, v, s in top if format_value(v) == winner)
        return FusedField(field_name, value, member.id, RULE_MAJORITY, candidates), None

    # --- rule 2b: tie broken by the most recent purchase ---
    tied_value = ranked[0][0]
    tied_count = ranked[0][1]
    tied = [
        (m, v, s)
        for m, v, s in top
        if votes[format_value(v)] == tied_count
    ]
    dated = [(m, v, s) for m, v, s in tied if m.last_purchase is not None]
    if dated:
        member, value, _ = max(dated, key=lambda row: row[0].last_purchase)
        return FusedField(field_name, value, member.id, RULE_RECENT, candidates), None

    # --- rule 3: the most complete/precise value ---
    member, value, _ = max(tied, key=lambda row: (_precision(row[1]), -row[0].id))
    conflict = {
        "attr": field_name,
        "values": sorted(distinct),
        "members": [m.id for m, _, _ in offered],
        "resolved_as": format_value(value),
        "note": f"members disagree on {field_name}; kept the most precise value",
    }
    _ = tied_value
    return FusedField(field_name, value, member.id, RULE_PRECISE, candidates), conflict


def fuse(members: list[Member], schema: ClassSchema) -> tuple[dict, list[FusedField], list[dict]]:
    """Fuse every declared attribute across the cluster."""
    attrs: dict[str, Any] = {}
    provenance: list[FusedField] = []
    conflicts: list[dict] = []

    for name, spec in schema.attributes.items():
        fused, conflict = fuse_attribute(name, members)
        if fused is None:
            continue
        attrs[name] = fused.value
        provenance.append(fused)
        if conflict:
            # Only an identity_critical disagreement blocks approval (§2D.4);
            # a cosmetic one is recorded and moved past.
            conflict["role"] = spec.role
            conflict["blocking"] = spec.role == "identity_critical"
            conflicts.append(conflict)

    return attrs, provenance, conflicts


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_description(
    attrs: dict[str, Any], schema: ClassSchema, mpn: str | None = None
) -> str:
    """Render the class template. Deterministic for a given attribute set.

    A template segment whose slots cannot be filled is dropped rather than
    emitted with an empty hole, so a partially-extracted item still produces
    clean text instead of "BEARING, , 52MM OD".
    """
    values = {name: format_value(value) for name, value in attrs.items()}
    values.setdefault("noun", schema.noun)
    values["mpn"] = format_value(mpn) if mpn else ""

    rendered: list[str] = []
    for segment in schema.template.split(","):
        slots = _SLOT.findall(segment)
        # A segment with slots needs at least one of them filled to be worth
        # emitting; a literal segment is always kept.
        if slots and not any(values.get(slot) for slot in slots):
            continue
        text = _SLOT.sub(lambda m: values.get(m.group(1), ""), segment)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            rendered.append(text)

    description = ", ".join(rendered)
    if schema.casing == "upper":
        description = description.upper()
    elif schema.casing == "title":
        description = description.title()
    if len(description) > schema.max_len:
        # Trim at a separator so the result stays readable rather than cut mid-token.
        description = description[: schema.max_len].rsplit(", ", 1)[0]
    return description


_DELTA_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9.\-/]*", re.IGNORECASE)


def _delta_tokens(text: str) -> set[str]:
    return {t.rstrip(".,") for t in _DELTA_TOKEN.findall(text or "")}


def standardization_delta(member: Member, golden: str) -> dict:
    """What changed from this member's legacy text to the golden record.

    §2D: this delta is what a CPSE actually reviews, so it is reported per
    member rather than only as a finished description.
    """
    # Compare on content tokens, not raw whitespace splits: the template
    # introduces separators, and reporting "150," as added while "150" was
    # dropped would be noise rather than a delta.
    legacy_set = _delta_tokens(member.norm_text)
    golden_set = _delta_tokens(golden)
    return {
        "member_id": member.id,
        "legacy": member.norm_text,
        "golden": golden,
        "unchanged": golden == member.norm_text,
        "tokens_added": sorted(golden_set - legacy_set),
        "tokens_dropped": sorted(legacy_set - golden_set),
        "length_before": len(member.norm_text),
        "length_after": len(golden),
    }


def standardize(
    members: list[Member], schema: ClassSchema, mpn: str | None = None
) -> Standardized:
    """Fuse, then render. The §2D entry point."""
    attrs, provenance, conflicts = fuse(members, schema)
    description = render_description(attrs, schema, mpn)
    blocking = [c for c in conflicts if c.get("blocking")]
    return Standardized(
        std_description=description,
        attrs=attrs,
        provenance=provenance,
        conflicts=conflicts,
        status="conflict" if blocking else "draft",
    )
