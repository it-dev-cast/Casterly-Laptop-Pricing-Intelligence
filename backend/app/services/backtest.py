"""Chronological hold-out validation of selling estimates against completed sales.

For each held-out sale (the most recent fraction, by date) the engine is run as of
the day before the sale, using only evidence dated and observed before then. Its
weighted median is compared with the realised price, alongside a simple baseline:
the plain median of earlier completed sales of the identical configuration in the
same channel (no weighting, deduplication or staleness rules).

Reported: coverage (how often each method produced an estimate), MAE, MAPE and
median APE on the cases where both produced one, and empirical coverage of the
engine's 25-75% and 10-90% ranges (nominally 50% and 80%).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MarketListing, SupplierQuote, Transaction
from ..pricing.config import PricingConfig
from ..pricing.engine import value_item
from ..pricing.stats import simple_median
from ..pricing.types import Subject
from .records import to_evidence


def _gross(price: float, tax_basis: str, cfg: PricingConfig) -> float | None:
    g = cfg.tax.gst_rate_pct / 100
    if tax_basis == "inclusive":
        return price
    if tax_basis == "exclusive":
        return price * (1 + g)
    pol = cfg.tax.unknown_tax_basis.get("sale", "exclude")
    if pol == "exclude":
        return None
    return price if pol == "assume_inclusive" else price * (1 + g)


def _subject_from_sale(e) -> Subject:
    return Subject(id=0, label="backtest", brand_key=e.brand_key, model_key=e.model_key, cpu_key=e.cpu_key,
                   ram_gb=e.ram_gb, storage_type=e.storage_type, storage_gb=e.storage_gb,
                   display_size_in=e.display_size_in, display_resolution=e.display_resolution, gpu_key=e.gpu_key,
                   condition_grade=e.condition_grade, battery_health_pct=e.battery_health_pct,
                   charger_included=e.charger_included, warranty_months=e.warranty_months, faults=None,
                   fault_category=None, quantity=1, intended_channel=e.channel, target_margin_pct=None,
                   refurbishment_cost=None, expected_yield_pct=None, salvage_value=None, asking_price=None,
                   asking_tax_basis="unknown", currency="INR", is_synthetic=e.is_synthetic)


def _config_key(e) -> tuple:
    return (e.brand_key, e.model_key, e.cpu_key, e.ram_gb, e.storage_gb, e.condition_grade, e.channel)


def run_backtest(db: Session, cfg: PricingConfig, *, holdout_fraction: float = 0.3, synthetic: bool = False) -> dict:
    evidence = []
    for Model in (MarketListing, SupplierQuote, Transaction):
        evidence += [to_evidence(r) for r in db.scalars(select(Model).where(Model.is_synthetic.is_(synthetic))).all()]
    sales = sorted([e for e in evidence if e.kind == "sale" and e.event_date and e.price],
                   key=lambda e: (e.event_date, e.id))
    report = {"method": __doc__.strip(), "synthetic_data": synthetic, "holdout_fraction": holdout_fraction,
              "total_completed_sales": len(sales)}
    if len(sales) < 10:
        report.update(status="insufficient_history",
                      message=f"Only {len(sales)} completed sales recorded; at least 10 are needed for a "
                              "meaningful chronological hold-out.")
        return report
    cut = int(len(sales) * (1 - holdout_fraction))
    held = sales[cut:]
    report["holdout_start_date"] = held[0].event_date.isoformat()
    report["holdout_count"] = len(held)
    cases = []
    for s in held:
        actual = _gross(s.price, s.tax_basis, cfg)
        if actual is None:
            cases.append({"sale_id": s.id, "skipped": "tax basis unknown"})
            continue
        as_of = datetime.combine(s.event_date - timedelta(days=1), time(23, 59, 59), tzinfo=timezone.utc)
        prior = [e for e in evidence if e.id != s.id and e.model_key == s.model_key]
        r = value_item(_subject_from_sale(s), prior, cfg, as_of)
        sel = r["selling"]
        base_vals = [_gross(e.price, e.tax_basis, cfg) for e in prior
                     if e.kind == "sale" and e.event_date and e.event_date < s.event_date
                     and _config_key(e) == _config_key(s)]
        base_vals = [v for v in base_vals if v is not None]
        cases.append({
            "sale_id": s.id, "date": s.event_date.isoformat(), "channel": s.channel, "actual": round(actual, 2),
            "engine_estimate": sel["p50_gross"] if sel else None, "engine_basis": sel["basis"] if sel else None,
            "engine_p25": sel["p25_gross"] if sel else None, "engine_p75": sel["p75_gross"] if sel else None,
            "engine_p10": sel["p10_gross"] if sel else None, "engine_p90": sel["p90_gross"] if sel else None,
            "engine_rating": (r["confidence"] or {}).get("grade"),
            "baseline_estimate": round(simple_median(base_vals), 2) if base_vals else None,
            "baseline_n": len(base_vals),
        })
    scored = [c for c in cases if "skipped" not in c]
    both = [c for c in scored if c["engine_estimate"] is not None and c["baseline_estimate"] is not None]

    def errs(key, rows):
        if not rows:
            return None
        ae = [abs(c[key] - c["actual"]) for c in rows]
        ape = [a / c["actual"] for a, c in zip(ae, rows)]
        return {"n": len(rows), "mae": round(sum(ae) / len(ae), 2), "mape_pct": round(100 * sum(ape) / len(ape), 2),
                "median_ape_pct": round(100 * simple_median(ape), 2)}

    eng = [c for c in scored if c["engine_estimate"] is not None]
    report.update(
        status="ok",
        engine_estimate_rate=round(len(eng) / len(scored), 4) if scored else None,
        baseline_estimate_rate=round(sum(1 for c in scored if c["baseline_estimate"] is not None) / len(scored), 4)
        if scored else None,
        head_to_head=errs("engine_estimate", both), baseline_head_to_head=errs("baseline_estimate", both),
        engine_all=errs("engine_estimate", eng),
        interval_coverage={
            "p25_p75": round(sum(1 for c in eng if c["engine_p25"] <= c["actual"] <= c["engine_p75"]) / len(eng), 4)
            if eng else None, "p25_p75_nominal": 0.5,
            "p10_p90": round(sum(1 for c in eng if c["engine_p10"] <= c["actual"] <= c["engine_p90"]) / len(eng), 4)
            if eng else None, "p10_p90_nominal": 0.8,
        },
        cases=cases,
        caveat="Coverage of the ranges is measured, not assumed. Small hold-out sets give noisy figures.",
    )
    return report
