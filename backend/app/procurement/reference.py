"""Reference packs: historical completed valuation workbooks (for example B001 / B002).

A completed workbook carries Casterly's own dated buy estimates in its ``Market Unit Price``
column. Importing it as a reference pack stores, per normalised product and grade, one
``historical_valuation`` observation dated at the workbook's reference date. These are labelled
historical everywhere, are only used when no current evidence exists, and make the resulting
estimate *provisional*.

A ``Rate Benchmarks`` sheet, when present, holds the earlier analyst's observed retail asking
prices and source URLs. They are imported as **candidate** ``refurb_retail`` observations (not
verified) because they were not verified by this system.
"""
from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..importing.files import UploadRejected, validate_and_store, stored_path
from ..models import User
from .excel_import import ImportError_, norm_header, read_workbook
from .identify import identify
from .models import PIObservation, PIProduct
from .research import dedup_key
from .service import ServiceError, active_rules

DATE_PATTERNS = ("%d %b %Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y")


def _find_reference_date(content: bytes) -> date | None:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i > 30:
                    break
                for j, v in enumerate(row[:-1]):
                    if isinstance(v, str) and norm_header(v) in ("reference date", "valuation date", "as of"):
                        nxt = row[j + 1]
                        if isinstance(nxt, datetime):
                            return nxt.date()
                        if isinstance(nxt, date):
                            return nxt
                        if isinstance(nxt, str):
                            for p in DATE_PATTERNS:
                                try:
                                    return datetime.strptime(nxt.strip(), p).date()
                                except ValueError:
                                    continue
    finally:
        wb.close()
    return None


def _money(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).replace(",", "").replace("₹", "").strip())
    except InvalidOperation:
        return None
    return d if d > 0 else None


def import_reference_pack(db: Session, user: User | None, *, filename: str, content: bytes,
                          reference_date: date | None = None) -> dict:
    try:
        info = validate_and_store(filename, content)
    except UploadRejected as e:
        raise ServiceError(str(e)) from e
    ref_date = reference_date or _find_reference_date(content)
    if ref_date is None:
        raise ServiceError("Reference date not found in the workbook; supply reference_date")
    rules, _ = active_rules(db)
    try:
        res = read_workbook(stored_path(info["stored_name"]), qty_columns=rules.quantity_columns, max_rows=50000)
    except ImportError_ as e:
        raise ServiceError(str(e)) from e
    if not res.price_column:
        raise ServiceError("The workbook has no 'Market Unit Price' column; it is not a completed valuation")
    observed = datetime.combine(ref_date, time(12, 0), tzinfo=timezone.utc)
    keywords = {k: c.keywords for k, c in rules.categories.items()}
    products = {p.product_key: p for p in db.scalars(select(PIProduct)).all()}
    groups: dict[tuple[str, str], dict] = {}
    conflicts = 0
    skipped = 0
    for r in res.rows:
        price = _money(r.raw.get(res.price_column))
        ident = identify(r.mapped, keywords)
        if price is None or not ident.product_key:
            skipped += 1
            continue
        key = (ident.product_key, ident.grade or "")
        g = groups.setdefault(key, {"ident": ident, "prices": defaultdict(int), "rows": 0})
        g["prices"][price] += 1
        g["rows"] += 1
    created = 0
    for (pkey, grade), g in groups.items():
        ident = g["ident"]
        p = products.get(pkey)
        if p is None:
            p = PIProduct(product_key=pkey, category=ident.category, label=ident.label[:300], spec=ident.spec)
            db.add(p)
            db.flush()
            products[pkey] = p
        if len(g["prices"]) > 1:
            conflicts += 1
        for price, n in sorted(g["prices"].items()):
            key = dedup_key(f"reference:{info['sha256']}:{grade}", price, observed, "reference_pack")
            existing = db.scalar(select(PIObservation).where(PIObservation.product_id == p.id, PIObservation.dedup_key == key))
            if existing:
                existing.attributes = {**(existing.attributes or {}), "identity_version": "pi-identity-1.1"}
                continue
            db.add(PIObservation(
                product_id=p.id, provider="reference_pack", price_type="historical_valuation", match_quality="identical",
                title=f"Casterly historical valuation · {filename}", price=price, currency="INR", tax_basis="exclusive",
                condition=f"Grade {grade}" if grade else None, seller="Casterly (historical estimate)", url=None,
                observed_at=observed, snippet=None, status="verified",
                status_reason=f"Casterly's own dated estimate ({ref_date:%d %b %Y}); not a live market price",
                dedup_key=key, attributes={"identity_version": "pi-identity-1.1", "grade": grade or None, "workbook": filename, "sha256": info["sha256"],
                                           "rows": n, "reference_date": ref_date.isoformat()},
                created_by=user.id if user else None))
            created += 1
    bench = _rate_benchmarks(db, user, content, filename, info["sha256"], observed, products)
    audit.record(db, user, "pi.reference.imported", None, None, filename=filename, sha256=info["sha256"],
                 reference_date=ref_date.isoformat(), observations=created, benchmarks=bench, groups=len(groups))
    return {"reference_date": ref_date.isoformat(), "rows": len(res.rows), "rows_skipped": skipped,
            "product_groups": len(groups), "historical_observations": created, "price_conflicts": conflicts,
            "benchmark_candidates": bench, "layout": res.layout}


def _rate_benchmarks(db: Session, user, content: bytes, filename: str, sha: str, observed: datetime,
                     products: dict[str, PIProduct]) -> int:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = next((w for w in wb.worksheets if norm_header(w.title) == "rate benchmarks"), None)
        if ws is None:
            return 0
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        return 0
    head = [norm_header(h) for h in rows[0]]

    def col(name):
        return head.index(name) if name in head else None

    ci, ca, cu = col("item class / cpu model"), col("observed retail ask ()"), col("source url")
    if ca is None:
        ca = next((i for i, h in enumerate(head) if h.startswith("observed retail ask")), None)
    if ci is None or ca is None:
        return 0
    n = 0
    for r in rows[1:]:
        item, ask = r[ci], _money(r[ca])
        url = r[cu] if cu is not None else None
        if not item or ask is None:
            continue
        targets = _benchmark_targets(str(item), products)
        for p in targets:
            key = dedup_key(url or f"benchmark:{sha}:{item}", ask, observed, "reference_pack")
            existing = db.scalar(select(PIObservation).where(PIObservation.product_id == p.id, PIObservation.dedup_key == key))
            if existing:
                existing.attributes = {**(existing.attributes or {}), "identity_version": "pi-identity-1.1"}
                continue
            db.add(PIObservation(
                product_id=p.id, provider="reference_pack", price_type="refurb_retail", match_quality="comparable",
                title=f"Archived retail ask for '{item}' ({filename})", price=ask, currency="INR", tax_basis="unknown",
                seller=None, url=str(url)[:2000] if url else None, observed_at=observed, status="candidate",
                status_reason="Archived from a prior analyst's Rate Benchmarks sheet; verify before use",
                dedup_key=key, attributes={"benchmark_class": str(item), "workbook": filename},
                created_by=user.id if user else None))
            n += 1
    return n


def _benchmark_targets(item: str, products: dict[str, PIProduct]) -> list[PIProduct]:
    up = item.upper()
    m = re.match(r"(DDR\d)\s+(\d+)GB\s+(\d{4})", up)
    if m:
        ddr, cap, speed = m.groups()
        prefix = f"server_ram|{ddr}|{cap}gb|{speed}|"
        return [p for k, p in products.items() if k.startswith(prefix)]
    key = "server_cpu|" + re.sub(r"\s+", "-", re.sub(r"\bV(\d)\b", r"v\1", item.strip()).lower())
    key = re.sub(r"(e5-\d{4})v(\d)", r"\1-v\2", key)
    return [p for k, p in products.items() if k == key]
