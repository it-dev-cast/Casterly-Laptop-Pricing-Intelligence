"""Pricing Intelligence: identification and deterministic engine unit tests (no database)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.procurement import catalog
from app.procurement.engine import Group, Obs, input_hash, price_group
from app.procurement.identify import identify
from app.procurement.rules import RiskRule, default_rules

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def codes(ident):
    return {f.code for f in ident.flags}


# --------------------------------------------------------------------------- identification

def test_xeon_normalisation_and_generation():
    i = identify({"category_hint": "PM-CPU", "make": "INTEL", "model": "XEON GOLD 6130", "cpu": "XEON GOLD 6130", "grade": "B"})
    assert i.category == "server_cpu" and i.label == "Intel Xeon Gold 6130"
    assert i.product_key == "server_cpu|xeon-gold-6130"
    assert i.spec["generation"].startswith("1st Gen Scalable") and i.spec["socket"] == "LGA3647"
    j = identify({"category_hint": "PM-CPU", "make": "INTEL", "model": "XEON E5-2690V4 SR2N2", "grade": "B"})
    assert j.product_key == "server_cpu|xeon-e5-2690-v4" and j.spec["sspec"] == "SR2N2"


def test_cpu_typo_and_missing_sku_are_not_guessed():
    i = identify({"category_hint": "PM-CPU", "make": "INTEL", "model": "XEON SILVER 41112", "grade": "B"})
    assert i.product_key is None and "possible_typo" in codes(i)
    assert i.spec["typo_candidate"] == "4112"
    j = identify({"category_hint": "PM-CPU", "make": "INTEL", "model": "XEON", "grade": "B"})
    assert j.product_key is None and "cpu_sku_missing" in codes(j)


def test_epyc_inferred_from_opn_and_make_mismatch():
    i = identify({"category_hint": "PM-CPU", "make": "INTEL", "model": "AMD EPYC", "cpu": "AMD EPYC",
                  "serial": "9JF6686V00155_100-000000075", "grade": "B"})
    assert i.product_key == "server_cpu|epyc-7542"
    assert {"cpu_sku_inferred", "manufacturer_mismatch"} <= codes(i)
    assert i.confidence == "medium"


def test_ram_part_number_overrides_conflicting_speed():
    i = identify({"category_hint": "RC-RAM", "asset_type": "Sorted RAM for Resale", "make": "SAMSUNG",
                  "model": "PH M393A4K40DB2-CVF 2205", "cpu": "PC4; 32GB; 2666MHZ", "grade": "B"})
    assert i.spec["speed_mts"] == 2933 and i.spec["module_type"] == "RDIMM" and i.spec["ecc"] is True
    assert "ram_speed_conflict" in codes(i)
    assert i.product_key == "server_ram|DDR4|32gb|2933|rdimm"


def test_ram_truncated_speed_and_manufacturer_mismatch():
    i = identify({"category_hint": "RC-RAM", "make": "SAMSUNG", "model": "HMA82GR7JJR8N-WM T8 AA 949",
                  "cpu": "PC4; 16GB; 2666MHz", "grade": "B"})
    assert "manufacturer_mismatch" in codes(i)  # Hynix part number under a Samsung make
    j = identify({"category_hint": "RC-RAM", "make": "SAMSUNG", "model": "CN M393A4K40CB2-CTD 1911",
                  "cpu": "PC4; 32GB; 26MHZ", "grade": "B"})
    assert j.spec["speed_mts"] == 2666 and "ram_speed_truncated" in codes(j)


def test_ram_unknown_part_flags_type():
    i = identify({"category_hint": "RC-RAM", "make": "DATARAM", "model": "DTM64313H", "cpu": "PC3; 4GB; 1333MHZ", "grade": "B"})
    assert {"ram_part_unrecognised", "ram_type_unknown", "discontinued_component"} <= codes(i)
    assert i.product_key == "server_ram|DDR3|4gb|1333|unknown"


def test_decoders():
    assert catalog.decode_ram_part("MTA36ASF4G72PZ-2G6E1")["speed_mts"] == 2666
    assert catalog.decode_ram_part("HMAA8GL7MMR4N-UH")["module_type"] == "LRDIMM"
    assert catalog.decode_ram_part("M393B2G70BH0-YK0")["speed_mts"] == 1600
    assert catalog.parse_ram_spec("PC4; 64GB; 32MHz")["speed_mts"] == 3200
    assert catalog.cpu_generation("Core i7 12th Gen") == 12
    assert catalog.cpu_generation("i5-8350U") == 8
    assert catalog.cpu_generation("i7-1265U") == 12


def test_laptop_generation_conflict_and_missing_exact_cpu():
    i = identify({"product_type": "Laptop", "model": "Lenovo ThinkPad P1 Gen 4", "cpu": "Core i7", "generation": "8th Gen",
                  "ram": "32GB", "storage": "1TB SSD", "grade": "A"})
    assert i.category == "mobile_workstation"
    assert {"cpu_generation_conflict", "workstation_gpu_missing"} <= codes(i)
    j = identify({"product_type": "Laptop", "model": "Dell Latitude 5430", "cpu": "Core i7", "generation": "12th Gen",
                  "ram": "16GB", "storage": "512GB SSD", "grade": "A"})
    assert "exact_cpu_unknown" in codes(j) and "cpu_generation_conflict" not in codes(j)
    assert j.product_key == "laptop|dell|latitude 5430|i7-gen12|16gb|512gb"


def test_apple_flags():
    i = identify({"product_type": "Laptop", "model": "Apple MacBook Pro 16-inch M1", "ram": "16GB", "storage": "512GB",
                  "grade": "A"})
    assert i.category == "macbook"
    assert {"apple_chip_unknown", "apple_lock_unknown"} <= codes(i)
    assert "activation_lock_unknown" in i.risk_flags
    j = identify({"product_type": "Laptop", "model": "Apple MacBook Pro 16-inch M1 Pro", "notes": "MDM removed",
                  "grade": "A"})
    assert "apple_chip_unknown" not in codes(j) and "apple_lock_unknown" not in codes(j)


def test_phone_memory_parsing():
    i = identify({"product_type": "Mobile", "model": "Samsung Galaxy A54 5G 8GB/128GB", "grade": "B"})
    assert i.category == "smartphone" and i.spec["ram_gb"] == 8 and i.spec["storage_gb"] == 128
    assert i.product_key.startswith("smartphone|samsung|galaxy a54 5g")


def test_unknown_condition_flag():
    i = identify({"product_type": "Laptop", "model": "Dell Latitude 7440", "cpu": "i5-1345U"})
    assert "unknown_condition" in codes(i) and "condition_unknown" in i.risk_flags


# --------------------------------------------------------------------------- engine

def ob(id, price, ptype="refurb_retail", tax="inclusive", days=1, match="identical", src="a.in", status="verified",
       cur="INR"):
    return Obs(id=id, price=Decimal(price), currency=cur, tax_basis=tax, price_type=ptype, match_quality=match,
               observed_at=NOW - timedelta(days=days), source_key=src, reliability=0.8, status=status)


def configured_rules():
    r = default_rules()
    c = r.categories["server_ram"]
    c.conversion["refurb_retail"] = Decimal("0.6")
    c.grade_adjustment_pct["B"] = Decimal("10")
    for b in c.quantity_bands:
        if b.min_qty == 100:
            b.discount_pct = Decimal("5")
    for rr in r.risk_rules:
        if rr.flag == "charger_missing":
            rr.discount_pct = Decimal("5")
        if rr.flag == "cosmetic_damage":
            rr.discount_pct = Decimal("3")
        if rr.flag == "condition_unknown":
            rr.discount_pct = Decimal("8")
    return r


def test_no_evidence_is_manual_required():
    res = price_group(Group("server_ram", "B", 10), [], default_rules(), NOW)
    assert res["status"] == "manual_required" and res["recommended_unit"] is None
    assert "no_market_evidence" in res["flags"]


def test_retail_without_conversion_is_not_priced():
    rules = default_rules()
    rules.categories["server_ram"].conversion["refurb_retail"] = None
    res = price_group(Group("server_ram", "B", 10), [ob(1, "11800")], rules, NOW)
    assert res["status"] == "manual_required"
    assert "conversion_not_configured" in res["flags"]
    assert res["observations"][0]["exclusion"] == "conversion factor to buy price not configured"


def test_full_pipeline_decimal_math():
    g = Group("server_ram", "B", 150, risk_flags=["charger_missing"])
    res = price_group(g, [ob(1, "11800")], configured_rules(), NOW)
    # 11800 incl. 18% GST -> 10000 ex-GST -> x0.6 = 6000 benchmark
    assert res["benchmark"] == "6000.00"
    # 6000 x 0.90 (grade B) x 0.95 (100-499 band) x 0.95 (charger) = 4873.50 -> round down to 50 = 4850
    assert res["recommended_unit"] == "4850.00"
    assert res["status"] == "priced"
    assert [s["step"] for s in res["steps"]] == ["benchmark", "condition", "quantity", "risk", "rounding"]


def test_risk_rules_in_same_group_do_not_stack():
    g = Group("server_ram", None, 1, risk_flags=["condition_unknown", "cosmetic_damage"])
    res = price_group(g, [ob(1, "11800")], configured_rules(), NOW)
    risk = next(s for s in res["steps"] if s["step"] == "risk")
    assert risk["pct"] == "8.00"  # max of the 'condition' group (8% vs 3%), not 11%


def test_buy_side_evidence_preferred_and_historical_superseded():
    rules = configured_rules()
    obs = [ob(1, "11800"), ob(2, "5000", ptype="bulk_wholesale", tax="exclusive"),
           ob(3, "9999", ptype="historical_valuation", tax="exclusive")]
    res = price_group(Group("server_ram", "B", 5), obs, rules, NOW)
    used = {o["id"] for o in res["observations"] if o["included"]}
    assert used == {2}
    assert res["benchmark"] == "5000.00"


def test_historical_only_is_provisional_and_grade_not_double_counted():
    rules = configured_rules()
    res = price_group(Group("server_ram", "B", 150), [ob(1, "6500", ptype="historical_valuation", tax="exclusive")],
                      rules, NOW)
    assert res["status"] == "provisional" and res["recommended_unit"] == "6500.00"
    assert res["confidence"] in ("Medium", "Low")


def test_unverified_and_stale_and_foreign_currency_excluded():
    rules = configured_rules()
    obs = [ob(1, "11800", status="candidate"), ob(2, "11800", days=400), ob(3, "120", cur="USD")]
    res = price_group(Group("server_ram", "B", 1), obs, rules, NOW)
    reasons = [o["exclusion"] for o in res["observations"]]
    assert reasons[0].startswith("not verified") and reasons[1].startswith("older than") and "FX" in reasons[2]
    assert res["status"] == "manual_required"


def test_outlier_removed():
    rules = configured_rules()
    obs = [ob(i, p, src=f"s{i}.in") for i, p in enumerate(["11800", "11900", "11700", "12000", "11850", "59000"], 1)]
    res = price_group(Group("server_ram", "B", 1), obs, rules, NOW)
    out = next(o for o in res["observations"] if o["id"] == 6)
    assert not out["included"] and out["exclusion"].startswith("outlier")


def test_deterministic_and_hash_stable():
    rules, g, obs = configured_rules(), Group("server_ram", "B", 150), [ob(1, "11800"), ob(2, "12500", src="b.in")]
    assert price_group(g, obs, rules, NOW) == price_group(g, obs, rules, NOW)
    assert input_hash(g, obs, rules, NOW) == input_hash(g, obs, rules, NOW)
    rules2 = configured_rules()
    rules2.risk_rules.append(RiskRule(flag="x", label="x", group="x", discount_pct=Decimal("1")))
    assert input_hash(g, obs, rules, NOW) != input_hash(g, obs, rules2, NOW)


def test_margin_constrained_maximum():
    rules = configured_rules()
    c = rules.categories["server_ram"]
    c.resale_realisation["refurb_retail"] = Decimal("0.9")
    c.min_margin_pct = Decimal("20")
    c.purchase_cost_per_unit = Decimal("200")
    res = price_group(Group("server_ram", "B", 1), [ob(1, "11800")], rules, NOW)
    # resale = 10000 x 0.9 = 9000; max = 9000 x 0.8 - 200 = 7000; recommended 6000 x 0.9 = 5400
    assert res["resale_unit"] == "9000.00" and res["max_unit"] == "7000.00" and res["recommended_unit"] == "5400.00"
    assert res["margin_pct"] == "37.78"  # (9000 - 5400 - 200) / 9000
