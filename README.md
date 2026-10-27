> **Automated Pricing Intelligence update (27-Oct-2026):** Upload a vendor workbook, then use **Analyze & Calculate Market Prices** to queue research/fallback, calculation and draft quotation export. See [Automatic workflow](docs/AUTOMATED_PRICING_WORKFLOW.md) and [verified handover and limitations](docs/PRICING_INTELLIGENCE_FINAL_HANDOVER.md). Older manual screens remain available for review and administration. Startup is `docker compose up --build -d` after one-time environment setup. Actual live search requires an authorized server API key; missing evidence is flagged.

<p align="center"><img src="brand/casterly-logo.png" alt="Casterly" width="120"></p>

# Casterly Laptop Pricing Intelligence

Source repository: [it-dev-cast/Casterly-Laptop-Pricing-Intelligence](https://github.com/it-dev-cast/Casterly-Laptop-Pricing-Intelligence).
For local branches, validation and merging changes, see [Contributing](CONTRIBUTING.md).

A pricing workbench for buying and selling refurbished laptops in India. Upload a supplier's stock list and your evidence (completed sales and purchases, advertised listings, supplier quotations). The app then estimates the selling range for each line and calculates a **target buying price** and a **maximum safe buying price**. Every figure can be traced to the comparables, weights, exclusions, adjustments and assumptions behind it.

Design rules the code enforces:

- **Prices come from a deterministic engine** (`backend/app/pricing/`). It never calls a language model, never reads the database, and returns byte-identical output for identical inputs.
- **Nothing is invented.** No adjustment percentages, fees, yields or market prices ship as defaults. Anything unconfigured is either reported as an assumption or stops the calculation with a "needs input" status.
- **Asking prices are never treated as completed sales.** Retail, wholesale and as-is procurement evidence stay separate.
- **"Insufficient evidence" is a normal answer.** If a dependable estimate can't be produced, no price is shown.
- **Synthetic demo data is labelled everywhere** and is never used to value real inventory.
- **No live market coverage is claimed** until a real, permitted feed is configured and has fetched successfully.

## Pricing Intelligence (procurement valuation of used IT assets)

A second module prices **what Casterly should pay a vendor** for used laptops, desktops, workstations,
MacBooks, phones, tablets, monitors, docks, Xeon/EPYC server CPUs and DDR3/4/5 server RAM. Upload the
vendor's Excel (B001 and B002 layouts are recognised), research the Indian market through a licensed search
API, calculate a deterministic, explainable buy price per row, review evidence and exceptions, approve, and
download the vendor's own workbook with **Market Unit Price** filled in. See:

* `docs/PRICING_INTELLIGENCE_USER_GUIDE.md` — how to use it
* `docs/MARKET_PRICING_METHODOLOGY.md` — how prices are calculated
* `docs/EXCEL_IMPORT_EXPORT_SPEC.md` — workbook detection and export
* `docs/PRICING_INTELLIGENCE_ARCHITECTURE.md` — architecture, API, setup
* `docs/PRICING_ENGINE_TEST_RESULTS.md` — test and regression results

Live research needs `CLPI_BRAVE_API_KEY` or `CLPI_TAVILY_API_KEY`; without them, pricing uses verified manual
quotes, recorded purchases and historical reference valuations only.

---

## Quick start (Docker)

Requires Docker Desktop.

```bash
cp .env.example .env
```

Edit `.env` and change every value marked CHANGE: the database password, `CLPI_SECRET_KEY`, and the first administrator's email and password. Then:

```bash
docker compose up --build -d
```

Open http://localhost:8088 and sign in as the administrator from `.env`. The interactive API docs are at http://localhost:8088/api/docs.

- Migrations run automatically when the `api` container starts.
- The first administrator is created only when the database has no users.
- To stop: `docker compose down`. Data persists in the `pgdata` and `uploads` volumes; `docker compose down -v` deletes them.
- To try the app without real data, sign in as admin and use **Load the synthetic demo dataset** on the dashboard (or **Users & audit → Load demo data**). Then switch the top bar to **Synthetic demo**.

Ports: the UI and API are both served on `CLPI_WEB_PORT` (default 8088) through nginx. PostgreSQL is not published to the host.

## Local development (without Docker)

Requirements: Python 3.12+, Node 20+, PostgreSQL 14+.

```bash
cd backend
pip install -r requirements-dev.txt
```

Create `backend/.env`:

```
CLPI_DATABASE_URL=postgresql+psycopg2://USER@127.0.0.1:5432/clpi
CLPI_SECRET_KEY=<long random string>
CLPI_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
CLPI_BOOTSTRAP_ADMIN_PASSWORD=<password>
CLPI_UPLOAD_DIR=backend/data/uploads
```

Then, from the repository root:

```bash
cd backend && python -m alembic upgrade head && cd ..
```

```bash
python -m uvicorn app.main:app --app-dir backend --env-file backend/.env --port 8010
```

```bash
npm --prefix frontend install
```

```bash
npm --prefix frontend run dev
```

The UI runs at http://localhost:5180 and proxies `/api` to port 8010. Set `VITE_API_PROXY` to point it at another API address.

### Tests

The suite covers the resale engine, the Pricing Intelligence module (identification, engine, research jobs, import/export, B002 regression) and end-to-end API flows. To run the API tests against PostgreSQL, using the real Alembic migrations:

```bash
cd backend
CLPI_TEST_DATABASE_URL=postgresql+psycopg2://USER@127.0.0.1:5432/clpi_test python -m pytest tests -q
```

The test database is wiped on every run. Without `CLPI_TEST_DATABASE_URL`, the API tests fall back to a temporary SQLite file.

### Sample upload templates

`templates/` holds an Excel and a CSV template for each record type, with an Instructions sheet. They are generated from the importer's own field definitions and contain no example prices. Regenerate them with `python scripts/make_templates.py`, which also copies them to `frontend/public/templates/` for download from the upload screen.

---

## Workflow

1. **Upload** (Upload & review): choose the record type, download its sample Excel template if you need the format (step 2 on that screen; also on the Inventory and Market evidence pages), fill the **Data** sheet, and drop the `.xlsx` or `.csv` file. The templates have dropdowns for fixed-value columns, a format note on every header, and required columns highlighted.
2. **Sheets & columns**: select one or more sheets. Columns are auto-mapped from header synonyms, and title rows above the header are skipped. You can apply or save named mappings, and set batch defaults (lot, channel, tax basis, currency) that fill blank cells only, each recorded as a warning on the row.
3. **Review & correct**: every row is shown with its status (valid, warnings, invalid, duplicate, needs review, skipped) and its issues. A row drawer shows each field's original cell, parsed value and errors. Corrections are recorded against the original value, with an optional reason. Rule-based (and optionally AI) extraction from descriptions produces suggestions that you must accept one by one. Import issues can be downloaded as CSV or Excel.
4. **Commit**: valid rows become records. Each record keeps `raw_values` (the original cells) and `corrections`. Duplicates are skipped unless you mark them "keep anyway".
5. **Value** (Inventory & lots): value selected lines or a whole lot. Each run is stored as an immutable snapshot.
6. **Inspect** (Valuation detail):
   - the verdict and decision prices;
   - selling-side and buying-side price ladders;
   - unit economics at the recommended buy, the safe ceiling and the supplier's ask;
   - every input and its source;
   - the evidence-quality breakdown;
   - included and excluded comparables, with weights, adjustments, source links and exclusion reasons;
   - all assumptions;
   - a one-click reproducibility check.
7. **Export**: one valuation as a multi-sheet Excel workbook, the latest valuations (all or per lot) as Excel or CSV, or evidence tables.
8. **Outcomes**: record actual sales and purchases against items. They become completed-transaction evidence and are compared with the valuation that was current at the time.

## Record types

| Type | Table | Role in pricing |
|---|---|---|
| Inventory being valued | `inventory_items` (+ `lots`) | The subject of a valuation |
| Advertised listings | `market_listings` | Asking prices: listing-price guidance only |
| Supplier quotations | `supplier_quotes` | As-is procurement market, shown beside buy prices |
| Completed purchases and sales | `transactions` | Sales are the primary basis for expected selling prices |

Every evidence record stores:

- **Provenance:** source type, source URL (only if supplied), uploaded-document reference (file, sheet and row), source record ID, seller or counterparty, platform, and region.
- **Price facts:** currency, price, tax basis, and the listing, quote or transaction date.
- **Observation details:** observation timestamp, availability, specification, condition, and warranty.

`NULL` always means *missing*. An explicit `0` is stored as 0.

## Pricing method

**1. Screening.** Each candidate record is excluded with a stated reason if any of these apply:
- It is synthetic while the item is real, or the reverse.
- It is a different brand or model.
- It has no price.
- Its channel is unknown (sales and listings only).
- Its currency is foreign and no FX rate is configured.
- Its tax basis is unknown and the configured policy for that evidence type is "exclude".
- It is dated or observed after the valuation time.
- It is older than the configured maximum age for its type (default: sales 180 days, listings 45, quotes 30, purchases 180).
- It is a listing marked out of stock or removed, or a quotation that has expired.

**2. Tax normalisation.** Every price is converted to a GST-inclusive basis before comparison. Inclusive prices stay as they are. Exclusive prices are multiplied by (1 + GST). Unknown-basis prices follow the configured per-type policy, and every record affected is counted in the assumptions.

**3. Deduplication.** Records are linked by union-find; each group keeps its most recent observation, and every other member is excluded with the reason that linked it. A link is made by:
- the same source URL;
- the same source record ID on the same platform or seller;
- repeated listings from the same seller with the same configuration, within a price tolerance (default 2%) and time window (21 days);
- syndicated offers: identical title, the same configuration, and a near-identical price (0.5%) across different sellers within 7 days.

**4. Configuration matching.**
- *Required dimensions* (default: exact CPU, RAM, storage capacity, condition grade) must be known on both sides and equal.
- *Optional dimensions* (storage type, GPU, display, charger, warranty) are compared only when both sides are known. If either side is unknown, the match is *unverified*.
- Battery health must be within a tolerance (default 10 points).
- A difference is allowed only if an explicit **adjustment rule** exists for it (dimension, comparable value → subject value, percent or INR amount, optional exact inverse). The rule is applied and recorded on the comparable. Rules marked uncalibrated appear as warnings on every valuation that uses them.
- Exact and unverified matches are used first. Adjusted matches are added only when there are fewer than the minimum number of comparables.

**5. Weighting and statistics.** Each comparable's weight is:
- recency: 0.5^(age ÷ half-life), default half-life 60 days; times
- match tier: exact 1.0, unverified 0.8, adjusted 0.5; times
- 1 ÷ (number of records from the same source), so one seller cannot dominate.

Records further than 3.5 × scaled MAD from the weighted median are excluded when a set has at least 5 records. Ranges are weighted quantiles (midpoint method), and the expected price is the weighted median. All of these values are configuration, listed in each valuation's assumptions, and are *not* calibrated.

**6. Evidence sets.** Comparables are split into `sale:<channel>`, `listing:<channel>`, `quote` and `purchase`, and each set is summarised separately. A set is *sufficient* with at least 3 comparables from at least 2 independent sources (configurable).

**7. Expected selling price.** This comes from sufficient completed sales in the item's intended channel. Asking prices can stand in only if an asking-to-sale ratio is configured for that channel; that ratio is reported as an assumption, and the rating is lowered. Otherwise the result is **insufficient evidence**.

**8. Economics, per purchased unit.**
- `revenue = yield × net sale price + (1 − yield) × salvage` (ex-GST)
- `contribution = revenue − purchase price − repair − per-purchased-unit costs − yield × (percentage fees + per-sold-unit costs)`
- **margin = contribution ÷ revenue**. **Markup = contribution ÷ total cost**, shown separately and never used as margin.
- Percentage fees are applied to either the GST-inclusive or the ex-GST sale price, as configured for each fee.
- Tax modes:
  - *standard*: full GST on the sale; purchase prices are compared ex-GST, with input tax assumed recoverable.
  - *margin scheme*: GST is charged on (sale price − purchase price) when that is positive; there is no input tax credit.
  - *none*.
- **Target buy** is the purchase price at which margin equals the target margin, at the median sale price.
- **Maximum safe buy** is the purchase price at which margin equals the configured ceiling margin (default 0%, i.e. break-even), at the conservative 25th-percentile sale price.
- **Recommended buy** is the lower of the two.
- Both prices are found by bisection on the same forward function, so they can never disagree with it. Negative results stay negative and are flagged (`negative_ceiling`, `infeasible_margin`); they are never replaced with zero.

**9. Mixed and defective lots.**
- Each line resolves its fault category from the recorded category, or from the fault text by configured keywords. "None" means explicitly no faults; blank means unknown.
- Yield, repair cost and salvage come from the item first, then from its fault category.
- If no yield exists anywhere, no buying price is produced; the app does not assume every unit sells.
- A missing repair cost on a faulty item also stops the calculation. On a no-fault item it is treated as 0, with a warning.
- Lot totals sum only the lines that have a computed price, and they say so.

**10. Evidence-quality rating.** This is a transparent points score, graded A to D. Points come from comparable count, independent sources, freshness (weighted median age), exact-match share, dispersion (IQR ÷ median) and evidence type (completed sales vs asking × ratio). Missing subject fields subtract points. **It is not a calibrated probability.**

**11. Snapshots and reproducibility.** Each valuation stores the full input: the subject, every evidence record as it was, the complete configuration, the engine version and the as-of time. It also stores the full output, plus SHA-256 hashes of both. "Verify reproducibility" re-runs the engine on the snapshot and compares the hashes.

## Validation

Go to **Validation → Run**. The most recent fraction of completed sales (default 30%) is held out. Each held-out sale is priced as of the day before it happened, using only evidence dated and observed before then. The result is compared with a **simple median baseline**: the plain median of earlier identical-configuration sales in the same channel.

The report shows:
- how often each method produced an estimate;
- MAE, MAPE and median APE on the cases where both did;
- empirical coverage of the P25–P75 and P10–P90 ranges.

Measured on the **synthetic demo data** only (36 held-out sales, 23 head-to-head):

| | Engine | Median baseline |
|---|---|---|
| MAPE (head-to-head) | 5.3% | 5.7% |
| Median APE | 4.1% | 3.6% |
| P25–P75 coverage | 26% (nominal 50%) | — |
| P10–P90 coverage | 43% (nominal 80%) | — |

These numbers say nothing about real-market accuracy. They do show that the comparable ranges are **narrower than true prediction intervals**: they describe the spread of comparable prices, not the uncertainty of a single future sale. Treat the ranges accordingly until real held-out sales show otherwise. Price forecasting is deliberately not implemented.

## Configuration (Cost & margin settings)

Settings are versioned; every save creates a new version with a note, and each valuation records the version it used. As shipped:

- **Not configured:**
  - default target margin;
  - every marketplace and payment fee rate;
  - logistics, packaging, warranty-provision, inbound and QC costs;
  - asking-to-sale ratios;
  - fault-category yields, repair costs and salvage values;
  - adjustment rules (there are none);
  - FX rates.
- **Configured defaults (all editable):**
  - GST 18%, labelled "confirm with your tax advisor";
  - unknown tax basis: listings assumed GST-inclusive, all other evidence excluded;
  - the matching, weighting, freshness, deduplication and rating thresholds described above.

The dashboard lists every configuration gap.

## Roles

| Permission | Administrator | Procurement | Sales |
|---|---|---|---|
| View, value, export | ✓ | ✓ | ✓ |
| Import inventory and evidence | ✓ | ✓ | |
| Edit inventory and evidence, add quotes | ✓ | ✓ | |
| Add listings | ✓ | ✓ | ✓ |
| Record purchases | ✓ | ✓ | |
| Record sales | ✓ | | ✓ |
| Run validation | ✓ | ✓ | |
| Settings, connectors, users, audit log, demo data | ✓ | | |

Every mutation is written to `audit_events`, including logins, failed logins, uploads, staging, corrections, commits, valuations, exports, settings saves, connector runs, AI calls and demo loads.

## File handling and security

- Only `.csv` and `.xlsx` files are accepted, up to `CLPI_MAX_UPLOAD_MB` (10 MB by default).
- **Content checks:** the content must match the extension (an XLSX is a ZIP containing a workbook part; a CSV is decodable text with no NUL bytes). Macro-enabled workbooks (`vbaProject.bin`) and legacy `.xls` files are rejected.
- **Size limits:** the total uncompressed size of an XLSX is checked before parsing (zip-bomb guard), and there is a row limit.
- **Workbooks are parsed as data only:** they are opened read-only with cached values, so formulas are never evaluated. Cell contents are treated as data.
- **Storage:** uploads are stored under random names outside any served directory, with their SHA-256 recorded.
- **Exports:** spreadsheet exports neutralise formula injection (cells starting with `=`, `+`, `-` or `@`).
- **Authentication:** passwords are bcrypt-hashed, and logins return JWT bearer tokens (HS256, 8-hour expiry). The UI keeps the token in `sessionStorage`.
- **Secrets:** they live only in the environment. Connector settings refuse secret-looking keys and instead name an environment variable.

## Market ingestion and connectors

Only **manual entry** and **bulk file import** are live.

- **`http_json_feed` adapter:** a generic client for an *approved* API or permitted JSON feed.
  - **Disabled until configured:** an administrator must supply an HTTPS URL and a field mapping, and set `terms_confirmed: true` after checking that the provider's terms allow this use.
  - **API keys:** they are read from an environment variable named in `api_key_env`, never stored in the database.
  - **Behaviour:** it does not scrape pages or follow redirects, and it stores only the URLs the feed provides.
- **Connector status** (Connectors page): status, last attempt, last success, failure count, last error, records held, and how many are past the freshness limit.
- **The dashboard says plainly** "No live market connector is configured" until a feed has fetched successfully in the last 2 days.

No real feed is configured in this build.

## Optional AI (Claude)

Set `CLPI_ANTHROPIC_API_KEY` (server-side only) to enable two features:
- **Extract with AI:** suggests specification fields from a row's title or description. Each suggestion must quote supporting text found verbatim in the document, otherwise it is downgraded to low confidence. Nothing is applied until the user accepts it.
- **Explain with AI:** a plain-language explanation of a computed valuation. Every figure in the explanation is checked against the valuation, and any figure not found there is listed as unverified.

How the integration behaves:
- **Prompt safety:** document text is passed as delimited, untrusted data, with an instruction not to follow anything inside it.
- **Model and fallbacks:** the default model is `claude-opus-5-5`, with server-side refusal fallbacks enabled.
- **Without a key:** the rule-based extractor and every pricing feature still work.

## Project layout

```
backend/
  app/pricing/      engine: config schema, matching, dedup, statistics, economics, orchestration (pure)
  app/importing/    safe file reading, field definitions, row validation, staging/corrections/commit
  app/services/     valuation runs & snapshots, backtest, exports, demo data, versioned config
  app/connectors/   connector adapters
  app/ai/           rule-based extractor, optional Claude client
  app/api/          FastAPI routers
  alembic/          migrations
  tests/            engine and API tests
frontend/src/       React + TypeScript UI
templates/          sample upload templates
scripts/            template and brand-asset generators
brand/              Casterly logo (source and trimmed)
```

### Logo

The official logo lives in `brand/casterly-logo-source.png`. Every variant the app uses (sidebar mark, login logo, favicons, Excel export logo) is generated from it:

```bash
python scripts/make_brand_assets.py
```

Re-run `python scripts/make_templates.py` afterwards so the templates pick up a changed logo.

## Known limitations

- **No live market feed is connected.** Live market coverage needs a provider you are permitted to use.
- **Uncalibrated defaults.** The match weights, recency half-life, outlier rule and rating thresholds are defaults chosen for explainability, not fitted to data. Calibrate them once real completed-sales history is available, using the Validation page.
- **Ranges are not prediction intervals.** As the synthetic validation shows, the P25–P75 and P10–P90 ranges under-cover.
- **Tax treatment is simplified.** GST on marketplace fees is assumed recoverable, and salvage values are entered net of tax.
- **CPU equivalence needs explicit rules.** Matching is exact on the normalised CPU model, so CPU equivalence classes need adjustment rules on the `cpu_key` dimension.
- **No auth extras.** Single sign-on, password reset by email and multi-factor authentication are not implemented.
