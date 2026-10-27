"""Pricing Intelligence REST API (/api/pi/...): procurement valuation of used IT assets."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import User
from ..procurement import accuracy, providers, research
from ..procurement.catalog import CATEGORY_LABELS
from ..procurement.excel_export import ExportIntegrityError, build
from ..procurement.excel_import import CANONICAL_FIELDS
from ..procurement.models import (PIAsset, PIBatch, PIEstimate, PIException, PIObservation, PIOutcome, PIOverride,
                                  PIProduct, PIQuotation, PIQuotationLine, PIResearchJob, PIResearchTask,
                                  PIRuleVersion, PISource)
from ..procurement.reference import import_reference_pack
from ..procurement.rules import PRICE_TYPES, Rules, config_gaps, default_rules, historical_reference_rules
from ..procurement.service import (ServiceError, active_rules, activate_rules, approve_assets, asset_out, batch_out,
                                   create_quotation, estimate_out, import_batch, job_out, money, observation_out,
                                   override_prices, price_batch, reidentify_asset, remap_batch, resolve_exceptions,
                                   save_rules)
from ..security import require

router = APIRouter(prefix="/api/pi", tags=["pricing-intelligence"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _err(e: Exception, code: int = 422):
    raise HTTPException(code, str(e))


def _batch(db: Session, batch_id: int) -> PIBatch:
    b = db.get(PIBatch, batch_id)
    if b is None:
        raise HTTPException(404, "Batch not found")
    return b


def _when(d: date | None) -> datetime:
    """Timestamp for a user-entered date: now for today (never in the future), noon UTC otherwise."""
    nw = datetime.now(timezone.utc)
    if d is None or d >= nw.date():
        return nw
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc).replace(hour=12)


def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise HTTPException(422, f"Not a valid amount: {v}")


# --------------------------------------------------------------------------- meta / dashboard

@router.get("/meta")
def meta(db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    rules, v = active_rules(db)
    db.commit()
    return {"categories": CATEGORY_LABELS, "price_types": PRICE_TYPES,
            "fields": {k: lbl for k, (lbl, _) in CANONICAL_FIELDS.items()}, "providers": providers.status(),
            "default_provider": providers.default_provider(), "rules_version": v.version,
            "statuses": ["unpriced", "auto_priced", "provisional", "review", "manual_required", "approved"]}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    rows = db.execute(select(PIAsset.category, PIAsset.status, func.count(), func.coalesce(func.sum(PIAsset.quantity), 0))
                      .group_by(PIAsset.category, PIAsset.status)).all()
    by_cat: dict[str, dict] = {}
    by_status: dict[str, int] = {}
    for cat, st, n, u in rows:
        c = by_cat.setdefault(cat, {"category": cat, "label": CATEGORY_LABELS.get(cat, cat), "lines": 0, "units": 0,
                                    "value": Decimal(0)})
        c["lines"] += n
        c["units"] += int(u)
        by_status[st] = by_status.get(st, 0) + n
    for cat, qty, calc, ov in db.execute(select(PIAsset.category, PIAsset.quantity, PIAsset.calculated_price,
                                                PIAsset.override_price)).all():
        p = ov if ov is not None else calc
        if p is not None and qty:
            by_cat[cat]["value"] += Decimal(p) * qty
    conf = dict(db.execute(select(PIEstimate.confidence, func.count()).where(PIEstimate.is_current.is_(True))
                           .group_by(PIEstimate.confidence)).all())
    total_products = db.scalar(select(func.count(func.distinct(PIAsset.product_id))).where(PIAsset.product_id.is_not(None))) or 0
    researched = db.scalar(select(func.count(func.distinct(PIObservation.product_id))).join(PIAsset, PIAsset.product_id == PIObservation.product_id).where(PIObservation.status == "verified", PIObservation.price > 0)) or 0
    quotes = db.scalars(select(PIQuotation).order_by(PIQuotation.id.desc()).limit(8)).all()
    batches = db.scalars(select(PIBatch).order_by(PIBatch.id.desc()).limit(8)).all()
    rules, v = active_rules(db)
    db.commit()
    return {"assets": sum(c["lines"] for c in by_cat.values()), "units": sum(c["units"] for c in by_cat.values()),
            "estimated_value": money(sum((c["value"] for c in by_cat.values()), Decimal(0))),
            "by_category": [{**c, "value": money(c["value"])} for c in sorted(by_cat.values(), key=lambda x: -x["units"])],
            "by_status": by_status, "confidence": {k or "None": n for k, n in conf.items()},
            "research_completion": round(100 * researched / total_products, 1) if total_products else None,
            "products": total_products, "products_with_evidence": researched,
            "review_required": by_status.get("review", 0) + by_status.get("manual_required", 0),
            "open_exceptions": db.scalar(select(func.count(PIException.id)).where(PIException.resolved.is_(False))) or 0,
            "recent_quotations": [quote_out(q) for q in quotes],
            "recent_batches": [{"id": b.id, "name": b.name, "status": b.status, "layout": b.layout,
                                "created_at": b.created_at.isoformat()} for b in batches],
            "rules": {"version": v.version, "name": v.name, "gaps": config_gaps(rules)},
            "providers": providers.status()}


@router.get("/diagnostics")
def diagnostics(db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    from ..procurement.diagnostics import report
    return report(db)


@router.post("/providers/{provider}/probe")
def probe_provider(provider: str, _: User = Depends(require("pi_research"))):
    try:
        adapter = providers.get_provider(provider)
        if not adapter.configured():
            return {"status": "blocked", "requirement": adapter.env_var}
        hits = adapter.search("Dell Latitude 5430 refurbished India price", count=1, country="IN")
        return {"status": "http_success", "hits": len(hits), "provider": provider,
                "note": "Connectivity probe only; this does not validate any price"}
    except providers.ProviderError as e:
        return {"status": "failed", "error": str(e), "retryable": e.retryable}


# --------------------------------------------------------------------------- batches

@router.post("/batches")
async def upload_batch(file: UploadFile = File(...), name: str | None = Form(None), vendor: str | None = Form(None),
                       sheet: str | None = Form(None), header_row: int | None = Form(None),
                       default_grade: str | None = Form(None),
                       db: Session = Depends(get_db), user: User = Depends(require("pi_import"))):
    content = await file.read()
    try:
        b = import_batch(db, user, filename=file.filename or "upload.xlsx", content=content, name=name, vendor=vendor,
                         sheet=sheet, header_row=header_row, default_grade=default_grade or None)
    except ServiceError as e:
        db.rollback()
        _err(e)
    db.commit()
    return batch_out(db, b)


class ManualAsset(BaseModel):
    description: str = Field(min_length=2)
    make: str | None = None
    model: str | None = None
    cpu: str | None = None
    ram: str | None = None
    storage: str | None = None
    grade: str | None = None
    quantity: int = Field(1, ge=1)
    category: str | None = None


class ManualBatchIn(BaseModel):
    name: str
    vendor: str | None = None
    assets: list[ManualAsset] = Field(min_length=1, max_length=200)


@router.post("/batches/manual")
def manual_batch(body: ManualBatchIn, db: Session = Depends(get_db), user: User = Depends(require("pi_import"))):
    """New Market Valuation: value assets typed in by a user (stored as a small generated workbook)."""
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    ws.title = "Asset List"
    ws.append(["Description", "Make", "Model", "Processor Type", "RAM", "Storage", "Grade", "Qty", "Product Type"])
    for a in body.assets:
        ws.append([a.description, a.make, a.model, a.cpu, a.ram, a.storage, a.grade, a.quantity,
                   CATEGORY_LABELS.get(a.category or "", None) if a.category else None])
    buf = io.BytesIO()
    wb.save(buf)
    try:
        b = import_batch(db, user, filename=f"{body.name[:80]}.xlsx", content=buf.getvalue(), name=body.name,
                         vendor=body.vendor)
    except ServiceError as e:
        db.rollback()
        _err(e)
    b.layout = "manual_entry"
    db.commit()
    return batch_out(db, b)


@router.get("/batches")
def list_batches(db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    return [batch_out(db, b) for b in db.scalars(select(PIBatch).order_by(PIBatch.id.desc()).limit(200)).all()]


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    return batch_out(db, _batch(db, batch_id))


class RemapIn(BaseModel):
    sheet: str | None = None
    header_row: int | None = None
    mapping: dict[str, str] | None = None
    default_grade: str | None = None


@router.post("/batches/{batch_id}/mapping")
def remap(batch_id: int, body: RemapIn, db: Session = Depends(get_db), user: User = Depends(require("pi_import"))):
    b = _batch(db, batch_id)
    unknown = [k for k in (body.mapping or {}) if k not in CANONICAL_FIELDS]
    if unknown:
        raise HTTPException(422, f"Unknown fields: {unknown}")
    try:
        remap_batch(db, b, user, sheet=body.sheet, header_row=body.header_row, mapping=body.mapping,
                    default_grade=body.default_grade)
    except ServiceError as e:
        db.rollback()
        _err(e)
    db.commit()
    return batch_out(db, b)


@router.get("/batches/{batch_id}/preview")
def preview(batch_id: int, limit: int = Query(25, le=200), db: Session = Depends(get_db),
            _: User = Depends(require("pi_view"))):
    b = _batch(db, batch_id)
    rows = db.scalars(select(PIAsset).where(PIAsset.batch_id == b.id).order_by(PIAsset.row_number).limit(limit)).all()
    return {"batch": batch_out(db, b), "rows": [{"row_number": a.row_number, "raw": a.raw, "label": (a.normalized or {}).get("label"),
                                                 "category": a.category, "quantity": a.quantity, "grade": a.grade,
                                                 "identify_confidence": a.identify_confidence} for a in rows]}


@router.post("/batches/{batch_id}/price")
def run_pricing(batch_id: int, rule_version_id: int | None = None, db: Session = Depends(get_db),
                user: User = Depends(require("pi_price"))):
    b = _batch(db, batch_id)
    try:
        res = price_batch(db, b, user, rules_version_id=rule_version_id)
    except ServiceError as e:
        db.rollback()
        _err(e)
    db.commit()
    return {**res, "batch": batch_out(db, b)}


@router.post("/batches/{batch_id}/analyze")
def analyze_batch(batch_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require("pi_price")),
                  _research: User = Depends(require("pi_research")),
                  _quote: User = Depends(require("pi_quote")),
                  _export: User = Depends(require("export"))):
    from ..procurement.automatic import queue
    job = queue(db, _batch(db, batch_id), user)
    db.commit()
    return job_out(job)


@router.get("/jobs/{job_id}/workbook")
def automatic_workbook(job_id: int, db: Session = Depends(get_db), _: User = Depends(require("export"))):
    from ..importing.files import stored_path
    j = db.get(PIResearchJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    artifact = (j.params or {}).get("artifact")
    if not artifact:
        raise HTTPException(409, "Workbook is not ready; inspect job progress/errors")
    path = stored_path(artifact)
    if not path.is_file():
        raise HTTPException(410, "Generated workbook is missing; rerun valuation")
    import hashlib
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != (j.params or {}).get("artifact_sha256"):
        raise HTTPException(409, "Workbook integrity check failed; rerun valuation")
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="Casterly_Valuation_{j.batch_id}.xlsx"',
        "X-Workbook-Fidelity": "Original OOXML parts preserved; pricing cells and report sheets added"})


SORTS = {"row": PIAsset.row_number, "price": PIAsset.calculated_price, "qty": PIAsset.quantity,
         "category": PIAsset.category, "status": PIAsset.status}


@router.get("/batches/{batch_id}/assets")
def list_assets(batch_id: int, status: str | None = None, category: str | None = None, confidence: str | None = None,
                q: str | None = None, sort: str = "row", desc: bool = False, page: int = Query(1, ge=1),
                page_size: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                _: User = Depends(require("pi_view"))):
    _batch(db, batch_id)
    base = select(PIAsset, PIEstimate).outerjoin(PIEstimate, PIEstimate.id == PIAsset.estimate_id).where(
        PIAsset.batch_id == batch_id)
    if status:
        base = base.where(PIAsset.status.in_(status.split(",")))
    if category:
        base = base.where(PIAsset.category == category)
    if confidence:
        base = base.where(PIEstimate.confidence == confidence)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(or_(func.lower(PIAsset.original_spec).like(like), func.lower(PIAsset.serial).like(like)))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    col = SORTS.get(sort, PIAsset.row_number)
    rows = db.execute(base.order_by(col.desc() if desc else col, PIAsset.row_number)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [asset_out(a, e) for a, e in rows]}


@router.get("/batches/{batch_id}/groups")
def list_groups(batch_id: int, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    """Research/pricing groups: one per product (and grade) — the unit of market research."""
    _batch(db, batch_id)
    rows = db.execute(select(PIAsset.product_id, PIAsset.grade, func.count(), func.coalesce(func.sum(PIAsset.quantity), 0))
                      .where(PIAsset.batch_id == batch_id).group_by(PIAsset.product_id, PIAsset.grade)).all()
    pids = [r[0] for r in rows if r[0]]
    prods = {p.id: p for p in db.scalars(select(PIProduct).where(PIProduct.id.in_(pids or [0]))).all()}
    est = {(e.product_id, e.grade): e for e in db.scalars(select(PIEstimate).where(
        PIEstimate.batch_id == batch_id, PIEstimate.is_current.is_(True))).all()}
    obs_counts = dict(db.execute(select(PIObservation.product_id, func.count()).where(
        PIObservation.product_id.in_(pids or [0])).group_by(PIObservation.product_id)).all())
    ver_counts = dict(db.execute(select(PIObservation.product_id, func.count()).where(
        PIObservation.product_id.in_(pids or [0]), PIObservation.status == "verified").group_by(PIObservation.product_id)).all())
    cand_counts = dict(db.execute(select(PIObservation.product_id, func.count()).where(
        PIObservation.product_id.in_(pids or [0]), PIObservation.status == "candidate").group_by(PIObservation.product_id)).all())
    out = []
    for pid, grade, n, units in rows:
        p = prods.get(pid)
        e = est.get((pid, grade or ""))
        out.append({"product_id": pid, "label": p.label if p else "Unidentified", "category": p.category if p else None,
                    "grade": grade, "lines": n, "units": int(units), "observations": obs_counts.get(pid, 0),
                    "verified": ver_counts.get(pid, 0), "candidates": cand_counts.get(pid, 0),
                    "estimate": estimate_out(e) if e else None})
    return sorted(out, key=lambda r: (-r["units"], r["label"]))


@router.get("/assets/{asset_id}")
def asset_detail(asset_id: int, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    a = db.get(PIAsset, asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    e = db.get(PIEstimate, a.estimate_id) if a.estimate_id else None
    p = db.get(PIProduct, a.product_id) if a.product_id else None
    exc = db.scalars(select(PIException).where(PIException.batch_id == a.batch_id, or_(
        PIException.asset_id == a.id, (PIException.asset_id.is_(None)) & (PIException.product_id == a.product_id)))).all()
    overrides = db.scalars(select(PIOverride).where(PIOverride.asset_id == a.id).order_by(PIOverride.id)).all()
    history = []
    if p:
        for h in db.scalars(select(PIEstimate).where(PIEstimate.product_id == p.id).order_by(PIEstimate.as_of.desc())
                            .limit(20)).all():
            history.append(estimate_out(h))
    return {"asset": asset_out(a, e), "product": {"id": p.id, "label": p.label, "category": p.category, "spec": p.spec,
                                                  "product_key": p.product_key} if p else None,
            "estimate": {**estimate_out(e), "breakdown": e.breakdown} if e else None,
            "exceptions": [exc_out(x) for x in exc],
            "overrides": [{"id": o.id, "calculated_price": money(o.calculated_price), "previous_price": money(o.previous_price),
                           "new_price": money(o.new_price), "reason": o.reason, "user_id": o.user_id,
                           "at": o.at.isoformat()} for o in overrides],
            "history": history}


class OverrideIn(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=5000)
    price: str | None = None  # null clears the override
    reason: str


@router.post("/assets/override")
def override(body: OverrideIn, db: Session = Depends(get_db), user: User = Depends(require("pi_override"))):
    try:
        n = override_prices(db, user, body.asset_ids, _dec(body.price), body.reason)
    except ServiceError as e:
        db.rollback()
        _err(e)
    db.commit()
    return {"updated": n}


class ReidentifyIn(BaseModel):
    fields: dict[str, str | int | None]
    method: str = "manual"  # manual | ai_suggested
    apply_to_same_spec: bool = False


@router.post("/assets/{asset_id}/reidentify")
def reidentify(asset_id: int, body: ReidentifyIn, db: Session = Depends(get_db), user: User = Depends(require("pi_import"))):
    a = db.get(PIAsset, asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    allowed = {"make", "model", "cpu", "generation", "ram", "storage", "gpu", "grade", "description", "category_hint",
               "product_type", "charger", "notes"}
    bad = [k for k in body.fields if k not in allowed]
    if bad or body.method not in ("manual", "ai_suggested"):
        raise HTTPException(422, f"Unsupported fields or method: {bad or body.method}")
    ids = reidentify_asset(db, user, a, body.fields, body.method, body.apply_to_same_spec)
    db.commit()
    return {"updated": ids, "asset": asset_out(db.get(PIAsset, asset_id))}


@router.post("/assets/{asset_id}/ai-suggest")
def ai_suggest(asset_id: int, db: Session = Depends(get_db), user: User = Depends(require("use_ai"))):
    """Ask Claude to read an ambiguous description. Returns suggestions only; nothing is changed or priced."""
    from ..ai import claude
    a = db.get(PIAsset, asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    text = " | ".join(f"{k}: {v}" for k, v in (a.raw or {}).items() if v not in (None, ""))
    try:
        sug, model = claude.extract(text)
    except claude.AIUnavailable as e:
        raise HTTPException(503, str(e))
    audit.record(db, user, "ai.pi_identify", "pi_asset", a.id, model=model, fields=sorted(sug))
    db.commit()
    mapping = {"brand": "make", "model": "model", "cpu": "cpu", "ram_gb": "ram", "storage_gb": "storage", "gpu": "gpu",
               "condition_grade": "grade", "charger_included": "charger"}
    return {"model": model, "suggestions": {mapping[k]: v for k, v in sug.items() if k in mapping},
            "note": "AI suggestions are unverified. Review each value before applying it."}


class IdsIn(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=10000)


@router.post("/assets/approve")
def approve(body: IdsIn, db: Session = Depends(get_db), user: User = Depends(require("pi_approve"))):
    r = approve_assets(db, user, body.asset_ids)
    db.commit()
    return r


@router.post("/batches/{batch_id}/approve-all")
def approve_all(batch_id: int, statuses: str = "auto_priced", db: Session = Depends(get_db),
                user: User = Depends(require("pi_approve"))):
    ids = list(db.scalars(select(PIAsset.id).where(PIAsset.batch_id == batch_id,
                                                   PIAsset.status.in_(statuses.split(",")))).all())
    r = approve_assets(db, user, ids) if ids else {"approved": 0, "skipped_unpriced": 0}
    db.commit()
    return r


# --------------------------------------------------------------------------- research

class ResearchIn(BaseModel):
    provider: str | None = None
    product_ids: list[int] | None = None
    force: bool = False


@router.post("/batches/{batch_id}/research")
def start_research(batch_id: int, body: ResearchIn, db: Session = Depends(get_db),
                   user: User = Depends(require("pi_research"))):
    _batch(db, batch_id)
    prov = body.provider or providers.default_provider()
    if prov is None:
        raise HTTPException(409, "No market research provider is configured. Set CLPI_BRAVE_API_KEY or "
                                 "CLPI_TAVILY_API_KEY on the server, or add verified evidence manually.")
    try:
        job = research.create_job(db, batch_id=batch_id, product_ids=body.product_ids, provider=prov, user=user,
                                  force=body.force)
    except (research.ResearchError, providers.ProviderError) as e:
        db.rollback()
        _err(e, 409)
    db.commit()
    return job_out(job)


@router.get("/jobs")
def list_jobs(batch_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    q = select(PIResearchJob).order_by(PIResearchJob.id.desc()).limit(50)
    if batch_id:
        q = q.where(PIResearchJob.batch_id == batch_id)
    return [job_out(j) for j in db.scalars(q).all()]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    j = db.get(PIResearchJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    tasks = db.execute(select(PIResearchTask, PIProduct).join(PIProduct, PIProduct.id == PIResearchTask.product_id)
                       .where(PIResearchTask.job_id == j.id).order_by(PIResearchTask.id)).all()
    return {**job_out(j), "tasks": [{"id": t.id, "product_id": t.product_id, "product": p.label, "status": t.status,
                                     "attempts": t.attempts, "hits": t.hits, "observations_found": t.observations_found,
                                     "error": t.error, "queries": t.queries} for t, p in tasks]}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, db: Session = Depends(get_db), user: User = Depends(require("pi_research"))):
    j = db.get(PIResearchJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    research.cancel_job(db, j, user)
    db.commit()
    return job_out(j)


@router.post("/jobs/{job_id}/resume")
def resume(job_id: int, db: Session = Depends(get_db), user: User = Depends(require("pi_research"))):
    j = db.get(PIResearchJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    if j.status in ("queued", "running"):
        raise HTTPException(409, "Job is already active")
    research.resume_job(db, j, user)
    db.commit()
    return job_out(j)


# --------------------------------------------------------------------------- observations

@router.get("/observations")
def list_observations(product_id: int | None = None, batch_id: int | None = None, status: str | None = None,
                      limit: int = Query(500, le=5000), db: Session = Depends(get_db),
                      _: User = Depends(require("pi_view"))):
    q = select(PIObservation, PISource).outerjoin(PISource, PISource.id == PIObservation.source_id)
    if product_id:
        q = q.where(PIObservation.product_id == product_id)
    if batch_id:
        pids = select(PIAsset.product_id).where(PIAsset.batch_id == batch_id)
        q = q.where(PIObservation.product_id.in_(pids))
    if status:
        q = q.where(PIObservation.status.in_(status.split(",")))
    rows = db.execute(q.order_by(PIObservation.product_id, PIObservation.id.desc()).limit(limit)).all()
    return [observation_out(o, s) for o, s in rows]


class ObservationIn(BaseModel):
    product_id: int
    price_type: str
    price: str
    tax_basis: str = "exclusive"
    match_quality: str = "identical"
    url: str | None = None
    seller: str | None = None
    title: str | None = None
    condition: str | None = None
    observed_at: date | None = None
    notes: str | None = None


@router.post("/observations")
def add_observation(body: ObservationIn, db: Session = Depends(get_db), user: User = Depends(require("pi_verify_evidence"))):
    """Administrator / procurement-entered evidence (for example a vendor's written buyback quote)."""
    from ..procurement.extraction import domain_of
    from ..procurement.research import _source_for, dedup_key
    if body.price_type not in PRICE_TYPES or body.price_type == "historical_valuation":
        raise HTTPException(422, "Unknown or reserved price type")
    if body.tax_basis not in ("inclusive", "exclusive", "unknown") or body.match_quality not in ("identical", "comparable"):
        raise HTTPException(422, "Invalid tax basis or match quality")
    if body.url and not body.url.startswith(("https://", "http://")):
        raise HTTPException(422, "URL must start with http(s)://")
    if db.get(PIProduct, body.product_id) is None:
        raise HTTPException(404, "Product not found")
    price = _dec(body.price)
    if price is None or price <= 0:
        raise HTTPException(422, "Price must be positive")
    when = _when(body.observed_at)
    src = _source_for(db, domain_of(body.url)) if body.url else None
    key = dedup_key(body.url or f"manual:{user.id}:{body.title}", price, when, "manual")
    if db.scalar(select(PIObservation.id).where(PIObservation.product_id == body.product_id, PIObservation.dedup_key == key)):
        raise HTTPException(409, "This observation already exists")
    o = PIObservation(product_id=body.product_id, source_id=src.id if src else None, provider="manual",
                      price_type=body.price_type, match_quality=body.match_quality, title=body.title, price=price,
                      tax_basis=body.tax_basis, condition=body.condition, seller=body.seller, url=body.url,
                      observed_at=when, status="verified", status_reason=f"Entered and verified by {user.email}",
                      dedup_key=key, verified_by=user.id, created_by=user.id, attributes={"notes": body.notes})
    db.add(o)
    db.flush()
    audit.record(db, user, "pi.observation.added", "pi_observation", o.id, product_id=o.product_id,
                 price=money(price), price_type=o.price_type)
    db.commit()
    return observation_out(o, src)


class VerifyIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=2000)
    action: str  # verify | reject | reset
    reason: str | None = None
    price_type: str | None = None
    tax_basis: str | None = None
    match_quality: str | None = None


@router.post("/observations/verify")
def verify_observations(body: VerifyIn, db: Session = Depends(get_db), user: User = Depends(require("pi_verify_evidence"))):
    if body.action not in ("verify", "reject", "reset"):
        raise HTTPException(422, "action must be verify, reject or reset")
    n = 0
    for o in db.scalars(select(PIObservation).where(PIObservation.id.in_(body.ids))).all():
        if o.provider == "reference_pack" and o.price_type == "historical_valuation":
            continue
        if body.action == "verify":
            if o.price is None:
                continue
            o.status, o.verified_by = "verified", user.id
            o.attributes = {**(o.attributes or {}), "research_mode": "manual_verified_search",
                            "verified_at": datetime.now(timezone.utc).isoformat()}
        elif body.action == "reject":
            o.status = "rejected"
        else:
            o.status = "candidate" if o.price is not None else "lead"
        o.status_reason = body.reason or f"{body.action} by {user.email}"
        if body.price_type in PRICE_TYPES and body.price_type != "historical_valuation":
            o.price_type = body.price_type
        if body.tax_basis in ("inclusive", "exclusive", "unknown"):
            o.tax_basis = body.tax_basis
        if body.match_quality in ("identical", "comparable"):
            o.match_quality = body.match_quality
        n += 1
    audit.record(db, user, f"pi.observation.{body.action}", "pi_observation", None, ids=body.ids[:200], count=n)
    db.commit()
    return {"updated": n}


# --------------------------------------------------------------------------- exceptions

def exc_out(e: PIException) -> dict:
    return {"id": e.id, "batch_id": e.batch_id, "asset_id": e.asset_id, "product_id": e.product_id, "code": e.code,
            "severity": e.severity, "message": e.message, "impact": e.impact, "action": e.action,
            "resolved": e.resolved, "resolution_note": e.resolution_note,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None}


@router.get("/exceptions")
def list_exceptions(batch_id: int | None = None, severity: str | None = None, code: str | None = None,
                    resolved: bool | None = False, limit: int = Query(1000, le=10000), db: Session = Depends(get_db),
                    _: User = Depends(require("pi_view"))):
    q = select(PIException, PIAsset, PIProduct).outerjoin(PIAsset, PIAsset.id == PIException.asset_id).outerjoin(
        PIProduct, PIProduct.id == PIException.product_id)
    if batch_id:
        q = q.where(PIException.batch_id == batch_id)
    if severity:
        q = q.where(PIException.severity.in_(severity.split(",")))
    if code:
        q = q.where(PIException.code == code)
    if resolved is not None:
        q = q.where(PIException.resolved.is_(resolved))
    rows = db.execute(q.order_by(PIException.id).limit(limit)).all()
    summary = dict(db.execute(select(PIException.code, func.count()).where(
        *( [PIException.batch_id == batch_id] if batch_id else []), PIException.resolved.is_(False))
        .group_by(PIException.code)).all())
    return {"summary": summary, "items": [{**exc_out(e), "row_number": a.row_number if a else None,
                                           "serial": a.serial if a else None,
                                           "product": p.label if p else (a.original_spec if a else None)}
                                          for e, a, p in rows]}


class ResolveIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)
    note: str | None = None


@router.post("/exceptions/resolve")
def resolve(body: ResolveIn, db: Session = Depends(get_db), user: User = Depends(require("pi_approve"))):
    n = resolve_exceptions(db, user, body.ids, body.note)
    db.commit()
    return {"resolved": n}


# --------------------------------------------------------------------------- quotations & export

def quote_out(q: PIQuotation) -> dict:
    return {"id": q.id, "quote_ref": q.quote_ref, "batch_id": q.batch_id, "vendor": q.vendor, "status": q.status,
            "lines": q.lines_count, "units": q.units, "total": money(q.total), "excluded_lines": q.excluded_lines,
            "valid_until": q.valid_until.isoformat() if q.valid_until else None, "notes": q.notes,
            "created_at": q.created_at.isoformat()}


class QuoteIn(BaseModel):
    vendor: str | None = None
    notes: str | None = None
    valid_days: int = Field(7, ge=1, le=90)
    include_unapproved: bool = False


@router.post("/batches/{batch_id}/quotations")
def new_quotation(batch_id: int, body: QuoteIn, db: Session = Depends(get_db), user: User = Depends(require("pi_quote"))):
    b = _batch(db, batch_id)
    try:
        q, created = create_quotation(db, user, b, vendor=body.vendor, notes=body.notes, valid_days=body.valid_days,
                                      include_unapproved=body.include_unapproved)
    except ServiceError as e:
        db.rollback()
        _err(e)
    db.commit()
    return {**quote_out(q), "created": created}


@router.get("/quotations")
def list_quotations(batch_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    q = select(PIQuotation).order_by(PIQuotation.id.desc()).limit(200)
    if batch_id:
        q = q.where(PIQuotation.batch_id == batch_id)
    return [quote_out(x) for x in db.scalars(q).all()]


@router.get("/quotations/{quote_id}")
def get_quotation(quote_id: int, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    q = db.get(PIQuotation, quote_id)
    if q is None:
        raise HTTPException(404, "Quotation not found")
    lines = db.execute(select(PIQuotationLine, PIAsset).join(PIAsset, PIAsset.id == PIQuotationLine.asset_id)
                       .where(PIQuotationLine.quotation_id == q.id).order_by(PIAsset.row_number).limit(5000)).all()
    return {**quote_out(q), "items": [{"asset_id": a.id, "row_number": a.row_number, "serial": a.serial,
                                       "description": ln.description, "quantity": ln.quantity,
                                       "unit_price": money(ln.unit_price), "line_total": money(ln.line_total),
                                       "basis": ln.price_basis} for ln, a in lines]}


@router.post("/quotations/{quote_id}/issue")
def issue_quotation(quote_id: int, db: Session = Depends(get_db), user: User = Depends(require("pi_quote"))):
    q = db.get(PIQuotation, quote_id)
    if q is None:
        raise HTTPException(404, "Quotation not found")
    if q.status == "superseded":
        raise HTTPException(409, "A newer quotation supersedes this one")
    q.status = "issued"
    audit.record(db, user, "pi.quotation.issued", "pi_quotation", q.id, ref=q.quote_ref)
    db.commit()
    return quote_out(q)


def _safe_name(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:80] or "export"


@router.get("/batches/{batch_id}/export")
def export_batch(batch_id: int, clean: bool = False, db: Session = Depends(get_db), user: User = Depends(require("export"))):
    b = _batch(db, batch_id)
    try:
        data, integrity = build(db, b, preserve=not clean)
    except ExportIntegrityError as e:
        raise HTTPException(500, str(e))
    audit.record(db, user, "pi.export.batch", "pi_batch", b.id, **{k: v for k, v in integrity.items() if k != "sheets"})
    db.commit()
    stem = _safe_name(b.original_filename.rsplit(".", 1)[0])
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{stem}_Market_Unit_Prices.xlsx"',
                                                    "X-Export-Prices-Written": str(integrity["prices_written"]),
                                                    "X-Workbook-Fidelity": integrity["fidelity"]["warning"]})


@router.get("/quotations/{quote_id}/export")
def export_quotation(quote_id: int, db: Session = Depends(get_db), user: User = Depends(require("export"))):
    q = db.get(PIQuotation, quote_id)
    if q is None:
        raise HTTPException(404, "Quotation not found")
    b = _batch(db, q.batch_id)
    try:
        data, integrity = build(db, b, q)
    except ExportIntegrityError as e:
        raise HTTPException(500, str(e))
    audit.record(db, user, "pi.export.quotation", "pi_quotation", q.id, ref=q.quote_ref,
                 prices_written=integrity["prices_written"])
    db.commit()
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{q.quote_ref}.xlsx"'})


# --------------------------------------------------------------------------- history, outcomes, accuracy

@router.get("/products")
def list_products(q: str | None = None, category: str | None = None, limit: int = Query(200, le=1000),
                  db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    s = select(PIProduct)
    if q:
        s = s.where(or_(func.lower(PIProduct.label).like(f"%{q.lower()}%"), func.lower(PIProduct.product_key).like(f"%{q.lower()}%")))
    if category:
        s = s.where(PIProduct.category == category)
    prods = db.scalars(s.order_by(PIProduct.label).limit(limit)).all()
    ids = [p.id for p in prods] or [0]
    latest = {}
    for e in db.scalars(select(PIEstimate).where(PIEstimate.product_id.in_(ids)).order_by(PIEstimate.as_of)).all():
        latest[e.product_id] = e
    obs = dict(db.execute(select(PIObservation.product_id, func.count()).where(PIObservation.product_id.in_(ids))
                          .group_by(PIObservation.product_id)).all())
    return [{"id": p.id, "label": p.label, "category": p.category, "product_key": p.product_key,
             "observations": obs.get(p.id, 0), "latest_estimate": estimate_out(latest[p.id]) if p.id in latest else None}
            for p in prods]


@router.get("/products/{product_id}")
def product_detail(product_id: int, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    p = db.get(PIProduct, product_id)
    if p is None:
        raise HTTPException(404, "Product not found")
    est = db.scalars(select(PIEstimate).where(PIEstimate.product_id == p.id).order_by(PIEstimate.as_of.desc())).all()
    obs = db.execute(select(PIObservation, PISource).outerjoin(PISource, PISource.id == PIObservation.source_id)
                     .where(PIObservation.product_id == p.id).order_by(PIObservation.observed_at.desc())).all()
    outs = db.scalars(select(PIOutcome).where(PIOutcome.product_id == p.id).order_by(PIOutcome.outcome_date.desc())).all()
    return {"product": {"id": p.id, "label": p.label, "category": p.category, "spec": p.spec, "product_key": p.product_key},
            "estimates": [estimate_out(e) for e in est], "observations": [observation_out(o, s) for o, s in obs],
            "outcomes": [outcome_out(o) for o in outs]}


def outcome_out(o: PIOutcome) -> dict:
    return {"id": o.id, "product_id": o.product_id, "batch_id": o.batch_id, "asset_id": o.asset_id, "kind": o.kind,
            "unit_price": money(o.unit_price), "quantity": o.quantity, "outcome_date": o.outcome_date.isoformat(),
            "vendor": o.vendor, "condition": o.condition, "notes": o.notes}


class OutcomeIn(BaseModel):
    product_id: int
    kind: str
    unit_price: str
    quantity: int = Field(1, ge=1)
    outcome_date: date
    vendor: str | None = None
    condition: str | None = None
    batch_id: int | None = None
    asset_id: int | None = None
    notes: str | None = None
    also_as_evidence: bool = True


@router.post("/outcomes")
def add_outcome(body: OutcomeIn, db: Session = Depends(get_db), user: User = Depends(require("pi_outcomes"))):
    if body.kind not in ("purchase", "resale"):
        raise HTTPException(422, "kind must be purchase or resale")
    if db.get(PIProduct, body.product_id) is None:
        raise HTTPException(404, "Product not found")
    price = _dec(body.unit_price)
    if price is None or price <= 0:
        raise HTTPException(422, "Price must be positive")
    o = PIOutcome(product_id=body.product_id, kind=body.kind, unit_price=price, quantity=body.quantity,
                  outcome_date=body.outcome_date, vendor=body.vendor, condition=body.condition, batch_id=body.batch_id,
                  asset_id=body.asset_id, notes=body.notes, created_by=user.id)
    db.add(o)
    db.flush()
    if body.kind == "purchase" and body.also_as_evidence:
        from ..procurement.research import dedup_key
        when = _when(body.outcome_date)
        db.add(PIObservation(product_id=body.product_id, provider="outcome", price_type="verified_transaction",
                             match_quality="identical", title=f"Casterly purchase ({body.quantity} units)", price=price,
                             tax_basis="exclusive", condition=body.condition, seller=body.vendor, observed_at=when,
                             status="verified", status_reason="Recorded purchase outcome",
                             dedup_key=dedup_key(f"outcome:{o.id}", price, when, "outcome"), verified_by=user.id,
                             created_by=user.id, attributes={"outcome_id": o.id, "quantity": body.quantity, "research_mode": "historical_transaction", "source_timestamp": when.isoformat()}))
    audit.record(db, user, "pi.outcome.recorded", "pi_outcome", o.id, kind=o.kind, price=money(price))
    db.commit()
    return outcome_out(o)


@router.get("/accuracy")
def accuracy_report(db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    rules, _v = active_rules(db)
    rep = accuracy.report(db)
    rep["suggestions"] = accuracy.suggestions(db, rules)
    return rep


# --------------------------------------------------------------------------- reference packs

@router.post("/reference-packs")
async def reference_pack(file: UploadFile = File(...), reference_date: date | None = Form(None),
                         db: Session = Depends(get_db), user: User = Depends(require("pi_rules"))):
    content = await file.read()
    try:
        res = import_reference_pack(db, user, filename=file.filename or "reference.xlsx", content=content,
                                    reference_date=reference_date)
    except ServiceError as e:
        db.rollback()
        _err(e)
    db.commit()
    return res


# --------------------------------------------------------------------------- sources

class SourceIn(BaseModel):
    name: str
    domain: str
    source_kind: str = "refurb_retailer"
    default_price_type: str | None = None
    reliability: float = Field(0.5, ge=0, le=1)
    categories: list[str] | None = None
    is_active: bool = True
    terms_note: str | None = None


def source_out(s: PISource, n: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "domain": s.domain, "source_kind": s.source_kind,
            "default_price_type": s.default_price_type, "reliability": s.reliability, "categories": s.categories,
            "region": s.region, "is_active": s.is_active, "terms_note": s.terms_note, "observations": n}


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    counts = dict(db.execute(select(PIObservation.source_id, func.count()).group_by(PIObservation.source_id)).all())
    return [source_out(s, counts.get(s.id, 0)) for s in db.scalars(select(PISource).order_by(PISource.name)).all()]


@router.post("/sources")
def add_source(body: SourceIn, db: Session = Depends(get_db), user: User = Depends(require("pi_sources"))):
    dom = body.domain.lower().strip().removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]
    if db.scalar(select(PISource).where(PISource.domain == dom)):
        raise HTTPException(409, "Source already exists")
    if body.default_price_type and body.default_price_type not in PRICE_TYPES:
        raise HTTPException(422, "Unknown price type")
    s = PISource(**{**body.model_dump(), "domain": dom}, region="India")
    db.add(s)
    db.flush()
    audit.record(db, user, "pi.source.added", "pi_source", s.id, domain=dom)
    db.commit()
    return source_out(s)


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourceIn, db: Session = Depends(get_db), user: User = Depends(require("pi_sources"))):
    s = db.get(PISource, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    for k in ("name", "source_kind", "default_price_type", "reliability", "categories", "is_active", "terms_note"):
        setattr(s, k, getattr(body, k))
    audit.record(db, user, "pi.source.updated", "pi_source", s.id, reliability=s.reliability, active=s.is_active)
    db.commit()
    return source_out(s)


# --------------------------------------------------------------------------- rules

def rv_out(v: PIRuleVersion) -> dict:
    return {"id": v.id, "version": v.version, "name": v.name, "note": v.note, "is_active": v.is_active,
            "hash": v.rules_hash, "created_at": v.created_at.isoformat(), "created_by": v.created_by}


@router.get("/rules")
def get_rules(db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    rules, v = active_rules(db)
    db.commit()
    return {"active": {**rv_out(v), "rules": v.rules}, "gaps": config_gaps(rules), "price_types": PRICE_TYPES,
            "versions": [rv_out(x) for x in db.scalars(select(PIRuleVersion).order_by(PIRuleVersion.version.desc())).all()]}


@router.get("/rules/versions/{version_id}")
def get_rule_version(version_id: int, db: Session = Depends(get_db), _: User = Depends(require("pi_view"))):
    v = db.get(PIRuleVersion, version_id)
    if v is None:
        raise HTTPException(404, "Rule version not found")
    return {**rv_out(v), "rules": v.rules}


class RulesIn(BaseModel):
    rules: dict
    note: str = Field(min_length=3)
    activate: bool = True


@router.post("/rules")
def put_rules(body: RulesIn, db: Session = Depends(get_db), user: User = Depends(require("pi_rules"))):
    try:
        rules = Rules.model_validate(body.rules)
    except Exception as e:
        raise HTTPException(422, f"Invalid rules: {e}")
    v = save_rules(db, rules, user, body.note, activate=body.activate)
    db.commit()
    return rv_out(v)


@router.post("/rules/versions/{version_id}/activate")
def activate(version_id: int, db: Session = Depends(get_db), user: User = Depends(require("pi_rules"))):
    try:
        v = activate_rules(db, version_id, user)
    except ServiceError as e:
        _err(e, 404)
    db.commit()
    return rv_out(v)


@router.post("/rules/presets/{preset}")
def load_preset(preset: str, db: Session = Depends(get_db), user: User = Depends(require("pi_rules"))):
    """Create (not activate) a preset rule version: 'defaults' or 'historical_reference'."""
    if preset == "defaults":
        r = default_rules()
    elif preset == "historical_reference":
        r = historical_reference_rules()
    else:
        raise HTTPException(404, "Unknown preset")
    v = save_rules(db, r, user, f"Preset: {r.name}", activate=False)
    db.commit()
    return rv_out(v)
