"""Inventory, lots, market evidence (manual entry and edits) and transaction outcomes."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, specs
from ..db import get_db
from ..importing.fields import field_map
from ..importing.normalize import jsonable, normalize_record
from ..models import FieldCorrection, InventoryItem, Lot, Transaction, User, ValuationRun
from ..security import can, current_user, require
from ..services import export as xport
from ..services.config_store import active_config
from ..services.records import MODEL_FOR, build_record, label, record_to_dict
from ..services.valuation import latest_runs, run_summary

router = APIRouter(prefix="/api", tags=["records"])

KIND_TO_TYPE = {"listings": "listing", "quotes": "quote", "transactions": "transaction"}


def _current_values(db: Session, rec, record_type: str) -> dict:
    d = record_to_dict(rec)
    vals = {k: d.get(k) for k in field_map(record_type)}
    if record_type == "inventory":
        vals["lot_ref"] = rec.lot.lot_ref if rec.lot else None
    if record_type == "transaction":
        item = db.get(InventoryItem, rec.inventory_item_id) if rec.inventory_item_id else None
        vals["item_ref"] = item.item_ref if item else None
    return vals


def _permission_for_create(record_type: str, values: dict) -> str:
    if record_type == "inventory":
        return "edit_inventory"
    if record_type == "listing":
        return "add_listing"
    if record_type == "quote":
        return "edit_evidence"
    kind = str(values.get("kind") or "").lower()
    return "record_sale" if kind.startswith("sale") or kind == "sold" else "record_purchase"


class ValuesIn(BaseModel):
    values: dict[str, Any]
    reason: str | None = None


# ---------------------------------------------------------------- inventory

@router.get("/inventory")
def list_inventory(q: str | None = None, lot_id: int | None = None, synthetic: bool | None = None,
                   db: Session = Depends(get_db), _: User = Depends(require("view"))):
    stmt = select(InventoryItem).order_by(InventoryItem.id.desc())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(InventoryItem.brand).like(like), InventoryItem.model_key.like(like),
                              func.lower(InventoryItem.item_ref).like(like), InventoryItem.cpu_key.like(like)))
    if lot_id is not None:
        stmt = stmt.where(InventoryItem.lot_id == lot_id)
    if synthetic is not None:
        stmt = stmt.where(InventoryItem.is_synthetic.is_(synthetic))
    items = db.scalars(stmt.limit(1000)).all()
    runs = latest_runs(db, [i.id for i in items])
    return [{**record_to_dict(i), "label": label(i),
             "latest_valuation": run_summary(runs[i.id]) if i.id in runs else None} for i in items]


@router.get("/inventory/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    i = db.get(InventoryItem, item_id)
    if i is None:
        raise HTTPException(404, "Item not found")
    runs = db.scalars(select(ValuationRun).where(ValuationRun.inventory_item_id == item_id)
                      .order_by(ValuationRun.id.desc())).all()
    corrections = db.scalars(select(FieldCorrection).where(FieldCorrection.record_type == "inventory",
                                                           FieldCorrection.record_id == item_id)).all()
    return {**record_to_dict(i), "label": label(i), "valuations": [run_summary(r) for r in runs],
            "edit_history": [{"field": c.field, "previous": c.previous_value, "new": c.new_value,
                              "at": c.at.isoformat(), "user_id": c.user_id, "reason": c.reason} for c in corrections]}


@router.get("/lots")
def list_lots(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    lots = db.scalars(select(Lot).order_by(Lot.id.desc())).all()
    out = []
    for lot in lots:
        items = lot.items
        runs = latest_runs(db, [i.id for i in items])
        summaries = [run_summary(runs[i.id]) for i in items if i.id in runs]

        def total(key):
            vals = [s[key] for s in summaries if s.get(key) is not None]
            return round(sum(vals), 2) if vals else None
        out.append({"id": lot.id, "lot_ref": lot.lot_ref, "supplier": lot.supplier, "is_synthetic": lot.is_synthetic,
                    "lines": len(items), "units": sum(i.quantity or 0 for i in items),
                    "lines_valued": len(summaries),
                    "lines_with_buy_price": sum(1 for s in summaries if s.get("recommended_buy") is not None),
                    "recommended_buy_total": total("recommended_buy_total"),
                    "max_safe_buy_total": total("max_safe_buy_total"),
                    "expected_contribution_total": total("expected_contribution_total"),
                    "total_lot_value": total("total_lot_value"), "asking_total": total("asking_total"),
                    "note": "Totals cover only lines with a computed valuation; see each line's status."})
    return out


# ---------------------------------------------------------------- create / edit (all record types)

def _create(db: Session, record_type: str, body: ValuesIn, user: User):
    perm = _permission_for_create(record_type, body.values)
    if not can(user, perm):
        raise HTTPException(403, f"Role '{user.role}' lacks permission '{perm}'")
    cfg, _ = active_config(db)
    norm, errors, warnings = normalize_record(record_type, body.values, cfg)
    if errors:
        raise HTTPException(422, {"errors": errors, "warnings": warnings})
    rec = build_record(db, record_type, norm, source_type="manual",
                       source_document=f"Manual entry by {user.email} on {date.today().isoformat()}", user=user,
                       raw_values={k: (str(v) if v is not None else None) for k, v in body.values.items()})
    audit.record(db, user, f"{record_type}.created", record_type, rec.id, source="manual")
    db.commit()
    return {**record_to_dict(rec), "warnings": warnings}


def _update(db: Session, record_type: str, rec, body: ValuesIn, user: User):
    perm = "edit_inventory" if record_type == "inventory" else "edit_evidence"
    if not can(user, perm):
        raise HTTPException(403, f"Role '{user.role}' lacks permission '{perm}'")
    fmap = field_map(record_type)
    bad = [k for k in body.values if k not in fmap]
    if bad:
        raise HTTPException(422, f"Unknown fields {bad}")
    cfg, _ = active_config(db)
    current = _current_values(db, rec, record_type)
    merged = {**current, **body.values}
    norm, errors, warnings = normalize_record(record_type, merged, cfg)
    if errors:
        raise HTTPException(422, {"errors": errors, "warnings": warnings})
    before = jsonable(current)
    after = jsonable(norm)
    changed = [k for k in body.values if before.get(k) != after.get(k)]
    for k in changed:
        db.add(FieldCorrection(record_type=record_type, record_id=rec.id, field=k,
                               original_value=str((rec.raw_values or {}).get(k)) if rec.raw_values else None,
                               previous_value=None if before.get(k) is None else str(before.get(k)),
                               new_value=None if after.get(k) is None else str(after.get(k)),
                               source="user", reason=body.reason, user_id=user.id))
    for k in changed:
        if k in ("lot_ref", "item_ref"):
            continue
        setattr(rec, k, norm[k])
    if any(k in changed for k in ("brand", "model")):
        rec.model_key = specs.model_key(norm.get("brand"), norm.get("model")) or ""
    if "cpu" in changed:
        rec.cpu_key = specs.cpu_key(norm.get("cpu"))
    if record_type == "transaction" and "item_ref" in changed:
        item = db.scalar(select(InventoryItem).where(InventoryItem.item_ref == norm["item_ref"],
                                                     InventoryItem.is_synthetic.is_(rec.is_synthetic))) \
            if norm.get("item_ref") else None
        rec.inventory_item_id = item.id if item else None
    if record_type == "inventory" and "lot_ref" in changed:
        if norm.get("lot_ref"):
            lot = db.scalar(select(Lot).where(Lot.lot_ref == norm["lot_ref"], Lot.is_synthetic.is_(rec.is_synthetic)))
            if lot is None:
                lot = Lot(lot_ref=norm["lot_ref"], is_synthetic=rec.is_synthetic)
                db.add(lot)
                db.flush()
            rec.lot_id = lot.id
        else:
            rec.lot_id = None
    corr = dict(rec.corrections or {})
    for k in changed:
        corr[k] = after.get(k)
    rec.corrections = corr or None
    audit.record(db, user, f"{record_type}.updated", record_type, rec.id, fields=changed, reason=body.reason)
    db.commit()
    return {**record_to_dict(rec), "changed": changed, "warnings": warnings}


@router.post("/inventory")
def create_item(body: ValuesIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _create(db, "inventory", body, user)


@router.patch("/inventory/{item_id}")
def update_item(item_id: int, body: ValuesIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rec = db.get(InventoryItem, item_id)
    if rec is None:
        raise HTTPException(404, "Item not found")
    return _update(db, "inventory", rec, body, user)


# ---------------------------------------------------------------- evidence

def _evidence_query(kind: str, q: str | None, synthetic: bool | None, txn_kind: str | None, channel: str | None):
    Model = MODEL_FOR[KIND_TO_TYPE[kind]]
    stmt = select(Model)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Model.brand).like(like), Model.model_key.like(like), Model.cpu_key.like(like),
                              func.lower(Model.seller).like(like)))
    if synthetic is not None:
        stmt = stmt.where(Model.is_synthetic.is_(synthetic))
    if txn_kind and kind == "transactions":
        stmt = stmt.where(Model.kind == txn_kind)
    if channel:
        stmt = stmt.where(Model.channel == channel)
    date_col = {"listings": Model.listing_date if kind == "listings" else None,
                "quotes": getattr(Model, "quote_date", None), "transactions": getattr(Model, "transaction_date", None)}[kind]
    return stmt.order_by(date_col.desc().nullslast(), Model.id.desc())


def _age(rec, kind: str, cfg) -> dict:
    d = {"listings": "listing_date", "quotes": "quote_date", "transactions": "transaction_date"}[kind]
    ev_date = getattr(rec, d)
    if ev_date is None:
        return {"age_days": None, "stale": None}
    age = (datetime.now(timezone.utc).date() - ev_date).days
    k = "listing" if kind == "listings" else ("quote" if kind == "quotes" else rec.kind)
    limit = cfg.freshness.max_age_days.get(k)
    return {"age_days": age, "stale": (age > limit) if limit is not None else None, "stale_limit_days": limit}


@router.get("/evidence/{kind}")
def list_evidence(kind: str, q: str | None = None, synthetic: bool | None = None, txn_kind: str | None = None,
                  channel: str | None = None, limit: int = Query(500, le=5000), db: Session = Depends(get_db),
                  _: User = Depends(require("view"))):
    if kind not in KIND_TO_TYPE:
        raise HTTPException(404, "Unknown evidence kind")
    cfg, _v = active_config(db)
    rows = db.scalars(_evidence_query(kind, q, synthetic, txn_kind, channel).limit(limit)).all()
    return [{**record_to_dict(r), "label": label(r), **_age(r, kind, cfg)} for r in rows]


@router.get("/evidence/{kind}/export")
def export_evidence(kind: str, format: str = "xlsx", synthetic: bool | None = None, db: Session = Depends(get_db),
                    user: User = Depends(require("export"))):
    if kind not in KIND_TO_TYPE:
        raise HTTPException(404, "Unknown evidence kind")
    rows = [record_to_dict(r) for r in db.scalars(_evidence_query(kind, None, synthetic, None, None)).all()]
    cols = [c for c in (rows[0].keys() if rows else []) if c not in ("raw_values", "corrections")]
    data = [[r.get(c) for c in cols] for r in rows]
    audit.record(db, user, "export.evidence", kind, None, format=format, rows=len(rows))
    db.commit()
    if format == "csv":
        return Response(xport.table_csv(cols, data), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})
    from openpyxl import Workbook
    wb = Workbook()
    xport._sheet(wb, kind.title(), cols, data, first=True)
    return Response(xport.to_bytes(wb),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{kind}.xlsx"'})


@router.post("/evidence/{kind}")
def create_evidence(kind: str, body: ValuesIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if kind not in KIND_TO_TYPE:
        raise HTTPException(404, "Unknown evidence kind")
    return _create(db, KIND_TO_TYPE[kind], body, user)


@router.patch("/evidence/{kind}/{rec_id}")
def update_evidence(kind: str, rec_id: int, body: ValuesIn, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if kind not in KIND_TO_TYPE:
        raise HTTPException(404, "Unknown evidence kind")
    rec = db.get(MODEL_FOR[KIND_TO_TYPE[kind]], rec_id)
    if rec is None:
        raise HTTPException(404, "Record not found")
    return _update(db, KIND_TO_TYPE[kind], rec, body, user)


# ---------------------------------------------------------------- transaction outcomes

class OutcomeIn(BaseModel):
    inventory_item_id: int
    kind: str  # sale | purchase
    price: Any
    transaction_date: Any
    quantity: Any = 1
    channel: str | None = None
    counterparty: str | None = None
    tax_basis: str | None = None
    fees_paid: Any = None
    reference: str | None = None


@router.post("/outcomes")
def record_outcome(body: OutcomeIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.kind not in ("sale", "purchase"):
        raise HTTPException(422, "kind must be sale or purchase")
    perm = "record_sale" if body.kind == "sale" else "record_purchase"
    if not can(user, perm):
        raise HTTPException(403, f"Role '{user.role}' lacks permission '{perm}'")
    item = db.get(InventoryItem, body.inventory_item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    spec = {k: getattr(item, k) for k in ("brand", "model", "cpu", "ram_gb", "storage_type", "storage_gb",
                                          "display_size_in", "display_resolution", "gpu", "condition_grade",
                                          "battery_health_pct", "faults", "charger_included", "warranty_months",
                                          "region")}
    if spec["faults"] is not None:
        spec["faults"] = "; ".join(spec["faults"]) if spec["faults"] else "none"
    values = {**spec, "kind": body.kind, "price": body.price, "transaction_date": body.transaction_date,
              "quantity": body.quantity, "channel": body.channel or item.intended_channel,
              "counterparty": body.counterparty, "currency": item.currency or "INR", "tax_basis": body.tax_basis,
              "fees_paid": body.fees_paid, "source_record_id": body.reference}
    cfg, _ = active_config(db)
    norm, errors, warnings = normalize_record("transaction", values, cfg)
    if errors:
        raise HTTPException(422, {"errors": errors, "warnings": warnings})
    rec = build_record(db, "transaction", norm, source_type="manual",
                       source_document=f"Outcome recorded by {user.email} for inventory item {item.id}",
                       user=user, is_synthetic=item.is_synthetic)
    rec.inventory_item_id = item.id
    run = db.scalar(select(ValuationRun).where(ValuationRun.inventory_item_id == item.id)
                    .order_by(ValuationRun.id.desc()).limit(1))
    rec.valuation_run_id = run.id if run else None
    if body.kind == "sale":
        item.status = "sold"
    audit.record(db, user, "outcome.recorded", "transaction", rec.id, inventory_item_id=item.id, kind=body.kind,
                 valuation_run_id=rec.valuation_run_id)
    db.commit()
    return {**record_to_dict(rec), "warnings": warnings}


@router.get("/outcomes")
def list_outcomes(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    rows = db.scalars(select(Transaction).where(Transaction.inventory_item_id.is_not(None))
                      .order_by(Transaction.transaction_date.desc().nullslast(), Transaction.id.desc())).all()
    cfg, _v = active_config(db)
    g = cfg.tax.gst_rate_pct / 100
    out = []
    for t in rows:
        run = db.get(ValuationRun, t.valuation_run_id) if t.valuation_run_id else None
        s = run_summary(run) if run else None
        actual_gross = t.price if t.tax_basis == "inclusive" else (t.price * (1 + g) if t.tax_basis == "exclusive" else None)
        pred = None
        if s and t.kind == "sale":
            pred = s["selling_p50"]
        elif s and t.kind == "purchase":
            pred = s["recommended_buy"]
        comparable_actual = actual_gross if t.kind == "sale" else (
            t.price / (1 + g) if t.tax_basis == "inclusive" and cfg.tax.mode == "standard" else t.price)
        out.append({**record_to_dict(t), "label": label(t), "valuation": s,
                    "predicted": pred, "actual_comparable": round(comparable_actual, 2) if comparable_actual else None,
                    "difference": round(comparable_actual - pred, 2) if (pred is not None and comparable_actual) else None,
                    "within_p25_p75": (s["selling_p25"] <= actual_gross <= s["selling_p75"])
                    if (t.kind == "sale" and s and s["selling_p25"] is not None and actual_gross) else None})
    return out
