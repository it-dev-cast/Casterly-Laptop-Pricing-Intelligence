"""Versioned procurement pricing rules.

Every save creates a version; each estimate records its version/hash. Default percentages are
explicit starter policy assumptions, not market truths. The legacy unconfigured preset remains
available for historical regression and upgrade detection. No monetary benchmarks are embedded.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .catalog import CATEGORY_LABELS, DEFAULT_CATEGORY_KEYWORDS

PRICE_TYPES: dict[str, str] = {
    "auction_price": "Auction advertised / hammer price (verify fees)",
    "verified_transaction": "Verified bulk purchase / wholesale transaction",
    "bulk_wholesale": "Bulk refurbished wholesale price",
    "buyback_quote": "Individual-device buyback quotation",
    "supplier_quote": "Supplier / vendor quotation",
    "refurb_retail": "Online refurbished retail selling price",
    "second_hand_ask": "Advertised second-hand market price",
    "historical_valuation": "Historical Casterly valuation (reference)",
}
BUY_SIDE_TYPES = ("verified_transaction", "bulk_wholesale", "buyback_quote", "supplier_quote")
ASKING_TYPES = ("refurb_retail", "second_hand_ask")

GRADES = ("New", "A+", "A", "B", "C", "D")


class QtyBand(BaseModel):
    min_qty: int
    max_qty: int | None = None
    discount_pct: Decimal | None = None


class RiskRule(BaseModel):
    flag: str
    label: str
    group: str  # rules in the same group never stack: the largest applies
    discount_pct: Decimal | None = None


class CategoryRules(BaseModel):
    label: str
    keywords: list[str] = []
    conversion: dict[str, Decimal | None] = {}
    grade_adjustment_pct: dict[str, Decimal | None] = {}
    quantity_bands: list[QtyBand] = []
    resale_realisation: dict[str, Decimal | None] = {}
    purchase_cost_per_unit: Decimal | None = None
    min_margin_pct: Decimal | None = None
    opening_discount_pct: Decimal | None = None
    large_lot_threshold: int | None = None


class ResearchRules(BaseModel):
    auto_accept_identical: bool = False  # accept identical-match snippet prices without human review
    auto_accept_confirmed: bool = True  # exact licensed offer, never a snippet alone
    queries_per_product: int = Field(2, ge=1, le=5)
    max_results_per_query: int = Field(10, ge=1, le=20)
    cache_days: int = Field(7, ge=0)
    max_attempts: int = Field(3, ge=1, le=10)
    retry_backoff_seconds: int = Field(30, ge=0)
    concurrency: int = Field(2, ge=1, le=8)
    country: str = "IN"


class Rounding(BaseModel):
    step: Decimal = Decimal("50")
    mode: Literal["down", "nearest"] = "down"


class Confidence(BaseModel):
    high: int = 70
    medium: int = 45


class Rules(BaseModel):
    name: str = "Default procurement rules"
    currency: str = "INR"
    quote_tax_basis: Literal["exclusive"] = "exclusive"
    gst_pct: Decimal = Decimal("18")
    unknown_tax_basis: dict[str, Literal["inclusive", "exclusive", "exclude"]] = {
        "refurb_retail": "inclusive", "second_hand_ask": "inclusive", "buyback_quote": "inclusive",
        "bulk_wholesale": "exclusive", "verified_transaction": "exclude", "supplier_quote": "exclude",
        "historical_valuation": "exclusive"}
    freshness_days: dict[str, int] = {"verified_transaction": 180, "bulk_wholesale": 60, "buyback_quote": 30,
                                      "supplier_quote": 30, "refurb_retail": 45, "second_hand_ask": 30,
                                      "historical_valuation": 30}
    provisional_max_age_days: int = 180
    price_type_weight: dict[str, Decimal] = {"verified_transaction": Decimal("1.0"), "bulk_wholesale": Decimal("0.95"),
                                             "buyback_quote": Decimal("0.9"), "supplier_quote": Decimal("0.85"),
                                             "refurb_retail": Decimal("0.7"), "second_hand_ask": Decimal("0.6"),
                                             "historical_valuation": Decimal("0.5")}
    match_weight: dict[str, Decimal] = {"identical": Decimal("1.0"), "comparable": Decimal("0.5")}
    half_life_days: int = 60
    prefer_top_tier: bool = True
    top_tier_types: list[str] = list(BUY_SIDE_TYPES)
    grade_adjusted_types: list[str] = ["historical_valuation"]
    bulk_priced_types: list[str] = ["bulk_wholesale", "verified_transaction", "historical_valuation"]
    outlier_mad_k: Decimal = Decimal("3.5")
    outlier_min_count: int = 5
    extreme_variation_ratio: Decimal = Decimal("0.5")
    risk_rules: list[RiskRule] = [
        RiskRule(flag="condition_unknown", label="Condition not stated", group="condition"),
        RiskRule(flag="charger_missing", label="Charger / accessory missing", group="accessories"),
        RiskRule(flag="untested", label="Not tested", group="testing"),
        RiskRule(flag="activation_lock_unknown", label="Activation Lock / MDM unknown", group="lock"),
        RiskRule(flag="legacy_platform", label="Legacy platform / low demand", group="obsolescence"),
        RiskRule(flag="battery_low", label="Battery health low", group="battery"),
        RiskRule(flag="cosmetic_damage", label="Cosmetic damage", group="condition"),
    ]
    max_total_discount_pct: Decimal | None = None
    rounding: Rounding = Rounding()
    confidence: Confidence = Confidence()
    fx_rates: dict[str, Decimal] = {}
    research: ResearchRules = ResearchRules()
    quantity_columns: list[str] = ["Net Leased Qty", "Qty", "Quantity", "Units", "Nos"]
    categories: dict[str, CategoryRules] = {}
    policy_basis: str | None = None
    similar_model_factors: dict[str, dict] = {}

    @model_validator(mode="after")
    def validate_policy(self):
        def rate(value, label):
            if value is not None and (not value.is_finite() or value < 0 or value > 100):
                raise ValueError(f"{label} must be a finite percentage from 0 to 100")
        rate(self.gst_pct, "GST")
        rate(self.max_total_discount_pct, "discount cap")
        for risk in self.risk_rules:
            rate(risk.discount_pct, risk.flag)
        for name, cat in self.categories.items():
            for value in cat.conversion.values():
                if value is not None and (not value.is_finite() or value <= 0):
                    raise ValueError(f"{name}: conversion factors must be finite and positive")
            for value in cat.grade_adjustment_pct.values():
                rate(value, name+" grade")
            rate(cat.opening_discount_pct, name+" opening")
            rate(cat.min_margin_pct, name+" margin")
            previous = 0
            for band in cat.quantity_bands:
                rate(band.discount_pct, name+" quantity")
                if band.min_qty <= previous or band.max_qty is not None and band.max_qty < band.min_qty:
                    raise ValueError(f"{name}: quantity bands must be ordered and non-overlapping")
                previous = band.max_qty if band.max_qty is not None else 10**12
        return self

    def category(self, key: str) -> CategoryRules:
        parent = "server_ram" if key.startswith("server_ram_") else "server_cpu" if key.startswith("server_cpu_") else key
        return self.categories.get(key) or self.categories.get(parent) or self.categories.get("other") or CategoryRules(label=key)


def _default_bands() -> list[QtyBand]:
    return [QtyBand(min_qty=1, max_qty=9), QtyBand(min_qty=10, max_qty=49), QtyBand(min_qty=50, max_qty=99),
            QtyBand(min_qty=100, max_qty=499), QtyBand(min_qty=500)]


def legacy_default_rules() -> Rules:
    cats = {}
    for key, label in CATEGORY_LABELS.items():
        cats[key] = CategoryRules(
            label=label, keywords=DEFAULT_CATEGORY_KEYWORDS.get(key, []),
            conversion={"verified_transaction": Decimal("1"), "bulk_wholesale": Decimal("1"),
                        "buyback_quote": Decimal("1"), "supplier_quote": Decimal("1"),
                        "historical_valuation": Decimal("1"), "refurb_retail": None, "second_hand_ask": None},
            grade_adjustment_pct={g: None for g in GRADES},
            quantity_bands=_default_bands(),
            resale_realisation={"refurb_retail": None, "second_hand_ask": None},
            large_lot_threshold=500,
        )
    return Rules(categories=cats)


def default_rules() -> Rules:
    """Starter policy assumptions, not market prices or calibrated transaction rates."""
    r = legacy_default_rules()
    r.name = "Casterly starter procurement policy v1"
    r.policy_basis = ("Initial assumptions dated 27-Oct-2026; review against actual transactions. "
                      "Grade A is the tested reference. Source conversion covers resale spread, warranty and holding risk; "
                      "specific condition/accessory risks apply separately only when not already reflected in evidence.")
    r.unknown_tax_basis["auction_price"] = "exclude"
    r.freshness_days["auction_price"] = 30
    r.price_type_weight["auction_price"] = Decimal("0.85")
    r.top_tier_types.append("auction_price")
    r.bulk_priced_types.append("auction_price")
    for key, c in r.categories.items():
        retail = {"smartphone":"0.70", "macbook":"0.68", "server_cpu":"0.60",
                  "server_ram":"0.65", "monitor":"0.60", "accessory":"0.55"}.get(key,"0.65")
        c.conversion.update(refurb_retail=Decimal(retail), second_hand_ask=Decimal("0.80"), auction_price=Decimal("0.90"))
        c.grade_adjustment_pct = {g:Decimal(v) for g,v in {"New":"0","A+":"0","A":"0","B":"10","C":"25","D":"50","Untested":"35"}.items()}
        for band,pct in zip(c.quantity_bands,("0","2","4","6","8")):
            band.discount_pct = Decimal(pct)
        c.opening_discount_pct = Decimal("5")
    r.risk_rules = [RiskRule(flag=f,label=l,group=g,discount_pct=Decimal(p)) for f,l,g,p in (
        ("condition_unknown","Condition unknown","condition","20"),
        ("charger_missing","Accessory missing","accessories","5"),
        ("untested","Not tested","condition","35"),
        ("activation_lock_unknown","Activation Lock / MDM unknown","lock","30"),
        ("legacy_platform","Legacy platform demand","obsolescence","10"),
        ("battery_low","Battery replacement allowance","battery","10"),
        ("cosmetic_damage","Cosmetic damage","condition","15"))]
    for variant,parent,label,factor in (
        ("server_ram_ddr3","server_ram","DDR3 server memory","0.55"),
        ("server_ram_ddr4","server_ram","DDR4 server memory","0.65"),
        ("server_ram_ddr5","server_ram","DDR5 server memory","0.70"),
        ("server_cpu_xeon","server_cpu","Intel Xeon processors","0.60"),
        ("server_cpu_epyc","server_cpu","AMD EPYC processors","0.65")):
        item = r.categories[parent].model_copy(deep=True)
        item.label, item.keywords = label, []
        item.conversion["refurb_retail"] = Decimal(factor)
        r.categories[variant] = item
    r.max_total_discount_pct = Decimal("80")
    return r


def historical_reference_rules() -> Rules:
    """Configuration that reproduces the dated B001/B002 reference valuations (26 Oct 2026).

    The reference workbooks already state Grade B, bulk, ex-GST buy prices, so no further grade,
    quantity or risk adjustment is applied to ``historical_valuation`` evidence. This rule set is a
    regression fixture: it is not activated automatically and must not be used for live quotes.
    """
    r = legacy_default_rules()
    r.name = "Historical reference configuration (B001/B002, 26-Oct-2026)"
    r.provisional_max_age_days = 36500
    r.freshness_days["historical_valuation"] = 36500
    r.rounding = Rounding(step=Decimal("1"), mode="nearest")
    return r


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def rules_hash(rules: Rules) -> str:
    return hashlib.sha256(canonical(rules.model_dump(mode="json")).encode()).hexdigest()


def config_gaps(rules: Rules) -> list[dict]:
    """Unconfigured items, for the Rules screen and dashboard."""
    gaps = []
    for key, c in rules.categories.items():
        missing_conv = [t for t in ASKING_TYPES if c.conversion.get(t) is None]
        if missing_conv:
            gaps.append({"category": key, "item": "conversion", "detail": "Retail / second-hand → buy conversion not set: "
                         + ", ".join(PRICE_TYPES[t] for t in missing_conv)})
        if all(v is None for v in c.grade_adjustment_pct.values()):
            gaps.append({"category": key, "item": "grade", "detail": "No grade adjustments configured"})
        if all(b.discount_pct is None for b in c.quantity_bands):
            gaps.append({"category": key, "item": "quantity", "detail": "No quantity-band discounts configured"})
    if all(r.discount_pct is None for r in rules.risk_rules):
        gaps.append({"category": "*", "item": "risk", "detail": "No risk adjustments configured"})
    return gaps
