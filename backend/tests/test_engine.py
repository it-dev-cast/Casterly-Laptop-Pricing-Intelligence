"""Pricing engine tests: pure, no database, no language model."""
import json
from datetime import timedelta

import pytest

from app.pricing.config import AdjustmentRule, ChannelCosts, FixedCost, PercentFee
from app.pricing.economics import CostInputs, solve_buy_price, unit_economics
from app.pricing.engine import reproduce, run_valuation, value_item
from app.pricing.stats import simple_median, weighted_median, weighted_quantile

from .factories import AS_OF, config, ev, sales, subject, today_minus


def comp(result, eid):
    return next(c for c in result["comparables"] if c["id"] == eid)


# ---------------------------------------------------------------- statistics

def test_weighted_median_equal_weights_matches_ordinary_median():
    assert weighted_median([1, 2, 3], [1, 1, 1]) == 2
    assert weighted_median([1, 2, 3, 4], [1, 1, 1, 1]) == 2.5
    assert simple_median([4, 1, 3, 2]) == 2.5


def test_weighted_quantile_respects_weights_and_clamps():
    assert weighted_quantile([10, 20], [3, 1], 0.5) < 15
    assert weighted_quantile([10, 20, 30], [1, 1, 1], 0.0) == 10
    assert weighted_quantile([10, 20, 30], [1, 1, 1], 1.0) == 30


# ---------------------------------------------------------------- configuration matching

def test_exact_configuration_first_and_incomparable_excluded_with_reason():
    exact = sales([30000, 31000, 32000])
    other = [ev("sale", 25000, ram_gb=8), ev("sale", 26000, ram_gb=8)]
    r = value_item(subject(), exact + other, config(), AS_OF)
    assert r["status"] == "ok"
    assert r["estimates"]["sale:retail"]["count"] == 3
    for e in other:
        c = comp(r, e.id)
        assert not c["included"]
        assert "Materially incomparable: RAM (GB) 8 vs subject 16" in c["exclusion"]
        assert "no adjustment rule configured" in c["exclusion"]


def test_broadening_only_with_explicit_rule_and_marked_uncalibrated():
    cfg = config(adjustments=[AdjustmentRule(id="ram8to16", dimension="ram_gb", comparable_value="8",
                                             subject_value="16", method="percent", value=10)])
    exact = sales([30000, 31000])
    adj = [ev("sale", 27000, ram_gb=8), ev("sale", 28000, ram_gb=8)]
    r = value_item(subject(), exact + adj, cfg, AS_OF)
    est = r["estimates"]["sale:retail"]
    assert est["broadened_with_adjustments"] is True and est["count"] == 4 and est["exact_count"] == 2
    c = comp(r, adj[0].id)
    assert c["match_tier"] == "adjusted" and c["included"]
    assert c["adjusted_price"] == pytest.approx(27000 * 1.10)
    assert c["adjustments"][0]["rule_id"] == "ram8to16" and c["adjustments"][0]["calibrated"] is False
    assert c["weights"]["match"] == cfg.matching.weight_adjusted
    warn = [a for a in r["assumptions"] if a["code"] == "adjustment_ram8to16"][0]
    assert warn["severity"] == "warning" and "UNCALIBRATED" in warn["text"]


def test_adjusted_matches_not_used_when_exact_evidence_suffices():
    cfg = config(adjustments=[AdjustmentRule(id="r", dimension="ram_gb", comparable_value="8",
                                             subject_value="16", method="amount", value=2000)])
    exact = sales([30000, 31000, 32000])
    adj = ev("sale", 27000, ram_gb=8)
    r = value_item(subject(), exact + [adj], cfg, AS_OF)
    assert not comp(r, adj.id)["included"]
    assert "Adjusted match not needed" in comp(r, adj.id)["exclusion"]
    assert r["estimates"]["sale:retail"]["broadened_with_adjustments"] is False


def test_symmetric_rule_applies_exact_inverse():
    cfg = config(adjustments=[AdjustmentRule(id="r", dimension="ram_gb", comparable_value="8",
                                             subject_value="16", method="percent", value=25, symmetric=True)])
    e = ev("sale", 25000, ram_gb=16)
    r = value_item(subject(ram_gb=8), sales([20000], ram_gb=8) + [e], cfg, AS_OF)
    assert comp(r, e.id)["adjusted_price"] == pytest.approx(20000)


def test_unknown_required_dimension_excludes_comparable():
    e = ev("sale", 30000, ram_gb=None)
    r = value_item(subject(), sales([30000, 31000, 32000]) + [e], config(), AS_OF)
    assert "RAM (GB) unknown on comparable" in comp(r, e.id)["exclusion"]


def test_unknown_optional_dimension_is_unverified_not_excluded():
    e = ev("sale", 30000, gpu_key=None)
    r = value_item(subject(), sales([30000, 31000]) + [e], config(), AS_OF)
    c = comp(r, e.id)
    assert c["included"] and c["match_tier"] == "unverified" and "gpu_key" in c["unverified_dimensions"]


def test_battery_outside_tolerance_excluded():
    e = ev("sale", 30000, battery_health_pct=60.0)
    r = value_item(subject(), sales([30000, 31000, 32000]) + [e], config(), AS_OF)
    assert "Battery health 60% vs subject 85%" in comp(r, e.id)["exclusion"]


# ---------------------------------------------------------------- duplicates

def test_repeated_source_record_is_deduplicated_keeping_latest():
    a = ev("listing", 33000, days_ago=10, source_record_id="L-1", platform="P")
    b = ev("listing", 33000, days_ago=2, source_record_id="L-1", platform="P")
    r = value_item(subject(), [a, b], config(), AS_OF)
    assert comp(r, a.id)["duplicate_of"] == b.id
    assert "Same source record id" in comp(r, a.id)["exclusion"]
    assert comp(r, b.id)["duplicate_of"] is None


def test_repeated_listing_same_seller_and_syndicated_offer():
    a = ev("listing", 33000, days_ago=12, seller="Shop A")
    b = ev("listing", 33300, days_ago=4, seller="Shop A")  # within 2%
    s1 = ev("listing", 34000, days_ago=3, seller="Shop B", title_key="dell 7490 i5 16 256 grade a")
    s2 = ev("listing", 34000, days_ago=2, seller="Shop C", title_key="dell 7490 i5 16 256 grade a")
    r = value_item(subject(), [a, b, s1, s2], config(), AS_OF)
    assert "Repeated listing by the same seller" in comp(r, a.id)["exclusion"]
    assert "Syndicated offer" in comp(r, s1.id)["exclusion"]
    assert r["estimates"]["listing:retail"]["count"] == 2


def test_tax_basis_does_not_hide_duplicates():
    a = ev("listing", 10000, tax_basis="exclusive", source_url="https://example.test/x")
    b = ev("listing", 11800, tax_basis="inclusive", source_url="https://example.test/x")
    r = value_item(subject(), [a, b], config(), AS_OF)
    assert sum(1 for c in r["comparables"] if c["duplicate_of"]) == 1


# ---------------------------------------------------------------- staleness, availability, timing

def test_stale_unavailable_expired_and_future_evidence_excluded():
    stale = ev("sale", 30000, days_ago=200)
    old_listing = ev("listing", 30000, days_ago=50)
    oos = ev("listing", 30000, days_ago=3, availability="out_of_stock")
    expired = ev("quote", 20000, days_ago=5, valid_until=today_minus(1), tax_basis="exclusive")
    future = ev("sale", 30000, days_ago=-3)
    r = value_item(subject(), sales([30000, 31000, 32000]) + [stale, old_listing, oos, expired, future], config(), AS_OF)
    assert comp(r, stale.id)["exclusion"].startswith("Stale: 200 days old")
    assert comp(r, old_listing.id)["exclusion"].startswith("Stale: 50 days old (limit 45")
    assert "Unavailable listing (out of stock)" == comp(r, oos.id)["exclusion"]
    assert "Quotation expired" in comp(r, expired.id)["exclusion"]
    assert comp(r, future.id)["exclusion"] == "Dated after the valuation date"


def test_synthetic_evidence_never_used_for_real_inventory():
    synth = [ev("sale", 30000, is_synthetic=True) for _ in range(5)]
    r = value_item(subject(), synth, config(), AS_OF)
    assert r["status"] == "insufficient_evidence"
    assert all("Synthetic demo evidence" in c["exclusion"] for c in r["comparables"])


def test_foreign_currency_without_rate_excluded():
    e = ev("sale", 400, currency="USD")
    r = value_item(subject(), [e], config(), AS_OF)
    assert comp(r, e.id)["exclusion"] == "Currency USD with no configured INR rate"


def test_outlier_excluded_with_reason():
    cfg = config()
    cfg.matching.outlier_mad_k = 3.5
    out = ev("sale", 150000)
    r = value_item(subject(), sales([30000, 30500, 31000, 31500, 32000]) + [out], cfg, AS_OF)
    assert comp(r, out.id)["exclusion"].startswith("Outlier:")


# ---------------------------------------------------------------- insufficient data

def test_insufficient_evidence_produces_no_prices():
    r = value_item(subject(), sales([30000, 31000]), config(), AS_OF)
    assert r["status"] == "insufficient_evidence"
    assert r["selling"] is None and r["confidence"] is None
    assert "target_buy" not in r["economics"]
    assert "Insufficient evidence" in r["messages"][0]


def test_single_source_is_insufficient():
    r = value_item(subject(), sales([30000, 31000, 32000], seller="Only Shop"), config(), AS_OF)
    assert r["estimates"]["sale:retail"]["independent_sources"] == 1
    assert r["status"] == "insufficient_evidence"


def test_asking_prices_never_treated_as_sales():
    listings = [ev("listing", p) for p in (34000, 35000, 36000, 37000)]
    r = value_item(subject(), listings, config(), AS_OF)
    assert r["status"] == "insufficient_evidence"
    assert "asking prices cannot stand in for sales" in r["messages"][0]
    assert r["listing_recommendation"]["price_gross"] == pytest.approx(35500)

    cfg = config()
    cfg.channels["retail"] = ChannelCosts(asking_to_sale_ratio=0.9, asking_to_sale_ratio_basis="test")
    r2 = value_item(subject(), listings, cfg, AS_OF)
    assert r2["selling"]["basis"] == "asking_adjusted"
    assert r2["selling"]["p50_gross"] == pytest.approx(35500 * 0.9)
    assert any(a["code"] == "asking_ratio" for a in r2["assumptions"])


# ---------------------------------------------------------------- economics

def _ci(**over):
    d = dict(tax_mode="standard", gst_rate=0.18, yield_fraction=1.0, salvage_per_unsold_unit=0.0,
             repair_per_unit=1000.0, fixed_per_purchased_unit=0.0, fixed_per_sold_unit=0.0,
             fee_rate_on_gross=0.0, fee_rate_on_net=0.0)
    d.update(over)
    return CostInputs(**d)


def test_margin_and_markup_are_distinct():
    e = unit_economics(11800, 7000, _ci())
    assert e.net_sale_price == pytest.approx(10000)
    assert e.contribution == pytest.approx(2000)
    assert e.margin == pytest.approx(0.20)  # contribution / revenue
    assert e.markup == pytest.approx(0.25)  # contribution / cost
    assert e.markup == pytest.approx(e.margin / (1 - e.margin))


def test_target_buy_price_achieves_exact_margin_in_every_tax_mode():
    for mode in ("standard", "margin_scheme", "none"):
        ci = _ci(tax_mode=mode, fee_rate_on_gross=0.05, fixed_per_sold_unit=300)
        b = solve_buy_price(30000, ci, margin=0.15)
        assert unit_economics(30000, b, ci).margin == pytest.approx(0.15, abs=1e-6)


def test_tax_consistency_inclusive_and_exclusive_evidence_agree():
    inc = [ev("sale", 35400, tax_basis="inclusive") for _ in range(3)]
    exc = [ev("sale", 30000, tax_basis="exclusive") for _ in range(3)]
    r1 = value_item(subject(), inc, config(), AS_OF)
    r2 = value_item(subject(), exc, config(), AS_OF)
    assert r1["selling"]["p50_gross"] == r2["selling"]["p50_gross"] == pytest.approx(35400)
    assert r1["selling"]["p50_ex_gst"] == pytest.approx(30000)
    assert r1["economics"]["target_buy"] == r2["economics"]["target_buy"]


def test_unknown_tax_basis_policy_applied_and_reported():
    unknown_sales = [ev("sale", 35400, tax_basis="unknown") for _ in range(3)]
    r = value_item(subject(), unknown_sales, config(), AS_OF)
    assert r["status"] == "insufficient_evidence"
    assert "Tax basis unknown" in r["comparables"][0]["exclusion"]
    listings = [ev("listing", 35400, tax_basis="unknown") for _ in range(3)]
    r2 = value_item(subject(), listings, config(), AS_OF)
    a = [x for x in r2["assumptions"] if x["code"] == "tax_assumed_inclusive_listing"][0]
    assert a["count"] == 3 and a["severity"] == "warning"


def test_margin_scheme_taxes_only_the_margin():
    e = unit_economics(11800, 9000, _ci(tax_mode="margin_scheme"))
    assert e.output_tax_per_sold_unit == pytest.approx(2800 * 0.18 / 1.18)
    e2 = unit_economics(8000, 9000, _ci(tax_mode="margin_scheme"))
    assert e2.output_tax_per_sold_unit == 0


def test_percentage_fees_on_gross_versus_net():
    gross = unit_economics(11800, 5000, _ci(fee_rate_on_gross=0.10))
    net = unit_economics(11800, 5000, _ci(fee_rate_on_net=0.10))
    assert gross.percentage_fees == pytest.approx(1180)
    assert net.percentage_fees == pytest.approx(1000)
    assert gross.contribution == pytest.approx(net.contribution - 180)


def test_unconfigured_fees_reported_and_configured_fees_applied():
    r = value_item(subject(), sales([35400, 35400, 35400]), config(), AS_OF)
    assert any(a["code"].startswith("fee_unset_") for a in r["assumptions"])
    cfg = config()
    cfg.channels["retail"] = ChannelCosts(percentage_fees=[PercentFee(name="Commission", rate_pct=10)],
                                          fixed_costs_per_sold_unit=[FixedCost(name="Ship", amount=500)])
    r2 = value_item(subject(), sales([35400, 35400, 35400]), cfg, AS_OF)
    e = r2["economics"]["at_recommended"]
    assert e["percentage_fees"] == pytest.approx(3540) and e["fixed_selling_costs"] == pytest.approx(500)
    assert r2["economics"]["target_buy"] < r["economics"]["target_buy"]


# ---------------------------------------------------------------- defective lots

def test_defective_lot_uses_yield_repair_and_salvage():
    s = subject(faults=("Display cracked",), refurbishment_cost=None, expected_yield_pct=None, quantity=20)
    r = value_item(s, sales([35400, 35400, 35400]), config(), AS_OF)
    inp = r["economics"]["inputs"]
    assert inp["fault_category"] == "display" and inp["expected_yield_pct"] == 70
    assert inp["repair_cost_per_unit"] == 4000 and inp["salvage_per_unsold_unit"] == 3000
    e = r["economics"]["at_recommended"]
    assert e["revenue"] == pytest.approx(0.7 * 30000 + 0.3 * 3000)
    lot = r["lot"]
    assert lot["expected_saleable_units"] == 14
    assert lot["recommended_buy_total"] == pytest.approx(r["economics"]["recommended_buy"] * 20, abs=0.05)
    # A no-fault unit at the same price is worth more per purchased unit.
    clean = value_item(subject(quantity=20), sales([35400, 35400, 35400]), config(), AS_OF)
    assert clean["economics"]["target_buy"] > r["economics"]["target_buy"]


def test_lot_with_unknown_yield_is_not_assumed_to_sell_fully():
    s = subject(faults=("No power",), refurbishment_cost=None, expected_yield_pct=None)
    r = value_item(s, sales([35400, 35400, 35400]), config(), AS_OF)
    assert r["status"] == "needs_input"
    assert any("saleable yield" in n for n in r["needs_input"])
    assert "target_buy" not in r["economics"] and r["selling"] is not None


def test_negative_ceiling_and_infeasible_margin_are_flagged_not_zeroed():
    s = subject(refurbishment_cost=40000.0, target_margin_pct=15.0)
    r = value_item(s, sales([35400, 35400, 35400]), config(), AS_OF)
    codes = {f["code"] for f in r["economics"]["flags"]}
    assert {"negative_ceiling", "infeasible_margin"} <= codes
    assert r["economics"]["max_safe_buy"] < 0 and r["economics"]["target_buy"] < 0
    r2 = value_item(subject(target_margin_pct=99.0), sales([35400, 35400, 35400]), config(), AS_OF)
    assert "infeasible_margin" in {f["code"] for f in r2["economics"]["flags"]}


def test_asking_price_verdict():
    r = value_item(subject(asking_price=50000.0, asking_tax_basis="inclusive"), sales([35400] * 3), config(), AS_OF)
    assert r["economics"]["asking"]["verdict"] == "above_ceiling"
    r2 = value_item(subject(asking_price=10000.0, asking_tax_basis="exclusive"), sales([35400] * 3), config(), AS_OF)
    assert r2["economics"]["asking"]["verdict"] == "within_target"


# ---------------------------------------------------------------- confidence & reproducibility

def test_rating_components_are_transparent():
    r = value_item(subject(), sales([30000, 31000, 32000, 33000, 31000]), config(), AS_OF)
    conf = r["confidence"]
    assert conf["grade"] in "ABCD" and "NOT a calibrated probability" in conf["note"]
    names = {c["component"] for c in conf["components"]}
    assert {"Comparable count", "Independent sources", "Exact-match coverage", "Evidence type"} <= names


def test_reproducibility_bit_for_bit():
    evidence = sales([30000, 31000, 32000]) + [ev("listing", 35000), ev("sale", 1, days_ago=400)]
    snap1, r1 = run_valuation(subject(), evidence, config(), AS_OF)
    snap2, r2 = run_valuation(subject(), list(reversed(evidence)), config(), AS_OF)
    assert r1["output_hash"] == r2["output_hash"] and r1["input_hash"] == r2["input_hash"]
    roundtrip = json.loads(json.dumps(snap1))
    assert reproduce(roundtrip)["output_hash"] == r1["output_hash"]
    later = AS_OF + timedelta(days=30)
    _, r3 = run_valuation(subject(), evidence, config(), later)
    assert r3["output_hash"] != r1["output_hash"]
