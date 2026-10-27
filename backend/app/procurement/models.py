"""Pricing Intelligence (procurement valuation) tables.

All money columns are NUMERIC(14,2) read back as ``Decimal``. Nullable means missing:
a NULL price is "not priced", never zero.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import JSONType, utcnow

PIMoney = Numeric(14, 2)


class PIProduct(Base):
    """A normalised product identity. Identical assets across rows and batches share one product."""

    __tablename__ = "pi_products"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_key: Mapped[str] = mapped_column(String(300), unique=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(300))
    spec: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PIBatch(Base):
    """ValuationBatch: one uploaded vendor workbook."""

    __tablename__ = "pi_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    vendor: Mapped[str | None] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    file_kind: Mapped[str] = mapped_column(String(8))
    layout: Mapped[str] = mapped_column(String(20))  # b001 | b002 | generic | manual_entry
    sheet_name: Mapped[str | None] = mapped_column(String(120))
    header_row: Mapped[int | None] = mapped_column(Integer)
    column_map: Mapped[dict] = mapped_column(JSONType)  # canonical field -> source header
    price_column: Mapped[str | None] = mapped_column(String(120))  # existing header to fill, if any
    qty_column: Mapped[str | None] = mapped_column(String(120))
    detection: Mapped[dict | None] = mapped_column(JSONType)  # scores, skipped rows, warnings
    status: Mapped[str] = mapped_column(String(20), default="imported")  # imported|researching|priced|approved
    rule_version_id: Mapped[int | None] = mapped_column(ForeignKey("pi_rule_versions.id"))
    priced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PIAsset(Base):
    """ImportedAsset + NormalizedAsset: one source row, its original cells and its normalised identity."""

    __tablename__ = "pi_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("pi_batches.id", ondelete="CASCADE"), index=True)
    sheet: Mapped[str] = mapped_column(String(120))
    row_number: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSONType)
    serial: Mapped[str | None] = mapped_column(String(160), index=True)
    quantity: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(40), index=True)
    grade: Mapped[str | None] = mapped_column(String(10))
    original_spec: Mapped[str | None] = mapped_column(Text)
    normalized: Mapped[dict] = mapped_column(JSONType)
    identify_confidence: Mapped[str] = mapped_column(String(10))  # high | medium | low
    identify_method: Mapped[str] = mapped_column(String(20), default="rules")  # rules | ai_suggested | manual
    product_id: Mapped[int | None] = mapped_column(ForeignKey("pi_products.id"), index=True)
    estimate_id: Mapped[int | None] = mapped_column(ForeignKey("pi_estimates.id"))
    calculated_price: Mapped[Decimal | None] = mapped_column(PIMoney)
    override_price: Mapped[Decimal | None] = mapped_column(PIMoney)
    override_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="unpriced", index=True)
    # unpriced | auto_priced | provisional | review | manual_required | approved
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("batch_id", "sheet", "row_number", name="uq_pi_asset_row"),)

    @property
    def final_price(self) -> Decimal | None:
        return self.override_price if self.override_price is not None else self.calculated_price


class PISource(Base):
    """Market Source Library entry. Listing a source does not imply permission to scrape it."""

    __tablename__ = "pi_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(200), unique=True)
    source_kind: Mapped[str] = mapped_column(String(40))  # refurb_retailer | marketplace | buyback | wholesaler | internal
    default_price_type: Mapped[str | None] = mapped_column(String(30))
    reliability: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1, administrator-set
    categories: Mapped[list | None] = mapped_column(JSONType)
    region: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    terms_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PIObservation(Base):
    """MarketObservation. ``status`` separates verified evidence from unreviewed search candidates."""

    __tablename__ = "pi_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("pi_products.id"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("pi_sources.id"))
    provider: Mapped[str] = mapped_column(String(30))  # manual | brave | tavily | reference_pack | outcome
    price_type: Mapped[str] = mapped_column(String(30))
    # refurb_retail | second_hand_ask | buyback_quote | bulk_wholesale | verified_transaction |
    # supplier_quote | historical_valuation
    match_quality: Mapped[str] = mapped_column(String(12))  # identical | comparable
    title: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(PIMoney)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    tax_basis: Mapped[str] = mapped_column(String(12), default="unknown")
    condition: Mapped[str | None] = mapped_column(String(60))
    seller: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[str | None] = mapped_column(String(20))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snippet: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(12), default="candidate", index=True)  # candidate|verified|rejected
    status_reason: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(64))
    research_job_id: Mapped[int | None] = mapped_column(ForeignKey("pi_research_jobs.id"))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("product_id", "dedup_key", name="uq_pi_observation_dedup"),)


class PIRuleVersion(Base):
    __tablename__ = "pi_rule_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    rules: Mapped[dict] = mapped_column(JSONType)
    rules_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PIEstimate(Base):
    """PriceEstimate for one product/grade group within a batch, with its full calculation breakdown."""

    __tablename__ = "pi_estimates"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("pi_batches.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("pi_products.id"), index=True)
    grade: Mapped[str] = mapped_column(String(10), default="")
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("pi_rule_versions.id"))
    engine_version: Mapped[str] = mapped_column(String(20))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    group_quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # priced | provisional | manual_required
    benchmark: Mapped[Decimal | None] = mapped_column(PIMoney)
    recommended_unit: Mapped[Decimal | None] = mapped_column(PIMoney)
    opening_unit: Mapped[Decimal | None] = mapped_column(PIMoney)
    max_unit: Mapped[Decimal | None] = mapped_column(PIMoney)
    resale_unit: Mapped[Decimal | None] = mapped_column(PIMoney)
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    confidence: Mapped[str | None] = mapped_column(String(10))
    confidence_score: Mapped[int | None] = mapped_column(Integer)
    breakdown: Mapped[dict] = mapped_column(JSONType)
    observation_ids: Mapped[list] = mapped_column(JSONType)
    input_hash: Mapped[str] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("batch_id", "product_id", "grade", "input_hash", name="uq_pi_estimate_input"),)


class PIResearchJob(Base):
    __tablename__ = "pi_research_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("pi_batches.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | running | completed | completed_with_errors | failed | cancelled
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[int] = mapped_column(Integer, default=0)
    observations_found: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    params: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PIResearchTask(Base):
    __tablename__ = "pi_research_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("pi_research_jobs.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("pi_products.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | running | done | cached | failed | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    queries: Mapped[list | None] = mapped_column(JSONType)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    observations_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("job_id", "product_id", name="uq_pi_task_product"),)


class PIException(Base):
    __tablename__ = "pi_exceptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("pi_batches.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("pi_assets.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("pi_products.id"))
    code: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # high | medium | low
    message: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("batch_id", "asset_id", "code", name="uq_pi_exception"),)


class PIOverride(Base):
    __tablename__ = "pi_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("pi_assets.id", ondelete="CASCADE"), index=True)
    calculated_price: Mapped[Decimal | None] = mapped_column(PIMoney)
    previous_price: Mapped[Decimal | None] = mapped_column(PIMoney)
    new_price: Mapped[Decimal | None] = mapped_column(PIMoney)
    reason: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PIQuotation(Base):
    __tablename__ = "pi_quotations"
    id: Mapped[int] = mapped_column(primary_key=True)
    quote_ref: Mapped[str] = mapped_column(String(40), unique=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("pi_batches.id", ondelete="CASCADE"), index=True)
    vendor: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | issued | superseded
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    rule_version_id: Mapped[int | None] = mapped_column(ForeignKey("pi_rule_versions.id"))
    lines_count: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    total: Mapped[Decimal] = mapped_column(PIMoney)
    excluded_lines: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PIQuotationLine(Base):
    __tablename__ = "pi_quotation_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("pi_quotations.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("pi_assets.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("pi_products.id"))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(PIMoney)
    line_total: Mapped[Decimal] = mapped_column(PIMoney)
    price_basis: Mapped[str] = mapped_column(String(20))  # calculated | override | provisional
    __table_args__ = (UniqueConstraint("quotation_id", "asset_id", name="uq_pi_quote_line"),)


class PIOutcome(Base):
    """Actual purchase or resale outcome, used for accuracy reporting."""

    __tablename__ = "pi_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("pi_products.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("pi_batches.id", ondelete="SET NULL"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("pi_assets.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10))  # purchase | resale
    unit_price: Mapped[Decimal] = mapped_column(PIMoney)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    outcome_date: Mapped[date] = mapped_column(Date)
    vendor: Mapped[str | None] = mapped_column(String(200))
    condition: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_pi_obs_product_status", PIObservation.product_id, PIObservation.status)
Index("ix_pi_est_product_current", PIEstimate.product_id, PIEstimate.is_current)

class PIWorkerHeartbeat(Base):
    """Worker liveness independent of whether a job is present."""
    __tablename__ = "pi_worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
