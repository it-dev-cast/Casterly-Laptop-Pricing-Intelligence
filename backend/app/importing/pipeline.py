"""Staging, review, correction, duplicate detection and commit of uploaded rows."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, specs
from ..models import FieldCorrection, StagingRow, UploadBatch, User
from ..pricing.config import PricingConfig
from ..services.records import MODEL_FOR, build_record
from .fields import field_map
from .files import read_sheets
from .normalize import jsonable, normalize_record

COMMITTABLE = ("valid", "warning")


def _effective_values(row: StagingRow) -> dict:
    vals = dict(row.mapped_raw)
    for k, v in (row.corrections or {}).items():
        vals[k] = v
    return vals


def _signature(record_type: str, n: dict) -> str:
    keys = [k for k in field_map(record_type) if k not in ("description",)]
    return json.dumps({k: n.get(k) for k in keys}, sort_keys=True, default=str)


def _validate(row: StagingRow, batch: UploadBatch, cfg: PricingConfig) -> None:
    normalized, errors, warnings = normalize_record(batch.record_type, _effective_values(row), cfg,
                                                    batch.import_defaults or {})
    extra = row.raw.get("__extra_cells__")
    if extra:
        warnings.append({"field": None, "message": f"Row has {len(extra)} value(s) beyond the header columns; ignored"})
    row.normalized = jsonable(normalized)
    row.errors = errors
    row.warnings = warnings


def _status(row: StagingRow) -> str:
    if row.status in ("skipped", "committed"):
        return row.status
    if row.errors:
        return "invalid"
    if row.suggestions:
        return "needs_review"
    if row.duplicate_of and not row.keep_duplicate:
        return "duplicate"
    return "warning" if row.warnings else "valid"


def _db_duplicate(db: Session, record_type: str, n: dict, is_synthetic: bool) -> str | None:
    Model = MODEL_FOR[record_type]
    mk = specs.model_key(n.get("brand"), n.get("model"))
    q = select(Model.id).where(Model.is_synthetic.is_(is_synthetic))
    checks = []
    if record_type == "inventory":
        if n.get("item_ref"):
            checks.append(q.where(Model.item_ref == n["item_ref"]))
    else:
        if n.get("source_url"):
            checks.append(q.where(Model.source_url == n["source_url"]))
        if n.get("source_record_id"):
            cq = q.where(Model.source_record_id == n["source_record_id"])
            if record_type == "transaction":
                cq = cq.where(Model.kind == n.get("kind"))
            elif n.get("seller"):
                cq = cq.where(Model.seller == n["seller"])
            checks.append(cq)
        date_col = {"listing": "listing_date", "quote": "quote_date", "transaction": "transaction_date"}[record_type]
        if n.get("price") is not None and n.get(date_col):
            dv = n[date_col]
            dv = date.fromisoformat(str(dv)[:10]) if not isinstance(dv, date) else dv
            cq = q.where(Model.model_key == mk, Model.cpu_key == specs.cpu_key(n.get("cpu")),
                         Model.price == n["price"], getattr(Model, date_col) == dv,
                         Model.ram_gb == n.get("ram_gb"), Model.storage_gb == n.get("storage_gb"),
                         Model.condition_grade == n.get("condition_grade"))
            party = n.get("seller") or n.get("counterparty")
            if party:
                cq = cq.where((Model.seller == party) if record_type != "transaction" else (Model.counterparty == party))
            checks.append(cq)
    for cq in checks:
        hit = db.scalar(cq.limit(1))
        if hit:
            return f"{record_type}:{hit}"
    return None


def detect_duplicates(db: Session, batch: UploadBatch) -> None:
    seen: dict[str, StagingRow] = {}
    for row in sorted(batch.rows, key=lambda r: (r.sheet or "", r.row_number)):
        if row.status in ("committed",):
            continue
        row.duplicate_of = None
        if row.errors:
            continue
        sig = _signature(batch.record_type, row.normalized)
        if sig in seen and seen[sig].status != "skipped":
            first = seen[sig]
            row.duplicate_of = f"row:{first.sheet}:{first.row_number}"
        else:
            seen.setdefault(sig, row)
            row.duplicate_of = _db_duplicate(db, batch.record_type, row.normalized, batch.is_synthetic)
    for row in batch.rows:
        row.status = _status(row)


def stage(db: Session, batch: UploadBatch, sheets: list[str] | None, mapping: dict[str, str],
          defaults: dict, cfg: PricingConfig) -> None:
    fmap = field_map(batch.record_type)
    unknown = [k for k in mapping if k not in fmap]
    if unknown:
        raise ValueError(f"Unknown fields in mapping: {unknown}")
    data = read_sheets(batch.stored_name, batch.file_kind, sheets)
    for sd in data:
        missing_cols = [c for c in mapping.values() if c and c not in sd.headers]
        if missing_cols:
            raise ValueError(f"Sheet '{sd.name}' has no column(s) {missing_cols}")
    batch.rows.clear()
    db.flush()
    for sd in data:
        for rownum, raw in sd.rows:
            mapped = {k: raw.get(col) for k, col in mapping.items() if col}
            row = StagingRow(sheet=sd.name, row_number=rownum, raw=raw, mapped_raw=mapped, normalized={},
                             corrections={}, errors=[], warnings=[], status="pending")
            batch.rows.append(row)
            _validate(row, batch, cfg)
    batch.mapping = mapping
    batch.selected_sheets = [sd.name for sd in data]
    batch.import_defaults = defaults
    batch.status = "staged"
    db.flush()
    detect_duplicates(db, batch)
    batch.summary = summarize(batch)


def summarize(batch: UploadBatch) -> dict:
    counts: dict[str, int] = {}
    for r in batch.rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {"total": len(batch.rows), "by_status": counts}


def correct_row(db: Session, row: StagingRow, changes: dict, user: User, cfg: PricingConfig,
                reason: str | None = None, source: str = "user") -> None:
    batch = row.batch
    if row.status == "committed":
        raise ValueError("Row already committed")
    fmap = field_map(batch.record_type)
    corrections = dict(row.corrections or {})
    for field, value in changes.items():
        if field not in fmap:
            raise ValueError(f"Unknown field '{field}'")
        previous = _effective_values(row).get(field)
        if value is None:
            corrections.pop(field, None)
        else:
            corrections[field] = value
        db.add(FieldCorrection(record_type=batch.record_type, staging_row_id=row.id, field=field,
                               original_value=_s(row.mapped_raw.get(field)), previous_value=_s(previous),
                               new_value=_s(value), source=source, reason=reason, user_id=user.id))
    row.corrections = corrections
    _validate(row, batch, cfg)
    detect_duplicates(db, batch)
    batch.summary = summarize(batch)
    audit.record(db, user, "import.row_corrected", "staging_row", row.id, fields=list(changes), source=source)


def _s(v):
    return None if v is None else str(v)


def commit(db: Session, batch: UploadBatch, user: User) -> dict:
    created, skipped = 0, 0
    for row in sorted(batch.rows, key=lambda r: (r.sheet or "", r.row_number)):
        eligible = row.status in COMMITTABLE or (row.status == "duplicate" and row.keep_duplicate)
        if not eligible:
            if row.status != "committed":
                skipped += 1
            continue
        doc = f"Upload #{batch.id} '{batch.original_filename}'" + \
              (f" sheet '{row.sheet}'" if batch.file_kind == "xlsx" else "") + f" row {row.row_number}"
        rec = build_record(db, batch.record_type, row.normalized, source_type="upload", source_document=doc,
                           user=user, is_synthetic=batch.is_synthetic, raw_values=row.mapped_raw,
                           corrections=row.corrections or None, batch_id=batch.id, staging_row_id=row.id)
        row.committed_record_id = rec.id
        row.status = "committed"
        created += 1
    remaining = sum(1 for r in batch.rows if r.status not in ("committed", "skipped"))
    batch.status = "committed" if remaining == 0 else "partially_committed"
    batch.committed_at = datetime.now(timezone.utc)
    batch.summary = summarize(batch)
    audit.record(db, user, "import.committed", "upload_batch", batch.id, record_type=batch.record_type,
                 created=created, not_committed=skipped)
    return {"created": created, "not_committed": skipped, "batch_status": batch.status}


def error_rows(batch: UploadBatch) -> list[StagingRow]:
    return [r for r in sorted(batch.rows, key=lambda r: (r.sheet or "", r.row_number))
            if r.status in ("invalid", "duplicate", "needs_review") or r.warnings]


def _error_table(batch: UploadBatch) -> tuple[list[str], list[list]]:
    rows = error_rows(batch)
    headers_raw: list[str] = []
    for r in rows:
        for h in r.raw:
            if h != "__extra_cells__" and h not in headers_raw:
                headers_raw.append(h)
    header = ["Sheet", "Row", "Status", "Errors", "Warnings", "Duplicate of"] + [f"[original] {h}" for h in headers_raw]
    table = []
    for r in rows:
        table.append([r.sheet, r.row_number, r.status,
                      "; ".join(e["message"] for e in r.errors),
                      "; ".join(w["message"] for w in r.warnings),
                      r.duplicate_of or ""] + [_safe_cell(r.raw.get(h)) for h in headers_raw])
    return header, table


def _safe_cell(v):
    """Neutralise spreadsheet formula injection in exported text."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def export_errors(batch: UploadBatch, fmt: str) -> bytes:
    header, table = _error_table(batch)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        for row in table:
            w.writerow([_safe_cell(c) if isinstance(c, str) else c for c in row])
        return buf.getvalue().encode("utf-8-sig")
    wb = Workbook()
    ws = wb.active
    ws.title = "Import issues"
    ws.append(header)
    for row in table:
        ws.append([_safe_cell(c) for c in row])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
