"""Human review operations — spec §5, §6.5, §6.6, §0.9.

Everything a reviewer can change to the cluster graph lives here, so that three
invariants hold in one place rather than in each endpoint:

* every mutation appends an audit event (§0.8);
* a cluster whose CNMC has been issued is immutable — a code that changes
  meaning is worse than no code;
* whoever proposed or edited a golden record may not approve it (§0.9).

Golden records are rebuilt from the cluster's current members after any change,
so the standardized description always reflects what is actually in the cluster.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from . import audit
from .models import (
    AuditEvent,
    Cluster,
    ClusterMember,
    Cnmc,
    Decision,
    GoldenFieldProvenance,
    GoldenRecord,
    Item,
    Pair,
    PairLabel,
    PurchaseHistory,
    ReviewTask,
    User,
)
from .standardize import Member, standardize
from .taxonomy import get_schema


class ImmutableClusterError(HTTPException):
    def __init__(self, cluster_id: int, code: str):
        super().__init__(
            status.HTTP_409_CONFLICT,
            f"Cluster {cluster_id} already carries CNMC {code}. An issued code is "
            "immutable; withdraw it before changing what it identifies.",
        )


def _issued_code(db: Session, cluster_id: int) -> str | None:
    return db.execute(
        select(Cnmc.code)
        .join(GoldenRecord, GoldenRecord.id == Cnmc.golden_id)
        .where(GoldenRecord.cluster_id == cluster_id)
    ).scalar_one_or_none()


def guard_mutable(db: Session, cluster_id: int) -> None:
    code = _issued_code(db, cluster_id)
    if code:
        raise ImmutableClusterError(cluster_id, code)


# --------------------------------------------------------------------------
# Golden records
# --------------------------------------------------------------------------


def rebuild_golden(db: Session, cluster_id: int, proposed_by: int | None = None) -> GoldenRecord:
    """Re-standardize a cluster from its current members (§2D).

    Called after any change to membership, so the golden record can never drift
    out of step with the cluster it describes.
    """
    rows = db.execute(
        select(Item.id, Item.norm_text, Item.class_code, Item.attrs_json)
        .join(ClusterMember, ClusterMember.item_id == Item.id)
        .where(ClusterMember.cluster_id == cluster_id)
        .order_by(Item.id)
    ).all()

    last_purchase = dict(
        db.execute(
            select(PurchaseHistory.item_id, func.max(PurchaseHistory.po_date))
            .where(PurchaseHistory.item_id.in_([r[0] for r in rows] or [0]))
            .group_by(PurchaseHistory.item_id)
        ).all()
    )

    members, readable_mpn = [], Counter()
    class_codes = Counter()
    for item_id, norm_text, class_code, attrs_json in rows:
        attrs = json.loads(attrs_json or "{}")
        class_codes[class_code] += 1
        if attrs.get("_mpn_raw"):
            readable_mpn[attrs["_mpn_raw"]] += 1
        members.append(
            Member(
                id=item_id,
                attrs={k: v for k, v in attrs.items() if not k.startswith("_")},
                sources=attrs.get("_sources", {}),
                norm_text=norm_text or "",
                last_purchase=last_purchase.get(item_id),
            )
        )

    class_code = class_codes.most_common(1)[0][0] if class_codes else "unclassified"
    result = standardize(
        members,
        get_schema(class_code),
        readable_mpn.most_common(1)[0][0] if readable_mpn else None,
    )

    attrs_json = json.dumps(result.attrs, sort_keys=True, default=str)
    golden = db.execute(
        select(GoldenRecord).where(GoldenRecord.cluster_id == cluster_id)
    ).scalar_one_or_none()
    if golden is None:
        # Every column is set before the flush: std_description is NOT NULL,
        # so an empty shell cannot be written and filled in afterwards.
        golden = GoldenRecord(
            cluster_id=cluster_id,
            std_description=result.std_description,
            attrs_json=attrs_json,
            status=result.status,
        )
        db.add(golden)
        db.flush()

    golden.std_description = result.std_description
    golden.attrs_json = attrs_json
    golden.status = result.status
    if proposed_by is not None:
        # §0.9: recorded so the approval step can refuse the same person.
        golden.proposed_by = proposed_by

    cluster = db.get(Cluster, cluster_id)
    if cluster:
        cluster.status = result.status

    db.execute(delete(GoldenFieldProvenance).where(GoldenFieldProvenance.golden_id == golden.id))
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
    db.flush()
    return golden


# --------------------------------------------------------------------------
# Cluster surgery
# --------------------------------------------------------------------------


def merge_clusters(
    db: Session, source_id: int, target_id: int, user: User, note: str | None = None
) -> int:
    """Move every member of `source` into `target`, then drop the empty source."""
    if source_id == target_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A cluster cannot merge into itself."
        )
    for cluster_id in (source_id, target_id):
        if db.get(Cluster, cluster_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No cluster {cluster_id}.")
        guard_mutable(db, cluster_id)

    moved = (
        db.execute(select(ClusterMember.item_id).where(ClusterMember.cluster_id == source_id))
        .scalars()
        .all()
    )

    # Review tasks point at the cluster their pair belongs to. The task is
    # still about the same items, so it follows them into the survivor rather
    # than being orphaned or deleted.
    db.execute(
        update(ReviewTask).where(ReviewTask.cluster_id == source_id).values(cluster_id=target_id)
    )
    db.execute(
        delete(GoldenFieldProvenance).where(
            GoldenFieldProvenance.golden_id.in_(
                select(GoldenRecord.id).where(GoldenRecord.cluster_id == source_id)
            )
        )
    )
    db.execute(delete(GoldenRecord).where(GoldenRecord.cluster_id == source_id))
    db.execute(delete(ClusterMember).where(ClusterMember.cluster_id == source_id))
    db.execute(delete(Cluster).where(Cluster.id == source_id))
    if moved:
        db.execute(
            insert(ClusterMember),
            [{"cluster_id": target_id, "item_id": item_id} for item_id in moved],
        )

    rebuild_golden(db, target_id, proposed_by=user.id)
    audit.record(
        db,
        action="cluster.merge",
        entity=f"cluster:{target_id}",
        payload={
            "merged_from": source_id,
            "merged_into": target_id,
            "items_moved": moved,
            "note": note,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return target_id


def split_member(
    db: Session, cluster_id: int, item_id: int, user: User, note: str | None = None
) -> int:
    """Remove one member from a cluster into a cluster of its own."""
    if db.get(Cluster, cluster_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No cluster {cluster_id}.")
    guard_mutable(db, cluster_id)

    membership = db.execute(
        select(ClusterMember).where(
            ClusterMember.cluster_id == cluster_id, ClusterMember.item_id == item_id
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Item {item_id} is not in cluster {cluster_id}."
        )
    remaining = db.execute(
        select(func.count(ClusterMember.id)).where(ClusterMember.cluster_id == cluster_id)
    ).scalar()
    if remaining <= 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That is the only member; the cluster is already just this item.",
        )

    db.delete(membership)
    db.flush()

    new_cluster = Cluster(status="draft")
    db.add(new_cluster)
    db.flush()
    db.execute(insert(ClusterMember), [{"cluster_id": new_cluster.id, "item_id": item_id}])

    rebuild_golden(db, cluster_id, proposed_by=user.id)
    rebuild_golden(db, new_cluster.id, proposed_by=user.id)

    audit.record(
        db,
        action="cluster.split",
        entity=f"cluster:{cluster_id}",
        payload={
            "removed_item": item_id,
            "from_cluster": cluster_id,
            "into_cluster": new_cluster.id,
            "note": note,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return new_cluster.id


# --------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------

#: Who may close a task in each band (§5). A conflict needs an approver
#: because it is a data-quality judgement, not a similarity judgement.
BAND_ROLES = {
    "high": ("steward", "approver", "registrar", "admin"),
    "grey": ("steward", "approver", "registrar", "admin"),
    "low": ("steward", "approver", "registrar", "admin"),
}
CONFLICT_ROLES = ("approver", "registrar", "admin")

VALID_ACTIONS = ("approve", "reject", "merge", "split")


def authorize(task: ReviewTask, pair: Pair | None, user: User) -> None:
    """Role gate for closing a review task."""
    allowed = (
        CONFLICT_ROLES
        if (pair is not None and pair.verdict == "conflict")
        else BAND_ROLES.get(task.band, ("steward",))
    )
    if user.role not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This task needs one of: {', '.join(sorted(allowed))}. "
            f"You are signed in as {user.role}.",
        )


def apply_decision(
    db: Session,
    task: ReviewTask,
    action: str,
    user: User,
    note: str | None = None,
    seconds: float | None = None,
) -> dict:
    """Close a review task and act on its verdict.

    `seconds` is how long the card was in front of the reviewer, reported by
    the client. It is recorded on the audit event, not trusted for anything
    else: the dashboard's seconds-per-decision figure comes from it.

    The audit payload also carries `before` (the pair's verdict and the two
    clusters as they were) so `undo_decision` can put things back.
    """
    if action not in VALID_ACTIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown action {action!r}; expected one of {', '.join(VALID_ACTIONS)}.",
        )
    if task.state == "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "That task has already been decided.")

    pair = db.get(Pair, task.pair_id) if task.pair_id else None
    authorize(task, pair, user)

    outcome: dict = {"action": action}
    before: dict = {}
    if pair is not None:
        cluster_a, cluster_b = _clusters_of(db, pair)
        before = {"verdict": pair.verdict, "cluster_a": cluster_a, "cluster_b": cluster_b}

    if action == "approve" and pair is not None:
        if cluster_a and cluster_b and cluster_a != cluster_b:
            for cluster_id in (cluster_a, cluster_b):
                guard_mutable(db, cluster_id)
            # Remembered so an undo can move exactly these rows back out.
            outcome["items_moved"] = list(
                db.execute(
                    select(ClusterMember.item_id).where(ClusterMember.cluster_id == cluster_a)
                ).scalars()
            )
            merge_clusters(db, cluster_a, cluster_b, user, note)
            outcome["merged_into"] = cluster_b
        else:
            outcome["merged_into"] = cluster_a or cluster_b
        pair.verdict = "duplicate"
    elif action == "reject" and pair is not None:
        if cluster_a is not None and cluster_a == cluster_b:
            # Overturning an automatic merge has to actually separate them;
            # otherwise the reviewer's "no" changes nothing but a flag.
            members = db.execute(
                select(func.count(ClusterMember.id)).where(ClusterMember.cluster_id == cluster_a)
            ).scalar()
            if members > 1:
                guard_mutable(db, cluster_a)
                outcome["split_into"] = split_member(db, cluster_a, pair.item_b, user, note)
        pair.verdict = "distinct"

    task.state = "done"
    decision = Decision(task_id=task.id, user_id=user.id, action=action, note=note)
    db.add(decision)
    if pair is not None and action in ("approve", "reject"):
        # The answer is also a label: what the learned model trains on.
        from .learn import record_label

        record_label(db, pair, action == "approve", user.id)
    db.flush()

    audit.record(
        db,
        action=f"decision.{action}",
        entity=f"review_task:{task.id}",
        payload={
            "task_id": task.id,
            "pair_id": task.pair_id,
            "band": task.band,
            "action": action,
            "note": note,
            "seconds": seconds,
            "before": before,
            "outcome": outcome,
        },
        user=user.email,
        commit=False,
    )
    db.commit()

    if pair is not None and action in ("approve", "reject"):
        # Enough reviewer labels since the last model: retrain in the
        # background. The decision is committed; nothing here can undo it.
        from .learn import schedule_retrain

        schedule_retrain(db)

    outcome["decision_id"] = decision.id
    outcome["task_id"] = task.id
    outcome["undo_until"] = (decision.ts.replace(tzinfo=UTC) + _undo_window()).isoformat()
    return outcome


def _clusters_of(db: Session, pair: Pair) -> tuple[int | None, int | None]:
    return tuple(
        db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == item_id)
        ).scalar_one_or_none()
        for item_id in (pair.item_a, pair.item_b)
    )


def _undo_window():
    from datetime import timedelta

    from .config import get_settings

    return timedelta(seconds=get_settings().saman_undo_window_s)


def apply_decisions(
    db: Session,
    task_ids: list[int],
    action: str,
    user: User,
    note: str | None = None,
) -> dict:
    """Close many tasks with one reason: the high band a page at a time.

    Each task is closed by `apply_decision`, so each keeps its own audit
    event, its own label and its own undo. A task that cannot be closed
    (already decided, wrong role, an issued code in the way) is reported and
    skipped rather than stopping the page.
    """
    done: list[dict] = []
    skipped: list[dict] = []
    for task_id in task_ids:
        task = db.get(ReviewTask, task_id)
        if task is None:
            skipped.append({"task_id": task_id, "reason": "no such task"})
            continue
        try:
            done.append(apply_decision(db, task, action, user, note))
        except HTTPException as exc:
            db.rollback()
            skipped.append({"task_id": task_id, "reason": str(exc.detail)})
    return {"action": action, "done": done, "skipped": skipped, "count": len(done)}


def undo_decision(db: Session, decision: Decision, user: User) -> dict:
    """Reopen a task and put the world back as it was before the decision.

    Everyone mis-clicks. Within the window (`SAMAN_UNDO_WINDOW_S`, five minutes
    by default) the reviewer who made a decision — or an admin — can take it
    back: the task returns to the queue, the cluster merge or split it caused
    is reversed, the reviewer's label is withdrawn so the learned model never
    trains on it, and the pair's verdict is restored. The decision row is
    removed so that counts of decisions stay counts of decisions that stand;
    the audit chain keeps both the decision and its undo, as it keeps
    everything.

    Only approve and reject can be undone here: a merge or split made from the
    cluster page is reversed from the cluster page, deliberately.
    """
    task = db.get(ReviewTask, decision.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No review task {decision.task_id}.")
    if decision.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the reviewer who made a decision can undo it."
        )
    if decision.action not in ("approve", "reject"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only approve and reject can be undone here; reverse a merge or split "
            "from the cluster page.",
        )
    age = datetime.now(UTC) - decision.ts.replace(tzinfo=UTC)
    window = _undo_window()
    if age > window:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The undo window closed {int((age - window).total_seconds())} s ago.",
        )
    latest = (
        db.execute(
            select(Decision.id).where(Decision.task_id == task.id).order_by(Decision.id.desc())
        )
        .scalars()
        .first()
    )
    if latest != decision.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A later decision on this task stands; undo that first."
        )

    event = (
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.action == f"decision.{decision.action}",
                AuditEvent.entity == f"review_task:{task.id}",
            )
            .order_by(AuditEvent.seq.desc())
        )
        .scalars()
        .first()
    )
    payload = json.loads(event.payload_json) if event else {}
    before = payload.get("before") or {}
    outcome = payload.get("outcome") or {}
    restored: dict = {}

    pair = db.get(Pair, task.pair_id) if task.pair_id else None
    if pair is not None:
        if decision.action == "approve" and outcome.get("items_moved"):
            # The merge moved cluster A's rows into B; move exactly those rows
            # back out into one cluster of their own.
            target = outcome["merged_into"]
            guard_mutable(db, target)
            moved = outcome["items_moved"]
            db.execute(
                delete(ClusterMember).where(
                    ClusterMember.cluster_id == target, ClusterMember.item_id.in_(moved)
                )
            )
            fresh = Cluster(status="draft")
            db.add(fresh)
            db.flush()
            db.execute(
                insert(ClusterMember),
                [{"cluster_id": fresh.id, "item_id": item_id} for item_id in moved],
            )
            rebuild_golden(db, target, proposed_by=user.id)
            rebuild_golden(db, fresh.id, proposed_by=user.id)
            restored["unmerged_into"] = fresh.id
        elif decision.action == "reject" and outcome.get("split_into"):
            # The reject split item B out; merge that cluster back.
            split = outcome["split_into"]
            home, _ = _clusters_of(db, pair)
            if home is not None and split != home and db.get(Cluster, split) is not None:
                merge_clusters(db, split, home, user, "undo")
                restored["remerged_into"] = home
        if before.get("verdict"):
            pair.verdict = before["verdict"]
            restored["verdict"] = before["verdict"]

        # The label this decision wrote, so the model never learns a mis-click.
        a, b = sorted((pair.item_a, pair.item_b))
        label = (
            db.execute(
                select(PairLabel)
                .where(
                    PairLabel.item_a == a,
                    PairLabel.item_b == b,
                    PairLabel.user_id == decision.user_id,
                    PairLabel.source == "reviewer",
                )
                .order_by(PairLabel.id.desc())
            )
            .scalars()
            .first()
        )
        if label is not None:
            db.delete(label)
            restored["label_withdrawn"] = True

    task.state = "pending"
    undone = {
        "decision_id": decision.id,
        "action": decision.action,
        "note": decision.note,
        "by_user_id": decision.user_id,
        "after_seconds": int(age.total_seconds()),
    }
    db.delete(decision)
    db.flush()
    audit.record(
        db,
        action="decision.undo",
        entity=f"review_task:{task.id}",
        payload={"task_id": task.id, "undone": undone, "restored": restored},
        user=user.email,
        commit=False,
    )
    db.commit()
    return {"task_id": task.id, "undone": undone, "restored": restored}
