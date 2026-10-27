"""Builders for engine inputs used across tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.pricing.config import FaultCategory, PricingConfig
from app.pricing.types import Evidence, Subject

AS_OF = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

BASE_SPEC = dict(brand_key="dell", model_key="latitude 7490", cpu_key="i5-8350u", ram_gb=16, storage_type="SSD",
                 storage_gb=256, display_size_in=14.0, display_resolution="1920x1080", gpu_key="integrated",
                 condition_grade="A", battery_health_pct=85.0, charger_included=True, warranty_months=6)


def subject(**over) -> Subject:
    d = dict(id=1, label="Dell Latitude 7490", faults=(), fault_category=None, quantity=10, intended_channel="retail",
             target_margin_pct=15.0, refurbishment_cost=1000.0, expected_yield_pct=100.0, salvage_value=None,
             asking_price=None, asking_tax_basis="unknown", currency="INR", is_synthetic=False, **BASE_SPEC)
    d.update(over)
    return Subject(**d)


_counter = [0]


def ev(kind="sale", price=30000.0, days_ago=10, seller=None, channel="retail", tax_basis="inclusive", **over) -> Evidence:
    _counter[0] += 1
    n = _counter[0]
    d = dict(id=f"{kind}:{n}", kind=kind, channel=channel, price=price, currency="INR", tax_basis=tax_basis,
             event_date=(AS_OF - timedelta(days=days_ago)).date(), observed_at=None, availability=None,
             valid_until=None, seller=seller or f"seller-{n}", source_key=f"src-{seller or n}", platform=None,
             source_url=None, source_document="test", source_record_id=None, title_key=None, is_synthetic=False,
             **BASE_SPEC)
    d.update(over)
    if "seller" in over or seller:
        d["source_key"] = f"src-{d['seller']}"
    return Evidence(**d)


def config(**over) -> PricingConfig:
    cfg = PricingConfig()
    cfg.matching.outlier_mad_k = None
    cfg.fault_categories = [
        FaultCategory(key="none", label="No faults", expected_yield_pct=100, repair_cost_per_unit=0),
        FaultCategory(key="display", label="Display", expected_yield_pct=70, repair_cost_per_unit=4000,
                      salvage_value_per_unit=3000, match_keywords=["display", "screen"]),
        FaultCategory(key="board_power", label="No power", expected_yield_pct=None, repair_cost_per_unit=None,
                      match_keywords=["no power"]),
    ]
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def sales(prices, **kw):
    return [ev("sale", p, days_ago=5 + i, **kw) for i, p in enumerate(prices)]


def today_minus(days: int) -> date:
    return (AS_OF - timedelta(days=days)).date()
