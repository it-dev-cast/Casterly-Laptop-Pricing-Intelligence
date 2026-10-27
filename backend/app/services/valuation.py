"""Loads evidence for an inventory item, runs the engine, and stores an immutable snapshot."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, specs
from ..models import InventoryItem, MarketListing, SupplierQuote, Transaction, User, ValuationRun
from ..pricing.engine import ENGINE_VERSION, reproduce, run_valuation
from ..pricing.types import Evidence, Subject
from .config_store import active_config
from .records import to_evidence, to_subject


def gather_evidence(db: Session, subject: Subject) -> list[Evidence]:
    out: list[Evidence] = []
    for Model in (MarketListing, SupplierQuote, Transaction):
        rows = db.scalars(select(Model).where(Model.model_key == subject.model_key,
                                              Model.is_synthetic.is_(subject.is_synthetic))).all()
        for r in rows:
            if specs.brand_key(r.brand) == subject.brand_key:
                out.append(to_evidence(r))
    return out


def value_inventory_item(db: Session, item: InventoryItem, user: User | None,
                         as_of: datetime | None = None) -> ValuationRun:
    cfg, version = active_config(db)
    as_of = as_of or datetime.now(timezone.utc)
    subject = to_subject(item)
    evidence = gather_evidence(db, subject)
    snapshot, result = run_valuation(subject, evidence, cfg, as_of)
    econ = result["economics"]
    run = ValuationRun(
        inventory_item_id=item.id, created_by=user.id if user else None, as_of=as_of, status=result["status"],
        rating=result["confidence"]["grade"] if result["confidence"] else None, config_version_id=version.id,
        engine_version=ENGINE_VERSION, input_snapshot=snapshot, result=result, input_hash=result["input_hash"],
        output_hash=result["output_hash"], is_synthetic=item.is_synthetic,
        sale_p50_gross=(result["selling"] or {}).get("p50_gross"), target_buy_unit=econ.get("target_buy"),
        max_safe_buy_unit=econ.get("max_safe_buy"),
    )
    db.add(run)
    db.flush()
    audit.record(db, user, "valuation.created", "valuation_run", run.id, inventory_item_id=item.id,
                 status=run.status, config_version=version.version, output_hash=run.output_hash)
    return run


def verify_reproducible(run: ValuationRun) -> dict:
    again = reproduce(run.input_snapshot)
    return {"reproduced": again["output_hash"] == run.output_hash, "stored_output_hash": run.output_hash,
            "recomputed_output_hash": again["output_hash"], "engine_version": ENGINE_VERSION,
            "snapshot_engine_version": run.engine_version}


def latest_runs(db: Session, item_ids: list[int]) -> dict[int, ValuationRun]:
    if not item_ids:
        return {}
    rows = db.scalars(select(ValuationRun).where(ValuationRun.inventory_item_id.in_(item_ids))
                      .order_by(ValuationRun.inventory_item_id, ValuationRun.id.desc())).all()
    out: dict[int, ValuationRun] = {}
    for r in rows:
        out.setdefault(r.inventory_item_id, r)
    return out


def run_summary(run: ValuationRun) -> dict:
    r = run.result
    lot = r.get("lot") or {}
    econ = r["economics"]
    return {
        "id": run.id, "inventory_item_id": run.inventory_item_id, "created_at": run.created_at.isoformat(),
        "as_of": run.as_of.isoformat(), "status": run.status, "rating": run.rating,
        "is_synthetic": run.is_synthetic, "channel": r["channel"],
        "selling_p25": (r["selling"] or {}).get("p25_gross"), "selling_p50": (r["selling"] or {}).get("p50_gross"),
        "selling_p75": (r["selling"] or {}).get("p75_gross"), "selling_basis": (r["selling"] or {}).get("basis"),
        "listing_price": (r["listing_recommendation"] or {}).get("price_gross"),
        "target_buy": econ.get("target_buy"), "max_safe_buy": econ.get("max_safe_buy"),
        "recommended_buy": econ.get("recommended_buy"),
        "expected_margin": (econ.get("at_recommended") or {}).get("margin"),
        "expected_contribution_unit": (econ.get("at_recommended") or {}).get("contribution"),
        "asking_verdict": (econ.get("asking") or {}).get("verdict"),
        "flags": [f["code"] for f in econ.get("flags", [])],
        "quantity": lot.get("quantity"), "recommended_buy_total": lot.get("recommended_buy_total"),
        "max_safe_buy_total": lot.get("max_safe_buy_total"),
        "expected_contribution_total": lot.get("expected_contribution_total"),
        "total_lot_value": lot.get("total_lot_value"), "asking_total": lot.get("asking_total"),
        "comparables_included": r["summary_counts"]["included"],
        "comparables_considered": r["summary_counts"]["considered"],
        "output_hash": run.output_hash,
    }
