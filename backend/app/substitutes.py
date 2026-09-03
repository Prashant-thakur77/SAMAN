"""Equipment context and approved substitutes.

The pipeline finds functional equivalents (§2B). A maintenance engineer will
not fit one without knowing where the original is installed and without a
technical authority's say-so: a substitute for a bearing on a spare pump is a
different decision from the same substitute on the main feed compressor.

So every item can say where it is installed (`equipment_bom`), each piece of
equipment carries a criticality (A, B, C: the plant's own ranking, read here
as VED: vital, essential, desirable), and an equivalence is only *approved*
when an engineer says so, with a reason, on the record. Until then it stays a
proposal: visible, labelled, not to be acted on.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from . import audit
from .models import (
    ClusterMember,
    Cnmc,
    Cpse,
    Equipment,
    EquipmentBom,
    GoldenRecord,
    Item,
    RawItem,
    Relation,
    SubstituteApproval,
    User,
)

#: Who may approve a substitute: the technical authority, or the registrar
#: and admin acting for the programme. Stewards may look, never sign.
DECIDERS = ("engineer", "registrar", "admin")
STATUSES = ("proposed", "approved", "rejected")
#: The plant's A/B/C read as VED.
VED = {"A": "vital", "B": "essential", "C": "desirable"}
CRITICALITY_ORDER = {"A": 0, "B": 1, "C": 2}


def installed_on(db: Session, item_ids: list[int]) -> dict[int, list[dict]]:
    """Every piece of equipment each item sits on, with its criticality."""
    if not item_ids:
        return {}
    rows = db.execute(
        select(
            EquipmentBom.item_id,
            Equipment.tag,
            Equipment.description,
            Equipment.criticality,
            Cpse.code,
            EquipmentBom.qty,
        )
        .join(Equipment, Equipment.id == EquipmentBom.equipment_id)
        .join(Cpse, Cpse.id == Equipment.cpse_id)
        .where(EquipmentBom.item_id.in_(item_ids))
        .order_by(Equipment.criticality, Equipment.tag)
    ).all()
    out: dict[int, list[dict]] = {}
    for item_id, tag, description, criticality, cpse, qty in rows:
        out.setdefault(item_id, []).append(
            {
                "tag": tag,
                "description": description,
                "criticality": criticality,
                "ved": VED.get(criticality),
                "cpse": cpse,
                "qty": qty,
            }
        )
    return out


def ved_of(installations: list[dict]) -> str | None:
    """The item's VED class: the most critical equipment it is fitted to."""
    if not installations:
        return None
    top = min(installations, key=lambda e: CRITICALITY_ORDER.get(e["criticality"], 9))
    return VED.get(top["criticality"])


def critical_sources(db: Session) -> set[tuple[int, str]]:
    """(cluster_id, cpse) pairs where the material is a spare for A-criticality
    equipment at that CPSE. Surplus there is insurance, not idle stock."""
    rows = db.execute(
        select(ClusterMember.cluster_id, Cpse.code)
        .join(EquipmentBom, EquipmentBom.item_id == ClusterMember.item_id)
        .join(Equipment, Equipment.id == EquipmentBom.equipment_id)
        .join(Cpse, Cpse.id == Equipment.cpse_id)
        .where(Equipment.criticality == "A")
        .distinct()
    ).all()
    return {(cluster_id, cpse) for cluster_id, cpse in rows}


def _describe(db: Session, item_ids: list[int]) -> dict[int, dict]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(
            Item.id,
            Item.norm_text,
            Item.class_code,
            RawItem.legacy_code,
            RawItem.description,
            Cpse.code,
            ClusterMember.cluster_id,
        )
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .outerjoin(ClusterMember, ClusterMember.item_id == Item.id)
        .where(Item.id.in_(item_ids))
    ).all()
    codes = {}
    cluster_ids = [r[6] for r in rows if r[6] is not None]
    if cluster_ids:
        codes = dict(
            db.execute(
                select(GoldenRecord.cluster_id, Cnmc.code)
                .join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
                .where(GoldenRecord.cluster_id.in_(cluster_ids))
            ).all()
        )
    return {
        item_id: {
            "item_id": item_id,
            "normalized": norm_text,
            "class_code": class_code,
            "legacy_code": legacy_code,
            "description": description,
            "cpse": cpse,
            "cluster_id": cluster_id,
            "cnmc": codes.get(cluster_id),
        }
        for item_id, norm_text, class_code, legacy_code, description, cpse, cluster_id in rows
    }


def approvals_for(db: Session, relation_ids: list[int]) -> dict[int, dict]:
    """The latest decision on each relation, if any."""
    if not relation_ids:
        return {}
    rows = db.execute(
        select(SubstituteApproval, User.name)
        .outerjoin(User, User.id == SubstituteApproval.decided_by)
        .where(SubstituteApproval.relation_id.in_(relation_ids))
        .order_by(SubstituteApproval.id)
    ).all()
    out: dict[int, dict] = {}
    for approval, name in rows:
        out[approval.relation_id] = {
            "status": approval.status,
            "decided_by": name,
            "reason": approval.reason,
            "ts": approval.ts.isoformat() if approval.ts else None,
        }
    return out


def summary(db: Session) -> dict:
    counts = dict(
        db.execute(
            select(Relation.status, func.count(Relation.id))
            .where(Relation.rel_type.in_(("equivalent", "supersedes")))
            .group_by(Relation.status)
        ).all()
    )
    return {s: counts.get(s, 0) for s in STATUSES}


def list_relations(
    db: Session, status_filter: str = "proposed", limit: int = 50, offset: int = 0
) -> dict:
    """Equivalences with both sides described, where each side is installed,
    and the decision so far."""
    query = select(Relation).where(Relation.rel_type.in_(("equivalent", "supersedes")))
    if status_filter != "all":
        query = query.where(Relation.status == status_filter)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    # Equivalences that touch fitted equipment first: those are the ones an
    # engineer is actually asked about. Within that, the pipeline's confidence.
    fitted = select(EquipmentBom.item_id)
    touches_plant = case(
        (or_(Relation.item_a.in_(fitted), Relation.item_b.in_(fitted)), 0), else_=1
    )
    relations = (
        db.execute(
            query.order_by(touches_plant, Relation.confidence.desc(), Relation.id)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    item_ids = sorted({r.item_a for r in relations} | {r.item_b for r in relations})
    described = _describe(db, item_ids)
    installed = installed_on(db, item_ids)
    approvals = approvals_for(db, [r.id for r in relations])
    rows = []
    for relation in relations:
        a = described.get(relation.item_a, {"item_id": relation.item_a})
        b = described.get(relation.item_b, {"item_id": relation.item_b})
        a_installed = installed.get(relation.item_a, [])
        b_installed = installed.get(relation.item_b, [])
        rows.append(
            {
                "id": relation.id,
                "rel_type": relation.rel_type,
                "direction": relation.direction,
                "basis": relation.basis,
                "confidence": relation.confidence,
                "status": relation.status,
                "evidence": json.loads(relation.evidence_json or "{}"),
                "a": {**a, "installed_on": a_installed, "ved": ved_of(a_installed)},
                "b": {**b, "installed_on": b_installed, "ved": ved_of(b_installed)},
                "approval": approvals.get(relation.id),
                # The highest criticality either side touches: what the
                # engineer is really signing for.
                "criticality": min(
                    [e["criticality"] for e in a_installed + b_installed] or ["-"],
                    key=lambda c: CRITICALITY_ORDER.get(c, 9),
                ),
            }
        )
    return {
        "status": status_filter,
        "total": total,
        "offset": offset,
        "counts": summary(db),
        "relations": rows,
        "note": (
            "An equivalence is a proposal until a technical authority approves it "
            "for the equipment it touches. Approved substitutes may be fitted; "
            "rejected ones stay on record with the reason."
        ),
    }


def decide(db: Session, relation_id: int, decision: str, reason: str | None, user: User) -> dict:
    if decision not in ("approved", "rejected"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "decision must be 'approved' or 'rejected'."
        )
    if user.role not in DECIDERS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Approving a substitute needs one of: {', '.join(DECIDERS)}. "
            f"You are signed in as {user.role}.",
        )
    relation = db.get(Relation, relation_id)
    if relation is None or relation.rel_type not in ("equivalent", "supersedes"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No substitute relation {relation_id}.")
    if not (reason or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A reason is required: it is what the next engineer reads.",
        )
    approval = SubstituteApproval(
        relation_id=relation.id,
        status=decision,
        decided_by=user.id,
        reason=reason.strip(),
        ts=datetime.now(UTC),
    )
    db.add(approval)
    relation.status = decision
    db.flush()
    audit.record(
        db,
        action=f"substitute.{decision}",
        entity=f"relation:{relation.id}",
        payload={
            "relation_id": relation.id,
            "item_a": relation.item_a,
            "item_b": relation.item_b,
            "direction": relation.direction,
            "basis": relation.basis,
            "reason": approval.reason,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return {
        "relation_id": relation.id,
        "status": relation.status,
        "approval_id": approval.id,
        "decided_by": user.name,
        "reason": approval.reason,
    }
