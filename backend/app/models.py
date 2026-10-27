"""Database models.

Design rules encoded here:
* Four separate record types: inventory being valued, advertised market listings,
  supplier quotations, and completed transactions (purchases and sales).
* Nullable columns mean "missing". A stored 0 is an explicit zero.
* Every imported record keeps its original cell values (``raw_values``) and the
  list of user corrections applied before commit.
* Synthetic demo data is flagged with ``is_synthetic`` and never mixed into
  valuations of real inventory.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(14, 2, asdecimal=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))  # admin | procurement | sales
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict | None] = mapped_column(JSONType)


class PricingConfigVersion(Base):
    __tablename__ = "pricing_config_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    config: Mapped[dict] = mapped_column(JSONType)
    config_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ColumnMapping(Base):
    __tablename__ = "column_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    record_type: Mapped[str] = mapped_column(String(32), index=True)
    mapping: Mapped[dict] = mapped_column(JSONType)  # canonical field -> source column header
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UploadBatch(Base):
    __tablename__ = "upload_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32))  # inventory | listing | quote | transaction
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    file_kind: Mapped[str] = mapped_column(String(8))  # csv | xlsx
    sheets: Mapped[list | None] = mapped_column(JSONType)  # [{name, rows, columns}]
    selected_sheets: Mapped[list | None] = mapped_column(JSONType)
    mapping: Mapped[dict | None] = mapped_column(JSONType)
    import_defaults: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(24), default="uploaded")  # uploaded|staged|committed
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict | None] = mapped_column(JSONType)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rows: Mapped[list[StagingRow]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class StagingRow(Base):
    __tablename__ = "staging_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("upload_batches.id", ondelete="CASCADE"), index=True)
    sheet: Mapped[str | None] = mapped_column(String(120))
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based row number in the source sheet
    raw: Mapped[dict] = mapped_column(JSONType)  # original cell values, keyed by source header
    mapped_raw: Mapped[dict] = mapped_column(JSONType)  # canonical field -> original cell value
    normalized: Mapped[dict] = mapped_column(JSONType)  # canonical field -> parsed value (after corrections)
    corrections: Mapped[dict] = mapped_column(JSONType, default=dict)  # canonical field -> user-entered value
    suggestions: Mapped[dict | None] = mapped_column(JSONType)  # extraction suggestions awaiting review
    errors: Mapped[list] = mapped_column(JSONType, default=list)
    warnings: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(80))
    keep_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    committed_record_id: Mapped[int | None] = mapped_column(Integer)

    batch: Mapped[UploadBatch] = relationship(back_populates="rows")


class FieldCorrection(Base):
    __tablename__ = "field_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32))
    staging_row_id: Mapped[int | None] = mapped_column(ForeignKey("staging_rows.id", ondelete="SET NULL"))
    record_id: Mapped[int | None] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(60))
    original_value: Mapped[str | None] = mapped_column(Text)
    previous_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="user")  # user | rule_extraction | ai_extraction
    reason: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpecColumns:
    """Laptop specification columns shared by every record type."""

    brand: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(160))
    model_key: Mapped[str] = mapped_column(String(160), index=True)
    cpu: Mapped[str | None] = mapped_column(String(160))
    cpu_key: Mapped[str | None] = mapped_column(String(120), index=True)
    ram_gb: Mapped[int | None] = mapped_column(Integer)
    storage_type: Mapped[str | None] = mapped_column(String(20))
    storage_gb: Mapped[int | None] = mapped_column(Integer)
    display_size_in: Mapped[float | None] = mapped_column(Float)
    display_resolution: Mapped[str | None] = mapped_column(String(20))
    gpu: Mapped[str | None] = mapped_column(String(120))
    condition_grade: Mapped[str | None] = mapped_column(String(10))
    battery_health_pct: Mapped[float | None] = mapped_column(Float)
    faults: Mapped[list | None] = mapped_column(JSONType)
    fault_category: Mapped[str | None] = mapped_column(String(40))
    charger_included: Mapped[bool | None] = mapped_column(Boolean)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[int | None] = mapped_column(Integer)
    region: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)

    raw_values: Mapped[dict | None] = mapped_column(JSONType)
    corrections: Mapped[dict | None] = mapped_column(JSONType)
    staging_row_id: Mapped[int | None] = mapped_column(Integer)
    upload_batch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer)


class EvidenceColumns:
    """Provenance and price columns shared by every evidence record."""

    source_type: Mapped[str] = mapped_column(String(20))  # upload | manual | connector | demo
    source_url: Mapped[str | None] = mapped_column(Text)  # only ever a URL supplied by the user or a feed
    source_document: Mapped[str | None] = mapped_column(String(300))
    source_record_id: Mapped[str | None] = mapped_column(String(160), index=True)
    seller: Mapped[str | None] = mapped_column(String(200))
    platform: Mapped[str | None] = mapped_column(String(120))
    currency: Mapped[str | None] = mapped_column(String(3))
    price: Mapped[float | None] = mapped_column(Money)
    tax_basis: Mapped[str] = mapped_column(String(12), default="unknown")  # inclusive | exclusive | unknown
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability: Mapped[str | None] = mapped_column(String(20))
    channel: Mapped[str | None] = mapped_column(String(20))  # retail | wholesale | as_is


class Lot(Base):
    __tablename__ = "lots"
    id: Mapped[int] = mapped_column(primary_key=True)
    lot_ref: Mapped[str] = mapped_column(String(120), index=True)
    supplier: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list[InventoryItem]] = relationship(back_populates="lot")


class InventoryItem(SpecColumns, Base):
    __tablename__ = "inventory_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_ref: Mapped[str | None] = mapped_column(String(120), index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), index=True)
    supplier: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str | None] = mapped_column(String(3))
    asking_price: Mapped[float | None] = mapped_column(Money)  # per unit
    asking_tax_basis: Mapped[str] = mapped_column(String(12), default="unknown")
    refurbishment_cost: Mapped[float | None] = mapped_column(Money)  # per unit
    intended_channel: Mapped[str | None] = mapped_column(String(20))
    target_margin_pct: Mapped[float | None] = mapped_column(Float)
    expected_yield_pct: Mapped[float | None] = mapped_column(Float)
    salvage_value: Mapped[float | None] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20), default="active")

    lot: Mapped[Lot | None] = relationship(back_populates="items")


class MarketListing(SpecColumns, EvidenceColumns, Base):
    """An advertised asking price. Never treated as a completed sale."""

    __tablename__ = "market_listings"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_date: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str | None] = mapped_column(Text)
    connector_id: Mapped[int | None] = mapped_column(ForeignKey("connectors.id"))
    __table_args__ = (Index("ix_listing_identity", "model_key", "cpu_key"),)


class SupplierQuote(SpecColumns, EvidenceColumns, Base):
    __tablename__ = "supplier_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    quote_date: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    quantity_available: Mapped[int | None] = mapped_column(Integer)
    moq: Mapped[int | None] = mapped_column(Integer)


class Transaction(SpecColumns, EvidenceColumns, Base):
    """A completed purchase or sale. ``price`` is the realised unit price."""

    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # purchase | sale
    transaction_date: Mapped[date | None] = mapped_column(Date, index=True)
    counterparty: Mapped[str | None] = mapped_column(String(200))
    fees_paid: Mapped[float | None] = mapped_column(Money)
    reference: Mapped[str | None] = mapped_column(String(160))
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"))
    valuation_run_id: Mapped[int | None] = mapped_column(ForeignKey("valuation_runs.id"))


class ValuationRun(Base):
    """An immutable valuation snapshot: full inputs, configuration, and outputs."""

    __tablename__ = "valuation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    rating: Mapped[str | None] = mapped_column(String(20))
    config_version_id: Mapped[int] = mapped_column(ForeignKey("pricing_config_versions.id"))
    engine_version: Mapped[str] = mapped_column(String(20))
    input_snapshot: Mapped[dict] = mapped_column(JSONType)
    result: Mapped[dict] = mapped_column(JSONType)
    input_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    # Headline numbers, denormalised for lists and exports (all per unit, INR).
    sale_p50_gross: Mapped[float | None] = mapped_column(Money)
    target_buy_unit: Mapped[float | None] = mapped_column(Money)
    max_safe_buy_unit: Mapped[float | None] = mapped_column(Money)
    ai_explanation: Mapped[dict | None] = mapped_column(JSONType)


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    adapter: Mapped[str] = mapped_column(String(40))  # manual | file_import | http_json_feed
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(30), default="not_configured")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_records: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    params: Mapped[dict] = mapped_column(JSONType)
    report: Mapped[dict] = mapped_column(JSONType)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


# Pricing Intelligence (procurement valuation) tables live in their own module; importing it here
# registers them on the shared metadata so Alembic and the test schema see them.
from .procurement import models as _pricing_intelligence_models  # noqa: E402,F401

assert _pricing_intelligence_models
