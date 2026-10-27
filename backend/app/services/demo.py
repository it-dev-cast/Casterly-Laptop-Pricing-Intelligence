"""Synthetic demo dataset.

Loaded only by an explicit administrator action. Every record is flagged
``is_synthetic``, carries the source document "SYNTHETIC DEMO DATA", has no source
URL, and uses obviously fictional sellers. The engine never mixes synthetic and
real records, so loading the demo cannot affect valuations of real inventory.
All prices below are invented for demonstration and are not market observations.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import audit
from ..models import (BacktestRun, InventoryItem, Lot, MarketListing, SupplierQuote, Transaction, User,
                      ValuationRun)
from .records import build_record

DOC = "SYNTHETIC DEMO DATA - generated, not market evidence"

CONFIGS = [
    dict(key="d7490", brand="Dell", model="Latitude 7490", cpu="Intel Core i5-8350U", ram_gb=16, storage_gb=256,
         storage_type="SSD", display_size_in=14.0, display_resolution="1920x1080", gpu="Integrated", base=31000),
    dict(key="hp840", brand="HP", model="EliteBook 840 G5", cpu="Intel Core i5-8350U", ram_gb=8, storage_gb=256,
         storage_type="SSD", display_size_in=14.0, display_resolution="1920x1080", gpu="Integrated", base=26500),
    dict(key="t480", brand="Lenovo", model="ThinkPad T480", cpu="Intel Core i5-8250U", ram_gb=8, storage_gb=256,
         storage_type="SSD", display_size_in=14.0, display_resolution="1920x1080", gpu="Integrated", base=24000),
    dict(key="mba", brand="Apple", model="MacBook Air M1 2020", cpu="Apple M1", ram_gb=8, storage_gb=256,
         storage_type="SSD", display_size_in=13.3, display_resolution="2560x1600", gpu="Integrated", base=52000),
    dict(key="d5400", brand="Dell", model="Latitude 5400", cpu="Intel Core i5-8365U", ram_gb=8, storage_gb=256,
         storage_type="SSD", display_size_in=14.0, display_resolution="1920x1080", gpu="Integrated", base=23500),
]
GRADE_FACTOR = {"A": 1.0, "B": 0.9}


def _spec(c: dict, grade: str, rng: random.Random) -> dict:
    s = {k: c[k] for k in ("brand", "model", "cpu", "ram_gb", "storage_gb", "storage_type", "display_size_in",
                           "display_resolution", "gpu")}
    s.update(condition_grade=grade, battery_health_pct=float(rng.randint(80, 92)), charger_included=True,
             warranty_months=3, region=rng.choice(["Delhi NCR", "Mumbai", "Bengaluru", "Hyderabad"]))
    return s


def load(db: Session, user: User | None, now: datetime | None = None) -> dict:
    if db.scalar(select(MarketListing.id).where(MarketListing.is_synthetic.is_(True)).limit(1)):
        return {"loaded": False, "message": "Synthetic demo data is already loaded."}
    now = now or datetime.now(timezone.utc)
    today = now.date()
    rng = random.Random(20260930)
    counts = {"inventory": 0, "listing": 0, "quote": 0, "transaction": 0}

    def add(kind, values):
        build_record(db, kind, values, source_type="demo", source_document=DOC, user=user, is_synthetic=True)
        counts[kind] += 1

    for c in CONFIGS:
        if c["key"] == "mba":
            n_sales, n_list = 2, 3  # deliberately thin evidence
        else:
            n_sales, n_list = 14, 9
        for grade in ("A", "B"):
            base = c["base"] * GRADE_FACTOR[grade]
            for i in range(n_sales):
                age = rng.randint(3, 320)
                drift = 1 + 0.0004 * age  # older sales slightly higher in this synthetic series
                price = round(base * drift * rng.uniform(0.93, 1.07), -1)
                ch = "retail" if i % 4 else "wholesale"
                if ch == "wholesale":
                    price = round(price * 0.86, -1)
                add("transaction", {**_spec(c, grade, rng), "kind": "sale", "transaction_date": today - timedelta(days=age),
                                    "price": price, "quantity": 1, "channel": ch, "currency": "INR",
                                    "tax_basis": "inclusive", "counterparty": f"DEMO Buyer {rng.randint(1, 40)}",
                                    "source_record_id": f"DEMO-INV-{c['key']}-{grade}-{i}"})
            for i in range(n_list):
                age = rng.randint(1, 60)
                price = round(base * rng.uniform(1.04, 1.16), -1)
                seller = f"DEMO Seller {rng.randint(1, 6)}"
                vals = {**_spec(c, grade, rng), "price": price, "currency": "INR",
                        "tax_basis": rng.choice(["inclusive", "inclusive", None]), "channel": "retail",
                        "listing_date": today - timedelta(days=age), "seller": seller,
                        "platform": "DEMO marketplace", "availability": "out_of_stock" if i == 0 else "in_stock",
                        "title": f"{c['brand']} {c['model']} {c['ram_gb']}GB {c['storage_gb']}GB grade {grade}",
                        "source_record_id": f"DEMO-AD-{c['key']}-{grade}-{i}"}
                add("listing", vals)
                if i == 1:  # the same ad observed again: deduplicated at valuation time
                    add("listing", {**vals, "listing_date": today - timedelta(days=max(0, age - 2))})
            for i in range(3):
                add("quote", {**_spec(c, grade, rng), "seller": f"DEMO Supplier {i + 1}",
                              "price": round(base * rng.uniform(0.58, 0.68), -1), "currency": "INR",
                              "tax_basis": "exclusive", "quote_date": today - timedelta(days=rng.randint(2, 20)),
                              "valid_until": today + timedelta(days=10), "quantity_available": rng.randint(5, 40),
                              "source_record_id": f"DEMO-Q-{c['key']}-{grade}-{i}"})
            for i in range(4):
                add("transaction", {**_spec(c, grade, rng), "kind": "purchase",
                                    "transaction_date": today - timedelta(days=rng.randint(10, 150)),
                                    "price": round(base * rng.uniform(0.55, 0.66), -1), "quantity": rng.randint(3, 15),
                                    "currency": "INR", "tax_basis": "exclusive",
                                    "counterparty": f"DEMO Supplier {i + 1}",
                                    "source_record_id": f"DEMO-PO-{c['key']}-{grade}-{i}"})
        # A different RAM configuration of the same model: incomparable without an adjustment rule.
        if c["key"] == "d7490":
            for i in range(4):
                add("transaction", {**_spec(c, "A", rng), "ram_gb": 8, "kind": "sale",
                                    "transaction_date": today - timedelta(days=rng.randint(5, 90)),
                                    "price": round(c["base"] * 0.9 * rng.uniform(0.95, 1.05), -1), "quantity": 1,
                                    "channel": "retail", "currency": "INR", "tax_basis": "inclusive",
                                    "counterparty": f"DEMO Buyer {50 + i}", "source_record_id": f"DEMO-INV-d7490-8gb-{i}"})

    lot = "DEMO-LOT-001"
    by = {c["key"]: c for c in CONFIGS}
    lines = [
        ("d7490", "A", dict(quantity=12, faults=[], expected_yield_pct=95, refurbishment_cost=800, asking_price=21500,
                            asking_tax_basis="exclusive")),
        ("hp840", "B", dict(quantity=8, faults=["Scuffed lid"], fault_category="cosmetic", expected_yield_pct=90,
                            refurbishment_cost=1200, asking_price=17000, asking_tax_basis="exclusive")),
        ("t480", "A", dict(quantity=5, faults=["Display lines"], fault_category="display", expected_yield_pct=70,
                           refurbishment_cost=3500, salvage_value=4000, asking_price=14500, asking_tax_basis="exclusive")),
        ("mba", "A", dict(quantity=3, faults=[], expected_yield_pct=95, refurbishment_cost=500, asking_price=38000,
                          asking_tax_basis="exclusive")),
        ("d7490", "A", dict(quantity=4, ram_gb=8, faults=[], expected_yield_pct=95, refurbishment_cost=800,
                            asking_price=19000, asking_tax_basis="exclusive")),
        ("d5400", "B", dict(quantity=6, faults=["No power"], fault_category="board_power", asking_price=6000,
                            asking_tax_basis="exclusive")),
    ]
    for n, (key, grade, extra) in enumerate(lines, start=1):
        spec = _spec(by[key], grade, rng)
        add("inventory", {**spec, "item_ref": f"DEMO-{n:03d}", "lot_ref": lot, "supplier": "DEMO Supplier 1",
                          "currency": "INR", "intended_channel": "retail", "target_margin_pct": 15, **extra})
    audit.record(db, user, "demo.loaded", None, None, counts=counts)
    return {"loaded": True, "counts": counts}


def remove(db: Session, user: User | None) -> dict:
    """Delete synthetic demo records only. Real records are never touched."""
    synth_runs = select(ValuationRun.id).where(ValuationRun.is_synthetic.is_(True))
    synth_items = select(InventoryItem.id).where(InventoryItem.is_synthetic.is_(True))
    db.execute(update(Transaction).where(Transaction.valuation_run_id.in_(synth_runs)).values(valuation_run_id=None))
    db.execute(update(Transaction).where(Transaction.inventory_item_id.in_(synth_items)).values(inventory_item_id=None))
    counts = {}
    for name, stmt in (
        ("transactions", delete(Transaction).where(Transaction.is_synthetic.is_(True))),
        ("valuations", delete(ValuationRun).where(ValuationRun.is_synthetic.is_(True))),
        ("listings", delete(MarketListing).where(MarketListing.is_synthetic.is_(True))),
        ("quotes", delete(SupplierQuote).where(SupplierQuote.is_synthetic.is_(True))),
        ("inventory", delete(InventoryItem).where(InventoryItem.is_synthetic.is_(True))),
        ("lots", delete(Lot).where(Lot.is_synthetic.is_(True))),
        ("backtests", delete(BacktestRun).where(BacktestRun.is_synthetic.is_(True))),
    ):
        counts[name] = db.execute(stmt).rowcount
    audit.record(db, user, "demo.removed", None, None, counts=counts)
    return {"removed": counts}


def demo_present(db: Session) -> bool:
    return bool(db.scalar(select(InventoryItem.id).where(InventoryItem.is_synthetic.is_(True)).limit(1)) or
                db.scalar(select(MarketListing.id).where(MarketListing.is_synthetic.is_(True)).limit(1)))
