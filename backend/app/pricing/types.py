"""Engine input records. Plain, serialisable, and independent of the database."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from typing import Any

SPEC_FIELDS = (
    "brand_key", "model_key", "cpu_key", "ram_gb", "storage_type", "storage_gb", "display_size_in",
    "display_resolution", "gpu_key", "condition_grade", "battery_health_pct", "charger_included",
    "warranty_months",
)


def _to_date(v: Any) -> date | None:
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v)[:10])


def _to_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


@dataclass(frozen=True)
class Subject:
    id: int
    label: str
    brand_key: str | None
    model_key: str | None
    cpu_key: str | None
    ram_gb: int | None
    storage_type: str | None
    storage_gb: int | None
    display_size_in: float | None
    display_resolution: str | None
    gpu_key: str | None
    condition_grade: str | None
    battery_health_pct: float | None
    charger_included: bool | None
    warranty_months: int | None
    faults: tuple[str, ...] | None
    fault_category: str | None
    quantity: int | None
    intended_channel: str | None
    target_margin_pct: float | None
    refurbishment_cost: float | None
    expected_yield_pct: float | None
    salvage_value: float | None
    asking_price: float | None
    asking_tax_basis: str
    currency: str | None
    is_synthetic: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["faults"] = list(self.faults) if self.faults is not None else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Subject:
        d = dict(d)
        if d.get("faults") is not None:
            d["faults"] = tuple(d["faults"])
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass(frozen=True)
class Evidence:
    id: str  # "<kind>:<db id>", e.g. "listing:41"
    kind: str  # sale | listing | quote | purchase
    channel: str | None
    brand_key: str | None
    model_key: str | None
    cpu_key: str | None
    ram_gb: int | None
    storage_type: str | None
    storage_gb: int | None
    display_size_in: float | None
    display_resolution: str | None
    gpu_key: str | None
    condition_grade: str | None
    battery_health_pct: float | None
    charger_included: bool | None
    warranty_months: int | None
    price: float | None
    currency: str | None
    tax_basis: str
    event_date: date | None  # listing date / transaction date / quote date
    observed_at: datetime | None
    availability: str | None
    valid_until: date | None
    seller: str | None
    source_key: str
    platform: str | None
    source_url: str | None
    source_document: str | None
    source_record_id: str | None
    title_key: str | None
    is_synthetic: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("event_date", "valid_until"):
            d[k] = d[k].isoformat() if d[k] else None
        d["observed_at"] = self.observed_at.isoformat() if self.observed_at else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Evidence:
        d = dict(d)
        d["event_date"] = _to_date(d.get("event_date"))
        d["valid_until"] = _to_date(d.get("valid_until"))
        d["observed_at"] = _to_dt(d.get("observed_at"))
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})
