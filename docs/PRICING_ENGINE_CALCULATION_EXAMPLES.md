# Pricing engine calculation examples

All amounts below are **illustrative synthetic test inputs, not live market quotations or production rate tables**. The engine uses Decimal arithmetic; rounding is down to INR 50 in starter policy v1. Detailed generated calculations are in `PRICING_CALCULATION_EXAMPLES.json`.

| Synthetic input | Buy-side benchmark | Grade | Quantity adjustment | Recommended unit | Opening offer |
|---|---:|---|---|---:|---:|
| One Grade B phone from a retail offer | 7000.00 | 10% | 0% | 6300.00 | 5950.00 |
| 862 Grade B phones from the same retail offer | 7000.00 | 10% | 8% | 5750.00 | 5450.00 |
| 862 Grade B phones from a buyback quotation | 10000.00 | 10% | 8% | 8250.00 | 7800.00 |
| Grade A DDR4 ECC module from approved catalog | 6500.00 | 0% | 0% | 6500.00 | 6150.00 |
| Recorded historical Grade B purchase valuation | 10000.00 | 0% | 0% | 10000.00 | 9500.00 |

For the 862-phone retail example: INR 11,800 including 18% GST → INR 10,000 ex-GST → 0.70 retail-to-buy factor → INR 7,000 benchmark → Grade B 10% → 500+ quantity band 8% → INR 5,796 before rounding → INR 5,750 recommendation. An individual-device buyback quotation uses a different source conversion (1.00), producing INR 8,250 under the same grade/quantity assumptions. This demonstrates source-type differences; it does not establish a market price for Samsung phones.

## Starter assumptions, not market truths
- Retail conversion factors: generic laptop/desktop/workstation 0.65; phone 0.70; MacBook 0.68; monitor 0.60; accessories 0.55. Server variants: DDR3 0.55, DDR4 0.65, DDR5 0.70, Xeon 0.60, EPYC 0.65. Second-hand asking factor 0.80. Auction advertised/hammer factor 0.90 with explicit tax basis required. Direct quotes/verified bulk transactions use 1.00 before additional applicable conditions.
- Grade A/New/A+ reference 0%; B 10%; C 25%; D 50%; untested 35%.
- Quantity bands 1–9/10–49/50–99/100–499/500+ use 0/2/4/6/8%. Evidence already representing bulk purchases avoids another bulk discount.
- Explicit battery, missing accessory, unknown lock, legacy-platform and condition risks are versioned. Condition-group risks use the larger adjustment rather than stacking the same grade/test risk twice. Historical prices of the same recorded grade do not receive the same grade/bulk/risk adjustment again. A combined discount cap is recorded.
- Normal resale spread, ordinary warranty exposure, holding and commercial uncertainty are represented by conversion assumptions; actual physical inspection and measured costs can supersede these assumptions. This release does not claim empirically calibrated repair/battery/logistics costs for every model.
- A negotiation opening can be derived from the configured 5% opening discount. **No maximum safe purchase price or resale value is invented by default.** Those require explicit resale-realisation, cost and margin inputs supported by independent evidence. Existing margin calculations remain available.

The qualitative business basis was researched from [Dell's cosmetic grades](https://www.dellrefurbished.com/cosmetic-grades) (grade differences are cosmetic and Grade B is generally cheaper, with equivalent functionality/warranty there) and [Cashify's condition-verification guidance](https://www.cashify.in/faq/paid-amount-different-from-shown-placing-the-order) (screen, battery and accessory inspection can change a quote). **Neither source supplies the starter percentages above.** They are documented initial Casterly policy assumptions requiring administrator review and calibration against recorded outcomes.

Source timestamps, retrieval timestamps, evidence type, exclusions, conversion, grade, quantity, risk, rounding, rule hash/version and confidence contributions remain inspectable. Historical and comparable-only prices remain provisional. No-evidence results remain blank and flagged.
