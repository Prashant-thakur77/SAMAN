"""Review queues, decisions and the audit ledger — spec §5, §6.5, §6.10."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from .. import audit, inventory, learn, opportunity, review, substitutes
from ..adjudicate import adjudicate
from ..auth import current_user_optional, require_roles, require_user
from ..config import get_settings
from ..db import get_db
from ..models import (
    AuditEvent,
    Cluster,
    ClusterMember,
    Cnmc,
    Cpse,
    Decision,
    GoldenRecord,
    Item,
    Pair,
    RawItem,
    Relation,
    ReviewTask,
    User,
)
from ..taxonomy import get_schema
from ..visibility import scope_for

router = APIRouter(tags=["review"])

BANDS = ("high", "grey", "low")


class DecisionIn(BaseModel):
    task_id: int
    action: str  # approve | reject | merge | split
    note: str | None = None
    #: for merge/split, the cluster and item the reviewer acted on
    cluster_id: int | None = None
    item_id: int | None = None
    #: how long the card was on screen, for the seconds-per-decision figure
    seconds: float | None = None


class BulkDecisionIn(BaseModel):
    task_ids: list[int]
    action: str  # approve | reject
    note: str | None = None


def _item_card(db: Session, item_id: int) -> dict:
    row = db.execute(
        select(
            Item.id,
            Item.norm_text,
            Item.class_code,
            Item.class_confidence,
            Item.mpn_norm,
            Item.gtin,
            Item.attrs_json,
            Item.pack_qty,
            Item.uom_base,
            RawItem.legacy_code,
            RawItem.description,
            RawItem.plant,
            Cpse.code,
        )
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .where(Item.id == item_id)
    ).first()
    if row is None:
        return {"item_id": item_id}
    attrs = json.loads(row[6] or "{}")
    cluster_id = db.execute(
        select(ClusterMember.cluster_id).where(ClusterMember.item_id == item_id)
    ).scalar_one_or_none()
    return {
        "item_id": row[0],
        "normalized": row[1],
        "class_code": row[2],
        "class_confidence": row[3],
        "class_uncertain": row[2] == "unclassified",
        "mpn_norm": row[4],
        "gtin": row[5],
        "pack_qty": row[7],
        "uom_base": row[8],
        "legacy_code": row[9],
        "description": row[10],
        "plant": row[11],
        "cpse": row[12],
        "cluster_id": cluster_id,
        "attrs": {k: v for k, v in attrs.items() if not k.startswith("_")},
    }


def _task_card(db: Session, task: ReviewTask, rephrase: bool = True) -> dict:
    """One workbench card: two items, their diff, the tier strip, the veto."""
    pair = db.get(Pair, task.pair_id) if task.pair_id else None
    card: dict = {
        "task_id": task.id,
        "band": task.band,
        "state": task.state,
        "assignee_role": task.assignee_role,
        "reason": task.reason,
        "cluster_id": task.cluster_id,
    }
    if pair is None:
        return card

    left = _item_card(db, pair.item_a)
    right = _item_card(db, pair.item_b)
    veto = json.loads(pair.veto_json) if pair.veto_json else None
    evidence = json.loads(pair.evidence_json or "{}")

    # Attribute diff, so the card can render agreement plainly and disagreement
    # marked, rather than making the reviewer compare two lists by eye.
    attributes = evidence.get("attributes", {})
    diff = [
        {
            "attr": entry["attr"],
            "role": entry["role"],
            "a": entry["a"],
            "b": entry["b"],
            "result": entry["result"],
            "detail": entry["detail"],
            "agrees": entry["result"] in ("match", "in_band"),
        }
        for entry in attributes.get("per_attr", [])
    ]

    tier_scores = json.loads(pair.tier_scores_json or "{}")
    # Tier 3 (§0.4): a recommendation with its reasons, so the reviewer starts
    # from a position rather than from a score. It never decides. The grey
    # band may have the model rephrase it; every band gets the deterministic
    # sentence as `why`, the one-line answer to "why is this card here".
    adjudication = adjudicate(
        evidence,
        tier_scores,
        pair.confidence,
        pair.verdict,
        veto,
        # Fifty cards times one model call is a page that never loads. The
        # first card is the one on screen; the rest read the deterministic
        # sentence, which says the same thing.
        rephrase=rephrase and task.band == "grey",
    )

    card.update(
        {
            "pair_id": pair.id,
            "verdict": pair.verdict,
            "why": adjudication.summary,
            "confidence": pair.confidence,
            "tier_scores": tier_scores,
            "veto": veto,
            "refused_because": (
                [f"{v['attr']}: {v['reason']}" for v in veto["vetoed_by"]] if veto else []
            ),
            "equivalence": evidence.get("equivalence"),
            "route": evidence.get("route"),
            "conflict": evidence.get("conflict"),
            "attribute_diff": diff,
            "agreement": attributes.get("agreement"),
            "items": [left, right],
            # The learned model's opinion, beside the pipeline's. It never
            # decides; it is here so a reviewer can see when the two disagree.
            "learned": learn.score(pair, db=db),
            "adjudication": adjudication.as_dict() if task.band == "grey" else None,
        }
    )
    return card


def _facets(db: Session, band: str | None, state: str) -> dict:
    """What the band holds, by class and by CPSE, so the filters offer only
    values that exist. Both sides of a pair count for the CPSE facet: a
    steward at BHEL wants every pair that touches BHEL."""
    A, B = aliased(Item), aliased(Item)
    RA, RB = aliased(RawItem), aliased(RawItem)
    query = (
        select(A.class_code, RA.cpse_id, RB.cpse_id)
        .select_from(ReviewTask)
        .join(Pair, Pair.id == ReviewTask.pair_id)
        .join(A, A.id == Pair.item_a)
        .join(B, B.id == Pair.item_b)
        .join(RA, RA.id == A.raw_item_id)
        .join(RB, RB.id == B.raw_item_id)
        .where(ReviewTask.state == state)
    )
    if band:
        query = query.where(ReviewTask.band == band)
    classes: dict[str, int] = {}
    cpses: dict[int, int] = {}
    for class_code, cpse_a, cpse_b in db.execute(query):
        classes[class_code] = classes.get(class_code, 0) + 1
        for cpse_id in {cpse_a, cpse_b}:
            cpses[cpse_id] = cpses.get(cpse_id, 0) + 1
    names = dict(db.execute(select(Cpse.id, Cpse.code)).all()) if cpses else {}
    return {
        "classes": [
            {"code": code, "count": n}
            for code, n in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "cpses": [
            {"id": cpse_id, "code": names.get(cpse_id, str(cpse_id)), "count": n}
            for cpse_id, n in sorted(cpses.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


@router.get("/queues/counts")
def queue_counts(db: Session = Depends(get_db)) -> dict:
    """Just the pending count per band: what the Home page needs, without a
    page of cards, facets and adjudications behind it. One query."""
    counts = dict(
        db.execute(
            select(ReviewTask.band, func.count(ReviewTask.id))
            .where(ReviewTask.state == "pending")
            .group_by(ReviewTask.band)
        ).all()
    )
    return {"counts": {band: counts.get(band, 0) for band in BANDS}, "total": sum(counts.values())}


@router.get("/queues")
def queues(
    band: str | None = Query(default=None),
    state: str = Query(default="pending"),
    limit: int = Query(default=25, le=200),
    offset: int = 0,
    order: str = Query(default="id"),
    klass: str | None = Query(default=None, alias="class"),
    cpse: int | None = Query(default=None),
    mine: bool = Query(default=False),
    user: Annotated[User | None, Depends(current_user_optional)] = None,
    db: Session = Depends(get_db),
) -> dict:
    """The three band queues with their counts, and a page of cards (§6.5).

    `order=uncertainty` puts the pairs the learned model is least sure about
    first, so a reviewer's time teaches it the most. It needs a trained model;
    without one the queue stays in id order and says so.

    Queues are worked by family: `class` keeps one class, `cpse` keeps the
    pairs that touch one CPSE on either side, `mine` keeps the tasks assigned
    to the caller's role. The facets say what values exist in the band.
    """
    if order not in ("id", "uncertainty"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "order must be 'id' or 'uncertainty'."
        )
    if band is not None and band not in BANDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown band {band!r}; expected one of {', '.join(BANDS)}.",
        )

    counts = dict(
        db.execute(
            select(ReviewTask.band, func.count(ReviewTask.id))
            .where(ReviewTask.state == "pending")
            .group_by(ReviewTask.band)
        ).all()
    )

    query = select(ReviewTask).where(ReviewTask.state == state)
    if band:
        query = query.where(ReviewTask.band == band)
    if mine and user is not None:
        query = query.where(ReviewTask.assignee_role == user.role)
    if klass or cpse:
        A, B = aliased(Item), aliased(Item)
        RA, RB = aliased(RawItem), aliased(RawItem)
        filtered = (
            select(ReviewTask.id)
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .join(A, A.id == Pair.item_a)
            .join(B, B.id == Pair.item_b)
        )
        if klass:
            filtered = filtered.where(or_(A.class_code == klass, B.class_code == klass))
        if cpse:
            filtered = (
                filtered.join(RA, RA.id == A.raw_item_id)
                .join(RB, RB.id == B.raw_item_id)
                .where(or_(RA.cpse_id == cpse, RB.cpse_id == cpse))
            )
        query = query.where(ReviewTask.id.in_(filtered))
    model = learn.load_model()
    if order == "uncertainty" and model is not None:
        # Score every pending task in the band, then page the sorted list.
        # A few thousand pairs of stored JSON; measured in tens of milliseconds.
        scored = []
        rows = db.execute(
            select(ReviewTask, Pair)
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .where(query.whereclause)
        ).all()
        # The items' few fields the features read, in one query for the band.
        facts = learn.item_facts(db, {p.item_a for _, p in rows} | {p.item_b for _, p in rows})
        for task, pair in rows:
            opinion = learn.score(pair, model, facts=facts)
            scored.append((opinion["uncertainty"] if opinion else -1.0, task.id, task))
        scored.sort(key=lambda row: (-row[0], row[1]))
        tasks, picked_for = _mixed_page(scored, offset, limit, seed=f"{band}:{state}")
    else:
        order = "id"
        tasks = (
            db.execute(query.order_by(ReviewTask.id).offset(offset).limit(limit)).scalars().all()
        )
        picked_for = {}
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar()

    return {
        "band": band,
        "state": state,
        "counts": {b: counts.get(b, 0) for b in BANDS},
        "total": total,
        "offset": offset,
        "order": order,
        "filters": {"class": klass, "cpse": cpse, "mine": mine},
        "facets": _facets(db, band, state),
        "model_available": model is not None,
        "undo_window_s": get_settings().saman_undo_window_s,
        "mix": (
            {
                "uncertain": sum(1 for v in picked_for.values() if v == "uncertain"),
                "random": sum(1 for v in picked_for.values() if v == "random"),
                "share": RANDOM_SHARE,
            }
            if order == "uncertainty"
            else None
        ),
        "tasks": [
            {**_task_card(db, task, rephrase=i == 0), "picked_for": picked_for.get(task.id)}
            for i, task in enumerate(tasks)
        ],
    }


#: In the uncertainty order, this share of each page is drawn at random from
#: the rest of the queue. Uncertainty sampling alone keeps showing the model
#: the pairs it already finds hard and never the ones it is confidently wrong
#: about; a few random cards sample those blind spots, and a reviewer sees
#: which cards are which.
RANDOM_SHARE = 0.2


def _mixed_page(scored: list, offset: int, limit: int, seed: str) -> tuple[list, dict]:
    """A page of the uncertainty order with a random fifth mixed in.

    The random picks come from beyond the page's own slice and are seeded by
    the page, so reloading the same page shows the same cards. A queue that
    fits in one page has nothing beyond it and gets no random picks.
    """
    import random

    k = int(limit * RANDOM_SHARE) if len(scored) > offset + limit else 0
    top = scored[offset : offset + limit - k]
    pool = scored[offset + limit - k :]
    picks = random.Random(f"{seed}:{offset}:{len(scored)}").sample(pool, min(k, len(pool)))
    picked_for = {task.id: "uncertain" for _, _, task in top}
    picked_for.update({task.id: "random" for _, _, task in picks})
    return [task for _, _, task in top] + [task for _, _, task in picks], picked_for


@router.post("/decisions")
def create_decision(
    body: DecisionIn,
    user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """Close a review task (§5). Role-gated, audited, and idempotent-safe."""
    task = db.get(ReviewTask, body.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No review task {body.task_id}.")

    if body.action == "split":
        review.authorize(task, db.get(Pair, task.pair_id) if task.pair_id else None, user)
        if body.cluster_id is None or body.item_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A split needs both cluster_id and item_id.",
            )
        new_cluster = review.split_member(db, body.cluster_id, body.item_id, user, body.note)
        task.state = "done"
        db.add(Decision(task_id=task.id, user_id=user.id, action="split", note=body.note))
        db.commit()
        return {"task_id": task.id, "action": "split", "new_cluster_id": new_cluster}

    return review.apply_decision(db, task, body.action, user, body.note, body.seconds)


@router.post("/decisions/bulk")
def create_decisions(
    body: BulkDecisionIn,
    user: Annotated[User, Depends(require_roles(*review.BAND_ROLES["high"]))],
    db: Session = Depends(get_db),
) -> dict:
    """Close a page of tasks with one reason (§5): the high band's policy
    confirmations, which nobody should do one card at a time. Each task keeps
    its own audit event, label and undo; the ones that cannot be closed are
    reported, not fatal."""
    if body.action not in ("approve", "reject"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Bulk decisions are approve or reject."
        )
    if not body.task_ids or len(body.task_ids) > 200:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Send between 1 and 200 task ids."
        )
    task_ids = list(dict.fromkeys(body.task_ids))
    return review.apply_decisions(db, task_ids, body.action, user, body.note)


@router.post("/decisions/{decision_id}/undo")
def undo_decision(
    decision_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """Take a decision back within the undo window (`SAMAN_UNDO_WINDOW_S`)."""
    decision = db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No decision {decision_id}; it may already have been undone.",
        )
    return review.undo_decision(db, decision, user)


class ClusterEditIn(BaseModel):
    std_description: str


@router.post("/clusters/{cluster_id}/golden")
def edit_golden(
    cluster_id: int,
    body: ClusterEditIn,
    user: Annotated[User, Depends(require_roles("steward", "approver", "registrar", "admin"))],
    db: Session = Depends(get_db),
) -> dict:
    """Edit the proposed description before approval (§6.6).

    Editing makes the editor its proposer, which is what the separation-of-duties
    check reads at approval time (§0.9).
    """
    golden = db.execute(
        select(GoldenRecord).where(GoldenRecord.cluster_id == cluster_id)
    ).scalar_one_or_none()
    if golden is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No golden record for cluster {cluster_id}."
        )
    if golden.status == "approved":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An approved golden record can no longer be edited."
        )
    review.guard_mutable(db, cluster_id)

    before = golden.std_description
    golden.std_description = body.std_description.strip()
    golden.proposed_by = user.id
    audit.record(
        db,
        action="golden.edit",
        entity=f"golden_record:{golden.id}",
        payload={"cluster_id": cluster_id, "before": before, "after": golden.std_description},
        user=user.email,
        commit=False,
    )
    db.commit()
    return {"cluster_id": cluster_id, "std_description": golden.std_description}


class MergeIn(BaseModel):
    source_cluster_id: int
    note: str | None = None


@router.post("/clusters/{cluster_id}/merge")
def merge_into(
    cluster_id: int,
    body: MergeIn,
    user: Annotated[User, Depends(require_roles("steward", "approver", "registrar", "admin"))],
    db: Session = Depends(get_db),
) -> dict:
    """Merge another cluster into this one (§6.6)."""
    target = review.merge_clusters(db, body.source_cluster_id, cluster_id, user, body.note)
    return {"cluster_id": target, "merged_from": body.source_cluster_id}


class SplitIn(BaseModel):
    item_id: int
    note: str | None = None


@router.post("/clusters/{cluster_id}/split")
def split_out(
    cluster_id: int,
    body: SplitIn,
    user: Annotated[User, Depends(require_roles("steward", "approver", "registrar", "admin"))],
    db: Session = Depends(get_db),
) -> dict:
    """Remove a member from this cluster into one of its own (§6.6)."""
    new_cluster = review.split_member(db, cluster_id, body.item_id, user, body.note)
    return {"cluster_id": cluster_id, "new_cluster_id": new_cluster}


# --------------------------------------------------------------------------
# Audit ledger (§6.10)
# --------------------------------------------------------------------------


@router.get("/audit")
def audit_stream(
    entity: str | None = None,
    user: str | None = None,
    action: str | None = None,
    exclude: str | None = Query(
        default=None,
        description="comma-separated action prefixes to leave out, e.g. auth.",
    ),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    query = select(AuditEvent)
    if entity:
        query = query.where(AuditEvent.entity.like(f"{entity}%"))
    if user:
        query = query.where(AuditEvent.user == user)
    if action:
        query = query.where(AuditEvent.action.like(f"{action}%"))
    # Sign-ins are on the ledger for the record and would otherwise be the
    # whole first page; the reader hides them with `exclude=auth.` and the
    # chain, hashes included, is untouched.
    for prefix in (p.strip() for p in (exclude or "").split(",") if p.strip()):
        query = query.where(AuditEvent.action.not_like(f"{prefix}%"))

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar()
    events = (
        db.execute(query.order_by(AuditEvent.seq.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    return {
        "total": total,
        "offset": offset,
        "actions": audit.stats(db),
        "events": [
            {
                "seq": event.seq,
                "ts": event.ts.isoformat(),
                "user": event.user,
                "action": event.action,
                "entity": event.entity,
                "payload": json.loads(event.payload_json or "{}"),
                "prev_hash": event.prev_hash,
                "hash": event.hash,
            }
            for event in events
        ],
    }


@router.get("/audit/verify")
def audit_verify(db: Session = Depends(get_db)) -> dict:
    """Re-walk the chain and report the first break with its sequence number."""
    return audit.verify(db)


# --------------------------------------------------------------------------
# Item detail (§6.4) — duplicates and equivalents as two separate blocks
# --------------------------------------------------------------------------


@router.get("/items/{item_id}")
def get_item(
    item_id: int,
    user: Annotated[User | None, Depends(current_user_optional)] = None,
    db: Session = Depends(get_db),
) -> dict:
    card = _item_card(db, item_id)
    if "normalized" not in card:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No item {item_id}.")

    scope = scope_for(user)
    cluster_id = card["cluster_id"]
    golden = (
        db.execute(
            select(GoldenRecord).where(GoldenRecord.cluster_id == cluster_id)
        ).scalar_one_or_none()
        if cluster_id
        else None
    )
    code = (
        db.execute(select(Cnmc).where(Cnmc.golden_id == golden.id)).scalar_one_or_none()
        if golden
        else None
    )

    # §2B: duplicates are merged into this CNMC; equivalents keep their own.
    siblings = (
        db.execute(
            select(ClusterMember.item_id).where(
                ClusterMember.cluster_id == cluster_id, ClusterMember.item_id != item_id
            )
        )
        .scalars()
        .all()
        if cluster_id
        else []
    )
    relations = (
        db.execute(
            select(Relation)
            .where((Relation.item_a == item_id) | (Relation.item_b == item_id))
            .order_by(Relation.confidence.desc())
            .limit(25)
        )
        .scalars()
        .all()
    )
    installed = substitutes.installed_on(db, [item_id]).get(item_id, [])
    approvals = substitutes.approvals_for(db, [r.id for r in relations])

    return {
        **card,
        "golden": (
            {
                "id": golden.id,
                "std_description": golden.std_description,
                "status": golden.status,
                "attrs": json.loads(golden.attrs_json or "{}"),
            }
            if golden
            else None
        ),
        "cnmc": {"code": code.code, "status": code.status} if code else None,
        # Public codes the class maps to (UNSPSC for GeM and tenders, the HSN
        # heading every PO needs), with the level each was assigned at.
        "standards": get_schema(card["class_code"]).standards,
        "duplicates": [_item_card(db, sibling) for sibling in siblings],
        "equivalents": [
            {
                "counterpart": _item_card(
                    db,
                    relation.item_b if relation.item_a == item_id else relation.item_a,
                ),
                "relation_id": relation.id,
                "rel_type": relation.rel_type,
                "direction": relation.direction,
                "basis": relation.basis,
                "confidence": relation.confidence,
                # A proposal until an engineer approves it for the equipment.
                "status": relation.status,
                "approval": approvals.get(relation.id),
                "substitutes_this": (relation.direction == "a_to_b" and relation.item_b == item_id)
                or (relation.direction == "b_to_a" and relation.item_a == item_id),
            }
            for relation in relations
        ],
        "cluster": {"id": cluster_id, "status": db.get(Cluster, cluster_id).status}
        if cluster_id
        else None,
        # Where this material is fitted, and the VED class that follows.
        "installed_on": installed,
        "ved": substitutes.ved_of(installed),
        # §2E: once items share a CNMC, stock held across CPSEs becomes one
        # visible position for the first time.
        "consolidated_stock": (
            inventory.consolidated_stock(db, cluster_id, scope) if cluster_id else None
        ),
        # §9A(c): last purchase price and its direction, and the material's
        # ABC class at this CPSE by 12-month consumption value.
        "purchase_history": {
            **opportunity.last_purchase_and_trend(db, item_id, scope),
            "abc": opportunity.abc_for(db, cluster_id, card["cpse"]),
        },
        "visibility": scope.as_dict(),
    }


@router.get("/compare")
def compare_items(
    a: int,
    b: int,
    _user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """Any two rows, side by side, scored by the same matcher the pipeline
    uses (§6.5). Nothing is stored and nothing is decided: an approver who
    asks "are these the same?" about two rows the pipeline never paired gets
    the tier strip, the attribute diff, the veto and the one-line why, and
    then makes up their own mind on the cluster page."""
    if a == b:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick two different rows.")
    from ..embed import unpack
    from ..match import MatchCandidate, match_pair

    def candidate(item_id: int) -> MatchCandidate:
        row = db.execute(
            select(
                Item.id,
                Item.class_code,
                Item.class_confidence,
                Item.norm_text,
                Item.norm_hash,
                Item.mpn_norm,
                Item.gtin,
                Item.attrs_json,
                Item.embed_vector,
            ).where(Item.id == item_id)
        ).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No item {item_id}.")
        return MatchCandidate(
            id=row[0],
            class_code=row[1],
            class_confidence=row[2] or 0.0,
            norm_text=row[3] or "",
            norm_hash=row[4] or "",
            mpn_norm=row[5],
            gtin=row[6],
            attrs=json.loads(row[7] or "{}"),
            vector=unpack(row[8]) if row[8] else None,
        )

    result = match_pair(candidate(a), candidate(b))
    attributes = result.evidence.get("attributes", {})
    said = adjudicate(
        result.evidence,
        result.tier_scores,
        result.confidence,
        result.verdict,
        result.veto,
        rephrase=False,
    )
    # The pipeline's own verdict on this pair, if it ever scored it.
    stored = (
        db.execute(
            select(Pair).where(
                ((Pair.item_a == a) & (Pair.item_b == b))
                | ((Pair.item_a == b) & (Pair.item_b == a))
            )
        )
        .scalars()
        .first()
    )
    same_cluster = (
        len(
            {
                db.execute(
                    select(ClusterMember.cluster_id).where(ClusterMember.item_id == i)
                ).scalar_one_or_none()
                for i in (a, b)
            }
        )
        == 1
    )
    return {
        "items": [_item_card(db, a), _item_card(db, b)],
        "verdict": result.verdict,
        "band": result.band,
        "confidence": result.confidence,
        "tier_scores": result.tier_scores,
        "veto": result.veto,
        "refused_because": (
            [f"{v['attr']}: {v['reason']}" for v in result.veto["vetoed_by"]] if result.veto else []
        ),
        "equivalence": result.equivalence,
        "attribute_diff": [
            {
                "attr": e["attr"],
                "role": e["role"],
                "a": e["a"],
                "b": e["b"],
                "result": e["result"],
                "detail": e["detail"],
                "agrees": e["result"] in ("match", "in_band"),
            }
            for e in attributes.get("per_attr", [])
        ],
        "agreement": attributes.get("agreement"),
        "why": said.summary,
        "adjudication": said.as_dict(),
        "pipeline": {
            "paired": stored is not None,
            "verdict": stored.verdict if stored else None,
            "pair_id": stored.id if stored else None,
            "same_cluster": same_cluster,
        },
        "note": "Scored now, by the same matcher as the pipeline. Nothing was stored or decided.",
    }
