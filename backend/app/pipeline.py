"""Pipeline orchestration — normalize -> extract -> (embed -> match -> cluster).

M2 registers the first two stages; M3 appends the rest. Progress is exposed
through `GET /api/pipeline/status` so the UI can show a determinate bar rather
than an indefinite spinner (spec §8A "long-job UX").

State is process-local and deliberately simple: one pipeline run at a time,
which is what a single-laptop prototype needs.
"""

from __future__ import annotations

import heapq
import json
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import bindparam, func, insert, select, update
from sqlalchemy.orm import Session

from .extract import extract
from .models import Item, RawItem
from .normalize import normalize_mpn, normalize_row

BATCH = 1000

#: How many auto-refused pairs to surface for spot-checking. Every refusal is
#: recorded, but a queue of hundreds of thousands is not a queue.
LOW_BAND_SAMPLE = 500

#: How many refused pairs keep their full evidence. The Auto-low workbench tab
#: samples the LOW_BAND_SAMPLE most confident refusals, so this is ten times the
#: headroom it needs -- and three orders of magnitude less than storing all of
#: them, which is what the demo profile was doing.
LOW_BAND_EVIDENCE_KEPT = 5_000


@dataclass
class PipelineStatus:
    state: str = "idle"  # idle|running|done|error
    stage: str | None = None
    stages_done: list[str] = field(default_factory=list)
    rows_done: int = 0
    rows_total: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None

    @property
    def eta_seconds(self) -> float | None:
        """Linear ETA from observed throughput. Honest about being an estimate."""
        if not self.started_at or self.rows_done <= 0 or self.state != "running":
            return None
        elapsed = time.time() - self.started_at
        rate = self.rows_done / elapsed
        remaining = max(self.rows_total - self.rows_done, 0)
        return round(remaining / rate, 1) if rate > 0 else None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "stage": self.stage,
            "stages_done": list(self.stages_done),
            "rows_done": self.rows_done,
            "rows_total": self.rows_total,
            "percent": round(100 * self.rows_done / self.rows_total, 1)
            if self.rows_total
            else 0.0,
            "eta_seconds": self.eta_seconds,
            "elapsed_seconds": round(time.time() - self.started_at, 1)
            if self.started_at
            else None,
            "error": self.error,
        }


_status = PipelineStatus()
_lock = threading.Lock()


def get_status() -> PipelineStatus:
    return _status


def reset_status() -> None:
    global _status
    with _lock:
        _status = PipelineStatus()



# --------------------------------------------------------------------------
# Stage: normalize + extract
# --------------------------------------------------------------------------


def build_items(
    db: Session,
    raw_item_ids: list[int] | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    """Create an `item` row for every raw row that does not have one.

    Resumable by construction: it only processes raw rows with no item yet, so a
    crashed run restarts where it stopped rather than from zero (spec §8A).
    """
    stmt = select(RawItem.id, RawItem.description, RawItem.uom).outerjoin(
        Item, Item.raw_item_id == RawItem.id
    ).where(Item.id.is_(None))
    if raw_item_ids is not None:
        stmt = stmt.where(RawItem.id.in_(raw_item_ids))

    rows = db.execute(stmt).all()
    created = 0
    buffer: list[dict] = []

    for raw_id, description, uom in rows:
        norm = normalize_row(description or "", uom)
        ex = extract(norm.norm_text)

        attrs = dict(ex.attrs)
        # Kept for §2D attribute fusion, which ranks values by how they were
        # obtained rather than treating every extraction as equally reliable.
        attrs["_sources"] = ex.attr_sources
        if ex.mpn:
            # The readable form; `mpn_norm` is punctuation-stripped for anchoring.
            attrs["_mpn_raw"] = ex.mpn
        if ex.designation:
            attrs["_designation"] = ex.designation
        if ex.conflicts:
            # §2A.1: a parsed designation disagreeing with the free text is a
            # review flag, not something to resolve by silently picking one.
            attrs["_conflicts"] = ex.conflicts

        buffer.append(
            {
                "raw_item_id": raw_id,
                "norm_text": norm.norm_text,
                "norm_hash": norm.norm_hash,
                "lang": norm.lang,
                "class_code": ex.class_code,
                "class_confidence": ex.class_confidence,
                "mpn_norm": normalize_mpn(ex.mpn),
                "gtin": ex.gtin,
                "uom_base": norm.uom_base,
                "pack_qty": norm.pack_qty,
                "attrs_json": json.dumps(attrs, sort_keys=True, default=str),
            }
        )

        if len(buffer) >= BATCH:
            db.execute(insert(Item), buffer)
            db.commit()
            created += len(buffer)
            buffer.clear()
            if on_progress:
                on_progress(created)

    if buffer:
        db.execute(insert(Item), buffer)
        db.commit()
        created += len(buffer)
        if on_progress:
            on_progress(created)

    return created


# --------------------------------------------------------------------------
# Stage registry
# --------------------------------------------------------------------------

#: Stage name -> callable(db, status). M3 appends embed/match/cluster here.
STAGES: dict[str, Callable[[Session, PipelineStatus], None]] = {}


def register_stage(name: str):
    def wrap(fn):
        STAGES[name] = fn
        return fn

    return wrap


@register_stage("normalize+extract")
def _stage_normalize_extract(db: Session, status: PipelineStatus) -> None:
    pending = db.execute(
        select(RawItem.id).outerjoin(Item, Item.raw_item_id == RawItem.id).where(Item.id.is_(None))
    ).scalars().all()
    status.rows_total = len(pending)
    status.rows_done = 0
    build_items(db, pending, on_progress=lambda n: setattr(status, "rows_done", n))


def run_pipeline(db: Session, stages: list[str] | None = None) -> PipelineStatus:
    """Run the registered stages in order, recording progress as we go.

    The claim below is what makes a second concurrent run a no-op rather than a
    corruption: the match stage deletes and rebuilds the pair and cluster
    tables, so two runs interleaving would not be a slow demo but a wrong one.
    """
    status = get_status()
    with _lock:
        if status.state == "running":
            return status
        status.state = "running"
        status.started_at = time.time()
        status.finished_at = None
        status.error = None
        status.stages_done = []

    names = stages if stages is not None else list(STAGES)
    try:
        for name in names:
            fn = STAGES.get(name)
            if fn is None:
                continue
            status.stage = name
            fn(db, status)
            status.stages_done.append(name)
        status.state = "done"
    except Exception as exc:  # a failed run must report, never take the app down
        status.state = "error"
        status.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        status.stage = None
        status.finished_at = time.time()
    return status


# --------------------------------------------------------------------------
# Stage: embed
# --------------------------------------------------------------------------


@register_stage("embed")
def _stage_embed(db: Session, status: PipelineStatus) -> None:
    """Fit the embedder over the whole corpus and persist one vector per item."""
    from sqlalchemy import update

    from .embed import Embedder, pack
    from .models import Item as ItemModel

    rows = db.execute(select(ItemModel.id, ItemModel.norm_text).order_by(ItemModel.id)).all()
    status.rows_total = len(rows)
    status.rows_done = 0
    if not rows:
        return

    result = Embedder().fit_transform([text or "" for _, text in rows])
    status.stage = f"embed ({result.mode})"

    updates = [
        {"id": item_id, "embed_vector": pack(result.vectors[i])}
        for i, (item_id, _) in enumerate(rows)
    ]
    for i in range(0, len(updates), BATCH):
        db.execute(update(ItemModel), updates[i : i + BATCH])
        db.commit()
        status.rows_done = min(i + BATCH, len(updates))
    status.rows_done = len(updates)


# --------------------------------------------------------------------------
# Stage: block + match
# --------------------------------------------------------------------------


def _identity_signature(class_code: str, attrs: dict) -> str | None:
    """Every identity-critical value in schema order, or None if any is missing.

    Missing means missing: a signature built from three attributes out of four
    would collide two items that differ on the fourth, which is the opposite of
    what this key is for.
    """
    from .taxonomy import UNCLASSIFIED, get_schema

    if class_code == UNCLASSIFIED:
        return None
    specs = get_schema(class_code).identity_critical
    if not specs:
        return None
    values = []
    for spec in specs:
        value = attrs.get(spec.name)
        if value is None:
            return None
        values.append(_canonical(value))
    return class_code + "|" + "|".join(values)


def _canonical(value) -> str:
    """One rendering per value, whatever type it arrived as.

    A bore read from "65MM BORE" is the float 65.0; the same bore derived from
    designation 6313 is the int 65. Formatted naively those are "65.0" and
    "65", so the same bearing produced two different signatures and never met
    itself — 172 of the equivalence pairs the pass was built to catch.

    This is the third time numbers-as-strings has cost something in this
    codebase (the fit-class comparison, then Smart-Create's blocking key), which
    is why the canonicalisation is a named function rather than an inline
    `str()` for the next person to get wrong.
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        number = float(value)
        return str(int(number)) if number.is_integer() else repr(round(number, 6))
    text = str(value).strip().upper()
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else repr(round(number, 6))


def _block_value(class_code: str, attrs: dict) -> str | None:
    from .taxonomy import get_schema

    block_on = get_schema(class_code).block_on
    if not block_on:
        return None
    value = attrs.get(block_on)
    return None if value is None else str(value)


@register_stage("match")
def _stage_match(db: Session, status: PipelineStatus) -> None:
    """Generate candidates, score every pair, persist the decisions worth keeping."""
    import numpy as np

    from .blocking import ItemKey, generate_candidates
    from .linkage import run_linkage
    from .match import candidate_from_row, match_pair
    from .metrics import measure_blocking_recall
    from .models import Item as ItemModel
    from .models import MatchRun, Pair, ReviewTask

    rows = db.execute(
        select(
            ItemModel.id,
            ItemModel.class_code,
            ItemModel.class_confidence,
            ItemModel.norm_text,
            ItemModel.norm_hash,
            ItemModel.mpn_norm,
            ItemModel.gtin,
            ItemModel.attrs_json,
            ItemModel.embed_vector,
        ).order_by(ItemModel.id)
    ).all()
    if not rows:
        return

    candidates = {row[0]: candidate_from_row(row) for row in rows}

    keys = [
        ItemKey(
            id=c.id,
            class_code=c.class_code,
            norm_text=c.norm_text,
            norm_hash=c.norm_hash,
            mpn_norm=c.mpn_norm,
            gtin=c.gtin,
            block_value=_block_value(c.class_code, c.attrs),
            identity_signature=_identity_signature(c.class_code, c.attrs),
        )
        for c in candidates.values()
    ]

    ordered_ids = [c.id for c in candidates.values()]
    index_by_id = {item_id: i for i, item_id in enumerate(ordered_ids)}
    first = candidates[ordered_ids[0]].vector
    vectors = (
        np.vstack([candidates[i].vector for i in ordered_ids]) if first is not None else None
    )

    pairs, blocking_stats = generate_candidates(keys, vectors, index_by_id)

    # Tier 1: train the probabilistic model once for the whole run. Returns
    # None when splink is unavailable or fails, in which case every pair falls
    # back to rapidfuzz (spec §0.4).
    status.stage = "match (tier-1 linkage)"
    linkage = run_linkage(db, pairs)
    status.stage = "match"

    status.rows_total = len(pairs)
    status.rows_done = 0

    bands: dict[str, int] = {}
    verdicts: dict[str, int] = {}
    accepted: list[tuple[int, int]] = []
    persist: list[dict] = []
    #: Min-heap of the most confident refusals, so the evidence a reviewer can
    #: actually reach survives while the other 99% is not written at all.
    evidence_kept: list[tuple[float, int, int, str | None, str]] = []
    equivalence_candidates = 0

    for n, (a, b) in enumerate(pairs, start=1):
        result = match_pair(candidates[a], candidates[b], linkage)
        bands[result.band] = bands.get(result.band, 0) + 1
        verdicts[result.verdict] = verdicts.get(result.verdict, 0) + 1
        if result.equivalence:
            equivalence_candidates += 1

        if result.verdict == "duplicate":
            accepted.append((a, b))

        # A vetoed pair is kept even though it was refused: "not a duplicate,
        # bore 25 mm vs 30 mm" is exactly the evidence a reviewer needs. But
        # only when the pair looked plausible in the first place — storing every
        # refused pair in a class would be a million rows for no added insight.
        looks_plausible = result.tier_scores.get("tier1_fuzzy", 0.0) >= 0.80
        if (
            result.band != "low"
            or (result.veto is not None and looks_plausible)
            # An equivalence candidate is refused as a duplicate but is exactly
            # what the §2B engine reads next; dropping it here would leave the
            # relation engine with nothing to evaluate.
            or result.equivalence is not None
        ):
            veto_json = (
                json.dumps(result.veto, sort_keys=True, default=str) if result.veto else None
            )
            evidence_json = json.dumps(
                {**result.evidence, "equivalence": result.equivalence},
                sort_keys=True,
                default=str,
            )

            # A refused pair's row is cheap and the §2B engine reads every one
            # of them; its evidence is ~2.7 KB and only the few hundred most
            # confident refusals are ever surfaced. Storing the rest cost 940 MB
            # on the demo profile alone -- and the same again in RAM here, since
            # this list is held until the inserts run. Keep the rows, keep the
            # evidence for the top slice, and fill it in after the insert.
            keep_evidence = result.band != "low"
            if not keep_evidence:
                heapq.heappush(
                    evidence_kept,
                    (result.confidence, result.item_a, result.item_b, veto_json, evidence_json),
                )
                if len(evidence_kept) > LOW_BAND_EVIDENCE_KEPT:
                    heapq.heappop(evidence_kept)

            persist.append(
                {
                    "item_a": result.item_a,
                    "item_b": result.item_b,
                    "tier_scores_json": json.dumps(result.tier_scores, sort_keys=True),
                    "verdict": result.verdict,
                    "band": result.band,
                    "confidence": result.confidence,
                    "veto_json": veto_json if keep_evidence else None,
                    "evidence_json": evidence_json if keep_evidence else "{}",
                }
            )
        if n % 5000 == 0:
            status.rows_done = n

    status.rows_done = len(pairs)

    # Review tasks reference pairs, so the derived layer goes first.
    db.query(ReviewTask).delete()
    db.query(Pair).delete()
    for i in range(0, len(persist), BATCH):
        db.execute(insert(Pair), persist[i : i + BATCH])
    db.commit()

    # The refusals a reviewer will actually be shown get their evidence back.
    restored = [
        {
            "b_item_a": item_a,
            "b_item_b": item_b,
            "b_veto_json": veto_json,
            "b_evidence_json": evidence_json,
        }
        for _, item_a, item_b, veto_json, evidence_json in evidence_kept
    ]
    for i in range(0, len(restored), BATCH):
        # Core-level, keyed on the natural pair key: the ORM's bulk update
        # wants primary keys we deliberately never read back.
        db.execute(
            update(Pair.__table__)
            .where(
                Pair.__table__.c.item_a == bindparam("b_item_a"),
                Pair.__table__.c.item_b == bindparam("b_item_b"),
            )
            .values(
                veto_json=bindparam("b_veto_json"),
                evidence_json=bindparam("b_evidence_json"),
            ),
            restored[i : i + BATCH],
        )
    db.commit()

    stats = {
        "blocking": {**blocking_stats.as_dict(), **measure_blocking_recall(db, pairs)},
        "linkage": linkage.as_stats() if linkage else {"engine": "rapidfuzz"},
        "bands": bands,
        "verdicts": verdicts,
        "accepted_pairs": len(accepted),
        "persisted_pairs": len(persist),
        "low_band_evidence_kept": len(restored),
        "equivalence_candidates": equivalence_candidates,
        "items": len(candidates),
    }
    db.execute(insert(MatchRun), [{"stats_json": json.dumps(stats, sort_keys=True)}])
    db.commit()


# --------------------------------------------------------------------------
# Stage: cluster + golden drafts
# --------------------------------------------------------------------------


@register_stage("cluster")
def _stage_cluster(db: Session, status: PipelineStatus) -> None:
    """Connected components over accepted pairs, then a golden draft each."""
    from .cluster import build_clusters, refine_clusters
    from .models import (
        Cluster,
        ClusterMember,
        Cnmc,
        GoldenFieldProvenance,
        GoldenRecord,
        Pair,
        PurchaseHistory,
        ReviewTask,
    )
    from .models import (
        Item as ItemModel,
    )
    from .standardize import Member, standardize
    from .taxonomy import get_schema

    rows = db.execute(
        select(ItemModel.id, ItemModel.norm_text, ItemModel.class_code, ItemModel.attrs_json)
    ).all()
    if not rows:
        return

    # §2D rule 2 breaks a tied majority vote by the most recent purchase.
    last_purchase = dict(
        db.execute(
            select(PurchaseHistory.item_id, func.max(PurchaseHistory.po_date)).group_by(
                PurchaseHistory.item_id
            )
        ).all()
    )

    members_by_id = {
        item_id: {
            "id": item_id,
            "norm_text": norm_text or "",
            "class_code": class_code,
            "attrs": json.loads(attrs_json or "{}"),
            "last_purchase": last_purchase.get(item_id),
        }
        for item_id, norm_text, class_code, attrs_json in rows
    }

    # A CNMC, once issued, is immutable — so is the cluster it was issued
    # against. Those clusters are left exactly as they are and their members
    # are held out of re-clustering; everything else is rebuilt from the pair
    # graph. Without this, re-running the pipeline would try to delete golden
    # records that codes already point at.
    frozen_clusters = set(
        db.execute(
            select(GoldenRecord.cluster_id)
            .join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
        ).scalars().all()
    )
    frozen_items = set(
        db.execute(
            select(ClusterMember.item_id).where(
                ClusterMember.cluster_id.in_(frozen_clusters)
            )
        ).scalars().all()
    ) if frozen_clusters else set()

    accepted = [
        (a, b)
        for a, b in db.execute(
            select(Pair.item_a, Pair.item_b).where(Pair.verdict == "duplicate")
        ).all()
        if a not in frozen_items and b not in frozen_items
    ]
    conflicted = {
        item
        for a, b in db.execute(
            select(Pair.item_a, Pair.item_b).where(Pair.verdict == "conflict")
        ).all()
        for item in (a, b)
    }

    rebuildable = [i for i in members_by_id if i not in frozen_items]
    groups = build_clusters(accepted, rebuildable)

    # Transitive closure can chain distinct products together through an
    # intermediate match. Split any cluster that contains a vetoed pair (§2A).
    degree: dict[int, int] = {}
    for a, b in accepted:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    attrs_by_id = {i: m["attrs"] for i, m in members_by_id.items()}
    class_by_id = {i: m["class_code"] for i, m in members_by_id.items()}
    mpn_by_id = dict(db.execute(select(ItemModel.id, ItemModel.mpn_norm)).all())

    refined: list[list[int]] = []
    splits = 0
    for member_ids in groups.values():
        parts = refine_clusters(member_ids, attrs_by_id, class_by_id, mpn_by_id, degree)
        splits += len(parts) - 1
        refined.extend(parts)

    status.rows_total = len(refined)
    status.rows_done = 0

    # Rebuild the derived layer for everything not pinned by an issued code.
    # Order matters: review tasks reference pairs, codes reference goldens.
    db.query(ReviewTask).delete()
    frozen_goldens = (
        set(
            db.execute(
                select(GoldenRecord.id).where(GoldenRecord.cluster_id.in_(frozen_clusters))
            ).scalars().all()
        )
        if frozen_clusters
        else set()
    )
    if frozen_goldens:
        db.query(GoldenFieldProvenance).filter(
            GoldenFieldProvenance.golden_id.notin_(frozen_goldens)
        ).delete(synchronize_session=False)
    else:
        db.query(GoldenFieldProvenance).delete()
    if frozen_clusters:
        db.query(GoldenRecord).filter(
            GoldenRecord.cluster_id.notin_(frozen_clusters)
        ).delete(synchronize_session=False)
        db.query(ClusterMember).filter(
            ClusterMember.cluster_id.notin_(frozen_clusters)
        ).delete(synchronize_session=False)
        db.query(Cluster).filter(Cluster.id.notin_(frozen_clusters)).delete(
            synchronize_session=False
        )
    else:
        db.query(GoldenRecord).delete()
        db.query(ClusterMember).delete()
        db.query(Cluster).delete()
    db.commit()

    for n, member_ids in enumerate(refined, start=1):
        raw_members = [members_by_id[i] for i in member_ids]
        class_code = Counter(m["class_code"] for m in raw_members).most_common(1)[0][0]
        schema = get_schema(class_code)

        members = [
            Member(
                id=m["id"],
                attrs={k: v for k, v in m["attrs"].items() if not k.startswith("_")},
                sources=m["attrs"].get("_sources", {}),
                norm_text=m["norm_text"],
                last_purchase=m["last_purchase"],
            )
            for m in raw_members
        ]
        readable_mpn = Counter(
            m["attrs"].get("_mpn_raw") for m in raw_members if m["attrs"].get("_mpn_raw")
        ).most_common(1)
        result = standardize(members, schema, readable_mpn[0][0] if readable_mpn else None)

        # An anchor-key conflict flagged by the matcher also blocks approval.
        anchor_conflict = any(i in conflicted for i in member_ids)
        record_status = "conflict" if anchor_conflict else result.status

        cluster = Cluster(status=record_status)
        db.add(cluster)
        db.flush()
        db.execute(
            insert(ClusterMember),
            [{"cluster_id": cluster.id, "item_id": i} for i in member_ids],
        )
        golden = GoldenRecord(
            cluster_id=cluster.id,
            std_description=result.std_description,
            attrs_json=json.dumps(result.attrs, sort_keys=True, default=str),
            status=record_status,
        )
        db.add(golden)
        db.flush()
        if result.provenance:
            db.execute(
                insert(GoldenFieldProvenance),
                [
                    {
                        "golden_id": golden.id,
                        "field": fused.field,
                        "source_member_id": fused.source_member_id,
                        "rule": fused.rule,
                    }
                    for fused in result.provenance
                ],
            )
        if n % 500 == 0:
            db.commit()
            status.rows_done = n
    db.commit()
    status.rows_done = len(refined)

    # Review queue. All three §6.5 bands are populated, not just the grey one:
    # an automation rate only means something if a human can sample what was
    # automated. Grey tasks must be decided; high and low tasks are there to be
    # confirmed or overturned.
    cluster_of = dict(
        db.execute(select(ClusterMember.item_id, ClusterMember.cluster_id)).all()
    )

    def _task(pair_id, item_a, band, verdict, role, reason):
        return {
            "pair_id": pair_id,
            "cluster_id": cluster_of.get(item_a),
            "band": band,
            "state": "pending",
            "assignee_role": role,
            "reason": reason,
        }

    tasks = [
        _task(
            pair_id,
            item_a,
            band,
            verdict,
            "approver" if verdict == "conflict" else "steward",
            "specification conflict on an anchor-key match"
            if verdict == "conflict"
            else "confidence in the grey band",
        )
        for pair_id, item_a, band, verdict in db.execute(
            select(Pair.id, Pair.item_a, Pair.band, Pair.verdict).where(
                Pair.verdict.in_(("review", "conflict"))
            )
        ).all()
    ]

    tasks += [
        _task(pair_id, item_a, "high", "duplicate", "approver",
              "confirm an automatic merge")
        for pair_id, item_a in db.execute(
            select(Pair.id, Pair.item_a).where(Pair.band == "high")
        ).all()
    ]

    # The most valuable low-band sample is the pairs that looked most alike and
    # were refused anyway — that is where the veto layer did the work.
    tasks += [
        _task(pair_id, item_a, "low", "distinct", "steward",
              "confirm an automatic refusal: a close match the veto layer declined")
        for pair_id, item_a in db.execute(
            select(Pair.id, Pair.item_a)
            .where(Pair.band == "low", Pair.veto_json.is_not(None))
            .order_by(Pair.confidence.desc(), Pair.id)
            .limit(LOW_BAND_SAMPLE)
        ).all()
    ]
    for i in range(0, len(tasks), BATCH):
        db.execute(insert(ReviewTask), tasks[i : i + BATCH])
    db.commit()


# --------------------------------------------------------------------------
# Stage: directed functional equivalence (§2B)
# --------------------------------------------------------------------------


@register_stage("relations")
def _stage_relations(db: Session, status: PipelineStatus) -> None:
    """Evaluate equivalence over the pairs the matcher refused as duplicates.

    Nothing here merges anything: equivalents keep distinct CNMCs and carry a
    substitution link instead (§2B).
    """
    from .equivalence import Candidate, build_crossref_index, evaluate, parse_rules
    from .models import ClusterMember, Crossref, Pair, Relation, SubstitutionRule
    from .models import Item as ItemModel
    from .taxonomy import get_schema

    rules_by_class: dict[str, list] = {}
    for class_code, rule_yaml in db.execute(
        select(SubstitutionRule.class_code, SubstitutionRule.rule_yaml).where(
            SubstitutionRule.active.is_(True)
        )
    ).all():
        rules_by_class.setdefault(class_code, []).extend(parse_rules(rule_yaml))

    crossrefs = build_crossref_index(
        db.execute(select(Crossref.mpn_a, Crossref.mpn_b)).all()
    )

    items = {
        item_id: Candidate(
            id=item_id,
            class_code=class_code,
            norm_text=norm_text or "",
            mpn_norm=mpn,
            attrs={
                k: v
                for k, v in json.loads(attrs_json or "{}").items()
                if not k.startswith("_")
            },
        )
        for item_id, class_code, norm_text, mpn, attrs_json in db.execute(
            select(
                ItemModel.id,
                ItemModel.class_code,
                ItemModel.norm_text,
                ItemModel.mpn_norm,
                ItemModel.attrs_json,
            )
        ).all()
    }

    # Only pairs the matcher did not accept as duplicates can be equivalents.
    candidate_pairs = db.execute(
        select(Pair.item_a, Pair.item_b).where(Pair.verdict != "duplicate")
    ).all()

    # Two items in one cluster are already one material under one CNMC, so an
    # "interchangeable with" link between them says nothing. This catches the
    # transitive case: a pair the matcher refused can still be merged through a
    # third item, and §2B is explicit that an equivalence is never a merge.
    cluster_of = dict(
        db.execute(select(ClusterMember.item_id, ClusterMember.cluster_id)).all()
    )
    status.rows_total = len(candidate_pairs)
    status.rows_done = 0

    db.query(Relation).delete()
    db.commit()

    rows: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for n, (item_a, item_b) in enumerate(candidate_pairs, start=1):
        a, b = items.get(item_a), items.get(item_b)
        if a is None or b is None:
            continue
        cluster_a = cluster_of.get(item_a)
        if cluster_a is not None and cluster_a == cluster_of.get(item_b):
            continue
        verdict = evaluate(
            a, b, get_schema(a.class_code), rules_by_class.get(a.class_code, []), crossrefs
        )
        if verdict is None:
            continue
        row = verdict.as_row(item_a, item_b)
        key = (row["item_a"], row["item_b"])
        if key in seen:
            continue
        seen.add(key)
        row["evidence_json"] = json.dumps(row["evidence_json"], sort_keys=True, default=str)
        rows.append(row)
        if n % 5000 == 0:
            status.rows_done = n

    for i in range(0, len(rows), BATCH):
        db.execute(insert(Relation), rows[i : i + BATCH])
    db.commit()
    status.rows_done = len(candidate_pairs)
