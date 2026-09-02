"""Smart-Create — duplicate prevention at the point of creation (spec §5).

Every other part of SAMAN cleans up duplicates that already exist. This is the
part that stops them being born: before a buyer creates a new material master,
the description they are typing is run through the same matcher the pipeline
uses, and the existing items it would duplicate come back ranked, with the same
evidence a reviewer would see.

Two design decisions are worth stating.

*The check is the same engine, not a lookalike.* It is tempting to write a
cheap fuzzy search for this screen. Then the search says "no duplicate", the
nightly pipeline says "duplicate", and nobody trusts either. So the probe is
normalized, extracted, embedded and scored by `match.match_pair` exactly as a
catalogue row is -- including the §2A veto layer, which is what stops it
proposing a 30 mm bore bearing as a match for a 25 mm one.

*Overriding is allowed, but it is recorded.* A buyer genuinely may need a new
record the platform thinks is a duplicate. Refusing would get the platform
switched off. So "create new anyway" is a signed token plus a reason, and both
the check and the override land in `smart_create_check`, which is where the
prevented-duplicate counter on the health dashboard comes from.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .blocking import content_tokens
from .compare import values_equal
from .config import get_settings
from .embed import Embedder, cosine, unpack
from .extract import extract
from .match import MatchCandidate, match_pair
from .models import (
    ClusterMember,
    Cnmc,
    Cpse,
    GoldenRecord,
    Item,
    RawItem,
    SmartCreateCheck,
    User,
)
from .normalize import normalize_mpn, normalize_row
from .taxonomy import UNCLASSIFIED, get_schema

#: How many existing items are scored with the full matcher per check. The
#: lexical pre-filter below is cheap; `match_pair` is not, and a buyer waiting
#: on a form field will not tolerate scoring 12,000 rows.
POOL = 80

#: How many suggestions come back. More than a handful is not read.
TOP_N = 5

#: A token stops being accepted after this long, so an override cannot be
#: replayed against a catalogue that has since changed underneath it.
TOKEN_TTL_SECONDS = 900

#: Above this the UI should make "create new anyway" the harder path.
STRONG_MATCH = 0.86

#: How the retrieval pre-filter ranks a class. The vector does most of the
#: work; tokens break its ties; sharing the class's defining attribute is a
#: strong hint that survives heavy rewording.
W_PROBE_VECTOR = 1.0
W_PROBE_TOKENS = 0.3
W_PROBE_BLOCK = 0.5

#: A vetoed pair is only worth showing as "checked and ruled out" if it looked
#: close in the first place. Below this it is just another item in the class.
NEAR_MISS = 0.6
NEAR_MISS_SHOWN = 3


@dataclass
class Suggestion:
    item_id: int
    confidence: float
    band: str
    verdict: str
    description: str
    cpse: str | None
    cnmc: str | None
    class_code: str
    tier_scores: dict
    veto: dict | None
    why: str

    def as_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "confidence": round(self.confidence, 4),
            "band": self.band,
            "verdict": self.verdict,
            "description": self.description,
            "cpse": self.cpse,
            "cnmc": self.cnmc,
            "class_code": self.class_code,
            "tier_scores": self.tier_scores,
            "veto": self.veto,
            "why": self.why,
        }


@dataclass
class Probe:
    """The not-yet-created item, built the way a catalogue row is built."""

    norm_text: str
    norm_hash: str
    class_code: str
    class_confidence: float
    mpn_norm: str | None
    gtin: str | None
    attrs: dict
    uom_base: str | None
    pack_qty: float | None
    vector: np.ndarray | None = field(default=None, repr=False)

    def as_candidate(self) -> MatchCandidate:
        # id 0: the probe has no row yet, and no real item can collide with it.
        return MatchCandidate(
            id=0,
            class_code=self.class_code,
            class_confidence=self.class_confidence,
            norm_text=self.norm_text,
            norm_hash=self.norm_hash,
            mpn_norm=self.mpn_norm,
            gtin=self.gtin,
            attrs=self.attrs,
            vector=self.vector,
        )


# --------------------------------------------------------------------------
# Embedding a probe
# --------------------------------------------------------------------------

#: (corpus signature, fitted embedder). Fitting TF-IDF over the catalogue costs
#: a couple of seconds, which is fine once and not fine per keystroke. The
#: signature is (row count, max id) so an ingest invalidates the cache without
#: anyone having to remember to clear it.
_FITTED: tuple[tuple[int, int], Embedder] | None = None


def _corpus_signature(db: Session) -> tuple[int, int]:
    count, max_id = db.execute(select(func.count(Item.id), func.max(Item.id))).one()
    return (int(count or 0), int(max_id or 0))


def probe_embedder(db: Session) -> Embedder | None:
    """A fitted embedder for scoring probes, or None on an empty catalogue."""
    global _FITTED
    signature = _corpus_signature(db)
    if signature[0] == 0:
        return None
    if _FITTED is not None and _FITTED[0] == signature:
        return _FITTED[1]

    texts = db.execute(select(Item.norm_text).order_by(Item.id)).scalars().all()
    embedder = Embedder()
    embedder.fit_transform([t or "" for t in texts])
    _FITTED = (signature, embedder)
    return embedder


def reset_embedder_cache() -> None:
    global _FITTED
    _FITTED = None


def build_probe(db: Session, description: str, mpn: str | None, uom: str | None) -> Probe:
    """Normalize, extract and embed a description that has no row yet."""
    norm = normalize_row(description or "", uom)
    ex = extract(norm.norm_text)

    attrs = dict(ex.attrs)
    attrs["_sources"] = ex.attr_sources
    if ex.designation:
        attrs["_designation"] = ex.designation

    # An MPN typed into its own field is better evidence than one guessed out
    # of free text, so it wins.
    mpn_norm = normalize_mpn(mpn) or normalize_mpn(ex.mpn)

    probe = Probe(
        norm_text=norm.norm_text,
        norm_hash=norm.norm_hash,
        class_code=ex.class_code,
        class_confidence=ex.class_confidence,
        mpn_norm=mpn_norm,
        gtin=ex.gtin,
        attrs=attrs,
        uom_base=norm.uom_base,
        pack_qty=norm.pack_qty,
    )

    embedder = probe_embedder(db)
    if embedder is not None:
        try:
            probe.vector = embedder.transform([probe.norm_text])[0]
        except Exception:
            # A probe without a vector still matches on anchors, text and
            # attributes; a form field that 500s because sklearn is unhappy is
            # worse than one that scores slightly lower (§9).
            probe.vector = None
    return probe


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------


def _pool(db: Session, probe: Probe) -> list[MatchCandidate]:
    """Existing items worth scoring against this probe.

    Anchors first -- an identical MPN, GTIN or normalized text is not a ranking
    question -- then the probe's own class, ranked the way blocking pass 5 ranks
    it: by cosine against the probe's embedding. Lexical overlap alone is not
    enough here. Ranking 1,500 bearings by shared tokens buries the SKF 6205
    under every other 6205 in the catalogue, because they share the same words;
    what separates them is the vector and the attributes, in that order.
    """
    columns = (
        Item.id, Item.class_code, Item.class_confidence, Item.norm_text, Item.norm_hash,
        Item.mpn_norm, Item.gtin, Item.attrs_json, Item.embed_vector,
    )

    anchored: dict[int, tuple] = {}
    clauses = [Item.norm_hash == probe.norm_hash]
    if probe.mpn_norm:
        clauses.append(Item.mpn_norm == probe.mpn_norm)
    if probe.gtin:
        clauses.append(Item.gtin == probe.gtin)
    for clause in clauses:
        for row in db.execute(select(*columns).where(clause).limit(POOL)).all():
            anchored[row[0]] = row

    ranked: list[tuple] = []
    if probe.class_code != UNCLASSIFIED:
        probe_tokens = content_tokens(probe.norm_text)
        block_on = get_schema(probe.class_code).block_on
        block_value = probe.attrs.get(block_on) if block_on else None

        rows = db.execute(select(*columns).where(Item.class_code == probe.class_code)).all()
        scored: list[tuple[float, tuple]] = []
        for row in rows:
            if row[0] in anchored:
                continue
            score = 0.0
            if probe.vector is not None:
                score += W_PROBE_VECTOR * cosine(probe.vector, unpack(row[8]))
            tokens = content_tokens(row[3] or "")
            if tokens and probe_tokens:
                score += W_PROBE_TOKENS * (
                    len(probe_tokens & tokens) / len(probe_tokens | tokens)
                )
            if block_value is not None:
                # Sharing the class's defining attribute (a bearing's bore, a
                # valve's size) is worth more than sharing three stopwords.
                attrs = json.loads(row[7] or "{}")
                if _same_value(attrs.get(block_on), block_value):
                    score += W_PROBE_BLOCK
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        ranked = [row for _, row in scored[:POOL]]

    return [_candidate(row) for row in list(anchored.values()) + ranked]


def _same_value(a, b) -> bool:
    """Numerically first, textually after -- see `compare.values_equal`.

    A bore read from "25MM BORE" is 25.0 and one derived from designation 6005
    is 25. As strings those differ, which silently cost the retrieval boost and
    dropped the FAG record written in another CPSE's house style out of the
    candidate pool entirely. A missing value matches nothing here, unlike in the
    attribute comparator: an absent bore is not a reason to retrieve a row.
    """
    if a is None or b is None:
        return False
    return values_equal(a, b)


def _candidate(row) -> MatchCandidate:
    return MatchCandidate(
        id=row[0],
        class_code=row[1],
        class_confidence=row[2] or 0.0,
        norm_text=row[3] or "",
        norm_hash=row[4] or "",
        mpn_norm=row[5],
        gtin=row[6],
        attrs=json.loads(row[7] or "{}"),
        vector=unpack(row[8]),
    )


def _describe(result, other: MatchCandidate) -> str:
    """One line a buyer can act on, not a score dump."""
    key = result.tier_scores.get("tier0_key")
    if key == "mpn":
        return f"Same manufacturer part number ({other.mpn_norm})."
    if key == "gtin":
        return f"Same barcode ({other.gtin})."
    if key == "text":
        return "Identical description once normalized."
    if result.veto:
        return _veto_reason(result.veto)
    if result.verdict == "duplicate":
        return "Same specification on every attribute compared."
    return "Similar wording; the attributes do not fully confirm it."


# --------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------


def check(
    db: Session,
    description: str,
    mpn: str | None = None,
    uom: str | None = None,
    user: User | None = None,
    limit: int = TOP_N,
) -> dict:
    """Rank the existing items a new description would duplicate.

    Three lists come back, because a buyer needs three different answers:

    * ``suggestions`` -- this material already exists; reuse it.
    * ``equivalents`` -- a different manufacturer's interchangeable part exists.
      Not a duplicate, and merging them would erase a real distinction (§2B),
      but a buyer about to raise a new code should still see it.
    * ``ruled_out`` -- items that looked close and were refused by the veto
      layer, with the attribute that refused them. This is the most persuasive
      output on the screen: it shows the check is reading specifications rather
      than matching strings.
    """
    if not (description or "").strip():
        raise ValueError("a description is required")

    probe = build_probe(db, description, mpn, uom)
    suggestions: list[Suggestion] = []
    equivalents: list[Suggestion] = []
    ruled_out: list[Suggestion] = []

    for other in _pool(db, probe):
        result = match_pair(probe.as_candidate(), other)
        suggestion = Suggestion(
            item_id=other.id,
            confidence=result.confidence,
            band=result.band,
            verdict=result.verdict,
            description="",
            cpse=None,
            cnmc=None,
            class_code=other.class_code,
            tier_scores=result.tier_scores,
            veto=result.veto,
            why=_describe(result, other),
        )
        if result.verdict in ("duplicate", "review", "conflict"):
            suggestions.append(suggestion)
        elif result.equivalence:
            suggestion.why = _equivalence_reason(result)
            equivalents.append(suggestion)
        elif result.veto and _similarity(result) >= NEAR_MISS:
            ruled_out.append(suggestion)

    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    equivalents.sort(key=lambda s: _text_score(s), reverse=True)
    ruled_out.sort(key=lambda s: _text_score(s), reverse=True)

    suggestions = suggestions[:limit]
    equivalents = equivalents[:limit]
    ruled_out = ruled_out[:NEAR_MISS_SHOWN]
    _decorate(db, suggestions + equivalents + ruled_out)

    top = suggestions[0].confidence if suggestions else 0.0
    duplicates = [s for s in suggestions if s.verdict == "duplicate"]
    record = SmartCreateCheck(
        user_id=user.id if user else None,
        cpse_id=user.cpse_id if user and user.cpse_id else None,
        description=description,
        norm_text=probe.norm_text,
        class_code=probe.class_code,
        top_confidence=round(top, 4),
        candidates=len(suggestions),
        outcome="open",
    )
    db.add(record)
    db.commit()

    return {
        "check_id": record.id,
        "probe": {
            "norm_text": probe.norm_text,
            "class_code": probe.class_code,
            "class_confidence": round(probe.class_confidence, 3),
            "mpn_norm": probe.mpn_norm,
            "gtin": probe.gtin,
            "uom_base": probe.uom_base,
            "pack_qty": probe.pack_qty,
            "attrs": {k: v for k, v in probe.attrs.items() if not k.startswith("_")},
        },
        "suggestions": [s.as_dict() for s in suggestions],
        "equivalents": [s.as_dict() for s in equivalents],
        "ruled_out": [s.as_dict() for s in ruled_out],
        "recommendation": _recommendation(duplicates, top),
        "create_token": mint_token(record.id, probe.norm_hash),
        "token_expires_in": TOKEN_TTL_SECONDS,
    }


def _veto_reason(veto: dict) -> str:
    """Name the attribute that refused the match, with both values.

    "Close, but something differs" is not worth printing. "Close, but the bore
    is 30 mm, not 25 mm" is the sentence that makes a buyer stop.
    """
    blocking = [c for c in veto.get("vetoed_by") or [] if c.get("attr")]
    if not blocking:
        blocking = [
            c for c in veto.get("per_attr") or []
            if c.get("result") == "conflict" and c.get("role") == "identity_critical"
        ]
    if not blocking:
        return "Close, but a defining specification differs. This is a different item."
    first = blocking[0]
    label = str(first.get("attr", "")).replace("_", " ")
    a, b = first.get("a"), first.get("b")
    if a is not None and b is not None:
        return f"Close, but {label} is {b}, not {a}. This is a different item."
    return f"Close, but {label} differs. This is a different item."


def _similarity(result) -> float:
    """Text-and-vector similarity, ignoring the attribute verdict."""
    return max(
        result.tier_scores.get("tier1_fuzzy", 0.0),
        result.tier_scores.get("tier2_semantic", 0.0),
    )


def _text_score(suggestion: Suggestion) -> float:
    return max(
        suggestion.tier_scores.get("tier1_fuzzy", 0.0),
        suggestion.tier_scores.get("tier2_semantic", 0.0),
    )


def _equivalence_reason(result) -> str:
    reasons = (result.equivalence or {}).get("reason") or []
    first = reasons[0] if reasons else {}
    if result.equivalence.get("basis") == "crossref":
        return f"Interchangeable part from a different manufacturer ({first.get('b', '')})."
    direction = result.equivalence.get("direction")
    if direction and direction != "bidirectional":
        return "A higher-rated item that can substitute for this one."
    return "Technically equivalent, but a separate manufacturer's record."


def _recommendation(duplicates: list[Suggestion], top: float) -> dict:
    if duplicates and top >= STRONG_MATCH:
        return {
            "action": "reuse",
            "reason": "An existing material already covers this specification.",
            "override_requires_reason": True,
        }
    if duplicates:
        return {
            "action": "review",
            "reason": "A possible match needs a human decision before a new code is created.",
            "override_requires_reason": True,
        }
    return {
        "action": "create",
        "reason": "Nothing in the national catalogue matches this specification.",
        "override_requires_reason": False,
    }


def _decorate(db: Session, suggestions: list[Suggestion]) -> None:
    """Fill in the human-facing fields for the shortlist only."""
    if not suggestions:
        return
    ids = [s.item_id for s in suggestions]
    rows = db.execute(
        select(Item.id, RawItem.description, Cpse.code, Cnmc.code)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id, isouter=True)
        .join(ClusterMember, ClusterMember.item_id == Item.id, isouter=True)
        .join(GoldenRecord, GoldenRecord.cluster_id == ClusterMember.cluster_id, isouter=True)
        .join(Cnmc, Cnmc.golden_id == GoldenRecord.id, isouter=True)
        .where(Item.id.in_(ids))
    ).all()
    by_id = {row[0]: row for row in rows}
    for suggestion in suggestions:
        row = by_id.get(suggestion.item_id)
        if row:
            suggestion.description = row[1] or ""
            suggestion.cpse = row[2]
            suggestion.cnmc = row[3]


# --------------------------------------------------------------------------
# The "create new anyway" token
# --------------------------------------------------------------------------


def _sign(payload: str) -> str:
    key = get_settings().saman_secret_key.encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]


def mint_token(check_id: int, norm_hash: str) -> str:
    """Bind an override to one check, one description and one time window."""
    payload = f"{check_id}.{norm_hash}.{int(time.time())}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str, norm_hash: str | None = None) -> int:
    """Return the check id, or raise ValueError saying what is wrong."""
    parts = (token or "").split(".")
    if len(parts) != 4:
        raise ValueError("malformed token")
    payload, signature = ".".join(parts[:3]), parts[3]
    if not hmac.compare_digest(_sign(payload), signature):
        raise ValueError("token signature does not match")
    check_id, token_hash, issued = int(parts[0]), parts[1], int(parts[2])
    if time.time() - issued > TOKEN_TTL_SECONDS:
        raise ValueError("token expired; run the check again")
    if norm_hash is not None and token_hash != norm_hash:
        raise ValueError("the description changed after the check")
    return check_id


# --------------------------------------------------------------------------
# Outcomes
# --------------------------------------------------------------------------


def _load(db: Session, check_id: int) -> SmartCreateCheck:
    record = db.get(SmartCreateCheck, check_id)
    if record is None:
        raise ValueError("unknown check")
    if record.outcome != "open":
        raise ValueError(f"this check was already resolved as {record.outcome}")
    return record


def reuse(db: Session, check_id: int, item_id: int, user: User | None = None) -> dict:
    """The buyer took an existing material. This is a prevented duplicate."""
    record = _load(db, check_id)
    if db.get(Item, item_id) is None:
        raise ValueError("unknown item")
    record.outcome = "prevented"
    record.reused_item_id = item_id
    audit.record(
        db,
        action="smart_create.prevented",
        entity=f"item:{item_id}",
        payload={"check_id": check_id, "top_confidence": record.top_confidence},
        user=user.email if user else "system",
        commit=False,
    )
    db.commit()
    return {"check_id": check_id, "outcome": "prevented", "reused_item_id": item_id}


def create_anyway(
    db: Session,
    token: str,
    legacy_code: str,
    description: str,
    uom: str | None = None,
    reason: str | None = None,
    user: User | None = None,
) -> dict:
    """Create the material the buyer asked for, and record that they were told.

    The new row enters the catalogue as an ordinary raw item, so the next
    pipeline run will cluster it like any other. Nothing here is special-cased
    out of the matcher -- an override is a business decision, not an exemption.
    """
    norm = normalize_row(description or "", uom)
    check_id = verify_token(token, norm.norm_hash)
    record = _load(db, check_id)

    if record.top_confidence >= STRONG_MATCH and not (reason or "").strip():
        raise ValueError("a reason is required to override a strong match")
    if user is None or user.cpse_id is None:
        raise ValueError("only a user attached to a CPSE can create a material")

    exists = db.execute(
        select(RawItem.id).where(
            RawItem.cpse_id == user.cpse_id, RawItem.legacy_code == legacy_code
        )
    ).scalar()
    if exists:
        raise ValueError(f"{legacy_code} already exists in this catalogue")

    raw = RawItem(
        cpse_id=user.cpse_id,
        legacy_code=legacy_code,
        description=description,
        uom=uom,
    )
    db.add(raw)
    db.flush()

    record.outcome = "created_anyway"
    record.created_raw_item_id = raw.id
    record.override_reason = (reason or "").strip() or None
    audit.record(
        db,
        action="smart_create.created_anyway",
        entity=f"raw_item:{raw.id}",
        payload={
            "check_id": check_id,
            "top_confidence": record.top_confidence,
            "reason": record.override_reason,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return {
        "check_id": check_id,
        "outcome": "created_anyway",
        "raw_item_id": raw.id,
        "legacy_code": legacy_code,
        "note": "Queued for the next pipeline run; it will be matched like any other row.",
    }


def stats(db: Session) -> dict:
    """The prevented-duplicate counter for the health dashboard (§5)."""
    rows = db.execute(
        select(SmartCreateCheck.outcome, func.count(SmartCreateCheck.id)).group_by(
            SmartCreateCheck.outcome
        )
    ).all()
    counts = {outcome: int(n) for outcome, n in rows}
    prevented = counts.get("prevented", 0)
    created = counts.get("created_anyway", 0)
    decided = prevented + created
    return {
        "checks": sum(counts.values()),
        "prevented": prevented,
        "created_anyway": created,
        "open": counts.get("open", 0),
        "prevention_rate": round(prevented / decided, 4) if decided else None,
        "note": (
            "A prevented duplicate is a check where the requester reused an existing "
            "material instead of creating a new code. Overrides are counted too, with "
            "the reason given."
        ),
    }
