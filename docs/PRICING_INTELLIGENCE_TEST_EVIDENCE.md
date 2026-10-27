# Executed validation evidence

Date: 27 October 2026. No production deployment.

## Continuation validation — 27 October 2026

The user supplied the actual originals at `D:\CIN-20261026-B001_Asset List.xlsx` and `D:\CIN-20261026-B002_Asset List.xlsx`. Copies were placed in the already git-ignored local fixture directory. Original files remain unchanged. Both originals now pass parsing and complete queued export checks.

- **PostgreSQL 18:** full suite ran against a separate temporary instance on loopback, with its own disposable `_test` database: **94 passed, 1 skipped in 77.50s**. Actual migrations were executed. The test harness now refuses an explicit PostgreSQL test URL whose database name does not end in `_test`, to protect operational data.
- **Docker:** actual backend and frontend images built successfully. A separate `clpi-audit` stack used PostgreSQL 16, API, worker and nginx web; existing CLPI/other stacks were not redeployed. DB/API/worker health passed; web HTTP returned 200. In the API container, Alembic reports `0003 (head)` and `alembic check` reports no new operations. Worker diagnostics returned exit 0.
- **Original B001:** 42 lines, 1,324 units, `Net Leased Qty`, Market Unit Price in N. Upload → separate worker → preserved export passed. In the absence of a live key or completed B001 historical reference, its prices remain blank and status is **Research Unavailable**. This is correct insufficient-evidence handling, not a completed monetary valuation or the historical INR 20,260,000 regression.
- **Original B002:** 2,892 rows, 2,698 RAM / 194 CPU. Upload → separate worker → preserved export populated **2,891** column-J historical prices, with one ambiguous SKU held. Supported subtotal **INR 13,334,100**, dated historical/provisional. No serial mapping or unrelated original cell data changed.
- **Still external:** live API keys remain absent; actual four-device live research remains BLOCKED. Only the completed/priced B001 reference is now missing for its exact historical total regression. Browser visual and Excel pivot-refresh acceptance remain unverified as previously stated.

Evidence: `PRICING_INTELLIGENCE_POSTGRESQL_TEST_RESULTS.xml`, `DOCKER_RUNTIME_VALIDATION.json`. User-facing review files: `B001_Needs_Research_Review.xlsx` and `B002_Historical_Provisional_Valuation.xlsx` (historical, not live).



| Check | Actual result |
|---|---|
| Baseline backend `python -m pytest tests -q` | 71 passed, 1 skipped (24.84s) |
| Final full backend `python -m pytest tests -q --tb=short --junitxml=../docs/PRICING_INTELLIGENCE_TEST_RESULTS.xml` | 92 passed, 1 skipped (47.44s) |
| Final targeted unit-price/confirmed-offer/provider tests | 3 passed (3.75s), after last extraction guard |
| Frontend `npm test` | 5 passed (1.41s) |
| Frontend `npm run typecheck` | exit 0 |
| Frontend `npm run build` | exit 0; Vite 74 modules, built in 1.42s |
| New/changed engine/queue/provider modules and tests `pyflakes` | exit 0 (verify_live_research unused import corrected before final check) |
| `docker compose config --quiet` | exit 0; configuration only |
| Fresh SQLite `alembic upgrade head` | 0001 → 0002 → 0003 executed successfully |
| SQLite `alembic current` | 0003 (head) |
| SQLite `alembic check` | No new upgrade operations detected |
| PostgreSQL `alembic upgrade head --sql` | Dialect SQL generated through 0003; NOT executed against PostgreSQL |
| Project configured PostgreSQL connection | BLOCKED: configured connection unavailable; no operational data modified |
| Docker engine/container health | BLOCKED: engine pipe not found |
| Actual live verification script | BLOCKED: no Brave/Tavily key; four cases, zero requests |
| Original B001 regression | SKIPPED: original/priced B001 fixtures missing |
| B002 actual completed reference / derived-unpriced automatic workflow | PASSED: 2,892 rows, 2,891 actual exported prices, one ambiguous SKU held; date and serial mapping checked |
| Synthetic B001 | PASSED: 42 rows, 1,324 units; synthetic values explicitly labeled |
| Actual background worker | PASSED in startup/thread/API integration test; no per-job command |
| Complex chart/image/formula and opaque cache/extension package checks | PASSED; Excel pivot refresh/render NOT verified |
| Browser visual acceptance | BLOCKED: security gate denied local-origin access; no bypass attempted |

Dependencies were isolated in a workspace venv because the global Python installation had incomplete pip/pytest dependencies. Automated tests used a workspace TEMP directory because the default sandbox TEMP path caused access errors. These environment corrections did not change production app credentials or the supplied source workbooks. UI test servers were temporary and stopped after browser access was denied.


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
