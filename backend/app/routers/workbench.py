"""Review queues, decisions and the audit ledger — spec §5, §6.5, §6.10."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, inventory, opportunity, review
from ..adjudicate import adjudicate
from ..auth import current_user_optional, require_roles, require_user
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


def _task_card(db: Session, task: ReviewTask) -> dict:
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

    card.update(
        {
            "pair_id": pair.id,
            "verdict": pair.verdict,
            "confidence": pair.confidence,
            "tier_scores": json.loads(pair.tier_scores_json or "{}"),
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
            # Tier 3 (§0.4): a recommendation with its reasons, so the reviewer
            # starts from a position rather than from a score. It never decides.
            "adjudication": adjudicate(
                evidence,
                json.loads(pair.tier_scores_json or "{}"),
                pair.confidence,
                pair.verdict,
                veto,
            ).as_dict()
            if task.band == "grey"
            else None,
        }
    )
    return card


@router.get("/queues")
def queues(
    band: str | None = Query(default=None),
    state: str = Query(default="pending"),
    limit: int = Query(default=25, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    """The three band queues with their counts, and a page of cards (§6.5)."""
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
    tasks = (
        db.execute(query.order_by(ReviewTask.id).offset(offset).limit(limit)).scalars().all()
    )
    total = db.execute(
        select(func.count(ReviewTask.id)).where(
            ReviewTask.state == state,
            *( [ReviewTask.band == band] if band else [] ),
        )
    ).scalar()

    return {
        "band": band,
        "state": state,
        "counts": {b: counts.get(b, 0) for b in BANDS},
        "total": total,
        "offset": offset,
        "tasks": [_task_card(db, task) for task in tasks],
    }


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

    return review.apply_decision(db, task, body.action, user, body.note)


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

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar()
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
        ).scalars().all()
        if cluster_id
        else []
    )
    relations = db.execute(
        select(Relation).where(
            (Relation.item_a == item_id) | (Relation.item_b == item_id)
        ).order_by(Relation.confidence.desc()).limit(25)
    ).scalars().all()

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
        "duplicates": [_item_card(db, sibling) for sibling in siblings],
        "equivalents": [
            {
                "counterpart": _item_card(
                    db,
                    relation.item_b if relation.item_a == item_id else relation.item_a,
                ),
                "rel_type": relation.rel_type,
                "direction": relation.direction,
                "basis": relation.basis,
                "confidence": relation.confidence,
                "substitutes_this": (
                    relation.direction == "a_to_b" and relation.item_b == item_id
                )
                or (relation.direction == "b_to_a" and relation.item_a == item_id),
            }
            for relation in relations
        ],
        "cluster": {"id": cluster_id, "status": db.get(Cluster, cluster_id).status}
        if cluster_id
        else None,
        # §2E: once items share a CNMC, stock held across CPSEs becomes one
        # visible position for the first time.
        "consolidated_stock": (
            inventory.consolidated_stock(db, cluster_id, scope) if cluster_id else None
        ),
        # §9A(c): last purchase price and its direction.
        "purchase_history": opportunity.last_purchase_and_trend(db, item_id, scope),
        "visibility": scope.as_dict(),
    }
