"""Historical pricing intelligence: outcomes, accuracy metrics and rule-adjustment suggestions.

Accuracy compares the *recommended buy price* that was current when an outcome happened with the
actual purchase price recorded for the same product. Resale outcomes are compared with the
estimate's expected resale value when one existed. Suggestions are advisory: applying one creates
a new rule version through the normal, audited rules workflow; nothing changes automatically.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone
from decimal import Decimal
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PIEstimate, PIOutcome, PIProduct
from .rules import ASKING_TYPES


def _pairs(db: Session, kind: str, category: str | None = None) -> list[dict]:
    q = select(PIOutcome, PIProduct).join(PIProduct, PIProduct.id == PIOutcome.product_id).where(PIOutcome.kind == kind)
    if category:
        q = q.where(PIProduct.category == category)
    out = []
    for o, p in db.execute(q).all():
        at = datetime.combine(o.outcome_date, time(23, 59), tzinfo=timezone.utc)
        est = db.scalar(select(PIEstimate).where(PIEstimate.product_id == p.id, PIEstimate.as_of <= at,
                                                 PIEstimate.status != "manual_required")
                        .order_by(PIEstimate.as_of.desc(), PIEstimate.id.desc()).limit(1))
        if est is None:
            continue
        predicted = est.recommended_unit if kind == "purchase" else est.resale_unit
        if predicted is None or o.unit_price is None or o.unit_price <= 0:
            continue
        err = Decimal(predicted) - Decimal(o.unit_price)
        out.append({"outcome_id": o.id, "product_id": p.id, "product": p.label, "category": p.category,
                    "date": o.outcome_date.isoformat(), "predicted": float(predicted), "actual": float(o.unit_price),
                    "error": float(err), "ape": float(abs(err) / Decimal(o.unit_price) * 100),
                    "signed_pct": float(err / Decimal(o.unit_price) * 100), "estimate_id": est.id,
                    "price_types": sorted({r["price_type"] for r in est.breakdown.get("observations", []) if r.get("included")})})
    return out


def _metrics(pairs: list[dict]) -> dict:
    if not pairs:
        return {"n": 0, "mae": None, "mape": None, "median_ape": None, "bias_pct": None}
    return {"n": len(pairs), "mae": round(sum(abs(p["error"]) for p in pairs) / len(pairs), 2),
            "mape": round(sum(p["ape"] for p in pairs) / len(pairs), 2),
            "median_ape": round(median(p["ape"] for p in pairs), 2),
            "bias_pct": round(sum(p["signed_pct"] for p in pairs) / len(pairs), 2)}


def category_mape(db: Session, category: str) -> float | None:
    m = _metrics(_pairs(db, "purchase", category))
    return m["mape"] if m["n"] >= 5 else None


def report(db: Session) -> dict:
    out = {}
    for kind in ("purchase", "resale"):
        pairs = _pairs(db, kind)
        by_cat = defaultdict(list)
        for p in pairs:
            by_cat[p["category"]].append(p)
        out[kind] = {"overall": _metrics(pairs), "by_category": {c: _metrics(v) for c, v in sorted(by_cat.items())},
                     "pairs": pairs[-200:]}
    out["note"] = ("Purchase accuracy compares the recommended buy price current at the outcome date with the actual "
                   "purchase price. Requires recorded outcomes; no outcome is inferred.")
    return out


def suggestions(db: Session, rules, min_n: int = 5) -> list[dict]:
    """Suggest conversion-factor changes where purchase predictions are consistently biased."""
    pairs = _pairs(db, "purchase")
    by_cat = defaultdict(list)
    for p in pairs:
        by_cat[p["category"]].append(p)
    out = []
    for cat, ps in by_cat.items():
        if len(ps) < min_n:
            continue
        bias = median(p["signed_pct"] for p in ps)
        if abs(bias) < 5:
            continue
        crules = rules.category(cat)
        for t in ASKING_TYPES:
            cur = crules.conversion.get(t)
            if cur is None or not any(t in p["price_types"] for p in ps):
                continue
            proposed = (Decimal(cur) / (Decimal(1) + Decimal(str(bias)) / 100)).quantize(Decimal("0.0001"))
            out.append({"category": cat, "price_type": t, "current": str(cur), "proposed": str(proposed),
                        "median_bias_pct": round(bias, 2), "n": len(ps),
                        "reason": f"Recommended buy prices were {'above' if bias > 0 else 'below'} actual purchase "
                                  f"prices by a median {abs(bias):.1f}% across {len(ps)} outcomes"})
    return out
