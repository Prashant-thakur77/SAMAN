"""Pipeline orchestration — normalize -> extract -> (embed -> match -> cluster).

M2 registers the first two stages; M3 appends the rest. Progress is exposed
through `GET /api/pipeline/status` so the UI can show a determinate bar rather
than an indefinite spinner (spec §8A "long-job UX").

State is process-local and deliberately simple: one pipeline run at a time,
which is what a single-laptop prototype needs.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from .extract import extract
from .models import Item, RawItem
from .normalize import normalize_mpn, normalize_row

BATCH = 1000


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
    """Run the registered stages in order, recording progress as we go."""
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
        if result.band != "low" or (result.veto is not None and looks_plausible):
            persist.append(
                {
                    "item_a": result.item_a,
                    "item_b": result.item_b,
                    "tier_scores_json": json.dumps(result.tier_scores, sort_keys=True),
                    "verdict": result.verdict,
                    "band": result.band,
                    "confidence": result.confidence,
                    "veto_json": json.dumps(result.veto, sort_keys=True, default=str)
                    if result.veto
                    else None,
                    "evidence_json": json.dumps(
                        {**result.evidence, "equivalence": result.equivalence},
                        sort_keys=True,
                        default=str,
                    ),
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

    stats = {
        "blocking": {**blocking_stats.as_dict(), **measure_blocking_recall(db, pairs)},
        "linkage": linkage.as_stats() if linkage else {"engine": "rapidfuzz"},
        "bands": bands,
        "verdicts": verdicts,
        "accepted_pairs": len(accepted),
        "persisted_pairs": len(persist),
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

    # Review queue: one task per pair a human still has to decide. The cluster
    # is carried alongside the pair so the workbench's merge-into-cluster view
    # has somewhere to go (§6.5).
    cluster_of = dict(
        db.execute(select(ClusterMember.item_id, ClusterMember.cluster_id)).all()
    )
    tasks = [
        {
            "pair_id": pair_id,
            "cluster_id": cluster_of.get(item_a),
            "band": band,
            "state": "pending",
            "assignee_role": "steward" if verdict != "conflict" else "approver",
            "reason": "specification conflict on an anchor-key match"
            if verdict == "conflict"
            else "confidence in the grey band",
        }
        for pair_id, item_a, band, verdict in db.execute(
            select(Pair.id, Pair.item_a, Pair.band, Pair.verdict).where(
                Pair.verdict.in_(("review", "conflict"))
            )
        ).all()
    ]
    for i in range(0, len(tasks), BATCH):
        db.execute(insert(ReviewTask), tasks[i : i + BATCH])
    db.commit()
