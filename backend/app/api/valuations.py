from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..ai import claude
from ..db import get_db
from ..models import InventoryItem, PricingConfigVersion, User, ValuationRun
from ..security import require
from ..services import export as xport
from ..services.records import label
from ..services.valuation import latest_runs, run_summary, value_inventory_item, verify_reproducible

router = APIRouter(prefix="/api", tags=["valuations"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class RunIn(BaseModel):
    inventory_item_ids: list[int] = []
    lot_id: int | None = None
    as_of: datetime | None = None


@router.post("/valuations")
def run(body: RunIn, db: Session = Depends(get_db), user: User = Depends(require("run_valuation"))):
    ids = list(body.inventory_item_ids)
    if body.lot_id is not None:
        ids += list(db.scalars(select(InventoryItem.id).where(InventoryItem.lot_id == body.lot_id)).all())
    ids = sorted(set(ids))
    if not ids:
        raise HTTPException(422, "Select at least one inventory item or a lot")
    as_of = body.as_of
    if as_of is not None and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    out = []
    for i in ids:
        item = db.get(InventoryItem, i)
        if item is None:
            raise HTTPException(404, f"Item {i} not found")
        out.append(run_summary(value_inventory_item(db, item, user, as_of)))
    db.commit()
    return out


@router.get("/valuations")
def list_runs(item_id: int | None = None, limit: int = Query(200, le=2000), db: Session = Depends(get_db),
              _: User = Depends(require("view"))):
    q = select(ValuationRun).order_by(ValuationRun.id.desc()).limit(limit)
    if item_id is not None:
        q = q.where(ValuationRun.inventory_item_id == item_id)
    return [run_summary(r) for r in db.scalars(q).all()]


def _run(db: Session, run_id: int) -> ValuationRun:
    r = db.get(ValuationRun, run_id)
    if r is None:
        raise HTTPException(404, "Valuation not found")
    return r


@router.get("/valuations/{run_id}")
def detail(run_id: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    r = _run(db, run_id)
    item = db.get(InventoryItem, r.inventory_item_id)
    cv = db.get(PricingConfigVersion, r.config_version_id)
    return {"summary": run_summary(r), "result": r.result, "item": {"id": item.id, "label": label(item),
            "item_ref": item.item_ref, "lot_id": item.lot_id, "is_synthetic": item.is_synthetic},
            "config_version": {"id": cv.id, "version": cv.version, "note": cv.note, "hash": cv.config_hash},
            "ai_explanation": r.ai_explanation, "input_hash": r.input_hash,
            "evidence_snapshot_count": len(r.input_snapshot.get("evidence", []))}


@router.post("/valuations/{run_id}/reproduce")
def reproduce(run_id: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    r = _run(db, run_id)
    res = verify_reproducible(r)
    audit.record(db, user, "valuation.reproduce_checked", "valuation_run", r.id, reproduced=res["reproduced"])
    db.commit()
    return res


@router.post("/valuations/{run_id}/explain")
def explain(run_id: int, db: Session = Depends(get_db), user: User = Depends(require("use_ai"))):
    r = _run(db, run_id)
    try:
        exp = claude.explain(claude.explain_payload(r.result))
    except claude.AIUnavailable as e:
        raise HTTPException(503, str(e))
    exp["generated_at"] = datetime.now(timezone.utc).isoformat()
    r.ai_explanation = exp
    audit.record(db, user, "ai.explain", "valuation_run", r.id, model=exp["model"],
                 unverified=len(exp["unverified_figures"]))
    db.commit()
    return exp


@router.get("/valuations/{run_id}/export")
def export_one(run_id: int, db: Session = Depends(get_db), user: User = Depends(require("export"))):
    r = _run(db, run_id)
    item = db.get(InventoryItem, r.inventory_item_id)
    cv = db.get(PricingConfigVersion, r.config_version_id)
    data = xport.valuation_detail_workbook(r.id, label(item), r.result, {"config_version": cv.version})
    audit.record(db, user, "export.valuation", "valuation_run", r.id)
    db.commit()
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="valuation-{r.id}.xlsx"'})


@router.get("/exports/valuations")
def export_latest(format: str = "xlsx", lot_id: int | None = None, synthetic: bool | None = None,
                  db: Session = Depends(get_db), user: User = Depends(require("export"))):
    """Latest valuation of every inventory item (optionally one lot)."""
    q = select(InventoryItem)
    if lot_id is not None:
        q = q.where(InventoryItem.lot_id == lot_id)
    if synthetic is not None:
        q = q.where(InventoryItem.is_synthetic.is_(synthetic))
    items = db.scalars(q.order_by(InventoryItem.id)).all()
    runs = latest_runs(db, [i.id for i in items])
    rows = []
    for i in items:
        if i.id in runs:
            s = run_summary(runs[i.id])
            s.update(label=label(i), item_ref=i.item_ref, lot_ref=i.lot.lot_ref if i.lot else None)
            rows.append(s)
    audit.record(db, user, "export.valuations", None, None, format=format, rows=len(rows))
    db.commit()
    if format == "csv":
        h, data = xport.summary_rows(rows)
        return Response(xport.table_csv(h, data), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="valuations.csv"'})
    return Response(xport.valuations_workbook(rows), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="valuations.xlsx"'})
