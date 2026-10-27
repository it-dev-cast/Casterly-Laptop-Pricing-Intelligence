"""Row-level parsing and validation, shared by bulk import and manual entry."""
from __future__ import annotations

from typing import Any

from .. import specs
from ..pricing.config import PricingConfig
from .fields import field_map

def parse_value(kind: str, raw: Any, key: str, cfg: PricingConfig) -> specs.ParseResult:
    if kind == "text":
        return specs.ParseResult(specs.clean_text(raw))
    if kind == "cpu":
        v = specs.clean_text(raw)
        if v is not None and specs.cpu_key(v) is None:
            return specs.ParseResult(None, error=f"cpu: '{raw}' has no recognisable processor model")
        return specs.ParseResult(v)
    if kind == "ram":
        return specs.parse_capacity_gb(raw, field=key)
    if kind == "storage":
        return specs.parse_capacity_gb(raw, field=key)
    if kind == "storage_type":
        return specs.parse_storage_type(raw)
    if kind == "display_size":
        return specs.parse_display_size(raw)
    if kind == "resolution":
        return specs.parse_resolution(raw)
    if kind == "grade":
        return specs.parse_grade(raw, cfg.grade_scale, cfg.grade_synonyms)
    if kind == "percent":
        return specs.parse_percent(raw, field=key)
    if kind == "pct":
        return specs.parse_percent(raw, field=key, lo=0, hi=100)
    if kind == "faults":
        return specs.parse_faults(raw)
    if kind == "fault_category":
        v = specs.clean_text(raw)
        if v is None:
            return specs.ParseResult(None)
        k = v.lower().replace(" ", "_")
        valid = {f.key for f in cfg.fault_categories}
        if k not in valid:
            return specs.ParseResult(None, error=f"fault_category: '{raw}' is not one of {sorted(valid)}")
        return specs.ParseResult(k)
    if kind == "bool":
        return specs.parse_bool(raw, field=key)
    if kind == "warranty":
        return specs.parse_warranty_months(raw)
    if kind == "quantity":
        return specs.parse_int(raw, field=key, minimum=1)
    if kind == "money":
        return specs.parse_money(raw, field=key, allow_zero=True)
    if kind == "price":
        return specs.parse_money(raw, field=key, allow_zero=False)
    if kind == "tax_basis":
        return specs.parse_tax_basis(raw)
    if kind == "currency":
        return specs.parse_currency(raw)
    if kind == "channel":
        return specs.parse_enum(raw, field=key, allowed=specs.CHANNELS)
    if kind == "availability":
        return specs.parse_enum(raw, field=key, allowed=specs.AVAILABILITY)
    if kind == "txn_kind":
        return specs.parse_enum(raw, field=key, allowed=specs.TXN_KINDS)
    if kind == "date":
        return specs.parse_date(raw, field=key, day_first=cfg.import_day_first_dates)
    if kind == "datetime":
        return specs.parse_datetime(raw, field=key, day_first=cfg.import_day_first_dates)
    if kind == "url":
        return specs.parse_url(raw)
    raise ValueError(f"unknown field kind {kind}")


def normalize_record(record_type: str, values: dict[str, Any], cfg: PricingConfig,
                     defaults: dict[str, Any] | None = None) -> tuple[dict, list[dict], list[dict]]:
    """``values``: canonical field -> raw value. Returns (normalized, errors, warnings).

    Errors/warnings are ``{"field": key | None, "message": str}``.
    """
    fmap = field_map(record_type)
    out: dict[str, Any] = {}
    errors: list[dict] = []
    warnings: list[dict] = []
    defaults = defaults or {}
    for key, fdef in fmap.items():
        raw = values.get(key)
        if specs.is_missing(raw) and key in defaults and not specs.is_missing(defaults[key]):
            raw = defaults[key]
            warnings.append({"field": key, "message": f"{fdef.label} not in the row; batch default '{raw}' applied"})
        r = parse_value(fdef.kind, raw, key, cfg)
        if r.error:
            errors.append({"field": key, "message": r.error})
        if r.warning:
            warnings.append({"field": key, "message": r.warning})
        out[key] = r.value
        if r.value is None and not r.error and record_type in fdef.required:
            errors.append({"field": key, "message": f"{fdef.label} is required"})
    # Storage capacity cells often carry the type ("512GB SSD").
    if out.get("storage_type") is None and values.get("storage_gb") is not None:
        t = specs.storage_type_from_text(values.get("storage_gb"))
        if t:
            out["storage_type"] = t
            warnings.append({"field": "storage_type", "message": f"Storage type '{t}' read from the capacity cell"})
    for key, fdef in fmap.items():
        if fdef.matching and out.get(key) is None and not any(e["field"] == key for e in errors):
            warnings.append({"field": key, "message": f"{fdef.label} missing: this record cannot be an exact "
                                                      "configuration match"})
    if record_type == "transaction" and out.get("kind") == "sale" and not out.get("channel"):
        errors.append({"field": "channel", "message": "Channel is required for sales (retail / wholesale / as_is)"})
    if "currency" in fmap and out.get("currency") is None and cfg.import_default_currency \
            and not specs.is_missing(values.get("price") or values.get("asking_price")):
        out["currency"] = cfg.import_default_currency
        warnings.append({"field": "currency", "message": f"Currency not given; import default "
                                                         f"{cfg.import_default_currency} assumed"})
    if record_type == "quote" and out.get("valid_until") and out.get("quote_date") \
            and out["valid_until"] < out["quote_date"]:
        errors.append({"field": "valid_until", "message": "Valid-until date is before the quote date"})
    return out, errors, warnings


def jsonable(d: dict) -> dict:
    """Make parsed values JSON-storable (dates to ISO strings)."""
    out = {}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
