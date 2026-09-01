"""Directed equivalence, substitution rules and OEM cross-references — §5, §2B.

Equivalents are presented as a *directed* relation, never as a merge: the item
page shows "Duplicates (merged into this CNMC)" and "Equivalents (separate
CNMC, interchangeable)" as two separate blocks, and nothing here touches a
cluster.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import insert, or_, select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..db import get_db
from ..equivalence import BASIS_CONFIDENCE, parse_rules
from ..models import Cnmc, Crossref, GoldenRecord, Item, RawItem, Relation, SubstitutionRule, User
from ..normalize import normalize_mpn

router = APIRouter(tags=["equivalence"])


class RelationIn(BaseModel):
    item_a: int
    item_b: int
    rel_type: str = "equivalent"  # equivalent | supersedes
    direction: str = "bidirectional"  # bidirectional | a_to_b | b_to_a
    note: str | None = None


class RuleIn(BaseModel):
    class_code: str
    rule_yaml: str
    active: bool = True


def _describe(db: Session, item_id: int) -> dict:
    row = db.execute(
        select(Item.id, Item.norm_text, Item.class_code, RawItem.legacy_code)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .where(Item.id == item_id)
    ).first()
    if row is None:
        return {"item_id": item_id}
    code = db.execute(
        select(Cnmc.code)
        .join(GoldenRecord, GoldenRecord.id == Cnmc.golden_id)
        .join(Item, Item.id == item_id)
        .limit(1)
    ).scalar()
    return {
        "item_id": row[0],
        "description": row[1],
        "class_code": row[2],
        "legacy_code": row[3],
        "cnmc": code,
    }


@router.get("/relations")
def list_relations(
    item: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    """Relations touching an item, phrased from that item's point of view."""
    query = select(Relation)
    if item is not None:
        query = query.where(or_(Relation.item_a == item, Relation.item_b == item))
    rows = db.execute(query.order_by(Relation.confidence.desc()).limit(limit)).scalars().all()

    out = []
    for relation in rows:
        other = (
            relation.item_b
            if item is not None and relation.item_a == item
            else relation.item_a
        )
        # Restate the direction so the UI can render one arrow without
        # re-deriving which side the reader is standing on.
        if relation.direction == "bidirectional":
            reading = "interchangeable in both directions"
        elif item is None:
            reading = (
                f"item {relation.item_b} can substitute item {relation.item_a}"
                if relation.direction == "a_to_b"
                else f"item {relation.item_a} can substitute item {relation.item_b}"
            )
        else:
            substitutes_this = (
                relation.direction == "a_to_b" and relation.item_b == item
            ) or (relation.direction == "b_to_a" and relation.item_a == item)
            reading = (
                "this item can substitute the other"
                if substitutes_this
                else "the other item can substitute this one"
            )
        out.append(
            {
                "id": relation.id,
                "rel_type": relation.rel_type,
                "direction": relation.direction,
                "basis": relation.basis,
                "confidence": relation.confidence,
                "status": relation.status,
                "reading": reading,
                "evidence": json.loads(relation.evidence_json or "{}"),
                "counterpart": _describe(db, other),
            }
        )
    return {"item": item, "count": len(out), "relations": out}


@router.post("/relations")
def propose_relation(
    body: RelationIn,
    user: Annotated[User, Depends(require_roles("steward", "registrar", "admin"))],
    db: Session = Depends(get_db),
) -> dict:
    """A steward proposes a relation by hand. Always `proposed`, never active."""
    if body.rel_type not in ("equivalent", "supersedes"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown relation type.")
    if body.direction not in ("bidirectional", "a_to_b", "b_to_a"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown direction.")
    if body.item_a == body.item_b:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "An item cannot relate to itself."
        )
    for item_id in (body.item_a, body.item_b):
        if db.get(Item, item_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No item {item_id}.")

    relation = Relation(
        item_a=body.item_a,
        item_b=body.item_b,
        rel_type=body.rel_type,
        direction=body.direction,
        confidence=BASIS_CONFIDENCE["rule"],
        basis="rule",
        evidence_json=json.dumps(
            {"source": "proposed by a steward", "by": user.name, "note": body.note},
            sort_keys=True,
        ),
        status="proposed",
    )
    db.add(relation)
    db.commit()
    return {"id": relation.id, "status": relation.status}


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)) -> dict:
    """The substitution rule DSL, as data a steward can read and edit (§2B)."""
    rows = db.execute(select(SubstitutionRule).order_by(SubstitutionRule.class_code)).scalars()
    out = []
    for rule in rows:
        parsed = parse_rules(rule.rule_yaml)
        out.append(
            {
                "id": rule.id,
                "class_code": rule.class_code,
                "active": rule.active,
                "author": rule.author,
                "rule_yaml": rule.rule_yaml,
                "parsed": [
                    {
                        "class": r.class_code,
                        "equivalent_if": [str(c) for c in r.equivalent_if],
                        "substitutable_if": [str(c) for c in r.substitutable_if],
                        "never_if": [str(c) for c in r.never_if],
                    }
                    for r in parsed
                ],
                "valid": bool(parsed),
            }
        )
    return {"count": len(out), "rules": out}


@router.post("/rules")
def upsert_rule(
    body: RuleIn,
    user: Annotated[User, Depends(require_roles("registrar", "admin"))],
    db: Session = Depends(get_db),
) -> dict:
    """Add or replace a class's rules. Rejected if the DSL does not parse."""
    parsed = parse_rules(body.rule_yaml)
    if not parsed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The rule did not parse. Each entry needs a `class` and at least one "
            "of equivalent_if / substitutable_if / never_if.",
        )

    existing = db.execute(
        select(SubstitutionRule).where(SubstitutionRule.class_code == body.class_code)
    ).scalar_one_or_none()
    if existing:
        existing.rule_yaml = body.rule_yaml
        existing.active = body.active
        existing.author = user.name
        rule_id = existing.id
    else:
        rule = SubstitutionRule(
            class_code=body.class_code,
            rule_yaml=body.rule_yaml,
            author=user.name,
            active=body.active,
        )
        db.add(rule)
        db.flush()
        rule_id = rule.id
    db.commit()
    return {"id": rule_id, "class_code": body.class_code, "conditions": len(parsed)}


@router.post("/crossref/import")
async def import_crossref(
    user: Annotated[User, Depends(require_roles("steward", "registrar", "admin"))],
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
) -> dict:
    """Load an OEM interchange table as CSV (§2B source 2).

    Expected columns: mpn_a, brand_a, mpn_b, brand_b.
    """
    payload = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(payload))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    required = {"mpn_a", "mpn_b"}
    if not required <= headers:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Needs at least columns {sorted(required)}; got {sorted(headers)}.",
        )

    existing = {
        (a, b) for a, b in db.execute(select(Crossref.mpn_a, Crossref.mpn_b)).all()
    }
    rows, rejected = [], 0
    for record in reader:
        lower = {k.strip().lower(): (v or "").strip() for k, v in record.items()}
        mpn_a, mpn_b = normalize_mpn(lower.get("mpn_a")), normalize_mpn(lower.get("mpn_b"))
        if not (mpn_a and mpn_b) or mpn_a == mpn_b or (mpn_a, mpn_b) in existing:
            rejected += 1
            continue
        existing.add((mpn_a, mpn_b))
        rows.append(
            {
                "mpn_a": mpn_a,
                "brand_a": lower.get("brand_a", "").upper(),
                "mpn_b": mpn_b,
                "brand_b": lower.get("brand_b", "").upper(),
                "source": f"uploaded by {user.name}",
            }
        )
    if rows:
        db.execute(insert(Crossref), rows)
        db.commit()
    return {
        "imported": len(rows),
        "rejected": rejected,
        "note": "Run the pipeline to apply new cross-references.",
    }
