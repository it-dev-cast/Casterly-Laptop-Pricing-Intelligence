"""Building database records from validated values, and converting them for the engine."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import specs
from ..models import InventoryItem, Lot, MarketListing, SupplierQuote, Transaction, User
from ..pricing.types import Evidence, Subject

MODEL_FOR = {"inventory": InventoryItem, "listing": MarketListing, "quote": SupplierQuote, "transaction": Transaction}

SPEC_KEYS = ("brand", "model", "cpu", "ram_gb", "storage_type", "storage_gb", "display_size_in", "display_resolution",
             "gpu", "condition_grade", "battery_health_pct", "faults", "charger_included", "warranty_months",
             "quantity", "region", "description")
TYPE_KEYS = {
    "inventory": ("item_ref", "supplier", "asking_price", "asking_tax_basis", "currency", "refurbishment_cost",
                  "intended_channel", "target_margin_pct", "fault_category", "expected_yield_pct", "salvage_value"),
    "listing": ("price", "currency", "tax_basis", "channel", "listing_date", "observed_at", "seller", "platform",
                "source_url", "source_record_id", "availability", "title"),
    "quote": ("seller", "price", "currency", "tax_basis", "quote_date", "valid_until", "source_record_id",
              "quantity_available", "moq", "channel", "source_url"),
    "transaction": ("kind", "transaction_date", "price", "channel", "counterparty", "currency", "tax_basis",
                    "fees_paid", "source_record_id", "platform"),
}


def _as_date(v):
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _as_dt(v):
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


def build_record(db: Session, record_type: str, values: dict[str, Any], *, source_type: str,
                 source_document: str | None, user: User | None, is_synthetic: bool = False,
                 raw_values: dict | None = None, corrections: dict | None = None,
                 batch_id: int | None = None, staging_row_id: int | None = None):
    Model = MODEL_FOR[record_type]
    rec = Model()
    for k in SPEC_KEYS + TYPE_KEYS[record_type]:
        if k in values:
            v = values[k]
            if k in ("listing_date", "quote_date", "valid_until", "transaction_date"):
                v = _as_date(v)
            elif k == "observed_at":
                v = _as_dt(v)
            elif k == "tax_basis" or k == "asking_tax_basis":
                v = v or "unknown"
            setattr(rec, k, v)
    rec.model_key = specs.model_key(values.get("brand"), values.get("model")) or ""
    rec.cpu_key = specs.cpu_key(values.get("cpu"))
    rec.is_synthetic = is_synthetic
    rec.raw_values = raw_values
    rec.corrections = corrections or None
    rec.upload_batch_id = batch_id
    rec.staging_row_id = staging_row_id
    rec.created_by = user.id if user else None
    if record_type != "inventory":
        rec.source_type = source_type
        rec.source_document = source_document
    if record_type == "transaction":
        rec.reference = values.get("source_record_id")
        if values.get("item_ref"):
            item = db.scalar(select(InventoryItem).where(InventoryItem.item_ref == values["item_ref"],
                                                         InventoryItem.is_synthetic.is_(is_synthetic)))
            rec.inventory_item_id = item.id if item else None
    if record_type == "inventory" and values.get("lot_ref"):
        lot = db.scalar(select(Lot).where(Lot.lot_ref == values["lot_ref"], Lot.is_synthetic.is_(is_synthetic)))
        if lot is None:
            lot = Lot(lot_ref=values["lot_ref"], supplier=values.get("supplier"), is_synthetic=is_synthetic)
            db.add(lot)
            db.flush()
        rec.lot_id = lot.id
    db.add(rec)
    db.flush()
    return rec


def record_to_dict(rec) -> dict:
    out = {}
    for col in rec.__table__.columns:
        v = getattr(rec, col.key)
        out[col.key] = v.isoformat() if hasattr(v, "isoformat") else v
    if isinstance(rec, InventoryItem):
        out["lot_ref"] = rec.lot.lot_ref if rec.lot else None
    return out


def label(rec) -> str:
    parts = [rec.brand, rec.model]
    if rec.cpu:
        parts.append(rec.cpu)
    cfg = []
    if rec.ram_gb is not None:
        cfg.append(f"{rec.ram_gb}GB")
    if rec.storage_gb is not None:
        cfg.append(f"{rec.storage_gb}GB {rec.storage_type or ''}".strip())
    if rec.condition_grade:
        cfg.append(f"Grade {rec.condition_grade}")
    return " ".join(p for p in parts if p) + (f" · {' / '.join(cfg)}" if cfg else "")


def to_subject(item: InventoryItem) -> Subject:
    return Subject(
        id=item.id, label=label(item), brand_key=specs.brand_key(item.brand), model_key=item.model_key,
        cpu_key=item.cpu_key, ram_gb=item.ram_gb, storage_type=item.storage_type, storage_gb=item.storage_gb,
        display_size_in=item.display_size_in, display_resolution=item.display_resolution,
        gpu_key=specs.gpu_key(item.gpu), condition_grade=item.condition_grade,
        battery_health_pct=item.battery_health_pct, charger_included=item.charger_included,
        warranty_months=item.warranty_months, faults=tuple(item.faults) if item.faults is not None else None,
        fault_category=item.fault_category, quantity=item.quantity, intended_channel=item.intended_channel,
        target_margin_pct=item.target_margin_pct, refurbishment_cost=item.refurbishment_cost,
        expected_yield_pct=item.expected_yield_pct, salvage_value=item.salvage_value,
        asking_price=item.asking_price, asking_tax_basis=item.asking_tax_basis or "unknown",
        currency=item.currency, is_synthetic=item.is_synthetic,
    )


def _source_key(kind: str, rec) -> str:
    if kind == "listing":
        if rec.seller:
            return f"seller:{rec.seller.strip().lower()}"
        # Unknown sellers on one platform cannot be shown to be independent: grouped as one source.
        return f"unknown-seller@{(rec.platform or 'unknown').strip().lower()}"
    if kind == "quote":
        return f"supplier:{(rec.seller or f'quote-{rec.id}').strip().lower()}"
    party = rec.counterparty or rec.seller
    if party:
        return f"party:{party.strip().lower()}"
    return f"{kind}:{rec.reference or rec.id}"


def to_evidence(rec) -> Evidence:
    if isinstance(rec, MarketListing):
        kind, event, valid_until = "listing", rec.listing_date, None
    elif isinstance(rec, SupplierQuote):
        kind, event, valid_until = "quote", rec.quote_date, rec.valid_until
    else:
        kind, event, valid_until = rec.kind, rec.transaction_date, None
    prefix = {"listing": "listing", "quote": "quote", "sale": "sale", "purchase": "purchase"}[kind]
    return Evidence(
        id=f"{prefix}:{rec.id}", kind=kind, channel=rec.channel, brand_key=specs.brand_key(rec.brand),
        model_key=rec.model_key, cpu_key=rec.cpu_key, ram_gb=rec.ram_gb, storage_type=rec.storage_type,
        storage_gb=rec.storage_gb, display_size_in=rec.display_size_in, display_resolution=rec.display_resolution,
        gpu_key=specs.gpu_key(rec.gpu), condition_grade=rec.condition_grade,
        battery_health_pct=rec.battery_health_pct, charger_included=rec.charger_included,
        warranty_months=rec.warranty_months, price=rec.price, currency=rec.currency,
        tax_basis=rec.tax_basis or "unknown", event_date=event, observed_at=rec.observed_at,
        availability=rec.availability, valid_until=valid_until, seller=rec.seller or getattr(rec, "counterparty", None),
        source_key=_source_key(kind, rec), platform=rec.platform, source_url=rec.source_url,
        source_document=rec.source_document, source_record_id=rec.source_record_id,
        title_key=specs.key_text(getattr(rec, "title", None)), is_synthetic=rec.is_synthetic,
    )
