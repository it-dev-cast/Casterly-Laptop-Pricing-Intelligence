"""Hardware knowledge used for deterministic identification.

Everything here is a lookup of published manufacturer naming conventions (part-number speed and
module-type codes, processor family/generation numbering). Nothing here is a price.
Unknown codes return ``None`` so callers can flag them instead of guessing.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- categories

CATEGORY_LABELS: dict[str, str] = {
    "laptop": "Laptop",
    "mobile_workstation": "Mobile workstation",
    "macbook": "Apple MacBook",
    "desktop": "Desktop / workstation",
    "smartphone": "Smartphone",
    "tablet": "Tablet",
    "monitor": "Monitor",
    "docking_station": "Docking station",
    "accessory": "Accessory",
    "server_cpu": "Server processor",
    "server_ram": "Server memory",
    "other": "Other IT asset",
}

# Default keyword rules (extensible through the pricing rules ``categories`` section).
DEFAULT_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "server_cpu": ["xeon", "epyc", "pm-cpu", "processor", "pinless cpu"],
    "server_ram": ["rdimm", "lrdimm", "ecc", "pc4", "pc3", "pc5", "ddr3", "ddr4", "ddr5", "rc-ram", "server ram",
                   "memory", "dimm"],
    "macbook": ["macbook"],
    "mobile_workstation": ["precision 7", "precision 3", "precision 5", "zbook", "thinkpad p", "mobile workstation"],
    "smartphone": ["iphone", "galaxy", "pixel", "smartphone", "mobile phone", "oneplus", "redmi"],
    "tablet": ["ipad", "galaxy tab", "tablet", "surface go"],
    "monitor": ["monitor", "display", "lcd", "led screen", "p24", "e24", "u24"],
    "docking_station": ["dock", "docking", "port replicator", "wd19", "thunderbolt dock"],
    "desktop": ["desktop", "optiplex", "elitedesk", "prodesk", "thinkcentre", "tower", "sff", "mini pc", "workstation"],
    "laptop": ["laptop", "notebook", "latitude", "thinkpad", "elitebook", "probook", "vostro", "inspiron",
               "ideapad", "x1 carbon", "surface laptop", "chromebook"],
    "accessory": ["charger", "adapter", "keyboard", "mouse", "headset", "bag"],
}

# --------------------------------------------------------------------------- server RAM

# Speed codes per manufacturer naming scheme -> MT/s
SAMSUNG_SPEED = {
    "CPB": 2133, "CRC": 2400, "CTD": 2666, "CVF": 2933, "CWE": 3200, "CWF": 3200,  # DDR4
    "YH9": 1333, "CH9": 1333, "YK0": 1600, "CK0": 1600, "CMA": 1866,  # DDR3
}
HYNIX_DDR4_SPEED = {"TF": 2133, "UH": 2400, "VK": 2666, "WM": 2933, "XN": 3200}
HYNIX_DDR3_SPEED = {"H9": 1333, "PB": 1600, "RD": 1866}
MICRON_SPEED = {"2G1": 2133, "2G3": 2400, "2G6": 2666, "2G9": 2933, "3G2": 3200,
                "1G4": 1333, "1G6": 1600, "1G9": 1866, "1G1": 1066}


def _samsung(pn: str) -> dict | None:
    m = re.search(r"\bM(3\d\d)([AB])([0-9A-Z]{3,4})[0-9A-Z]{2,4}-([A-Z0-9]{3})\b", pn)
    if not m:
        return None
    family, gen, _, speed_code = m.groups()
    module = {"393": "RDIMM", "386": "LRDIMM", "378": "UDIMM", "391": "ECC UDIMM", "471": "SODIMM",
              "474": "ECC SODIMM"}.get(family)
    ddr = {"A": "DDR4", "B": "DDR3"}[gen]
    return {"manufacturer": "Samsung", "part_number": m.group(0), "ddr": ddr, "module_type": module,
            "speed_mts": SAMSUNG_SPEED.get(speed_code), "speed_code": speed_code,
            "ecc": module in ("RDIMM", "LRDIMM", "ECC UDIMM", "ECC SODIMM") if module else None}


def _hynix(pn: str) -> dict | None:
    m = re.search(r"\bHM([AT])(A?\d{1,2})G([RLUS])(\d)[0-9A-Z]{2,5}-([A-Z0-9]{2})\b", pn)
    if not m:
        return None
    gen, _, kind, width, speed_code = m.groups()
    ddr = "DDR4" if gen == "A" else "DDR3"
    module = {"R": "RDIMM", "L": "LRDIMM", "U": "UDIMM", "S": "SODIMM"}[kind]
    speed = (HYNIX_DDR4_SPEED if ddr == "DDR4" else HYNIX_DDR3_SPEED).get(speed_code)
    return {"manufacturer": "SK Hynix", "part_number": m.group(0), "ddr": ddr, "module_type": module,
            "speed_mts": speed, "speed_code": speed_code, "ecc": width in ("7", "8") or module in ("RDIMM", "LRDIMM")}


def _micron(pn: str) -> dict | None:
    m = re.search(r"\bMTA?(\d{1,2})([A-Z]{2,5})(\d{1,2})G(72|64)([A-Z]{1,3})-(\d[G]\d)", pn)
    if not m:
        return None
    _, tech, _, width, pkg, speed_code = m.groups()
    ddr = "DDR4" if "AS" in tech else ("DDR3" if tech.startswith(("KS", "JS", "KSZ", "JSZ", "KSF")) else None)
    if ddr is None:
        ddr = "DDR4" if speed_code.startswith(("2", "3")) else "DDR3"
    module = None
    if pkg.endswith("Z") or pkg.endswith("DZ"):
        module = {"P": "RDIMM", "L": "LRDIMM", "A": "UDIMM", "H": "SODIMM"}.get(pkg[0])
    return {"manufacturer": "Micron", "part_number": m.group(0), "ddr": ddr, "module_type": module,
            "speed_mts": MICRON_SPEED.get(speed_code), "speed_code": speed_code, "ecc": width == "72"}


def decode_ram_part(text: str | None) -> dict | None:
    """Decode a DRAM module part number. Returns None when no supported scheme matches."""
    if not text:
        return None
    up = text.upper()
    for fn in (_samsung, _hynix, _micron):
        r = fn(up)
        if r:
            return r
    m = re.search(r"\b(KSM\d{2}[RLE]\w+|LV\d{2}D4[RLU]\w+-\w+)\b", up)
    if m:  # Kingston: type is reliable from the code, speed only from the KSM prefix
        pn = m.group(1)
        kind = re.search(r"D4([RLU])|KSM\d{2}([RLE])", pn)
        k = (kind.group(1) or kind.group(2)) if kind else None
        speed = None
        km = re.match(r"KSM(\d{2})", pn)
        if km:
            speed = {"21": 2133, "24": 2400, "26": 2666, "29": 2933, "32": 3200, "48": 4800, "56": 5600}.get(km.group(1))
        return {"manufacturer": "Kingston", "part_number": pn, "ddr": "DDR5" if speed and speed >= 4800 else "DDR4",
                "module_type": {"R": "RDIMM", "L": "LRDIMM", "U": "UDIMM", "E": "ECC UDIMM"}.get(k or ""),
                "speed_mts": speed, "speed_code": None, "ecc": k in ("R", "L", "E")}
    return None


TRUNCATED_SPEED_HINT = {"13": 1333, "16": 1600, "18": 1866, "21": 2133, "24": 2400, "26": 2666, "29": 2933,
                        "32": 3200, "48": 4800, "52": 5200, "56": 5600}
STANDARD_SPEEDS = {1066, 1333, 1600, 1866, 2133, 2400, 2666, 2933, 3200, 4800, 5200, 5600, 6400}


def parse_ram_spec(text: str | None) -> dict:
    """Parse spec strings such as 'PC4; 32GB; 2666MHz' or truncated 'PC4; 32GB; 26MHZ'."""
    out: dict = {"ddr": None, "capacity_gb": None, "speed_mts": None, "speed_raw": None, "speed_truncated": False,
                 "module_type": None, "ecc": None}
    if not text:
        return out
    up = text.upper()
    m = re.search(r"\bPC([345])L?\b|\bDDR([345])\b", up)
    if m:
        out["ddr"] = f"DDR{m.group(1) or m.group(2)}"
    m = re.search(r"(\d{1,3})\s*GB", up)
    if m:
        out["capacity_gb"] = int(m.group(1))
    m = re.search(r"(\d{2,4})\s*(?:MHZ|MZ|MT/S|MTS)\b", up)
    if m:
        raw = m.group(1)
        out["speed_raw"] = raw
        v = int(raw)
        if v in STANDARD_SPEEDS:
            out["speed_mts"] = v
        elif raw in TRUNCATED_SPEED_HINT:
            out["speed_mts"] = TRUNCATED_SPEED_HINT[raw]
            out["speed_truncated"] = True
        else:
            out["speed_truncated"] = True
    m = re.search(r"\b(LRDIMM|RDIMM|UDIMM|SODIMM)\b", up)
    if m:
        out["module_type"] = m.group(1)
    if "ECC" in up or out["module_type"] in ("RDIMM", "LRDIMM"):
        out["ecc"] = True
    return out


# --------------------------------------------------------------------------- server CPUs

AMD_OPN = {  # AMD ordering part numbers (tray) for EPYC 7002 SKUs present in Casterly lots
    "100-000000054": "7502",
    "100-000000075": "7542",
    "100-000000079": "7272",
}


def _xeon_scalable_gen(num: str) -> tuple[str, str] | None:
    """Xeon Scalable: second digit encodes the generation (1=Skylake, 2=Cascade Lake, 3=Ice Lake, 4=SPR, 5=EMR)."""
    if len(num) != 4:
        return None
    g = num[1]
    return {"1": ("1st Gen Scalable (Skylake-SP)", "LGA3647"), "2": ("2nd Gen Scalable (Cascade Lake)", "LGA3647"),
            "3": ("3rd Gen Scalable (Ice Lake-SP)", "LGA4189"), "4": ("4th Gen Scalable (Sapphire Rapids)", "LGA4677"),
            "5": ("5th Gen Scalable (Emerald Rapids)", "LGA4677")}.get(g)


def parse_server_cpu(text: str | None) -> dict | None:
    if not text:
        return None
    up = re.sub(r"\s+", " ", text.upper())
    out: dict = {"vendor": None, "family": None, "model": None, "generation": None, "socket": None,
                 "sspec": None, "opn": None, "inferred_from": None, "possible_typo": None}
    ss = re.search(r"\bSR[0-9A-Z]{3}\b", up)
    if ss:
        out["sspec"] = ss.group(0)
    m = re.search(r"XEON\s*(GOLD|SILVER|PLATINUM|BRONZE)\s*(\d{4,5})([A-Z]{0,2})\b", up)
    if m:
        tier, num, suffix = m.groups()
        out.update(vendor="Intel", family=f"Xeon {tier.title()}")
        if len(num) == 5:
            out["possible_typo"] = f"Model number '{num}' has 5 digits; Xeon Scalable SKUs have 4"
            cand = re.sub(r"(\d)\1", r"\1", num, count=1)
            out["typo_candidate"] = cand if len(cand) == 4 else None
            return out
        out["model"] = f"Xeon {tier.title()} {num}{suffix}"
        g = _xeon_scalable_gen(num)
        if g:
            out["generation"], out["socket"] = g
        return out
    m = re.search(r"\bE([357])-?\s?(\d{4}[LW]?)\s?V(\d)\b", up)
    if m:
        series, num, v = m.groups()
        out.update(vendor="Intel", family=f"Xeon E{series}", model=f"Xeon E{series}-{num} v{v}")
        out["generation"] = {"2": "Ivy Bridge-EP", "3": "Haswell-EP", "4": "Broadwell-EP"}.get(v, f"v{v}")
        out["socket"] = "LGA2011" if v == "2" else "LGA2011-3"
        return out
    m = re.search(r"\bXEON\s*([XLEW])(\d{4})\b", up)
    if m:
        out.update(vendor="Intel", family="Xeon 5600/5500", model=f"Xeon {m.group(1)}{m.group(2)}",
                   generation="Westmere-EP / Nehalem-EP", socket="LGA1366")
        return out
    m = re.search(r"\bEPYC\s*(\d{4}[A-Z]?)\b", up)
    opn = re.search(r"100-0{4,}\d{2,3}", up)
    if opn:
        out["opn"] = opn.group(0)
    if m or "EPYC" in up or opn:
        out.update(vendor="AMD", family="EPYC")
        num = m.group(1) if m else None
        if not num and out["opn"] and out["opn"] in AMD_OPN:
            num = AMD_OPN[out["opn"]]
            out["inferred_from"] = f"AMD OPN {out['opn']}"
        if num:
            out["model"] = f"EPYC {num}"
            gen_digit = num[3] if len(num) >= 4 else None
            out["generation"] = {"1": "EPYC 7001 (Naples)", "2": "EPYC 7002 (Rome)", "3": "EPYC 7003 (Milan)",
                                 "4": "EPYC 9004 (Genoa)"}.get(gen_digit or "")
            out["socket"] = "SP3" if num.startswith("7") else ("SP5" if num.startswith("9") else None)
        return out
    return None


# --------------------------------------------------------------------------- client devices

KNOWN_BRANDS = ["dell", "hp", "hewlett packard", "lenovo", "apple", "samsung", "asus", "acer", "microsoft",
                "toshiba", "fujitsu", "lg", "xiaomi", "oneplus", "google", "panasonic", "intel", "amd", "kingston",
                "micron", "sk hynix", "hynix", "dataram", "benq", "viewsonic"]

# Expected CPU generations for models frequently seen in corporate lease returns. Used only to flag conflicts.
MODEL_CPU_GENERATIONS: dict[str, set[int]] = {
    "latitude 5430": {12}, "latitude 5440": {13}, "latitude 7440": {13}, "latitude 7430": {12},
    "latitude 7420": {11}, "latitude 5420": {11}, "latitude 7490": {8}, "latitude 5490": {7, 8},
    "latitude 7480": {6, 7}, "latitude 5400": {8}, "latitude 7400": {8}, "latitude 5410": {10}, "latitude 7410": {10},
    "thinkpad p1 gen 4": {11}, "thinkpad p1 gen 5": {12}, "thinkpad p1 gen 3": {10}, "thinkpad x1 carbon gen 9": {11},
    "thinkpad x1 carbon gen 10": {12}, "thinkpad x1 carbon gen 11": {13}, "thinkpad t480": {8}, "thinkpad t490": {8, 10},
    "thinkpad t14 gen 2": {11}, "thinkpad t14 gen 3": {12}, "elitebook 840 g5": {7, 8}, "elitebook 840 g6": {8},
    "elitebook 840 g7": {10}, "elitebook 840 g8": {11}, "elitebook 840 g9": {12},
}

APPLE_M1_PRO_MAX_MODELS = ("macbook pro 14", "macbook pro 16")


def cpu_generation(text: str | None) -> int | None:
    """Intel Core generation from 'i7-1265U', 'i5 8350U', '12th Gen' etc."""
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)\s*gen", t)
    if m:
        return int(m.group(1))
    m = re.search(r"i[3579][\s-]?(\d{4,5})[a-z]{0,2}", t)
    if m:
        n = m.group(1)
        if len(n) == 5:
            return int(n[:2])
        if n[0] == "1" and n[1] in "01234":  # 10th-14th gen mobile: i7-1065G7, i5-1145G7, i7-1265U, i5-1345U
            return 10 + int(n[1])
        return int(n[0])
    return None
