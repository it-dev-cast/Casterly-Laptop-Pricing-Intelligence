# Market Pricing Methodology (procurement side)

Pricing Intelligence answers one question per asset: **what is the most Casterly should start by
offering the vendor for this used asset, ex-GST, in INR?** The answer is the *Market Unit Price*
(recommended Casterly vendor purchase price). It is produced by a deterministic engine
(`backend/app/procurement/engine.py`) from stored evidence and a versioned rule set. AI never
produces a price.

## 1. Price types are not interchangeable

| Price type (`price_type`) | Meaning | Default conversion to a buy price |
|---|---|---|
| `verified_transaction` | Casterly's own recorded purchase (or a verified bulk deal) | 1.0 |
| `bulk_wholesale` | Bulk refurbished wholesale price | 1.0 |
| `buyback_quote` | Individual-device buyback quotation | 1.0 |
| `supplier_quote` | Written supplier / vendor quotation | 1.0 |
| `refurb_retail` | Online refurbished retail selling price | **not configured** |
| `second_hand_ask` | Advertised second-hand asking price | **not configured** |
| `historical_valuation` | Casterly's dated historical estimate (reference pack) | 1.0, provisional only |

Retail and second-hand asking prices are *selling* prices. Turning them into a buy price needs a
conversion factor that reflects Casterly's own margins and costs. No factor ships as a default: until
an administrator configures one, such evidence is listed but ignored, and the line shows
**Manual pricing required** with the `conversion_not_configured` exception. Buy-side evidence is
never converted a second time.

Two more values are separated in the output and are not used as the buy price: **expected resale value**
(asking evidence × a configured realisation factor) and **expected gross margin**.

## 2. Pipeline

```
observed price
  → screening (verified only, not future-dated, freshness window, currency/FX, tax-basis policy)
  → ex-GST normalisation            inclusive ÷ (1 + GST%)
  → source-type conversion          × conversion[category][price_type]
  → evidence priority               buy-side evidence first; current evidence supersedes historical
  → independence                    weight ÷ number of observations from the same source
  → outlier removal                 > k × 1.4826 × MAD from the weighted median (n ≥ 5)
  → MARKET BENCHMARK                weighted median
  → condition adjustment            grade %   (skipped if the evidence already reflects the grade)
  → quantity adjustment             band %    (skipped if the evidence is already a bulk price)
  → risk adjustment                 per risk group, largest only (no double-discounting)
  → optional cap                    max combined discount %
  → rounding                        down to the configured ₹ step
  → RECOMMENDED BUY PRICE (Market Unit Price)
```

Weight of an observation = price-type weight × match weight (identical 1.0, comparable 0.5) ×
source reliability × 0.5^(age ÷ half-life). All arithmetic on money uses `Decimal`.

Also returned: **negotiation opening price** (recommended × (1 − opening %), when configured),
**maximum permitted purchase price** (resale × (1 − minimum margin) − purchase costs, when resale
evidence and a minimum margin are configured; a `recommended_exceeds_margin_cap` exception is raised
if the market price leaves too little margin), **estimated lot value** (quantity × unit price) and
**expected margin** = (resale − (price + purchase costs)) ÷ resale × 100.

## 3. Grouping

Identical assets share one research and one estimate: the group key is the normalised product
identity plus grade. RAM groups by DDR generation, capacity, speed and module type (manufacturer
part-number variants of the same class share one market); CPUs by exact SKU; client devices by
brand, model, CPU (or generation), RAM and storage. The group's total quantity selects the
quantity band. Export keeps one row per source row.

## 4. Status

| Status | Meaning |
|---|---|
| Auto-priced | Current, identical-match evidence; High/Medium confidence; no open high-severity exception |
| Review | Low confidence, an open high-severity exception, or a manual override awaiting approval |
| Provisional | Only historical valuations or comparable-model evidence |
| Manual pricing | No usable evidence, an unconfigured conversion, or an unidentified asset (price left blank) |
| Approved | A user approved the price (calculated or override) |

## 5. Confidence (High ≥ 70, Medium ≥ 45, otherwise Low)

Transparent points, shown in every price drawer:

| Component | Points |
|---|---|
| Exact SKU / configuration match share | 0–25 |
| Independent sources (3+ = full) | 0–20 |
| Source reliability (administrator-set) | 0–10 |
| Freshness (median age vs 2 × half-life) | 0–15 |
| Price agreement (IQR ÷ median ≤ 0.10 / 0.25 / 0.5) | 15 / 10 / 5 / 0 |
| Specification completeness (identification confidence, minus high-severity issues) | −10…10 |
| Condition certainty (grade known) | 0–5 |
| Historical accuracy (category MAPE, when ≥ 5 outcomes) | 0 / −5 / −10 |

Provisional estimates are capped at Medium. The score is not a probability.

## 6. Market research

* Licensed search APIs only (Brave Search API, Tavily). Result pages are **not** fetched or scraped.
* Queries are generated per product group from the normalised specification (2 by default).
* A hit is kept only when it matches the technical identity (CPU SKU number; RAM capacity + DDR +
  speed + server/ECC markers; laptop brand + all model tokens). Mismatches are rejected and counted.
* A price is captured only if an INR amount appears in the provider-returned text. Hits without a
  price are stored as *leads* (no price) for a user to open.
* Every captured price is a **candidate** until a user verifies it (choosing the tax basis), or an
  administrator enables auto-verification of identical matches from sources with reliability ≥ 0.6.
* Deduplication: URL + price + day + provider, within and across runs. Results are cached per product
  for `cache_days`.

## 7. Historical reference cases (B001 / B002, 26 Oct 2026)

Completed valuation workbooks can be imported as **reference packs**. Each product group's Market
Unit Price becomes one `historical_valuation` observation dated at the workbook's reference date.
These estimates are already Grade-B, bulk, ex-GST buy prices, so the grade and quantity steps are
skipped for them. They are used only when no current evidence exists and always yield *provisional*
prices. The `Historical reference configuration` preset (never activated automatically) widens the
freshness window and uses ₹1 rounding so the dated estimates are reproduced exactly; it is a
regression fixture, not a live pricing configuration.
