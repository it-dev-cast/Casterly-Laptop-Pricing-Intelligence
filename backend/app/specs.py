"""Parsing and normalisation of laptop specification values.

Each parser returns ``ParseResult(value, error, warning)``. ``value is None`` means
the input was missing (blank, "NA", "-", ...). An explicit "0" parses to 0, never None.
These functions are pure and shared by the importer, manual entry, and the engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

MISSING_TOKENS = {"", "na", "n/a", "n.a.", "-", "--", "null", "none given", "unknown", "?", "nan", "not available"}


@dataclass
class ParseResult:
    value: Any = None
    error: str | None = None
    warning: str | None = None


def is_missing(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, float) and raw != raw:  # NaN
        return True
    if isinstance(raw, str) and raw.strip().lower() in MISSING_TOKENS:
        return True
    return False


def clean_text(raw: Any) -> str | None:
    if is_missing(raw):
        return None
    s = str(raw).strip()
    s = re.sub(r"\s+", " ", s)
    return s or None


def key_text(s: str | None) -> str | None:
    if s is None:
        return None
    k = s.lower()
    k = re.sub(r"[™®©]|\(tm\)|\(r\)", "", k)
    k = re.sub(r"[^a-z0-9.+/ -]", " ", k)
    k = re.sub(r"\s+", " ", k).strip()
    return k or None


# ---------------------------------------------------------------- numbers

_NUM_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


def parse_number(raw: Any, *, allow_negative: bool = False, field: str = "value") -> ParseResult:
    """Parse a number, accepting Indian digit grouping (1,23,456) and currency marks."""
    if is_missing(raw):
        return ParseResult(None)
    if isinstance(raw, bool):
        return ParseResult(None, error=f"{field}: expected a number, got a boolean")
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        s = str(raw).strip().lower()
        s = re.sub(r"(₹|rs\.?|inr|/-|\s)", "", s)
        s = s.replace(",", "")
        if s.endswith("/unit"):
            s = s[:-5]
        if not _NUM_RE.match(s):
            return ParseResult(None, error=f"{field}: '{raw}' is not a number")
        val = float(s)
    if val < 0 and not allow_negative:
        return ParseResult(None, error=f"{field}: negative value {val:g} not allowed")
    return ParseResult(val)


def parse_money(raw: Any, *, field: str = "price", allow_zero: bool = True) -> ParseResult:
    r = parse_number(raw, field=field)
    if r.value is not None:
        r.value = round(r.value, 2)
        if r.value == 0 and not allow_zero:
            return ParseResult(None, error=f"{field}: 0 is not a valid observed price")
    return r


def parse_int(raw: Any, *, field: str = "value", minimum: int | None = None) -> ParseResult:
    r = parse_number(raw, field=field)
    if r.value is None or r.error:
        return r
    if abs(r.value - round(r.value)) > 1e-9:
        return ParseResult(None, error=f"{field}: '{raw}' must be a whole number")
    v = int(round(r.value))
    if minimum is not None and v < minimum:
        return ParseResult(None, error=f"{field}: must be at least {minimum}")
    return ParseResult(v)


def parse_percent(raw: Any, *, field: str = "percent", lo: float = 0, hi: float = 100) -> ParseResult:
    """Accepts '85%', '85', and fractions such as 0.85 (with a warning)."""
    if is_missing(raw):
        return ParseResult(None)
    had_pct = isinstance(raw, str) and "%" in raw
    s = str(raw).replace("%", "") if isinstance(raw, str) else raw
    r = parse_number(s, field=field, allow_negative=lo < 0)
    if r.value is None or r.error:
        return r
    v = r.value
    warning = None
    if not had_pct and 0 < v <= 1 and hi > 1:
        v = v * 100
        warning = f"{field}: '{raw}' read as a fraction ({v:g}%)"
    if v < lo or v > hi:
        return ParseResult(None, error=f"{field}: {v:g}% outside {lo:g}–{hi:g}%")
    return ParseResult(round(v, 4), warning=warning)


# ---------------------------------------------------------------- capacities

def parse_capacity_gb(raw: Any, *, field: str) -> ParseResult:
    """'16GB', '16 GB', '16', '1TB', '512 GB SSD', '16384MB'. 1 TB = 1024 GB."""
    if is_missing(raw):
        return ParseResult(None)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        v = float(raw)
        if v <= 0:
            return ParseResult(None, error=f"{field}: capacity must be positive")
        return ParseResult(int(round(v)))
    s = str(raw).lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(tb|gb|mb|g|t)?\b", s)
    if not m:
        return ParseResult(None, error=f"{field}: cannot read a capacity from '{raw}'")
    num = float(m.group(1))
    unit = m.group(2) or "gb"
    if unit in ("tb", "t"):
        num *= 1024
    elif unit == "mb":
        num /= 1024
    if num <= 0:
        return ParseResult(None, error=f"{field}: capacity must be positive")
    warning = None
    if len(re.findall(r"\d+(?:\.\d+)?\s*(?:tb|gb|mb)", s)) > 1:
        warning = f"{field}: several capacities in '{raw}'; used the first ({int(round(num))} GB)"
    return ParseResult(int(round(num)), warning=warning)


def parse_storage_type(raw: Any) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).lower()
    if "sshd" in s or "hybrid" in s:
        return ParseResult("SSHD")
    if "nvme" in s or "ssd" in s or "m.2" in s or "pcie" in s:
        return ParseResult("SSD")
    if "emmc" in s:
        return ParseResult("eMMC")
    if "hdd" in s or "hard" in s or "sata hdd" in s:
        return ParseResult("HDD")
    return ParseResult(None, error=f"storage_type: '{raw}' not recognised (SSD, HDD, SSHD, eMMC)")


def storage_type_from_text(raw: Any) -> str | None:
    if is_missing(raw):
        return None
    r = parse_storage_type(raw)
    return r.value


# ---------------------------------------------------------------- identity

_CPU_NOISE = re.compile(
    r"\b(intel|amd|apple|qualcomm|core|processor|cpu|mobile|with radeon graphics|radeon graphics|"
    r"\d+(\.\d+)?\s*ghz|@|\d+(st|nd|rd|th)\s*gen(eration)?)\b"
)


def cpu_key(raw: Any) -> str | None:
    """Canonical exact-CPU key: 'Intel Core i5-8350U @ 1.70GHz' -> 'i5-8350u'."""
    s = clean_text(raw)
    if s is None:
        return None
    k = s.lower()
    k = re.sub(r"\(tm\)|\(r\)|[™®]", "", k)
    k = _CPU_NOISE.sub(" ", k)
    k = re.sub(r"[^a-z0-9 -]", " ", k)
    k = re.sub(r"\s+", " ", k).strip()
    # Intel: 'i5 8350u' -> 'i5-8350u'
    k = re.sub(r"\b(i[3579])\s*-?\s*(\d{4,5}[a-z]{0,2})\b", r"\1-\2", k)
    # Intel Core Ultra: 'ultra 7 155h' -> 'ultra 7-155h'
    k = re.sub(r"\bultra (\d) ?-?(\d{3}[a-z]{0,2})\b", r"ultra \1-\2", k)
    return k or None


def model_key(brand: str | None, model: str | None) -> str | None:
    m = key_text(model)
    if m is None:
        return None
    b = key_text(brand)
    if b and m.startswith(b + " "):
        m = m[len(b) + 1 :]
    return m


def brand_key(raw: Any) -> str | None:
    s = key_text(clean_text(raw))
    if s is None:
        return None
    aliases = {"hewlett packard": "hp", "hewlett-packard": "hp", "hp inc": "hp", "apple inc": "apple"}
    return aliases.get(s, s)


def gpu_key(raw: Any) -> str | None:
    s = key_text(clean_text(raw))
    if s is None:
        return None
    if s in {"integrated", "onboard", "intel uhd", "intel hd", "igpu", "shared", "intel iris xe", "uhd"}:
        return "integrated"
    s = re.sub(r"\b(nvidia|geforce|amd|graphics)\b", "", s)
    return re.sub(r"\s+", " ", s).strip() or None


def parse_resolution(raw: Any) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).lower().replace(" ", "")
    named = {"fhd": "1920x1080", "fullhd": "1920x1080", "1080p": "1920x1080", "hd": "1366x768",
             "qhd": "2560x1440", "wqhd": "2560x1440", "4k": "3840x2160", "uhd": "3840x2160",
             "fhd+": "1920x1200", "wuxga": "1920x1200"}
    m = re.search(r"(\d{3,4})[x×*](\d{3,4})", s)
    if m:
        return ParseResult(f"{m.group(1)}x{m.group(2)}")
    for k, v in named.items():
        if s == k or s.startswith(k):
            return ParseResult(v)
    return ParseResult(None, error=f"display_resolution: '{raw}' not recognised (e.g. 1920x1080, FHD)")


def parse_display_size(raw: Any) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).lower().replace('"', "").replace("inch", "").replace("in", "").strip()
    r = parse_number(s, field="display_size_in")
    if r.value is not None and not (7 <= r.value <= 20):
        return ParseResult(None, error=f"display_size_in: {r.value:g} is not a plausible laptop screen size")
    return r


# ---------------------------------------------------------------- condition & extras

def parse_grade(raw: Any, scale: list[str], synonyms: dict[str, str]) -> ParseResult:
    """Grades must resolve to the configured scale; free-text words are not guessed."""
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).strip()
    lowered = s.lower()
    if lowered in synonyms:
        return ParseResult(synonyms[lowered])
    stripped = re.sub(r"^(grade|grd|condition)\s*[:-]?\s*", "", lowered).strip().upper()
    for g in scale:
        if stripped == g.upper():
            return ParseResult(g)
    return ParseResult(None, error=f"condition_grade: '{raw}' is not in the configured grade scale {scale}")


def parse_bool(raw: Any, *, field: str) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    if isinstance(raw, bool):
        return ParseResult(raw)
    s = str(raw).strip().lower()
    if s in {"yes", "y", "true", "1", "included", "with charger", "available", "present"}:
        return ParseResult(True)
    if s in {"no", "n", "false", "0", "missing", "not included", "without charger", "absent", "none"}:
        return ParseResult(False)
    return ParseResult(None, error=f"{field}: '{raw}' is not yes/no")


def parse_warranty_months(raw: Any) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return parse_int(raw, field="warranty_months", minimum=0)
    s = str(raw).strip().lower()
    if s in {"no", "no warranty", "nil", "none", "0", "without warranty", "na warranty"}:
        return ParseResult(0)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(y|yr|yrs|year|years|m|mo|mon|month|months|d|day|days)?\b", s)
    if not m:
        return ParseResult(None, error=f"warranty_months: '{raw}' not understood (e.g. 6 months, 1 year, none)")
    n = float(m.group(1))
    unit = (m.group(2) or "m")[0]
    months = n * 12 if unit == "y" else (n / 30 if unit == "d" else n)
    return ParseResult(int(round(months)))


def parse_faults(raw: Any) -> ParseResult:
    """None = unknown; [] = explicitly no faults."""
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).strip()
    if s.lower() in {"none", "no", "nil", "no faults", "no fault", "ok", "working", "fully working", "0"}:
        return ParseResult([])
    parts = [p.strip() for p in re.split(r"[;,|/]+", s) if p.strip()]
    return ParseResult(parts)


def parse_tax_basis(raw: Any) -> ParseResult:
    if is_missing(raw):
        return ParseResult("unknown")
    s = str(raw).strip().lower().replace(" ", "")
    if s in {"inclusive", "incl", "incl.gst", "inclgst", "inc", "includinggst", "withgst", "gstincluded", "mrp", "inclusiveofgst"}:
        return ParseResult("inclusive")
    if s in {"exclusive", "excl", "excl.gst", "exclgst", "ex", "exgst", "+gst", "plusgst", "excludinggst", "withoutgst", "gstextra", "exclusiveofgst"}:
        return ParseResult("exclusive")
    if s in {"unknown", "notstated"}:
        return ParseResult("unknown")
    return ParseResult("unknown", error=f"tax_basis: '{raw}' not recognised (inclusive / exclusive / unknown)")


def parse_enum(raw: Any, *, field: str, allowed: dict[str, str]) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if s in allowed:
        return ParseResult(allowed[s])
    return ParseResult(None, error=f"{field}: '{raw}' must be one of {sorted(set(allowed.values()))}")


CHANNELS = {"retail": "retail", "b2c": "retail", "consumer": "retail", "online": "retail",
            "wholesale": "wholesale", "b2b": "wholesale", "trade": "wholesale", "bulk": "wholesale",
            "as_is": "as_is", "asis": "as_is", "as_is_procurement": "as_is", "scrap": "as_is", "salvage": "as_is"}
AVAILABILITY = {"in_stock": "in_stock", "available": "in_stock", "instock": "in_stock", "yes": "in_stock", "active": "in_stock",
                "out_of_stock": "out_of_stock", "outofstock": "out_of_stock", "unavailable": "out_of_stock", "no": "out_of_stock",
                "removed": "removed", "delisted": "removed", "expired": "removed", "sold": "sold", "sold_out": "sold",
                "unknown": "unknown"}
TXN_KINDS = {"sale": "sale", "sold": "sale", "sell": "sale", "purchase": "purchase", "bought": "purchase", "buy": "purchase"}


# ---------------------------------------------------------------- dates

def _excel_serial(v: float) -> date:
    return date(1899, 12, 30) + timedelta(days=int(v))


def parse_date(raw: Any, *, field: str, day_first: bool = True) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    if isinstance(raw, datetime):
        return ParseResult(raw.date())
    if isinstance(raw, date):
        return ParseResult(raw)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if 20000 < raw < 80000:
            return ParseResult(_excel_serial(raw), warning=f"{field}: Excel serial {raw:g} converted to a date")
        return ParseResult(None, error=f"{field}: '{raw}' is not a date")
    s = str(raw).strip()
    s = re.sub(r"[T ]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$", "", s)
    fmts = ["%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%d-%b-%Y", "%d-%b-%y"]
    fmts += (["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"] if day_first
             else ["%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y", "%m/%d/%y"])
    for f in fmts:
        try:
            return ParseResult(datetime.strptime(s, f).date())
        except ValueError:
            continue
    return ParseResult(None, error=f"{field}: '{raw}' is not a recognised date (use YYYY-MM-DD or DD/MM/YYYY)")


def parse_datetime(raw: Any, *, field: str, day_first: bool = True) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    if isinstance(raw, datetime):
        return ParseResult(raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc))
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            return ParseResult(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    r = parse_date(raw, field=field, day_first=day_first)
    if r.value is not None:
        r.value = datetime(r.value.year, r.value.month, r.value.day, tzinfo=timezone.utc)
    return r


def parse_url(raw: Any) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).strip()
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", s, re.I):
        return ParseResult(None, error=f"source_url: '{s[:80]}' is not an http(s) URL")
    return ParseResult(s)


def parse_currency(raw: Any) -> ParseResult:
    if is_missing(raw):
        return ParseResult(None)
    s = str(raw).strip().upper()
    if s in {"₹", "RS", "RS.", "RUPEES", "INR"}:
        return ParseResult("INR")
    if re.fullmatch(r"[A-Z]{3}", s):
        return ParseResult(s)
    return ParseResult(None, error=f"currency: '{raw}' is not an ISO currency code")
