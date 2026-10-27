"""Deterministic procurement pricing engine.

Pure function of (group, observations, rules, as_of). No database access, no network, no AI.
All money arithmetic uses ``Decimal``; weights are floats (they never become money).

Pipeline (each step recorded in ``breakdown``):

    observed price → tax normalisation (ex-GST) → source-type conversion → weighted benchmark
    → condition (grade) adjustment → quantity-band adjustment → risk adjustment → rounding
    → recommended buy price  (+ negotiation opening, margin-constrained maximum, confidence)
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from .rules import PRICE_TYPES, Rules, canonical, rules_hash

ENGINE_VERSION = "pi-1.1.0"
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


@dataclass
class Obs:
    id: int
    price: Decimal | None
    currency: str
    tax_basis: str
    price_type: str
    match_quality: str
    observed_at: datetime
    source_key: str
    reliability: float
    status: str
    url: str | None = None
    title: str | None = None
    condition: str | None = None
    research_mode: str | None = None
    source_timestamp: str | None = None
    evidence_grade: str | None = None


@dataclass
class Group:
    category: str
    grade: str | None
    quantity: int
    risk_flags: list[str] = field(default_factory=list)
    identify_confidence: str = "high"
    high_severity_flags: int = 0
    policy_variant: str | None = None
    category_mape: float | None = None  # historical accuracy for the category, if measured


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round(v: Decimal, rules: Rules) -> Decimal:
    step = rules.rounding.step if rules.rounding.step > 0 else Decimal("1")
    units = v / step
    units = units.to_integral_value(rounding=ROUND_DOWN if rules.rounding.mode == "down" else ROUND_HALF_UP)
    return _q2(units * step)


def _wquantile(pairs: list[tuple[Decimal, float]], q: float) -> Decimal | None:
    """Weighted quantile (midpoint convention) returning an observed value or the mean of two."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    target = q * total
    cum = 0.0
    for i, (v, w) in enumerate(pairs):
        cum += w
        if math.isclose(cum, target, rel_tol=1e-9) and i + 1 < len(pairs):
            return (v + pairs[i + 1][0]) / 2
        if cum > target:
            return v
    return pairs[-1][0]


def _pct(v: Decimal | None) -> Decimal:
    return (v or ZERO) / HUNDRED


def price_group(group: Group, observations: list[Obs], rules: Rules, as_of: datetime) -> dict:
    cat = rules.category(group.policy_variant or group.category)
    gst = rules.gst_pct / HUNDRED
    assumptions: list[str] = [rules.policy_basis] if rules.policy_basis else []
    flags: list[str] = []
    rows: list[dict] = []
    missing_conversion: set[str] = set()

    # 1-3. screening, tax normalisation, source-type conversion
    for o in observations:
        r = {"id": o.id, "price_type": o.price_type, "price_type_label": PRICE_TYPES.get(o.price_type, o.price_type),
             "match_quality": o.match_quality, "observed": str(o.price) if o.price is not None else None,
             "currency": o.currency, "tax_basis": o.tax_basis, "observed_at": o.observed_at.isoformat(),
             "evidence_grade": o.evidence_grade, "research_mode": o.research_mode, "source_timestamp": o.source_timestamp,
             "source": o.source_key, "url": o.url, "title": o.title, "included": False, "exclusion": None,
             "ex_gst": None, "factor": None, "converted": None, "weight": None, "stale": False}
        rows.append(r)
        age = (as_of - o.observed_at).total_seconds() / 86400
        r["age_days"] = round(age, 1)
        if o.status != "verified":
            r["exclusion"] = "not verified (candidate search result)" if o.status == "candidate" else f"status {o.status}"
            continue
        if o.price is None or o.price <= 0:
            r["exclusion"] = "no price"
            continue
        if age < 0:
            r["exclusion"] = "observed after the valuation date"
            continue
        price = o.price
        if o.currency != rules.currency:
            fx = rules.fx_rates.get(o.currency)
            if fx is None:
                r["exclusion"] = f"currency {o.currency} with no FX rate configured"
                continue
            price = price * fx
            assumptions.append(f"Converted {o.currency} at {fx} per unit (configured FX rate)")
        fresh = rules.freshness_days.get(o.price_type, 30)
        if age > fresh:
            if o.price_type == "historical_valuation" and age <= rules.provisional_max_age_days:
                r["stale"] = True
            else:
                r["exclusion"] = f"older than {fresh} days ({int(age)} days)"
                continue
        basis = o.tax_basis
        if basis == "unknown":
            policy = rules.unknown_tax_basis.get(o.price_type, "exclude")
            if policy == "exclude":
                r["exclusion"] = "tax basis unknown (policy: exclude)"
                continue
            basis = policy
            assumptions.append(f"Unknown tax basis on {PRICE_TYPES.get(o.price_type, o.price_type)} assumed GST-{policy}")
        ex = price / (ONE + gst) if basis == "inclusive" else price
        r["ex_gst"] = str(_q2(ex))
        factor = cat.conversion.get(o.price_type)
        if factor is None:
            r["exclusion"] = "conversion factor to buy price not configured"
            missing_conversion.add(o.price_type)
            continue
        conv = ex * factor
        r["factor"] = str(factor)
        r["converted"] = str(_q2(conv))
        w = float(rules.price_type_weight.get(o.price_type, Decimal("0.5"))) * \
            float(rules.match_weight.get(o.match_quality, Decimal("0.5"))) * max(0.05, min(1.0, o.reliability)) * \
            0.5 ** (max(age, 0) / max(1, rules.half_life_days))
        r["_conv"], r["_w"], r["included"] = conv, w, True

    for t in sorted(missing_conversion):
        assumptions.append(f"Evidence of type '{PRICE_TYPES.get(t, t)}' ignored: conversion to a buy price is not "
                           f"configured for {cat.label}")

    included = [r for r in rows if r["included"]]
    # 4. evidence priority: buy-side evidence first; current evidence supersedes historical valuations
    if rules.prefer_top_tier and any(r["price_type"] in rules.top_tier_types and not r["stale"] for r in included):
        for r in included:
            if r["price_type"] not in rules.top_tier_types:
                r["included"], r["exclusion"] = False, "lower-priority evidence (buy-side evidence available)"
    included = [r for r in rows if r["included"]]
    if any(r["price_type"] != "historical_valuation" for r in included):
        for r in included:
            if r["price_type"] == "historical_valuation":
                r["included"], r["exclusion"] = False, "historical valuation superseded by current evidence"
    included = [r for r in rows if r["included"]]

    # independence: one source cannot dominate
    per_source: dict[str, int] = {}
    for r in included:
        per_source[r["source"]] = per_source.get(r["source"], 0) + 1
    for r in included:
        r["_w"] /= per_source[r["source"]]

    # outliers (scaled MAD)
    if len(included) >= rules.outlier_min_count:
        med = _wquantile([(r["_conv"], r["_w"]) for r in included], 0.5)
        mad = _wquantile([(abs(r["_conv"] - med), r["_w"]) for r in included], 0.5) or ZERO
        if mad > 0:
            lim = rules.outlier_mad_k * Decimal("1.4826") * mad
            for r in included:
                if abs(r["_conv"] - med) > lim:
                    r["included"], r["exclusion"] = False, f"outlier (> {rules.outlier_mad_k} scaled MAD from median)"
        included = [r for r in rows if r["included"]]

    for r in rows:
        if "_w" in r:
            r["weight"] = round(r["_w"], 4) if r["included"] else None

    base = {"engine_version": ENGINE_VERSION, "rules_name": rules.name, "rules_hash": rules_hash(rules),
            "as_of": as_of.isoformat(), "category": group.category, "policy_variant": group.policy_variant, "category_label": cat.label, "grade": group.grade,
            "group_quantity": group.quantity, "observations": [{k: v for k, v in r.items() if not k.startswith("_")}
                                                                for r in rows]}

    if not included:
        if missing_conversion:
            flags.append("conversion_not_configured")
        flags.append("no_market_evidence")
        return {**base, "status": "manual_required", "benchmark": None, "recommended_unit": None, "opening_unit": None,
                "max_unit": None, "resale_unit": None, "margin_pct": None, "confidence": None, "confidence_score": None,
                "confidence_parts": [], "steps": [], "assumptions": sorted(set(assumptions)), "flags": flags,
                "observation_ids": [], "message": "Research unavailable: insufficient verified evidence; review required"}

    pairs = [(r["_conv"], r["_w"]) for r in included]
    benchmark = _q2(_wquantile(pairs, 0.5))
    p25, p75 = _wquantile(pairs, 0.25), _wquantile(pairs, 0.75)
    dispersion = float((p75 - p25) / benchmark) if benchmark > 0 and len(included) > 1 else 0.0
    if dispersion > float(rules.extreme_variation_ratio):
        flags.append("extreme_price_variation")
    only_historical = all(r["price_type"] == "historical_valuation" for r in included)
    if any(r["stale"] for r in included):
        flags.append("stale_evidence")
    types_used = {r["price_type"] for r in included}

    steps = [{"step": "benchmark", "label": "Market benchmark (weighted median of converted evidence)",
              "value": str(benchmark), "detail": f"{len(included)} observation(s); P25 {_q2(p25)} · P75 {_q2(p75)}"}]

    # 5. condition adjustment (skipped when the evidence already reflects the grade)
    if types_used and (types_used.issubset(set(rules.grade_adjusted_types)) or
                       group.grade and all(r["evidence_grade"] == group.grade for r in included)):
        g_pct, g_note = ZERO, "evidence already reflects the asset grade"
    elif group.grade is None:
        g_pct, g_note = ZERO, "grade unknown: no grade adjustment (risk rule 'condition_unknown' may apply)"
    else:
        cfg = cat.grade_adjustment_pct.get(group.grade)
        if cfg is None:
            g_pct, g_note = ZERO, f"grade {group.grade} adjustment not configured (0% applied)"
            assumptions.append(f"Grade {group.grade} adjustment not configured for {cat.label}; 0% applied")
        else:
            g_pct, g_note = cfg, f"grade {group.grade}: {cfg}%"
    steps.append({"step": "condition", "label": "Condition / grade adjustment", "pct": str(g_pct), "detail": g_note})

    # 6. quantity band
    q_pct, q_note = ZERO, ""
    if types_used and types_used.issubset(set(rules.bulk_priced_types)):
        q_note = "evidence is already a bulk price"
    else:
        band = next((b for b in cat.quantity_bands if b.min_qty <= group.quantity and
                     (b.max_qty is None or group.quantity <= b.max_qty)), None)
        if band is None:
            q_note = "no quantity band matches"
        elif band.discount_pct is None:
            q_note = f"band {band.min_qty}–{band.max_qty or '∞'} discount not configured (0% applied)"
            if group.quantity >= 10:
                assumptions.append(f"Quantity band {band.min_qty}–{band.max_qty or '∞'} discount not configured for "
                                   f"{cat.label}; 0% applied")
        else:
            q_pct, q_note = band.discount_pct, f"{group.quantity} units → band {band.min_qty}–{band.max_qty or '∞'}: {band.discount_pct}%"
    steps.append({"step": "quantity", "label": "Quantity-band adjustment", "pct": str(q_pct), "detail": q_note})
    if cat.large_lot_threshold and group.quantity >= cat.large_lot_threshold:
        flags.append("large_lot")

    reflected_condition = types_used.issubset(set(rules.grade_adjusted_types))
    # 7. risk adjustments: within a group the largest applies (no double-discounting)
    by_group: dict[str, tuple[Decimal, str]] = {}
    for rr in rules.risk_rules:
        if rr.flag not in group.risk_flags:
            continue
        if rr.discount_pct is None:
            assumptions.append(f"Risk '{rr.label}' present but no adjustment configured")
            continue
        if reflected_condition:
            continue
        if rr.group == "condition" and g_pct and rr.flag in ("cosmetic_damage", "untested", "condition_unknown"):
            if rr.discount_pct <= g_pct:
                continue
            adjusted = (ONE - _pct(rr.discount_pct)) / (ONE - _pct(g_pct))
            rr = rr.model_copy(update={"discount_pct": (ONE - adjusted) * HUNDRED})
        if rr.group == "condition" and group.grade is not None and rr.flag == "condition_unknown":
            continue
        cur = by_group.get(rr.group)
        if cur is None or rr.discount_pct > cur[0]:
            by_group[rr.group] = (rr.discount_pct, rr.label)
    risk_factor = ONE
    for pct_, _ in by_group.values():
        risk_factor *= ONE - _pct(pct_)
    r_pct = _q2((ONE - risk_factor) * HUNDRED)
    steps.append({"step": "risk", "label": "Risk adjustments", "pct": str(r_pct),
                  "detail": "; ".join(f"{lbl} {p}%" for p, lbl in by_group.values()) or "none applied"})

    total_factor = (ONE - _pct(g_pct)) * (ONE - _pct(q_pct)) * risk_factor
    total_disc = (ONE - total_factor) * HUNDRED
    if rules.max_total_discount_pct is not None and total_disc > rules.max_total_discount_pct:
        total_factor = ONE - _pct(rules.max_total_discount_pct)
        steps.append({"step": "cap", "label": "Total discount cap", "pct": str(rules.max_total_discount_pct),
                      "detail": f"combined discount {_q2(total_disc)}% capped"})
    raw_rec = benchmark * total_factor
    recommended = _round(raw_rec, rules)
    steps.append({"step": "rounding", "label": f"Rounding ({rules.rounding.mode} to ₹{rules.rounding.step})",
                  "value": str(recommended), "detail": f"before rounding {_q2(raw_rec)}"})

    opening = _round(recommended * (ONE - _pct(cat.opening_discount_pct)), rules) if cat.opening_discount_pct is not None else None

    # 8. resale and margin (only with independently supported resale evidence and a configured realisation)
    resale_pairs = []
    for r in rows:
        f = cat.resale_realisation.get(r["price_type"])
        if r["ex_gst"] is not None and f is not None and r.get("exclusion") in (None, "lower-priority evidence (buy-side evidence available)",
                                                                                 "conversion factor to buy price not configured"):
            resale_pairs.append((Decimal(r["ex_gst"]) * f, 1.0))
    resale = _q2(_wquantile(resale_pairs, 0.5)) if resale_pairs else None
    costs = cat.purchase_cost_per_unit
    margin = max_unit = None
    if resale is not None and resale > 0:
        total_cost = recommended + (costs or ZERO)
        if costs is None:
            assumptions.append("Purchase-related costs per unit not configured; margin excludes them")
        margin = _q2((resale - total_cost) / resale * HUNDRED)
        if cat.min_margin_pct is not None:
            max_unit = _round(resale * (ONE - _pct(cat.min_margin_pct)) - (costs or ZERO), rules)
            if max_unit < recommended:
                flags.append("recommended_exceeds_margin_cap")
    if recommended <= 0:
        flags.append("non_positive_price")

    source_date_unknown = any(r["research_mode"] in ("live_search_confirmed", "cached_search")
                              and not r["source_timestamp"] for r in included)
    if source_date_unknown:
        assumptions.append("Confirmed offer has no source update date; retrieval date is not source freshness")
    status = "provisional" if source_date_unknown or any(r["research_mode"] == "similar_model_estimate" for r in included) or only_historical or all(r["match_quality"] != "identical" for r in included) else "priced"
    if recommended <= 0:
        status = "manual_required"

    # 9. confidence (transparent points)
    parts = []
    ident_share = sum(1 for r in included if r["match_quality"] == "identical") / len(included)
    parts.append(("Exact SKU / configuration match", round(25 * ident_share)))
    n_sources = len({r["source"] for r in included})
    parts.append((f"Independent sources ({n_sources})", round(20 * min(n_sources, 3) / 3)))
    rel = [o.reliability for o in observations if any(r["id"] == o.id for r in included)]
    parts.append(("Source reliability", round(10 * (sum(rel) / len(rel)) if rel else 0)))
    ages = [r["age_days"] for r in included]
    med_age = sorted(ages)[len(ages) // 2]
    parts.append((f"Freshness (median age {med_age:.0f} d)", round(15 * max(0.0, 1 - med_age / (2 * rules.half_life_days)))))
    parts.append((f"Price agreement (IQR/median {dispersion:.2f})",
                  15 if dispersion <= 0.10 else 10 if dispersion <= 0.25 else 5 if dispersion <= 0.5 else 0))
    parts.append(("Specification completeness", {"high": 10, "medium": 5}.get(group.identify_confidence, 0)
                  - min(10, 5 * group.high_severity_flags)))
    parts.append(("Condition certainty", 5 if group.grade else 0))
    if group.category_mape is not None:
        parts.append((f"Historical accuracy (MAPE {group.category_mape:.1f}%)",
                      0 if group.category_mape <= 10 else -5 if group.category_mape <= 25 else -10))
    score = max(0, min(100, sum(p for _, p in parts)))
    level = "High" if score >= rules.confidence.high else "Medium" if score >= rules.confidence.medium else "Low"
    if status == "provisional" and level == "High":
        level = "Medium"
        parts.append(("Provisional estimate cap", 0))

    modes = sorted({r["research_mode"] or ("historical" if r["price_type"] == "historical_valuation" else "verified_record") for r in included})
    return {**base, "research_methods": modes, "status": status, "benchmark": str(benchmark), "recommended_unit": str(recommended),
            "opening_unit": str(opening) if opening is not None else None,
            "max_unit": str(max_unit) if max_unit is not None else None,
            "resale_unit": str(resale) if resale is not None else None,
            "margin_pct": str(margin) if margin is not None else None,
            "confidence": level, "confidence_score": score,
            "confidence_parts": [{"label": l, "points": p} for l, p in parts], "steps": steps,
            "dispersion": round(dispersion, 4), "assumptions": sorted(set(assumptions)), "flags": sorted(set(flags)),
            "observation_ids": [r["id"] for r in included],
            "message": ("Provisional: based only on historical Casterly valuations" if only_historical else
                        "Provisional: source date unknown" if source_date_unknown else
                        "Provisional: comparable-model evidence only" if status == "provisional" else "Priced from dated verified evidence; inspect source dates and research methods")}


def input_hash(group: Group, observations: list[Obs], rules: Rules, as_of: datetime) -> str:
    payload = {"group": asdict(group), "obs": [{**asdict(o), "price": str(o.price), "observed_at": o.observed_at.isoformat()}
                                               for o in sorted(observations, key=lambda x: x.id)],
               "rules": rules_hash(rules), "as_of": as_of.date().isoformat(), "engine": ENGINE_VERSION}
    return hashlib.sha256(canonical(payload).encode()).hexdigest()
