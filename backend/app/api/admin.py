"""Settings, connectors, demo data, audit log, validation (backtest), dashboard, AI status."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..ai import claude
from ..connectors.adapters import ADAPTERS, ConnectorError, run_feed, validate_feed_config
from ..db import get_db
from ..models import (AuditEvent, BacktestRun, Connector, InventoryItem, MarketListing, PricingConfigVersion,
                      SupplierQuote, Transaction, UploadBatch, User, ValuationRun)
from ..pricing.config import PricingConfig, default_config
from ..security import require
from ..services import demo
from ..services.backtest import run_backtest
from ..services.config_store import active_config, save_config
from ..services.valuation import latest_runs, run_summary

router = APIRouter(prefix="/api", tags=["admin"])


# ---------------------------------------------------------------- settings

@router.get("/settings/pricing")
def get_pricing(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    cfg, v = active_config(db)
    return {"version": v.version, "id": v.id, "note": v.note, "created_at": v.created_at.isoformat(),
            "hash": v.config_hash, "config": cfg.model_dump(mode="json"),
            "defaults": default_config().model_dump(mode="json")}


class PricingIn(BaseModel):
    config: dict[str, Any]
    note: str | None = None


@router.put("/settings/pricing")
def put_pricing(body: PricingIn, db: Session = Depends(get_db), user: User = Depends(require("edit_settings"))):
    try:
        cfg = PricingConfig.model_validate(body.config)
    except ValidationError as e:
        raise HTTPException(422, [{"loc": ".".join(map(str, err["loc"])), "msg": err["msg"]} for err in e.errors()])
    ids = [a.id for a in cfg.adjustments]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Adjustment rule ids must be unique")
    v = save_config(db, cfg, user, body.note)
    audit.record(db, user, "settings.pricing_saved", "pricing_config", v.id, version=v.version, note=body.note,
                 hash=v.config_hash)
    db.commit()
    return {"version": v.version, "id": v.id, "hash": v.config_hash}


@router.get("/settings/pricing/versions")
def versions(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    rows = db.scalars(select(PricingConfigVersion).order_by(PricingConfigVersion.version.desc())).all()
    return [{"id": r.id, "version": r.version, "note": r.note, "is_active": r.is_active, "hash": r.config_hash,
             "created_at": r.created_at.isoformat(), "created_by": r.created_by} for r in rows]


# ---------------------------------------------------------------- connectors

def _stale_counts(db: Session, cfg: PricingConfig) -> dict:
    limit = cfg.freshness.max_age_days.get("listing", 45)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=limit)
    rows = db.execute(select(MarketListing.source_type, MarketListing.connector_id,
                             func.count().filter(MarketListing.listing_date < cutoff),
                             func.count()).where(MarketListing.is_synthetic.is_(False))
                      .group_by(MarketListing.source_type, MarketListing.connector_id)).all()
    return {(st, cid): (stale, total) for st, cid, stale, total in rows}


def connector_out(c: Connector, stale: dict) -> dict:
    info = ADAPTERS.get(c.adapter)
    if c.adapter == "manual":
        s, t = stale.get(("manual", None), (0, 0))
    elif c.adapter == "file_import":
        s, t = stale.get(("upload", None), (0, 0))
    else:
        s, t = stale.get(("connector", c.id), (0, 0))
    cfg = dict(c.config or {})
    return {"id": c.id, "name": c.name, "adapter": c.adapter, "title": info.title if info else c.adapter,
            "description": info.description if info else "", "live_capable": info.live_capable if info else False,
            "enabled": c.enabled, "status": c.status, "config": cfg,
            "config_problems": validate_feed_config(cfg) if c.adapter == "http_json_feed" else [],
            "last_attempt_at": c.last_attempt_at.isoformat() if c.last_attempt_at else None,
            "last_success_at": c.last_success_at.isoformat() if c.last_success_at else None,
            "last_error": c.last_error, "failure_count": c.failure_count, "last_records": c.last_records,
            "evidence_records": t, "stale_records": s}


@router.get("/connectors")
def list_connectors(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    cfg, _v = active_config(db)
    stale = _stale_counts(db, cfg)
    return [connector_out(c, stale) for c in db.scalars(select(Connector).order_by(Connector.id)).all()]


class ConnectorIn(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    name: str | None = None


@router.put("/connectors/{cid}")
def update_connector(cid: int, body: ConnectorIn, db: Session = Depends(get_db),
                     user: User = Depends(require("manage_connectors"))):
    c = db.get(Connector, cid)
    if c is None:
        raise HTTPException(404, "Connector not found")
    if c.adapter != "http_json_feed":
        raise HTTPException(422, "Built-in channels are not configurable")
    if body.config is not None:
        if any(k.lower() in ("api_key", "key", "token", "secret", "password") for k in body.config):
            raise HTTPException(422, "Do not store secrets in connector settings; name an environment variable "
                                     "in api_key_env instead")
        c.config = body.config
    if body.name:
        c.name = body.name[:120]
    if body.enabled is not None:
        if body.enabled and validate_feed_config(c.config or {}):
            raise HTTPException(422, {"problems": validate_feed_config(c.config or {})})
        c.enabled = body.enabled
    c.status = ("not_configured" if validate_feed_config(c.config or {}) else
                ("configured" if c.enabled and not c.last_success_at else ("disabled" if not c.enabled else c.status)))
    audit.record(db, user, "connector.updated", "connector", c.id, enabled=c.enabled,
                 config_keys=sorted((c.config or {}).keys()))
    db.commit()
    cfg, _v = active_config(db)
    return connector_out(c, _stale_counts(db, cfg))


@router.post("/connectors/{cid}/run")
def run_connector(cid: int, db: Session = Depends(get_db), user: User = Depends(require("manage_connectors"))):
    c = db.get(Connector, cid)
    if c is None:
        raise HTTPException(404, "Connector not found")
    if c.adapter != "http_json_feed":
        raise HTTPException(422, "Only feed connectors can be run")
    cfg, _v = active_config(db)
    try:
        res = run_feed(db, c, cfg, user)
    except ConnectorError as e:
        db.commit()
        raise HTTPException(502, str(e))
    db.commit()
    return res


# ---------------------------------------------------------------- demo data

@router.post("/admin/demo")
def load_demo(db: Session = Depends(get_db), user: User = Depends(require("manage_demo"))):
    res = demo.load(db, user)
    db.commit()
    return res


@router.delete("/admin/demo")
def remove_demo(db: Session = Depends(get_db), user: User = Depends(require("manage_demo"))):
    res = demo.remove(db, user)
    db.commit()
    return res


# ---------------------------------------------------------------- audit

@router.get("/audit")
def audit_log(limit: int = Query(300, le=2000), action: str | None = None, db: Session = Depends(get_db),
              _: User = Depends(require("view_audit"))):
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if action:
        q = q.where(AuditEvent.action.like(f"{action}%"))
    return [{"id": e.id, "at": e.at.isoformat(), "user": e.user_email, "action": e.action,
             "entity_type": e.entity_type, "entity_id": e.entity_id, "details": e.details}
            for e in db.scalars(q).all()]


# ---------------------------------------------------------------- validation

class BacktestIn(BaseModel):
    holdout_fraction: float = 0.3
    synthetic: bool = False


@router.post("/validation/backtest")
def backtest(body: BacktestIn, db: Session = Depends(get_db), user: User = Depends(require("run_backtest"))):
    if not 0.05 <= body.holdout_fraction <= 0.8:
        raise HTTPException(422, "holdout_fraction must be between 0.05 and 0.8")
    cfg, v = active_config(db)
    report = run_backtest(db, cfg, holdout_fraction=body.holdout_fraction, synthetic=body.synthetic)
    report["config_version"] = v.version
    row = BacktestRun(created_by=user.id, params=body.model_dump(), report=report, is_synthetic=body.synthetic)
    db.add(row)
    db.flush()
    audit.record(db, user, "validation.backtest", "backtest_run", row.id, status=report.get("status"),
                 synthetic=body.synthetic)
    db.commit()
    return {"id": row.id, "created_at": row.created_at.isoformat(), **report}


@router.get("/validation/backtest")
def latest_backtests(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    rows = db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(20)).all()
    return [{"id": r.id, "created_at": r.created_at.isoformat(), **r.report} for r in rows]


# ---------------------------------------------------------------- AI status & dashboard

@router.get("/ai/status")
def ai_status(_: User = Depends(require("view"))):
    return claude.status()


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    cfg, v = active_config(db)
    today = datetime.now(timezone.utc).date()

    def evidence_stats(Model, date_col, kind_key, extra=None):
        out = {}
        for synth in (False, True):
            q = select(func.count()).select_from(Model).where(Model.is_synthetic.is_(synth))
            if extra is not None:
                q = q.where(extra)
            total = db.scalar(q) or 0
            limit = cfg.freshness.max_age_days.get(kind_key)
            fresh = db.scalar(q.where(date_col >= today - timedelta(days=limit))) if limit else None
            out["synthetic" if synth else "real"] = {"total": total, "fresh": fresh, "fresh_window_days": limit}
        return out

    evidence = {
        "completed_sales": evidence_stats(Transaction, Transaction.transaction_date, "sale", Transaction.kind == "sale"),
        "completed_purchases": evidence_stats(Transaction, Transaction.transaction_date, "purchase",
                                              Transaction.kind == "purchase"),
        "listings": evidence_stats(MarketListing, MarketListing.listing_date, "listing"),
        "supplier_quotes": evidence_stats(SupplierQuote, SupplierQuote.quote_date, "quote"),
    }
    portfolio = {}
    for synth in (False, True):
        items = db.scalars(select(InventoryItem).where(InventoryItem.is_synthetic.is_(synth),
                                                       InventoryItem.status == "active")).all()
        runs = latest_runs(db, [i.id for i in items])
        sums = [run_summary(runs[i.id]) for i in items if i.id in runs]
        status_counts: dict[str, int] = {}
        for s in sums:
            status_counts[s["status"]] = status_counts.get(s["status"], 0) + 1

        def tot(k):
            vals = [s[k] for s in sums if s.get(k) is not None]
            return round(sum(vals), 2) if vals else None
        portfolio["synthetic" if synth else "real"] = {
            "lines": len(items), "units": sum(i.quantity or 0 for i in items), "lines_valued": len(sums),
            "status_counts": status_counts, "recommended_buy_total": tot("recommended_buy_total"),
            "max_safe_buy_total": tot("max_safe_buy_total"), "asking_total": tot("asking_total"),
            "expected_contribution_total": tot("expected_contribution_total"),
            "total_lot_value": tot("total_lot_value"),
            "above_ceiling": sum(1 for s in sums if s.get("asking_verdict") == "above_ceiling"),
            "critical_flags": sum(1 for s in sums if {"negative_ceiling", "infeasible_margin"} & set(s["flags"])),
        }
    conns = db.scalars(select(Connector)).all()
    live = [c for c in conns if c.adapter == "http_json_feed" and c.enabled and c.last_success_at
            and c.last_success_at >= datetime.now(timezone.utc) - timedelta(days=2)]
    recent = db.scalars(select(ValuationRun).order_by(ValuationRun.id.desc()).limit(8)).all()
    labels = {i.id: f"{i.brand} {i.model}" for i in db.scalars(select(InventoryItem).where(
        InventoryItem.id.in_([r.inventory_item_id for r in recent]))).all()} if recent else {}
    bt = db.scalar(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(1))
    pending_imports = db.scalar(select(func.count()).select_from(UploadBatch)
                                .where(UploadBatch.status.in_(("uploaded", "staged", "partially_committed")))) or 0
    return {
        "config_version": v.version, "config_gaps": _config_gaps(cfg), "evidence": evidence, "portfolio": portfolio,
        "market_coverage": {"live": bool(live), "live_connectors": [c.name for c in live],
                            "statement": ("Live market data from: " + ", ".join(c.name for c in live)) if live else
                            "No live market connector is configured. Evidence comes only from manual entry and "
                            "uploaded files."},
        "demo_data_present": demo.demo_present(db),
        "recent_valuations": [{**run_summary(r), "label": labels.get(r.inventory_item_id)} for r in recent],
        "latest_backtest": ({"id": bt.id, "created_at": bt.created_at.isoformat(), "status": bt.report.get("status"),
                             "synthetic": bt.is_synthetic, "head_to_head": bt.report.get("head_to_head"),
                             "baseline_head_to_head": bt.report.get("baseline_head_to_head"),
                             "interval_coverage": bt.report.get("interval_coverage"),
                             "holdout_count": bt.report.get("holdout_count")} if bt else None),
        "pending_imports": pending_imports,
        "ai": claude.status(),
    }


def _config_gaps(cfg: PricingConfig) -> list[str]:
    gaps = []
    if cfg.default_target_margin_pct is None:
        gaps.append("No default target margin (items without one cannot get a target buying price)")
    for ch, cc in cfg.channels.items():
        for f in cc.percentage_fees:
            if f.rate_pct is None:
                gaps.append(f"{ch} fee '{f.name}' not configured")
        for fc in cc.fixed_costs_per_sold_unit:
            if fc.amount is None:
                gaps.append(f"{ch} cost '{fc.name}' not configured")
    for fc in cfg.fixed_costs_per_purchased_unit:
        if fc.amount is None:
            gaps.append(f"Per-purchased-unit cost '{fc.name}' not configured")
    for f in cfg.fault_categories:
        if f.expected_yield_pct is None:
            gaps.append(f"Yield not set for fault category '{f.label}'")
    return gaps
