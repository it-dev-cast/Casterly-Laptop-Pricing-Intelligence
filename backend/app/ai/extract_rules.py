"""Deterministic specification extraction from free-text descriptions.

Always available (no API key needed). Every suggestion carries the matched text
and a confidence; nothing is applied to a record until a user accepts it.
"""
from __future__ import annotations

import re

from .. import specs

BRANDS = ["dell", "hp", "lenovo", "apple", "asus", "acer", "msi", "microsoft", "samsung", "lg", "toshiba",
          "fujitsu", "panasonic", "huawei", "xiaomi", "razer", "gigabyte", "avita", "infinix", "realme"]

CPU_PATTERNS = [
    r"\bi[3579][\s-]?\d{4,5}[a-z]{0,2}\b",
    r"\bcore\s+ultra\s+\d\s*-?\s*\d{3}[a-z]{0,2}\b",
    r"\bryzen\s+[3579]\s+(?:pro\s+)?\d{4}[a-z]{0,2}\b",
    r"\bapple\s+m[1-4](?:\s+(?:pro|max|ultra))?\b|\bm[1-4]\s+(?:pro|max|ultra)\b|\b(?<![a-z0-9])m[1-4](?![a-z0-9])\s+chip\b",
    r"\bceleron\s+[a-z]?\d{4}[a-z]?\b",
    r"\bpentium\s+(?:gold\s+|silver\s+)?[a-z]?\d{4}[a-z]?\b",
    r"\bsnapdragon\s+x\s+(?:elite|plus)\b",
]


def _one(pattern: str, text: str, flags=re.I) -> tuple[str | None, int]:
    found = re.findall(pattern, text, flags)
    found = [f if isinstance(f, str) else f[0] for f in found]
    uniq = list(dict.fromkeys(x.strip() for x in found if x and x.strip()))
    return (uniq[0] if uniq else None), len(uniq)


def extract(text: str) -> dict[str, dict]:
    """Returns {field: {value, raw, confidence, method}}."""
    if not text:
        return {}
    t = " " + re.sub(r"\s+", " ", text) + " "
    out: dict[str, dict] = {}

    def put(field, value, raw, n):
        if value is None:
            return
        out[field] = {"value": value, "raw": raw, "confidence": "high" if n == 1 else "low", "method": "rule",
                      "note": None if n == 1 else f"{n} different candidates found; first used"}

    low = t.lower()
    brands = [b for b in BRANDS if re.search(rf"\b{b}\b", low)]
    if brands:
        put("brand", brands[0].upper() if len(brands[0]) <= 3 else brands[0].title(), brands[0], len(brands))
    for pat in CPU_PATTERNS:
        raw, n = _one(pat, t)
        if raw:
            put("cpu", raw, raw, n)
            break
    m = re.findall(r"\b(\d{1,2})\s*gb\s*(?:ddr\d\w*\s*)?(?:ram|memory)\b|\b(?:ram|memory)\s*[:\-]?\s*(\d{1,2})\s*gb\b",
                   t, re.I)
    vals = list(dict.fromkeys(a or b for a, b in m))
    if vals:
        put("ram_gb", int(vals[0]), f"{vals[0]} GB RAM", len(vals))
    m = re.findall(r"\b(\d+(?:\.\d+)?)\s*(tb|gb)\s*(nvme|ssd|hdd|emmc|sshd|m\.2)\b", t, re.I)
    if m:
        uniq = list(dict.fromkeys((a, b.lower(), c.lower()) for a, b, c in m))
        a, b, c = uniq[0]
        cap = specs.parse_capacity_gb(f"{a}{b}", field="storage_gb").value
        put("storage_gb", cap, f"{a}{b} {c}", len(uniq))
        put("storage_type", specs.parse_storage_type(c).value, c, len({x[2] for x in uniq}))
    raw, n = _one(r"\b(1[0-8](?:\.\d)?)\s*(?:\"|”|''|inch(?:es)?|in\b)", t)
    if raw:
        put("display_size_in", float(raw), raw, n)
    raw, n = _one(r"\b\d{3,4}\s*[x×]\s*\d{3,4}\b|\b(?:fhd\+?|full hd|qhd|wqhd|4k|uhd)\b", t)
    if raw:
        r = specs.parse_resolution(raw.replace("full hd", "fhd"))
        put("display_resolution", r.value, raw, n)
    raw, n = _one(r"\bgrade\s*[:\-]?\s*(a\+|[a-d])\b", t)
    if raw:
        put("condition_grade", raw.upper(), f"grade {raw}", n)
    raw, n = _one(r"\bbattery(?:\s*health)?\s*[:\-]?\s*(\d{2,3})\s*%", t)
    if raw:
        put("battery_health_pct", float(raw), f"battery {raw}%", n)
    if re.search(r"\b(without|no)\s+(charger|adapter)\b|\bcharger\s+(missing|not included)\b", low):
        put("charger_included", False, "no charger", 1)
    elif re.search(r"\bwith\s+(original\s+)?(charger|adapter)\b|\bcharger\s+included\b", low):
        put("charger_included", True, "with charger", 1)
    m = re.search(r"\b(\d{1,2})\s*(months?|yrs?|years?)\s*warranty\b|\bwarranty\s*[:\-]?\s*(\d{1,2})\s*(months?|yrs?|years?)\b", low)
    if m:
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        put("warranty_months", specs.parse_warranty_months(f"{num} {unit}").value, m.group(0), 1)
    gpu, n = _one(r"\b(?:rtx|gtx|mx)\s*\d{3,4}(?:\s*ti)?\b|\bradeon\s+(?:rx\s*)?\d{3,4}m?\b", t)
    if gpu:
        put("gpu", gpu.upper(), gpu, n)
    return out
