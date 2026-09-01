"""SQLAlchemy models — spec §4.

Naming follows the spec table list exactly. Two conventions throughout:

* JSON payloads are stored as TEXT columns holding canonical JSON, so the audit
  hash chain (§0.9a) can re-serialise them byte-identically.
* `raw_item.price` / `raw_item.qty_on_hand` are provenance only. `purchase_history`
  is authoritative for price analytics and `stock` for inventory — see the
  data-authority note in §4. Dashboards and the Copilot must not read prices
  from `raw_item`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Organisations, users
# --------------------------------------------------------------------------


class Cpse(Base):
    __tablename__ = "cpse"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))

    raw_items: Mapped[list[RawItem]] = relationship(back_populates="cpse")


class User(Base):
    __tablename__ = "users"  # "user" is reserved in several SQL dialects

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # registrar|admin|approver|steward|auditor|viewer
    password_hash: Mapped[str] = mapped_column(String(256))
    cpse_id: Mapped[int | None] = mapped_column(ForeignKey("cpse.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    cpse: Mapped[Cpse | None] = relationship()


# --------------------------------------------------------------------------
# Catalogue: raw rows in, normalized items out
# --------------------------------------------------------------------------


class RawItem(Base):
    """A row exactly as it arrived from a CPSE catalogue. Never edited."""

    __tablename__ = "raw_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    cpse_id: Mapped[int] = mapped_column(ForeignKey("cpse.id"), index=True)
    legacy_code: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    uom: Mapped[str | None] = mapped_column(String(16), nullable=True)
    plant: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty_on_hand: Mapped[float | None] = mapped_column(Float, nullable=True)

    cpse: Mapped[Cpse] = relationship(back_populates="raw_items")
    item: Mapped[Item | None] = relationship(back_populates="raw_item", uselist=False)

    __table_args__ = (
        # Spec §8A: the lookup the ingest de-duplicator and ERP mapping both use.
        Index("ix_raw_item_cpse_legacy", "cpse_id", "legacy_code", unique=True),
    )


class Item(Base):
    """The normalized, classified, attribute-extracted view of a raw row."""

    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_item.id"), unique=True, index=True)
    norm_text: Mapped[str] = mapped_column(Text)
    norm_hash: Mapped[str] = mapped_column(String(64), index=True)  # Tier-0 exact text key
    lang: Mapped[str] = mapped_column(String(8), default="en")
    class_code: Mapped[str] = mapped_column(String(64), index=True)
    class_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    mpn_norm: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    gtin: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    uom_base: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pack_qty: Mapped[float] = mapped_column(Float, default=1.0)
    attrs_json: Mapped[str] = mapped_column(Text, default="{}")
    embed_vector: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    raw_item: Mapped[RawItem] = relationship(back_populates="item")


# --------------------------------------------------------------------------
# Matching: pairs, clusters, golden records, codes
# --------------------------------------------------------------------------


class Pair(Base):
    """A candidate pair with its per-tier scores and any hard-constraint veto."""

    __tablename__ = "pair"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_a: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    item_b: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    tier_scores_json: Mapped[str] = mapped_column(Text, default="{}")
    verdict: Mapped[str] = mapped_column(String(16))  # duplicate|conflict|distinct|review
    band: Mapped[str] = mapped_column(String(8), default="grey")  # high|grey|low
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    veto_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")

    __table_args__ = (UniqueConstraint("item_a", "item_b", name="uq_pair_items"),)


class Relation(Base):
    """Directed functional equivalence — a different relation from duplication (§2B)."""

    __tablename__ = "relation"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_a: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    item_b: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    rel_type: Mapped[str] = mapped_column(String(16))  # duplicate|equivalent|supersedes
    direction: Mapped[str] = mapped_column(String(16))  # bidirectional|a_to_b
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    basis: Mapped[str] = mapped_column(String(16))  # designation|crossref|rule|llm
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="proposed")


class SubstitutionRule(Base):
    """Per-class YAML substitution rules — data, not code (§2B)."""

    __tablename__ = "substitution_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_code: Mapped[str] = mapped_column(String(64), index=True)
    rule_yaml: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Crossref(Base):
    """OEM cross-reference: interchangeable part numbers across manufacturers (§2B)."""

    __tablename__ = "crossref"

    id: Mapped[int] = mapped_column(primary_key=True)
    mpn_a: Mapped[str] = mapped_column(String(64), index=True)
    brand_a: Mapped[str] = mapped_column(String(64))
    mpn_b: Mapped[str] = mapped_column(String(64), index=True)
    brand_b: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64), default="seed")


class Cluster(Base):
    __tablename__ = "cluster"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|conflict

    members: Mapped[list[ClusterMember]] = relationship(back_populates="cluster")
    golden: Mapped[GoldenRecord | None] = relationship(back_populates="cluster", uselist=False)


class ClusterMember(Base):
    __tablename__ = "cluster_member"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("cluster.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)

    cluster: Mapped[Cluster] = relationship(back_populates="members")

    __table_args__ = (UniqueConstraint("cluster_id", "item_id", name="uq_cluster_member"),)


class GoldenRecord(Base):
    __tablename__ = "golden_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("cluster.id"), unique=True, index=True)
    std_description: Mapped[str] = mapped_column(Text)
    attrs_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|conflict
    # Separation of duties (§0.9): proposer and approver are recorded separately
    # and the API refuses to let them be the same user.
    proposed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    cluster: Mapped[Cluster] = relationship(back_populates="golden")


class GoldenFieldProvenance(Base):
    """Which member and which fusion rule produced each golden field (§2D)."""

    __tablename__ = "golden_field_provenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    golden_id: Mapped[int] = mapped_column(ForeignKey("golden_record.id"), index=True)
    field: Mapped[str] = mapped_column(String(64))
    source_member_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"), nullable=True)
    rule: Mapped[str] = mapped_column(String(64))


class Cnmc(Base):
    """The Common National Material Code issued for an approved golden record."""

    __tablename__ = "cnmc"

    id: Mapped[int] = mapped_column(primary_key=True)
    golden_id: Mapped[int] = mapped_column(ForeignKey("golden_record.id"), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    issued_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------
# Review workflow
# --------------------------------------------------------------------------


class ReviewTask(Base):
    __tablename__ = "review_task"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("cluster.id"), nullable=True, index=True
    )
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("pair.id"), nullable=True, index=True)
    band: Mapped[str] = mapped_column(String(8), index=True)  # high|grey|low
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|done
    assignee_role: Mapped[str] = mapped_column(String(16), default="steward")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Decision(Base):
    __tablename__ = "decision"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_task.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # approve|reject|merge|split
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------
# Commercial & inventory facts (authoritative for analytics — see §4 note)
# --------------------------------------------------------------------------


class PurchaseHistory(Base):
    """Authoritative source for all price analytics (see the §4 data-authority note).

    `unit_price` is the price paid **per catalogued unit** — the PO line price
    for the UoM that was ordered, which is what an ERP holds. Comparing a box
    of 100 with a single piece therefore requires dividing by `item.pack_qty`,
    and that normalization is the analytics layer's job (§2A.1, §9A).
    """

    __tablename__ = "purchase_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    cpse_id: Mapped[int] = mapped_column(ForeignKey("cpse.id"), index=True)
    po_date: Mapped[date] = mapped_column(Date, index=True)
    qty: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)
    vendor: Mapped[str] = mapped_column(String(128))


class Stock(Base):
    __tablename__ = "stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    cpse_id: Mapped[int] = mapped_column(ForeignKey("cpse.id"), index=True)
    plant: Mapped[str] = mapped_column(String(32))
    qty_on_hand: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_qty: Mapped[float] = mapped_column(Float, default=0.0)
    last_movement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit_value: Mapped[float] = mapped_column(Float, default=0.0)


# --------------------------------------------------------------------------
# ERP migration journal (§2C)
# --------------------------------------------------------------------------


class MigrationBatch(Base):
    __tablename__ = "migration_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MigrationChange(Base):
    __tablename__ = "migration_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("migration_batch.id"), index=True)
    erp_table: Mapped[str] = mapped_column(String(32))
    erp_key: Mapped[str] = mapped_column(String(64))
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="planned")  # applied|held|rolled_back


class SmartCreateCheck(Base):
    """One duplicate-prevention check at the point of creation (§5).

    Kept as a row rather than an audit event because the outcome is *counted*:
    the prevention rate on the health dashboard is the honest measure of whether
    the platform stops duplicates being born, and it needs the denominator --
    every check -- as much as the numerator.
    """

    __tablename__ = "smart_create_check"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cpse_id: Mapped[int | None] = mapped_column(ForeignKey("cpse.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    norm_text: Mapped[str] = mapped_column(Text)
    class_code: Mapped[str] = mapped_column(String(64), default="unclassified")
    top_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    candidates: Mapped[int] = mapped_column(Integer, default=0)
    #: open | prevented | created_anyway
    outcome: Mapped[str] = mapped_column(String(16), default="open", index=True)
    #: The existing item reused, when the outcome is `prevented`.
    reused_item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"), nullable=True)
    #: The raw row created, when the outcome is `created_anyway`.
    created_raw_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_item.id"), nullable=True
    )
    #: Why the requester overrode a high-confidence match. Required by the API.
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------
# Governance
# --------------------------------------------------------------------------


class AuditEvent(Base):
    """Hash-chained, tamper- and reorder-evident event log (§0.8, §0.9a)."""

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    user: Mapped[str] = mapped_column(String(128), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class MatchRun(Base):
    """One pipeline matching run, with the statistics behind it.

    Blocking recall (§2A.1) can only be measured while the candidate set is in
    memory — persisting every candidate pair would mean hundreds of thousands
    of rows for a number. The run record keeps the measurement instead.
    """

    __tablename__ = "match_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")


# --------------------------------------------------------------------------
# Ground truth — never read by the pipeline, only by metrics (§0.6)
# --------------------------------------------------------------------------


class TruthGroup(Base):
    """Which real product a raw row actually is, plus its evaluation split."""

    __tablename__ = "truth_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_item.id"), unique=True, index=True)
    group_id: Mapped[str] = mapped_column(String(64), index=True)
    # §0.6: thresholds are tuned on `tuning` only; every reported number is `holdout`.
    split: Mapped[str] = mapped_column(String(8), default="tuning", index=True)


class TruthTrap(Base):
    """A planted near-miss the veto layer must refuse (§2A acceptance, §7)."""

    __tablename__ = "truth_trap"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_item_a: Mapped[int] = mapped_column(ForeignKey("raw_item.id"), index=True)
    raw_item_b: Mapped[int] = mapped_column(ForeignKey("raw_item.id"), index=True)
    trap_kind: Mapped[str] = mapped_column(String(32))  # identity_critical|performance_band|...
    offending_attr: Mapped[str] = mapped_column(String(64))
    value_a: Mapped[str] = mapped_column(String(64))
    value_b: Mapped[str] = mapped_column(String(64))
    # True when the pair really is a duplicate despite looking like a trap
    # (in-band performance difference), False when it must be refused.
    expect_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    split: Mapped[str] = mapped_column(String(8), default="tuning", index=True)


class TruthEquivalence(Base):
    """Ground truth for the directed equivalence engine (§2B acceptance)."""

    __tablename__ = "truth_equivalence"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_item_a: Mapped[int] = mapped_column(ForeignKey("raw_item.id"), index=True)
    raw_item_b: Mapped[int] = mapped_column(ForeignKey("raw_item.id"), index=True)
    rel_type: Mapped[str] = mapped_column(String(16))  # equivalent|supersedes
    direction: Mapped[str] = mapped_column(String(16))  # bidirectional|a_to_b
    basis: Mapped[str] = mapped_column(String(16))  # designation|crossref|rule
    split: Mapped[str] = mapped_column(String(8), default="tuning", index=True)
