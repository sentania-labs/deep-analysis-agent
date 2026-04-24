"""Generate app.ico from the idle colorless pip PNG.

Produces icons/app.ico at multiple resolutions (16, 32, 48, 64, 128, 256)
for use as the installer icon in the Squirrel NuGet package.

Run after generate_icons.py has produced C.png.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ICONS_DIR = Path(__file__).resolve().parent
SIZES = [16, 32, 48, 64, 128, 256]


def main() -> None:
    src = ICONS_DIR / "C.png"
    if not src.exists():
        raise FileNotFoundError(f"C.png not found at {src} — run generate_icons.py first")
    img = Image.open(src).convert("RGBA")
    frames = [img.resize((s, s), Image.LANCZOS) for s in SIZES]
    out = ICONS_DIR / "app.ico"
    frames[0].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[1:])
    print(f"wrote {out} ({len(SIZES)} sizes)")


if __name__ == "__main__":
    main()
