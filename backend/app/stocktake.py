"""Stock counts and bin bindings from the Scan screen (spec §5, the floor).

The storekeeper's real daily job is not looking a part up; it is walking the
store with a device and counting. Two things make that work here:

* **Bin binding.** A shelf has a label of its own. Bind it once to the
  material it holds and every later scan of the bin answers with that
  material, its system quantity at this plant, and where else it is held —
  whether or not the part in the bin carries any code.
* **Stock count.** Scan, count, next. Each line records what the shelf said
  beside what the system said at that moment, under a session that groups
  one walk through the store. The count changes nothing in the stock table:
  a variance is a fact for a person to reconcile, and the session's summary
  is what they reconcile from.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit, scan
from .models import (
    BinBinding,
    ClusterMember,
    Cpse,
    GoldenRecord,
    Item,
    RawItem,
    Stock,
    StockCount,
    User,
)
from .visibility import Scope


def plants_for(db: Session, cpse_id: int) -> list[str]:
    """The plants a CPSE holds stock at, most positions first."""
    rows = db.execute(
        select(Stock.plant, func.count(Stock.id))
        .where(Stock.cpse_id == cpse_id)
        .group_by(Stock.plant)
        .order_by(func.count(Stock.id).desc())
    ).all()
    return [plant for plant, _ in rows]


def _resolve(db: Session, code: str, scope: Scope, cpse_id: int, plant: str) -> dict | None:
    """The single material a code names: a bound bin first, then the usual
    lookup order. None when nothing resolves or several materials share it."""
    binding = db.execute(
        select(BinBinding).where(
            BinBinding.cpse_id == cpse_id,
            BinBinding.plant == plant,
            func.upper(BinBinding.bin_code) == code.strip().upper(),
        )
    ).scalar_one_or_none()
    if binding is not None:
        return {
            "item_id": binding.item_id,
            "cluster_id": binding.cluster_id,
            "matched_by": "bin",
            "bin_code": binding.bin_code,
        }
    found = scan.lookup(db, code, scope)
    if len(found["materials"]) != 1:
        return None
    material = found["materials"][0]
    # Prefer this CPSE's own row for the position; any member otherwise.
    own = next((m for m in material["members"] if m["cpse"] == scope.cpse_code), None)
    member = own or material["members"][0]
    return {
        "item_id": member["item_id"],
        "cluster_id": material["cluster_id"],
        "matched_by": found["matched_by"],
        "bin_code": None,
    }


def _system_qty(db: Session, cpse_id: int, plant: str, cluster_id: int | None, item_id: int):
    """What the system says is on this plant's shelf for the material: every
    member of the cluster this CPSE holds here, summed; the one item if it
    is unclustered."""
    items = (
        db.execute(select(ClusterMember.item_id).where(ClusterMember.cluster_id == cluster_id))
        .scalars()
        .all()
        if cluster_id is not None
        else [item_id]
    )
    return db.execute(
        select(func.sum(Stock.qty_on_hand)).where(
            Stock.cpse_id == cpse_id, Stock.plant == plant, Stock.item_id.in_(items)
        )
    ).scalar()


def _describe(db: Session, item_id: int, cluster_id: int | None) -> dict:
    row = db.execute(
        select(RawItem.legacy_code, RawItem.description, Cpse.code)
        .join(Item, Item.raw_item_id == RawItem.id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .where(Item.id == item_id)
    ).first()
    golden = (
        db.execute(
            select(GoldenRecord.std_description).where(GoldenRecord.cluster_id == cluster_id)
        ).scalar_one_or_none()
        if cluster_id is not None
        else None
    )
    return {
        "legacy_code": row[0] if row else None,
        "description": golden or (row[1] if row else None),
        "cpse": row[2] if row else None,
    }


def count(
    db: Session,
    user: User,
    scope: Scope,
    session_id: str,
    code: str,
    counted_qty: float,
    plant: str,
    bin_code: str | None = None,
    note: str | None = None,
) -> dict:
    """Record one counted line and return it with its variance."""
    if user.cpse_id is None:
        raise PermissionError("A stock count belongs to a CPSE; sign in as its steward.")
    resolved = _resolve(db, code, scope, user.cpse_id, plant)
    if resolved is None:
        raise LookupError(
            f"{code!r} does not name one material here: nothing carries it, or several "
            "materials share it. Look it up first and bind the bin."
        )
    system = _system_qty(db, user.cpse_id, plant, resolved["cluster_id"], resolved["item_id"])
    line = StockCount(
        session_id=session_id,
        counted_by=user.id,
        cpse_id=user.cpse_id,
        plant=plant,
        bin_code=bin_code or resolved["bin_code"],
        code=code.strip(),
        item_id=resolved["item_id"],
        cluster_id=resolved["cluster_id"],
        counted_qty=float(counted_qty),
        system_qty=float(system) if system is not None else None,
        note=note,
    )
    db.add(line)
    db.flush()
    audit.record(
        db,
        action="stock.count",
        entity=f"stock_count:{line.id}",
        payload={
            "session": session_id,
            "plant": plant,
            "code": line.code,
            "bin": line.bin_code,
            "cluster_id": line.cluster_id,
            "counted": line.counted_qty,
            "system": line.system_qty,
            "matched_by": resolved["matched_by"],
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return _line(db, line, resolved["matched_by"])


def _line(db: Session, line: StockCount, matched_by: str | None = None) -> dict:
    variance = round(line.counted_qty - line.system_qty, 3) if line.system_qty is not None else None
    return {
        "id": line.id,
        "counted_at": line.counted_at.isoformat(),
        "plant": line.plant,
        "bin_code": line.bin_code,
        "code": line.code,
        "matched_by": matched_by,
        "cluster_id": line.cluster_id,
        "item_id": line.item_id,
        **_describe(db, line.item_id, line.cluster_id),
        "counted_qty": line.counted_qty,
        "system_qty": line.system_qty,
        "variance": variance,
        "note": line.note,
    }


def session(db: Session, user: User, session_id: str) -> dict:
    """One walk through the store: its lines and the totals a reconciler needs."""
    lines = (
        db.execute(
            select(StockCount)
            .where(StockCount.session_id == session_id, StockCount.cpse_id == user.cpse_id)
            .order_by(StockCount.id)
        )
        .scalars()
        .all()
    )
    rows = [_line(db, line) for line in lines]
    with_system = [r for r in rows if r["variance"] is not None]
    return {
        "session_id": session_id,
        "lines": rows,
        "totals": {
            "lines": len(rows),
            "counted": round(sum(r["counted_qty"] for r in rows), 3),
            "system": round(sum(r["system_qty"] for r in with_system), 3),
            "over": sum(1 for r in with_system if r["variance"] > 0),
            "short": sum(1 for r in with_system if r["variance"] < 0),
            "exact": sum(1 for r in with_system if r["variance"] == 0),
            "unknown_to_system": len(rows) - len(with_system),
        },
        "note": (
            "Counts record what the shelf said beside what the system said at that "
            "moment; the stock table is not changed. Reconcile from this list."
        ),
    }


def bind(db: Session, user: User, scope: Scope, plant: str, bin_code: str, code: str) -> dict:
    """Bind a bin to the material a code names; rebinding replaces and audits."""
    if user.cpse_id is None:
        raise PermissionError("A bin belongs to a CPSE; sign in as its steward.")
    found = scan.lookup(db, code, scope)
    if len(found["materials"]) != 1:
        raise LookupError(f"{code!r} does not name exactly one material; a bin is bound to one.")
    material = found["materials"][0]
    own = next((m for m in material["members"] if m["cpse"] == scope.cpse_code), None)
    member = own or material["members"][0]
    bin_key = bin_code.strip()
    existing = db.execute(
        select(BinBinding).where(
            BinBinding.cpse_id == user.cpse_id,
            BinBinding.plant == plant,
            func.upper(BinBinding.bin_code) == bin_key.upper(),
        )
    ).scalar_one_or_none()
    before = {"cluster_id": existing.cluster_id, "item_id": existing.item_id} if existing else None
    if existing is None:
        existing = BinBinding(cpse_id=user.cpse_id, plant=plant, bin_code=bin_key)
        db.add(existing)
    existing.cluster_id = material["cluster_id"]
    existing.item_id = member["item_id"]
    existing.bound_by = user.id
    existing.bound_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        action="bin.bind",
        entity=f"bin:{plant}/{bin_key}",
        payload={
            "before": before,
            "after": {"cluster_id": existing.cluster_id, "item_id": existing.item_id},
            "code": code,
        },
        user=user.email,
        commit=False,
    )
    db.commit()
    return {
        "bin_code": bin_key,
        "plant": plant,
        "cluster_id": existing.cluster_id,
        "item_id": existing.item_id,
        **_describe(db, existing.item_id, existing.cluster_id),
        "replaced": before is not None,
    }


def bindings(db: Session, user: User, plant: str | None = None) -> list[dict]:
    query = select(BinBinding).where(BinBinding.cpse_id == user.cpse_id)
    if plant:
        query = query.where(BinBinding.plant == plant)
    rows = db.execute(query.order_by(BinBinding.plant, BinBinding.bin_code)).scalars().all()
    return [
        {
            "bin_code": b.bin_code,
            "plant": b.plant,
            "cluster_id": b.cluster_id,
            "item_id": b.item_id,
            "bound_at": b.bound_at.isoformat(),
            **_describe(db, b.item_id, b.cluster_id),
        }
        for b in rows
    ]


def rehome(db: Session) -> int:
    """After a pipeline run rebuilt the clusters, refresh each binding's
    cluster from the row it is bound to."""
    current = dict(db.execute(select(ClusterMember.item_id, ClusterMember.cluster_id)).all())
    moved = 0
    for binding in db.execute(select(BinBinding)).scalars():
        cluster_id = current.get(binding.item_id)
        if cluster_id != binding.cluster_id:
            binding.cluster_id = cluster_id
            moved += 1
    db.commit()
    return moved
