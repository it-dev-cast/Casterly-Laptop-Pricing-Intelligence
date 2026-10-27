# Pricing Intelligence — User Guide

**Goal:** upload a vendor's used-IT-asset Excel → identify every asset → research Indian market prices
→ calculate safe bulk purchase values → review evidence and exceptions → approve → download the
completed quotation workbook. All prices are **INR per unit, excluding GST**.

The menu section **Pricing Intelligence** holds every screen below. Procurement and administrators can
do everything except change rules and sources (administrators only); sales users can view and export.

## 1. Import the vendor workbook — *Excel bulk import*

1. Drop the `.xlsx` file. Optionally enter the vendor and a **default grade** (used only for rows with
   no grade/condition column, such as B001 lease-return lists).
2. Check the detection: layout (B001 / B002 / generic), sheet, header row, rows excluded (totals,
   blanks) and the column mapping. Change any mapping and press **Apply mapping**.
3. The identification preview shows how each row was read. Identical products are grouped, so 2,892
   RAM/CPU rows become ~52 research groups.

Single assets can be valued without a file in **New market valuation**.

## 2. Research — *Market research results*

* **Start research** queues a background job (one task per product group). Progress, cached and
  failed tasks are shown; jobs can be cancelled and resumed.
* Open a product to see its evidence. Search results arrive as **candidates** (price found in the
  search result) or **leads** (no price shown — open the link). Select candidates, choose whether the
  price includes GST, and **Verify** or **Reject**. Only verified evidence is used.
* **Add verified evidence** records a written vendor quote, buyback quote or wholesale price you hold.
* Administrators can **Import reference valuation**: a completed Casterly workbook (B001/B002) whose
  prices become dated historical evidence (provisional only).

Without a configured search API key, research is unavailable and the screen says so; manual and
historical evidence still work.

## 3. Calculate and review — *Asset pricing review*

* **Recalculate** prices every group with the active rules. Filters: status, category, confidence,
  search; sortable columns; 100 rows per page.
* Click a row for the **price drawer**: normalised specification, every observation (used or excluded
  and why), the calculation steps, confidence points, assumptions, verification issues and price
  history.
* **Correct identification** fixes a model (for example a typo such as `XEON SILVER 41112` → `4112`
  after confirming with the vendor), optionally for all rows with the same original text. **Suggest
  with AI** pre-fills values from Claude when configured; every suggestion must be checked.
* **Override** a price with a mandatory reason (single row or bulk). The calculated price is kept
  alongside the override and every change is logged.
* **Approve** selected rows, or **Approve all auto-priced** (High/Medium confidence, no open
  high-severity issue).

Statuses: *Auto-priced*, *Review*, *Provisional* (historical or comparable evidence only), *Manual
pricing* (no usable evidence — price left blank), *Approved*.

## 4. Exceptions — *Review exceptions*

Every issue states its business impact and the verification action (for example RAM speed
contradicting the part number, unknown Apple Activation Lock/MDM, missing workstation GPU, CPU
generation not matching the model, duplicate serials, unusually large lots). Resolve with a note once
verified.

## 5. Quote and export — *Vendor quotations*, *Valuation reports*

* **Create quotation** from approved lines (or include unapproved priced lines). Creating it again with
  unchanged prices returns the same quotation. Mark it *issued* when sent.
* **Download Excel** returns the vendor's own workbook with **Market Unit Price** filled (B002 column J)
  or added (B001, plus *Estimated Lot Value* = Net Leased Qty × price), and the Valuation Summary,
  Model Pricing Evidence, Review Before Purchase, Rate Benchmarks and Research Sources sheets.

## 6. Learn from outcomes — *Price history*

Record the actual purchase (and later resale) price for a product. Purchases also become verified
transaction evidence. The accuracy report shows MAE, MAPE and bias by category and suggests rule
changes, which an administrator applies by saving a new rule version.

## 7. Rules — *Pricing rules* (administrators)

Per category: conversion factors from each price type to a buy price, grade adjustments, quantity
bands (1–9, 10–49, 50–99, 100–499, 500+), resale realisation, purchase costs, minimum margin, opening
discount, large-lot threshold and detection keywords. Global: GST, freshness windows, rounding, risk
adjustments (one per risk group — never stacked), research settings. Every save is a new version;
older versions can be re-activated. **Nothing ships pre-filled with invented market discounts.**

## 8. Market source library (administrators)

Domains seen in research or added manually, with kind, default price type, **reliability** (weights
evidence) and active flag. Listing a site is not an integration and does not permit scraping it.
