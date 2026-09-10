#!/usr/bin/env python3
"""Generate the app icon set, from source, with no image library.

WHY THIS IS A SCRIPT AND NOT FOUR CHECKED-IN PNGs
--------------------------------------------------
web/ contains zero image files, and the app has no installable surface
partly because of it: a web manifest needs real icons to point at. The easy
move is to paste four binaries into the repo and never think about them
again. But `docs/BRAND_SCREEN_LINEHOUND.md` says the name itself is a
WORKING PLACEHOLDER pending trademark clearance, and `api/meta.py` marks the
brand `{"temporary": True}` -- so these icons are certain to be replaced,
and a binary nobody can regenerate is a binary nobody dares change.

Everything here is derived from web/css/tokens.css's real palette. When the
brand lands, edit the constants below and re-run; when a designer delivers
proper artwork, delete this file and commit their PNGs instead.

NO PILLOW, NO CAIRO, NO NODE. Pure stdlib: PNG is a container around
zlib-compressed scanlines, which is about thirty lines to write and removes
a dependency this project would otherwise carry for four small files.

THE MARK
--------
Two stacked bars on a chamfered dark ground. The lower bar is long and dim,
the upper is shorter and bright: one price, and a better one above it. That
is literally what the product does -- find the better number -- and it stays
legible at 48px, which a wordmark or a hound would not. The chamfered corner
is the design system's own primitive (tokens.css uses chamfers, never
border-radius).

USAGE
-----
    python scripts/make_icons.py          # writes web/icons/*.png
    python scripts/make_icons.py --check  # verifies they match, writes nothing

`--check` is what CI runs: it regenerates in memory and compares bytes, so a
hand-edited icon or a stale checkout fails loudly instead of drifting.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "web" / "icons"

# --- palette, from web/css/tokens.css --------------------------------------
GROUND = (0x0A, 0x0A, 0x0B)      # --v-ground
MONEY = (0xFF, 0x3D, 0x57)       # --money
MONEY_LIT = (0xFF, 0x62, 0x74)   # --money-lit
EDGE = (0x2A, 0x2A, 0x2E)        # a hairline so the tile reads on dark wallpaper

# --- the sizes each platform actually asks for -----------------------------
# 192 and 512: the web manifest's two required sizes.
# 180: apple-touch-icon, the only one iOS reads, and it must be opaque --
#      iOS composites nothing and a transparent icon renders black-on-black.
# 512 maskable: Android crops icons to a device-chosen shape, so the mark
#      must sit inside a 40% safe radius or corners of it get sliced off.
# style: "chamfer"  -- full bleed with the design system's cut corner
#        "maskable" -- no silhouette of our own, mark inset into the safe zone
#        "opaque"   -- full bleed, no chamfer, no transparency anywhere
SIZES = (
    ("icon-192.png", 192, "chamfer"),
    ("icon-512.png", 512, "chamfer"),
    ("icon-maskable-512.png", 512, "maskable"),
    # iOS ignores transparency and composites nothing behind it, so a
    # chamfered corner here would render as a black notch -- and iOS applies
    # its own rounded mask regardless, which would fight our cut corner even
    # if it did honour alpha. Full bleed, fully opaque.
    ("apple-touch-icon.png", 180, "opaque"),
)


def _png(width: int, height: int, pixels: bytes) -> bytes:
    """Minimal RGBA PNG. `pixels` is width*height*4 bytes, top row first."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter type 0 (None) for every scanline
        raw.extend(pixels[y * stride:(y + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _blend(dst, src, alpha):
    """src over dst at `alpha` in 0..1. Icons are small and flat, so a
    per-pixel float blend is plenty fast and keeps the edges from aliasing
    into hard jaggies at 48px."""
    return tuple(int(round(d + (s - d) * alpha)) for d, s in zip(dst, src))


def render(size: int, style: str) -> bytes:
    """The mark, at `size`, in one of the three styles above."""
    maskable = style == "maskable"

    # Android's maskable spec guarantees only the middle 80% survives a
    # crop; 0.72 leaves a margin on top of that rather than sitting exactly
    # on the line.
    pad = (1.0 - 0.72) / 2.0 * size if maskable else 0.0

    # A chamfered ground, not a rounded one -- the design system uses a cut
    # corner everywhere and a rounded icon would read as a different brand.
    chamfer = size * 0.18 if style == "chamfer" else 0.0

    inner = size - 2 * pad
    # Bar geometry, as fractions of the inner box.
    #
    # THE BRIGHT BAR IS THE LONGER ONE. It was the shorter one first, which
    # renders as a bar chart where our number is the small one -- the exact
    # opposite of the point. A better price is a bigger number, so the lit
    # bar has to be the one that reaches further.
    bar_h = inner * 0.150
    gap = inner * 0.105
    hi_w, low_w = inner * 0.680, inner * 0.440
    left = pad + inner * 0.165
    mid = pad + inner / 2.0
    low_top = mid + gap / 2.0
    hi_top = mid - gap / 2.0 - bar_h

    def in_bar(px, py, top, width):
        return top <= py <= top + bar_h and left <= px <= left + width

    # The top-right chamfer runs from (size - c, 0) to (size, c); a point is
    # cut away when it sits above that 45-degree line.
    dim_bar = _blend(GROUND, MONEY, 0.55)

    out = bytearray()
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5

            if chamfer and (px - py) > (size - chamfer):
                out.extend((0, 0, 0, 0))   # outside the chamfered ground
                continue

            colour = GROUND
            # Hairline edge so the tile has a boundary on a dark wallpaper.
            # Not on maskable (the launcher supplies the silhouette) and not
            # on the iOS icon (its own mask would clip a border unevenly).
            if style == "chamfer" and (px < 2 or py < 2
                                       or px > size - 2 or py > size - 2):
                colour = EDGE

            if in_bar(px, py, hi_top, hi_w):
                colour = MONEY_LIT           # the better number
            elif in_bar(px, py, low_top, low_w):
                colour = dim_bar             # the price you would have taken

            out.extend((colour[0], colour[1], colour[2], 255))
    return _png(size, size, bytes(out))


def main() -> int:
    check = "--check" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    drifted = []
    for name, size, style in SIZES:
        data = render(size, style)
        target = OUT_DIR / name
        if check:
            if not target.exists() or target.read_bytes() != data:
                drifted.append(name)
            continue
        target.write_bytes(data)
        print(f"  wrote {target.relative_to(REPO)}  ({len(data):,} bytes)")

    if check:
        if drifted:
            print("ESCALATE: icons differ from what scripts/make_icons.py "
                  f"generates: {', '.join(drifted)}. Re-run the script, or "
                  f"if the artwork was replaced on purpose, delete the "
                  f"script and its CI check together.")
            return 1
        print("icons: match their generator")
        return 0
    print(f"\n{len(SIZES)} icons written to {OUT_DIR.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
