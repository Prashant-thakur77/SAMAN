"""What a scanned code is: one answer for a barcode, a label, a nameplate.

The person holding a part on the plant floor, or a box at the store gate, has
one question: *what is this, and do we already have it, under any name, in
any CPSE?* They have a phone or a barcode gun, and what they can give the
platform is a string: a GTIN off the packaging, a manufacturer's part number
off the race, one CPSE's own material code off a bin label, or the national
code off a label this platform printed. This module turns that string into
the material it names, with everything the person needs next: the code, the
names it carries elsewhere, where it is held, what it is fitted to, and which
substitutes an engineer has approved.

It resolves, it does not guess. A code is looked up by exact key in a fixed
order: the national code (its shape is unmistakable and its check digit says
whether it was read correctly), a CPSE's own code (an exact key of that
catalogue), a GTIN (check digit verified), and a manufacturer part number
(normalised the way the matcher normalises it). A part number may name more
than one material: the seeded bearings carry the same number across load
ratings, and the veto layer kept them apart for a reason. Then every one is
returned and the person chooses by the attribute that differs, rather than the
platform choosing for them. Nothing found is an honest answer with a next
step: type or photograph the description and let Smart-Create decide.

The engineer's version of the question starts from the other end: not a part
but a pump. Plants tag their equipment ("P-101B"), and the tag plate is what
is in front of them at two in the morning. A tag resolves to the equipment,
its criticality, and every spare on its bill of materials with how many are on
the shelf here and how many another CPSE holds under whatever name.
"""

from __future__ import annotations

import json

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import cnmc, inventory, substitutes
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
    Stock,
)
from .normalize import normalize_gtin, normalize_mpn
from .visibility import Scope

#: How a code was resolved, in the order it is tried. An equipment tag comes
#: last: tags are plant-local ("P-101B" exists at three CPSEs) and short, so a
#: material's own keys must have their say first.
METHODS = ("cnmc", "legacy_code", "gtin", "mpn", "bin", "equipment_tag")

#: A scanned string longer than this is not a code; it is a description, and
#: Smart-Create is the place for it.
MAX_CODE_LENGTH = 64


def lookup(db: Session, code: str, scope: Scope) -> dict:
    raw = code.strip()
    if not raw or len(raw) > MAX_CODE_LENGTH:
        return _nothing(
            raw, None, "A code is a short string; type a description into Smart-Create instead."
        )

    upper = raw.upper()
    if cnmc.CODE_PATTERN.match(upper):
        if not cnmc.is_valid(upper):
            return _nothing(
                raw,
                "cnmc",
                "That has the shape of a national code but its check digit does not "
                "verify: one digit was misread. Scan it again.",
            )
        record = db.execute(select(Cnmc).where(Cnmc.code == upper)).scalar_one_or_none()
        if record is None:
            return _nothing(raw, "cnmc", "No material carries that code.")
        golden = db.get(GoldenRecord, record.golden_id)
        return _found(db, raw, "cnmc", [golden.cluster_id], scope)

    legacy = (
        db.execute(
            select(Item.id)
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .where(func.upper(RawItem.legacy_code) == upper)
        )
        .scalars()
        .all()
    )
    if legacy:
        return _found(db, raw, "legacy_code", _clusters_of(db, legacy), scope, legacy)

    gtin = normalize_gtin(raw)
    if gtin:
        hits = db.execute(select(Item.id).where(Item.gtin == gtin)).scalars().all()
        if hits:
            return _found(db, raw, "gtin", _clusters_of(db, hits), scope, hits)

    mpn = normalize_mpn(raw)
    if mpn:
        hits = db.execute(select(Item.id).where(Item.mpn_norm == mpn)).scalars().all()
        if hits:
            return _found(db, raw, "mpn", _clusters_of(db, hits), scope, hits)

    # A bin label this CPSE bound to a material (stocktake.bind): the shelf
    # answers even when the part in it carries no code of its own.
    if scope.cpse_code:
        from .models import BinBinding

        bound = (
            db.execute(
                select(BinBinding)
                .join(Cpse, Cpse.id == BinBinding.cpse_id)
                .where(Cpse.code == scope.cpse_code, func.upper(BinBinding.bin_code) == upper)
            )
            .scalars()
            .first()
        )
        if bound is not None:
            return _found(db, raw, "bin", _clusters_of(db, [bound.item_id]), scope, [bound.item_id])

    equipment = (
        db.execute(select(Equipment).where(func.upper(Equipment.tag) == upper)).scalars().all()
    )
    if equipment:
        return _equipment_found(db, raw, equipment, scope)

    return _nothing(
        raw,
        None,
        "No catalogue row carries that code as a national code, a CPSE code, a GTIN, "
        "a part number or an equipment tag. If it is a description, Smart-Create can "
        "match it.",
    )


def _nothing(raw: str, tried: str | None, note: str) -> dict:
    return {
        "query": raw,
        "matched_by": None,
        "tried": tried,
        "materials": [],
        "equipment": [],
        "differs_on": [],
        "note": note,
        # A bare digit run of barcode length is handed over as the barcode
        # too, so Smart-Create anchors on it rather than reading it as words.
        "next": {
            "action": "smart_create",
            "to": f"/smart-create?description={raw}"
            + (f"&gtin={raw}" if raw.isdigit() and 8 <= len(raw) <= 14 else ""),
        },
    }


def _clusters_of(db: Session, item_ids: list[int]) -> list[int | None]:
    """Cluster ids for items, `None` for a row the pipeline has not clustered."""
    found = dict(
        db.execute(
            select(ClusterMember.item_id, ClusterMember.cluster_id).where(
                ClusterMember.item_id.in_(item_ids)
            )
        ).all()
    )
    seen: list[int | None] = []
    for item_id in item_ids:
        cluster_id = found.get(item_id)
        if cluster_id not in seen:
            seen.append(cluster_id)
    return seen


def _found(
    db: Session,
    raw: str,
    method: str,
    cluster_ids: list[int | None],
    scope: Scope,
    hit_items: list[int] | None = None,
) -> dict:
    materials = [_material(db, cluster_id, scope, hit_items or []) for cluster_id in cluster_ids]
    materials.sort(key=lambda m: (m["cnmc"] is None, m["std_description"] or ""))
    if len(materials) == 1:
        note = f"Matched by {_METHOD_NAMES[method]}."
        target = materials[0]
        nxt = (
            {"action": "open_cluster", "to": f"/clusters/{target['cluster_id']}"}
            if target["cluster_id"] is not None
            else {"action": "open_item", "to": f"/items/{target['members'][0]['item_id']}"}
        )
    else:
        note = (
            f"Matched by {_METHOD_NAMES[method]}, which {len(materials)} distinct materials "
            "share. They differ on an attribute the matcher refused to merge across; "
            "choose by it."
        )
        nxt = {"action": "choose", "to": None}
    return {
        "query": raw,
        "matched_by": method,
        "tried": method,
        "materials": materials,
        "equipment": [],
        # The attributes on which the materials differ: what the person reads
        # off the part to choose between them. Empty when there is one.
        "differs_on": _differs_on(materials),
        "note": note,
        "next": nxt,
    }


def _differs_on(materials: list[dict]) -> list[str]:
    if len(materials) < 2:
        return []
    keys = sorted({k for m in materials for k in m["attrs"]})

    def values(key: str) -> set[str]:
        return {json.dumps(m["attrs"].get(key), sort_keys=True) for m in materials}

    return [k for k in keys if len(values(k)) > 1]


_METHOD_NAMES = {
    "cnmc": "the national code",
    "legacy_code": "a CPSE's own material code",
    "gtin": "the GTIN",
    "mpn": "the manufacturer's part number",
    "bin": "a bin label bound to this material",
}


def _material(db: Session, cluster_id: int | None, scope: Scope, hit_items: list[int]) -> dict:
    """One material as the person at the bin needs it."""
    if cluster_id is None:
        member_ids = list(hit_items)
        golden = None
    else:
        member_ids = (
            db.execute(select(ClusterMember.item_id).where(ClusterMember.cluster_id == cluster_id))
            .scalars()
            .all()
        )
        golden = db.execute(
            select(GoldenRecord).where(GoldenRecord.cluster_id == cluster_id)
        ).scalar_one_or_none()
    code = (
        db.execute(select(Cnmc.code).where(Cnmc.golden_id == golden.id)).scalar_one_or_none()
        if golden
        else None
    )
    rows = db.execute(
        select(
            Item.id,
            Cpse.code,
            RawItem.legacy_code,
            RawItem.description,
            Item.class_code,
            Item.mpn_norm,
            Item.gtin,
            Item.attrs_json,
        )
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .where(Item.id.in_(member_ids))
        .order_by(Cpse.code, RawItem.legacy_code)
    ).all()
    members = [
        {
            "item_id": item_id,
            "cpse": cpse,
            "legacy_code": legacy_code,
            "description": description,
            "mpn": mpn,
            "gtin": gtin,
            "scanned": item_id in hit_items,
        }
        for item_id, cpse, legacy_code, description, _, mpn, gtin, _ in rows
    ]
    class_code = rows[0][4] if rows else "unclassified"
    # The attributes a person tells variants apart by, from the golden record
    # when there is one and from the scanned row otherwise.
    attrs = (
        json.loads(golden.attrs_json or "{}")
        if golden
        else (json.loads(rows[0][7] or "{}") if rows else {})
    )
    installed = substitutes.installed_on(db, member_ids)
    fitted = sorted(
        {(e["cpse"], e["tag"]): e for entries in installed.values() for e in entries}.values(),
        key=lambda e: (substitutes.CRITICALITY_ORDER.get(e["criticality"], 9), e["tag"]),
    )
    return {
        "cluster_id": cluster_id,
        "golden_id": golden.id if golden else None,
        "cnmc": code,
        "status": golden.status if golden else None,
        "std_description": golden.std_description if golden else (rows[0][3] if rows else None),
        "class_code": class_code,
        "family": code[:4] if code else cnmc.family_for(class_code)[0],
        "attrs": attrs,
        "members": members,
        "cpses": sorted({m["cpse"] for m in members}),
        "stock": inventory.consolidated_stock(db, cluster_id, scope) if cluster_id else None,
        "installed_on": fitted,
        "ved": substitutes.ved_of(fitted),
        "substitutes": _substitutes(db, member_ids),
    }


def _substitutes(db: Session, member_ids: list[int]) -> list[dict]:
    """Equivalences touching this material, approved ones first, each with
    the other side described so the person can go and fetch it."""
    if not member_ids:
        return []
    relations = (
        db.execute(
            select(Relation).where(
                Relation.rel_type.in_(("equivalent", "supersedes")),
                or_(Relation.item_a.in_(member_ids), Relation.item_b.in_(member_ids)),
            )
        )
        .scalars()
        .all()
    )
    if not relations:
        return []
    others = sorted({r.item_b if r.item_a in member_ids else r.item_a for r in relations})
    described = substitutes._describe(db, others)
    approvals = substitutes.approvals_for(db, [r.id for r in relations])
    out = []
    for r in relations:
        other = r.item_b if r.item_a in member_ids else r.item_a
        out.append(
            {
                "relation_id": r.id,
                "rel_type": r.rel_type,
                "direction": r.direction,
                "status": r.status,
                "confidence": r.confidence,
                "other": described.get(other, {"item_id": other}),
                "approval": approvals.get(r.id),
            }
        )
    order = {"approved": 0, "proposed": 1, "rejected": 2}
    out.sort(key=lambda s: (order.get(s["status"], 9), -(s["confidence"] or 0)))
    return out


def _equipment_found(db: Session, raw: str, equipment: list[Equipment], scope: Scope) -> dict:
    """A tag plate: the equipment at each CPSE that carries the tag, the
    signed-in person's own CPSE first, each with its spares and their stock."""
    cards = [_equipment(db, e, scope) for e in equipment]
    cards.sort(key=lambda c: (not scope.owns(c["cpse"]), c["cpse"]))
    if len(cards) == 1:
        note = f"Matched by the equipment tag at {cards[0]['cpse']}."
    else:
        note = (
            f"Matched by the equipment tag, which {len(cards)} CPSEs use for different "
            "plant. Tags are local to a plant; choose the site."
        )
    return {
        "query": raw,
        "matched_by": "equipment_tag",
        "tried": "equipment_tag",
        "materials": [],
        "equipment": cards,
        "differs_on": [],
        "note": note,
        "next": {"action": "choose_site" if len(cards) > 1 else "none", "to": None},
    }


def _equipment(db: Session, equipment: Equipment, scope: Scope) -> dict:
    cpse = db.get(Cpse, equipment.cpse_id)
    rows = db.execute(
        select(
            EquipmentBom.item_id,
            EquipmentBom.qty,
            RawItem.legacy_code,
            RawItem.description,
            Item.class_code,
            ClusterMember.cluster_id,
        )
        .join(Item, Item.id == EquipmentBom.item_id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .outerjoin(ClusterMember, ClusterMember.item_id == Item.id)
        .where(EquipmentBom.equipment_id == equipment.id)
        .order_by(RawItem.legacy_code)
    ).all()
    cluster_ids = [r[5] for r in rows if r[5] is not None]
    codes = (
        dict(
            db.execute(
                select(GoldenRecord.cluster_id, Cnmc.code)
                .join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
                .where(GoldenRecord.cluster_id.in_(cluster_ids))
            ).all()
        )
        if cluster_ids
        else {}
    )
    # Stock of the material (the whole cluster, every name it carries), split
    # into this plant's CPSE and everyone else's. The engineer wants to know
    # whether to walk to the store or ring a sister company.
    members_of: dict[int, list[int]] = {}
    if cluster_ids:
        for cluster_id, item_id in db.execute(
            select(ClusterMember.cluster_id, ClusterMember.item_id).where(
                ClusterMember.cluster_id.in_(cluster_ids)
            )
        ).all():
            members_of.setdefault(cluster_id, []).append(item_id)
    all_items = sorted({i for ids in members_of.values() for i in ids} | {r[0] for r in rows})
    stock_rows = (
        db.execute(
            select(Stock.item_id, Stock.cpse_id, func.sum(Stock.qty_on_hand))
            .where(Stock.item_id.in_(all_items))
            .group_by(Stock.item_id, Stock.cpse_id)
        ).all()
        if all_items
        else []
    )
    by_item: dict[int, dict[int, float]] = {}
    for item_id, cpse_id, qty in stock_rows:
        by_item.setdefault(item_id, {})[cpse_id] = float(qty or 0.0)

    def stock_split(item_id: int, cluster_id: int | None) -> tuple[float, float, int]:
        ids = members_of.get(cluster_id, [item_id]) if cluster_id is not None else [item_id]
        here = elsewhere = 0.0
        sites: set[int] = set()
        for member in ids:
            for cpse_id, qty in by_item.get(member, {}).items():
                if cpse_id == equipment.cpse_id:
                    here += qty
                elif qty > 0:
                    elsewhere += qty
                    sites.add(cpse_id)
        return round(here, 1), round(elsewhere, 1), len(sites)

    spares = []
    for item_id, qty, legacy_code, description, class_code, cluster_id in rows:
        here, elsewhere, sites = stock_split(item_id, cluster_id)
        spares.append(
            {
                "item_id": item_id,
                "cluster_id": cluster_id,
                "cnmc": codes.get(cluster_id),
                "legacy_code": legacy_code,
                "description": description,
                "class_code": class_code,
                "qty_fitted": qty,
                "stock_here": here,
                "stock_elsewhere": elsewhere,
                "cpses_elsewhere": sites,
            }
        )
    return {
        "id": equipment.id,
        "tag": equipment.tag,
        "description": equipment.description,
        "criticality": equipment.criticality,
        "ved": substitutes.VED.get(equipment.criticality),
        "cpse": cpse.code if cpse else None,
        "spares": spares,
    }
