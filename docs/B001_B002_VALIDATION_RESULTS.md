# B001 / B002 validation results

Executed 27 October 2026. Original customer workbooks are kept out of source control and public outputs.

## Continuation validation — 27 October 2026

The user supplied the actual originals at `D:\CIN-20261026-B001_Asset List.xlsx` and `D:\CIN-20261026-B002_Asset List.xlsx`. Copies were placed in the already git-ignored local fixture directory. Original files remain unchanged. Both originals now pass parsing and complete queued export checks.

- **PostgreSQL 18:** full suite ran against a separate temporary instance on loopback, with its own disposable `_test` database: **94 passed, 1 skipped in 77.50s**. Actual migrations were executed. The test harness now refuses an explicit PostgreSQL test URL whose database name does not end in `_test`, to protect operational data.
- **Docker:** actual backend and frontend images built successfully. A separate `clpi-audit` stack used PostgreSQL 16, API, worker and nginx web; existing CLPI/other stacks were not redeployed. DB/API/worker health passed; web HTTP returned 200. In the API container, Alembic reports `0003 (head)` and `alembic check` reports no new operations. Worker diagnostics returned exit 0.
- **Original B001:** 42 lines, 1,324 units, `Net Leased Qty`, Market Unit Price in N. Upload → separate worker → preserved export passed. In the absence of a live key or completed B001 historical reference, its prices remain blank and status is **Research Unavailable**. This is correct insufficient-evidence handling, not a completed monetary valuation or the historical INR 20,260,000 regression.
- **Original B002:** 2,892 rows, 2,698 RAM / 194 CPU. Upload → separate worker → preserved export populated **2,891** column-J historical prices, with one ambiguous SKU held. Supported subtotal **INR 13,334,100**, dated historical/provisional. No serial mapping or unrelated original cell data changed.
- **Still external:** live API keys remain absent; actual four-device live research remains BLOCKED. Only the completed/priced B001 reference is now missing for its exact historical total regression. Browser visual and Excel pivot-refresh acceptance remain unverified as previously stated.

Evidence: `PRICING_INTELLIGENCE_POSTGRESQL_TEST_RESULTS.xml`, `DOCKER_RUNTIME_VALIDATION.json`. User-facing review files: `B001_Needs_Research_Review.xlsx` and `B002_Historical_Provisional_Valuation.xlsx` (historical, not live).

## Initial fixture availability (before user supplied originals)
Found `backend/tests/fixtures/reference/CIN-20261026-B002_Market_Unit_Prices_Researched.xlsx`.
Missing original files: `CIN-20261026-B001_Asset List.xlsx`, `CIN-20261026-B001_Used_Asset_Market_Prices.xlsx`, and original unpriced `CIN-20261026-B002_Asset List.xlsx`. Discovery was limited to project fixtures and explicitly configured reference directories. No contents were invented. The original B001 regression remains SKIPPED with its reason in the JUnit report.

## B002: actual completed historical workbook
Existing regression `tests/test_pi_api.py::test_b002_regression` checks:
- 2,892 rows: 2,698 RAM and 194 processor rows; grade B.
- 52 groups including one unidentified SKU; 51 identified research products.
- Existing column J reused, serial-to-row mapping retained, no duplicate Market Unit Price column.
- Historical reference imports 51 deduplicated observations dated 26 October 2026.
- 2,891 evidence-supported rows priced; ambiguous `XEON SILVER 41112` remains blank rather than being guessed as 4112.
- Supported historical subtotal is **INR 13,334,100**. The original historical total of **INR 13,337,100** includes INR 3,000 for the held row. The test explicitly confirms the full historical total only after an authorized manual SKU correction. This is not an automatic or live valuation claim.
- Actual RAM subtotal INR 12,142,800 and supported CPU subtotal INR 1,191,300.
- Supplementary sheets and original contents remain available.

New `test_configured_history_automatic_reuse_b002` derives an unpriced copy in memory from the completed historical workbook; it is explicitly **not the missing original unpriced workbook**. It then executes upload → one-click analyze → worker → automatic configured-reference reuse → draft quotation → preserved export. It verifies 2,891 actual populated prices, per-row historical price equality except the held row, 2,892 serial mappings, quantity and category counts, no duplicate J column, provisional/historical labeling, INR 13,334,100 supported total and idempotent historical discovery. No discounts or prices are manually entered for that valuation.

## B001: independent synthetic tests only
The original 42-line B001 historical result INR 20,260,000 cannot be reproduced without the original/priced B001 files. It has not been reported as passed.

Existing structural fixture checks mixed laptop/phone/Apple rows, quantity gaps, generation/Apple flags, and A–M → N/O output behavior. New `test_synthetic_b001_42_lines_1324_units` independently creates 42 clearly labeled synthetic rows totaling 1,324 units; imports synthetic dated historical evidence once; runs automatic valuation; checks all 42 populated N prices, O quantity formulas, original layout and a synthetic total of INR 13,240,000. That synthetic amount is **not** B001's historical or current market total.

## Workbook integrity
`test_complex_workbook_original_parts_retained`: real synthetic chart, image, formulas and colliding existing report sheets. All original ZIP members remain; every member outside the explicit mutation allowlist is byte-identical. Original formulas and both customer sheet names/contents remain. New report sheets receive unique names.

`test_ooxml_opaque_parts_preserved`: synthetic opaque cache/extension entries remain byte-identical. This verifies package preservation only. **A real pivot refresh/render test in Microsoft Excel was not executed**; no real complex pivot fixture or Excel-render check was available. Default export warns explicitly; alternate clean quotation export is implemented and tested.

Uploaded source SHA-256 is checked unchanged in the offline integration test. Generated artifacts have independent SHA-256 validation on authenticated download.

## Execution evidence
See `PRICING_INTELLIGENCE_TEST_RESULTS.xml` for the executed backend suite and the handover for frontend/migration/runtime results. Simulated provider responses are never substituted for real live pricing.


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
