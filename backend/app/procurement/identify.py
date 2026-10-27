"""Deterministic hardware identification and normalisation.

Input: one mapped source row (canonical field -> original cell value).
Output: category, normalised specification, a product identity key used to group identical
assets, an identification confidence, and the exceptions that need human verification.

Rules:
* Nothing is invented. A field that cannot be read stays ``None`` and is flagged where it matters.
* When the supplied spec text and a manufacturer part number disagree, the part number wins for
  the normalised value, the original text is kept, and a conflict exception is raised.
* Ambiguous rows are marked ``low`` confidence; an optional AI pass may *suggest* values, which a
  user must accept (see ``ai_suggest``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .. import specs
from . import catalog

# --------------------------------------------------------------------------- exceptions

EXCEPTIONS: dict[str, tuple[str, str, str]] = {
    # code: (severity, business impact, recommended verification action)
    "missing_model": ("high", "The asset cannot be identified, so no market price can be researched.",
                      "Ask the vendor for the exact model / part number or inspect the asset label."),
    "missing_quantity": ("high", "Lot value cannot be calculated for this line.",
                         "Confirm the unit count with the vendor before quoting."),
    "unknown_condition": ("medium", "Condition drives the procurement discount; the price assumes no grade adjustment.",
                          "Obtain a grading report or inspect a sample."),
    "cpu_generation_conflict": ("high", "The stated CPU generation does not exist for this model; the configuration may be wrong.",
                                "Verify the CPU from BIOS / system information before pricing."),
    "exact_cpu_unknown": ("low", "Only the CPU family/generation is known; comparable listings may differ in value.",
                          "Record the exact processor SKU (for example i7-1265U)."),
    "workstation_gpu_missing": ("medium", "Workstation value depends heavily on the discrete GPU.",
                                "Confirm the GPU model (for example RTX A2000) and VRAM."),
    "charger_missing": ("medium", "Missing chargers reduce resale value and add replacement cost.",
                        "Confirm charger availability; apply the configured missing-accessory adjustment."),
    "apple_chip_unknown": ("high", "M1 Pro and M1 Max machines differ materially in value.",
                           "Check 'About This Mac' or the serial number to confirm the chip and GPU core count."),
    "apple_lock_unknown": ("high", "Activation Lock / MDM-enrolled Apple devices cannot be resold.",
                           "Obtain written confirmation that Activation Lock and MDM are removed, or test a sample."),
    "ram_speed_conflict": ("medium", "Supplied speed disagrees with the manufacturer part number; price uses the part-number speed.",
                           "Read the module label or SPD data to confirm the speed."),
    "ram_speed_truncated": ("low", "Speed was abbreviated in the source (for example '26MHz'); interpreted from the abbreviation.",
                            "Confirm the speed from the part number or module label."),
    "ram_type_unknown": ("medium", "ECC / RDIMM / LRDIMM status is not confirmed; module types are not interchangeable.",
                         "Confirm the module type from the label (RDIMM, LRDIMM, UDIMM) and ECC support."),
    "ram_part_unrecognised": ("low", "Part number could not be decoded; identification relies on the spec text only.",
                              "Check the manufacturer's part-number decoder or the module label."),
    "manufacturer_mismatch": ("medium", "The Make column contradicts the part number or model.",
                              "Confirm the manufacturer from the physical label."),
    "cpu_sku_missing": ("high", "Processor SKU is missing; server CPU prices vary by SKU.",
                        "Read the SKU from the heat-spreader marking (model and sSpec)."),
    "cpu_sku_inferred": ("medium", "Processor SKU was inferred from the AMD ordering part number in the serial field.",
                         "Confirm the model printed on the heat-spreader."),
    "possible_typo": ("medium", "The model number looks like a typing error; priced only if confirmed.",
                      "Confirm the exact model with the vendor."),
    "discontinued_component": ("low", "Legacy platform with limited resale demand.",
                               "Price as low-demand stock; confirm there is a buyer before purchase."),
    "duplicate_serial": ("medium", "The same serial number appears more than once; the lot may be double-counted.",
                         "Ask the vendor to confirm whether the duplicate rows are separate units."),
    "large_lot": ("medium", "Unusually large quantity for a single line; bulk discount and resale absorption matter.",
                  "Confirm the quantity and consider staged purchase."),
    "extreme_price_variation": ("medium", "Market observations disagree widely; the benchmark is uncertain.",
                                "Review the evidence and remove irrelevant observations."),
    "no_market_evidence": ("high", "No verified market evidence; the line needs manual pricing or is provisional.",
                           "Add a verified quotation or listing, or run research with a configured provider."),
    "stale_evidence": ("medium", "Only historical / stale evidence is available; the price is provisional.",
                       "Refresh research before issuing the quotation."),
    "conversion_not_configured": ("high", "No conversion factor is configured from the available price type to a buy price.",
                                  "An administrator must configure the conversion factor in Pricing Rules."),
    "recommended_exceeds_margin_cap": ("high", "The market-derived price leaves less than the required minimum margin.",
                                       "Negotiate at or below the maximum permitted purchase price."),
    "ai_identification_used": ("low", "Identification was suggested by AI and accepted by a user.", "Spot-check the asset."),
}


@dataclass
class Flag:
    code: str
    message: str

    def as_dict(self) -> dict:
        sev, impact, action = EXCEPTIONS[self.code]
        return {"code": self.code, "severity": sev, "message": self.message, "impact": impact, "action": action}


@dataclass
class Identification:
    category: str
    label: str
    product_key: str | None
    spec: dict
    confidence: str  # high | medium | low
    flags: list[Flag] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)  # inputs to the pricing engine's risk adjustments
    grade: str | None = None

    def as_dict(self) -> dict:
        return {"category": self.category, "label": self.label, "product_key": self.product_key, "spec": self.spec,
                "confidence": self.confidence, "flags": [f.as_dict() for f in self.flags],
                "risk_flags": self.risk_flags, "grade": self.grade}


def _t(v: Any) -> str | None:
    return specs.clean_text(v)


def _joined(row: dict, *keys: str) -> str:
    return " ".join(str(row[k]) for k in keys if row.get(k) not in (None, ""))


GRADE_MAP = {"untested": "Untested", "not tested": "Untested", "a+": "A+", "a": "A", "b": "B", "c": "C", "d": "D", "excellent": "A", "very good": "A", "good": "B",
             "fair": "C", "poor": "D", "new": "New", "open box": "A+",
             "faulty": "D", "not working": "D", "scrap": "D", "as is": "D"}


def parse_grade(raw: Any) -> str | None:
    s = _t(raw)
    if s is None:
        return None
    k = s.lower().replace("grade", "").strip()
    return GRADE_MAP.get(k)  # working/refurbished alone do not establish a cosmetic grade


# --------------------------------------------------------------------------- category detection

def detect_category(row: dict, keyword_rules: dict[str, list[str]] | None = None) -> str:
    rules = keyword_rules or catalog.DEFAULT_CATEGORY_KEYWORDS
    hint = (_t(row.get("category_hint")) or "").lower()
    if hint in ("pm-cpu", "cpu", "processor") or "cpu" in hint.split("-"):
        return "server_cpu"
    if hint in ("rc-ram", "ram", "memory") or "ram" in hint.split("-"):
        return "server_ram"
    ptype = (_t(row.get("product_type")) or "").lower()
    direct = {"laptop": "laptop", "notebook": "laptop", "desktop": "desktop", "mobile": "smartphone",
              "smartphone": "smartphone", "phone": "smartphone", "tablet": "tablet", "monitor": "monitor",
              "workstation": "desktop", "mobile workstation": "mobile_workstation", "docking station": "docking_station",
              "dock": "docking_station", "accessories": "accessory", "accessory": "accessory"}
    text = _joined(row, "asset_type", "make", "model", "description", "cpu", "product_type").lower()
    if "macbook" in text:
        return "macbook"
    if ptype in direct:
        cat = direct[ptype]
        if cat == "laptop" and any(k in text for k in rules.get("mobile_workstation", [])):
            return "mobile_workstation"
        return cat
    for cat in ("server_cpu", "server_ram", "macbook", "mobile_workstation", "tablet", "smartphone", "docking_station",
                "monitor", "desktop", "laptop", "accessory"):
        for kw in rules.get(cat, []):
            if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text):
                return cat
    for cat, kws in rules.items():  # administrator-added categories
        if cat not in catalog.CATEGORY_LABELS and any(kw in text for kw in kws):
            return cat
    return "other"


# --------------------------------------------------------------------------- identification

def identify(row: dict, keyword_rules: dict[str, list[str]] | None = None,
             default_grade: str | None = None) -> Identification:
    category = detect_category(row, keyword_rules)
    grade = parse_grade(row.get("grade") or row.get("condition"))
    grade_source = "source"
    if grade is None and default_grade:
        grade, grade_source = parse_grade(default_grade), "batch default"
    if category == "server_cpu":
        ident = _server_cpu(row)
    elif category == "server_ram":
        ident = _server_ram(row)
    else:
        ident = _client_device(row, category)
    condition = _joined(row, "condition", "notes").lower()
    if re.search(r"\b(untested|not tested|functionality unknown)\b", condition):
        ident.risk_flags.append("untested")
        if grade is None:
            grade = "Untested"
    if row.get("battery") is not None:
        m = re.search(r"(\d{1,3})", str(row["battery"]))
        if m and int(m.group(1)) < 70:
            ident.risk_flags.append("battery_low")
    if ident.product_key:
        extra = sorted(set(ident.risk_flags) - {"legacy_platform", "condition_unknown"})
        if extra:
            ident.product_key += "|risk:" + ",".join(extra)
    ident.grade = grade
    ident.spec["grade_source"] = grade_source if grade else None
    if grade is None:
        ident.flags.append(Flag("unknown_condition", "No grade or condition supplied"))
        ident.risk_flags.append("condition_unknown")
    return ident


def _brand(row: dict, text: str) -> str | None:
    b = specs.brand_key(row.get("make"))
    if b:
        return b
    low = text.lower()
    for kb in catalog.KNOWN_BRANDS:
        if re.search(r"\b" + re.escape(kb) + r"\b", low):
            return specs.brand_key(kb)
    if re.search(r"\b(iphone|ipad|macbook|imac)\b", low):
        return "apple"
    if re.search(r"\b(latitude|precision|optiplex|vostro|inspiron)\b", low):
        return "dell"
    if re.search(r"\b(thinkpad|thinkcentre|ideapad|thinkbook)\b", low):
        return "lenovo"
    if re.search(r"\b(elitebook|probook|zbook|elitedesk|prodesk)\b", low):
        return "hp"
    if re.search(r"\bgalaxy\b", low):
        return "samsung"
    return None


def _server_cpu(row: dict) -> Identification:
    flags: list[Flag] = []
    text = _joined(row, "model", "cpu", "description", "asset_type")
    serial = _t(row.get("serial")) or ""
    parsed = catalog.parse_server_cpu(text) or catalog.parse_server_cpu(text + " " + serial)
    make = specs.brand_key(row.get("make"))
    confidence = "high"
    if parsed and parsed.get("opn") is None and "EPYC" in text.upper() and not parsed.get("model"):
        parsed = catalog.parse_server_cpu(text + " " + serial)
    if not parsed or not parsed.get("model"):
        if parsed and parsed.get("possible_typo"):
            flags.append(Flag("possible_typo", parsed["possible_typo"] +
                              (f"; may be '{parsed['typo_candidate']}'" if parsed.get("typo_candidate") else "")))
            spec = {"vendor": parsed["vendor"], "family": parsed["family"], "model": None, "source_text": text,
                    "typo_candidate": parsed.get("typo_candidate")}
            return Identification("server_cpu", f"{parsed['family']} (unconfirmed model)", None, spec, "low", flags)
        flags.append(Flag("cpu_sku_missing", f"Could not identify a processor SKU in '{text}'"))
        return Identification("server_cpu", text or "Unidentified processor", None, {"source_text": text}, "low", flags)
    if parsed.get("inferred_from"):
        flags.append(Flag("cpu_sku_inferred", f"{parsed['model']} inferred from {parsed['inferred_from']}"))
        confidence = "medium"
    vendor_key = parsed["vendor"].lower()
    if make and make != vendor_key:
        flags.append(Flag("manufacturer_mismatch", f"Make '{row.get('make')}' but the processor is {parsed['vendor']}"))
        confidence = "medium" if confidence == "high" else confidence
    if parsed.get("family") in ("Xeon 5600/5500",):
        flags.append(Flag("discontinued_component", f"{parsed['model']} ({parsed['generation']}) is a legacy platform"))
    spec = {k: parsed.get(k) for k in ("vendor", "family", "model", "generation", "socket", "sspec", "opn")}
    spec["source_text"] = text
    label = f"{parsed['vendor']} {parsed['model']}"
    key = "server_cpu|" + parsed["model"].lower().replace(" ", "-")
    return Identification("server_cpu", label, key, spec, confidence, flags,
                          risk_flags=["legacy_platform"] if any(f.code == "discontinued_component" for f in flags) else [])


def _server_ram(row: dict) -> Identification:
    flags: list[Flag] = []
    model_text = _t(row.get("model")) or ""
    spec_text = _joined(row, "cpu", "description", "ram", "asset_type")
    sp = catalog.parse_ram_spec(spec_text + " " + model_text)
    part = catalog.decode_ram_part(model_text) or catalog.decode_ram_part(spec_text)
    confidence = "high"
    ddr, cap, speed, mtype, ecc = sp["ddr"], sp["capacity_gb"], sp["speed_mts"], sp["module_type"], sp["ecc"]
    make = specs.brand_key(row.get("make"))
    if part:
        if part["ddr"] and ddr and part["ddr"] != ddr:
            flags.append(Flag("ram_speed_conflict", f"Spec says {ddr} but part number {part['part_number']} is {part['ddr']}"))
        ddr = part["ddr"] or ddr
        if part["speed_mts"]:
            if speed and speed != part["speed_mts"]:
                flags.append(Flag("ram_speed_conflict",
                                  f"Source speed '{sp['speed_raw']}' ({speed} MT/s) vs part-number code "
                                  f"{part['speed_code']} = {part['speed_mts']} MT/s"))
                confidence = "medium"
            elif sp["speed_truncated"]:
                flags.append(Flag("ram_speed_truncated",
                                  f"Speed '{sp['speed_raw']}' read as {speed} MT/s; confirmed by part number"))
            speed = part["speed_mts"]
        elif sp["speed_truncated"]:
            flags.append(Flag("ram_speed_truncated", f"Speed '{sp['speed_raw']}' interpreted as {speed} MT/s"))
            confidence = "medium"
        mtype = part["module_type"] or mtype
        ecc = part["ecc"] if part["ecc"] is not None else ecc
        pmk = specs.brand_key(part["manufacturer"])
        if make and pmk and make.replace("sk ", "") != pmk.replace("sk ", ""):
            flags.append(Flag("manufacturer_mismatch",
                              f"Make '{row.get('make')}' but part number {part['part_number']} is {part['manufacturer']}"))
    else:
        flags.append(Flag("ram_part_unrecognised", f"Part number '{model_text}' not decoded"))
        confidence = "medium"
        if sp["speed_truncated"]:
            flags.append(Flag("ram_speed_truncated", f"Speed '{sp['speed_raw']}' interpreted as {speed} MT/s"))
    if mtype is None or ecc is None:
        flags.append(Flag("ram_type_unknown", "Module type / ECC not stated and not decodable"))
        confidence = "medium" if confidence == "high" else confidence
    if ddr is None or cap is None or speed is None:
        missing = [n for n, v in (("DDR generation", ddr), ("capacity", cap), ("speed", speed)) if v is None]
        flags.append(Flag("missing_model", "Cannot identify module: missing " + ", ".join(missing)))
        return Identification("server_ram", f"{model_text or spec_text} (incomplete)", None,
                              {"ddr": ddr, "capacity_gb": cap, "speed_mts": speed, "module_type": mtype, "ecc": ecc,
                               "part_number": part["part_number"] if part else model_text or None,
                               "source_spec": spec_text}, "low", flags)
    if ddr == "DDR3":
        flags.append(Flag("discontinued_component", f"{ddr} memory has limited resale demand"))
    spec = {"ddr": ddr, "capacity_gb": cap, "speed_mts": speed, "module_type": mtype, "ecc": ecc,
            "manufacturer": part["manufacturer"] if part else (row.get("make") or None),
            "part_number": part["part_number"] if part else (model_text or None), "source_spec": spec_text}
    type_label = mtype or ("ECC" if ecc else "type unconfirmed")
    label = f"{ddr} {cap}GB {speed} {type_label}"
    # Market identity: generation + capacity + speed + module type. Manufacturer variants share one research.
    key = f"server_ram|{ddr}|{cap}gb|{speed}|{(mtype or ('ecc' if ecc else 'unknown')).lower()}"
    return Identification("server_ram", label, key, spec, confidence, flags,
                          risk_flags=["legacy_platform"] if ddr == "DDR3" else [])


_PHONE_MEM = re.compile(r"(\d{1,2})\s*gb\s*[/+|,]\s*(\d{2,4})\s*(gb|tb)", re.I)


def _client_device(row: dict, category: str) -> Identification:
    flags: list[Flag] = []
    risk: list[str] = []
    model_raw = _t(row.get("model"))
    desc = _t(row.get("description")) or ""
    text = _joined(row, "make", "model", "description", "cpu", "generation", "ram", "storage", "notes")
    brand = _brand(row, text)
    if not model_raw and desc:
        model_raw = desc
    if not model_raw:
        flags.append(Flag("missing_model", "No model or description supplied"))
        return Identification(category, "Unidentified asset", None, {"source_text": text}, "low", flags)
    model = specs.model_key(brand, model_raw) or model_raw.lower()
    model = re.sub(r"\s+", " ", model).strip()
    cpu_text = _joined(row, "cpu", "generation")
    cpu_k = specs.cpu_key(row.get("cpu")) if row.get("cpu") else None
    gen = catalog.cpu_generation(cpu_text) or catalog.cpu_generation(desc)
    exact_cpu = None
    m = re.search(r"\b(i[3579])[\s-]?(\d{4,5}[a-z]{0,2})\b", (cpu_text + " " + desc).lower())
    if m:
        exact_cpu = f"{m.group(1)}-{m.group(2)}"
    apple_chip = None
    am = re.search(r"\bm([1-4])\s*(pro|max|ultra)?\b", (model_raw + " " + desc + " " + cpu_text).lower())
    if brand == "apple" and am:
        apple_chip = f"M{am.group(1)}" + (f" {am.group(2).title()}" if am.group(2) else "")
    ram = specs.parse_capacity_gb(row.get("ram"), field="ram").value if row.get("ram") not in (None, "") else None
    storage = specs.parse_capacity_gb(row.get("storage"), field="storage").value if row.get("storage") not in (None, "") else None
    pm = _PHONE_MEM.search(model_raw + " " + desc)
    if pm and category in ("smartphone", "tablet"):
        ram = ram or int(pm.group(1))
        storage = storage or int(pm.group(2)) * (1024 if pm.group(3).lower() == "tb" else 1)
    elif category in ("smartphone", "tablet") and storage is None:
        sm = re.search(r"(\d{2,4})\s*(gb|tb)\b", (model_raw + " " + desc).lower())
        if sm:
            storage = int(sm.group(1)) * (1024 if sm.group(2) == "tb" else 1)
    storage_type = specs.storage_type_from_text(row.get("storage"))
    gpu = _t(row.get("gpu"))
    charger = _t(row.get("charger"))
    confidence = "high"

    # Model / CPU-generation consistency
    for known, gens in catalog.MODEL_CPU_GENERATIONS.items():
        if re.search(r"\b" + re.escape(known) + r"\b", f"{brand or ''} {model}".lower()) and gen and gen not in gens:
            flags.append(Flag("cpu_generation_conflict",
                              f"{known.title()} ships with {'/'.join(f'{g}th' for g in sorted(gens))} Gen CPUs; "
                              f"source says {gen}th Gen"))
            confidence = "low"
            break
    if category in ("laptop", "mobile_workstation", "desktop") and not exact_cpu and brand != "apple":
        if gen or cpu_text:
            flags.append(Flag("exact_cpu_unknown", f"CPU given as '{cpu_text or desc}'"))
            confidence = "medium" if confidence == "high" else confidence
    if category == "mobile_workstation" and not gpu:
        flags.append(Flag("workstation_gpu_missing", "No GPU stated for a mobile workstation"))
        confidence = "medium" if confidence == "high" else confidence
    if category in ("laptop", "mobile_workstation", "macbook") and charger and charger.lower() in ("no", "n", "without",
                                                                                                    "missing", "0"):
        flags.append(Flag("charger_missing", "Charger not included"))
        risk.append("charger_missing")
    if brand == "apple":
        if category == "macbook" and any(k in model for k in catalog.APPLE_M1_PRO_MAX_MODELS) and apple_chip in (None, "M1"):
            flags.append(Flag("apple_chip_unknown", f"'{model_raw}' does not say M1 Pro or M1 Max"))
            confidence = "low"
        notes = (_t(row.get("notes")) or "").lower()
        if not re.search(r"(activation lock|icloud|mdm)\s*(removed|off|clear|free|unlocked)", notes):
            flags.append(Flag("apple_lock_unknown", "Activation Lock / MDM status not stated"))
            risk.append("activation_lock_unknown")

    spec = {"brand": brand, "model": model, "model_text": model_raw, "cpu": exact_cpu or cpu_k, "cpu_generation": gen,
            "apple_chip": apple_chip, "ram_gb": ram, "storage_gb": storage, "storage_type": storage_type, "gpu": gpu,
            "charger": charger, "display": _t(row.get("display")), "source_text": text}
    family_match = re.search(r"\b(i[3579]|ryzen\s*[3579])\b", (cpu_text + " " + desc).lower())
    family = cpu_k or (family_match.group(1) if family_match else None)
    spec["cpu"] = exact_cpu or family
    cpu_part = exact_cpu or apple_chip or ((family or "cpu?") + (f"-gen{gen}" if gen else ""))
    parts = [category, brand or "unknown", model, cpu_part, f"{ram}gb" if ram else "ram?", f"{storage}gb" if storage else "st?"]
    if gpu or category == "mobile_workstation":
        parts.append(specs.gpu_key(gpu) or "gpu?")
    key = "|".join(p.replace("|", "/") for p in parts)
    brand_disp = (brand or "").upper() if brand in ("hp", "lg") else (brand or "").title()
    shown = model_raw if not brand or model_raw.lower().startswith(brand) else f"{brand_disp} {model_raw}"
    label_bits = [shown]
    low_shown = shown.lower()
    cpu_disp = exact_cpu or apple_chip or (f"{gen}th Gen" if gen else None)
    if cpu_disp and cpu_disp.lower() not in low_shown:
        label_bits.append(cpu_disp)
    if ram and f"{ram}gb" not in low_shown.replace(" ", ""):
        label_bits.append(f"{ram}GB")
    if storage and f"{storage}gb" not in low_shown.replace(" ", ""):
        label_bits.append(f"{storage}GB" if storage < 1024 else f"{storage // 1024}TB")
    label = " · ".join(b for b in label_bits if b)
    if brand is None:
        confidence = "low"
    return Identification(category, label, key, spec, confidence, flags, risk)


# --------------------------------------------------------------------------- AI assistance

def ai_suggest(text: str) -> dict:
    """Ask Claude to suggest identification fields for an ambiguous description.

    Returns suggestions only; values whose supporting quote is not found verbatim are downgraded
    by ``claude.extract``. The caller stores them for user review; they never change a price directly.
    """
    from ..ai import claude
    suggestions, model = claude.extract(text)
    return {"suggestions": suggestions, "model": model}
