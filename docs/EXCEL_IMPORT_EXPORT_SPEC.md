# Excel Import / Export Specification

## Import (`backend/app/procurement/excel_import.py`)

Accepted: `.xlsx` (macro-enabled and legacy `.xls` rejected; zip-bomb and size checks from the
existing upload guard). The stored upload is never modified.

### Detection

1. Every sheet's first 30 rows are scored by how many cells match known header synonyms. The best
   row of each sheet is its header candidate.
2. Layout signatures:
   * **B002** (server components): `Serial Number, Category, Request Label, OFFER, Type, Make, Model, CPU, Grade, Market Unit Price`.
   * **B001** (mixed assets): `Sales Order, Global/Local, Item Code, Open Description, Location, Net Leased Qty, Product Type, Model, Processor Type, Generation, RAM, Storage (HDD/SSD), Notes`.
   * anything else: **generic** (synonym mapping; user can remap).
3. The highest-scoring sheet wins (a recognised layout, then a sheet named like "Asset List", then
   row count). Supplementary sheets are ignored. If nothing scores high enough the upload is refused
   with a request to map columns manually.

### Rows

* Blank rows, repeated header rows, and total/summary rows (`Total`, `Grand Total`, `Subtotal`,
  `Summary`…) are skipped and listed with the reason.
* Rows with no identifying column (model, description, serial, item code, make) are skipped.
* Quantity column: first match of the configurable `quantity_columns` list (default
  `Net Leased Qty, Qty, Quantity, Units, Nos`). Without one, each row is one unit (B002).
  Unreadable or blank quantities raise `missing_quantity` and the line is not valued.
* Duplicate serial numbers are kept and flagged (`duplicate_serial`).
* Every asset keeps `sheet`, `row_number` and the original `raw` cells; corrections are stored
  separately.

### Manual mapping

`POST /api/pi/batches/{id}/mapping` with `{mapping: {field: header}, sheet, header_row, default_grade}`
re-reads the stored file. Fields: `serial, item_code, sales_order, global_local, request_label, offer,
category_hint, asset_type, product_type, make, model, cpu, generation, ram, storage, gpu, display, grade,
condition, charger, battery, notes, description, location, quantity, existing_price`.

## Export (`backend/app/procurement/excel_export.py`)

The original workbook is reopened with formatting and formulas intact.

* **Market Unit Price**: filled in place when the column exists (B002 column J); otherwise appended
  after the last header with the header style copied (B001 and generic).
* **Estimated Lot Value**: appended when a quantity column exists, as the formula
  `=IF(ISNUMBER(price), N(qty) × price, "")`.
* Lines needing manual pricing are left **blank** (never 0).
* Supplementary sheets (an existing sheet of the same name is never overwritten; ours become
  "… (CLPI)"):

| Sheet | Content |
|---|---|
| Valuation Summary | Batch, vendor, rule version, basis; per-category lines/units/value as `SUMIF` formulas over Model Pricing Evidence; asset-sheet total as `SUM` / `SUMPRODUCT` over the price column; reconciliation difference (must be 0); row counts imported / priced / manual |
| Model Pricing Evidence | One row per product group: benchmark, Market Unit Price, lot value formula, confidence, status, evidence used, source URLs |
| Review Before Purchase | Every exception with severity, row, serial, impact and verification action |
| Rate Benchmarks | Per group: benchmark, grade/quantity/risk %, recommended, opening, maximum, resale, margin, assumptions |
| Research Sources | Every observation for the batch's products, whether it was used and why not |
| Vendor Quotation | (quotation export only) lines with `=Qty × Unit` and a `SUM` total |

* Text from vendors or the web is neutralised against formula injection (leading `= + - @`).
* **Integrity check**: the saved file is reopened; the count of numeric prices in the price column must
  equal the number of priced assets and all supplementary sheets must exist, or the export fails
  (HTTP 500) instead of returning a wrong file. The response header `X-Export-Prices-Written` carries
  the count.

### Known limitation

openpyxl does not round-trip charts, images, pivot tables or external links of the source workbook.
Cell values, formulas, styles, merged cells, column widths and other sheets are preserved.
