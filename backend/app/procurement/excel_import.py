"""Layout-detecting Excel importer for vendor asset lists.

* Finds the sheet and header row that hold the real asset table (title rows, notes and
  supplementary sheets are ignored).
* Recognises the Casterly B001 (mixed asset list) and B002 (server components) layouts and any
  other layout through header synonyms; a user-supplied mapping overrides detection.
* Excludes blank rows, repeated header rows and total/summary rows, recording why.
* Keeps every source row's original cells and its sheet/row number so the export can write back
  to exactly the same row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .. import specs

HEADER_SCAN_ROWS = 30


def norm_header(h: Any) -> str:
    s = str(h or "").strip().lower()
    s = re.sub(r"[\s_]+", " ", s)
    return re.sub(r"[^a-z0-9/()# ]", "", s).strip()


CANONICAL_FIELDS: dict[str, tuple[str, list[str]]] = {
    # key: (label, header synonyms - normalised)
    "serial": ("Serial number", ["serial number", "serial", "serial no", "s/n", "sn", "service tag", "asset tag", "imei",
                                 "serial #"]),
    "item_code": ("Item code", ["item code", "sku", "part code", "item no", "item id"]),
    "sales_order": ("Sales order", ["sales order", "so", "so number", "so no"]),
    "global_local": ("Global/Local", ["global/local", "global local"]),
    "request_label": ("Request label", ["request label"]),
    "offer": ("Vendor offer", ["offer", "vendor offer", "offer price"]),
    "category_hint": ("Category", ["category", "asset category"]),
    "asset_type": ("Type", ["type", "asset type", "item type"]),
    "product_type": ("Product type", ["product type", "device type", "asset class", "product category"]),
    "make": ("Make / brand", ["make", "brand", "manufacturer", "oem"]),
    "model": ("Model", ["model", "model name", "model number", "model no", "part number", "product", "product name"]),
    "cpu": ("Processor / spec", ["cpu", "processor", "processor type", "cpu model", "chip"]),
    "generation": ("Generation", ["generation", "gen", "cpu generation", "processor generation"]),
    "ram": ("RAM", ["ram", "memory", "ram size", "ram (gb)"]),
    "storage": ("Storage", ["storage (hdd/ssd)", "storage", "hdd", "ssd", "hdd/ssd", "storage capacity", "hard disk"]),
    "gpu": ("GPU", ["gpu", "graphics", "graphics card"]),
    "display": ("Display", ["display", "screen size", "display size"]),
    "grade": ("Grade", ["grade", "condition grade", "cosmetic grade"]),
    "condition": ("Condition", ["condition", "working status", "functional status"]),
    "charger": ("Charger", ["charger", "adapter", "charger included"]),
    "battery": ("Battery", ["battery", "battery health", "battery %"]),
    "notes": ("Notes", ["notes", "remarks", "comments", "note"]),
    "description": ("Description", ["open description", "description", "item description", "desc", "details"]),
    "location": ("Location", ["location", "city", "site", "warehouse"]),
    "quantity": ("Quantity", ["net leased qty", "qty", "quantity", "units", "nos", "count", "unit count"]),
    "existing_price": ("Market Unit Price", ["market unit price"]),
}

LAYOUT_SIGNATURES = {
    "b002": {"serial", "category_hint", "request_label", "asset_type", "make", "model", "cpu", "grade"},
    "b001": {"sales_order", "item_code", "description", "quantity", "product_type", "model", "cpu"},
}
B001_REQUIRED_HEADERS = {"net leased qty", "open description", "sales order"}

TOTAL_RE = re.compile(r"^\s*(grand\s+)?(sub\s*)?totals?\b|^\s*summary\b|^\s*total\s+(units|value|qty)", re.I)


class ImportError_(ValueError):
    pass


@dataclass
class ParsedRow:
    row_number: int
    raw: dict  # header -> cell value (JSON-safe)
    mapped: dict  # canonical -> value


@dataclass
class ImportResult:
    layout: str
    sheet: str
    header_row: int
    headers: list[str]
    column_map: dict[str, str]
    qty_column: str | None
    price_column: str | None
    rows: list[ParsedRow] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)

    def detection(self) -> dict:
        return {"layout": self.layout, "sheet": self.sheet, "header_row": self.header_row, "headers": self.headers,
                "skipped_rows": self.skipped[:500], "skipped_count": len(self.skipped), "warnings": self.warnings,
                "candidates": self.candidates, "data_rows": len(self.rows)}


def _cell(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def suggest_map(headers: list[str], qty_columns: list[str]) -> dict[str, str]:
    """canonical field -> header, first synonym hit wins; each header used once."""
    normed = {h: norm_header(h) for h in headers}
    out: dict[str, str] = {}
    used: set[str] = set()
    synonyms = dict(CANONICAL_FIELDS)
    synonyms["quantity"] = (synonyms["quantity"][0], [norm_header(q) for q in qty_columns] + synonyms["quantity"][1])
    # exact matches first, in synonym priority order
    for key, (_, syns) in synonyms.items():
        for syn in syns:
            hit = next((h for h, n in normed.items() if n == syn and h not in used), None)
            if hit:
                out[key] = hit
                used.add(hit)
                break
    return out


def _header_score(values: list) -> int:
    known = {s for _, syns in CANONICAL_FIELDS.values() for s in syns}
    return sum(1 for v in values if isinstance(v, str) and norm_header(v) in known)


def _unique(raw: list) -> list[str]:
    raw = list(raw)
    while raw and (raw[-1] is None or not str(raw[-1]).strip()):
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


def read_workbook(path: Path, *, qty_columns: list[str], max_rows: int, sheet: str | None = None,
                  header_row: int | None = None, mapping: dict[str, str] | None = None) -> ImportResult:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        candidates = []
        for ws in wb.worksheets:
            if sheet and ws.title != sheet:
                continue
            rows = []
            for idx, r in enumerate(ws.iter_rows(values_only=True), start=1):
                rows.append([_cell(v) for v in r])
                if idx > max_rows + HEADER_SCAN_ROWS:
                    raise ImportError_(f"Sheet '{ws.title}' has more than {max_rows} rows")
            if not rows:
                continue
            best = None
            scan = range(min(HEADER_SCAN_ROWS, len(rows)))
            if header_row:
                scan = [header_row - 1] if header_row - 1 < len(rows) else []
            for i in scan:
                sc = _header_score(rows[i])
                if best is None or sc > best[0]:
                    best = (sc, i)
            if best is None:
                continue
            sc, hi = best
            headers = _unique(rows[hi])
            cmap = suggest_map(headers, qty_columns)
            layout = "generic"
            if LAYOUT_SIGNATURES["b002"].issubset(cmap.keys()):
                layout = "b002"
            elif len(LAYOUT_SIGNATURES["b001"] & cmap.keys()) >= 5 and \
                    B001_REQUIRED_HEADERS.issubset({norm_header(h) for h in headers}):
                layout = "b001"
            data = [r for r in rows[hi + 1:] if any(v is not None for v in r)]
            bonus = 50 if layout != "generic" else 0
            bonus += 10 if ws.title.strip().lower() in ("asset list", "assets", "sheet1", "data") else 0
            candidates.append({"sheet": ws.title, "header_row": hi + 1, "score": sc * 10 + bonus + min(len(data), 1000) / 1000,
                               "layout": layout, "headers": headers, "map": cmap, "rows": rows, "hi": hi})
        if not candidates:
            raise ImportError_("No sheet with a recognisable header row was found")
        candidates.sort(key=lambda c: -c["score"])
        chosen = candidates[0]
        if chosen["score"] < 20 and not mapping:
            raise ImportError_("Could not recognise the asset table. Choose the sheet and map the columns manually.")
        cmap = dict(mapping) if mapping else chosen["map"]
        bad = [h for h in cmap.values() if h not in chosen["headers"]]
        if bad:
            raise ImportError_(f"Mapped columns not found in the header row: {', '.join(bad)}")
        if "model" not in cmap and "description" not in cmap:
            raise ImportError_("Map at least a Model or Description column")
        res = ImportResult(layout=chosen["layout"] if not mapping else (chosen["layout"] if chosen["map"] == cmap else "generic"),
                           sheet=chosen["sheet"], header_row=chosen["header_row"], headers=chosen["headers"],
                           column_map=cmap, qty_column=cmap.get("quantity"), price_column=cmap.get("existing_price"),
                           candidates=[{k: c[k] for k in ("sheet", "header_row", "layout", "score")} for c in candidates])
        _rows(res, chosen["rows"], chosen["hi"])
        if res.qty_column is None:
            res.warnings.append("No quantity column: each row is treated as one unit")
        return res
    finally:
        wb.close()


def _rows(res: ImportResult, rows: list[list], hi: int) -> None:
    headers = res.headers
    header_norm = [norm_header(h) for h in headers]
    inv = {v: k for k, v in res.column_map.items()}
    ident_fields = ("model", "description", "serial", "item_code", "make")
    for offset, values in enumerate(rows[hi + 1:], start=hi + 2):
        if not any(v is not None for v in values):
            continue
        values = list(values) + [None] * (len(headers) - len(values))
        raw = {headers[i]: values[i] for i in range(len(headers))}
        texts = [str(v) for v in values if isinstance(v, str)]
        if [norm_header(v) for v in values[: len(headers)]] == header_norm:
            res.skipped.append({"row": offset, "reason": "repeated header row"})
            continue
        if any(TOTAL_RE.match(t) for t in texts[:3]):
            res.skipped.append({"row": offset, "reason": "total / summary row"})
            continue
        mapped = {inv[h]: v for h, v in raw.items() if h in inv}
        if not any(specs.clean_text(mapped.get(f)) for f in ident_fields):
            res.skipped.append({"row": offset, "reason": "no identifying columns (model, description, serial)"})
            continue
        res.rows.append(ParsedRow(offset, raw, mapped))


def parse_quantity(raw: Any) -> tuple[int | None, str | None]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "missing"
    r = specs.parse_number(raw, field="quantity")
    if r.error or r.value is None:
        return None, f"unreadable quantity '{raw}'"
    v = r.value
    if v < 0 or v != int(v):
        return None, f"invalid quantity '{raw}'"
    return int(v), None
