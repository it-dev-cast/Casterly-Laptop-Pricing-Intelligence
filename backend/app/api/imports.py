"""Upload -> sheet selection -> column mapping -> review/correct -> commit."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..ai import claude, extract_rules
from ..db import get_db
from ..importing import pipeline
from ..importing.fields import RECORD_TYPES, fields_for, suggest_mapping
from ..importing.files import UploadRejected, read_sheets, validate_and_store
from ..models import ColumnMapping, StagingRow, UploadBatch, User
from ..security import can, current_user, require
from ..services.config_store import active_config

router = APIRouter(prefix="/api", tags=["import"])


def _perm_for(record_type: str) -> str:
    return "import_inventory" if record_type == "inventory" else "import_evidence"


def _check(user: User, record_type: str) -> None:
    if record_type not in RECORD_TYPES:
        raise HTTPException(422, f"record_type must be one of {list(RECORD_TYPES)}")
    if not can(user, _perm_for(record_type)):
        raise HTTPException(403, f"Role '{user.role}' cannot import {RECORD_TYPES[record_type].lower()}")


def batch_out(b: UploadBatch) -> dict:
    return {"id": b.id, "record_type": b.record_type, "record_type_label": RECORD_TYPES[b.record_type],
            "original_filename": b.original_filename, "file_kind": b.file_kind, "size_bytes": b.size_bytes,
            "sha256": b.sha256, "sheets": b.sheets, "selected_sheets": b.selected_sheets, "mapping": b.mapping,
            "import_defaults": b.import_defaults, "status": b.status, "is_synthetic": b.is_synthetic,
            "summary": b.summary, "created_at": b.created_at.isoformat(),
            "committed_at": b.committed_at.isoformat() if b.committed_at else None}


def row_out(r: StagingRow) -> dict:
    return {"id": r.id, "sheet": r.sheet, "row_number": r.row_number, "raw": r.raw, "mapped_raw": r.mapped_raw,
            "normalized": r.normalized, "corrections": r.corrections, "suggestions": r.suggestions,
            "errors": r.errors, "warnings": r.warnings, "status": r.status, "duplicate_of": r.duplicate_of,
            "keep_duplicate": r.keep_duplicate, "committed_record_id": r.committed_record_id}


@router.get("/import/record-types")
def record_types(_: User = Depends(current_user)):
    return [{"key": k, "label": v} for k, v in RECORD_TYPES.items()]


@router.get("/import/fields")
def import_fields(record_type: str, _: User = Depends(current_user)):
    if record_type not in RECORD_TYPES:
        raise HTTPException(422, "Unknown record type")
    return [{"key": f.key, "label": f.label, "kind": f.kind, "help": f.help,
             "required": record_type in f.required, "matching": f.matching} for f in fields_for(record_type)]


@router.post("/uploads")
async def upload(record_type: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    _check(user, record_type)
    content = await file.read()
    try:
        info = validate_and_store(file.filename or "", content)
        sheets = read_sheets(info["stored_name"], info["file_kind"])
    except UploadRejected as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # unreadable workbook/CSV
        raise HTTPException(422, f"Could not read the file: {type(e).__name__}")
    b = UploadBatch(record_type=record_type, original_filename=(file.filename or "upload")[:255],
                    created_by=user.id, status="uploaded", **info,
                    sheets=[{"name": s.name, "rows": len(s.rows), "headers": s.headers,
                             "preview": [r for _, r in s.rows[:5]]} for s in sheets])
    db.add(b)
    db.flush()
    audit.record(db, user, "import.uploaded", "upload_batch", b.id, filename=b.original_filename,
                 sha256=b.sha256, record_type=record_type, size=b.size_bytes)
    db.commit()
    return batch_out(b)


@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return [batch_out(b) for b in db.scalars(select(UploadBatch).order_by(UploadBatch.id.desc()).limit(200)).all()]


def _batch(db: Session, batch_id: int) -> UploadBatch:
    b = db.get(UploadBatch, batch_id)
    if b is None:
        raise HTTPException(404, "Upload not found")
    return b


@router.get("/uploads/{batch_id}")
def get_upload(batch_id: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return batch_out(_batch(db, batch_id))


@router.get("/uploads/{batch_id}/suggest-mapping")
def suggest(batch_id: int, sheets: list[str] = Query(default=[]), db: Session = Depends(get_db),
            _: User = Depends(require("view"))):
    b = _batch(db, batch_id)
    chosen = [s for s in b.sheets if not sheets or s["name"] in sheets]
    headers: list[str] = []
    for s in chosen:
        for h in s["headers"]:
            if h not in headers:
                headers.append(h)
    saved = db.scalars(select(ColumnMapping).where(ColumnMapping.record_type == b.record_type)
                       .order_by(ColumnMapping.id.desc())).all()
    return {"headers": headers, "suggested": suggest_mapping(b.record_type, headers),
            "saved_mappings": [{"id": m.id, "name": m.name, "mapping": m.mapping,
                                "applicable": all(c in headers for c in m.mapping.values() if c)} for m in saved]}


class StageIn(BaseModel):
    sheets: list[str]
    mapping: dict[str, str | None]
    defaults: dict[str, Any] = {}
    save_mapping_as: str | None = None


@router.post("/uploads/{batch_id}/stage")
def stage(batch_id: int, body: StageIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _batch(db, batch_id)
    _check(user, b.record_type)
    if b.status == "committed":
        raise HTTPException(409, "This upload is already committed")
    if not body.sheets:
        raise HTTPException(422, "Select at least one sheet")
    names = {s["name"] for s in b.sheets}
    if any(s not in names for s in body.sheets):
        raise HTTPException(422, "Unknown sheet selected")
    mapping = {k: v for k, v in body.mapping.items() if v}
    cfg, _ = active_config(db)
    try:
        pipeline.stage(db, b, body.sheets, mapping, body.defaults, cfg)
    except (ValueError, UploadRejected) as e:
        raise HTTPException(422, str(e))
    if body.save_mapping_as:
        db.add(ColumnMapping(name=body.save_mapping_as[:120], record_type=b.record_type, mapping=mapping,
                             created_by=user.id))
    audit.record(db, user, "import.staged", "upload_batch", b.id, sheets=body.sheets, mapping=mapping,
                 defaults=body.defaults, summary=b.summary)
    db.commit()
    return batch_out(b)


@router.get("/uploads/{batch_id}/rows")
def rows(batch_id: int, status: str | None = None, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    b = _batch(db, batch_id)
    out = sorted(b.rows, key=lambda r: (r.sheet or "", r.row_number))
    if status:
        wanted = set(status.split(","))
        out = [r for r in out if r.status in wanted]
    return [row_out(r) for r in out]


def _row(db: Session, row_id: int, user: User) -> StagingRow:
    r = db.get(StagingRow, row_id)
    if r is None:
        raise HTTPException(404, "Row not found")
    _check(user, r.batch.record_type)
    return r


class CorrectIn(BaseModel):
    changes: dict[str, Any]
    reason: str | None = None


@router.patch("/staging-rows/{row_id}")
def correct(row_id: int, body: CorrectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _row(db, row_id, user)
    cfg, _ = active_config(db)
    try:
        pipeline.correct_row(db, r, body.changes, user, cfg, body.reason)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return row_out(r)


class RowAction(BaseModel):
    action: str  # skip | unskip | keep_duplicate | drop_duplicate


@router.post("/staging-rows/{row_id}/action")
def row_action(row_id: int, body: RowAction, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _row(db, row_id, user)
    if r.status == "committed":
        raise HTTPException(409, "Row already committed")
    if body.action == "skip":
        r.status = "skipped"
    elif body.action == "unskip":
        r.status = "pending"
    elif body.action in ("keep_duplicate", "drop_duplicate"):
        r.keep_duplicate = body.action == "keep_duplicate"
    else:
        raise HTTPException(422, "Unknown action")
    pipeline.detect_duplicates(db, r.batch)
    r.batch.summary = pipeline.summarize(r.batch)
    audit.record(db, user, f"import.row_{body.action}", "staging_row", r.id)
    db.commit()
    return row_out(r)


class ExtractIn(BaseModel):
    use_ai: bool = False


@router.post("/staging-rows/{row_id}/extract")
def extract(row_id: int, body: ExtractIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Suggest field values from the row's description/title. Suggestions must be reviewed and accepted."""
    r = _row(db, row_id, user)
    text = " ".join(str(r.mapped_raw.get(k) or "") for k in ("title", "description", "model")).strip()
    if not text:
        raise HTTPException(422, "Row has no description or title text to extract from")
    if body.use_ai:
        if not can(user, "use_ai"):
            raise HTTPException(403, "Not permitted to use AI")
        try:
            sugg, model = claude.extract(text)
        except claude.AIUnavailable as e:
            raise HTTPException(503, str(e))
        audit.record(db, user, "ai.extract", "staging_row", r.id, model=model, fields=list(sugg))
    else:
        sugg = extract_rules.extract(text)
    current = r.normalized or {}
    sugg = {k: v for k, v in sugg.items() if k in current and current.get(k) in (None, [], "")}
    r.suggestions = sugg or None
    r.status = pipeline._status(r)
    r.batch.summary = pipeline.summarize(r.batch)
    db.commit()
    return row_out(r)


class AcceptIn(BaseModel):
    accept: list[str]
    reject: list[str] = []


@router.post("/staging-rows/{row_id}/suggestions")
def resolve_suggestions(row_id: int, body: AcceptIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _row(db, row_id, user)
    sugg = dict(r.suggestions or {})
    cfg, _ = active_config(db)
    changes = {k: sugg[k]["value"] for k in body.accept if k in sugg}
    sources = {sugg[k]["method"] for k in changes}
    for k in list(body.accept) + list(body.reject):
        sugg.pop(k, None)
    r.suggestions = sugg or None
    if changes:
        pipeline.correct_row(db, r, changes, user, cfg, reason="Accepted extraction suggestion",
                             source=("ai_extraction" if "claude" in sources else "rule_extraction"))
    else:
        r.status = pipeline._status(r)
        r.batch.summary = pipeline.summarize(r.batch)
    db.commit()
    return row_out(r)


@router.get("/uploads/{batch_id}/issues")
def issues_file(batch_id: int, format: str = "csv", db: Session = Depends(get_db), _: User = Depends(require("view"))):
    b = _batch(db, batch_id)
    if format not in ("csv", "xlsx"):
        raise HTTPException(422, "format must be csv or xlsx")
    data = pipeline.export_errors(b, format)
    media = "text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="upload-{b.id}-issues.{format}"'})


@router.post("/uploads/{batch_id}/commit")
def commit(batch_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _batch(db, batch_id)
    _check(user, b.record_type)
    if b.status not in ("staged", "partially_committed"):
        raise HTTPException(409, "Map and review the upload before committing")
    result = pipeline.commit(db, b, user)
    db.commit()
    return {**result, "batch": batch_out(b)}


@router.get("/mappings")
def mappings(record_type: str | None = None, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    q = select(ColumnMapping).order_by(ColumnMapping.id.desc())
    if record_type:
        q = q.where(ColumnMapping.record_type == record_type)
    return [{"id": m.id, "name": m.name, "record_type": m.record_type, "mapping": m.mapping}
            for m in db.scalars(q).all()]


@router.delete("/mappings/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    m = db.get(ColumnMapping, mapping_id)
    if m is None:
        raise HTTPException(404, "Mapping not found")
    _check(user, m.record_type)
    db.delete(m)
    audit.record(db, user, "import.mapping_deleted", "column_mapping", mapping_id, name=m.name)
    db.commit()
    return {"deleted": mapping_id}
