"""Codes that issue themselves, under a policy a registrar set (spec §5, §0.9).

Seven thousand policy confirmations are not a registrar's afternoon. Where
the evidence is beyond argument, the code can be issued without a click, but
only under three gates, each of which a person can read:

1. **Anchored and in full agreement.** Every stored pair inside the cluster
   carries a Tier-0 anchor (the same part number, GTIN or exact text) and
   every compared attribute agrees; nothing was vetoed and nothing is held
   as a conflict. A cluster with a single row has nothing to compare and is
   left to a person.
2. **The class has earned it.** The class's held-out precision, on the
   latest run's snapshot, is at or above the target the registrar set for
   the family. No snapshot, no truth, no target met: nothing issues.
3. **Nobody is still looking.** No pending grey-band task touches the
   cluster.

The policy is per family and off by default. Every code issued under it is
audited as `cnmc.issue` with `policy: "auto"`, and is recorded as issued by
the registrar who set the policy: automation does not dilute accountability,
it names the person who chose it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import analytics, audit
from .cnmc import FAMILY_BY_CLASS, ConflictError, family_for, issue_code
from .models import (
    ClusterMember,
    Cnmc,
    GoldenRecord,
    IssuePolicy,
    Item,
    Pair,
    ReviewTask,
    User,
)

#: The precision a family must show on the held-out split before its codes
#: may issue on their own, unless the registrar sets another.
DEFAULT_MIN_PRECISION = 0.99

FAMILIES = tuple(sorted(set(FAMILY_BY_CLASS.values())))


@dataclass
class Candidate:
    cluster_id: int
    golden_id: int
    class_code: str
    family: str
    members: int
    pairs: int
    std_description: str


def class_precision(db: Session) -> dict[str, float]:
    """Held-out precision per class from the latest run's snapshot; empty
    when no run carries one (no truth, no scorecard, no automation)."""
    run = analytics.latest_run(db, full=True) or analytics.latest_run(db)
    snapshot = run.stats.get("evaluation") if run else None
    if not snapshot or not snapshot.get("counts", {}).get("truth_groups_holdout"):
        return {}
    return {
        row["class_code"]: float(row["precision"])
        for row in snapshot.get("per_class", [])
        if row.get("precision") is not None
    }


def policies(db: Session) -> dict[str, IssuePolicy]:
    return {p.family: p for p in db.execute(select(IssuePolicy)).scalars()}


def set_policy(
    db: Session, family: str, enabled: bool, min_precision: float, user: User
) -> IssuePolicy:
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}; one of {', '.join(FAMILIES)}")
    if not 0.9 <= min_precision <= 1.0:
        raise ValueError("min_precision must be between 0.90 and 1.00")
    policy = db.get(IssuePolicy, family)
    before = {"enabled": policy.enabled, "min_precision": policy.min_precision} if policy else None
    if policy is None:
        policy = IssuePolicy(family=family)
        db.add(policy)
    policy.enabled = enabled
    policy.min_precision = min_precision
    policy.set_by = user.id
    policy.set_at = datetime.now(UTC)
    audit.record(
        db,
        action="policy.autoissue",
        entity=f"family:{family}",
        payload={
            "before": before,
            "after": {"enabled": enabled, "min_precision": min_precision},
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return policy


def _cluster_gate(db: Session, cluster_id: int, members: list[int]) -> tuple[bool, int, str]:
    """Gate 1: every stored pair among the members anchored, agreeing,
    unvetoed. Returns (passes, pairs_seen, reason)."""
    if len(members) < 2:
        return False, 0, "single row: nothing to compare"
    pairs = (
        db.execute(select(Pair).where(Pair.item_a.in_(members), Pair.item_b.in_(members)))
        .scalars()
        .all()
    )
    if not pairs:
        return False, 0, "no scored pair inside the cluster"
    for pair in pairs:
        if pair.veto_json and json.loads(pair.veto_json).get("vetoed_by"):
            return False, len(pairs), "a pair was vetoed"
        if pair.verdict in ("conflict", "distinct", "auto_reject"):
            return False, len(pairs), f"a pair is {pair.verdict}"
        tiers = json.loads(pair.tier_scores_json or "{}")
        if not tiers.get("tier0_key"):
            return False, len(pairs), "a pair has no anchor"
        evidence = json.loads(pair.evidence_json or "{}")
        agreement = (evidence.get("attributes") or {}).get("agreement")
        if agreement is None or agreement < 1.0:
            return False, len(pairs), "an attribute does not agree"
    return True, len(pairs), "anchored, all attributes agree"


def eligible(db: Session, family: str | None = None) -> tuple[list[Candidate], dict]:
    """Clusters that pass every gate, and a tally of why the rest did not."""
    precision = class_precision(db)
    active = {f: p for f, p in policies(db).items() if p.enabled}
    reasons: dict[str, int] = {}
    out: list[Candidate] = []

    coded = select(Cnmc.golden_id)
    goldens = (
        db.execute(
            select(GoldenRecord).where(
                GoldenRecord.status == "draft", GoldenRecord.id.notin_(coded)
            )
        )
        .scalars()
        .all()
    )
    pending_grey = {
        row
        for row in db.execute(
            select(ReviewTask.cluster_id).where(
                ReviewTask.state == "pending", ReviewTask.band == "grey"
            )
        ).scalars()
    }
    for golden in goldens:
        members = (
            db.execute(
                select(ClusterMember.item_id).where(ClusterMember.cluster_id == golden.cluster_id)
            )
            .scalars()
            .all()
        )
        class_code = (
            db.execute(select(Item.class_code).where(Item.id.in_(members)).limit(1)).scalar()
            or "unclassified"
        )
        fam, _ = family_for(class_code)
        if family and fam != family:
            continue
        policy = active.get(fam)
        if policy is None:
            reasons["policy off"] = reasons.get("policy off", 0) + 1
            continue
        got = precision.get(class_code)
        if got is None:
            reasons["no held-out precision for the class"] = (
                reasons.get("no held-out precision for the class", 0) + 1
            )
            continue
        if got < policy.min_precision:
            key = f"precision {got:.3f} below {policy.min_precision:.2f}"
            reasons[key] = reasons.get(key, 0) + 1
            continue
        if golden.cluster_id in pending_grey:
            key = "a grey-band task is pending"
            reasons[key] = reasons.get(key, 0) + 1
            continue
        passes, n_pairs, why = _cluster_gate(db, golden.cluster_id, list(members))
        if not passes:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        out.append(
            Candidate(
                cluster_id=golden.cluster_id,
                golden_id=golden.id,
                class_code=class_code,
                family=fam,
                members=len(members),
                pairs=n_pairs,
                std_description=golden.std_description,
            )
        )
    return out, reasons


def run(db: Session, dry_run: bool = True, limit: int = 500, family: str | None = None) -> dict:
    """Issue a code to every eligible cluster (or say what would be issued).

    The issuer of record is the registrar who set the family's policy; the
    audit event carries `policy: "auto"` beside it. A cluster the gates admit
    but `issue_code` refuses (a conflict that appeared since) is skipped and
    named, never forced.
    """
    candidates, reasons = eligible(db, family)
    active = policies(db)
    issued: list[dict] = []
    skipped: list[dict] = []
    for candidate in candidates[:limit]:
        if dry_run:
            issued.append({**candidate.__dict__, "code": None})
            continue
        policy = active[candidate.family]
        issuer = db.get(User, policy.set_by)
        golden = db.get(GoldenRecord, candidate.golden_id)
        try:
            result = issue_code(db, golden, issuer, policy="auto")
        except ConflictError as exc:
            skipped.append({"cluster_id": candidate.cluster_id, "reason": str(exc)})
            continue
        issued.append({**candidate.__dict__, "code": result["code"]})
    if not dry_run and issued:
        audit.record(
            db,
            action="cnmc.autoissue",
            entity="policy:autoissue",
            payload={
                "issued": len(issued),
                "skipped": len(skipped),
                "families": sorted({c["family"] for c in issued}),
            },
            user="system",
        )
    return {
        "dry_run": dry_run,
        "eligible": len(candidates),
        "issued": issued,
        "skipped": skipped,
        "not_eligible": reasons,
        "note": (
            "Every gate is stated: anchored pairs in full agreement, class precision "
            "at or above the family's target on the held-out split, no grey-band task "
            "pending. Codes issue in the name of the registrar who set the policy."
        ),
    }


def status(db: Session) -> dict:
    """The per-family view for the admin page: policy, precision, eligible."""
    precision = class_precision(db)
    active = policies(db)
    candidates, reasons = eligible(db)
    by_family: dict[str, int] = {}
    for c in candidates:
        by_family[c.family] = by_family.get(c.family, 0) + 1
    classes_by_family: dict[str, list[str]] = {}
    for class_code, fam in FAMILY_BY_CLASS.items():
        classes_by_family.setdefault(fam, []).append(class_code)
    from .models import AuditEvent

    issued_auto = (
        db.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "cnmc.issue",
                # The chain writes compact JSON: {"policy":"auto"}.
                AuditEvent.payload_json.like('%"policy":"auto"%'),
            )
        ).scalar()
        or 0
    )
    rows = []
    for fam in FAMILIES:
        policy = active.get(fam)
        classes = classes_by_family.get(fam, [])
        precisions = [precision[c] for c in classes if c in precision]
        rows.append(
            {
                "family": fam,
                "classes": classes,
                "enabled": bool(policy and policy.enabled),
                "min_precision": policy.min_precision if policy else DEFAULT_MIN_PRECISION,
                "set_by": policy.set_by if policy else None,
                "set_at": policy.set_at.isoformat() if policy and policy.set_at else None,
                "precision": min(precisions) if precisions else None,
                "eligible": by_family.get(fam, 0),
            }
        )
    return {
        "families": rows,
        "eligible": len(candidates),
        "not_eligible": reasons,
        "has_snapshot": bool(precision),
        "issued_under_policy": issued_auto,
        "default_min_precision": DEFAULT_MIN_PRECISION,
    }
