# Pricing Intelligence final handover

The existing application at `D:\Casterly\Casterly-Laptop-Pricing-Intelligence` was audited and modified directly on 27 October 2026. The automatic offline/approved-evidence workflow is implemented and integration-tested. Actual live-provider pricing remains blocked pending a user-configured API key. PostgreSQL and Docker runtime acceptance have now passed in isolated audit environments. Nothing was deployed to production or pushed to GitHub.

## Continuation validation — 27 October 2026

The user supplied the actual originals at `D:\CIN-20261026-B001_Asset List.xlsx` and `D:\CIN-20261026-B002_Asset List.xlsx`. Copies were placed in the already git-ignored local fixture directory. Original files remain unchanged. Both originals now pass parsing and complete queued export checks.

- **PostgreSQL 18:** full suite ran against a separate temporary instance on loopback, with its own disposable `_test` database: **94 passed, 1 skipped in 77.50s**. Actual migrations were executed. The test harness now refuses an explicit PostgreSQL test URL whose database name does not end in `_test`, to protect operational data.
- **Docker:** actual backend and frontend images built successfully. A separate `clpi-audit` stack used PostgreSQL 16, API, worker and nginx web; existing CLPI/other stacks were not redeployed. DB/API/worker health passed; web HTTP returned 200. In the API container, Alembic reports `0003 (head)` and `alembic check` reports no new operations. Worker diagnostics returned exit 0.
- **Original B001:** 42 lines, 1,324 units, `Net Leased Qty`, Market Unit Price in N. Upload → separate worker → preserved export passed. In the absence of a live key or completed B001 historical reference, its prices remain blank and status is **Research Unavailable**. This is correct insufficient-evidence handling, not a completed monetary valuation or the historical INR 20,260,000 regression.
- **Original B002:** 2,892 rows, 2,698 RAM / 194 CPU. Upload → separate worker → preserved export populated **2,891** column-J historical prices, with one ambiguous SKU held. Supported subtotal **INR 13,334,100**, dated historical/provisional. No serial mapping or unrelated original cell data changed.
- **Still external:** live API keys remain absent; actual four-device live research remains BLOCKED. Only the completed/priced B001 reference is now missing for its exact historical total regression. Browser visual and Excel pivot-refresh acceptance remain unverified as previously stated.

Evidence: `PRICING_INTELLIGENCE_POSTGRESQL_TEST_RESULTS.xml`, `DOCKER_RUNTIME_VALIDATION.json`. User-facing review files: `B001_Needs_Research_Review.xlsx` and `B002_Historical_Provisional_Valuation.xlsx` (historical, not live).

## Management report
| Requirement | Before | After | Verified |
|---|---|---|---|
| Automatic Excel import | Separate import/identification action | Upload parses/maps assets and records completion before queued analysis | Existing APIs, structural B001/B002 tests |
| Automatic product identification | CPU/RAM decoding and exception flags; generic CPU class/GPU/condition grouping gaps | CPU class + generation, GPU and functional-risk distinctions; working/refurbished no longer fabricate cosmetic grade | Unit and integration tests |
| Live Indian market research | Actual adapters existed but disconnected; candidates not automatically usable | Configured provider selection/fallback, exact confirmed offer validation, provenance and source-date uncertainty | Simulated transports passed; ACTUAL LIVE TEST BLOCKED: API credentials absent |
| Default procurement rules | Retail conversions and adjustments unset | Versioned documented starter assumptions, including DDR/Xeon/EPYC variants and untested grade; admin versions preserved | Clean DB startup/policy tests |
| Bulk discount calculation | Calculator existed but default rates unset | Configurable quantity bands and grade/risk handling; no repeated bulk or same-condition discount | Decimal calculation tests incl. 862-phone case |
| Historical pricing fallback | Manual reference upload before reuse | Configured completed-reference discovery, identity-version-aware dedup, automatic future reuse; historical/provisional labeling | Actual B002 fixture via one-click worker/export |
| Automatic Excel export | Separate openpyxl round-trip export | Queued draft quotation + authenticated hashed workbook artifact; minimal original-package patch and alternate clean export | Worker/API/download/integrity tests |
| B001 regression | Original fixtures absent | Original 42-line/1,324-unit import and queued export now pass; synthetic monetary checks also pass | Original historical TOTAL still SKIPPED: priced B001 reference absent |
| B002 regression | Manual historical regression path | Original unpriced workbook verified: 2,892 rows; 2,698 RAM/194 CPU; 2,891 supported export prices and one ambiguous SKU held | Original-workbook PostgreSQL tests and separate Docker worker PASSED |
| Source traceability | URL/date/type fields existed; retrieval/source dates conflated | Queries, seller, type, match, rejection, source/research dates, actual evidence method and rule snapshot inspectable | API, export and simulated provider tests |

## Initial validation record (superseded where noted above)
- Baseline: 71 backend tests passed, 1 skipped; original frontend production build passed.
- Final backend: 92 passed, 1 skipped (original B001 files absent); actual final execution is in `PRICING_INTELLIGENCE_TEST_RESULTS.xml`.
- After the final lot-total/per-capacity unit-price rejection guard, the 3 directly affected extraction/provider integration tests passed again (3.75s).
- Frontend: 5 React component workflow tests passed. TypeScript checks and production build passed. npm dependency audit reported zero vulnerabilities after adding test dependencies.
- Fresh SQLite: real Alembic upgrade 0001 → 0002 → 0003 passed; current revision 0003; `alembic check` reported no new operations. PostgreSQL dialect migration SQL generated through 0003, but that is not a PostgreSQL execution claim.
- `docker compose config --quiet` passed. Actual container builds, container health and PostgreSQL migration/concurrency execution remain BLOCKED: the Docker engine pipe is unavailable and the project's configured PostgreSQL URL cannot be reached.
- Background thread test actually starts the application worker, submits analysis through the API and waits for the generated workbook without running a per-job command.
- Live verification script executed: four public hardware cases BLOCKED, zero live requests, exact requirement `CLPI_BRAVE_API_KEY` or `CLPI_TAVILY_API_KEY`. See `MARKET_LIVE_RESEARCH_RESULTS.json`.
- Visual browser check was attempted against an isolated test app. The browser security gate denied origin access. No alternate browser or bypass was attempted; visual/browser-download acceptance remains unverified. Temporary test servers were stopped.
- Real Excel pivot refresh/render acceptance remains unverified. Chart/image/formula preservation and opaque cache/extension byte preservation were tested; these are not an Excel rendering guarantee. The UI and exports state the fidelity limitation and provide a clean quotation alternative.

## Business limits
The B002 supported historical subtotal is INR 13,334,100; INR 3,000 for the ambiguous SKU is deliberately held. The original historical INR 13,337,100 is reproduced only by the existing test after an explicitly authorized SKU correction. No such correction is performed automatically. Historical reference prices are dated 26 October 2026 and never labeled live. The synthetic B001 total is not the missing B001 historical total.

Starter percentages are policy assumptions, not observed market prices or empirically calibrated procurement economics. Administrators can change them with a versioned reason. Safe maximum/resale prices remain absent until adequate resale/cost/margin inputs are configured. The generic similar-model mechanism only runs with an explicit approved mapping/factor/reason, never an invented adjustment.

Configured reference directories are reprocessed once for the improved identity version, preserving existing observations and avoiding duplicate entries. Legacy ambiguous generic-CPU history without an available reference file is not silently reassigned to a specific i5/i7 product. Such records require administrator identity review or a supported dated reference reimport.

## Remaining setup / release steps
1. Select/configure the intended deployment PostgreSQL service. Real PostgreSQL migrations and tests have now passed on isolated instances. `CLPI_TEST_DATABASE_URL` tests recreate the public schema and must NEVER point to an operational database.
2. Configure at least one authorized live-search key on the server and validate actual returned offers with `python ../scripts/verify_live_research.py` from backend. Do not paste keys into chat or expose them to the browser.
3. Review the starter assumptions once and optionally configure approved reference directories/catalog data. Ordinary procurement valuations then require only workbook upload and the Analyze button.
4. Optionally supply the completed/priced B001 reference for its exact historical-total regression. Both original unpriced files are now verified. Do not commit confidential fixtures.
5. Docker Desktop is now running and container validation passed. For an authorized target deployment, use `docker compose up --build -d`. Confirm API and worker health. Production deployment still requires separate authorization.

## Files changed
The repository initially showed the whole supplied project as untracked; that pre-existing state was preserved. No broad git add/commit was performed. Implementation files touched or added in this task:

- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/api/pricing_intel.py`
- `backend/app/procurement/automatic.py`
- `backend/app/procurement/diagnostics.py`
- `backend/app/procurement/xlsx_patch.py`
- `backend/app/procurement/engine.py`
- `backend/app/procurement/extraction.py`
- `backend/app/procurement/identify.py`
- `backend/app/procurement/models.py`
- `backend/app/procurement/providers.py`
- `backend/app/procurement/research.py`
- `backend/app/procurement/rules.py`
- `backend/app/procurement/service.py`
- `backend/app/procurement/worker.py`
- `backend/app/procurement/excel_export.py`
- `backend/app/procurement/reference.py`
- `backend/alembic/versions/0003_worker_heartbeat.py`
- `backend/tests/conftest.py`
- `backend/tests/test_pi_api.py`
- `backend/tests/test_pi_engine.py`
- `backend/tests/test_pi_automatic.py`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vitest.config.ts`
- `frontend/src/pages/pi/AutomaticValuation.tsx`
- `frontend/src/pages/pi/AutomaticValuation.test.tsx`
- `frontend/src/pages/pi/PiImport.tsx`
- `frontend/src/pages/pi/AssetDrawer.tsx`
- `frontend/src/pages/pi/types.ts`
- `frontend/src/pages/pi/PiRules.tsx`
- `frontend/src/pages/pi/PiResearch.tsx`
- `frontend/src/pages/pi/PiDashboard.tsx`
- `docker-compose.yml`
- `.env.example`
- `.gitignore`
- `references/.gitkeep`
- `scripts/verify_live_research.py`
- `README.md`

Required documentation: `PRICING_INTELLIGENCE_IMPLEMENTATION_AUDIT.md`, `AUTOMATED_PRICING_WORKFLOW.md`, `MARKET_RESEARCH_PROVIDER_STATUS.md`, `B001_B002_VALIDATION_RESULTS.md`, `PRICING_ENGINE_CALCULATION_EXAMPLES.md`, and this handover. Supporting evidence: JUnit XML, `MARKET_LIVE_RESEARCH_RESULTS.json`, `PRICING_CALCULATION_EXAMPLES.json` and `PRICING_INTELLIGENCE_TEST_EVIDENCE.md`.

The source audit documents actual pre-change function calls and the observed gaps. Provider and business-convention primary references are linked in the provider/calculation documents. Tests using fake HTTP responses or synthetic workbooks are explicitly labeled and never counted as actual live research or original B001 acceptance.


## Running-instance correction — blank Market Unit Price export

27 October 2026: the user's running B002 batch had 2,892 manual-required rows, no research jobs and no connected historical observations. The legacy Calculate/Recalculate UI actions only called the evidence-only `/price` endpoint. The available completed B002 reference had been used in isolated tests but was not connected to the running local stack. This deployment/configuration gap caused a real blank export and was corrected.

- Connected the existing dated completed B002 workbook under the git-ignored `references/` directory and enabled `CLPI_REFERENCE_DIRS` for the local Compose stack. Keys and other environment values were preserved.
- Changed the remaining primary import calculation action to queue `/analyze`; review now displays the same full automatic workflow. Price rows refresh after job completion.
- Disabled the misleading priced-export button when the batch has no supported value. Zero-price automatic exports are labeled review workbooks, with explicit row-price counts.
- Recalculated the user's existing batch from dated evidence and reopened its actual XLSX: **2,891 numeric prices in J**, one unsupported row held, subtotal **INR 13,334,100**. First processor prices are INR 4,300 / 4,300 / 3,300 / 3,300. These are historical/provisional, not current live observations.
- Queued a genuine full live refresh through the separate worker, with the historical prices remaining available during research. The live job's final result is recorded separately when complete.
- Frontend tests: **7 passed**; TypeScript and Vite production build passed. Current local API/database/worker are healthy.
- Tavily is now configured. Eight real connectivity/research requests for four public cases succeeded, but those eight results provided no sufficiently confirmed exact offers. The earlier BLOCKED credential status is superseded; successful HTTP access is not a confirmed price.

The corrected downloaded workbook is `B002_Corrected_Historical_Prices.xlsx`. The original vendor input is intentionally not overwritten. Existing source data was preserved in the export.
