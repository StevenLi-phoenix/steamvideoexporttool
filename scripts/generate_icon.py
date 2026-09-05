"""One-off generator for assets/app-icon.ico (used by build-quick.ps1).

Run with Pillow available but without adding it as a project dependency:

    uv run --with pillow python scripts/generate_icon.py

Draws a simple, original mark (not Steam's logo) evoking "export a recording":
a play triangle over a rounded dark tile, with a small downward export arrow
badge. Regenerate at a larger SIZE and re-run if a sharper source is needed.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
OUT = Path(__file__).resolve().parent.parent / "assets" / "app-icon.ico"

BACKGROUND = (17, 24, 32, 255)      # near-black navy tile
ACCENT = (102, 192, 244, 255)       # light blue play glyph
BADGE = (37, 47, 61, 255)           # export-arrow badge circle
ARROW = (237, 245, 250, 255)        # white-ish arrow


def draw_icon():
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = SIZE * 0.06
    draw.rounded_rectangle(
        [margin, margin, SIZE - margin, SIZE - margin],
        radius=SIZE * 0.22, fill=BACKGROUND,
    )

    # Play triangle, centered and slightly left-shifted so it reads as centered
    # despite its own visual weight leaning right.
    cx, cy = SIZE * 0.46, SIZE * 0.50
    half = SIZE * 0.20
    draw.polygon(
        [(cx - half, cy - half * 1.15), (cx - half, cy + half * 1.15), (cx + half * 1.2, cy)],
        fill=ACCENT,
    )

    # Export badge: circle + downward arrow, bottom-right corner.
    bx, by, br = SIZE * 0.735, SIZE * 0.735, SIZE * 0.19
    draw.ellipse([bx - br, by - br, bx + br, by + br], fill=BADGE)
    shaft_w = br * 0.34
    draw.rectangle([bx - shaft_w / 2, by - br * 0.55, bx + shaft_w / 2, by + br * 0.12], fill=ARROW)
    head = br * 0.55
    draw.polygon(
        [(bx - head, by), (bx + head, by), (bx, by + head * 0.95)],
        fill=ARROW,
    )

    return image


def main():
    image = draw_icon()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
