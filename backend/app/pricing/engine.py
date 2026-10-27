"""The valuation engine. Pure and deterministic: same inputs -> byte-identical output.

It never calls a language model, never reads the database, and never invents a
number. Every weight, exclusion, adjustment and assumption is recorded in the
returned dict so a valuation can be audited and reproduced.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from .config import PricingConfig, canonical_json
from .dedup import deduplicate
from .economics import CostInputs, solve_buy_price, unit_economics
from .matching import DIMENSION_LABELS, match
from .stats import kish_effective_n, weighted_mad, weighted_median, weighted_quantile
from .types import Evidence, Subject

ENGINE_VERSION = "1.0.0"

KIND_LABEL = {"sale": "Completed sale", "listing": "Advertised listing (asking price)",
              "quote": "Supplier quotation", "purchase": "Completed purchase"}
SET_LABEL = {"sale": "Completed sales", "listing": "Advertised asking prices",
             "quote": "Supplier quotations", "purchase": "Completed purchases"}
DEFINITIONS = {
    "margin": "Contribution margin = contribution / sale revenue (ex-GST).",
    "markup": "Markup = contribution / total cost (purchase + repair + costs + fees). Shown separately; never used as margin.",
    "target_buy": "Highest purchase price per unit that still achieves the target contribution margin at the median expected sale price.",
    "max_safe_buy": "Purchase price per unit at which the minimum ceiling margin is still achieved at the conservative (25th percentile) sale price.",
    "recommended_buy": "The lower of the target buying price and the maximum safe buying price.",
    "rating": "Evidence-quality rating: a transparent points score over count, sources, freshness, exact-match coverage, dispersion and evidence type. It is NOT a calibrated probability.",
    "prices": "Selling prices are tax-inclusive (what the buyer pays) unless labelled ex-GST.",
}


class _Assumptions:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def add(self, code: str, text: str, severity: str = "info", count: int | None = None) -> None:
        if code in self.items and count is not None:
            self.items[code]["count"] = (self.items[code].get("count") or 0) + count
            return
        self.items.setdefault(code, {"code": code, "text": text, "severity": severity,
                                     **({"count": count} if count is not None else {})})

    def as_list(self) -> list[dict]:
        order = {"warning": 0, "info": 1}
        return sorted(self.items.values(), key=lambda a: (order.get(a["severity"], 2), a["code"]))


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def _fault_category(subject: Subject, cfg: PricingConfig) -> tuple[str | None, str]:
    if subject.fault_category:
        return subject.fault_category, "recorded on the item"
    if subject.faults is None:
        return None, "faults not recorded"
    if len(subject.faults) == 0:
        return "none", "item records no faults"
    text = " ".join(subject.faults).lower()
    for fc in cfg.fault_categories:
        if any(k in text for k in fc.match_keywords):
            return fc.key, f"derived from fault text by keyword ('{', '.join(subject.faults)}')"
    return "other", "fault text matched no category keyword"


def _estimate(name: str, comps: list[dict], cfg: PricingConfig, as_of_date) -> dict:
    """Select, weight, trim and summarise one evidence set. Mutates comps' inclusion fields."""
    m = cfg.matching
    first = [c for c in comps if c["match_tier"] in ("exact", "unverified")]
    adjusted = [c for c in comps if c["match_tier"] == "adjusted"]
    broadened = False
    use = list(first)
    if len(first) < m.min_comparables and adjusted:
        use += adjusted
        broadened = True
    else:
        for c in adjusted:
            c.update(included=False, exclusion=f"Adjusted match not needed: {len(first)} exact/unverified "
                                                f"comparables meet the minimum of {m.min_comparables}")
    tier_w = {"exact": m.weight_exact, "unverified": m.weight_unverified, "adjusted": m.weight_adjusted}
    for c in use:
        rec = 0.5 ** (c["age_days"] / m.recency_half_life_days)
        c["weights"] = {"recency": round(rec, 6), "match": tier_w[c["match_tier"]]}
    # Robust outlier screen on (recency x match) weights.
    if m.outlier_mad_k and len(use) >= m.outlier_min_count:
        vals = [c["adjusted_price"] for c in use]
        ws = [c["weights"]["recency"] * c["weights"]["match"] for c in use]
        med = weighted_median(vals, ws)
        mad = weighted_mad(vals, ws, med)
        if mad and mad > 0:
            limit = m.outlier_mad_k * 1.4826 * mad
            keep = []
            for c in use:
                if abs(c["adjusted_price"] - med) > limit:
                    c.update(included=False, exclusion=(
                        f"Outlier: {c['adjusted_price']:,.0f} is more than {m.outlier_mad_k:g} x scaled MAD "
                        f"({limit:,.0f}) from the weighted median {med:,.0f}"))
                    c.pop("weights", None)
                else:
                    keep.append(c)
            use = keep
    counts: dict[str, int] = {}
    for c in use:
        counts[c["source_key"]] = counts.get(c["source_key"], 0) + 1
    for c in use:
        share = 1 / counts[c["source_key"]] if m.split_weight_by_source else 1.0
        c["weights"]["source_share"] = round(share, 6)
        c["weights"]["final"] = round(c["weights"]["recency"] * c["weights"]["match"] * share, 6)
        c["included"] = True
        c["exclusion"] = None
    vals = [c["adjusted_price"] for c in use]
    ws = [c["weights"]["final"] for c in use]
    n = len(use)
    sources = len(counts)
    q = {f"p{int(p * 100)}": _r(weighted_quantile(vals, ws, p)) for p in (0.10, 0.25, 0.50, 0.75, 0.90)} if use else \
        {"p10": None, "p25": None, "p50": None, "p75": None, "p90": None}
    exact_n = sum(1 for c in use if c["match_tier"] == "exact")
    ages = [c["age_days"] for c in use]
    out = {
        "set": name, "count": n, "independent_sources": sources,
        "effective_n": _r(kish_effective_n(ws), 2) if use else 0,
        "broadened_with_adjustments": broadened,
        "exact_count": exact_n, "exact_share": _r(exact_n / n, 4) if n else None,
        "adjusted_count": sum(1 for c in use if c["match_tier"] == "adjusted"),
        "weighted_median_age_days": _r(weighted_median(ages, ws), 1) if use else None,
        "oldest_age_days": max(ages) if ages else None, "newest_age_days": min(ages) if ages else None,
        **q,
        "dispersion_iqr_over_median": _r((q["p75"] - q["p25"]) / q["p50"], 4) if use and q["p50"] else None,
        "sufficient": n >= m.min_comparables and sources >= m.min_independent_sources,
        "requirement": f"at least {m.min_comparables} comparables from {m.min_independent_sources} independent sources",
    }
    return out


def _rating(est: dict, basis: str, missing_fields: list[str], cfg: PricingConfig) -> dict:
    r = cfg.rating
    comps = []

    def tiered(label, value, table, fmt, higher_is_better=True):
        pts = 0
        if value is not None:
            for thr, p in table:
                if (value >= thr) if higher_is_better else (value <= thr):
                    pts = p
                    break
        comps.append({"component": label, "value": fmt(value) if value is not None else "n/a", "points": pts,
                      "max_points": max(p for _, p in table)})

    tiered("Comparable count", est["count"], r.count_points, lambda v: f"{v}")
    tiered("Independent sources", est["independent_sources"], r.source_points, lambda v: f"{v}")
    tiered("Freshness (weighted median age, days)", est["weighted_median_age_days"], r.freshness_points,
           lambda v: f"{v:g}", higher_is_better=False)
    tiered("Exact-match coverage", est["exact_share"], r.exact_share_points, lambda v: f"{v * 100:.0f}%")
    tiered("Price dispersion (IQR / median)", est["dispersion_iqr_over_median"], r.dispersion_points,
           lambda v: f"{v * 100:.1f}%", higher_is_better=False)
    ev_pts = r.sales_basis_points if basis == "completed_sales" else r.asking_basis_points
    comps.append({"component": "Evidence type", "value": "Completed sales" if basis == "completed_sales"
                  else "Asking prices x configured ratio", "points": ev_pts, "max_points": r.sales_basis_points})
    pen = -r.missing_field_penalty * len(missing_fields)
    comps.append({"component": "Missing subject fields", "value": ", ".join(missing_fields) or "none",
                  "points": pen, "max_points": 0})
    score = max(0, sum(c["points"] for c in comps))
    grade = next(g for thr, g in r.grade_thresholds if score >= thr)
    return {"grade": grade, "score": score, "max_score": sum(c["max_points"] for c in comps), "components": comps,
            "note": DEFINITIONS["rating"]}


def value_item(subject: Subject, evidence: list[Evidence], cfg: PricingConfig, as_of: datetime) -> dict:
    A = _Assumptions()
    g = cfg.tax.gst_rate_pct / 100
    as_of_date = as_of.date()
    m = cfg.matching
    channel = subject.intended_channel
    if not channel:
        channel = cfg.default_channel
        A.add("default_channel", f"Intended channel not set on the item; configured default '{channel}' used.", "warning")

    A.add("tax_mode", f"Tax mode '{cfg.tax.mode}', GST {cfg.tax.gst_rate_pct:g}% ({cfg.tax.gst_rate_basis}). "
                      "All evidence is normalised to a tax-inclusive price before comparison.")
    A.add("weights", f"Weights = recency (half-life {m.recency_half_life_days:g} days) x match tier "
                     f"(exact {m.weight_exact:g}, unverified {m.weight_unverified:g}, adjusted {m.weight_adjusted:g})"
                     + (" x 1/(records from the same source)." if m.split_weight_by_source else ".")
                     + " These are configured statistical choices, not calibrated values.")
    A.add("quantiles", "Ranges are weighted quantiles (midpoint method); expected price is the weighted median.")
    if m.outlier_mad_k:
        A.add("outliers", f"Records more than {m.outlier_mad_k:g} x scaled MAD from the weighted median are "
                          f"excluded when a set has at least {m.outlier_min_count} records.")
    A.add("asking_vs_sales", "Advertised asking prices are kept separate and are never treated as completed sales.")

    comps: list[dict] = []
    candidates: list[Evidence] = []
    prices: dict[str, float] = {}
    by_id: dict[str, dict] = {}

    for ev in sorted(evidence, key=lambda e: e.id):
        c = {
            "id": ev.id, "kind": ev.kind, "kind_label": KIND_LABEL.get(ev.kind, ev.kind), "channel": ev.channel,
            "seller": ev.seller, "platform": ev.platform, "source_key": ev.source_key, "source_url": ev.source_url,
            "source_document": ev.source_document, "source_record_id": ev.source_record_id,
            "event_date": ev.event_date.isoformat() if ev.event_date else None,
            "observed_at": ev.observed_at.isoformat() if ev.observed_at else None,
            "price": ev.price, "currency": ev.currency, "tax_basis": ev.tax_basis, "availability": ev.availability,
            "is_synthetic": ev.is_synthetic,
            "spec": {k: getattr(ev, k) for k in ("cpu_key", "ram_gb", "storage_type", "storage_gb", "condition_grade",
                                                 "battery_health_pct", "gpu_key", "display_size_in",
                                                 "display_resolution", "charger_included", "warranty_months")},
            "gross_price": None, "adjusted_price": None, "age_days": None, "match_tier": None,
            "unverified_dimensions": [], "adjustments": [], "weights": None,
            "included": False, "exclusion": None, "set": None, "duplicate_of": None,
        }
        comps.append(c)
        by_id[ev.id] = c
        reason = None
        gross = None
        if ev.is_synthetic != subject.is_synthetic:
            reason = ("Synthetic demo evidence is never used for real inventory" if ev.is_synthetic
                      else "Real evidence is not mixed into a synthetic demo valuation")
        elif ev.brand_key != subject.brand_key or ev.model_key != subject.model_key:
            reason = "Different brand/model"
        elif ev.price is None or ev.price <= 0:
            reason = "No usable price"
        elif not ev.channel and ev.kind in ("sale", "listing"):
            reason = "Channel unknown: cannot assign to retail / wholesale / as-is evidence"
        else:
            price = ev.price
            cur = (ev.currency or "").upper()
            if not cur:
                reason = "Currency missing"
            elif cur != "INR":
                fx = cfg.fx_rates_to_inr.get(cur)
                if not fx:
                    reason = f"Currency {cur} with no configured INR rate"
                else:
                    price = price * fx
                    A.add(f"fx_{cur}", f"{cur} converted at configured rate {fx:g} INR.", "warning", 1)
            if reason is None:
                if ev.tax_basis == "inclusive":
                    gross = price
                elif ev.tax_basis == "exclusive":
                    gross = price * (1 + g)
                else:
                    policy = cfg.tax.unknown_tax_basis.get(ev.kind, "exclude")
                    if policy == "exclude":
                        reason = "Tax basis unknown (configured to exclude for this evidence type)"
                    elif policy == "assume_inclusive":
                        gross = price
                        A.add(f"tax_assumed_inclusive_{ev.kind}", f"{SET_LABEL[ev.kind]} with unknown tax basis "
                              "were assumed GST-inclusive (configured).", "warning", 1)
                    else:
                        gross = price * (1 + g)
                        A.add(f"tax_assumed_exclusive_{ev.kind}", f"{SET_LABEL[ev.kind]} with unknown tax basis "
                              "were assumed GST-exclusive (configured).", "warning", 1)
            if reason is None:
                ref = ev.event_date or (ev.observed_at.date() if ev.observed_at else None)
                max_age = cfg.freshness.max_age_days.get(ev.kind)
                if ref is None:
                    reason = "No listing/transaction date: freshness cannot be established"
                elif ref > as_of_date:
                    reason = "Dated after the valuation date"
                elif ev.observed_at and ev.observed_at > as_of:
                    reason = "Observed after the valuation time"
                else:
                    c["age_days"] = (as_of_date - ref).days
                    if max_age is not None and c["age_days"] > max_age:
                        reason = f"Stale: {c['age_days']} days old (limit {max_age} days for {SET_LABEL[ev.kind].lower()})"
            if reason is None and ev.kind == "listing" and cfg.freshness.exclude_unavailable_listings \
                    and ev.availability in ("out_of_stock", "removed"):
                reason = f"Unavailable listing ({ev.availability.replace('_', ' ')})"
            if reason is None and ev.kind == "quote" and cfg.freshness.exclude_expired_quotes \
                    and ev.valid_until and ev.valid_until < as_of_date:
                reason = f"Quotation expired on {ev.valid_until.isoformat()}"
        if reason:
            c["exclusion"] = reason
            continue
        c["gross_price"] = _r(gross)
        candidates.append(ev)
        prices[ev.id] = gross

    for dup_id, (keep_id, why) in deduplicate(candidates, prices, cfg.dedup).items():
        by_id[dup_id].update(exclusion=f"Duplicate of {keep_id}: {why}", duplicate_of=keep_id)

    sets: dict[str, list[dict]] = {}
    for ev in candidates:
        c = by_id[ev.id]
        if c["duplicate_of"]:
            continue
        mo = match(subject, ev, cfg)
        if mo.tier is None:
            c["exclusion"] = mo.exclusion
            continue
        price = prices[ev.id]
        adj = []
        for a in sorted(mo.adjustments, key=lambda a: a.dimension):
            before = price
            price = a.apply(price)
            adj.append(a.to_dict(before, price))
            A.add(f"adjustment_{a.rule_id}", f"Adjustment rule '{a.rule_id}' ({DIMENSION_LABELS.get(a.dimension)} "
                  f"{a.comparable_value} -> {a.subject_value}: {a.method} {a.value:+g}) is "
                  + ("calibrated" if a.calibrated else "an UNCALIBRATED assumption")
                  + (f"; basis: {a.basis}" if a.basis else "; no basis recorded") + ".",
                  "info" if a.calibrated else "warning")
        c.update(match_tier=mo.tier, unverified_dimensions=mo.unverified, adjustments=adj, adjusted_price=_r(price))
        set_name = ev.kind if ev.kind in ("quote", "purchase") else f"{ev.kind}:{ev.channel}"
        c["set"] = set_name
        sets.setdefault(set_name, []).append(c)

    estimates = {name: _estimate(name, members, cfg, as_of_date) for name, members in sorted(sets.items())}

    def est(name: str) -> dict | None:
        return estimates.get(name)

    # ------------------------------------------------------------ selling basis
    ch_costs = cfg.channels.get(channel)
    sale_est, list_est = est(f"sale:{channel}"), est(f"listing:{channel}")
    basis = None
    p = {}
    basis_note = ""
    if sale_est and sale_est["sufficient"]:
        basis, basis_est = "completed_sales", sale_est
        p = {k: sale_est[k] for k in ("p10", "p25", "p50", "p75", "p90")}
        basis_note = f"Weighted quantiles of {sale_est['count']} comparable completed {channel} sales."
    elif list_est and list_est["sufficient"] and ch_costs and ch_costs.asking_to_sale_ratio:
        ratio = ch_costs.asking_to_sale_ratio
        basis, basis_est = "asking_adjusted", list_est
        p = {k: _r(list_est[k] * ratio) for k in ("p10", "p25", "p50", "p75", "p90")}
        basis_note = (f"No sufficient completed-sales evidence; {list_est['count']} asking prices x configured "
                      f"asking-to-sale ratio {ratio:g}.")
        A.add("asking_ratio", f"Expected sale prices derived from asking prices using the configured ratio {ratio:g} "
              f"({ch_costs.asking_to_sale_ratio_basis or 'no basis recorded; uncalibrated'}).", "warning")
    else:
        basis_est = sale_est or list_est

    def ex_gst(v):
        if v is None:
            return None
        return _r(v / (1 + g)) if cfg.tax.mode == "standard" else v

    missing_fields = [DIMENSION_LABELS.get(d, d) for d in m.required_dimensions + m.optional_dimensions
                      if getattr(subject, d) is None]
    if subject.battery_health_pct is None:
        missing_fields.append("Battery health")
    if subject.faults is None and not subject.fault_category:
        missing_fields.append("Faults")
    needs_input: list[str] = []
    messages: list[str] = []
    for d in m.required_dimensions:
        if getattr(subject, d) is None:
            needs_input.append(f"{DIMENSION_LABELS.get(d, d)} is missing on the item; exact matching is impossible.")

    selling = None
    if basis:
        selling = {"basis": basis, "basis_note": basis_note, "channel": channel,
                   **{f"{k}_gross": v for k, v in p.items()},
                   **{f"{k}_ex_gst": ex_gst(v) for k, v in p.items()}}
    else:
        req = f"at least {m.min_comparables} comparables from {m.min_independent_sources} independent sources"
        why = [f"completed {channel} sales: {sale_est['count'] if sale_est else 0} usable"]
        if list_est:
            why.append(f"asking prices: {list_est['count']} usable"
                       + ("" if (ch_costs and ch_costs.asking_to_sale_ratio)
                          else " (no asking-to-sale ratio configured, so asking prices cannot stand in for sales)"))
        messages.append(f"Insufficient evidence for a dependable {channel} selling estimate: needs {req}; "
                        + "; ".join(why) + ".")

    listing_rec = None
    if list_est and list_est["sufficient"]:
        listing_rec = {"price_gross": list_est["p50"], "basis": "Weighted median of comparable asking prices",
                       "range_gross": [list_est["p25"], list_est["p75"]]}
    elif basis == "completed_sales":
        listing_rec = {"price_gross": p["p75"], "basis": "No sufficient comparable listings; upper quartile of "
                       "completed sales", "range_gross": [p["p50"], p["p75"]]}

    wholesale = {"supported": False, "note": "Not supported by sufficient wholesale evidence."}
    ws_sale, ws_list = est("sale:wholesale"), est("listing:wholesale")
    if ws_sale and ws_sale["sufficient"]:
        wholesale = {"supported": True, "basis": "completed_sales", "p25_gross": ws_sale["p25"],
                     "p50_gross": ws_sale["p50"], "p75_gross": ws_sale["p75"], "count": ws_sale["count"]}
    elif ws_list and ws_list["sufficient"]:
        wholesale = {"supported": True, "basis": "asking_prices", "p25_gross": ws_list["p25"],
                     "p50_gross": ws_list["p50"], "p75_gross": ws_list["p75"], "count": ws_list["count"],
                     "note": "Wholesale ASKING prices, not completed sales."}

    def buy_basis(gross):
        return ex_gst(gross) if cfg.tax.mode == "standard" else gross

    procurement = {}
    for k in ("quote", "purchase"):
        e = est(k)
        if e:
            procurement[k] = {"label": SET_LABEL[k], "count": e["count"], "sufficient": e["sufficient"],
                              "p25_buy_basis": buy_basis(e["p25"]), "p50_buy_basis": buy_basis(e["p50"]),
                              "p75_buy_basis": buy_basis(e["p75"])}

    # ------------------------------------------------------------ economics inputs
    target_margin = subject.target_margin_pct
    tm_src = "item"
    if target_margin is None:
        target_margin, tm_src = cfg.default_target_margin_pct, "configured default"
    if target_margin is None:
        needs_input.append("Target contribution margin is not set on the item or as a configured default.")
    fcat_key, fcat_src = _fault_category(subject, cfg)
    fcat = cfg.fault(fcat_key) if fcat_key else None
    yield_pct, y_src = subject.expected_yield_pct, "item"
    if yield_pct is None and fcat and fcat.expected_yield_pct is not None:
        yield_pct, y_src = fcat.expected_yield_pct, f"fault category '{fcat.label}'"
    if yield_pct is None:
        needs_input.append("Expected saleable yield is not set on the item"
                           + (f" or for fault category '{fcat.label}'" if fcat else " and faults are not recorded")
                           + ". Every unit selling cannot be assumed.")
    repair, r_src = subject.refurbishment_cost, "item"
    if repair is None and fcat and fcat.repair_cost_per_unit is not None:
        repair, r_src = fcat.repair_cost_per_unit, f"fault category '{fcat.label}'"
    if repair is None:
        if fcat_key == "none":
            repair, r_src = 0.0, "not provided; item has no recorded faults, treated as 0"
            A.add("repair_zero", "Refurbishment cost not provided for a no-fault item; treated as 0. Enter an "
                  "explicit value to remove this warning.", "warning")
        else:
            needs_input.append("Refurbishment / repair cost is not set on the item or for its fault category.")
    salvage, s_src = subject.salvage_value, "item"
    if salvage is None and fcat and fcat.salvage_value_per_unit is not None:
        salvage, s_src = fcat.salvage_value_per_unit, f"fault category '{fcat.label}'"
    if salvage is None:
        salvage, s_src = 0.0, "not configured; unsold units assumed to recover nothing (conservative)"

    fee_gross = fee_net = 0.0
    fixed_sold = 0.0
    cost_lines = []
    for f in (ch_costs.percentage_fees if ch_costs else []):
        if f.rate_pct is None:
            A.add(f"fee_unset_{f.name}", f"{channel.title()} fee '{f.name}' is not configured; treated as 0%.", "warning")
        rate = (f.rate_pct or 0) / 100
        if f.base == "gross_incl_tax":
            fee_gross += rate
        else:
            fee_net += rate
        cost_lines.append({"name": f.name, "type": f"% of {'tax-inclusive' if f.base == 'gross_incl_tax' else 'ex-GST'} "
                           "sale price", "value": f.rate_pct, "configured": f.rate_pct is not None})
    for fc in (ch_costs.fixed_costs_per_sold_unit if ch_costs else []):
        if fc.amount is None:
            A.add(f"cost_unset_{fc.name}", f"{channel.title()} cost '{fc.name}' is not configured; treated as 0.", "warning")
        fixed_sold += fc.amount or 0
        cost_lines.append({"name": fc.name, "type": "INR per sold unit", "value": fc.amount,
                           "configured": fc.amount is not None})
    fixed_purchased = 0.0
    for fc in cfg.fixed_costs_per_purchased_unit:
        if fc.amount is None:
            A.add(f"cost_unset_{fc.name}", f"Cost '{fc.name}' is not configured; treated as 0.", "warning")
        fixed_purchased += fc.amount or 0
        cost_lines.append({"name": fc.name, "type": "INR per purchased unit", "value": fc.amount,
                           "configured": fc.amount is not None})

    econ = {"inputs": {
        "channel": channel, "tax_mode": cfg.tax.mode, "gst_rate_pct": cfg.tax.gst_rate_pct,
        "target_margin_pct": target_margin, "target_margin_source": tm_src,
        "minimum_margin_for_ceiling_pct": cfg.minimum_margin_pct_for_ceiling,
        "fault_category": fcat_key, "fault_category_source": fcat_src,
        "expected_yield_pct": yield_pct, "yield_source": y_src,
        "repair_cost_per_unit": repair, "repair_source": r_src,
        "salvage_per_unsold_unit": salvage, "salvage_source": s_src,
        "cost_lines": cost_lines,
        "buy_price_basis": "ex-GST (input tax assumed recoverable)" if cfg.tax.mode == "standard"
        else "total price paid (no input tax credit)",
    }, "flags": []}
    lot = None
    qty = subject.quantity
    if basis and yield_pct is not None and repair is not None:
        ci = CostInputs(cfg.tax.mode, g, yield_pct / 100, salvage, repair, fixed_purchased, fixed_sold, fee_gross, fee_net)
        ceiling = solve_buy_price(p["p25"], ci, margin=cfg.minimum_margin_pct_for_ceiling / 100)
        target = solve_buy_price(p["p50"], ci, margin=target_margin / 100) if target_margin is not None else None
        recommended = None
        if ceiling is not None and target is not None:
            recommended = min(target, ceiling)
        econ.update(target_buy=target, max_safe_buy=ceiling, recommended_buy=recommended)
        if target is not None and target < 0:
            econ["flags"].append({"code": "infeasible_margin", "severity": "critical",
                                  "text": f"Target margin {target_margin:g}% is infeasible: it would require paying "
                                          f"{target:,.2f} per unit (a negative price)."})
        if ceiling is not None and ceiling < 0:
            econ["flags"].append({"code": "negative_ceiling", "severity": "critical",
                                  "text": f"Maximum safe buying price is negative ({ceiling:,.2f}): costs exceed "
                                          "conservative revenue even at a zero purchase price."})
        if target is not None and ceiling is not None and target > ceiling:
            econ["flags"].append({"code": "target_above_ceiling", "severity": "warning",
                                  "text": "Target buying price exceeds the conservative safe ceiling; the ceiling governs."})
        if recommended is not None:
            econ["at_recommended"] = unit_economics(p["p50"], recommended, ci).to_dict()
        if ceiling is not None:
            econ["at_ceiling_conservative"] = unit_economics(p["p25"], ceiling, ci).to_dict()
        if subject.asking_price is not None:
            ask = subject.asking_price
            tb = subject.asking_tax_basis
            if cfg.tax.mode == "standard":
                ask_b = ask / (1 + g) if tb == "inclusive" else ask
            else:
                ask_b = ask * (1 + g) if tb == "exclusive" else ask
            if tb == "unknown":
                A.add("asking_tax_unknown", "Supplier asking price has unknown tax basis; compared as stated.", "warning")
            ask_b = round(ask_b, 2)
            at_ask = unit_economics(p["p50"], ask_b, ci).to_dict()
            if ceiling is not None and ask_b > ceiling:
                verdict = ("above_ceiling", "Asking price is above the maximum safe buying price. Do not buy at this price.")
            elif target is not None and ask_b > target:
                verdict = ("above_target", "Asking price is below the safe ceiling but above the target price. Negotiate down.")
            elif target is not None:
                verdict = ("within_target", "Asking price is at or below the target buying price.")
            else:
                verdict = ("within_ceiling", "Asking price is within the safe ceiling (no target margin set).")
            econ["asking"] = {"asking_price": ask, "asking_tax_basis": tb, "asking_buy_basis": ask_b,
                              "economics": at_ask, "verdict": verdict[0], "verdict_text": verdict[1],
                              "gap_to_target": _r(ask_b - target) if target is not None else None,
                              "gap_to_ceiling": _r(ask_b - ceiling) if ceiling is not None else None}
        if qty is not None:
            rev = econ["at_recommended"]["revenue"] if "at_recommended" in econ else None
            lot = {
                "quantity": qty,
                "expected_saleable_units": _r(qty * yield_pct / 100, 2),
                "target_buy_total": _r(target * qty) if target is not None else None,
                "max_safe_buy_total": _r(ceiling * qty) if ceiling is not None else None,
                "recommended_buy_total": _r(recommended * qty) if recommended is not None else None,
                "expected_contribution_total": _r(econ["at_recommended"]["contribution"] * qty)
                if "at_recommended" in econ else None,
                "total_lot_value": _r(rev * qty) if rev is not None else None,
                "total_lot_value_definition": "Expected ex-GST revenue: saleable units x net sale price + salvage.",
                "asking_total": _r(subject.asking_price * qty) if subject.asking_price is not None else None,
                "contribution_at_asking_total": _r(econ["asking"]["economics"]["contribution"] * qty)
                if "asking" in econ else None,
            }
        else:
            needs_input.append("Quantity is missing; lot totals cannot be computed.")

    status = "insufficient_evidence" if basis is None else ("needs_input" if needs_input else "ok")
    confidence = _rating(basis_est, basis, missing_fields, cfg) if basis and basis_est else None
    for c in comps:
        if c["included"] is False and c["exclusion"] is None and c["set"]:
            c["exclusion"] = "Not used"
    result = {
        "engine_version": ENGINE_VERSION,
        "as_of": as_of.isoformat(),
        "status": status,
        "messages": messages,
        "needs_input": needs_input,
        "subject": {"id": subject.id, "label": subject.label, "is_synthetic": subject.is_synthetic,
                    "missing_fields": missing_fields},
        "channel": channel,
        "selling": selling,
        "listing_recommendation": listing_rec,
        "wholesale": wholesale,
        "procurement_market": procurement,
        "economics": econ,
        "lot": lot,
        "confidence": confidence,
        "estimates": estimates,
        "comparables": comps,
        "summary_counts": {
            "considered": len(comps),
            "included": sum(1 for c in comps if c["included"]),
            "excluded": sum(1 for c in comps if not c["included"]),
        },
        "assumptions": A.as_list(),
        "definitions": DEFINITIONS,
    }
    return result


def hash_payload(data) -> str:
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def run_valuation(subject: Subject, evidence: list[Evidence], cfg: PricingConfig, as_of: datetime) -> tuple[dict, dict]:
    """Returns (input_snapshot, result) with input and output hashes."""
    snapshot = {
        "engine_version": ENGINE_VERSION,
        "as_of": as_of.isoformat(),
        "subject": subject.to_dict(),
        "evidence": [e.to_dict() for e in sorted(evidence, key=lambda e: e.id)],
        "config": cfg.model_dump(mode="json"),
    }
    result = value_item(subject, evidence, cfg, as_of)
    result["input_hash"] = hash_payload(snapshot)
    result["output_hash"] = hash_payload({k: v for k, v in result.items() if k not in ("input_hash", "output_hash")})
    return snapshot, result


def reproduce(snapshot: dict) -> dict:
    subject = Subject.from_dict(snapshot["subject"])
    evidence = [Evidence.from_dict(e) for e in snapshot["evidence"]]
    cfg = PricingConfig.model_validate(snapshot["config"])
    as_of = datetime.fromisoformat(snapshot["as_of"])
    _, result = run_valuation(subject, evidence, cfg, as_of)
    return result
