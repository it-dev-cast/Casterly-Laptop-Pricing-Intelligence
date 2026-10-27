"""Generate every logo variant the app uses from the single source file.

Run from the repository root:  python scripts/make_brand_assets.py
Source: brand/casterly-logo-source.png (official Casterly logo, transparent background).
Outputs:
  frontend/public/brand/casterly-logo.png   full logo (mark + wordmark), trimmed
  frontend/public/brand/casterly-mark.png   the C mark only, trimmed
  frontend/public/favicon-32.png, favicon-64.png, apple-touch-icon.png
  backend/app/assets/casterly-logo.png      for Excel exports
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "brand" / "casterly-logo-source.png"
PUB = ROOT / "frontend" / "public"


def trimmed(im: Image.Image, pad: int = 0) -> Image.Image:
    box = im.getchannel("A").getbbox()
    im = im.crop(box)
    if pad:
        out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
        out.paste(im, (pad, pad))
        im = out
    return im


def square(im: Image.Image, size: int, bg=(0, 0, 0, 0), margin: float = 0.08) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), bg)
    inner = int(size * (1 - 2 * margin))
    scale = inner / max(im.width, im.height)
    fitted = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2), fitted)
    return canvas


def main() -> None:
    src = Image.open(SRC).convert("RGBA")
    full = trimmed(src)
    # The C mark ends above the wordmark: find the transparent band between them.
    alpha = src.getchannel("A")
    rows = [any(alpha.getpixel((x, y)) for x in range(0, src.width, 2)) for y in range(src.height)]
    top = rows.index(True)
    gap = next(y for y in range(top, src.height) if not rows[y] and y > src.height * 0.6)
    mark = trimmed(src.crop((0, 0, src.width, gap)))

    (PUB / "brand").mkdir(parents=True, exist_ok=True)
    full.save(PUB / "brand" / "casterly-logo.png", optimize=True)
    mark.save(PUB / "brand" / "casterly-mark.png", optimize=True)
    square(mark, 32, margin=0.04).save(PUB / "favicon-32.png", optimize=True)
    square(mark, 64, margin=0.04).save(PUB / "favicon-64.png", optimize=True)
    square(mark, 180, bg=(255, 255, 255, 255), margin=0.16).convert("RGB").save(PUB / "apple-touch-icon.png", optimize=True)
    assets = ROOT / "backend" / "app" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    full.resize((full.width // 3, full.height // 3), Image.LANCZOS).save(assets / "casterly-logo.png", optimize=True)
    shutil.copy(PUB / "brand" / "casterly-logo.png", ROOT / "brand" / "casterly-logo.png")
    print("full", full.size, "mark", mark.size)


if __name__ == "__main__":
    main()
