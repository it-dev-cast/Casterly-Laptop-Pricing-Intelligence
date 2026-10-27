"""Canonical import fields for each record type, with header synonyms for auto-mapping."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

RECORD_TYPES = {
    "inventory": "Inventory being valued",
    "listing": "Advertised market listings",
    "quote": "Supplier quotations",
    "transaction": "Completed purchases and sales",
}


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: str
    synonyms: tuple[str, ...] = ()
    help: str = ""
    required: frozenset[str] = field(default_factory=frozenset)  # record types where it is mandatory
    matching: bool = False  # needed for exact configuration matching (warn when missing)


def F(key, label, kind, synonyms=(), help="", required=(), matching=False):
    return FieldDef(key, label, kind, tuple(synonyms), help, frozenset(required), matching)


ALL = set(RECORD_TYPES)

SPEC_FIELDS = [
    F("brand", "Brand", "text", ["brand", "make", "manufacturer", "oem", "company"], required=ALL),
    F("model", "Model", "text", ["model", "model name", "model no", "model number", "series", "product"], required=ALL),
    F("cpu", "Exact CPU", "cpu", ["cpu", "processor", "proc", "cpu model", "chip", "processor model"],
      "Exact processor model, e.g. i5-8350U", matching=True),
    F("ram_gb", "RAM (GB)", "ram", ["ram", "memory", "ram gb", "ram (gb)", "ram size"], matching=True),
    F("storage_type", "Storage type", "storage_type", ["storage type", "disk type", "drive type", "ssd/hdd"]),
    F("storage_gb", "Storage capacity (GB)", "storage", ["storage", "storage gb", "storage (gb)", "ssd", "hdd",
                                                          "disk", "capacity", "rom", "hard disk", "storage capacity"],
      "1 TB is stored as 1024 GB", matching=True),
    F("display_size_in", "Display size (in)", "display_size", ["display", "screen", "screen size", "display size", "inch", "size"]),
    F("display_resolution", "Display resolution", "resolution", ["resolution", "display resolution", "screen resolution"]),
    F("gpu", "GPU", "text", ["gpu", "graphics", "graphics card", "vga"]),
    F("condition_grade", "Condition grade", "grade", ["grade", "condition", "condition grade", "cosmetic grade"],
      matching=True),
    F("battery_health_pct", "Battery health (%)", "percent", ["battery", "battery health", "battery %", "battery health %", "bh"]),
    F("faults", "Faults", "faults", ["faults", "fault", "issues", "defects", "problems", "remarks"],
      "Separate several faults with ';'. 'None' = explicitly no faults; blank = unknown"),
    F("charger_included", "Charger included", "bool", ["charger", "adapter", "charger included", "with charger"]),
    F("warranty_months", "Warranty (months)", "warranty", ["warranty", "warranty months", "warranty period"]),
    F("region", "Location / region", "text", ["location", "region", "city", "state", "warehouse"]),
    F("description", "Description", "text", ["description", "desc", "details", "notes", "specs", "specification"]),
]

TYPE_FIELDS = {
    "inventory": [
        F("item_ref", "Item / SKU reference", "text", ["sku", "item id", "item ref", "asset id", "serial", "stock id", "id"]),
        F("lot_ref", "Lot reference", "text", ["lot", "lot id", "lot ref", "lot no", "batch"]),
        F("supplier", "Supplier", "text", ["supplier", "vendor", "seller"]),
        F("quantity", "Quantity", "quantity", ["qty", "quantity", "units", "count", "nos"], required={"inventory"}),
        F("asking_price", "Supplier asking price (per unit)", "money", ["asking price", "ask", "price", "unit price",
                                                                         "supplier price", "offer price", "cost"]),
        F("asking_tax_basis", "Asking price tax basis", "tax_basis", ["tax basis", "gst", "price basis", "tax"]),
        F("currency", "Currency", "currency", ["currency", "cur"]),
        F("refurbishment_cost", "Refurbishment cost (per unit)", "money", ["refurb", "refurbishment", "refurb cost",
                                                                           "repair cost", "refurbishment cost"]),
        F("intended_channel", "Intended channel", "channel", ["channel", "sales channel", "intended channel"]),
        F("target_margin_pct", "Target contribution margin (%)", "pct", ["target margin", "margin", "margin %"]),
        F("fault_category", "Fault category", "fault_category", ["fault category", "fault type"]),
        F("expected_yield_pct", "Expected saleable yield (%)", "pct", ["yield", "expected yield", "saleable yield"]),
        F("salvage_value", "Salvage value per unsold unit", "money", ["salvage", "salvage value", "scrap value"]),
    ],
    "listing": [
        F("price", "Asking price (per unit)", "price", ["price", "asking price", "listed price", "selling price",
                                                         "offer price", "mrp", "amount"], required={"listing"}),
        F("currency", "Currency", "currency", ["currency", "cur"]),
        F("tax_basis", "Tax basis", "tax_basis", ["tax basis", "gst", "price basis", "tax"]),
        F("channel", "Channel", "channel", ["channel", "market", "segment"], "retail / wholesale / as_is",
          required={"listing"}),
        F("listing_date", "Listing date", "date", ["listing date", "date", "posted", "posted on", "listed on"],
          required={"listing"}),
        F("observed_at", "Observed at", "datetime", ["observed at", "observed", "scraped at", "captured at", "checked on"]),
        F("seller", "Seller", "text", ["seller", "vendor", "dealer", "shop", "store"]),
        F("platform", "Platform / site", "text", ["platform", "site", "marketplace", "website", "source"]),
        F("source_url", "Source URL", "url", ["url", "link", "source url", "listing url"]),
        F("source_record_id", "Source listing ID", "text", ["listing id", "ad id", "source id", "item id", "id"]),
        F("availability", "Availability", "availability", ["availability", "stock", "status", "in stock"]),
        F("title", "Listing title", "text", ["title", "listing title", "headline", "name"]),
        F("quantity", "Quantity offered", "quantity", ["qty", "quantity", "units"]),
    ],
    "quote": [
        F("seller", "Supplier", "text", ["supplier", "vendor", "seller", "company name"], required={"quote"}),
        F("price", "Quoted unit price", "price", ["price", "unit price", "quoted price", "rate", "amount"],
          required={"quote"}),
        F("currency", "Currency", "currency", ["currency", "cur"]),
        F("tax_basis", "Tax basis", "tax_basis", ["tax basis", "gst", "price basis", "tax"]),
        F("quote_date", "Quote date", "date", ["quote date", "date", "quotation date"], required={"quote"}),
        F("valid_until", "Valid until", "date", ["valid until", "validity", "valid till", "expiry"]),
        F("source_record_id", "Quote reference", "text", ["quote ref", "quote no", "quotation no", "reference", "ref"]),
        F("quantity_available", "Quantity available", "quantity", ["qty", "quantity", "available qty", "units"]),
        F("moq", "Minimum order quantity", "quantity", ["moq", "min order", "minimum order"]),
        F("channel", "Channel", "channel", ["channel"]),
        F("source_url", "Source URL", "url", ["url", "link"]),
    ],
    "transaction": [
        F("kind", "Transaction type", "txn_kind", ["type", "transaction type", "kind", "purchase/sale", "direction"],
          "purchase or sale", required={"transaction"}),
        F("transaction_date", "Transaction date", "date", ["date", "transaction date", "invoice date", "sale date",
                                                           "purchase date"], required={"transaction"}),
        F("price", "Realised unit price", "price", ["price", "unit price", "sale price", "purchase price", "amount",
                                                     "rate"], required={"transaction"}),
        F("quantity", "Quantity", "quantity", ["qty", "quantity", "units"]),
        F("channel", "Channel", "channel", ["channel", "sales channel"], "Required for sales"),
        F("counterparty", "Counterparty", "text", ["customer", "buyer", "supplier", "counterparty", "party", "vendor"]),
        F("currency", "Currency", "currency", ["currency", "cur"]),
        F("tax_basis", "Tax basis", "tax_basis", ["tax basis", "gst", "price basis", "tax"]),
        F("fees_paid", "Fees paid (per unit)", "money", ["fees", "fee", "commission", "fees paid"]),
        F("source_record_id", "Invoice / reference", "text", ["invoice", "invoice no", "reference", "ref", "order id"]),
        F("item_ref", "Inventory item reference", "text", ["sku", "item ref", "item id", "asset id"]),
        F("platform", "Platform", "text", ["platform", "marketplace", "site"]),
    ],
}


def fields_for(record_type: str) -> list[FieldDef]:
    extra = TYPE_FIELDS[record_type]
    keys = {f.key for f in extra}
    return [f for f in SPEC_FIELDS if f.key not in keys] + extra


def field_map(record_type: str) -> dict[str, FieldDef]:
    return {f.key: f for f in fields_for(record_type)}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", str(h).lower()).strip()


def suggest_mapping(record_type: str, headers: list[str]) -> dict[str, str]:
    """Exact synonym match first, then label match. Each header maps to at most one field."""
    fields = fields_for(record_type)
    used: set[str] = set()
    out: dict[str, str] = {}
    norm_headers = {h: _norm(h) for h in headers}
    for pass_ in ("exact", "label"):
        for f in fields:
            if f.key in out:
                continue
            for h, nh in norm_headers.items():
                if h in used:
                    continue
                if (pass_ == "exact" and (nh in {_norm(s) for s in f.synonyms} or nh == _norm(f.key))) or \
                        (pass_ == "label" and nh == _norm(f.label)):
                    out[f.key] = h
                    used.add(h)
                    break
    return out
