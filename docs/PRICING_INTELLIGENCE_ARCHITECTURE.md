# Pricing Intelligence — Architecture

This module adds **procurement-side pricing of used IT assets** (laptops, desktops, phones, monitors,
server CPUs, server RAM and other categories) to the existing Casterly Laptop Pricing Intelligence
application. It is an extension of the existing codebase, not a separate application.

## 1. Assessment of the existing project (before this change)

| Area | Finding | Decision |
|---|---|---|
| Frontend | React 19 + TypeScript + Vite, React Router 7, no UI library; shared primitives in `components/ui.tsx`, design tokens in `styles.css` | New screens reuse `Card`, `Kpi`, `Drawer`, `PageHead`, `Loading`, `ErrorBox`, the `t` table, `badge`, `btn`, `formgrid` styles and `useLoad`/`useApp` |
| Backend | FastAPI, SQLAlchemy 2 (typed `Mapped`), Pydantic 2 settings (`CLPI_*`) | New package `backend/app/procurement/`; new routers registered in `main.py` |
| Database | PostgreSQL 14+ via Alembic (`0001_initial_schema`), SQLite fallback for tests | New migration `0002_pricing_intelligence`; no existing table altered |
| Auth | JWT bearer, role → permission map in `security.py` (admin / procurement / sales) | New `pi_*` permissions added to the same map |
| Audit | `audit_events` table + `audit.record()` | Reused as the **PricingAuditLog** (every import, research run, pricing run, override, approval, rule change, quotation, export) |
| AI | Optional Claude integration (`ai/claude.py`): extraction suggestions + explanation; never prices | Reused `_call` for (a) ambiguous-description identification and (b) search-result classification. AI never produces a price; extracted prices must appear verbatim in the provider's snippet |
| Pricing | Deterministic laptop **resale** engine (`pricing/`) with weighted statistics, versioned config | Untouched. The procurement engine is a separate pure module (`procurement/engine.py`) that reuses `pricing/stats.py` |
| Excel | Safe upload (`importing/files.py`: extension/zip-bomb/macro checks), read-only parsing, exports with formula-injection guard | Reused `validate_and_store`, `stored_path`, `safe`, header styling |
| Connectors | Manual, file import and an approved-JSON-feed adapter; no scraping by design | Same policy applied to market research: licensed search APIs only, no page scraping |
| Jobs | None | Durable DB-backed job queue (`research_jobs` / `research_tasks`) processed by an in-process worker thread or a separate `worker` container |
| Tests | 42 pytest tests (engine + API), SQLite or PostgreSQL | New tests added alongside; existing tests unchanged |

## 2. Module layout

```
backend/app/procurement/
  catalog.py        category engine, part-number decoders (RAM speed/type, CPU families, AMD OPN)
  identify.py       deterministic hardware identification + normalisation + exception detection
  excel_import.py   layout detection (B001 / B002 / generic), header-row search, totals exclusion
  excel_export.py   priced workbook: preserves the original workbook, fills/creates Market Unit Price
  rules.py          versioned pricing rule schema (Pydantic) and defaults
  engine.py         pure deterministic Decimal pricing pipeline + confidence score
  providers.py      search-provider adapters (Brave, Tavily, manual) and query generation
  extraction.py     price extraction from provider snippets, relevance matching, classification
  research.py       research job orchestration (claim, retry, cache, cancel, resume)
  worker.py         background worker loop (thread or `python -m app.procurement.worker`)
  service.py        batch import, grouping, pricing runs, overrides, approvals, quotations, history
  reference.py      reference-pack import of historical completed valuation workbooks
  accuracy.py       outcome tracking, MAE/MAPE/bias, rule-adjustment suggestions
backend/app/api/pricing_intel.py   REST API (/api/pi/...)
frontend/src/pages/pi/*            Pricing Intelligence screens
```

## 3. Data model (migration 0002)

| Table | Purpose | Key constraints |
|---|---|---|
| `pi_products` | Normalised product identity shared across batches (one research per identity) | `product_key` unique |
| `pi_batches` | ValuationBatch: one uploaded workbook, its detected layout and column mapping | sha256 indexed |
| `pi_assets` | ImportedAsset + normalised spec, one row per source row; keeps raw cells and sheet/row | (`batch_id`,`sheet`,`row_number`) unique |
| `pi_sources` | Market Source Library (domains, reliability, terms status) | `domain` unique |
| `pi_observations` | MarketObservation: price facts with URL, timestamps, price type, verification status | dedup key unique per product |
| `pi_rule_versions` | PricingRule / PricingRuleVersion (whole rule set versioned, hashed, one active) | `version` unique |
| `pi_estimates` | PriceEstimate per (batch, product, grade): benchmark, recommended, opening, max, confidence, full breakdown, input hash | (`batch_id`,`product_id`,`grade`,`input_hash`) unique → idempotent re-pricing |
| `pi_research_jobs`, `pi_research_tasks` | Durable ResearchJob with per-product tasks (attempts, status) | (`job_id`,`product_id`) unique |
| `pi_exceptions` | ReviewException with business impact and verification action | (`batch_id`,`asset_id`,`code`) unique |
| `pi_overrides` | PriceOverride history (previous, new, reason, user) | FK asset |
| `pi_quotations`, `pi_quotation_lines` | VendorQuotation + lines | `quote_ref` unique, `idempotency_key` unique, (`quotation_id`,`asset_id`) unique |
| `pi_outcomes` | Actual purchase/resale outcomes for accuracy reporting | FK product |

Money columns are `NUMERIC(14,2)`; calculations use Python `Decimal` end to end.

## 4. Processing flow

```
Upload ─▶ layout detection ─▶ rows → pi_assets (raw + mapped) ─▶ identify/normalise ─▶ group → pi_products
   ─▶ research job (one task per product, not per serial) ─▶ provider search ─▶ candidate observations
   ─▶ verification (manual or rule-based auto-accept) ─▶ pricing run (active rule version) ─▶ pi_estimates
   ─▶ review (filters, drawer, override with reason, approve) ─▶ quotation ─▶ priced workbook export
```

## 5. Key design rules

* Prices are produced only by the deterministic engine from stored observations and a versioned rule set.
* AI output is advisory: identification suggestions and search-result classification. AI-produced numbers are never used.
* A search hit without a price present in the provider's own result text is stored as a lead, never as a priced observation.
* Unconfigured conversion factors stop pricing for that line (`manual_required`) rather than inventing a discount.
* Historical reference valuations (B001/B002) are imported as `historical_valuation` observations dated 26-Oct-2026 and are
  always labelled provisional; the live engine never treats them as current market prices.
* The uploaded workbook is never modified; exports are written to a new file.

## 6. REST API (`/api/pi`, bearer auth; full schema at `/api/docs`)

| Area | Endpoints | Permission |
|---|---|---|
| Meta / dashboard | `GET meta`, `GET dashboard` | `pi_view` |
| Batches | `POST batches` (multipart: file, name, vendor, sheet, header_row, default_grade), `POST batches/manual`, `GET batches`, `GET batches/{id}`, `GET batches/{id}/preview`, `POST batches/{id}/mapping` | `pi_import` / `pi_view` |
| Pricing | `POST batches/{id}/price[?rule_version_id=]`, `GET batches/{id}/groups`, `GET batches/{id}/assets` (status, category, confidence, q, sort, desc, page, page_size) | `pi_price` / `pi_view` |
| Assets | `GET assets/{id}`, `POST assets/override` (reason required), `POST assets/approve`, `POST batches/{id}/approve-all`, `POST assets/{id}/reidentify`, `POST assets/{id}/ai-suggest` | `pi_override`, `pi_approve`, `pi_import`, `use_ai` |
| Research | `POST batches/{id}/research`, `GET jobs`, `GET jobs/{id}`, `POST jobs/{id}/cancel`, `POST jobs/{id}/resume` | `pi_research` |
| Evidence | `GET observations`, `POST observations` (manual verified evidence), `POST observations/verify` (verify / reject / reset) | `pi_verify_evidence` |
| Exceptions | `GET exceptions`, `POST exceptions/resolve` | `pi_view` / `pi_approve` |
| Quotations | `POST batches/{id}/quotations` (idempotent), `GET quotations`, `GET quotations/{id}`, `POST quotations/{id}/issue` | `pi_quote` |
| Export | `GET batches/{id}/export`, `GET quotations/{id}/export` | `export` |
| History | `GET products`, `GET products/{id}`, `POST outcomes`, `GET accuracy` | `pi_view` / `pi_outcomes` |
| Reference packs | `POST reference-packs` (multipart: file, reference_date) | `pi_rules` |
| Sources | `GET sources`, `POST sources`, `PATCH sources/{id}` | `pi_sources` (admin) |
| Rules | `GET rules`, `GET rules/versions/{id}`, `POST rules`, `POST rules/versions/{id}/activate`, `POST rules/presets/{defaults|historical_reference}` | `pi_rules` (admin) |

Roles: administrator = all; procurement = all except rules and sources; sales = view, export, outcomes.

## 7. Configuration and setup

| Variable | Purpose |
|---|---|
| `CLPI_BRAVE_API_KEY` | Brave Search API subscription token (enables live research) |
| `CLPI_TAVILY_API_KEY` | Tavily API key (alternative provider) |
| `CLPI_RESEARCH_PROVIDER` | `brave` or `tavily`; default = first configured |
| `CLPI_RESEARCH_WORKER` | `thread` (default: worker thread inside the API) or `off` (run `python -m app.procurement.worker`) |
| `CLPI_RESEARCH_POLL_SECONDS`, `CLPI_RESEARCH_HTTP_TIMEOUT` | Worker polling interval, provider timeout |
| `CLPI_ANTHROPIC_API_KEY` | Optional Claude assistance (identification suggestions) |

Provider setup: create a Brave Search API key (https://api.search.brave.com, "Data for Search" or AI plan) or
a Tavily key (https://tavily.com), put it in `.env`, restart `api` and `worker`. Check **Market research
results** — the banner shows the configured provider. Without keys the feature remains fully usable with
manual, transaction and reference evidence; the UI never claims live coverage.

Docker: `docker compose up --build -d` now also starts the `worker` service (research jobs); migrations
(`0002_pricing_intelligence`) run automatically in the `api` container. Local: `alembic upgrade head`, then
run uvicorn as before; the in-process worker starts automatically.

## 8. Security

* API keys only in environment variables; never stored in the database or sent to the browser.
* Third-party search text is untrusted: parsed with regular expressions only, length-limited, stored as data,
  rendered as text, and neutralised against spreadsheet formula injection on export. Links open with
  `rel="noopener noreferrer nofollow"`.
* No page fetching or scraping; `follow_redirects=False` on provider calls.
* Every mutation (import, remap, research, verification, pricing, override, approval, rules, sources,
  quotation, export, reference pack, AI call) is written to `audit_events`.

## 9. Implementation checklist

- [x] Assessment of existing architecture (this document)
- [x] Models + migration 0002
- [x] Identification engine (laptops/desktops/phones/tablets/monitors/docks, server CPU, server RAM)
- [x] Excel importer with B001/B002/generic detection and manual mapping
- [x] Versioned rules + deterministic Decimal engine + confidence
- [x] Research providers (Brave, Tavily), durable jobs, caching, retries, cancel/resume
- [x] APIs, permissions, audit
- [x] Priced workbook export with supplementary sheets and formulas
- [x] Frontend screens (11)
- [x] Tests (unit, API, export integrity, provider mocks, B002 regression)
- [x] Documentation, environment and Docker configuration
