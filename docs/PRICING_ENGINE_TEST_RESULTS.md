# Pricing Engine — Test Results

Run date: 27 Oct 2026. Python 3.13, FastAPI 0.141, SQLAlchemy 2.0, PostgreSQL 16 and SQLite.

```
cd backend
CLPI_TEST_DATABASE_URL=postgresql+psycopg2://USER@127.0.0.1:5432/clpi_test python -m pytest tests -q
71 passed, 1 skipped          (PostgreSQL, schema from Alembic 0001 + 0002)
python -m pytest tests -q
71 passed, 1 skipped          (SQLite fallback)
```

Skipped: `test_b001_regression`, because `CIN-20261026-B001_Asset List.xlsx` and
`CIN-20261026-B001_Used_Asset_Market_Prices.xlsx` are not in the workspace. Put them in
`backend/tests/fixtures/reference/` (git-ignored) and the test runs: 42 lines, 1,324 units, the 862-unit
Galaxy A54 group, and the ₹2,02,60,000 total under the historical reference configuration.
The B001 *layout* is covered by a synthetic structural fixture (clearly labelled; not the real rows).

Alembic: `upgrade 0001 → 0002`, `downgrade → 0001`, `upgrade` again, and `alembic check`
("No new upgrade operations detected") all pass on PostgreSQL 16.

Frontend: `tsc -b` and `vite build` pass. A browser walkthrough (Playwright, Chromium) covered
login → import B002 → reference pack → calculate → review table → price drawer → research →
exceptions → rules → dashboard → quotation → history/sources/reports/new valuation → 390 px mobile
view, with no application errors (only blocked web-font requests in the sandbox).

## New tests

| File | Tests | Covers |
|---|---|---|
| `tests/test_pi_engine.py` | 21 | Xeon / E5 / EPYC normalisation, sSpec, OPN inference, typo held (not guessed), RAM part-number decoding (Samsung, SK Hynix, Micron, Kingston), speed conflicts and truncated speeds, manufacturer mismatch, laptop CPU-generation conflict, workstation GPU, Apple chip & Activation Lock flags, phone memory parsing, unknown condition; engine: no evidence → manual, unconfigured conversion → manual, full Decimal pipeline (₹11,800 incl. GST → ₹4,850), risk groups do not stack, buy-side priority, historical superseded, historical-only provisional, unverified / stale / FX exclusions, outlier removal, determinism and input hash, margin-constrained maximum |
| `tests/test_pi_api.py` | 9 (1 skipped) | B001-layout import (title rows, totals excluded, blank qty flagged), A54 bulk band + grade via a new rules version (₹8,250 × 862), override with mandatory reason, sales role 403, approval, idempotent quotation, export (columns appended, formulas, other sheets untouched); manual valuation and manual mapping; research job with mocked Brave transport (identity filtering, leads, dedup, candidates unused until verified, cache); retry with back-off, resume, cancel, non-retryable 401; no provider → 409; outcomes → MAE/MAPE/bias; rules/sources permissions and validation; **B002 regression** |

## B002 regression (real workbook `CIN-20261026-B002_Market_Unit_Prices_Researched.xlsx`)

| Check | Result |
|---|---|
| Asset rows / RAM / CPU | 2,892 / 2,698 / 194 |
| Layout, price column | B002, existing column J filled (no column added) |
| Grade | all Grade B |
| Research groups | 52 (51 identified products + 1 unidentified row) |
| RAM speed conflicts detected (part number vs supplied speed) | 235 rows |
| EPYC SKUs inferred from AMD OPN | 7 rows (7542 × 5, 7502 × 2) |
| Possible typo `XEON SILVER 41112` | held for manual pricing (not guessed) |
| Serial-to-row mapping in export | preserved for every row |
| Prices vs historical (historical reference configuration) | identical for 2,891 rows; row 49 (NA-744) blank |
| RAM total | ₹1,21,42,800 (historical ₹1,21,42,800) |
| CPU total | ₹11,91,300 + ₹3,000 held row = historical ₹11,94,300 |
| After a user corrects 41112 → 4112 | batch total ₹1,33,37,100 = historical total |
| Excel formulas (recalculated with LibreOffice) | category SUMIFs = asset-sheet SUM; difference 0 |
| Import time (2,892 rows) | ≈ 0.8 s |

These are dated historical estimates (26 Oct 2026). The test reproduces them only under the
historical reference configuration; live prices are not expected to equal them.
