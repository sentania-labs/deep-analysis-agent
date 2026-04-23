"""Generate placeholder tray pip icons as PNGs.

Produces six 64x64 PNGs: W / U / B / R / G (active pips) and C (idle).
Real artwork deferred — these solid filled circles make the tray
functional immediately. Re-run to regenerate.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ICONS_DIR = Path(__file__).resolve().parent
SIZE = 64
PAD = 4

PIP_COLORS: dict[str, str] = {
    "W": "#F5F5E6",
    "U": "#0E68AB",
    "B": "#282828",
    "R": "#D3202A",
    "G": "#00733E",
    "C": "#C1C1C1",
}


def make_pip(name: str, hex_color: str) -> Path:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        (PAD, PAD, SIZE - PAD, SIZE - PAD),
        fill=hex_color,
        outline="#000000",
        width=2,
    )
    path = ICONS_DIR / f"{name}.png"
    img.save(path, format="PNG")
    return path


def main() -> None:
    for name, color in PIP_COLORS.items():
        out = make_pip(name, color)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
