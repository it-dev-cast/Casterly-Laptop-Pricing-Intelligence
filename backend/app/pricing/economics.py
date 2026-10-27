"""Unit economics: one forward function, and an inverse solved against it.

Definitions (shown in the UI and README):

* ``revenue``       sale revenue per *purchased* unit, net of output GST:
                    ``yield x net_sale_price + (1 - yield) x salvage``
* ``contribution``  revenue - purchase price - per-purchased-unit costs
                    - yield x (percentage fees + per-sold-unit costs)
* ``margin``        contribution / revenue            (contribution margin)
* ``markup``        contribution / total cost         (kept separate from margin)

Tax modes
* ``standard``      sale prices carry full GST; input tax on purchases is assumed
                    recoverable, so purchase prices are compared ex-GST.
* ``margin_scheme`` GST is charged on (sale price - purchase price) when positive
                    (second-hand goods valuation rule); purchase prices carry no ITC.
* ``none``          seller not charging GST; net sale price = gross sale price.

The inverse (buy price for a required margin) is found by bisection on the
forward function, so the two can never disagree. Negative results are returned
as negative numbers and flagged by the caller — never clamped to zero.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class CostInputs:
    tax_mode: str
    gst_rate: float  # fraction, e.g. 0.18
    yield_fraction: float
    salvage_per_unsold_unit: float
    repair_per_unit: float
    fixed_per_purchased_unit: float
    fixed_per_sold_unit: float
    fee_rate_on_gross: float  # fraction of tax-inclusive sale price
    fee_rate_on_net: float  # fraction of ex-tax sale price


@dataclass
class Economics:
    gross_sale_price: float
    buy_price: float
    output_tax_per_sold_unit: float
    net_sale_price: float
    revenue: float
    percentage_fees: float
    fixed_selling_costs: float
    repair_cost: float
    fixed_purchase_costs: float
    total_cost: float
    contribution: float
    margin: float | None
    markup: float | None
    lines: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, float):
                d[k] = round(v, 6) if k in ("margin", "markup") else round(v, 2)
        return d


def unit_economics(gross_sale_price: float, buy_price: float, c: CostInputs) -> Economics:
    g = c.gst_rate
    if c.tax_mode == "standard":
        net = gross_sale_price / (1 + g)
    elif c.tax_mode == "margin_scheme":
        taxable_margin_incl = max(0.0, gross_sale_price - buy_price)
        net = gross_sale_price - taxable_margin_incl * g / (1 + g)
    elif c.tax_mode == "none":
        net = gross_sale_price
    else:
        raise ValueError(f"unknown tax mode {c.tax_mode}")
    tax = gross_sale_price - net
    y = c.yield_fraction
    fees_per_sold = c.fee_rate_on_gross * gross_sale_price + c.fee_rate_on_net * net
    revenue = y * net + (1 - y) * c.salvage_per_unsold_unit
    pct_fees = y * fees_per_sold
    fixed_sell = y * c.fixed_per_sold_unit
    total_cost = buy_price + c.repair_per_unit + c.fixed_per_purchased_unit + pct_fees + fixed_sell
    contribution = revenue - total_cost
    margin = contribution / revenue if revenue > 0 else None
    markup = contribution / total_cost if total_cost > 0 else None
    lines = [
        {"label": "Expected sale price (tax-inclusive, per sold unit)", "amount": gross_sale_price},
        {"label": "Output GST per sold unit", "amount": -tax},
        {"label": f"Saleable yield {y * 100:.1f}% x net sale price", "amount": y * net},
        {"label": "Salvage on unsold units", "amount": (1 - y) * c.salvage_per_unsold_unit},
        {"label": "Revenue (ex-GST)", "amount": revenue, "subtotal": True},
        {"label": "Purchase price", "amount": -buy_price},
        {"label": "Refurbishment / repair", "amount": -c.repair_per_unit},
        {"label": "Per-purchased-unit costs", "amount": -c.fixed_per_purchased_unit},
        {"label": "Percentage selling fees (sold units)", "amount": -pct_fees},
        {"label": "Per-sold-unit costs (sold units)", "amount": -fixed_sell},
        {"label": "Contribution", "amount": contribution, "subtotal": True},
    ]
    for ln in lines:
        ln["amount"] = round(ln["amount"], 2)
    return Economics(gross_sale_price, buy_price, tax, net, revenue, pct_fees, fixed_sell,
                     c.repair_per_unit, c.fixed_per_purchased_unit, total_cost, contribution,
                     margin, markup, lines)


def solve_buy_price(gross_sale_price: float, c: CostInputs, *, margin: float) -> float | None:
    """Purchase price at which contribution / revenue equals ``margin``.

    ``f(B) = contribution(B) - margin * revenue(B)`` is strictly decreasing in B for
    every tax mode, so bisection converges to the unique root. Returns None only if
    revenue is non-positive for every B (nothing to sell).
    """
    def f(b: float) -> float:
        e = unit_economics(gross_sale_price, b, c)
        return e.contribution - margin * e.revenue

    span = max(abs(gross_sale_price), 1.0) * 20 + 1e6
    lo, hi = -span, span
    if f(lo) < 0 or f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 2)
