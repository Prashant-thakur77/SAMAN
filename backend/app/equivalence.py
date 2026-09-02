"""Functional equivalence — a separate, directed relation (spec §2B).

The problem statement asks for identical, duplicate, near-duplicate **and
functionally equivalent** items. The first three are similarity problems; the
fourth is not, and pure NLP does not solve it. This is an explicit rules and
knowledge layer, and we say so plainly rather than pretending embeddings cover
it.

**Duplicate is symmetric; equivalence is directed.** A 500 bar valve can stand
in for a 300 bar requirement; the reverse is unsafe. The direction is stored.

Four evidence sources, in precision order:

    1. designation  two items whose parsed standard designations agree on every
                    identity-critical field are the same specification, however
                    differently they are written
    2. crossref     a seeded, steward-editable table of interchangeable OEM part
                    numbers (SKF 6205-2Z <-> FAG 6205-2ZR <-> NSK 6205ZZ)
    3. rule         per-class YAML substitution rules — data, not code
    4. llm          may only *propose*; never auto-approves, always subject to
                    the §2A vetoes (wired in M6)

Equivalent items keep distinct CNMCs. Nothing here ever merges a cluster.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from .compare import EPSILON, compare_attrs
from .extract import parse_designation
from .numeric import parse_number
from .taxonomy import ClassSchema

#: Highest trust first. Also the order the engine tries them in.
BASIS_PRIORITY = ("crossref", "designation", "rule", "rating", "llm")

BASIS_CONFIDENCE = {
    "crossref": 0.98,   # a published interchange is as good as it gets
    "designation": 0.95,  # the item states its own specification
    "rule": 0.85,       # a steward's rule, applied to extracted attributes
    "rating": 0.80,     # the class schema's own `direction: higher_ok`
    "llm": 0.50,        # a suggestion for a human, never more
}

#: Every identity-critical attribute must have been readable on both sides
#: before a rating difference may imply a substitution — not most of them.
#:
#: A substitution is a safety claim: "you may use B where A was specified". A
#: partial guard let it through on a valve whose body material had not
#: extracted (SS361, a typo for SS316) and on a cable whose voltage had not
#: (330V0). Both agreed on everything that *was* readable and differed on a
#: rated attribute, so both were proposed — across an unknown body material
#: and an unknown voltage rating. "We could not read it" is not a basis for
#: telling a buyer the parts interchange.
REQUIRE_FULL_IDENTITY = True

REL_EQUIVALENT = "equivalent"
REL_SUPERSEDES = "supersedes"

DIRECTION_BOTH = "bidirectional"
DIRECTION_A_TO_B = "a_to_b"
DIRECTION_B_TO_A = "b_to_a"


# --------------------------------------------------------------------------
# The substitution rule DSL (§2B source 3) — rules are data, not code
# --------------------------------------------------------------------------

_CONDITION = re.compile(r"^\s*(\w+)\s*(==|!=|>=|<=)\s*$")


@dataclass(frozen=True)
class Condition:
    attr: str
    op: str

    def __str__(self) -> str:
        return f"{self.attr} {self.op}"


@dataclass
class SubstitutionRuleSet:
    class_code: str
    equivalent_if: tuple[Condition, ...] = ()
    substitutable_if: tuple[Condition, ...] = ()
    never_if: tuple[Condition, ...] = ()


def _parse_conditions(raw: list[str] | None) -> tuple[Condition, ...]:
    conditions: list[Condition] = []
    for entry in raw or []:
        match = _CONDITION.match(str(entry))
        if not match:
            # A malformed rule is a steward's typo, not a reason to fail the
            # pipeline; skip it and keep the rest of the rule usable.
            continue
        conditions.append(Condition(match.group(1), match.group(2)))
    return tuple(conditions)


def parse_rules(rule_yaml: str) -> list[SubstitutionRuleSet]:
    """Parse the YAML DSL. Never raises on bad input — returns what it can."""
    try:
        document = yaml.safe_load(rule_yaml) or []
    except yaml.YAMLError:
        return []
    if isinstance(document, dict):
        document = [document]

    out: list[SubstitutionRuleSet] = []
    for entry in document:
        if not isinstance(entry, dict) or not entry.get("class"):
            continue
        out.append(
            SubstitutionRuleSet(
                class_code=str(entry["class"]),
                equivalent_if=_parse_conditions(entry.get("equivalent_if")),
                substitutable_if=_parse_conditions(entry.get("substitutable_if")),
                never_if=_parse_conditions(entry.get("never_if")),
            )
        )
    return out


def _values(attrs_a: dict, attrs_b: dict, attr: str):
    return attrs_a.get(attr), attrs_b.get(attr)


def _as_float(value) -> float | None:
    parsed = parse_number(value)
    return parsed.value if parsed else None


def _equal(a, b) -> bool:
    left, right = _as_float(a), _as_float(b)
    if left is not None and right is not None:
        return abs(left - right) <= EPSILON
    return str(a).strip().upper() == str(b).strip().upper()


def evaluate_condition(condition: Condition, attrs_a: dict, attrs_b: dict) -> bool | None:
    """Evaluate one condition. None means "not decidable from what we have"."""
    a, b = _values(attrs_a, attrs_b, condition.attr)
    if a is None or b is None:
        return None

    if condition.op == "==":
        return _equal(a, b)
    if condition.op == "!=":
        return not _equal(a, b)

    left, right = _as_float(a), _as_float(b)
    if left is None or right is None:
        return None
    # ">=" reads as "B meets or exceeds A", the direction of substitution.
    return right >= left - EPSILON if condition.op == ">=" else right <= left + EPSILON


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


@dataclass
class EquivalenceVerdict:
    rel_type: str
    direction: str
    basis: str
    confidence: float
    evidence: dict = field(default_factory=dict)

    def as_row(self, item_a: int, item_b: int) -> dict:
        """Normalized so (a, b) is always stored with a < b."""
        direction = self.direction
        if item_a > item_b:
            item_a, item_b = item_b, item_a
            direction = {
                DIRECTION_A_TO_B: DIRECTION_B_TO_A,
                DIRECTION_B_TO_A: DIRECTION_A_TO_B,
            }.get(direction, direction)
        return {
            "item_a": item_a,
            "item_b": item_b,
            "rel_type": self.rel_type,
            "direction": direction,
            "confidence": round(self.confidence, 4),
            "basis": self.basis,
            "evidence_json": self.evidence,
            "status": "proposed",
        }


@dataclass
class Candidate:
    """One item, as the equivalence engine needs to see it."""

    id: int
    class_code: str
    norm_text: str
    mpn_norm: str | None
    attrs: dict


# --------------------------------------------------------------------------
# The four evidence sources
# --------------------------------------------------------------------------


def by_crossref(
    a: Candidate, b: Candidate, crossrefs: dict[str, set[str]]
) -> EquivalenceVerdict | None:
    """A published OEM interchange. The strongest evidence available."""
    if not (a.mpn_norm and b.mpn_norm):
        return None
    if b.mpn_norm not in crossrefs.get(a.mpn_norm, ()):
        return None
    return EquivalenceVerdict(
        rel_type=REL_EQUIVALENT,
        direction=DIRECTION_BOTH,
        basis="crossref",
        confidence=BASIS_CONFIDENCE["crossref"],
        evidence={
            "source": "OEM cross-reference table",
            "mpn_a": a.mpn_norm,
            "mpn_b": b.mpn_norm,
            "brand_a": a.attrs.get("brand"),
            "brand_b": b.attrs.get("brand"),
        },
    )


def by_designation(a: Candidate, b: Candidate, schema: ClassSchema) -> EquivalenceVerdict | None:
    """Two designations that agree on every identity-critical field.

    This is what recognises SKF 6205-2Z and FAG 6205-2ZR as the same bearing
    even though neither description mentions the other's part number.
    """
    left = parse_designation(a.norm_text, a.class_code)
    right = parse_designation(b.norm_text, b.class_code)
    if not (left and right) or left.kind != right.kind:
        return None

    critical = {spec.name for spec in schema.identity_critical}
    shared = (set(left.attrs) & set(right.attrs) & critical) or (
        set(left.attrs) & set(right.attrs)
    )
    if not shared:
        return None
    if any(not _equal(left.attrs[name], right.attrs[name]) for name in shared):
        return None

    # A designation rarely encodes every identity-critical field — a metric
    # thread says nothing about a bolt's grade or material. Agreeing on the
    # part it does encode is not evidence about the rest, so the remaining
    # identity-critical attributes must be comparable and must agree before
    # this claims the two are the same specification.
    for name in critical - shared:
        a_value, b_value = a.attrs.get(name), b.attrs.get(name)
        if a_value is None or b_value is None:
            return None
        if not _equal(a_value, b_value):
            return None

    return EquivalenceVerdict(
        rel_type=REL_EQUIVALENT,
        direction=DIRECTION_BOTH,
        basis="designation",
        confidence=BASIS_CONFIDENCE["designation"],
        evidence={
            "source": f"standard designation ({left.kind})",
            "designation_a": left.raw,
            "designation_b": right.raw,
            "agreed_on": sorted(shared),
        },
    )


def by_rule(
    a: Candidate, b: Candidate, rules: list[SubstitutionRuleSet]
) -> EquivalenceVerdict | None:
    """Apply the class's substitution rules (§2B source 3)."""
    for rule in rules:
        if rule.class_code != a.class_code:
            continue

        # never_if is absolute: one true condition ends it.
        if any(
            evaluate_condition(condition, a.attrs, b.attrs) is True
            for condition in rule.never_if
        ):
            return None

        base = [evaluate_condition(c, a.attrs, b.attrs) for c in rule.equivalent_if]
        if not base or any(outcome is not True for outcome in base):
            continue

        forward = [evaluate_condition(c, a.attrs, b.attrs) for c in rule.substitutable_if]
        backward = [evaluate_condition(c, b.attrs, a.attrs) for c in rule.substitutable_if]
        b_covers_a = bool(forward) and all(outcome is True for outcome in forward)
        a_covers_b = bool(backward) and all(outcome is True for outcome in backward)

        if b_covers_a and a_covers_b:
            # Each meets the other's requirement: interchangeable both ways.
            rel_type, direction = REL_EQUIVALENT, DIRECTION_BOTH
        elif b_covers_a:
            rel_type, direction = REL_SUPERSEDES, DIRECTION_A_TO_B
        elif a_covers_b:
            rel_type, direction = REL_SUPERSEDES, DIRECTION_B_TO_A
        else:
            continue

        return EquivalenceVerdict(
            rel_type=rel_type,
            direction=direction,
            basis="rule",
            confidence=BASIS_CONFIDENCE["rule"],
            evidence={
                "source": f"substitution rule for {rule.class_code}",
                "equivalent_if": [str(c) for c in rule.equivalent_if],
                "substitutable_if": [str(c) for c in rule.substitutable_if],
                "reading": (
                    "each meets the other's rating"
                    if direction == DIRECTION_BOTH
                    else "the higher-rated item can substitute the lower-rated one"
                ),
            },
        )
    return None


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------


def by_rating(comparison, schema: ClassSchema) -> EquivalenceVerdict | None:
    """A directed substitute the class schema already implies (§2B source 3).

    When two items agree on every identity-critical attribute they state, and
    differ only on a performance attribute the schema marks `higher_ok`, the
    higher-rated one can stand in for the lower. That is a substitution, and
    nobody had to write a rule for it — `classes.yaml` said so when it declared
    the direction.

    §2A computes exactly this and calls it `equivalence_candidate`; until now
    only `_apply_direction` read it, and only to *correct* a verdict some other
    source had already produced. So a 50% technical-grade xylene and a 20% one
    from another manufacturer — same substance, same grade, no crossref, no
    designation to parse, no hand-written rule — produced nothing at all. That
    single gap was 395 of the 560 reachable equivalence pairs the engine missed.
    """
    if not (comparison.equivalence_candidate and comparison.direction):
        return None

    total = len(schema.identity_critical)
    compared = sum(
        1
        for entry in comparison.per_attr
        if entry.role == "identity_critical" and entry.result != "unknown"
    )
    if REQUIRE_FULL_IDENTITY and compared < total:
        return None

    return EquivalenceVerdict(
        rel_type=REL_SUPERSEDES,
        direction=comparison.direction,
        basis="rating",
        confidence=BASIS_CONFIDENCE["rating"],
        evidence={
            "source": "the class schema declares this rating may be exceeded",
            "agreed_on": sorted(comparison.matched_attrs),
            "rating_difference": comparison.vetoed_by,
        },
    )


def evaluate(
    a: Candidate,
    b: Candidate,
    schema: ClassSchema,
    rules: list[SubstitutionRuleSet],
    crossrefs: dict[str, set[str]],
) -> EquivalenceVerdict | None:
    """Decide whether two items are equivalent, and in which direction.

    A §2A veto on an identity-critical attribute ends it: items that are not
    the same kind of thing are not substitutes for each other, however well
    their ratings line up.
    """
    if a.class_code != b.class_code:
        return None

    comparison = compare_attrs(a.attrs, b.attrs, schema)
    identity_blocked = any(
        entry["role"] == "identity_critical" for entry in comparison.vetoed_by
    )

    for source in (by_crossref, by_designation):
        verdict = (
            source(a, b, crossrefs) if source is by_crossref else source(a, b, schema)
        )
        if verdict and not identity_blocked:
            return _apply_direction(verdict, comparison)

    verdict = by_rule(a, b, rules)
    if verdict:
        # A rule may legitimately span an identity_critical difference — a
        # class-600 valve substituting a class-300 one is exactly that — so the
        # veto does not block a rule-based substitution, only an equivalence
        # claim that the two are the same specification.
        if identity_blocked and verdict.rel_type == REL_EQUIVALENT:
            return None
        return verdict

    # Last, and only when identity agrees: the direction the schema itself
    # declares. A rating difference cannot span an identity difference.
    if identity_blocked:
        return None
    return by_rating(comparison, schema)


def _apply_direction(
    verdict: EquivalenceVerdict, comparison
) -> EquivalenceVerdict:
    """Correct a symmetric verdict that the ratings say is actually directed.

    A crossref or a matching designation establishes that two items are the
    same *specification family*; it says nothing about their ratings. Two
    6205 bearings rated 200 kg and 500 kg share a designation but are not
    interchangeable both ways — the higher-rated one substitutes the lower,
    never the reverse. Getting this wrong is the exact failure §2B warns about,
    so direction is settled from the performance comparison whatever source
    produced the verdict.
    """
    if verdict.direction != DIRECTION_BOTH:
        return verdict
    if not (comparison.equivalence_candidate and comparison.direction):
        return verdict

    verdict.rel_type = REL_SUPERSEDES
    verdict.direction = comparison.direction
    verdict.evidence = {
        **verdict.evidence,
        "direction_from": "performance ratings differ beyond tolerance",
        "rating_difference": comparison.vetoed_by,
    }
    return verdict


def build_crossref_index(rows: list[tuple[str, str]]) -> dict[str, set[str]]:
    """Symmetric lookup over the OEM interchange table."""
    from .normalize import normalize_mpn

    index: dict[str, set[str]] = {}
    for mpn_a, mpn_b in rows:
        left, right = normalize_mpn(mpn_a), normalize_mpn(mpn_b)
        if not (left and right):
            continue
        index.setdefault(left, set()).add(right)
        index.setdefault(right, set()).add(left)
    return index
