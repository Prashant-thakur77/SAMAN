"""Two-way ERP migration — spec §2C.

    plan -> dry run -> impact check -> staged apply -> verify -> rollback

The steps that matter are the ones consolidations usually skip. A record with
open purchase orders is **held** rather than changed underneath a live
transaction. A superseded material is **blocked**, never deleted. And every
touched row is journaled with its before-image, so a batch can be put back
exactly as it was — which is asserted by hashing the ERP, not assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .erp import fingerprint, get_adapter
from .models import (
    ClusterMember,
    Cnmc,
    Cpse,
    GoldenRecord,
    Item,
    MigrationBatch,
    MigrationChange,
    RawItem,
    User,
)

STATE_PLANNED = "planned"
STATE_APPLIED = "applied"
STATE_HELD = "held"
STATE_ROLLED_BACK = "rolled_back"

#: What the UI colours the impact table with (§2C).
IMPACT_SAFE = "safe"
IMPACT_HOLD = "open_transactions"
IMPACT_CONFLICT = "valuation_conflict"

#: Blocking a material that still carries stock is ordinary — the stock is
#: consumed or transferred under the surviving code. What needs a human is
#: blocking one that would strand a *material* amount of value, so the flag has
#: a threshold rather than firing on any stock at all. Set above the median
#: position so the traffic light stays informative.
VALUATION_CONFLICT_VALUE = 5_000_000.0  # ₹50 lakh


@dataclass
class PlannedChange:
    matnr: str
    cpse: str
    legacy_code: str
    cluster_id: int
    cnmc: str
    action: str  # crossref | block
    surviving_matnr: str | None = None
    impact: str = IMPACT_SAFE
    open_po_lines: int = 0
    open_qty: float = 0.0
    stock_qty: float = 0.0
    total_value: float = 0.0
    before: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "matnr": self.matnr,
            "cpse": self.cpse,
            "legacy_code": self.legacy_code,
            "cluster_id": self.cluster_id,
            "cnmc": self.cnmc,
            "action": self.action,
            "surviving_matnr": self.surviving_matnr,
            "impact": self.impact,
            "open_po_lines": self.open_po_lines,
            "open_qty": self.open_qty,
            "stock_qty": self.stock_qty,
            "total_value": self.total_value,
            "before": self.before,
        }


def _coded_clusters(db: Session, cluster_ids: list[int] | None = None) -> list[tuple[int, str]]:
    """Clusters whose golden record carries an issued CNMC."""
    query = (
        select(GoldenRecord.cluster_id, Cnmc.code)
        .join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
        .where(GoldenRecord.status == "approved")
    )
    if cluster_ids:
        query = query.where(GoldenRecord.cluster_id.in_(cluster_ids))
    return list(db.execute(query.order_by(GoldenRecord.cluster_id)).all())


def plan(db: Session, cluster_ids: list[int] | None = None, adapter=None) -> dict:
    """Build the change set from approved, coded clusters (§2C).

    One member survives as the master and receives the cross-reference; the rest
    are blocked against it. The survivor is the row with the most stock, because
    that is the record the organisation is actually transacting on.
    """
    adapter = adapter or get_adapter()
    coded = _coded_clusters(db, cluster_ids)
    if not coded:
        return {
            "changes": [],
            "clusters": 0,
            "note": (
                "Nothing to migrate: a cluster is only planned once its golden "
                "record is approved and carries a CNMC."
            ),
        }

    members = db.execute(
        select(ClusterMember.cluster_id, RawItem.legacy_code, Cpse.code)
        .join(Item, Item.id == ClusterMember.item_id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .where(ClusterMember.cluster_id.in_([c for c, _ in coded]))
    ).all()

    by_cluster: dict[int, list[tuple[str, str]]] = {}
    for cluster_id, legacy_code, cpse in members:
        by_cluster.setdefault(cluster_id, []).append((cpse, legacy_code))

    all_matnrs = [f"{cpse}-{code}" for rows in by_cluster.values() for cpse, code in rows]
    transactions = adapter.read_open_transactions(all_matnrs)
    masters = adapter.read_masters(all_matnrs)

    changes: list[PlannedChange] = []
    for cluster_id, cnmc in coded:
        rows = by_cluster.get(cluster_id, [])
        if not rows:
            continue
        # The record with the most stock survives; ties broken deterministically.
        ranked = sorted(
            rows,
            key=lambda pair: (
                -transactions[f"{pair[0]}-{pair[1]}"].stock_qty,
                f"{pair[0]}-{pair[1]}",
            ),
        )
        survivor_cpse, survivor_code = ranked[0]
        survivor = f"{survivor_cpse}-{survivor_code}"

        for cpse, legacy_code in ranked:
            matnr = f"{cpse}-{legacy_code}"
            impact_row = transactions[matnr]
            change = PlannedChange(
                matnr=matnr,
                cpse=cpse,
                legacy_code=legacy_code,
                cluster_id=cluster_id,
                cnmc=cnmc,
                action="crossref" if matnr == survivor else "block",
                surviving_matnr=None if matnr == survivor else survivor,
                open_po_lines=impact_row.open_po_lines,
                open_qty=impact_row.open_qty,
                stock_qty=impact_row.stock_qty,
                total_value=impact_row.total_value,
                before=masters.get(matnr, {}),
            )
            if impact_row.blocks_change:
                # Held by default: never change a material underneath an open
                # purchase order. This is the step consolidations get wrong.
                change.impact = IMPACT_HOLD
            elif (
                change.action == "block"
                and impact_row.stock_qty > 0
                and impact_row.total_value >= VALUATION_CONFLICT_VALUE
            ):
                # Blocking a material holding this much value needs someone to
                # say where the value goes before the code is retired.
                change.impact = IMPACT_CONFLICT
            changes.append(change)

    return {
        "clusters": len(coded),
        "changes": [c.as_dict() for c in changes],
        "summary": _summarise(changes),
        "thresholds": {
            "valuation_conflict_value": VALUATION_CONFLICT_VALUE,
            "note": (
                "A record with open purchase orders is always held. A block is "
                "flagged for review when it would strand stock worth more than "
                f"₹{VALUATION_CONFLICT_VALUE:,.0f}."
            ),
        },
        "note": (
            "One member survives as the master and receives the cross-reference; "
            "the rest are blocked against it. Nothing is deleted."
        ),
    }


def _summarise(changes: list[PlannedChange]) -> dict:
    return {
        "total": len(changes),
        "crossref": sum(1 for c in changes if c.action == "crossref"),
        "block": sum(1 for c in changes if c.action == "block"),
        "safe": sum(1 for c in changes if c.impact == IMPACT_SAFE),
        "held_open_transactions": sum(1 for c in changes if c.impact == IMPACT_HOLD),
        "valuation_conflict": sum(1 for c in changes if c.impact == IMPACT_CONFLICT),
    }


#: Exceptions first. A reviewer scrolling a 12,000-row plan should meet the
#: stranded valuations and the held purchase orders before the safe majority.
IMPACT_ORDER = {IMPACT_CONFLICT: 0, IMPACT_HOLD: 1, IMPACT_SAFE: 2}

#: The default window the API returns. A full national rollout plans one change
#: per catalogue row -- 11,778 on the demo profile and 150,000 on the benchmark
#: one -- and neither the wire nor the browser should be handed all of them.
DEFAULT_PAGE = 200
MAX_PAGE = 2_000


def paginate(planned: dict, limit: int | None = DEFAULT_PAGE, offset: int = 0) -> dict:
    """Return a window of the change set with every total left intact.

    The summary, `would_apply` and `would_hold` are computed over the whole
    plan and stay that way: a paginated count is a wrong count, and the traffic
    light is the reason anyone opens this screen.
    """
    changes = sorted(
        planned["changes"],
        key=lambda c: (IMPACT_ORDER.get(c["impact"], 9), c["matnr"]),
    )
    total = len(changes)
    offset = max(0, offset)
    window = changes[offset:] if limit is None else changes[offset : offset + limit]
    return {
        **planned,
        "changes": window,
        "total_changes": total,
        "offset": offset,
        "limit": limit,
        "truncated": len(window) < total,
    }


def dry_run(db: Session, cluster_ids: list[int] | None = None, adapter=None) -> dict:
    """The plan, plus the per-record diff the apply would write (§2C)."""
    adapter = adapter or get_adapter()
    planned = plan(db, cluster_ids, adapter)
    for change in planned["changes"]:
        before = change["before"]
        after = dict(before)
        if change["action"] == "crossref":
            after["zz_cnmc"] = change["cnmc"]
        else:
            after["lvorm"] = "X"
            after["zz_supersedes"] = change["surviving_matnr"]
        change["after"] = after
        change["diff"] = {
            key: {"before": before.get(key), "after": after.get(key)}
            for key in ("lvorm", "zz_cnmc", "zz_supersedes")
            if before.get(key) != after.get(key)
        }
        change["will_apply"] = change["impact"] == IMPACT_SAFE
    planned["would_apply"] = sum(1 for c in planned["changes"] if c["will_apply"])
    planned["would_hold"] = len(planned["changes"]) - planned["would_apply"]
    planned["erp_fingerprint"] = fingerprint()
    return planned


def apply(
    db: Session,
    user: User,
    cluster_ids: list[int] | None = None,
    include_held: bool = False,
    adapter=None,
) -> dict:
    """Write the safe changes to the ERP, journaling every row (§2C).

    Idempotent: a change whose after-image already matches the ERP is recorded
    as applied without writing again, so a retried batch cannot double-apply.
    """
    adapter = adapter or get_adapter()
    preview = dry_run(db, cluster_ids, adapter)
    before_fingerprint = preview["erp_fingerprint"]

    batch = MigrationBatch(status="applying", created_by=user.id)
    db.add(batch)
    db.flush()

    applied = held = skipped = 0
    # One read for the whole batch, and the writes collected for one round trip
    # each. Row-at-a-time cost an fsync per material and turned a 2,000-row
    # rollout into a fourteen-second blocking request.
    targets = [c["matnr"] for c in preview["changes"] if c["will_apply"] or include_held]
    current_masters = adapter.read_masters(targets)
    crossrefs: list[tuple[str, str]] = []
    blocks: list[tuple[str, str]] = []

    for change in preview["changes"]:
        if not change["will_apply"] and not include_held:
            db.add(
                MigrationChange(
                    batch_id=batch.id,
                    erp_table="mara",
                    erp_key=change["matnr"],
                    before_json=json.dumps(change["before"], sort_keys=True),
                    after_json=None,
                    state=STATE_HELD,
                )
            )
            held += 1
            continue

        current = current_masters.get(change["matnr"], {})
        if all(current.get(k) == v for k, v in change["after"].items()):
            skipped += 1  # already in the target state
        elif change["action"] == "crossref":
            crossrefs.append((change["matnr"], change["cnmc"]))
        else:
            blocks.append((change["matnr"], change["surviving_matnr"]))

        db.add(
            MigrationChange(
                batch_id=batch.id,
                erp_table="mara",
                erp_key=change["matnr"],
                before_json=json.dumps(change["before"], sort_keys=True),
                after_json=json.dumps(change["after"], sort_keys=True),
                state=STATE_APPLIED,
            )
        )
        applied += 1

    _write_crossrefs(adapter, crossrefs)
    _block_materials(adapter, blocks)

    batch.status = "applied"
    audit.record(
        db,
        action="migration.apply",
        entity=f"migration_batch:{batch.id}",
        payload={
            "batch_id": batch.id,
            "applied": applied,
            "held": held,
            "already_in_state": skipped,
            "erp_before": before_fingerprint,
            "erp_after": fingerprint(),
        },
        user=user.email,
        commit=False,
    )
    db.commit()

    return {
        "batch_id": batch.id,
        "applied": applied,
        "held": held,
        "already_in_state": skipped,
        "erp_fingerprint_before": before_fingerprint,
        "erp_fingerprint_after": fingerprint(),
    }


def _write_crossrefs(adapter, pairs: list[tuple[str, str]]) -> None:
    """Bulk if the adapter offers it, row-at-a-time if not.

    The Protocol declares the bulk forms, but an adapter written against an
    older revision -- or a test double -- may only have the singular ones, and
    a migration that refused to run against it would be the wrong failure.
    """
    bulk = getattr(adapter, "write_crossref_many", None)
    if bulk is not None:
        bulk(pairs)
        return
    for matnr, cnmc in pairs:
        adapter.write_crossref(matnr, cnmc)


def _block_materials(adapter, pairs: list[tuple[str, str]]) -> None:
    bulk = getattr(adapter, "block_material_many", None)
    if bulk is not None:
        bulk(pairs)
        return
    for matnr, supersedes in pairs:
        adapter.block_material(matnr, supersedes)


def _restore(adapter, rows: list[tuple[str, dict]]) -> None:
    bulk = getattr(adapter, "restore_many", None)
    if bulk is not None:
        bulk(rows)
        return
    for matnr, before in rows:
        adapter.restore(matnr, before)


def rollback(db: Session, batch_id: int, user: User, adapter=None) -> dict:
    """Restore every applied row in a batch from its before-image (§2C)."""
    adapter = adapter or get_adapter()
    batch = db.get(MigrationBatch, batch_id)
    if batch is None:
        raise ValueError(f"no migration batch {batch_id}")

    changes = (
        db.execute(
            select(MigrationChange).where(
                MigrationChange.batch_id == batch_id, MigrationChange.state == STATE_APPLIED
            )
        )
        .scalars()
        .all()
    )

    before_fingerprint = fingerprint()
    _restore(adapter, [(c.erp_key, json.loads(c.before_json or "{}")) for c in changes])
    for change in changes:
        change.state = STATE_ROLLED_BACK

    batch.status = "rolled_back"
    after_fingerprint = fingerprint()
    audit.record(
        db,
        action="migration.rollback",
        entity=f"migration_batch:{batch_id}",
        payload={
            "batch_id": batch_id,
            "restored": len(changes),
            "erp_before": before_fingerprint,
            "erp_after": after_fingerprint,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return {
        "batch_id": batch_id,
        "restored": len(changes),
        "erp_fingerprint": after_fingerprint,
    }


def verify(db: Session, batch_id: int, adapter=None) -> dict:
    """Re-diff a batch against the ERP: is it still in the state we wrote?"""
    adapter = adapter or get_adapter()
    changes = (
        db.execute(select(MigrationChange).where(MigrationChange.batch_id == batch_id))
        .scalars()
        .all()
    )
    if not changes:
        return {"batch_id": batch_id, "checked": 0, "in_sync": True, "drifted": []}

    current = adapter.read_masters([c.erp_key for c in changes])
    drifted = []
    checked = 0
    for change in changes:
        expected_json = change.after_json if change.state == STATE_APPLIED else change.before_json
        if not expected_json:
            continue
        checked += 1
        expected = json.loads(expected_json)
        actual = current.get(change.erp_key, {})
        differences = {
            key: {"expected": expected.get(key), "actual": actual.get(key)}
            for key in ("lvorm", "zz_cnmc", "zz_supersedes")
            if expected.get(key) != actual.get(key)
        }
        if differences:
            drifted.append({"matnr": change.erp_key, "differences": differences})

    return {
        "batch_id": batch_id,
        "checked": checked,
        "in_sync": not drifted,
        "drifted": drifted,
    }


def batches(db: Session) -> dict:
    rows = db.execute(
        select(
            MigrationBatch.id,
            MigrationBatch.status,
            MigrationBatch.ts,
            func.count(MigrationChange.id),
        )
        .outerjoin(MigrationChange, MigrationChange.batch_id == MigrationBatch.id)
        .group_by(MigrationBatch.id)
        .order_by(MigrationBatch.id.desc())
    ).all()
    return {
        "batches": [
            {"id": i, "status": s, "ts": ts.isoformat(), "changes": n} for i, s, ts, n in rows
        ]
    }


def batch_detail(db: Session, batch_id: int) -> dict:
    batch = db.get(MigrationBatch, batch_id)
    if batch is None:
        raise ValueError(f"no migration batch {batch_id}")
    changes = (
        db.execute(
            select(MigrationChange)
            .where(MigrationChange.batch_id == batch_id)
            .order_by(MigrationChange.id)
        )
        .scalars()
        .all()
    )
    return {
        "id": batch.id,
        "status": batch.status,
        "ts": batch.ts.isoformat(),
        "changes": [
            {
                "erp_table": c.erp_table,
                "erp_key": c.erp_key,
                "state": c.state,
                "before": json.loads(c.before_json or "{}"),
                "after": json.loads(c.after_json) if c.after_json else None,
            }
            for c in changes
        ],
        "verification": verify(db, batch_id),
    }


# --------------------------------------------------------------------------
# Load files: the first rollout, applied by a basis team (docs/sap-integration.md)
# --------------------------------------------------------------------------

LOADFILE_README = """SAMAN -> SAP load files
=======================

Generated from a dry run of the migration plan. One row per planned change,
in SAP field names, for an LSMW recording or an LTMC (Migration Cockpit)
project. Map the columns once; every later batch uses the same layout.

crossref.csv  {crossref} surviving masters
    MATNR            the material that keeps transacting
    ZZ_CNMC          the national code (append field on MARA, CHAR 20)
    UNSPSC, HSN      the class's public codes, for classification and GST
    CNMC_DESCRIPTION the standardised description (MAKT, if the site adopts it)

block.csv     {block} superseded materials
    MATNR            the material being retired
    LVORM            X: deletion flag set. Blocked, never deleted.
    ZZ_SUPERSEDES    the surviving master (append field on MARA, CHAR 18)
    ZZ_CNMC          the national code, so a blocked row still resolves

held.csv      {held} rows NOT to load
    Materials with open purchase order lines, or a valuation the plan holds
    for review. Resolve them in SAMAN and export again.

After loading, run Verify on SAMAN's Migration screen: it re-reads the ERP
against the journal and reports any drift.
"""


def load_files(db: Session, planned: dict) -> bytes:
    """A zip of the dry run's changes as CSVs in SAP field names."""
    import csv
    import io
    import zipfile

    from .taxonomy import get_schema

    changes = planned.get("changes", [])
    cluster_ids = {c["cluster_id"] for c in changes}
    info: dict[int, tuple[str, dict]] = {}
    if cluster_ids:
        rows = db.execute(
            select(GoldenRecord.cluster_id, GoldenRecord.std_description, Item.class_code)
            .join(ClusterMember, ClusterMember.cluster_id == GoldenRecord.cluster_id)
            .join(Item, Item.id == ClusterMember.item_id)
            .where(GoldenRecord.cluster_id.in_(cluster_ids))
        ).all()
        for cluster_id, text, class_code in rows:
            info.setdefault(cluster_id, (text, get_schema(class_code).standards))

    crossref, block, held = io.StringIO(), io.StringIO(), io.StringIO()
    w_cross = csv.writer(crossref)
    w_block = csv.writer(block)
    w_held = csv.writer(held)
    w_cross.writerow(["MATNR", "ZZ_CNMC", "UNSPSC", "HSN", "CNMC_DESCRIPTION"])
    w_block.writerow(["MATNR", "LVORM", "ZZ_SUPERSEDES", "ZZ_CNMC"])
    w_held.writerow(["MATNR", "ACTION", "IMPACT", "OPEN_PO_LINES", "OPEN_QTY", "ZZ_CNMC"])
    counts = {"crossref": 0, "block": 0, "held": 0}
    for change in changes:
        will_apply = change.get("will_apply", change.get("impact") == IMPACT_SAFE)
        if not will_apply:
            w_held.writerow(
                [
                    change["matnr"],
                    change["action"],
                    change["impact"],
                    change.get("open_po_lines", 0),
                    change.get("open_qty", 0),
                    change["cnmc"],
                ]
            )
            counts["held"] += 1
        elif change["action"] == "crossref":
            text, standards = info.get(change["cluster_id"], ("", {}))
            w_cross.writerow(
                [
                    change["matnr"],
                    change["cnmc"],
                    (standards.get("unspsc") or {}).get("code", ""),
                    (standards.get("hsn") or {}).get("code", ""),
                    text,
                ]
            )
            counts["crossref"] += 1
        else:
            w_block.writerow([change["matnr"], "X", change["surviving_matnr"], change["cnmc"]])
            counts["block"] += 1

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("crossref.csv", crossref.getvalue())
        archive.writestr("block.csv", block.getvalue())
        archive.writestr("held.csv", held.getvalue())
        archive.writestr("README.txt", LOADFILE_README.format(**counts))
    return buffer.getvalue()
