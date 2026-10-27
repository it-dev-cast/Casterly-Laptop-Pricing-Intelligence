"""Market-evidence connector adapters.

Only two channels are live out of the box: manual entry and bulk file import. The
``http_json_feed`` adapter is a generic client for an *approved* API or permitted
data feed. It is disabled until an administrator supplies an HTTPS endpoint and
confirms that the provider's terms permit this use. It does not scrape web pages,
does not attempt to bypass authentication, rate limits or robots rules, and stores
only URLs that the feed itself provides.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..importing.normalize import normalize_record
from ..models import Connector, MarketListing, User
from ..pricing.config import PricingConfig
from ..services.records import build_record


@dataclass
class AdapterInfo:
    adapter: str
    title: str
    description: str
    live_capable: bool


ADAPTERS = {
    "manual": AdapterInfo("manual", "Manual evidence entry", "Evidence typed in by users. Always available.", False),
    "file_import": AdapterInfo("file_import", "Bulk file import", "CSV / Excel uploads through the import wizard.", False),
    "http_json_feed": AdapterInfo(
        "http_json_feed", "Approved JSON feed",
        "Pulls listings from an approved API or permitted feed that returns JSON. Requires an HTTPS URL, a field "
        "mapping, and explicit confirmation that the provider's terms allow this use. API keys are read from a "
        "server environment variable named in the configuration, never stored in the database.", True),
}

DEFAULT_CONNECTORS = [
    ("Manual entry", "manual", True, "active"),
    ("Bulk file import", "file_import", True, "active"),
    ("Approved market feed (not configured)", "http_json_feed", False, "not_configured"),
]


class ConnectorError(RuntimeError):
    pass


def ensure_defaults(db: Session) -> None:
    existing = {c.adapter for c in db.scalars(select(Connector)).all()}
    for name, adapter, enabled, status in DEFAULT_CONNECTORS:
        if adapter not in existing:
            db.add(Connector(name=name, adapter=adapter, enabled=enabled, status=status, config={}))


def validate_feed_config(cfg: dict) -> list[str]:
    problems = []
    url = (cfg or {}).get("url") or ""
    if not url.startswith("https://"):
        problems.append("Feed URL must be an https:// endpoint")
    if not cfg.get("terms_confirmed"):
        problems.append("Confirm that the provider's terms permit automated retrieval and this use")
    fm = cfg.get("field_map") or {}
    for req in ("brand", "model", "price", "listing_date"):
        if req not in fm:
            problems.append(f"field_map must map '{req}'")
    if not (cfg.get("default_channel") or "channel" in fm):
        problems.append("Set default_channel or map 'channel'")
    return problems


def _dig(obj, path: str | None):
    if not path:
        return obj
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def run_feed(db: Session, conn: Connector, cfg_pricing: PricingConfig, user: User | None,
             transport: httpx.BaseTransport | None = None) -> dict:
    cfg = conn.config or {}
    conn.last_attempt_at = datetime.now(timezone.utc)
    problems = validate_feed_config(cfg)
    if problems or not conn.enabled:
        conn.status = "not_configured" if problems else "disabled"
        raise ConnectorError("; ".join(problems) or "Connector is disabled")
    headers = {"Accept": "application/json", "User-Agent": "CasterlyLaptopPricing/1.0"}
    key_env = cfg.get("api_key_env")
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            conn.status, conn.last_error = "error", f"Environment variable {key_env} is not set"
            conn.failure_count += 1
            raise ConnectorError(conn.last_error)
        headers[cfg.get("api_key_header") or "Authorization"] = (cfg.get("api_key_prefix") or "Bearer ") + key
    try:
        with httpx.Client(timeout=30, transport=transport, follow_redirects=False) as client:
            resp = client.get(cfg["url"], headers=headers)
        if resp.status_code != 200:
            raise ConnectorError(f"Feed returned HTTP {resp.status_code}")
        payload = resp.json()
    except (httpx.HTTPError, ValueError, ConnectorError) as e:
        conn.status, conn.last_error = "error", str(e)[:500]
        conn.failure_count += 1
        audit.record(db, user, "connector.failed", "connector", conn.id, error=conn.last_error)
        raise ConnectorError(conn.last_error) from e
    items = _dig(payload, cfg.get("records_path"))
    if not isinstance(items, list):
        conn.status, conn.last_error = "error", "records_path did not resolve to a list"
        conn.failure_count += 1
        raise ConnectorError(conn.last_error)
    fm = cfg["field_map"]
    created = rejected = duplicates = 0
    errors_sample = []
    observed = datetime.now(timezone.utc)
    for item in items[:5000]:
        if not isinstance(item, dict):
            rejected += 1
            continue
        values = {k: _dig(item, src) for k, src in fm.items()}
        values.setdefault("observed_at", observed.isoformat())
        defaults = {"channel": cfg.get("default_channel"), "tax_basis": cfg.get("default_tax_basis"),
                    "platform": cfg.get("platform"), "currency": cfg.get("default_currency")}
        norm, errs, _ = normalize_record("listing", values, cfg_pricing, {k: v for k, v in defaults.items() if v})
        if errs:
            rejected += 1
            if len(errors_sample) < 5:
                errors_sample.append("; ".join(e["message"] for e in errs))
            continue
        sid = norm.get("source_record_id")
        if sid and db.scalar(select(MarketListing.id).where(MarketListing.connector_id == conn.id,
                                                            MarketListing.source_record_id == sid,
                                                            MarketListing.price == norm.get("price"),
                                                            MarketListing.listing_date == norm.get("listing_date"))):
            duplicates += 1
            continue
        rec = build_record(db, "listing", norm, source_type="connector", source_document=f"Connector '{conn.name}'",
                           user=user, raw_values={k: (str(v) if v is not None else None) for k, v in values.items()})
        rec.connector_id = conn.id
        created += 1
    conn.status = "active"
    conn.last_success_at = datetime.now(timezone.utc)
    conn.last_error = None if not rejected else f"{rejected} record(s) rejected: " + " | ".join(errors_sample)
    conn.last_records = created
    audit.record(db, user, "connector.run", "connector", conn.id, created=created, rejected=rejected,
                 duplicates=duplicates)
    return {"created": created, "rejected": rejected, "duplicates_skipped": duplicates, "errors_sample": errors_sample}
