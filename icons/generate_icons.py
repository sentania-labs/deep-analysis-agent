"""Generate Deep Analysis identity and tray pip icons.

Produces 7 ICO files in this directory:
  identity.ico                           (16 + 32 + 48 + 256)
  W.ico / U.ico / B.ico / R.ico / G.ico  (16 + 32) — active pips
  C.ico                                  (16 + 32) — colorless / idle pip

All artwork is simple geometric primitives drawn with Pillow. The identity
icon is a five-wedge color wheel loosely inspired by the MTG color pie;
it is not derived from WotC art. Re-run this script to regenerate.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ICONS_DIR = Path(__file__).resolve().parent
BASE = 512  # high-resolution render; PIL downsamples to ICO frames

PIP_SIZES = [16, 32]
IDENTITY_SIZES = [16, 32, 48, 256]

# Pip fill colors — tuned for visibility on both light and dark tray bars.
PIP_COLORS = {
    "W": "#D4D0C8",
    "U": "#0E68AB",
    "B": "#2C2C2C",
    "R": "#D3202A",
    "G": "#00733E",
    "C": "#C1C1C1",
}

# Identity wheel colors — truer to the mana palette; visibility handled
# by the dark border between wedges.
WHEEL_COLORS = {
    "W": "#F9FAF4",
    "U": "#0E68AB",
    "B": "#150B00",
    "R": "#D3202A",
    "G": "#00733E",
}


def new_canvas() -> Image.Image:
    return Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))


def save_ico(img: Image.Image, filename: str, sizes: list[int]) -> Path:
    path = ICONS_DIR / filename
    img.save(path, format="ICO", sizes=[(s, s) for s in sizes])
    return path


def make_pip(name: str, fill: str) -> Path:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    pad = 12
    # 1px-equivalent dark border so light pips (W, C) read on light tray bars.
    draw.ellipse([pad, pad, BASE - pad, BASE - pad], fill="#1A1A1A")
    ring = 24
    draw.ellipse(
        [pad + ring, pad + ring, BASE - pad - ring, BASE - pad - ring],
        fill=fill,
    )
    return save_ico(img, f"{name}.ico", PIP_SIZES)


def make_identity() -> Path:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    cx = cy = BASE // 2
    r = 240
    bbox = [cx - r, cy - r, cx + r, cy + r]

    # WUBRG clockwise from the top, each wedge 72°.
    order = ["W", "U", "B", "R", "G"]
    # pieslice angles are measured clockwise from 3 o'clock; -90 puts 0 at the top.
    start = -90
    for i, key in enumerate(order):
        a0 = start + i * 72
        a1 = a0 + 72
        draw.pieslice(bbox, a0, a1, fill=WHEEL_COLORS[key], outline="#1A1A1A", width=4)

    # Outer ring to contain the wheel cleanly.
    draw.ellipse(bbox, outline="#1A1A1A", width=6)

    # Neutral hub so the wedges read as a wheel, not a flat pie.
    hub_r = 55
    draw.ellipse(
        [cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r],
        fill="#2C2C2C",
        outline="#1A1A1A",
        width=4,
    )
    return save_ico(img, "identity.ico", IDENTITY_SIZES)


def cleanup_retired() -> list[Path]:
    removed: list[Path] = []
    for name in ("rainbow_pentagon.ico", "M_idle.ico"):
        p = ICONS_DIR / name
        if p.exists():
            p.unlink()
            removed.append(p)
    return removed


def main() -> None:
    produced: list[Path] = []
    produced.append(make_identity())
    for key in ("W", "U", "B", "R", "G", "C"):
        produced.append(make_pip(key, PIP_COLORS[key]))

    removed = cleanup_retired()

    rel_root = ICONS_DIR.parent.parent
    for p in produced:
        print(f"  wrote {p.relative_to(rel_root)}")
    for p in removed:
        print(f"  removed {p.relative_to(rel_root)}")
    print(f"generated {len(produced)} icons")


if __name__ == "__main__":
    main()
