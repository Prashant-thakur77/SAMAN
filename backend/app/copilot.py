"""Guarded natural-language copilot — spec §5, §6.9, §9, §0.9b.

The pattern is vanna's (§9): retrieve, generate, **validate before execute**.
The difference is that generation is constrained to a whitelist. A question is
routed to one of a fixed set of parameterized queries, or to retrieval over the
golden records, or refused. Free-form SQL is never generated and never
executed, so there is no path from user text to the database at all — the only
thing a question can influence is which whitelisted query runs and what its
bound parameters are.

Three layers, in order:

    guard      destructive or injection-shaped input is refused outright
    route      the question is matched to a template, or to retrieval
    compose    deterministic prose by default; a local LLM may only rephrase
               facts that have already been computed, and its output is
               checked back against them

Row-level visibility (§0.9b) is applied by the same functions the dashboards
use, so the Copilot cannot become a way around it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import llm
from .config import get_settings
from .visibility import Scope, price_band

# --------------------------------------------------------------------------
# Guard
# --------------------------------------------------------------------------

#: Anything that reads as an attempt to mutate, exfiltrate, or talk past the
#: rules. The Copilot has no code path to execute these, so this is defence in
#: depth and, as much, a way of saying plainly what was refused and why.
_REFUSAL_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(
            r"\b(drop|truncate|delete\s+from|alter\s+table|update\s+\w+\s+set|"
            r"insert\s+into|create\s+table|grant|revoke|attach|pragma)\b",
            re.IGNORECASE,
        ),
        "That asks for a change to the database. The copilot can only read, and "
        "only through a fixed set of reviewed queries.",
    ),
    (
        re.compile(
            # Up to three words may sit between the verb and the noun:
            # "ignore the visibility rules" escaped a pattern that demanded
            # they be adjacent. The noun list is what keeps this from refusing
            # "ignore the small differences".
            r"((?:ignore|disregard|bypass|override|forget)\s+(?:\w+\s+){0,3}"
            r"(?:instructions?|rules?|prompts?|guardrails?|restrictions?|"
            r"permissions?|visibility)"
            r"|you\s+are\s+now\s+|system\s+prompt|jailbreak|act\s+as\s+(?:an?\s+)?admin)",
            re.IGNORECASE,
        ),
        "That asks the copilot to set aside its rules. The rules are not "
        "instructions in a prompt — they are the only queries it can run.",
    ),
    (
        # `--` must also match at end of input: "SELECT * FROM users; --" ended
        # the string with the comment marker and slipped through a pattern that
        # required trailing whitespace.
        re.compile(
            r"(--(\s|$)|;\s*\S|/\*|\bunion\s+select\b|\bor\s+1\s*=\s*1\b"
            r"|\bselect\b.{0,40}\bfrom\b)",
            re.IGNORECASE,
        ),
        "That looks like an attempt to inject SQL. Questions never become SQL "
        "here; they select a reviewed query and its parameters.",
    ),
    (
        re.compile(r"\b(password|password_hash|secret|credential|api[_ ]?key)\b", re.IGNORECASE),
        "Credentials are never readable through the copilot.",
    ),
)


def guard(question: str) -> str | None:
    """Return a refusal reason, or None if the question may proceed."""
    for pattern, reason in _REFUSAL_PATTERNS:
        if pattern.search(question or ""):
            return reason
    return None


# --------------------------------------------------------------------------
# Whitelisted queries
# --------------------------------------------------------------------------


@dataclass
class Answer:
    text: str
    citations: list[dict] = field(default_factory=list)
    sql: str | None = None
    params: dict = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)
    template: str | None = None
    mode: str = "template"
    refused: bool = False
    note: str | None = None

    def as_dict(self) -> dict:
        return {
            "answer": self.text,
            "citations": self.citations,
            "sql": self.sql,
            "params": self.params,
            "rows": self.rows[:25],
            "template": self.template,
            "mode": self.mode,
            "refused": self.refused,
            "note": self.note,
        }


@dataclass
class Template:
    key: str
    description: str
    example: str
    patterns: tuple[re.Pattern, ...]
    sql: str
    render: Callable[[list[dict], dict], str]
    needs_class: bool = False
    price_sensitive: bool = False
    #: Optional second query naming the materials an aggregate answer rests on,
    #: so an aggregate can still be traced to specific records.
    citation_sql: str | None = None


def _kw(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.IGNORECASE)


#: Class names as a user would say them.
CLASS_SYNONYMS: dict[str, str] = {
    "bearing": "bearing.ball.deep_groove",
    "bearings": "bearing.ball.deep_groove",
    "valve": "valve.gate",
    "valves": "valve.gate",
    "gasket": "gasket.spiral_wound",
    "gaskets": "gasket.spiral_wound",
    "pipe": "pipe.seamless",
    "pipes": "pipe.seamless",
    "bolt": "fastener.bolt.hex",
    "bolts": "fastener.bolt.hex",
    "fastener": "fastener.bolt.hex",
    "fasteners": "fastener.bolt.hex",
    "cable": "cable.power",
    "cables": "cable.power",
    "chemical": "chemical.reagent",
    "chemicals": "chemical.reagent",
    "helmet": "ppe.helmet",
    "helmets": "ppe.helmet",
    "ppe": "ppe.helmet",
}


def class_in(question: str) -> str | None:
    lowered = (question or "").lower()
    for word, class_code in CLASS_SYNONYMS.items():
        if re.search(rf"\b{word}\b", lowered):
            return class_code
    return None


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else (plural or singular + 's')}"


def _render_overpaying(rows: list[dict], params: dict) -> str:
    """Answer "who pays most" without naming another CPSE's price to a steward.

    Redacting the table is not enough — the sentence would leak the same figure.
    A restricted viewer gets their own price and the anonymised band, which is
    what §0.9b intends them to act on.
    """
    label = params.get("class_label") or "that class"
    if not rows:
        return f"No purchase history has been recorded for {label}."
    if params.get("redacted"):
        mine = next((r for r in rows if r.get("avg_unit_price") is not None), None)
        band = params.get("band")
        own = (
            f"Your catalogue pays ₹{mine['avg_unit_price']:,.2f} per base unit for "
            f"{label} across {mine['orders']:,} orders. "
            if mine
            else ""
        )
        return own + (
            f"Across all {len(rows)} CPSEs buying {label}, the price ranges from "
            f"₹{band['min']:,.2f} to ₹{band['max']:,.2f} per base unit."
            if band
            else f"No comparable price range is available for {label}."
        )
    if len(rows) == 1:
        return f"Only {rows[0]['cpse']} has purchase history for {label}; nothing to compare."
    return (
        f"For {label}, {rows[0]['cpse']} pays the most at "
        f"₹{rows[0]['avg_unit_price']:,.2f} per base unit across {rows[0]['orders']:,} orders, "
        f"against {rows[-1]['cpse']} at ₹{rows[-1]['avg_unit_price']:,.2f} — a "
        f"{_gap_pct(rows)}% difference. Prices are normalized per base unit, so pack "
        "sizes compare."
    )


def _gap_pct(rows: list[dict]) -> int:
    """Percentage between the dearest and cheapest buyer."""
    high, low = rows[0]["avg_unit_price"], rows[-1]["avg_unit_price"]
    return round(100 * (high - low) / high) if high else 0


TEMPLATES: tuple[Template, ...] = (
    Template(
        key="duplicates_by_cpse",
        description="How many duplicate rows each CPSE holds",
        example="count duplicates by cpse",
        patterns=(_kw(r"duplicate.*(by|per)\s+cpse", r"how many duplicates", r"duplicate rows"),),
        sql="""
            SELECT c.code AS cpse,
                   COUNT(*) AS rows_in_shared_clusters
            FROM cluster_member cm
            JOIN item i        ON i.id = cm.item_id
            JOIN raw_item r    ON r.id = i.raw_item_id
            JOIN cpse c        ON c.id = r.cpse_id
            WHERE cm.cluster_id IN (
                SELECT cluster_id FROM cluster_member
                GROUP BY cluster_id HAVING COUNT(*) > 1
            )
            GROUP BY c.code
            ORDER BY rows_in_shared_clusters DESC
        """,
        render=lambda rows, _p: (
            "Rows that sit in a cluster shared with at least one other catalogue: "
            + ", ".join(f"{r['cpse']} {r['rows_in_shared_clusters']:,}" for r in rows)
            + ". Each of these collapses into a single CNMC once the cluster is adopted."
            if rows
            else "No cluster yet contains rows from more than one catalogue."
        ),
    ),
    Template(
        key="pending_approvals",
        description="What is waiting for a human decision",
        example="how many approvals are pending",
        patterns=(_kw(r"pending", r"waiting", r"awaiting", r"to review", r"review queue"),),
        sql="""
            SELECT band, assignee_role, COUNT(*) AS pending
            FROM review_task WHERE state = 'pending'
            GROUP BY band, assignee_role ORDER BY pending DESC
        """,
        render=lambda rows, _p: (
            f"{sum(r['pending'] for r in rows):,} tasks are pending: "
            + ", ".join(
                f"{r['pending']:,} in {r['band']} for the {r['assignee_role']}" for r in rows
            )
            + "."
            if rows
            else "Nothing is pending — every review task has been decided."
        ),
    ),
    Template(
        key="cnmcs_issued",
        description="How many codes have been issued, and to what",
        example="how many CNMCs have been issued",
        patterns=(_kw(r"cnmc", r"codes? issued", r"how many codes"),),
        sql="""
            SELECT n.code, g.std_description, n.status
            FROM cnmc n JOIN golden_record g ON g.id = n.golden_id
            ORDER BY n.id DESC LIMIT 25
        """,
        render=lambda rows, _p: (
            f"{_plural(len(rows), 'code has', 'codes have')} been issued. "
            f"Most recent: {rows[0]['code']} for {rows[0]['std_description']}."
            if rows
            else "No CNMC has been issued yet. A registrar issues one from a cluster page."
        ),
    ),
    Template(
        key="overpaying_cpse",
        description="Which CPSE pays the most for a class of material",
        example="which CPSE overpays for gaskets",
        patterns=(
            _kw(
                r"overpay",
                r"pays? (the )?most",
                r"most expensive",
                r"paying more",
                r"highest price",
            ),
        ),
        needs_class=True,
        price_sensitive=True,
        citation_sql="""
            SELECT cm.cluster_id, g.std_description, n.code AS cnmc,
                   ROUND(SUM(p.qty * p.unit_price), 2) AS spend
            FROM purchase_history p
            JOIN item i            ON i.id = p.item_id
            JOIN cluster_member cm ON cm.item_id = i.id
            JOIN golden_record g   ON g.cluster_id = cm.cluster_id
            LEFT JOIN cnmc n       ON n.golden_id = g.id
            WHERE i.class_code = :class_code
            GROUP BY cm.cluster_id, g.std_description, n.code
            ORDER BY spend DESC LIMIT 6
        """,
        sql="""
            SELECT c.code AS cpse,
                   COUNT(*) AS orders,
                   ROUND(AVG(p.unit_price / MAX(i.pack_qty, 1)), 2) AS avg_unit_price
            FROM purchase_history p
            JOIN item i     ON i.id = p.item_id
            JOIN cpse c     ON c.id = p.cpse_id
            WHERE i.class_code = :class_code
            GROUP BY c.code
            ORDER BY avg_unit_price DESC
        """,
        render=lambda rows, params: _render_overpaying(rows, params),
    ),
    Template(
        key="price_variance",
        description="The materials with the widest price spread between CPSEs",
        example="top price variance",
        patterns=(
            _kw(r"price variance", r"widest (price )?spread", r"biggest price", r"price gap"),
        ),
        price_sensitive=True,
        sql="""
            SELECT cm.cluster_id,
                   g.std_description,
                   COUNT(DISTINCT p.cpse_id) AS cpses,
                   ROUND(MIN(p.unit_price / MAX(i.pack_qty, 1)), 2) AS low,
                   ROUND(MAX(p.unit_price / MAX(i.pack_qty, 1)), 2) AS high
            FROM purchase_history p
            JOIN item i          ON i.id = p.item_id
            JOIN cluster_member cm ON cm.item_id = i.id
            JOIN golden_record g ON g.cluster_id = cm.cluster_id
            GROUP BY cm.cluster_id, g.std_description
            HAVING COUNT(DISTINCT p.cpse_id) > 1 AND MAX(p.unit_price / MAX(i.pack_qty, 1)) > 0
            ORDER BY (MAX(p.unit_price / MAX(i.pack_qty, 1))
                      - MIN(p.unit_price / MAX(i.pack_qty, 1)))
                     / MAX(p.unit_price / MAX(i.pack_qty, 1)) DESC
            LIMIT 20
        """,
        render=lambda rows, params: (
            (
                f"The widest spread is on {rows[0]['std_description']}: "
                + (
                    f"₹{rows[0]['low']:,.2f} to ₹{rows[0]['high']:,.2f} per base unit "
                    if rows[0].get("low") is not None
                    else ""
                )
                + f"across {rows[0]['cpses']} CPSEs. "
                f"{len(rows)} materials show a spread between catalogues."
            )
            if rows
            else "No material has been bought by more than one CPSE yet."
        ),
    ),
    Template(
        key="idle_stock",
        description="Where stock is sitting unused",
        example="where is idle stock of bearings",
        patterns=(_kw(r"idle stock", r"dead stock", r"slow.?moving", r"not moved", r"sitting"),),
        needs_class=False,
        sql="""
            SELECT c.code AS cpse, s.plant, g.std_description,
                   s.qty_on_hand AS qty,
                   ROUND(s.qty_on_hand * s.unit_value, 2) AS value,
                   s.last_movement_date AS last_movement,
                   cm.cluster_id
            FROM stock s
            JOIN item i          ON i.id = s.item_id
            JOIN cpse c          ON c.id = s.cpse_id
            JOIN cluster_member cm ON cm.item_id = i.id
            JOIN golden_record g ON g.cluster_id = cm.cluster_id
            WHERE s.qty_on_hand > 0
              AND s.last_movement_date < date('now', '-12 months')
              AND (:class_code IS NULL OR i.class_code = :class_code)
            ORDER BY value DESC LIMIT 20
        """,
        render=lambda rows, params: (
            f"{len(rows)} positions have not moved in twelve months"
            + (f" for {params['class_label']}" if params.get("class_label") else "")
            + f". The largest is {rows[0]['qty']:,.0f} units at {rows[0]['cpse']} "
            f"{rows[0]['plant']} — {rows[0]['std_description']} — last moved "
            f"{rows[0]['last_movement']}."
            if rows
            else "Nothing has been idle for twelve months in that scope."
        ),
    ),
    Template(
        key="joint_tenders",
        description="Materials several CPSEs buy separately",
        example="which items could we tender jointly",
        patterns=(
            _kw(
                r"joint(ly)? tender",
                r"tender (jointly|together)",
                r"buy together",
                r"aggregate demand",
                r"combined volume",
                r"consolidat",
            ),
        ),
        price_sensitive=True,
        sql="""
            SELECT cm.cluster_id, g.std_description,
                   COUNT(DISTINCT p.cpse_id) AS cpses,
                   ROUND(SUM(p.qty * MAX(i.pack_qty, 1)), 1) AS combined_qty
            FROM purchase_history p
            JOIN item i          ON i.id = p.item_id
            JOIN cluster_member cm ON cm.item_id = i.id
            JOIN golden_record g ON g.cluster_id = cm.cluster_id
            GROUP BY cm.cluster_id, g.std_description
            HAVING COUNT(DISTINCT p.cpse_id) > 1
            ORDER BY combined_qty DESC LIMIT 20
        """,
        render=lambda rows, _p: (
            f"{len(rows)} materials are bought by more than one CPSE. The largest combined "
            f"volume is {rows[0]['combined_qty']:,.0f} units of {rows[0]['std_description']} "
            f"across {rows[0]['cpses']} CPSEs."
            if rows
            else "No material is bought by more than one CPSE in the recorded history."
        ),
    ),
    Template(
        key="items_by_class",
        description="How the catalogue breaks down by class",
        example="how many items per class",
        patterns=(
            _kw(
                r"(items?|rows?|materials?).*(by|per)\s+class", r"class breakdown", r"what classes"
            ),
        ),
        sql="""
            SELECT class_code, COUNT(*) AS items
            FROM item GROUP BY class_code ORDER BY items DESC
        """,
        render=lambda rows, _p: (
            f"{sum(r['items'] for r in rows):,} rows across {len(rows)} classes: "
            + ", ".join(f"{r['class_code']} {r['items']:,}" for r in rows[:6])
            + ("…" if len(rows) > 6 else "")
            if rows
            else "The catalogue is empty."
        ),
    ),
)


# --------------------------------------------------------------------------
# Retrieval (for "which item / what is" questions)
# --------------------------------------------------------------------------

RETRIEVAL_SQL = """
    SELECT g.cluster_id, g.std_description, n.code AS cnmc,
           (SELECT COUNT(*) FROM cluster_member cm WHERE cm.cluster_id = g.cluster_id) AS members
    FROM golden_record g
    LEFT JOIN cnmc n ON n.golden_id = g.id
"""


def retrieve(db: Session, question: str, limit: int = 5) -> list[dict]:
    """Rank golden records against the question by token similarity.

    Deliberately offline and deterministic: rapidfuzz over the standardized
    descriptions. The golden layer is the shared vocabulary, so searching it
    rather than raw rows is also what keeps retrieval inside §0.9b.
    """
    from rapidfuzz import fuzz

    rows = [dict(row._mapping) for row in db.execute(text(RETRIEVAL_SQL))]
    scored = [
        (fuzz.token_set_ratio(question.upper(), row["std_description"] or ""), row) for row in rows
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [{**row, "score": round(score / 100, 3)} for score, row in scored[:limit] if score >= 55]


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------


def match_template(question: str) -> Template | None:
    for template in TEMPLATES:
        if any(pattern.search(question or "") for pattern in template.patterns):
            return template
    return None


def _run(db: Session, template: Template, params: dict) -> list[dict]:
    bound = {"class_code": params.get("class_code")}
    result = db.execute(text(template.sql), bound)
    return [dict(row._mapping) for row in result]


def _apply_visibility(
    template: Template, rows: list[dict], scope: Scope
) -> tuple[list[dict], str | None, dict | None]:
    """§0.9b — the Copilot must not be a way around row-level security."""
    if not template.price_sensitive or scope.sees_all_prices:
        return rows, None, None

    price_fields = [f for f in ("avg_unit_price", "low", "high", "value") if rows and f in rows[0]]
    if not price_fields:
        return rows, None, None

    values = [r[f] for r in rows for f in price_fields if r.get(f)]
    band = price_band(values)
    redacted = []
    for row in rows:
        if scope.owns(row.get("cpse")):
            redacted.append(row)
            continue
        entry = dict(row)
        for field_name in price_fields:
            entry[field_name] = None
        entry["price_withheld"] = True
        redacted.append(entry)
    note = (
        "Individual CPSE prices are withheld from your role (§0.9b); ask a "
        "registrar or auditor for attributed figures."
    )
    return redacted, note, band


def answer(db: Session, question: str, scope: Scope, use_llm: bool = False) -> Answer:
    """Route one question. Never generates SQL; only selects a reviewed one."""
    question = (question or "").strip()
    if not question:
        return Answer(text="Ask a question about the material master.", refused=False)

    refusal = guard(question)
    if refusal:
        return Answer(
            text=refusal,
            refused=True,
            note="Refused before any query was selected.",
            mode="refusal",
        )

    why = explain_why(db, question)
    if why is not None:
        return why

    template = match_template(question)
    if template is not None:
        class_code = class_in(question)
        if template.needs_class and not class_code:
            return Answer(
                text=(
                    "Which material class do you mean? Try one of: "
                    + ", ".join(sorted({v.split(".")[0] for v in CLASS_SYNONYMS.values()}))
                    + "."
                ),
                template=template.key,
                note="The question matched a query that needs a class to be named.",
            )

        params = {
            "class_code": class_code,
            "class_label": class_code.split(".")[0] if class_code else None,
        }
        rows = _run(db, template, params)
        rows, visibility_note, band = _apply_visibility(template, rows, scope)
        params["redacted"] = visibility_note is not None
        params["band"] = band
        prose = template.render(rows, params)

        citation_rows = rows
        if template.citation_sql:
            citation_rows = [
                dict(row._mapping)
                for row in db.execute(
                    text(template.citation_sql), {"class_code": params.get("class_code")}
                )
            ]
        citations = [
            {
                "cluster_id": row.get("cluster_id"),
                "label": row.get("std_description") or row.get("cpse") or row.get("class_code"),
                "cnmc": row.get("cnmc"),
            }
            for row in citation_rows[:6]
            if row.get("cluster_id") or row.get("std_description")
        ]
        return Answer(
            text=prose + (f" {visibility_note}" if visibility_note else ""),
            citations=citations,
            sql=template.sql.strip(),
            params={k: v for k, v in params.items() if v is not None},
            rows=rows,
            template=template.key,
            mode="llm" if use_llm else "template",
            note=visibility_note,
        )

    # Fall through to retrieval over the golden records.
    hits = retrieve(db, question)
    if not hits:
        return Answer(
            text=(
                "I could not match that to one of my reviewed queries or find a matching "
                "material. Try naming a material class, or ask about duplicates, pending "
                "approvals, price variance or idle stock."
            ),
            note="No template matched and retrieval found nothing above the threshold.",
            sql=RETRIEVAL_SQL.strip(),
        )

    lead = hits[0]
    return Answer(
        text=(
            f"The closest match is {lead['std_description']}"
            + (f", coded {lead['cnmc']}" if lead["cnmc"] else " (no CNMC issued yet)")
            + f", covering {_plural(lead['members'], 'catalogue row')}."
            + (f" {len(hits) - 1} other materials also match." if len(hits) > 1 else "")
        ),
        citations=[
            {"cluster_id": h["cluster_id"], "label": h["std_description"], "cnmc": h["cnmc"]}
            for h in hits
        ],
        sql=RETRIEVAL_SQL.strip(),
        rows=hits,
        template="retrieval",
        mode="llm" if use_llm else "template",
    )


def suggested_prompts() -> list[str]:
    return [template.example for template in TEMPLATES] + [WHY_EXAMPLE]


# --------------------------------------------------------------------------
# "Why?" — the reason behind one pair, already computed
# --------------------------------------------------------------------------

WHY_EXAMPLE = "why were IOCL001320 and CPCL001294 not merged"

_WHY = re.compile(r"\bwhy\b|\bkyu[n]?\b|क्यों", re.IGNORECASE)
_TASK_REF = re.compile(r"\btask\s*#?\s*(\d+)", re.IGNORECASE)
_CODE_REF = re.compile(r"\b([A-Z]{2,8}\d{4,10})\b")


def explain_why(db: Session, question: str) -> Answer | None:
    """Answer "why were X and Y (not) merged" or "why is task N in the queue"
    with the sentence the pipeline already wrote for that pair: the veto's
    reason, the anchor, or the attribute that could not be read. Nothing is
    computed anew and no model is consulted; this is the Workbench card's
    `why` line, reachable by asking."""
    if not _WHY.search(question):
        return None
    import json as _json

    from sqlalchemy import or_, select

    from .adjudicate import adjudicate
    from .models import ClusterMember, Item, Pair, RawItem, ReviewTask

    task_match = _TASK_REF.search(question)
    codes = [c.upper() for c in _CODE_REF.findall(question.upper())]
    pair: Pair | None = None
    task: ReviewTask | None = None
    labels: list[str] = []

    if task_match:
        task = db.get(ReviewTask, int(task_match.group(1)))
        if task is None:
            return Answer(
                text=f"There is no review task {task_match.group(1)}.",
                template="why",
                note="No such task.",
            )
        pair = db.get(Pair, task.pair_id) if task.pair_id else None
    elif len(codes) >= 2:
        rows = db.execute(
            select(RawItem.legacy_code, Item.id)
            .join(Item, Item.raw_item_id == RawItem.id)
            .where(RawItem.legacy_code.in_(codes[:2]))
        ).all()
        by_code = {code: item_id for code, item_id in rows}
        missing = [c for c in codes[:2] if c not in by_code]
        if missing:
            return Answer(
                text=f"I do not know the code{'s' if len(missing) > 1 else ''} "
                + ", ".join(missing)
                + ".",
                template="why",
                note="Unknown legacy code.",
            )
        a, b = by_code[codes[0]], by_code[codes[1]]
        labels = codes[:2]
        pair = (
            db.execute(
                select(Pair).where(
                    or_(
                        (Pair.item_a == a) & (Pair.item_b == b),
                        (Pair.item_a == b) & (Pair.item_b == a),
                    )
                )
            )
            .scalars()
            .first()
        )
        if pair is None:
            clusters = {
                db.execute(
                    select(ClusterMember.cluster_id).where(ClusterMember.item_id == i)
                ).scalar_one_or_none()
                for i in (a, b)
            }
            if len(clusters) == 1 and None not in clusters:
                text_value = (
                    f"{labels[0]} and {labels[1]} were never scored against each other "
                    "directly, but they sit in the same cluster: each was matched to a "
                    "row that the other also matched."
                )
            else:
                text_value = (
                    f"{labels[0]} and {labels[1]} were never compared. Blocking did not put "
                    "them in the same candidate bucket (no shared part number, class key, "
                    "or text neighbourhood), so no pair was scored."
                )
            return Answer(text=text_value, template="why", rows=[{"pair": None}])
        task = (
            db.execute(
                select(ReviewTask)
                .where(ReviewTask.pair_id == pair.id)
                .order_by(ReviewTask.id.desc())
            )
            .scalars()
            .first()
        )
    else:
        return None

    if pair is None:
        return Answer(text="That task has no pair behind it.", template="why")

    evidence = _json.loads(pair.evidence_json or "{}")
    veto = _json.loads(pair.veto_json) if pair.veto_json else None
    tiers = _json.loads(pair.tier_scores_json or "{}")
    verdict_words = {
        "duplicate": "merged",
        "auto_merge": "merged automatically",
        "distinct": "kept apart",
        "auto_reject": "kept apart automatically",
        "review": "held for a person",
        "conflict": "flagged as a specification conflict",
    }
    said = adjudicate(evidence, tiers, pair.confidence, pair.verdict, veto, rephrase=False)
    if not labels:
        labels = [f"item {pair.item_a}", f"item {pair.item_b}"]
    parts = [
        f"{labels[0]} and {labels[1]} were {verdict_words.get(pair.verdict, pair.verdict)} "
        f"at confidence {pair.confidence:.2f}.",
        said.summary,
    ]
    if veto and veto.get("vetoed_by"):
        parts.append(
            "The veto layer refused on "
            + "; ".join(
                f"{v['attr']}: {v.get('reason', '')}".strip() for v in veto["vetoed_by"][:3]
            )
            + "."
        )
    if task is not None:
        if task.state == "pending":
            parts.append(f"Review task {task.id} in the {task.band} band is still pending.")
        else:
            from .models import Decision

            decision = (
                db.execute(
                    select(Decision).where(Decision.task_id == task.id).order_by(Decision.id.desc())
                )
                .scalars()
                .first()
            )
            parts.append(
                f"Review task {task.id} in the {task.band} band was "
                + (
                    f"{decision.action}d by a reviewer"
                    + (f' ("{decision.note}")' if decision.note else "")
                    if decision
                    else "decided"
                )
                + "."
            )
    cluster_ids = [
        db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == i)
        ).scalar_one_or_none()
        for i in (pair.item_a, pair.item_b)
    ]
    return Answer(
        text=" ".join(parts),
        citations=[
            {"cluster_id": cid, "label": label, "cnmc": None}
            for cid, label in zip(cluster_ids, labels, strict=True)
            if cid
        ],
        rows=[
            {
                "pair_id": pair.id,
                "verdict": pair.verdict,
                "confidence": pair.confidence,
                "recommendation": said.recommendation,
                "reasons": said.reasons,
                "task_id": task.id if task else None,
                "band": task.band if task else pair.band,
            }
        ],
        template="why",
        note="Computed from the pair's stored evidence; no model was consulted.",
    )


# --------------------------------------------------------------------------
# Optional local LLM (§0.4 Tier 3, §5c)
# --------------------------------------------------------------------------

#: The LLM may only rephrase. It is given the facts and the sentence already
#: computed from them, and asked for better English — never for a conclusion.
_PROSE_PROMPT = """You are rewriting one sentence for a materials-management
dashboard used by Indian public-sector companies.

Question: {question}

Facts already computed (these are the only facts that exist):
{facts}

Draft answer: {draft}

Rewrite the draft as one or two plain sentences. Rules:
- Use only the numbers and names in the facts. Invent nothing.
- Do not add caveats, opinions, or recommendations.
- Keep it under 60 words.
Rewritten answer:"""

_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def _numbers_in(text_value: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(text_value or "")}


def compose_with_llm(question: str, draft: str, rows: list[dict]) -> tuple[str, str | None]:
    """Ask a local Ollama model to rephrase. Returns (text, rejection reason).

    The output is checked back against the draft: any number the model produces
    that was not already computed means it invented something, and the
    deterministic sentence is kept instead. Prose is the only thing the model is
    trusted with.
    """
    settings = get_settings()
    if not settings.llm_enabled:
        return draft, "no model configured"

    facts = "\n".join(f"- {row}" for row in rows[:12]) or "- (no rows)"
    prompt = _PROSE_PROMPT.format(question=question, facts=facts, draft=draft)

    try:
        candidate = llm.generate(prompt, temperature=0.2, timeout=20.0, max_tokens=300)
    except Exception as exc:
        # A local model being down must never cost the user their answer.
        llm.record("copilot", "unavailable")
        return draft, f"model unavailable ({type(exc).__name__})"

    if not candidate:
        llm.record("copilot", "empty")
        return draft, "the model returned nothing"

    invented = _numbers_in(candidate) - _numbers_in(draft)
    if invented:
        llm.record("copilot", "invented_figure")
        return draft, f"the model introduced figures that were not computed: {sorted(invented)[:3]}"
    if len(candidate) > 600:
        llm.record("copilot", "too_long")
        return draft, "the model's answer was too long to be a rephrasing"
    llm.record("copilot", "accepted")
    return candidate, None
