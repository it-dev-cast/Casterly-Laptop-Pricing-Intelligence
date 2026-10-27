# Pricing Intelligence implementation audit

Audit performed 27 October 2026 against the existing source, before implementation changes.

## Executed baseline
71 backend tests passed, 1 skipped (missing original/priced B001 workbooks), in 24.84s. Frontend TypeScript/Vite production build passed. Tests use SQLite, not PostgreSQL. Docker engine pipe is absent. Brave/Tavily keys are absent from both root and backend environment files. Actual live research is BLOCKED, not passed by mock.

## Actual call trace
PiImport.submit -> POST /api/pi/batches -> pricing_intel.upload_batch -> service.import_batch -> validate_and_store -> service._load_rows -> excel_import.read_workbook -> identify.identify. This stops after import/identification. User separately calls /batches/{id}/research -> research.create_job -> worker.run_once -> research.run_job -> _research_product -> BraveProvider.search or TavilyProvider.search. Results default to candidates; user must verify, then separately POST /batches/{id}/price -> service.price_batch -> engine.price_group, then GET /batches/{id}/export -> excel_export.build. No orchestration joins these steps.

## Findings
| Component | Before | Evidence |
|---|---|---|
| Excel import | Implemented and baseline tested | excel_import.read_workbook/_rows/parse_quantity; B001 Net Leased Qty, B002 existing price field |
| Frontend | Real API integration, manual sequence | PiImport, PiResearch, PiReview, PiQuotations use separate actions |
| Brave/Tavily | Real HTTP adapters, live execution blocked | providers.py GET/POST, timeout/auth/retry classification; no alternate-provider fallback, weak response-shape validation |
| Evidence validation | Partial | extraction.to_candidate chooses minimum snippet price; exact match can overstate RAM/CPU variant equivalence; search retrieval timestamp substitutes for source timestamp |
| Queue | Partial | Persistent jobs/tasks and recovery exist; SELECT lock released before claim, counters only finalized at end, no automatic calculation/export |
| Policies | Partial | default_rules leaves retail conversions, grade/quantity/risk rates unset; source-type/Decimal engine otherwise implemented |
| Product identity | Partial | catalog/identify decode part numbers, P1 generation and Apple ambiguity; GPU omitted from non-workstation keys; functional state not separated |
| History | Implemented but manual ingestion | reference.import_reference_pack deduplicates dated provisional evidence; no configured reference discovery/startup import |
| Approved feeds | Implemented but disconnected from PI | connectors.adapters.run_feed populates legacy MarketListing rather than PIObservation; candidate source list is not an integration |
| AI | Implemented optional assistance | ai/claude.py and /assets/{id}/ai-suggest; suggestions and explanations only; no prices generated |
| Export | Partial | excel_export.build rewrites workbook with openpyxl; original stored file untouched, but unsupported OOXML can be lost; _sheet can delete suffixed existing sheet; checks filled count only |
| PostgreSQL | Schema/migrations exist, runtime unverified | alembic 0001/0002, JSONB variants, persistent PI products/evidence/estimates/quotes |
| Operations | Partial | Compose DB/API/worker/web and API health; no worker heartbeat/provider diagnostic; local Docker engine unavailable |

No hardcoded B001/B002 price table was found in production procurement code. catalog.py contains hardware naming knowledge, not monetary values. services/demo.py is an explicit separate legacy demo path. Providers perform real calls. Historical valuations are explicitly typed and provisional. Existing source domains are documented candidates, not vendor integrations. Main gaps: disconnected automation, missing starter rules, candidate verification, timestamps and workbook fidelity.

## Reference discovery
Only backend/tests/fixtures/reference/CIN-20261026-B002_Market_Unit_Prices_Researched.xlsx exists. Missing: CIN-20261026-B001_Asset List.xlsx, CIN-20261026-B001_Used_Asset_Market_Prices.xlsx, original CIN-20261026-B002_Asset List.xlsx. No unrestricted search of personal directories. Synthetic tests must remain labeled synthetic. The completed B002 can be stripped of prices in memory for independent import checks, but is not the original unpriced source.

## Remediation
Add durable one-click orchestration and progress; seed versioned starter assumptions without replacing admin rules; validate offers and fall back across providers; reuse configured catalog/history; preserve OOXML parts with minimal patching and clean export option; test real APIs, B002, synthetic B001 and complex workbooks. Final executed evidence and residual limits are recorded in the handover and validation documents.

## Remediation verification

Implementation and final executed checks are documented in PRICING_INTELLIGENCE_FINAL_HANDOVER.md. The automatic path and default policy gaps above were corrected; actual live-provider, PostgreSQL/Docker runtime, original B001 and Excel pivot-render checks remain explicitly limited or blocked. No production market values were hardcoded.

## Continuation validation — 27 October 2026

The user supplied the actual originals at `D:\CIN-20261026-B001_Asset List.xlsx` and `D:\CIN-20261026-B002_Asset List.xlsx`. Copies were placed in the already git-ignored local fixture directory. Original files remain unchanged. Both originals now pass parsing and complete queued export checks.

- **PostgreSQL 18:** full suite ran against a separate temporary instance on loopback, with its own disposable `_test` database: **94 passed, 1 skipped in 77.50s**. Actual migrations were executed. The test harness now refuses an explicit PostgreSQL test URL whose database name does not end in `_test`, to protect operational data.
- **Docker:** actual backend and frontend images built successfully. A separate `clpi-audit` stack used PostgreSQL 16, API, worker and nginx web; existing CLPI/other stacks were not redeployed. DB/API/worker health passed; web HTTP returned 200. In the API container, Alembic reports `0003 (head)` and `alembic check` reports no new operations. Worker diagnostics returned exit 0.
- **Original B001:** 42 lines, 1,324 units, `Net Leased Qty`, Market Unit Price in N. Upload → separate worker → preserved export passed. In the absence of a live key or completed B001 historical reference, its prices remain blank and status is **Research Unavailable**. This is correct insufficient-evidence handling, not a completed monetary valuation or the historical INR 20,260,000 regression.
- **Original B002:** 2,892 rows, 2,698 RAM / 194 CPU. Upload → separate worker → preserved export populated **2,891** column-J historical prices, with one ambiguous SKU held. Supported subtotal **INR 13,334,100**, dated historical/provisional. No serial mapping or unrelated original cell data changed.
- **Still external:** live API keys remain absent; actual four-device live research remains BLOCKED. Only the completed/priced B001 reference is now missing for its exact historical total regression. Browser visual and Excel pivot-refresh acceptance remain unverified as previously stated.

Evidence: `PRICING_INTELLIGENCE_POSTGRESQL_TEST_RESULTS.xml`, `DOCKER_RUNTIME_VALIDATION.json`. User-facing review files: `B001_Needs_Research_Review.xlsx` and `B002_Historical_Provisional_Valuation.xlsx` (historical, not live).
