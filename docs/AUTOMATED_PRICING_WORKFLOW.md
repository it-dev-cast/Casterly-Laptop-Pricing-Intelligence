# Automated pricing workflow

Implementation date: 27 October 2026. Existing application modified directly; no production deployment performed.

## Procurement workflow
1. Open Pricing Intelligence → Excel bulk import.
2. Upload the vendor `.xlsx`. Import identifies the table, parses quantities and stores original bytes unchanged. The existing mapping panel remains available for unfamiliar layouts.
3. Click **Analyze & Calculate Market Prices**. No per-row prices, discount entry, keyword selection or terminal commands are needed for adequately supported products.
4. Watch backend job progress, review exceptions and source evidence, then download the completed Excel. Draft quotations are generated automatically; they are not automatically approved or issued.

The import/identification stages run during upload and their actual completion is recorded. The queue continues through Researching market → Validating price evidence → Calculating procurement prices → Generating quotation. Terminal business results are Completed, Needs Review or Research Unavailable. Operational failures remain Failed, with no successful workbook claim. Source-date uncertainty, historical fallback and missing/contradictory specifications remain visible.

## Execution and durability
`POST /api/pi/batches/{id}/analyze` checks existing price/research/quote/export permissions and returns a durable `PIResearchJob`. Repeated clicks while active return the same job. Rule version ID and full snapshot are captured. `worker.run_once` claims work before releasing its DB lock; a conditional update also prevents duplicate SQLite claims. Backoff jobs are not repeatedly claimed before due. The existing worker handles provider queries and retries. `automatic.complete` handles evidence fallback, pricing, draft quotation and workbook generation. Progress is in `GET /api/pi/jobs/{id}` under `workflow`; task counters update as work completes. Recovery requeues abandoned jobs after five minutes. The worker must remain running.

Artifacts are written outside served directories and downloaded through authenticated `GET /api/pi/jobs/{id}/workbook`; SHA-256 is checked before download. Source bytes are never edited. Authorization and mandatory override reasons use the existing audited APIs.

## First-time setup
- Configure PostgreSQL, a random production secret and bootstrap admin credentials using `.env.example`.
- Configure `CLPI_BRAVE_API_KEY` or `CLPI_TAVILY_API_KEY` once to enable live search. Configure both for provider fallback. Keys stay server-side. The optional Claude integration is not required and never supplies money.
- Optionally place completed, dated historical workbooks in `references/` and set `CLPI_REFERENCE_DIRS=["/data/references"]` for Docker. Only explicitly configured directories are imported. Test fixtures are never silently imported into a production database. Deduplication is based on content SHA, product, grade, date and amount.
- Optional approved catalog: place a JSON file in that mount, set `CLPI_APPROVED_CATALOG_PATH=/data/references/catalog.json` and `CLPI_APPROVED_CATALOG_TERMS_CONFIRMED=true` only when authorized. Records require `product_key`, positive `price`, INR `currency`, explicit `tax_basis`, `price_type`, and `observed_at`; URL, seller and condition should also be supplied. Date-less/malformed records are rejected.
- Review the installed starter policy once. Administrators may edit category/variant conversions, grades, quantity bands, risk rules and rounding in the existing Rules screen, saving a reason and new version. Untouched old initial defaults are upgraded; custom admin versions are retained.

After configuration, the supported stack starts with **`docker compose up --build -d`**. API startup runs Alembic migrations through 0003 and seeds defaults. Compose starts DB, API, external worker and web. In non-Docker development the default API worker is an in-process thread; `CLPI_RESEARCH_WORKER=off` requires a separate worker. Never enable both accidentally for a single-worker setup, though PostgreSQL claims support multiple workers.

## Evidence and fallback
The actual chain is configured search providers → approved catalog → verified cached/recorded evidence → dated historical valuation → explicit administrator-approved comparable mapping. Fresh verified cache can avoid a network call. Unusable primary results try the alternative provider. Historical evidence never becomes live evidence. A similar-model price requires a versioned `similar_model_factors` entry containing source product key, factor and reason; no generic invented adjustment is applied. Exact usable evidence takes precedence over comparable estimates.

Snippet-only amounts remain candidates and never auto-verify, even if an older `auto_accept_identical` setting exists. Automatic verification requires exact specifications, used/refurbished condition and an unambiguous INR structured product offer or single-price licensed full content. Ambiguous amounts, lot totals/per-capacity amounts without explicit unit pricing, EMI/ranges, incompatible models and unsafe URLs are rejected or held. Source timestamps and retrieval timestamps are separate; an unknown source date makes an automatic search estimate provisional. Historical, comparable and cached methods are labeled explicitly. Configured does not mean provider connectivity was verified.

## Workbooks
Default export minimally patches original OOXML pricing cells and adds report sheets. It preserves unrelated archive members, including chart/image/pivot-cache/extension bytes. B001 prices append in N for A–M inputs; B002 uses existing J. Existing report-name collisions receive unique names. Model evidence, category summaries, exceptions, source URLs/dates, confidence and policy assumptions are exported.

`GET /api/pi/batches/{id}/export?clean=true` is an alternate clean quotation export reconstructed from stored asset rows. The UI also offers **Download clean quotation**. It intentionally does not promise original workbook formatting or objects. Default preservation carries an explicit fidelity notice: Excel application rendering, pivot refresh and formula recalculation are not certified. No original file is overwritten.

## Diagnostics
`GET /api/health` checks DB and identifies configured research/worker mode. Authenticated `GET /api/pi/diagnostics` reports queue depth, worker heartbeat and provider configuration. `POST /api/pi/providers/{provider}/probe` performs a real authorized one-result connectivity check; without a key it reports BLOCKED. Compose has API and worker health checks. A persistent missing heartbeat, failed job or research-unavailable result is not a completed live valuation.
