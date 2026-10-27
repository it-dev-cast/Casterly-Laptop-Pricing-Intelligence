"""Pricing configuration.

Everything the engine needs that is a *choice* (rather than evidence) lives here,
versioned, and is copied into each valuation snapshot. Defaults are deliberately
conservative and clearly labelled:

* No price-adjustment percentages ship by default. Broadening to similar
  configurations only happens once a user enters an explicit rule, and every rule
  carries ``calibrated`` and ``basis`` fields that are surfaced as assumptions.
* Cost items that a business must supply (fees, logistics, yields, repair costs)
  default to ``None`` = "not configured" and are reported, never silently zeroed.
* Statistical choices (recency half-life, match weights, outlier rule, staleness
  windows, rating thresholds) have documented defaults and are listed in every
  valuation's assumptions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Channel = Literal["retail", "wholesale", "as_is"]
EvidenceKind = Literal["sale", "listing", "quote", "purchase"]
ADJUSTABLE_DIMENSIONS = (
    "cpu_key", "ram_gb", "storage_gb", "storage_type", "condition_grade", "gpu_key",
    "display_size_in", "display_resolution", "charger_included", "warranty_months",
)


class PercentFee(BaseModel):
    name: str
    rate_pct: float | None = Field(default=None, ge=0, le=100)
    base: Literal["gross_incl_tax", "net_ex_tax"] = "gross_incl_tax"


class FixedCost(BaseModel):
    name: str
    amount: float | None = Field(default=None, ge=0)  # INR per sold unit, ex-GST


class ChannelCosts(BaseModel):
    percentage_fees: list[PercentFee] = []
    fixed_costs_per_sold_unit: list[FixedCost] = []
    # Ratio of realised sale price to advertised asking price. None = not configured:
    # asking prices are then never converted into an expected sale price.
    asking_to_sale_ratio: float | None = Field(default=None, gt=0, le=1.5)
    asking_to_sale_ratio_basis: str | None = None


class FaultCategory(BaseModel):
    key: str
    label: str
    expected_yield_pct: float | None = Field(default=None, ge=0, le=100)
    repair_cost_per_unit: float | None = Field(default=None, ge=0)
    salvage_value_per_unit: float | None = Field(default=None, ge=0)
    match_keywords: list[str] = []


class AdjustmentRule(BaseModel):
    """Adjust a comparable whose ``dimension`` equals ``comparable_value`` to a
    subject whose value is ``subject_value``. Applied as percent of price or a
    fixed INR amount (on the tax-inclusive price)."""

    id: str
    dimension: str
    comparable_value: str
    subject_value: str
    method: Literal["percent", "amount"]
    value: float
    symmetric: bool = False  # also apply the exact inverse for subject->comparable
    calibrated: bool = False
    basis: str = ""  # who set it and on what evidence

    @field_validator("dimension")
    @classmethod
    def _dim(cls, v: str) -> str:
        if v not in ADJUSTABLE_DIMENSIONS:
            raise ValueError(f"dimension must be one of {ADJUSTABLE_DIMENSIONS}")
        return v


class MatchingRules(BaseModel):
    min_comparables: int = Field(default=3, ge=1)
    min_independent_sources: int = Field(default=2, ge=1)
    # Dimensions where an unknown value on either side excludes the comparable.
    required_dimensions: list[str] = ["cpu_key", "ram_gb", "storage_gb", "condition_grade"]
    # Dimensions compared only when both sides are known (unknown = unverified, not excluded).
    optional_dimensions: list[str] = ["storage_type", "gpu_key", "display_size_in", "display_resolution",
                                      "charger_included", "warranty_months"]
    battery_tolerance_pts: float | None = Field(default=10, ge=0)
    weight_exact: float = Field(default=1.0, gt=0)
    weight_unverified: float = Field(default=0.8, gt=0)
    weight_adjusted: float = Field(default=0.5, gt=0)
    recency_half_life_days: float = Field(default=60, gt=0)
    split_weight_by_source: bool = True
    outlier_mad_k: float | None = Field(default=3.5, gt=0)
    outlier_min_count: int = 5


class FreshnessRules(BaseModel):
    max_age_days: dict[str, int] = {"sale": 180, "listing": 45, "quote": 30, "purchase": 180}
    exclude_unavailable_listings: bool = True
    exclude_expired_quotes: bool = True


class DedupRules(BaseModel):
    repeat_price_tolerance_pct: float = 2.0
    repeat_window_days: int = 21
    syndication_price_tolerance_pct: float = 0.5
    syndication_window_days: int = 7


class TaxRules(BaseModel):
    mode: Literal["standard", "margin_scheme", "none"] = "standard"
    gst_rate_pct: float = Field(default=18.0, ge=0, le=100)
    gst_rate_basis: str = "Configured default (HSN 8471 laptops). Confirm with your tax advisor."
    unknown_tax_basis: dict[str, Literal["assume_inclusive", "assume_exclusive", "exclude"]] = {
        "listing": "assume_inclusive",
        "sale": "exclude",
        "quote": "exclude",
        "purchase": "exclude",
    }


class RatingRules(BaseModel):
    count_points: list[tuple[int, int]] = [(8, 25), (5, 18), (3, 10)]
    source_points: list[tuple[int, int]] = [(5, 15), (3, 10), (2, 5)]
    freshness_points: list[tuple[int, int]] = [(14, 15), (45, 10), (90, 5)]  # weighted median age (days) <=
    exact_share_points: list[tuple[float, int]] = [(0.8, 15), (0.5, 10), (0.01, 5)]
    dispersion_points: list[tuple[float, int]] = [(0.10, 15), (0.20, 10), (0.35, 5)]  # IQR / median <=
    sales_basis_points: int = 15
    asking_basis_points: int = 5
    missing_field_penalty: int = 3
    grade_thresholds: list[tuple[int, str]] = [(80, "A"), (60, "B"), (40, "C"), (0, "D")]


class PricingConfig(BaseModel):
    currency: str = "INR"
    fx_rates_to_inr: dict[str, float] = {}
    grade_scale: list[str] = ["A+", "A", "B", "C", "D"]
    grade_synonyms: dict[str, str] = {"grade a+": "A+", "a plus": "A+", "grade a": "A", "grade b": "B",
                                      "grade c": "C", "grade d": "D"}
    default_target_margin_pct: float | None = None
    minimum_margin_pct_for_ceiling: float = 0.0
    default_channel: Channel = "retail"
    channels: dict[str, ChannelCosts] = {
        "retail": ChannelCosts(
            percentage_fees=[PercentFee(name="Marketplace commission"), PercentFee(name="Payment gateway")],
            fixed_costs_per_sold_unit=[FixedCost(name="Outbound logistics"), FixedCost(name="Packaging"),
                                       FixedCost(name="Warranty provision")],
        ),
        "wholesale": ChannelCosts(fixed_costs_per_sold_unit=[FixedCost(name="Outbound logistics")]),
        "as_is": ChannelCosts(),
    }
    fixed_costs_per_purchased_unit: list[FixedCost] = [FixedCost(name="Inbound logistics"),
                                                       FixedCost(name="Testing / QC")]
    fault_categories: list[FaultCategory] = [
        FaultCategory(key="none", label="No reported faults"),
        FaultCategory(key="cosmetic", label="Cosmetic only", match_keywords=["scratch", "dent", "cosmetic", "scuff"]),
        FaultCategory(key="battery", label="Battery", match_keywords=["battery"]),
        FaultCategory(key="display", label="Display", match_keywords=["display", "screen", "lcd", "panel", "line"]),
        FaultCategory(key="keyboard_input", label="Keyboard / touchpad", match_keywords=["keyboard", "key", "touchpad", "trackpad"]),
        FaultCategory(key="board_power", label="Motherboard / no power", match_keywords=["motherboard", "no power", "dead", "board", "no display"]),
        FaultCategory(key="other", label="Other / unspecified fault"),
    ]
    adjustments: list[AdjustmentRule] = []
    matching: MatchingRules = MatchingRules()
    freshness: FreshnessRules = FreshnessRules()
    dedup: DedupRules = DedupRules()
    tax: TaxRules = TaxRules()
    rating: RatingRules = RatingRules()
    import_default_currency: str | None = "INR"
    import_day_first_dates: bool = True

    def fault(self, key: str | None) -> FaultCategory | None:
        for f in self.fault_categories:
            if f.key == key:
                return f
        return None


def default_config() -> PricingConfig:
    return PricingConfig()


def canonical_json(data) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def config_hash(cfg: PricingConfig) -> str:
    return hashlib.sha256(canonical_json(cfg.model_dump(mode="json")).encode()).hexdigest()
