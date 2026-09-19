"""Catalogue search — spec §5, §6.3.

Paginated server-side with a total count (§8A): the result set is the whole
estate, and a 150k-row table cannot be shipped to the browser to be filtered
there.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Cluster, ClusterMember, Cnmc, Cpse, GoldenRecord, Item, RawItem
from ..normalize import apply_hindi_terms, expand_abbreviations, transliterate_devanagari
from ..taxonomy import load_schemas

router = APIRouter(tags=["search"])

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]*")

SORTS = ("relevance", "shortest", "newest")


def read_query(search: str | None) -> tuple[list[str], list[tuple[str, str]]]:
    """The query's tokens, read the way a description is read.

    Hindi domain words land on their English term, the rest is transliterated,
    and house abbreviations are expanded on whole tokens, so "BRG 6205" asks
    for bearings the way the catalogue spells them after normalisation. The
    second value lists what was rewritten, so the screen can say so.
    """
    readable = transliterate_devanagari(apply_hindi_terms(search or ""))
    raw = _TOKEN.findall(readable.upper())[:6]
    tokens: list[str] = []
    rewritten: list[tuple[str, str]] = []
    for token in raw:
        expanded = expand_abbreviations(token)
        if expanded != token:
            rewritten.append((token, expanded))
        tokens.extend(expanded.split())
    return tokens[:8], rewritten


_vocab_cache: tuple[int, list[str]] | None = None


#: A word has to appear this often in the catalogue to count as a spelling
#: worth suggesting. Real extracts carry typos too ("BEARNIG" is in this
#: estate); a word seen once or twice is more likely one of those than a term.
VOCAB_MIN_ROWS = 5


def vocabulary(db: Session) -> list[str]:
    """The words the normalised catalogue uses often, plus the abbreviation
    table's full forms: what a misspelt query is corrected against. Rebuilt
    when the item count changes."""
    global _vocab_cache
    from collections import Counter

    from ..data.abbreviations import ABBREVIATIONS

    count = db.execute(select(func.count(Item.id))).scalar() or 0
    if _vocab_cache and _vocab_cache[0] == count:
        return _vocab_cache[1]
    seen: Counter[str] = Counter()
    for text in db.execute(select(Item.norm_text)).scalars():
        seen.update({word for word in text.split() if len(word) >= 4 and word.isalpha()})
    # Expansions can be phrases ("SPIRAL WOUND GASKET"); the vocabulary is words.
    words = {w for v in ABBREVIATIONS.values() for w in v.split() if len(w) >= 4 and w.isalpha()}
    words |= {w for w, n in seen.items() if n >= VOCAB_MIN_ROWS}
    _vocab_cache = (count, sorted(words))
    return _vocab_cache[1]


def did_you_mean(db: Session, tokens: list[str]) -> str | None:
    """A corrected query when the typed one finds nothing: each word that is
    not in the vocabulary is replaced by its nearest neighbour, if one is near
    enough. Numbers and codes are left alone. None when nothing changes."""
    from rapidfuzz import fuzz, process

    vocab = vocabulary(db)
    known = set(vocab)
    out: list[str] = []
    changed = False
    for token in tokens:
        if not token.isalpha() or len(token) < 4 or token in known:
            out.append(token)
            continue
        hit = process.extractOne(token, vocab, scorer=fuzz.ratio, score_cutoff=78)
        if hit:
            out.append(hit[0])
            changed = True
        else:
            out.append(token)
    return " ".join(out) if changed else None


@router.get("/items")
def search_items(
    search: str | None = None,
    cpse: str | None = None,
    class_code: str | None = Query(default=None, alias="class"),
    has_cnmc: bool | None = None,
    sort: str = Query(default="relevance"),
    limit: int = Query(default=25, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    """Search normalized text, legacy codes and anchor keys, with filters.

    `sort=relevance` (default) puts rows whose text carries the whole query
    in order first, then part-number hits, then the shortest text; `shortest`
    is length alone; `newest` is the latest rows first. A query that finds
    nothing comes back with `did_you_mean`, a spelling the catalogue does use.
    """
    if sort not in SORTS:
        sort = "relevance"
    query = (
        select(
            Item.id,
            Item.norm_text,
            Item.class_code,
            Item.mpn_norm,
            Item.attrs_json,
            RawItem.legacy_code,
            RawItem.description,
            Cpse.code,
            ClusterMember.cluster_id,
        )
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .outerjoin(ClusterMember, ClusterMember.item_id == Item.id)
    )

    # A query is read the way a description is: Hindi domain words land on
    # their English term and the rest is transliterated, so "वाल्व गेट 50NB"
    # asks for gate valves and not for everything with 50NB in it. The
    # tokeniser only knows Latin letters and digits; without this, Devanagari
    # was silently dropped from the query.
    tokens, rewritten = read_query(search)
    if tokens:
        # Every token must appear, so "6205 SKF" narrows rather than widens,
        # and each must start a token in the text. A plain substring match
        # returns a cable whose barcode happens to contain 6205; padding the
        # field and anchoring to a token start is what keeps "6205" meaning the
        # bearing designation and still matching "6205-2Z" and "6205ZZ".
        padded_text = func.concat(" ", Item.norm_text, " ")
        padded_code = func.concat(" ", RawItem.legacy_code, " ")
        for token in tokens:
            starts = f"% {token}%"
            query = query.where(
                or_(
                    padded_text.like(starts),
                    padded_code.like(starts),
                    Item.mpn_norm.like(f"{token}%"),
                )
            )
    if cpse:
        query = query.where(Cpse.code == cpse.upper())
    if class_code:
        query = query.where(Item.class_code == class_code)
    if has_cnmc is not None:
        coded = select(GoldenRecord.cluster_id).join(Cnmc, Cnmc.golden_id == GoldenRecord.id)
        query = query.where(
            ClusterMember.cluster_id.in_(coded)
            if has_cnmc
            else ClusterMember.cluster_id.notin_(coded)
        )

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0

    # Shorter descriptions rank first: a row that is mostly the searched term is
    # a better answer than one that merely contains it. Relevance puts the
    # rows that carry the whole query, in order, ahead of that, and a
    # part-number hit ahead of a text hit.
    if sort == "newest":
        ordering: tuple = (Item.id.desc(),)
    elif tokens and sort == "relevance":
        from sqlalchemy import case

        phrase = " ".join(tokens)
        ordering = (
            case((func.concat(" ", Item.norm_text, " ").like(f"% {phrase}%"), 0), else_=1),
            case((Item.mpn_norm.like(f"{tokens[0]}%"), 0), else_=1),
            func.length(Item.norm_text),
            Item.id,
        )
    elif tokens:
        ordering = (func.length(Item.norm_text), Item.id)
    else:
        ordering = (Item.id,)
    rows = db.execute(query.order_by(*ordering).offset(offset).limit(limit)).all()

    cluster_ids = [row[8] for row in rows if row[8]]
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
    sizes = (
        dict(
            db.execute(
                select(ClusterMember.cluster_id, func.count(ClusterMember.item_id))
                .where(ClusterMember.cluster_id.in_(cluster_ids))
                .group_by(ClusterMember.cluster_id)
            ).all()
        )
        if cluster_ids
        else {}
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "sort": sort,
        "query": {"search": search, "cpse": cpse, "class": class_code, "has_cnmc": has_cnmc},
        # How the query was read: which abbreviations were expanded, and, when
        # nothing matched, the nearest spelling the catalogue does use.
        "read_as": " ".join(tokens) if rewritten else None,
        "rewritten": [{"from": a, "to": b} for a, b in rewritten],
        "did_you_mean": did_you_mean(db, tokens) if tokens and total == 0 else None,
        "items": [
            {
                "item_id": row[0],
                "normalized": row[1],
                "class_code": row[2],
                "mpn_norm": row[3],
                "brand": json.loads(row[4] or "{}").get("brand"),
                "legacy_code": row[5],
                "description": row[6],
                "cpse": row[7],
                "cluster_id": row[8],
                "cluster_size": sizes.get(row[8], 1),
                "cnmc": codes.get(row[8]),
            }
            for row in rows
        ],
    }


@router.get("/facets")
def facets(db: Session = Depends(get_db)) -> dict:
    """The filter options a search screen needs, from the data itself."""
    return {
        "cpses": [
            {"code": code, "name": name, "items": count}
            for code, name, count in db.execute(
                select(Cpse.code, Cpse.name, func.count(RawItem.id))
                .join(RawItem, RawItem.cpse_id == Cpse.id)
                .group_by(Cpse.code, Cpse.name)
                .order_by(Cpse.code)
            ).all()
        ],
        "classes": [
            {
                "class_code": class_code,
                "label": load_schemas()[class_code].label
                if class_code in load_schemas()
                else class_code,
                "items": count,
            }
            for class_code, count in db.execute(
                select(Item.class_code, func.count(Item.id))
                .group_by(Item.class_code)
                .order_by(func.count(Item.id).desc())
            ).all()
        ],
        "totals": {
            "items": db.execute(select(func.count(Item.id))).scalar() or 0,
            "clusters": db.execute(select(func.count(Cluster.id))).scalar() or 0,
            "cnmcs": db.execute(select(func.count(Cnmc.id))).scalar() or 0,
        },
    }
