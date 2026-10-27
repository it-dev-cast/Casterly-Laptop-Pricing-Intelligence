"""Pricing Intelligence application services: import, grouping, pricing runs, review, quotations."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..importing.files import UploadRejected, stored_path, validate_and_store
from ..models import User
from . import engine
from .excel_import import ImportError_, parse_quantity, read_workbook
from .identify import EXCEPTIONS, Flag, identify
from .models import (
    PIAsset,
    PIBatch,
    PIEstimate,
    PIException,
    PIObservation,
    PIOverride,
    PIProduct,
    PIQuotation,
    PIQuotationLine,
    PIResearchJob,
    PIRuleVersion,
    PISource,
)
from .rules import Rules, default_rules, legacy_default_rules, rules_hash


class ServiceError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def money(v) -> str | None:
    return None if v is None else f"{Decimal(v):.2f}"


# --------------------------------------------------------------------------- rules

def save_rules(db: Session, rules: Rules, user: User | None, note: str | None, activate: bool = True) -> PIRuleVersion:
    nxt = (db.scalar(select(func.max(PIRuleVersion.version))) or 0) + 1
    if activate:
        db.execute(update(PIRuleVersion).values(is_active=False))
    v = PIRuleVersion(version=nxt, name=rules.name, rules=rules.model_dump(mode="json"), rules_hash=rules_hash(rules),
                      note=note, is_active=activate, created_by=user.id if user else None)
    db.add(v)
    db.flush()
    audit.record(db, user, "pi.rules.saved", "pi_rule_version", v.id, version=nxt, active=activate, note=note)
    return v


def active_rules(db: Session) -> tuple[Rules, PIRuleVersion]:
    v = db.scalar(select(PIRuleVersion).where(PIRuleVersion.is_active.is_(True)))
    if v is None:
        v = save_rules(db, default_rules(), None, "Initial documented starter assumptions; review against transactions")
    elif (v.note == "Initial defaults: identity conversions only; no discounts configured"
          and rules_hash(Rules.model_validate(v.rules)) == rules_hash(legacy_default_rules())):
        v = save_rules(db, default_rules(), None, "Upgrade untouched defaults; prior version retained")
    return Rules.model_validate(v.rules), v


def activate_rules(db: Session, version_id: int, user: User | None) -> PIRuleVersion:
    v = db.get(PIRuleVersion, version_id)
    if v is None:
        raise ServiceError("Rule version not found")
    db.execute(update(PIRuleVersion).values(is_active=False))
    v.is_active = True
    audit.record(db, user, "pi.rules.activated", "pi_rule_version", v.id, version=v.version)
    return v


# --------------------------------------------------------------------------- sources

CANDIDATE_SOURCES = [
    ("Cashify", "cashify.in", "buyback", "buyback_quote", ["smartphone", "tablet", "laptop", "macbook"]),
    ("ServerCart", "servercart.in", "refurb_retailer", "refurb_retail", ["server_cpu", "server_ram"]),
    ("ServerBasket", "serverbasket.com", "refurb_retailer", "refurb_retail", ["server_cpu", "server_ram"]),
    ("Server India", "serverindia.in", "refurb_retailer", "refurb_retail", ["server_cpu", "server_ram"]),
    ("ServerIndiaOnline", "serverindiaonline.com", "refurb_retailer", "refurb_retail", ["server_ram"]),
    ("Serverwale", "serverwale.com", "refurb_retailer", "refurb_retail", ["server_cpu", "server_ram"]),
    ("Xfurbish", "xfurbish.com", "refurb_retailer", "refurb_retail", ["server_cpu", "server_ram"]),
    ("Serverstore", "serverstore.in", "refurb_retailer", "refurb_retail", ["server_cpu"]),
    ("Refurbr", "refurbr.in", "refurb_retailer", "refurb_retail", ["server_cpu"]),
    ("Server Supply India", "serversupply.in", "refurb_retailer", "refurb_retail", ["server_ram"]),
    ("OLX India", "olx.in", "marketplace", "second_hand_ask", None),
    ("Casterly internal", "casterly.internal", "internal", "historical_valuation", None),
]


def seed_sources(db: Session) -> None:
    have = set(db.scalars(select(PISource.domain)).all())
    for name, dom, kind, ptype, cats in CANDIDATE_SOURCES:
        if dom not in have:
            db.add(PISource(name=name, domain=dom, source_kind=kind, default_price_type=ptype, reliability=0.5,
                            categories=cats, region="India", is_active=True,
                            terms_note="Candidate source: not an API integration. Reliability not yet assessed; "
                                       "prices reach the system only through licensed search results or manual entry."))


# --------------------------------------------------------------------------- import

def _exc_row(batch_id: int, asset_id: int | None, product_id: int | None, f: Flag) -> PIException:
    d = f.as_dict()
    return PIException(batch_id=batch_id, asset_id=asset_id, product_id=product_id, code=d["code"],
                       severity=d["severity"], message=d["message"][:2000], impact=d["impact"], action=d["action"])


def import_batch(db: Session, user: User | None, *, filename: str, content: bytes, name: str | None = None,
                 vendor: str | None = None, sheet: str | None = None, header_row: int | None = None,
                 mapping: dict[str, str] | None = None, default_grade: str | None = None) -> PIBatch:
    try:
        info = validate_and_store(filename, content)
    except UploadRejected as e:
        raise ServiceError(str(e)) from e
    if info["file_kind"] != "xlsx":
        raise ServiceError("Pricing Intelligence imports .xlsx workbooks")
    b = PIBatch(name=(name or filename)[:200], vendor=vendor, original_filename=filename[:255], layout="generic",
                column_map={}, created_by=user.id if user else None, **info)
    db.add(b)
    db.flush()
    _load_rows(db, b, sheet=sheet, header_row=header_row, mapping=mapping, default_grade=default_grade)
    audit.record(db, user, "pi.batch.imported", "pi_batch", b.id, filename=filename, layout=b.layout,
                 rows=(b.detection or {}).get("data_rows"), sha256=b.sha256)
    return b


def remap_batch(db: Session, b: PIBatch, user: User | None, *, sheet: str | None, header_row: int | None,
                mapping: dict[str, str] | None, default_grade: str | None = None) -> PIBatch:
    if db.scalar(select(func.count(PIAsset.id)).where(PIAsset.batch_id == b.id, PIAsset.status == "approved")):
        raise ServiceError("Approved prices exist; remapping would discard them")
    if db.scalar(select(func.count(PIQuotation.id)).where(PIQuotation.batch_id == b.id)):
        raise ServiceError("A quotation exists for this batch; upload the file again as a new batch instead")
    db.execute(update(PIAsset).where(PIAsset.batch_id == b.id).values(estimate_id=None))
    db.execute(delete(PIException).where(PIException.batch_id == b.id))
    db.execute(delete(PIEstimate).where(PIEstimate.batch_id == b.id))
    db.execute(delete(PIAsset).where(PIAsset.batch_id == b.id))
    _load_rows(db, b, sheet=sheet, header_row=header_row, mapping=mapping,
               default_grade=default_grade or (b.detection or {}).get("default_grade"))
    b.status = "imported"
    audit.record(db, user, "pi.batch.remapped", "pi_batch", b.id, mapping=b.column_map, sheet=b.sheet_name)
    return b


def _load_rows(db: Session, b: PIBatch, *, sheet, header_row, mapping, default_grade: str | None = None) -> None:
    rules, _ = active_rules(db)
    try:
        res = read_workbook(stored_path(b.stored_name), qty_columns=rules.quantity_columns,
                            max_rows=get_settings().max_upload_rows, sheet=sheet, header_row=header_row, mapping=mapping)
    except ImportError_ as e:
        raise ServiceError(str(e)) from e
    b.layout, b.sheet_name, b.header_row = res.layout, res.sheet, res.header_row
    b.column_map, b.qty_column, b.price_column = res.column_map, res.qty_column, res.price_column
    b.detection = {**res.detection(), "default_grade": default_grade}
    if default_grade:
        b.detection["warnings"] = b.detection["warnings"] + [
            f"Rows without a grade were assigned the batch default grade '{default_grade}'"]
    keywords = {k: c.keywords for k, c in rules.categories.items()}
    products: dict[str, PIProduct] = {p.product_key: p for p in db.scalars(select(PIProduct)).all()}
    serials: dict[str, int] = defaultdict(int)
    for r in res.rows:
        s = r.mapped.get("serial")
        if s not in (None, ""):
            serials[str(s).strip().upper()] += 1
    pending_exc: list[tuple[PIAsset, list[Flag]]] = []
    for r in res.rows:
        ident = identify(r.mapped, keywords, default_grade)
        flags = list(ident.flags)
        if res.qty_column:
            qty, qerr = parse_quantity(r.mapped.get("quantity"))
            if qerr:
                flags.append(Flag("missing_quantity", f"Quantity {qerr}"))
        else:
            qty = 1
        serial = str(r.mapped["serial"]).strip() if r.mapped.get("serial") not in (None, "") else None
        if serial and serials[serial.upper()] > 1:
            flags.append(Flag("duplicate_serial", f"Serial {serial} appears {serials[serial.upper()]} times"))
        lot_threshold = rules.category(ident.category).large_lot_threshold
        if qty and lot_threshold and qty >= lot_threshold:
            flags.append(Flag("large_lot", f"{qty} units on one line"))
        product = None
        if ident.product_key:
            product = products.get(ident.product_key)
            if product is None:
                product = PIProduct(product_key=ident.product_key, category=ident.category, label=ident.label[:300],
                                    spec=ident.spec)
                db.add(product)
                db.flush()
                products[ident.product_key] = product
        original = " | ".join(str(r.mapped[k]) for k in ("make", "model", "cpu", "description", "generation", "ram",
                                                         "storage") if r.mapped.get(k) not in (None, ""))
        a = PIAsset(batch_id=b.id, sheet=res.sheet, row_number=r.row_number, raw=r.raw, serial=serial, quantity=qty,
                    category=ident.category, grade=ident.grade, original_spec=original[:4000],
                    normalized={**ident.spec, "label": ident.label, "risk_flags": ident.risk_flags},
                    identify_confidence=ident.confidence, product_id=product.id if product else None,
                    status="unpriced" if product else "manual_required")
        db.add(a)
        pending_exc.append((a, flags))
    db.flush()
    b.detection = {**b.detection, "identified_at": now().isoformat()}
    for a, flags in pending_exc:
        seen = set()
        for f in flags:
            if f.code in seen:
                continue
            seen.add(f.code)
            db.add(_exc_row(b.id, a.id, a.product_id, f))


# --------------------------------------------------------------------------- pricing

def _obs_for(db: Session, product_ids: list[int]) -> dict[int, list[tuple[PIObservation, PISource | None]]]:
    out: dict[int, list] = defaultdict(list)
    if not product_ids:
        return out
    q = select(PIObservation, PISource).outerjoin(PISource, PISource.id == PIObservation.source_id).where(
        PIObservation.product_id.in_(product_ids), PIObservation.status == "verified")
    for o, s in db.execute(q).all():
        out[o.product_id].append((o, s))
    return out


def price_batch(db: Session, b: PIBatch, user: User | None, as_of: datetime | None = None,
                rules_version_id: int | None = None) -> dict:
    from .accuracy import category_mape
    if rules_version_id:
        v = db.get(PIRuleVersion, rules_version_id)
        if v is None:
            raise ServiceError("Rule version not found")
        rules = Rules.model_validate(v.rules)
    else:
        rules, v = active_rules(db)
    as_of = _aware(as_of) if as_of else now()
    assets = db.scalars(select(PIAsset).where(PIAsset.batch_id == b.id)).all()
    groups: dict[tuple[int, str], list[PIAsset]] = defaultdict(list)
    for a in assets:
        if a.product_id is not None:
            groups[(a.product_id, a.grade or "")].append(a)
    open_exc = defaultdict(int)
    for asset_id, sev in db.execute(select(PIException.asset_id, PIException.severity).where(
            PIException.batch_id == b.id, PIException.resolved.is_(False))).all():
        if sev == "high" and asset_id:
            open_exc[asset_id] += 1
    obs_map = _obs_for(db, sorted({pid for pid, _ in groups}))
    products = {p.id: p for p in db.scalars(select(PIProduct).where(PIProduct.id.in_([pid for pid, _ in groups]))).all()} \
        if groups else {}
    latest_job_id = db.scalar(select(PIResearchJob.id).where(PIResearchJob.batch_id == b.id).order_by(PIResearchJob.id.desc()).limit(1))
    mape_cache: dict[str, float | None] = {}
    summary = defaultdict(int)
    for (pid, grade), members in groups.items():
        product = products[pid]
        qty = sum(a.quantity or 0 for a in members)
        risk = sorted({f for a in members for f in (a.normalized or {}).get("risk_flags", [])})
        conf_rank = {"high": 2, "medium": 1, "low": 0}
        ident_conf = min((a.identify_confidence for a in members), key=lambda c: conf_rank.get(c, 0))
        if product.category not in mape_cache:
            mape_cache[product.category] = category_mape(db, product.category)
        variant = None
        if product.category == "server_ram" and product.spec.get("ddr"):
            variant = "server_ram_" + product.spec["ddr"].lower()
        elif product.category == "server_cpu":
            variant = "server_cpu_epyc" if product.spec.get("vendor") == "AMD" else "server_cpu_xeon"
        group = engine.Group(category=product.category, grade=grade or None, quantity=qty, risk_flags=risk, policy_variant=variant,
                             identify_confidence=ident_conf,
                             high_severity_flags=max((open_exc.get(a.id, 0) for a in members), default=0),
                             category_mape=mape_cache[product.category])
        obs = []
        for o, s in obs_map.get(pid, []):
            if o.price_type == "historical_valuation" or (o.attributes or {}).get("grade"):
                g = (o.attributes or {}).get("grade")
                if g and grade and g != grade:
                    continue
            obs.append(engine.Obs(id=o.id, price=o.price, currency=o.currency, tax_basis=o.tax_basis,
                                  price_type=o.price_type, match_quality=o.match_quality,
                                  observed_at=_aware(o.observed_at), source_key=(s.domain if s else o.provider),
                                  reliability=(s.reliability if s else (1.0 if o.provider == "reference_pack" else 0.5)),
                                  status=o.status, url=o.url, title=o.title, condition=o.condition,
                                  research_mode=("cached_search" if (o.attributes or {}).get("research_mode") == "live_search_confirmed"
                                                 and o.retrieved_at and (o.research_job_id != latest_job_id or as_of - _aware(o.retrieved_at) > timedelta(minutes=5))
                                                 else (o.attributes or {}).get("research_mode")),
                                  source_timestamp=(o.attributes or {}).get("source_timestamp"),
                                  evidence_grade=(o.attributes or {}).get("grade")))
        h = engine.input_hash(group, obs, rules, as_of)
        est = db.scalar(select(PIEstimate).where(PIEstimate.batch_id == b.id, PIEstimate.product_id == pid,
                                                 PIEstimate.grade == grade, PIEstimate.input_hash == h))
        if est is None:
            res = engine.price_group(group, obs, rules, as_of)
            db.execute(update(PIEstimate).where(PIEstimate.batch_id == b.id, PIEstimate.product_id == pid,
                                                PIEstimate.grade == grade).values(is_current=False))
            est = PIEstimate(batch_id=b.id, product_id=pid, grade=grade, rule_version_id=v.id,
                             engine_version=engine.ENGINE_VERSION, as_of=as_of, group_quantity=qty,
                             status=res["status"], benchmark=_d(res["benchmark"]),
                             recommended_unit=_d(res["recommended_unit"]), opening_unit=_d(res["opening_unit"]),
                             max_unit=_d(res["max_unit"]), resale_unit=_d(res["resale_unit"]),
                             margin_pct=_d(res["margin_pct"]), confidence=res["confidence"],
                             confidence_score=res["confidence_score"], breakdown=res,
                             observation_ids=res["observation_ids"], input_hash=h, is_current=True,
                             created_by=user.id if user else None)
            db.add(est)
            db.flush()
        else:
            db.execute(update(PIEstimate).where(PIEstimate.batch_id == b.id, PIEstimate.product_id == pid,
                                                PIEstimate.grade == grade, PIEstimate.id != est.id).values(is_current=False))
            est.is_current = True
        res = est.breakdown
        for code in res.get("flags", []):
            if code in EXCEPTIONS:  # product-group level: one exception per product, not per serial
                _ensure_exc(db, b.id, None, pid, Flag(code, res.get("message") if code == "no_market_evidence"
                                                      else _flag_message(code, res)))
        for a in members:
            new_price = est.recommended_unit
            changed = a.calculated_price != new_price
            a.estimate_id, a.calculated_price = est.id, new_price
            if a.status == "approved" and not changed:
                summary["approved"] += 1
                continue
            if a.override_price is not None:
                a.status = "review"
            elif est.status == "manual_required":
                a.status = "manual_required"
            elif est.status == "provisional":
                a.status = "provisional"
            elif est.confidence == "Low" or open_exc.get(a.id):
                a.status = "review"
            else:
                a.status = "auto_priced"
            summary[a.status] += 1
    for a in assets:
        if a.product_id is None:
            a.status = "manual_required"
            summary["manual_required"] += 1
    b.status, b.rule_version_id, b.priced_at = "priced", v.id, now()
    audit.record(db, user, "pi.batch.priced", "pi_batch", b.id, rule_version=v.version, groups=len(groups),
                 **{f"n_{k}": n for k, n in summary.items()})
    return {"groups": len(groups), "rule_version": v.version, "statuses": dict(summary)}


def _flag_message(code: str, res: dict) -> str:
    if code == "extreme_price_variation":
        return f"IQR/median {res.get('dispersion')}"
    if code == "stale_evidence":
        return "Only historical valuation evidence is available"
    if code == "large_lot":
        return f"{res.get('group_quantity')} units in this product group"
    if code == "recommended_exceeds_margin_cap":
        return f"Recommended {res.get('recommended_unit')} exceeds margin-constrained maximum {res.get('max_unit')}"
    if code == "conversion_not_configured":
        return "Available evidence types have no configured buy-price conversion"
    return code.replace("_", " ")


def _ensure_exc(db: Session, batch_id: int, asset_id: int | None, product_id: int | None, f: Flag) -> None:
    cond = PIException.asset_id.is_(None) if asset_id is None else PIException.asset_id == asset_id
    pcond = PIException.product_id.is_(None) if product_id is None else PIException.product_id == product_id
    if db.scalar(select(PIException.id).where(PIException.batch_id == batch_id, cond, pcond,
                                              PIException.code == f.code)) is None:
        db.add(_exc_row(batch_id, asset_id, product_id, f))


def _d(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


# --------------------------------------------------------------------------- review actions

def override_prices(db: Session, user: User, asset_ids: list[int], price: Decimal | None, reason: str) -> int:
    if not reason or len(reason.strip()) < 5:
        raise ServiceError("A reason (at least 5 characters) is required for a price override")
    if price is not None and price < 0:
        raise ServiceError("Price cannot be negative")
    n = 0
    for a in db.scalars(select(PIAsset).where(PIAsset.id.in_(asset_ids))).all():
        db.add(PIOverride(asset_id=a.id, calculated_price=a.calculated_price, previous_price=a.final_price,
                          new_price=price, reason=reason.strip(), user_id=user.id))
        a.override_price = price
        a.override_reason = reason.strip() if price is not None else None
        a.status = "review" if a.final_price is not None else "manual_required"
        a.approved_by = a.approved_at = None
        n += 1
    audit.record(db, user, "pi.price.override", "pi_asset", None, assets=asset_ids[:200], count=n,
                 price=money(price), reason=reason)
    return n


def approve_assets(db: Session, user: User, asset_ids: list[int]) -> dict:
    ok, skipped = 0, 0
    for a in db.scalars(select(PIAsset).where(PIAsset.id.in_(asset_ids))).all():
        if a.final_price is None:
            skipped += 1
            continue
        a.status, a.approved_by, a.approved_at = "approved", user.id, now()
        ok += 1
    audit.record(db, user, "pi.price.approved", "pi_asset", None, count=ok, skipped=skipped, assets=asset_ids[:200])
    return {"approved": ok, "skipped_unpriced": skipped}


def resolve_exceptions(db: Session, user: User, ids: list[int], note: str | None) -> int:
    n = 0
    for e in db.scalars(select(PIException).where(PIException.id.in_(ids))).all():
        e.resolved, e.resolution_note, e.resolved_by, e.resolved_at = True, note, user.id, now()
        n += 1
    audit.record(db, user, "pi.exception.resolved", "pi_exception", None, ids=ids[:200], note=note)
    return n


def reidentify_asset(db: Session, user: User, a: PIAsset, fields: dict, method: str, apply_to_same_spec: bool) -> list[int]:
    """Correct an asset's identification (manual entry or an accepted AI suggestion) and regroup it.

    The original cells (``raw``) are never changed; corrections are layered over the mapped values.
    """
    b = db.get(PIBatch, a.batch_id)
    rules, _ = active_rules(db)
    keywords = {k: c.keywords for k, c in rules.categories.items()}
    targets = [a]
    if apply_to_same_spec and a.original_spec:
        targets = db.scalars(select(PIAsset).where(PIAsset.batch_id == a.batch_id,
                                                   PIAsset.original_spec == a.original_spec)).all()
    inv = {v: k for k, v in (b.column_map or {}).items()}
    done = []
    for t in targets:
        if t.status == "approved":
            continue
        mapped = {inv[h]: v for h, v in (t.raw or {}).items() if h in inv}
        corrections = dict((t.normalized or {}).get("corrections") or {})
        corrections.update({k: v for k, v in fields.items() if v not in (None, "")})
        mapped.update(corrections)
        ident = identify(mapped, keywords, (b.detection or {}).get("default_grade"))
        product = None
        if ident.product_key:
            product = db.scalar(select(PIProduct).where(PIProduct.product_key == ident.product_key))
            if product is None:
                product = PIProduct(product_key=ident.product_key, category=ident.category, label=ident.label[:300],
                                    spec=ident.spec)
                db.add(product)
                db.flush()
        t.category, t.grade, t.product_id = ident.category, ident.grade, product.id if product else None
        t.normalized = {**ident.spec, "label": ident.label, "risk_flags": ident.risk_flags, "corrections": corrections}
        t.identify_confidence, t.identify_method = ident.confidence, method
        t.estimate_id, t.calculated_price = None, None
        t.status = "unpriced" if product else "manual_required"
        for e in db.scalars(select(PIException).where(PIException.asset_id == t.id, PIException.resolved.is_(False))).all():
            if e.code not in {f.code for f in ident.flags} and e.code not in ("duplicate_serial", "missing_quantity", "large_lot"):
                e.resolved, e.resolved_by, e.resolved_at = True, user.id, now()
                e.resolution_note = f"Resolved by re-identification ({method})"
        if method == "ai_suggested":
            _ensure_exc(db, b.id, t.id, t.product_id, Flag("ai_identification_used", "Identification accepted from an AI suggestion"))
        done.append(t.id)
    audit.record(db, user, "pi.asset.reidentified", "pi_asset", a.id, method=method, fields=fields, assets=done[:200])
    return done


# --------------------------------------------------------------------------- quotations

def asset_description(a: PIAsset) -> str:
    return (a.normalized or {}).get("label") or a.original_spec or f"Row {a.row_number}"


def create_quotation(db: Session, user: User, b: PIBatch, *, vendor: str | None, notes: str | None,
                     valid_days: int = 7, include_unapproved: bool = False) -> tuple[PIQuotation, bool]:
    assets = db.scalars(select(PIAsset).where(PIAsset.batch_id == b.id).order_by(PIAsset.sheet, PIAsset.row_number)).all()
    eligible = [a for a in assets if a.final_price is not None and a.quantity and
                (a.status == "approved" or include_unapproved)]
    if not eligible:
        raise ServiceError("No approved, priced lines to quote. Approve prices first or include unapproved lines.")
    sig = hashlib.sha256(("|".join(f"{a.id}:{a.final_price}:{a.quantity}" for a in eligible) +
                          f"|{vendor or b.vendor or ''}|{include_unapproved}").encode()).hexdigest()
    existing = db.scalar(select(PIQuotation).where(PIQuotation.idempotency_key == sig))
    if existing:
        return existing, False
    n = (db.scalar(select(func.count(PIQuotation.id)).where(PIQuotation.batch_id == b.id)) or 0) + 1
    ref = f"CQ-{now():%Y%m%d}-{b.id:04d}-{n:02d}"
    total = sum((a.final_price * a.quantity for a in eligible), Decimal("0"))
    db.execute(update(PIQuotation).where(PIQuotation.batch_id == b.id, PIQuotation.status != "superseded")
               .values(status="superseded"))
    q = PIQuotation(quote_ref=ref, batch_id=b.id, vendor=vendor or b.vendor, status="draft", idempotency_key=sig,
                    rule_version_id=b.rule_version_id, lines_count=len(eligible),
                    units=sum(a.quantity for a in eligible), total=total, excluded_lines=len(assets) - len(eligible),
                    notes=notes, valid_until=date.today() + timedelta(days=valid_days), created_by=user.id)
    db.add(q)
    db.flush()
    for a in eligible:
        basis = "override" if a.override_price is not None else ("provisional" if a.status == "provisional" else "calculated")
        db.add(PIQuotationLine(quotation_id=q.id, asset_id=a.id, product_id=a.product_id,
                               description=asset_description(a)[:2000], quantity=a.quantity, unit_price=a.final_price,
                               line_total=a.final_price * a.quantity, price_basis=basis))
    audit.record(db, user, "pi.quotation.created", "pi_quotation", q.id, ref=ref, total=money(total),
                 lines=len(eligible))
    return q, True


# --------------------------------------------------------------------------- serialisers

def batch_out(db: Session, b: PIBatch) -> dict:
    rows = db.execute(select(PIAsset.status, func.count(), func.coalesce(func.sum(PIAsset.quantity), 0))
                      .where(PIAsset.batch_id == b.id).group_by(PIAsset.status)).all()
    by_status = {s: {"lines": n, "units": int(u)} for s, n, u in rows}
    value = Decimal("0")
    for qty, calc, ov in db.execute(select(PIAsset.quantity, PIAsset.calculated_price, PIAsset.override_price)
                                    .where(PIAsset.batch_id == b.id)).all():
        p = ov if ov is not None else calc
        if p is not None and qty:
            value += Decimal(p) * qty
    job = db.scalar(select(PIResearchJob).where(PIResearchJob.batch_id == b.id).order_by(PIResearchJob.id.desc()).limit(1))
    return {"id": b.id, "name": b.name, "vendor": b.vendor, "original_filename": b.original_filename, "layout": b.layout,
            "sheet_name": b.sheet_name, "header_row": b.header_row, "column_map": b.column_map,
            "price_column": b.price_column, "qty_column": b.qty_column, "detection": b.detection, "status": b.status,
            "rule_version_id": b.rule_version_id, "priced_at": b.priced_at.isoformat() if b.priced_at else None,
            "created_at": b.created_at.isoformat(), "lines": sum(v["lines"] for v in by_status.values()),
            "units": sum(v["units"] for v in by_status.values()), "by_status": by_status, "estimated_value": money(value),
            "products": db.scalar(select(func.count(func.distinct(PIAsset.product_id))).where(PIAsset.batch_id == b.id)) or 0,
            "open_exceptions": db.scalar(select(func.count(PIException.id)).where(PIException.batch_id == b.id,
                                                                                  PIException.resolved.is_(False))) or 0,
            "latest_job": job_out(job) if job else None}


def job_out(j: PIResearchJob) -> dict:
    return {"id": j.id, "batch_id": j.batch_id, "provider": j.provider, "status": j.status, "total": j.total,
            "done": j.done, "failed": j.failed, "cached": j.cached, "observations_found": j.observations_found,
            "cancel_requested": j.cancel_requested, "error": j.error, "workflow": j.params or {},
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None, "created_at": j.created_at.isoformat()}


def asset_out(a: PIAsset, est: PIEstimate | None = None) -> dict:
    final = a.final_price
    return {"id": a.id, "batch_id": a.batch_id, "sheet": a.sheet, "row_number": a.row_number, "serial": a.serial,
            "quantity": a.quantity, "category": a.category, "grade": a.grade, "original_spec": a.original_spec,
            "label": (a.normalized or {}).get("label"), "normalized": a.normalized,
            "identify_confidence": a.identify_confidence, "product_id": a.product_id, "status": a.status,
            "calculated_price": money(a.calculated_price), "override_price": money(a.override_price),
            "override_reason": a.override_reason, "final_price": money(final),
            "total_value": money(final * a.quantity) if final is not None and a.quantity else None,
            "benchmark": money(est.benchmark) if est else None, "confidence": est.confidence if est else None,
            "estimate_status": est.status if est else None, "estimate_id": a.estimate_id,
            "sources": len(est.observation_ids) if est else 0,
            "research_methods": (est.breakdown or {}).get("research_methods", []) if est else [],
            "pricing_date": est.as_of.isoformat() if est else None,
            "evidence_urls": [o["url"] for o in (est.breakdown or {}).get("observations", []) if o.get("included") and o.get("url")] if est else [],
            "approved_at": a.approved_at.isoformat() if a.approved_at else None}


def observation_out(o: PIObservation, s: PISource | None = None) -> dict:
    return {"id": o.id, "product_id": o.product_id, "provider": o.provider, "price_type": o.price_type,
            "match_quality": o.match_quality, "title": o.title, "price": money(o.price), "currency": o.currency,
            "tax_basis": o.tax_basis, "condition": o.condition, "seller": o.seller, "url": o.url,
            "observed_at": o.observed_at.isoformat(), "retrieved_at": o.retrieved_at.isoformat() if o.retrieved_at else None,
            "snippet": o.snippet, "status": o.status, "status_reason": o.status_reason, "attributes": o.attributes,
            "source": {"id": s.id, "name": s.name, "domain": s.domain, "reliability": s.reliability} if s else None}


def estimate_out(e: PIEstimate) -> dict:
    return {"id": e.id, "batch_id": e.batch_id, "product_id": e.product_id, "grade": e.grade, "status": e.status,
            "benchmark": money(e.benchmark), "recommended_unit": money(e.recommended_unit),
            "opening_unit": money(e.opening_unit), "max_unit": money(e.max_unit), "resale_unit": money(e.resale_unit),
            "margin_pct": money(e.margin_pct), "confidence": e.confidence, "confidence_score": e.confidence_score,
            "group_quantity": e.group_quantity, "as_of": e.as_of.isoformat(), "rule_version_id": e.rule_version_id,
            "engine_version": e.engine_version, "is_current": e.is_current, "created_at": e.created_at.isoformat(),
            "input_hash": e.input_hash}
