"""Safe reading of uploaded CSV and XLSX files.

* Only .csv and .xlsx are accepted, and the content must match the extension
  (XLSX = ZIP container with a workbook part; CSV = decodable text without NUL bytes).
* Macro-enabled or legacy formats (.xlsm, .xls) are rejected.
* XLSX archives are checked for total uncompressed size before parsing (zip-bomb guard).
* Workbooks are opened read-only with cached values only: formulas are never evaluated.
* Files are stored under a random name outside any served directory.
* Cell contents are treated purely as data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from ..config import get_settings


class UploadRejected(ValueError):
    pass


@dataclass
class SheetData:
    name: str
    headers: list[str]
    rows: list[tuple[int, dict]]  # (1-based source row number, header -> value)


def validate_and_store(filename: str, content: bytes) -> dict:
    s = get_settings()
    if not filename:
        raise UploadRejected("File name missing")
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx"):
        raise UploadRejected("Only .csv and .xlsx files are accepted (macro-enabled and legacy .xls are not)")
    if len(content) == 0:
        raise UploadRejected("File is empty")
    if len(content) > s.max_upload_mb * 1024 * 1024:
        raise UploadRejected(f"File exceeds the {s.max_upload_mb} MB limit")
    kind = ext[1:]
    if kind == "xlsx":
        if not content.startswith(b"PK\x03\x04"):
            raise UploadRejected("File is not a valid .xlsx workbook")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = z.namelist()
                if "xl/workbook.xml" not in names:
                    raise UploadRejected("Archive is not an Excel workbook")
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    raise UploadRejected("Workbooks containing macros are not accepted")
                total = sum(i.file_size for i in z.infolist())
                if total > s.max_xlsx_uncompressed_mb * 1024 * 1024:
                    raise UploadRejected("Workbook expands beyond the allowed size")
        except zipfile.BadZipFile as e:
            raise UploadRejected("File is not a valid .xlsx workbook") from e
    else:
        if b"\x00" in content[:65536]:
            raise UploadRejected("CSV contains binary data")
        _decode(content)
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{kind}"
    (s.upload_dir / stored).write_bytes(content)
    return {"stored_name": stored, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
            "file_kind": kind}


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UploadRejected("CSV is not UTF-8 or Windows-1252 text")


def stored_path(stored_name: str) -> Path:
    if "/" in stored_name or "\\" in stored_name or ".." in stored_name:
        raise UploadRejected("Invalid stored file name")
    return get_settings().upload_dir / stored_name


def _cell(v):
    if isinstance(v, datetime):
        return v.isoformat() if (v.hour or v.minute or v.second) else v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        v = v.strip()
        return v if v != "" else None
    return v


def _unique_headers(raw: list) -> list[str]:
    raw = list(raw)
    while raw and raw[-1] is None:
        raw.pop()
    out, seen = [], {}
    for i, h in enumerate(raw):
        name = str(h).strip() if h is not None and str(h).strip() else f"Column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        out.append(name)
    return out


HEADER_SCAN_ROWS = 10


def _filled(values: list) -> int:
    return sum(1 for v in values if v is not None)


def _table(rows_iter, name: str, max_rows: int) -> SheetData:
    """The header is the first row, among the first few non-empty rows, that is at least half as
    full as the fullest of them. Title or note rows above a table are skipped."""
    headers: list[str] | None = None
    rows: list[tuple[int, dict]] = []
    preamble: list[tuple[int, list]] = []
    it = iter(enumerate(rows_iter, start=1))
    for idx, row in it:
        values = [_cell(v) for v in row]
        if _filled(values):
            preamble.append((idx, values))
        if len(preamble) >= HEADER_SCAN_ROWS:
            break
    if preamble:
        widest = max(_filled(v) for _, v in preamble)
        h_pos = next(i for i, (_, v) in enumerate(preamble) if _filled(v) >= max(2, widest / 2) or widest < 2)
        headers = _unique_headers(preamble[h_pos][1])
        buffered = preamble[h_pos + 1:]
    else:
        buffered = []

    def remaining():
        yield from buffered
        for idx, row in it:
            yield idx, [_cell(v) for v in row]

    for idx, values in remaining():
        if headers is None:
            break
        if not any(v is not None for v in values):
            continue
        if len(rows) >= max_rows:
            raise UploadRejected(f"Sheet '{name}' has more than {max_rows} data rows")
        values += [None] * (len(headers) - len(values))
        extra = values[len(headers):]
        rec = dict(zip(headers, values[: len(headers)]))
        if any(v is not None for v in extra):
            rec["__extra_cells__"] = [v for v in extra if v is not None]
        rows.append((idx, rec))
    return SheetData(name, headers or [], rows)


def read_sheets(stored_name: str, file_kind: str, only: list[str] | None = None) -> list[SheetData]:
    path = stored_path(stored_name)
    max_rows = get_settings().max_upload_rows
    if file_kind == "csv":
        text = _decode(path.read_bytes())
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [_table(csv.reader(io.StringIO(text), dialect), "CSV", max_rows)]
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        out = []
        for ws in wb.worksheets:
            if only is not None and ws.title not in only:
                continue
            out.append(_table(ws.iter_rows(values_only=True), ws.title, max_rows))
        return out
    finally:
        wb.close()
