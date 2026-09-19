"""The executive dashboard's explanatory sections — spec §6.7, extended.

The KPI row says how far the estate has come. The eight sections here say
where (by material family, and by how many CPSEs describe one material), how
the machine got there (the ladder from every possible pair down to issued
codes, what vetoed the look-alikes, why pairs wait for a human, how the
matcher scores on truth it never tuned on), and what it is worth (the savings
ladder behind the KPI, the stock that has stopped moving).

Two rules. Every figure is computed from the database, and modelled money
travels with its assumption. And nothing here may cost what belongs to the
pipeline: which attribute vetoed each of 600,000 refused pairs is only known
while the matcher has the evidence in hand, and scoring a run on held-out
truth takes over a second, so both are recorded into `MatchRun.stats_json` at
run end (`pipeline.RunTally`, `metrics.record_evaluation`) and read back here.
A database whose latest run predates that recording gets the honest fallback:
the stored pairs where they carry the answer, and `null` where they do not.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from . import inventory, learn, opportunity, quality
from .blocking import PASSES
from .match import T_HIGH, T_LOW
from .metrics import TARGETS
from .models import (
    AuditEvent,
    Cluster,
    ClusterMember,
    Cnmc,
    Cpse,
    Decision,
    GoldenRecord,
    Item,
    MatchRun,
    Pair,
    RawItem,
    ReviewTask,
    Stock,
)
from .opportunity import Purchase
from .pipeline import (
    LOW_BAND_SAMPLE,
    REASON_CONFIRM_MERGE,
    REASON_CONFIRM_REFUSAL,
    RunTally,
)
from .review import BAND_ROLES, CONFLICT_ROLES
from .taxonomy import AttrSpec, load_schemas
from .visibility import Scope

#: The donut's three disjoint parts, in order. `by_class` applies the same rule
#: per row, so the family bars sum to the donut by construction.
HARMONISATION_PARTS = (
    ("coded", "Carrying a CNMC", "Through review and issued a national code."),
    (
        "duplicate_pending",
        "Duplicate found, awaiting a code",
        "Clustered with at least one other row; the code is the next step.",
    ),
    ("unique_pending", "No duplicate found", "The only row describing this material so far."),
)

#: Stock-age bins in months since the last movement. The rule's edge is one of
#: them, so the bars beyond it are exactly the dead-stock tile.
STOCK_AGE_EDGES = (0, 6, 12, 18, 24, 30)


@dataclass(frozen=True)
class Run:
    """The latest match run, with its statistics parsed once."""

    id: int
    ts: datetime
    stats: dict


def latest_run(db: Session) -> Run | None:
    row = db.execute(
        select(MatchRun.id, MatchRun.ts, MatchRun.stats_json).order_by(MatchRun.id.desc()).limit(1)
    ).first()
    if row is None:
        return None
    return Run(row[0], row[1], json.loads(row[2] or "{}"))


# --------------------------------------------------------------------------
# Where the estate stands
# --------------------------------------------------------------------------


def by_class(db: Session) -> dict:
    """The donut's three parts, per material family.

    The rule is applied to every catalogue row: coded when its cluster carries
    a CNMC, duplicate found when its cluster is uncoded and has more than one
    row, and otherwise a single-row material. A row not yet in any cluster is
    a single-row material too: no duplicate has been found for it. Counting
    per row is what lets the family bars and the donut reconcile exactly.
    """
    rows = db.execute(
        text(
            """
            WITH cm AS (
                SELECT m.cluster_id, m.item_id,
                       COUNT(*) OVER (PARTITION BY m.cluster_id) AS n
                FROM cluster_member m
            ),
            coded AS (
                SELECT DISTINCT g.cluster_id
                FROM golden_record g JOIN cnmc c ON c.golden_id = g.id
            )
            SELECT i.class_code,
                   COUNT(*),
                   COALESCE(SUM(cm.cluster_id IN (SELECT cluster_id FROM coded)), 0),
                   COALESCE(SUM(cm.cluster_id NOT IN (SELECT cluster_id FROM coded)
                                AND cm.n > 1), 0)
            FROM item i LEFT JOIN cm ON cm.item_id = i.id
            GROUP BY i.class_code
            """
        )
    ).all()
    # The family a class's codes carry: the commonest prefix among them, since
    # a cluster can hold rows of more than one class and a stray code from a
    # neighbour must not rename the family (MIN() once labelled valves MISC).
    family: dict[str, str] = {}
    for class_code, prefix, _ in db.execute(
        text(
            """
            SELECT i.class_code, substr(c.code, 1, 4) AS family, COUNT(*) AS n
            FROM cnmc c
            JOIN golden_record g ON g.id = c.golden_id
            JOIN cluster_member m ON m.cluster_id = g.cluster_id
            JOIN item i ON i.id = m.item_id
            GROUP BY i.class_code, family
            ORDER BY i.class_code, n DESC, family
            """
        )
    ).all():
        family.setdefault(class_code, prefix)
    out = []
    for class_code, total, coded, duplicate in rows:
        out.append(
            {
                "class_code": class_code,
                "family": family.get(class_code),
                "rows": total,
                "coded": coded,
                "duplicate_pending": duplicate,
                "unique_pending": total - coded - duplicate,
                "coded_share": round(coded / total, 4) if total else 0.0,
            }
        )
    out.sort(key=lambda r: (-r["coded_share"], -r["rows"], r["class_code"]))

    codes, issue_days, first_day = db.execute(
        select(
            func.count(Cnmc.id),
            func.count(func.distinct(func.date(Cnmc.issued_at))),
            func.min(func.date(Cnmc.issued_at)),
        )
    ).one()
    conflicts = (
        db.execute(
            select(func.count(GoldenRecord.id)).where(GoldenRecord.status == "conflict")
        ).scalar()
        or 0
    )
    # The trailing family is only "explained" by the conflicts when it holds
    # most of them; otherwise the note stops at the fact.
    conflicts_by_class = dict(
        db.execute(
            select(Item.class_code, func.count(func.distinct(GoldenRecord.cluster_id)))
            .join(ClusterMember, ClusterMember.cluster_id == GoldenRecord.cluster_id)
            .join(Item, Item.id == ClusterMember.item_id)
            .where(GoldenRecord.status == "conflict")
            .group_by(Item.class_code)
        ).all()
    )
    trailing = out[-1]["class_code"] if len(out) > 1 else None
    trailing_holds_most = (
        trailing is not None
        and conflicts > 0
        and conflicts_by_class.get(trailing, 0) * 2 > conflicts
    )
    if codes and issue_days == 1:
        issued = f"All {codes:,} codes were issued in one batch on {first_day}"
    elif codes:
        issued = f"{codes:,} codes have been issued over {issue_days} days"
    else:
        issued = "No code has been issued yet"
    note = (
        "A row's part is the donut's rule applied per class: coded = its cluster "
        "carries a CNMC; duplicate found = an uncoded cluster with more than one "
        f"row; the rest are single-row materials. {issued}; clusters whose golden "
        f"record is in status conflict ({conflicts:,}) are left for the workbench"
        + (
            f", which is why {trailing} trails ({conflicts_by_class[trailing]:,} of them)."
            if trailing_holds_most
            else "."
        )
    )
    return {
        "parts": [{"key": key, "label": label} for key, label, _ in HARMONISATION_PARTS],
        "rows": out,
        "note": note,
    }


def harmonisation(by_class_result: dict) -> dict:
    """The donut: the family rows summed, so the two can never disagree."""
    rows = by_class_result["rows"]
    return {
        "total": sum(r["rows"] for r in rows),
        "parts": [
            {"key": key, "label": label, "value": sum(r[key] for r in rows), "note": note}
            for key, label, note in HARMONISATION_PARTS
        ],
    }


def by_cpse_count(db: Session) -> dict:
    """How many CPSEs describe each material: the problem statement in one figure."""
    inner = (
        select(
            ClusterMember.cluster_id,
            func.count().label("n"),
            func.count(func.distinct(RawItem.cpse_id)).label("k"),
        )
        .join(Item, Item.id == ClusterMember.item_id)
        .join(RawItem, RawItem.id == Item.raw_item_id)
        .group_by(ClusterMember.cluster_id)
        .subquery()
    )
    counts = {
        k: (materials, rows, internal)
        for k, materials, rows, internal in db.execute(
            select(inner.c.k, func.count(), func.sum(inner.c.n), func.sum(inner.c.n - inner.c.k))
            .group_by(inner.c.k)
            .order_by(inner.c.k)
        ).all()
    }
    per_cpse = db.execute(
        select(Cpse.code, func.count(RawItem.id))
        .outerjoin(RawItem, RawItem.cpse_id == Cpse.id)
        .group_by(Cpse.code)
        .order_by(Cpse.code)
    ).all()
    with_rows = sum(1 for _, n in per_cpse if n)
    empty = [code for code, n in per_cpse if not n]

    rows = [
        {
            "cpses": k,
            "materials": counts.get(k, (0, 0, 0))[0],
            "rows": int(counts.get(k, (0, 0, 0))[1] or 0),
        }
        for k in range(1, with_rows + 1)
    ]
    materials = sum(r["materials"] for r in rows)
    multi_materials = sum(r["materials"] for r in rows if r["cpses"] >= 2)
    multi_rows = sum(r["rows"] for r in rows if r["cpses"] >= 2)
    internal = int(sum(v[2] or 0 for v in counts.values()))
    return {
        "rows": rows,
        "multi_materials": multi_materials,
        "multi_rows": multi_rows,
        "internal_duplicate_rows": internal,
        "cpses_with_rows": with_rows,
        "cpses_empty": empty,
        "note": (
            "A material is a cluster; a row is one CPSE's catalogue entry for it. "
            f"{multi_materials:,} of {materials:,} materials are described by more "
            f"than one CPSE. {internal:,} rows are duplicated inside a single CPSE "
            "(a cluster with more rows than CPSEs). "
            + (
                f"{', '.join(empty)} has no catalogue rows loaded, so the maximum is "
                f"{with_rows}. "
                if empty
                else ""
            )
            + "Demo data is synthetic: the near-uniform overlap between CPSEs is the "
            "generator's, not a finding."
        ),
    }


# --------------------------------------------------------------------------
# How the machine decided
# --------------------------------------------------------------------------


def pipeline(db: Session, run: Run | None) -> dict | None:
    """The ladder from every possible pair to issued codes, from the run record.

    Band totals come from the run, never from the pair table: only the most
    confident few thousand refusals are persisted, so the table would show a
    44% loss that never happened. Null when there is no run to read.
    """
    if run is None:
        return None
    stats = run.stats
    blocking = stats.get("blocking", {})
    bands = stats.get("bands", {})
    items = stats.get("items") or db.execute(select(func.count(Item.id))).scalar() or 0
    high, grey, low = bands.get("high", 0), bands.get("grey", 0), bands.get("low", 0)
    candidates = blocking.get("candidate_pairs", high + grey + low)
    multi = (
        db.execute(
            select(func.count()).select_from(
                select(ClusterMember.cluster_id)
                .group_by(ClusterMember.cluster_id)
                .having(func.count() > 1)
                .subquery()
            )
        ).scalar()
        or 0
    )
    clusters = db.execute(select(func.count(Cluster.id))).scalar() or 0
    codes = db.execute(select(func.count(Cnmc.id))).scalar() or 0

    recall = blocking.get("recall_all")
    true_pairs = blocking.get("true_pairs_all")
    missed = blocking.get("missed_all")
    recall_holdout = blocking.get("recall_holdout")
    recall_note = (
        f"blocking recall {recall:.4f} on {true_pairs:,} planted true pairs"
        + (f" ({recall_holdout:.4f} on the held-out split)" if recall_holdout is not None else "")
        if recall is not None and true_pairs is not None
        else None
    )

    rungs = [
        {
            "key": "possible",
            "label": "Possible pairs",
            "value": math.comb(items, 2),
            "unit": "pairs",
            "aside": None,
            "note": f"{items:,} rows, every pair (n choose 2)",
        },
        {
            "key": "candidates",
            "label": "Candidates after blocking",
            "value": candidates,
            "unit": "pairs",
            "aside": {"label": "true pairs no pass produced", "value": missed}
            if missed is not None
            else None,
            "note": recall_note,
        },
        {
            "key": "close",
            "label": "Close enough to matter",
            "value": high + grey,
            "unit": "pairs",
            "aside": {"label": "refused as distinct by the machine", "value": low},
            "note": None,
        },
        {
            "key": "merged",
            "label": "Merged automatically",
            "value": high,
            "unit": "pairs",
            "aside": {"label": "held for a human", "value": grey},
            "note": f"score >= {T_HIGH}, every identity-critical attribute checked",
        },
        {
            "key": "materials",
            "label": "Materials with more than one name",
            "value": multi,
            "unit": "materials",
            "aside": None,
            "note": f"{clusters:,} materials in all",
        },
        {
            "key": "codes",
            "label": "CNMCs issued",
            "value": codes,
            "unit": "codes",
            "aside": None,
            "note": None,
        },
    ]
    for i, rung in enumerate(rungs):
        previous = rungs[i - 1] if i else None
        same_unit = previous is not None and previous["unit"] == rung["unit"]
        rung["factor_from_previous"] = (
            round(previous["value"] / rung["value"], 1) if same_unit and rung["value"] else None
        )

    per_pass = blocking.get("per_pass", {})
    return {
        "run_id": run.id,
        "run_at": run.ts.isoformat() if run.ts else None,
        "rungs": rungs,
        "blocking": {
            "recall": recall,
            "true_pairs": true_pairs,
            "missed": missed,
            "passes": [
                {"pass": name, "added": per_pass[name], "note": note}
                for name, note in PASSES
                if name in per_pass
            ],
        },
        "source": "run",
    }


def _attr_specs() -> dict[str, AttrSpec]:
    """Attribute name -> its spec, from whichever class declares it first.

    Names are shared across classes with one meaning (`bore_mm` is millimetres
    everywhere), so a veto counted by attribute can be labelled without the
    class it came from.
    """
    specs: dict[str, AttrSpec] = {}
    for schema in load_schemas().values():
        for name, spec in schema.attributes.items():
            specs.setdefault(name, spec)
    return specs


_WORDS = {
    "dia": "diameter",
    "temp": "temperature",
    "max": "maximum",
    "nb": "nominal bore",
    "nps": "nominal pipe size",
    "pct": "percent",
}


def _unit_suffixes(unit: str) -> set[str]:
    """How a unit is abbreviated at the end of an attribute name: `_c` for
    degC, `_pct` for percent, otherwise the unit itself."""
    low = unit.lower()
    return {low, low.removeprefix("deg"), "pct" if low == "percent" else low}


def _attr_label(name: str, spec: AttrSpec | None) -> str:
    """A readable label derived from the attribute's name and declared unit.

    The class schema names attributes but does not label them, so the label is
    derived rather than looked up: the unit suffix comes off the name, the
    unit is printed from the schema, and the few abbreviations are spelled out.
    """
    words = name.split("_")
    unit = spec.unit if spec and spec.unit and spec.unit != "dimensionless" else None
    if unit and words[-1].lower() in _unit_suffixes(unit):
        words = words[:-1]
    label = " ".join(_WORDS.get(w, w) for w in words)
    label = label[:1].upper() + label[1:]
    return f"{label} ({unit})" if unit else label


def _render(value, spec: AttrSpec | None) -> str:
    """One value as the evidence card would print it: number and unit."""
    unit = spec.unit if spec and spec.unit and spec.unit != "dimensionless" else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    number = f"{value:g}"
    return f"{number} {unit}" if unit else number


def _stored_tally(db: Session) -> RunTally:
    """The run tally rebuilt from the pairs that kept their evidence.

    Exact for the grey band, which is always stored; partial for refusals, of
    which only the most confident few thousand keep their veto. The caller
    says which it is.
    """
    tally = RunTally()
    for verdict, band, confidence, veto_json in db.execute(
        select(Pair.verdict, Pair.band, Pair.confidence, Pair.veto_json).where(
            or_(Pair.veto_json.is_not(None), Pair.band == "grey")
        )
    ).all():
        tally.add(verdict, band, confidence, json.loads(veto_json) if veto_json else None)
    return tally


def tally_for(db: Session, run: Run | None) -> tuple[dict, str]:
    """The veto and grey-band counters, and where they came from.

    `run` when the pipeline recorded them over every pair it scored;
    `stored_pairs` for an older run, rebuilt from the evidence that was kept.
    """
    if run and "veto_attributes" in run.stats and "held_for_review" in run.stats:
        return run.stats, "run"
    return _stored_tally(db).as_stats(), "stored_pairs"


def _refused_total(db: Session, run: Run | None) -> int:
    if run and "bands" in run.stats:
        return run.stats["bands"].get("low", 0)
    return db.execute(select(func.count(Pair.id)).where(Pair.band == "low")).scalar() or 0


def veto_attributes(db: Session, run: Run | None, tally: tuple[dict, str] | None = None) -> dict:
    """Which attribute kept look-alikes apart, and whether it defines the part
    or rates its performance. Counted as distinct pairs per attribute."""
    stats, source = tally or tally_for(db, run)
    counted = stats["veto_attributes"]
    specs = _attr_specs()
    by_attr = sorted(counted["by_attribute"].items(), key=lambda kv: (-kv[1]["pairs"], kv[0]))
    top, rest = by_attr[:10], by_attr[10:]
    cosmetic = sorted(name for name, spec in specs.items() if spec.role == "cosmetic")
    refused_total = _refused_total(db, run)
    coverage = {
        "conflict": counted["conflict"],
        "refused": counted["refused"],
        "refused_total": refused_total,
    }
    if source == "run":
        covered = (
            f"Covers every vetoed pair of the run: {coverage['conflict']:,} conflicts and "
            f"{coverage['refused']:,} of {refused_total:,} refusals."
        )
    else:
        covered = (
            f"Covers the {counted['pairs_with_veto']:,} vetoed pairs whose evidence was "
            f"stored: all {coverage['conflict']:,} conflicts and {coverage['refused']:,} of "
            f"the {refused_total:,} refusals; the rest were refused without keeping "
            "their evidence, which the pipeline now counts at run time."
        )
    return {
        "source": source,
        "pairs_with_veto": counted["pairs_with_veto"],
        "coverage": coverage,
        "by_attribute": [
            {
                "attr": attr,
                "label": _attr_label(attr, specs.get(attr)),
                "role": entry["role"],
                "pairs": entry["pairs"],
                "example": {
                    "a": _render(entry["example"]["a"], specs.get(attr)),
                    "b": _render(entry["example"]["b"], specs.get(attr)),
                    "reason": entry["example"]["reason"],
                }
                if entry.get("example")
                else None,
            }
            for attr, entry in top
        ],
        "other": {"attributes": len(rest), "pairs": sum(e["pairs"] for _, e in rest)},
        "attrs_per_pair": [
            {"n": int(n), "pairs": pairs}
            for n, pairs in sorted(counted["attrs_per_pair"].items(), key=lambda kv: int(kv[0]))
        ],
        "cosmetic_never_vetoes": cosmetic,
        "note": (
            "Bars are pairs, and a pair refused on two attributes appears under both, "
            "so the bars can exceed the pair count; the strip beside them says how many "
            f"attributes each pair carried. Cosmetic attributes ({', '.join(cosmetic)}) "
            f"never veto and are excluded. {covered} The attribute mix is the synthetic "
            "seed's; veto precision on planted traps is the measure of the veto layer."
        ),
    }


def held_for_review(
    db: Session,
    run: Run | None,
    evaluation: dict | None,
    tally: tuple[dict, str] | None = None,
) -> dict:
    """The honest twin of the automation tile: what is in the other 0.6%."""
    stats, _source = tally or tally_for(db, run)
    parts = stats["held_for_review"]
    conflict, review = parts["conflict"], parts["review"]
    total = (
        run.stats["bands"].get("grey", 0)
        if run and "bands" in run.stats
        else db.execute(select(func.count(Pair.id)).where(Pair.band == "grey")).scalar() or 0
    )
    queue = {
        (band, state): n
        for band, state, n in db.execute(
            select(ReviewTask.band, ReviewTask.state, func.count(ReviewTask.id)).group_by(
                ReviewTask.band, ReviewTask.state
            )
        ).all()
    }
    decisions = db.execute(
        select(Decision.action, func.count(Decision.id), func.max(Decision.ts)).group_by(
            Decision.action
        )
    ).all()
    last_at = max((ts for _, _, ts in decisions if ts is not None), default=None)
    labels = learn.label_counts(db)
    precision = None
    if evaluation:
        precision = next(
            (row["value"] for row in evaluation["rows"] if row["key"] == "precision"), None
        )
    sample_of = _refused_total(db, run)
    return {
        "total": total,
        "thresholds": {"t_low": T_LOW, "t_high": T_HIGH},
        "reasons": [
            {
                "key": "conflict",
                "label": "Same part number, but a specification disagrees",
                "pairs": conflict["pairs"],
                "confidence": conflict["confidence"],
                "owner_roles": list(CONFLICT_ROLES),
                "parts": [
                    {
                        "key": "identity_critical",
                        "label": "An identity-critical attribute differs",
                        "pairs": conflict["identity_critical"],
                        "equivalence_flagged": None,
                    },
                    {
                        "key": "performance_only",
                        "label": "Only a performance rating is out of band",
                        "pairs": conflict["performance_only"],
                        "equivalence_flagged": conflict["equivalence_flagged"],
                    },
                ],
            },
            {
                "key": "review",
                "label": "Scored inside the grey zone",
                "pairs": review["pairs"],
                "confidence": review["confidence"],
                "owner_roles": list(BAND_ROLES["grey"]),
                "parts": None,
            },
        ],
        "also_queued": [
            {
                "band": "high",
                "reason": REASON_CONFIRM_MERGE,
                "pending": queue.get(("high", "pending"), 0),
                "done": queue.get(("high", "done"), 0),
                "disposition": "policy",
                "evidence": {"duplicate_precision": precision, "split": "holdout"},
            },
            {
                "band": "low",
                "reason": REASON_CONFIRM_REFUSAL,
                "pending": queue.get(("low", "pending"), 0),
                "done": queue.get(("low", "done"), 0),
                "disposition": "audit_sample",
                "sample_of": sample_of,
            },
        ],
        "decisions": {
            "by_action": {action: n for action, n, _ in decisions},
            "total": sum(n for _, n, _ in decisions),
            "last_at": last_at.isoformat() if last_at else None,
            "seconds": _seconds_per_decision(db),
            "undone": db.execute(
                select(func.count(AuditEvent.id)).where(AuditEvent.action == "decision.undo")
            ).scalar()
            or 0,
        },
        "labels": {
            "reviewer": labels.get("reviewer", 0),
            "simulated": labels.get("simulated", 0),
        },
        "note": (
            "The automation tile counts the machine's decisions; this is the rest. A "
            "conflict is a pair the machine is sure shares a part number and sure the "
            "specifications disagree: a data-quality defect for an approver, not a "
            "matching doubt. A grey-zone pair scored between the two thresholds and "
            "needs a steward. The high-band queue is a policy choice to confirm "
            f"automatic merges; the low-band queue is an audit sample of {sample_of:,} "
            f"refusals (at most {LOW_BAND_SAMPLE:,} of them). Simulated labels are named "
            "as such."
        ),
    }


def _seconds_per_decision(db: Session) -> dict | None:
    """How long a card was on screen before it was decided: the first number a
    pilot is judged on. Reported by the client on each decision and kept on
    the audit event; only decisions that reported it count. Median and the
    90th percentile, never a mean — one reviewer's tea break is not a trend."""
    seconds: list[float] = []
    rows = db.execute(
        select(AuditEvent.payload_json).where(
            AuditEvent.action.in_(("decision.approve", "decision.reject"))
        )
    ).scalars()
    for raw in rows:
        value = json.loads(raw).get("seconds")
        if isinstance(value, int | float) and 0 < value < 3600:
            seconds.append(float(value))
    if not seconds:
        return None
    seconds.sort()
    n = len(seconds)
    return {
        "n": n,
        "median": round(seconds[n // 2], 1),
        "p90": round(seconds[min(n - 1, int(n * 0.9))], 1),
    }


def evaluation(db: Session, run: Run | None) -> dict | None:
    """The held-out scorecard, read from the snapshot the pipeline wrote.

    Null when the latest run carries no snapshot: the page shows an empty
    state pointing at `make evaluate`, never a cached constant.
    """
    snapshot = run.stats.get("evaluation") if run else None
    if not snapshot:
        return None
    # A scorecard needs truth to score against. The synthetic estate plants
    # truth groups; a CPSE's own upload carries none, and a run over such data
    # would otherwise record precision 0.0 and a failed gate for a matcher that
    # was never measured. No truth, no scorecard: the page says so.
    if not snapshot.get("counts", {}).get("truth_groups_holdout"):
        return None
    pairwise = snapshot["duplicate"]["pairwise"]
    bcubed = snapshot["duplicate"]["bcubed"]
    baseline = snapshot["baseline_exact_text"]["pairwise"]
    blocking = snapshot["blocking"]
    veto = snapshot["veto"]

    def row(key, label, value, target, baseline_value, detail):
        return {
            "key": key,
            "label": label,
            "value": value,
            "target": target,
            "pass": (value >= target) if target is not None else None,
            "baseline": baseline_value,
            "detail": detail,
        }

    merged = pairwise["true_positives"] + pairwise["false_positives"]
    true_pairs = pairwise["true_positives"] + pairwise["false_negatives"]
    in_band = (
        round(veto["in_band_accuracy"] * veto["in_band_total"])
        if veto.get("in_band_accuracy") is not None
        else None
    )
    rows = [
        row(
            "precision",
            "Pairwise precision",
            pairwise["precision"],
            TARGETS["duplicate_precision"],
            baseline["precision"],
            f"{pairwise['false_positives']:,} false positives among {merged:,} merged pairs",
        ),
        row(
            "recall",
            "Pairwise recall",
            pairwise["recall"],
            TARGETS["duplicate_recall"],
            baseline["recall"],
            f"{pairwise['false_negatives']:,} of {true_pairs:,} true pairs missed",
        ),
        row("f1", "Pairwise F1", pairwise["f1"], None, baseline["f1"], None),
        row(
            "bcubed_f1",
            "B-cubed F1 (cluster level)",
            bcubed["f1"],
            None,
            None,
            f"every one of {bcubed['items']:,} held-out rows weighted equally",
        ),
    ]
    if blocking.get("recall") is not None:
        rows.append(
            row(
                "blocking_recall",
                "Blocking recall",
                blocking["recall"],
                TARGETS["blocking_recall"],
                None,
                f"{blocking['stats'].get('true_pairs_holdout', 0):,} held-out true pairs",
            )
        )
    rows.append(
        row(
            "veto_precision",
            "Veto precision",
            veto["precision"],
            TARGETS["veto_precision"],
            None,
            f"{veto['traps_refused']:,} of {veto['traps_total']:,} traps refused"
            + (
                f"; {in_band:,} of {veto['in_band_total']:,} in-band merged"
                if in_band is not None
                else ""
            ),
        )
    )
    computed_at = datetime.fromisoformat(snapshot["computed_at"])
    since = (
        db.execute(select(func.count(Decision.id)).where(Decision.ts > computed_at)).scalar() or 0
    )
    return {
        "run_id": run.id,
        "computed_at": snapshot["computed_at"],
        "split": snapshot["split"],
        "items_holdout": snapshot["counts"]["items_holdout"],
        "decisions_since": since,
        "rows": rows,
        "baseline_note": snapshot["baseline_exact_text"]["note"],
        "per_class": sorted(
            (
                {
                    "class_code": r["class_code"],
                    "items": r["items"],
                    "precision": r["precision"],
                    "recall": r["recall"],
                    "f1": r["f1"],
                    "false_negatives": r["false_negatives"],
                }
                for r in snapshot["per_class"]
            ),
            key=lambda r: (r["f1"], r["class_code"]),
        ),
        "worst_class": snapshot["worst_class"],
        "note": snapshot["note"],
    }


# --------------------------------------------------------------------------
# What it is worth
# --------------------------------------------------------------------------


def savings_ladder(db: Session, scope: Scope, purchases: list[Purchase] | None = None) -> dict:
    """From last year's purchases to the savings figure, one rung at a time.

    Built from the same call that produces the savings KPI, so the bottom rung
    is the tile's number by construction. Totals only: per-material and
    per-CPSE prices stay on the opportunity page, where §0.9b redaction applies.
    """
    tenders = opportunity.joint_tender_candidates(db, scope, limit=0, purchases=purchases)
    capture = tenders["capture_assumption"]
    ceiling = tenders["total_max_opportunity"]
    rungs = [
        {
            "key": "spend",
            "label": f"Purchases in the last {tenders['window_months']} months",
            "value_inr": tenders["spend_in_window"],
            "materials": tenders["materials_in_window"],
            "orders": tenders["orders_in_window"],
            "assumption": None,
        },
        {
            "key": "shared",
            "label": "On materials two or more CPSEs buy",
            "value_inr": tenders["shared_spend"],
            "materials": tenders["candidates_found"],
            "orders": tenders["shared_orders"],
            "assumption": None,
        },
        {
            "key": "ceiling",
            "label": "If every order had been at the best price paid",
            "value_inr": ceiling,
            "materials": tenders["candidates_found"],
            "orders": None,
            "assumption": (
                "Upper bound: every order in the window at the lowest per-base-unit "
                "price any CPSE paid. Not a forecast."
            ),
        },
        {
            "key": "estimate",
            "label": f"Savings identified at {round(capture * 100)}% capture",
            "value_inr": tenders["total_estimated_saving"],
            "materials": None,
            "orders": None,
            "assumption": tenders["assumption_note"],
            "sensitivity": {
                "capture_low": 0.4,
                "value_low_inr": round(ceiling * 0.4, 2),
                "capture_high": 0.8,
                "value_high_inr": round(ceiling * 0.8, 2),
            },
        },
    ]
    for i, rung in enumerate(rungs):
        previous = rungs[i - 1]["value_inr"] if i else None
        rung["share_of_previous"] = round(rung["value_inr"] / previous, 4) if previous else None
    return {
        "window_months": tenders["window_months"],
        "capture": capture,
        "assumption_note": tenders["assumption_note"],
        "rungs": rungs,
        "synthetic_note": (
            "Purchase history is seeded; the overlap between CPSEs is near-uniform by "
            "construction and the share of spend on shared materials will not look "
            "like this in real catalogues."
        ),
    }


def stock_age(db: Session, purchases: list[Purchase]) -> dict:
    """Stock by months since its last movement, with the dead-stock rule drawn.

    The bin edges are `inventory._cutoff` at 6, 12, 18, 24 and 30 months, the
    same 31-day months `dead_stock` uses, so the bins beyond the rule sum to
    the dead-stock tile exactly. A position is "demand elsewhere" when a CPSE
    other than its holder bought the material inside the demand window: a
    visibility signal, never avoidable spend.
    """
    rule = inventory.DEAD_STOCK_MONTHS
    edges = list(STOCK_AGE_EDGES)
    cutoffs = [inventory._cutoff(months) for months in edges[1:]]
    bought_by: dict[int, set[str]] = {}
    for purchase in purchases:
        bought_by.setdefault(purchase.cluster_id, set()).add(purchase.cpse)

    bins = [
        {
            "from_months": edges[i],
            "to_months": edges[i + 1] if i + 1 < len(edges) else None,
            "label": f"{edges[i]}–{edges[i + 1]}" if i + 1 < len(edges) else f"{edges[i]}+",
            "positions": 0,
            "materials": set(),
            "value_inr": 0.0,
            "demand_elsewhere_value_inr": 0.0,
            "no_demand_value_inr": 0.0,
            "idle": edges[i] >= rule,
        }
        for i in range(len(edges))
    ]

    def bin_for(moved: date) -> dict:
        for i, cutoff in enumerate(cutoffs):
            if moved >= cutoff:
                return bins[i]
        return bins[-1]

    idle_materials: set[int] = set()
    idle_demand_materials: set[int] = set()
    value_by_class: Counter[str] = Counter()
    counted = 0
    for cluster_id, cpse, moved, value, class_code in db.execute(
        select(
            ClusterMember.cluster_id,
            Cpse.code,
            Stock.last_movement_date,
            Stock.qty_on_hand * Stock.unit_value,
            Item.class_code,
        )
        .join(Item, Item.id == Stock.item_id)
        .join(ClusterMember, ClusterMember.item_id == Stock.item_id)
        .join(Cpse, Cpse.id == Stock.cpse_id)
        .where(Stock.qty_on_hand > 0, Stock.last_movement_date.is_not(None))
    ).all():
        counted += 1
        entry = bin_for(moved)
        value = value or 0.0
        entry["positions"] += 1
        entry["materials"].add(cluster_id)
        entry["value_inr"] += value
        elsewhere = bool(bought_by.get(cluster_id, set()) - {cpse})
        entry["demand_elsewhere_value_inr" if elsewhere else "no_demand_value_inr"] += value
        if entry["idle"]:
            idle_materials.add(cluster_id)
            value_by_class[class_code] += value
            if elsewhere:
                idle_demand_materials.add(cluster_id)

    for entry in bins:
        entry["materials"] = len(entry["materials"])
        for key in ("value_inr", "demand_elsewhere_value_inr", "no_demand_value_inr"):
            entry[key] = round(entry[key], 2)
    idle_bins = [b for b in bins if b["idle"]]
    idle_value = sum(b["value_inr"] for b in idle_bins)
    positions_total = inventory.stock_totals(db)["positions"]
    top = value_by_class.most_common(1)
    return {
        "rule_months": rule,
        "quality_stale_months": quality.STALE_MONTHS,
        "demand_window_months": opportunity.WINDOW_MONTHS,
        "bins": bins,
        "idle": {
            "value_inr": round(idle_value, 2),
            "positions": sum(b["positions"] for b in idle_bins),
            "materials": len(idle_materials),
            "demand_elsewhere_value_inr": round(
                sum(b["demand_elsewhere_value_inr"] for b in idle_bins), 2
            ),
            "demand_elsewhere_materials": len(idle_demand_materials),
        },
        "top_class": {
            "class_code": top[0][0],
            "share_of_idle_value": round(top[0][1] / idle_value, 4) if idle_value else 0.0,
        }
        if top
        else None,
        "excluded_positions": positions_total - counted,
        "note": (
            f"Age is months since the last stock movement, in the {rule}-month rule "
            "inventory.dead_stock applies (31-day months), so the bars beyond "
            f"{rule} months sum to the dead-stock tile. Demand elsewhere means a "
            f"sister CPSE bought the same material in the last {opportunity.WINDOW_MONTHS} "
            "months: a visibility signal, not avoidable spend. The data-quality "
            f"scorecard's staleness rule is a different one ({quality.STALE_MONTHS} months "
            f"without a purchase or a movement). {positions_total - counted:,} positions "
            "with no movement date, no quantity, or no cluster yet are not binned. "
            "Valuations are synthetic."
        ),
    }
