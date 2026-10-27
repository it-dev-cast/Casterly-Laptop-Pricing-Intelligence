"""Deduplication of repeated listings, syndicated offers, and duplicate records.

Groups are formed with union-find; each group keeps one representative (the most
recent observation, ties broken by id) and every other member is excluded with
the reason that linked it.
"""
from __future__ import annotations

from .config import DedupRules
from .matching import dim_str
from .types import SPEC_FIELDS, Evidence


def _config_sig(e: Evidence) -> tuple:
    return tuple(dim_str(getattr(e, f)) for f in SPEC_FIELDS)


def _seller(e: Evidence) -> str | None:
    s = (e.seller or "").strip().lower()
    return s or None


def _within(a: float, b: float, tol_pct: float) -> bool:
    hi = max(a, b)
    return hi > 0 and abs(a - b) / hi * 100 <= tol_pct


def _days_apart(a: Evidence, b: Evidence) -> int | None:
    if a.event_date is None or b.event_date is None:
        return None
    return abs((a.event_date - b.event_date).days)


def _recency_key(e: Evidence) -> tuple:
    return (e.event_date.isoformat() if e.event_date else "", e.observed_at.isoformat() if e.observed_at else "", e.id)


def deduplicate(records: list[Evidence], prices: dict[str, float], rules: DedupRules) -> dict[str, tuple[str, str]]:
    """Return {excluded_id: (representative_id, reason)}.

    ``prices`` holds the tax-normalised price of each record so that a GST-inclusive
    and a GST-exclusive copy of the same offer are recognised as the same offer.
    """
    parent = {r.id: r.id for r in records}
    reason: dict[tuple[str, str], str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str, why: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        reason.setdefault((min(a, b), max(a, b)), why)

    recs = sorted(records, key=lambda r: r.id)
    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            if a.kind != b.kind:
                continue
            if a.source_url and a.source_url == b.source_url:
                union(a.id, b.id, "Same source URL observed more than once")
                continue
            if a.source_record_id and a.source_record_id == b.source_record_id and \
                    (a.platform or a.seller or "") == (b.platform or b.seller or ""):
                union(a.id, b.id, f"Same source record id '{a.source_record_id}' observed more than once")
                continue
            if a.kind != "listing" or _config_sig(a) != _config_sig(b):
                continue
            pa, pb = prices.get(a.id), prices.get(b.id)
            if pa is None or pb is None:
                continue
            gap = _days_apart(a, b)
            if _seller(a) and _seller(a) == _seller(b) and _within(pa, pb, rules.repeat_price_tolerance_pct) \
                    and gap is not None and gap <= rules.repeat_window_days:
                union(a.id, b.id, f"Repeated listing by the same seller within {rules.repeat_window_days} days "
                                  f"(price within {rules.repeat_price_tolerance_pct:g}%)")
                continue
            if a.title_key and a.title_key == b.title_key and _seller(a) != _seller(b) \
                    and _within(pa, pb, rules.syndication_price_tolerance_pct) \
                    and gap is not None and gap <= rules.syndication_window_days:
                union(a.id, b.id, "Syndicated offer: identical title and price across sellers/platforms")

    groups: dict[str, list[Evidence]] = {}
    for r in recs:
        groups.setdefault(find(r.id), []).append(r)
    out: dict[str, tuple[str, str]] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = max(members, key=_recency_key)
        for m in members:
            if m.id == keep.id:
                continue
            why = reason.get((min(m.id, keep.id), max(m.id, keep.id)))
            if why is None:  # linked transitively
                why = next((v for (x, y), v in sorted(reason.items()) if m.id in (x, y)), "Duplicate group")
            out[m.id] = (keep.id, why)
    return out
