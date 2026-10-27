"""Turning provider search hits into candidate market observations.

Third-party text is untrusted input: it is parsed with regular expressions only, never executed,
and never allowed to change instructions. A hit becomes a *priced* candidate only when an INR price
appears verbatim in the provider-returned title/snippet. Hits that do not match the product's
technical identity are rejected and not stored as evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from .providers import SearchHit

PRICE_RE = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]{2,7}(?:\.[0-9]{1,2})?)",
                      re.I)
USD_RE = re.compile(r"(?:\$|usd)\s*[0-9]", re.I)
NEW_RE = re.compile(r"\b(brand[\s-]new|new sealed|sealed pack|box pack(ed)?)\b", re.I)


@dataclass
class Candidate:
    title: str
    url: str
    domain: str
    snippet: str
    price: Decimal | None
    other_prices: list[str]
    price_type: str
    match_quality: str
    condition: str | None
    reason: str | None  # rejection reason; None = keep


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def prices_in(text: str) -> list[Decimal]:
    out = []
    for m in PRICE_RE.finditer(text):
        try:
            v = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            continue
        if v >= 50:
            out.append(v)
    return out


def _has(text: str, token: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])", text) is not None


RAM_PC_RATING = {2133: "17000", 2400: "19200", 2666: "21300", 2933: "23400", 3200: "25600", 1600: "12800",
                 1866: "14900", 1333: "10600"}


def match_quality(category: str, spec: dict, text: str) -> str | None:
    """'identical', 'comparable' or None (irrelevant)."""
    t = text.lower()
    if category == "server_cpu":
        from .catalog import parse_server_cpu
        parsed = parse_server_cpu(text)
        expected = (spec.get("model") or "").lower()
        if parsed and (parsed.get("model") or "").lower() != expected:
            return None
        model = (spec.get("model") or "").lower()
        num = re.search(r"(\d{4}[a-z]?)", model)
        if not num:
            return None
        n = num.group(1)
        fam_ok = any(_has(t, w) for w in ("gold", "silver", "platinum", "bronze", "epyc", "e5", "xeon"))
        if not _has(t, n) and not _has(t, n.upper()):
            v = re.search(r"v(\d)", model)
            if not (v and re.search(rf"{n[:4]}\s*-?v{v.group(1)}", t)):
                return None
        return "identical" if fam_ok else "comparable"
    if category == "server_ram":
        cap, ddr, speed = spec.get("capacity_gb"), (spec.get("ddr") or "").lower(), spec.get("speed_mts")
        if not cap or not ddr:
            return None
        if not re.search(rf"(?<!\d){cap}\s*gb", t):
            return None
        pc = {"ddr3": "pc3", "ddr4": "pc4", "ddr5": "pc5"}.get(ddr, "")
        if not (_has(t, ddr) or pc in t):
            return None
        speeds = {int(v) for v in re.findall(r"(?<![0-9])(1333|1600|1866|2133|2400|2666|2933|3200|4800|5600|6400)(?:\s*(?:mhz|mt/s))?", t)}
        if speed and speeds and speed not in speeds:
            return None
        module = (spec.get("module_type") or "").lower()
        if module == "rdimm" and "lrdimm" in t or module == "lrdimm" and "rdimm" in t.replace("lrdimm", ""):
            return None
        speed_ok = bool(speed) and (str(speed) in t or RAM_PC_RATING.get(speed, "@@") in t)
        server_ok = any(w in t for w in ("ecc", "rdimm", "lrdimm", "registered", "server", "reg "))
        if spec.get("part_number") and spec["part_number"].lower() in t:
            return "identical"
        return "identical" if speed_ok and server_ok else "comparable" if server_ok else None
    brand = (spec.get("brand") or "").lower()
    model = (spec.get("model") or "").lower()
    if not model:
        return None
    tokens = [x for x in re.split(r"[\s/,-]+", model) if x and x not in ("laptop", "notebook")]
    if brand and not _has(t, brand) and brand not in ("hp",):
        if not all(_has(t, x) for x in tokens):
            return None
    if not all(_has(t, x) for x in tokens):
        return None
    cfg_hits = 0
    cfg_total = 0
    for v in (spec.get("cpu"), spec.get("apple_chip")):
        if v:
            cfg_total += 1
            cfg_hits += 1 if v.lower() in t else 0
    for gb in (spec.get("ram_gb"), spec.get("storage_gb")):
        if gb:
            cfg_total += 1
            cfg_hits += 1 if re.search(rf"(?<!\d){gb}\s*gb", t) else 0
    gpu = spec.get("gpu")
    if gpu:
        cfg_total += 1
        cfg_hits += int(gpu.lower() in t)
    gen = spec.get("cpu_generation")
    generations = {int(x) for x in re.findall(r"(\d{1,2})(?:st|nd|rd|th)?\s*gen", t)}
    if gen and generations and gen not in generations:
        return None
    return "identical" if cfg_total == 0 or cfg_hits == cfg_total else "comparable"


def classify_price_type(text: str, url: str, source_default: str | None) -> str:
    t = text.lower()
    if "auction" in t:
        return "auction_price"
    if re.search(r"\b(sell (your|old)|buyback|buy back|get (instant )?quote|we buy)\b", t):
        return "buyback_quote"
    if re.search(r"\b(wholesale|bulk|lot of \d+|moq)\b", t):
        return "bulk_wholesale"
    if source_default:
        return source_default
    d = domain_of(url)
    if any(x in d for x in ("olx.", "quikr.", "facebook.")):
        return "second_hand_ask"
    if re.search(r"\b(second[\s-]hand|pre[\s-]owned|used)\b", t) and not re.search(r"\brefurb", t):
        return "second_hand_ask"
    return "refurb_retail"


def condition_of(text: str) -> str | None:
    t = text.lower()
    if NEW_RE.search(t):
        return "new"
    if "refurb" in t or "renewed" in t:
        return "refurbished"
    if re.search(r"\b(used|second[\s-]hand|pre[\s-]owned|pulled)\b", t):
        return "used"
    return None


def to_candidate(hit: SearchHit, category: str, spec: dict, source_default: str | None = None) -> Candidate:
    text = f"{hit.title} {hit.snippet}"
    dom = domain_of(hit.url)
    raw = hit.extra.get("raw_content") or ""
    text = text + " " + raw
    mq = match_quality(category, spec, text)
    cond = condition_of(text)
    ptype = classify_price_type(text, hit.url, source_default)
    prices = prices_in(text)
    price = prices[0] if len(set(prices)) == 1 else None
    others = sorted({str(p) for p in prices if p != price})
    reason = None
    if urlparse(hit.url).scheme not in ("https", "http") or not dom:
        reason = "invalid source URL"
    elif mq is None:
        reason = "not the same product (technical identity mismatch)"
    elif re.search(r"\b(?:lot|pack|set) of \d+|\bper (?:lot|gb|pair|kit)\b|/\s*(?:lot|gb|pair|kit)\b", text, re.I) and not re.search(r"\bper (?:unit|piece|device)\b", text, re.I):
        reason = "lot-total or per-capacity price; unit amount not confirmed"
    elif len(set(prices)) > 1:
        reason = "ambiguous multiple prices; no confirmed unit offer"
    elif price is None:
        reason = "USD price only" if USD_RE.search(text) else "no price shown in the provider's result text"
    elif cond == "new":
        reason = "new-condition listing (not used/refurbished)"
    return Candidate(hit.title, hit.url, dom, hit.snippet[:2000], price, others, ptype, mq or "comparable", cond, reason)

def confirmed_offer(hit: SearchHit, category: str, spec: dict) -> tuple[Decimal | None, str | None]:
    """Confirm a single offer in licensed structured/full content. Snippets alone never suffice."""
    offers = []
    def visit(obj, product_context=False):
        if isinstance(obj, list):
            for v in obj:
                visit(v, product_context)
        elif isinstance(obj, dict):
            kind = str(obj.get("@type") or "").lower()
            context = product_context or "product" in kind
            if "offers" in obj:
                visit(obj["offers"], True)
            if (context or kind == "offer") and obj.get("price") is not None:
                currency = str(obj.get("priceCurrency") or obj.get("price_currency") or "").upper()
                availability = str(obj.get("availability") or "").lower()
                if currency == "INR" and not any(v in availability for v in ("outofstock", "discontinued", "soldout")):
                    try:
                        amount = Decimal(str(obj["price"]).replace(",", ""))
                        if amount.is_finite() and amount >= 50:
                            offers.append(amount)
                    except InvalidOperation:
                        pass
            if "@graph" in obj:
                visit(obj["@graph"])
    visit(hit.extra.get("product"), True)
    visit(hit.extra.get("schemas"))
    if len(set(offers)) == 1 and match_quality(category, spec, hit.title + " " + hit.snippet) == "identical":
        return offers[0], "structured_product_offer"
    raw = hit.extra.get("raw_content")
    if isinstance(raw, str) and raw and match_quality(category, spec, hit.title + " " + raw) == "identical":
        amounts = set(prices_in(raw))
        # Reject financing/ranges/multi-product pages instead of choosing the minimum amount.
        if len(amounts) == 1 and re.search(r"\bprice\b", raw, re.I) and not re.search(r"\b(emi|per month|starting from|up to|upto)\b", raw, re.I):
            return next(iter(amounts)), "licensed_full_content_single_price"
    return None, None


def source_timestamp(hit: SearchHit):
    from datetime import datetime, timezone
    value = hit.extra.get("published_date") or hit.extra.get("page_age")
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        return when if when <= datetime.now(timezone.utc) else None
    except ValueError:
        return None
