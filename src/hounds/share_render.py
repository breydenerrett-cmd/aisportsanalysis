"""Pillow drawing for the shared-dog card (decisions are in ``share_card``; this file only paints a ``CardSpec``).

Imported lazily by ``share_card.png_for`` so a machine without Pillow (the Linux CI image) still loads the rest.

THE HOUND. web/js/dog-rig.js draws 33 breeds with a procedural rig; this is not a port of it. It reads the same
whitelisted look and the same colour tables and paints one head per ear-and-muzzle family: coat, shade and light,
eye colour, tile background, the art style's outline weight (mascot thick, street slimmer, elite a hairline), the
sunburst / grain / gold ring of the three styles, and the accessories an owner picks (cap, headband, visor,
sunglasses, collar, chain, bandana, hoodie, jersey with its number). It draws at 2x and shrinks, so edges are clean.

THE TYPE is the site's own: Barlow Condensed and Instrument Sans, the Latin subsets already shipped as base64 in
web/css/fonts.css, converted once to TTF under ``share_assets/`` (SIL Open Font License 1.1). A missing font file
falls back to Pillow's built-in face rather than failing the card.
"""

from __future__ import annotations

import io
import math
import random
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from src.hounds import share_card as sc

ASSETS = Path(__file__).resolve().parent / "share_assets"
DISPLAY_BOLD = "BarlowCondensed-Bold.ttf"
DISPLAY_SEMI = "BarlowCondensed-SemiBold.ttf"
BODY = "InstrumentSans-Medium.ttf"

INK = (11, 13, 18)
GROUND = (11, 12, 14)
ACCENT = (47, 208, 122)
TEXT = (246, 247, 250)
SOFT = (214, 219, 228)
MUTE = (138, 145, 158)
GOLD = (224, 178, 74)
SS = 2                                   # supersampling for the art tile

# breed -> (ears, muzzle length, skull width). Families, not 33 drawings: the ears and the muzzle are what the eye reads.
_BREED_TRAITS = {
    "retriever": ("drop", 1.0, 1.0), "labrador": ("drop", 0.95, 1.02), "bulldog": ("rose", 0.55, 1.12),
    "newfoundland": ("drop", 1.0, 1.1), "chihuahua": ("prick", 0.7, 0.92), "corgi": ("prick", 0.95, 1.0),
    "collie": ("fold", 1.3, 0.92), "shepherd": ("prick", 1.1, 1.0), "kelpie": ("prick", 1.0, 0.96),
    "husky": ("prick", 0.95, 1.0), "jackrussell": ("fold", 0.9, 0.95), "dalmatian": ("fold", 1.0, 0.98),
    "pointer": ("drop", 1.15, 0.95), "beagle": ("drop", 0.95, 1.0), "basset": ("drop", 1.05, 1.0),
    "bloodhound": ("drop", 1.15, 1.04), "hound": ("drop", 1.05, 1.0), "greyhound": ("rose", 1.35, 0.85),
    "whippet": ("rose", 1.3, 0.86), "setter": ("drop", 1.15, 0.96), "spaniel": ("drop", 0.9, 1.0),
    "poodle": ("drop", 1.2, 0.92), "terrier": ("fold", 1.0, 0.94), "schnauzer": ("fold", 1.05, 0.98),
    "mutt": ("fold", 1.0, 1.0), "doberman": ("crop", 1.3, 0.92), "rottweiler": ("fold", 0.85, 1.12),
    "pitbull": ("rose", 0.75, 1.12), "wolfhound": ("fold", 1.3, 0.95), "boxer": ("fold", 0.6, 1.08),
    "mastiff": ("drop", 0.7, 1.15), "shiba": ("prick", 0.85, 1.0), "malinois": ("prick", 1.1, 0.95),
}
_STYLE = {  # outline weight in 120-unit space, and the finish
    "mascot": {"ow": 3.2, "burst": True, "grit": False, "ring": False, "cel": True, "hood": (44, 52, 66), "hood_light": (59, 68, 85), "jersey": (242, 244, 248)},
    "street": {"ow": 2.5, "burst": False, "grit": True, "ring": False, "cel": True, "hood": (21, 24, 30), "hood_light": (35, 39, 47), "jersey": (231, 233, 238)},
    "elite": {"ow": 1.2, "burst": False, "grit": False, "ring": True, "cel": False, "hood": (37, 43, 54), "hood_light": (50, 58, 72), "jersey": (247, 248, 251)},
}
_CAP = {"mascot": (43, 95, 217), "street": (42, 46, 55), "elite": (27, 45, 82)}


# ---- small helpers ----------------------------------------------------------------------------------------------

def _rgb(hexs: str) -> tuple:
    return tuple(int(hexs[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


@lru_cache(maxsize=32)
def _font(name: str, size: int):
    try:
        return ImageFont.truetype(str(ASSETS / name), size)
    except OSError:
        try:
            return ImageFont.load_default(size)
        except TypeError:  # very old Pillow
            return ImageFont.load_default()


def _spline(pts: Sequence, closed: bool = True, steps: int = 10) -> list:
    """Catmull-Rom through the points (the rig's own smoothing), sampled to a polyline."""
    n = len(pts)
    out = []
    count = n if closed else n - 1
    for i in range(count):
        p0 = pts[(i - 1) % n] if closed else pts[max(0, i - 1)]
        p1, p2 = pts[i], pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed else pts[min(n - 1, i + 2)]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    if not closed:
        out.append(tuple(pts[-1]))
    return out


def _sym(half: Sequence) -> list:
    """A closed outline from the right half ((dx, y) from the top centre to the bottom centre), around x = 60."""
    right = [(60 + dx, y) for dx, y in half]
    left = [(60 - dx, y) for dx, y in reversed(half[1:-1])]
    return right + left


def _mirror(pts: Sequence) -> list:
    return [(120 - x, y) for x, y in pts]


class _Canvas:
    """A 120-unit drawing surface on an RGBA image `px * SS` wide."""

    def __init__(self, px: int):
        self.px = px
        self.size = px * SS
        self.k = self.size / 120.0
        self.img = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img, "RGBA")
        self._ov = None
        self._od = None

    def _translucent(self) -> ImageDraw.ImageDraw:
        """ImageDraw REPLACES pixels (alpha included) on an RGBA image, so a translucent mark drawn straight on the
        tile would punch a hole in it. Translucent marks go on an overlay that is composited before the next opaque draw."""
        if self._ov is None:
            self._ov = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
            self._od = ImageDraw.Draw(self._ov)
        return self._od

    def flush(self) -> None:
        if self._ov is not None:
            self.img.alpha_composite(self._ov)
            self._ov = self._od = None

    def xy(self, pts: Sequence) -> list:
        return [(x * self.k, y * self.k) for x, y in pts]

    def shape(self, pts: Sequence, fill: tuple, ink: tuple, ow: float, *, smooth: bool = True, shade: float = 0.0, cel: bool = True,
              closed: bool = True) -> None:
        self.flush()
        poly = self.xy(_spline(pts) if smooth else pts)
        self.d.polygon(poly, fill=fill + (255,))
        if shade:
            self._shade(poly, shade, cel)
        if ow:
            self.d.line(poly + [poly[0]], fill=ink + (255,), width=max(1, int(round(ow * self.k))), joint="curve")

    def flat(self, pts: Sequence, fill: tuple, alpha: int = 255, smooth: bool = True) -> None:
        d = self._translucent() if alpha < 255 else (self.flush() or self.d)
        d.polygon(self.xy(_spline(pts) if smooth else pts), fill=fill + (alpha,))

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, fill: tuple, ink: tuple = None, ow: float = 0.0, alpha: int = 255) -> None:
        box = [(cx - rx) * self.k, (cy - ry) * self.k, (cx + rx) * self.k, (cy + ry) * self.k]
        d = self._translucent() if alpha < 255 else (self.flush() or self.d)
        d.ellipse(box, fill=fill + (alpha,), outline=(ink + (255,)) if ink and ow else None,
                       width=max(1, int(round(ow * self.k))) if ow else 1)

    def line(self, pts: Sequence, fill: tuple, w: float, alpha: int = 255, smooth: bool = False) -> None:
        pl = self.xy(_spline(pts, closed=False) if smooth else pts)
        d = self._translucent() if alpha < 255 else (self.flush() or self.d)
        d.line(pl, fill=fill + (alpha,), width=max(1, int(round(w * self.k))), joint="curve")
        r = w * self.k / 2
        for x, y in (pl[0], pl[-1]):
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill + (alpha,))

    def _shade(self, poly: list, strength: float, cel: bool) -> None:
        """Light from the upper left: a hard step of shadow on the lower right (mascot, street) or a soft one (elite)."""
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.size, x1), min(self.size, y1)
        w, h = x1 - x0, y1 - y0
        if w < 4 or h < 4:
            return
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in poly], fill=255)
        big = Image.radial_gradient("L").resize((w * 2, h * 2))
        cx, cy = int(w * 2 * 0.5 - w * 0.32), int(h * 2 * 0.5 - h * 0.28)
        grad = big.crop((cx, cy, cx + w, cy + h))
        if cel:
            grad = grad.point(lambda v: 255 if v >= 150 else 0)
        else:
            grad = grad.point(lambda v: int(255 * max(0.0, (v - 80) / 175.0)))
        alpha = ImageChops.multiply(ImageChops.multiply(grad, mask), Image.new("L", (w, h), int(255 * strength)))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.putalpha(alpha)
        self.img.alpha_composite(layer, (x0, y0))


# ---- the hound ---------------------------------------------------------------------------------------------------

def _tile_background(c: _Canvas, look: dict, style: dict) -> None:
    top, bottom = (_rgb(h) for h in sc.BACKGROUNDS[look["bg"]])
    grad = ImageOps.colorize(Image.linear_gradient("L").resize((c.size, c.size)), black=top, white=bottom)
    c.img.paste(grad.convert("RGBA"), (0, 0))
    glow = Image.radial_gradient("L").resize((c.size, c.size))
    glow = glow.point(lambda v: int(max(0.0, 255 - v * 255 / 180.0) * 0.2))
    layer = Image.new("RGBA", (c.size, c.size), (255, 255, 255, 0))
    layer.putalpha(glow)
    c.img.alpha_composite(layer)
    if style["burst"]:
        for i in range(12):
            a0, a1 = math.radians(i * 30 - 6), math.radians(i * 30 + 6)
            c.flat([(60, 66), (60 + 150 * math.cos(a0), 66 + 150 * math.sin(a0)), (60 + 150 * math.cos(a1), 66 + 150 * math.sin(a1))],
                   (255, 255, 255), 19, smooth=False)
    if style["grit"]:
        rnd = random.Random(7)
        for _ in range(260):
            x, y = rnd.uniform(0, 120), rnd.uniform(0, 120)
            c.ellipse(x, y, 0.5, 0.5, (0, 0, 0) if rnd.random() < 0.6 else (255, 255, 255), alpha=70)
        c.ellipse(8, 8, 9, 8, (255, 79, 163), alpha=210)
        c.ellipse(15, 12, 3, 3, (255, 79, 163), alpha=210)
        c.ellipse(108, 100, 8, 8, (39, 211, 245), alpha=200)
        c.line([(8, 112), (30, 105), (52, 110)], (198, 244, 50), 3, alpha=200, smooth=True)


def _ears(c: _Canvas, kind: str, hw: float, coat: dict, ink: tuple, ow: float) -> None:
    shade, base = coat["shade"], coat["base"]
    inner = _mix(coat["shade"], (217, 138, 146), 0.45)
    if kind == "drop":
        left = [(60 - hw * 0.55, 24), (60 - hw - 7, 33), (60 - hw - 11, 58), (60 - hw - 7, 84), (60 - hw + 3, 82), (60 - hw + 7, 50)]
        for pts in (left, _mirror(left)):
            c.shape(pts, shade, ink, ow, shade=0.2)
    elif kind in ("prick", "crop"):
        tall = 20 if kind == "crop" else 16
        left = [(60 - hw * 0.28, 28), (60 - hw * 0.98, 38), (60 - hw * (0.92 if kind == "crop" else 0.82), 38 - tall - 14)]
        inn = [(60 - hw * 0.42, 30), (60 - hw * 0.84, 36), (60 - hw * 0.8, 38 - tall - 2)]
        for pts, ip in ((left, inn), (_mirror(left), _mirror(inn))):
            c.shape(pts, base, ink, ow, smooth=False, shade=0.2)
            c.flat(ip, inner, smooth=False)
    elif kind == "fold":
        left = [(60 - hw * 0.3, 24), (60 - hw * 0.95, 26), (60 - hw - 5, 46), (60 - hw * 0.7, 40)]
        for pts in (left, _mirror(left)):
            c.shape(pts, shade, ink, ow, smooth=False, shade=0.15)
    else:  # rose
        left = [(60 - hw * 0.35, 25), (60 - hw * 0.95, 28), (60 - hw - 2, 40), (60 - hw * 0.75, 38)]
        for pts in (left, _mirror(left)):
            c.shape(pts, shade, ink, ow, smooth=False, shade=0.15)


def _head_piece(c: _Canvas, look: dict, style: dict, ink: tuple, ow: float, hw: float) -> None:
    kind = look["head"]
    if kind == "none":
        return
    col = _CAP[look["style"]]
    if kind == "cap":
        dome = [(60 - hw * 0.9, 38), (60 - hw * 0.85, 22), (60 - hw * 0.4, 12), (60, 10), (60 + hw * 0.4, 12), (60 + hw * 0.85, 22), (60 + hw * 0.9, 38)]
        c.shape(dome, col, ink, ow, shade=0.25, cel=style["cel"])
        c.shape([(60 - hw * 0.95, 36), (60 + hw * 0.95, 36), (60 + hw * 0.8, 43), (60 - hw * 0.8, 43)], _mix(col, (255, 255, 255), 0.12), ink, ow, smooth=False)
    elif kind == "visor":
        c.shape([(60 - hw * 0.95, 33), (60 + hw * 0.95, 33), (60 + hw * 0.8, 44), (60 - hw * 0.8, 44)], col, ink, ow, smooth=False)
        c.line([(60 - hw * 0.9, 31), (60 + hw * 0.9, 31)], _mix(col, (255, 255, 255), 0.25), 3.2)
    else:  # headband
        c.shape([(60 - hw * 0.98, 33), (60 + hw * 0.98, 33), (60 + hw * 0.98, 41), (60 - hw * 0.98, 41)], ACCENT, ink, ow * 0.7, smooth=False)


def _face_piece(c: _Canvas, look: dict, ink: tuple, ow: float, ey: float, edx: float) -> None:
    if look["face"] != "sunglasses":
        return
    lens = (14, 16, 20)
    for sx in (-1, 1):
        cx = 60 + sx * edx
        c.shape([(cx - 9.5, ey - 5), (cx + 9.5, ey - 5), (cx + 8.5, ey + 6.5), (cx - 8.5, ey + 6.5)], lens, ink, ow * 0.6)
        c.line([(cx - 5, ey - 2.5), (cx - 1, ey - 2.5)], (255, 255, 255), 1.4, alpha=140)
    c.line([(60 - edx + 9, ey - 2), (60 + edx - 9, ey - 2)], lens, 2.4)


def _neck_piece(c: _Canvas, look: dict, style: dict, ink: tuple, ow: float, chin: float, nk: float) -> None:
    kind = look["neck"]
    if kind == "collar":
        c.line([(60 - nk, chin - 6), (60, chin + 6), (60 + nk, chin - 6)], (22, 24, 29), 5.4, smooth=True)
        for t in (-0.7, -0.35, 0, 0.35, 0.7):
            x = 60 + t * nk
            y = chin + 6 - abs(t) * 5.5
            c.flat([(x - 1.8, y), (x + 1.8, y), (x, y + 5)], (201, 208, 218), smooth=False)
    elif kind == "bandana":
        col = {"mascot": (228, 87, 46), "street": (242, 201, 76), "elite": (30, 45, 87)}[look["style"]]
        c.shape([(60 - nk - 2, chin + 2), (60 + nk + 2, chin + 2), (60 + 6, chin + 26), (60 - 6, chin + 26)], col, ink, ow * 0.8, smooth=False, shade=0.2)
    elif look["body"] not in ("hoodie", "jersey"):
        c.line([(60 - nk, chin - 6), (60, chin + 5), (60 + nk, chin - 6)], ACCENT, 4.2, smooth=True)
        c.ellipse(60, chin + 8.5, 3.2, 3.2, GOLD, (138, 106, 31), 0.8)
    if kind == "chain":
        c.line([(60 - nk, chin - 4), (60, chin + 14), (60 + nk, chin - 4)], ink, style_chain(look) + 1.6, smooth=True)
        c.line([(60 - nk, chin - 4), (60, chin + 14), (60 + nk, chin - 4)], GOLD, style_chain(look), smooth=True)
        c.shape([(60, chin + 11), (66, chin + 15), (66, chin + 20), (60, chin + 24), (54, chin + 20), (54, chin + 15)], GOLD, ink, ow * 0.5, smooth=False)


def style_chain(look: dict) -> float:
    return {"mascot": 3.4, "street": 4.6, "elite": 2.8}[look["style"]]


def _body(c: _Canvas, look: dict, style: dict, coat: dict, ink: tuple, ow: float, chin: float, nk: float, bulk: float) -> None:
    top = max(94.0, chin + 1)
    X = lambda x: 60 + (x - 60) * bulk                                           # noqa: E731
    c.shape([(60 - nk, chin - 18), (60 + nk, chin - 18), (60 + nk + 12, top + 10), (60 - nk - 12, top + 10)],
            _mix(coat["base"], coat["shade"], 0.35), ink, ow, smooth=False)
    torso = [(X(-8), 126), (X(-2), top + 14), (X(18), top + 3), (X(42), top - 0.5), (60, top + 5.5), (X(78), top - 0.5),
             (X(102), top + 3), (X(122), top + 14), (X(128), 126)]
    if look["body"] == "hoodie":
        c.shape([(60 - 34, top - 8), (60 - 20, top - 20), (60 + 20, top - 20), (60 + 34, top - 8), (60 + 18, top + 8), (60 - 18, top + 8)],
                style["hood_light"], ink, ow, shade=0.2, cel=style["cel"])
        c.shape(torso, style["hood"], ink, ow, shade=0.25, cel=style["cel"])
        c.line([(52, top + 6), (51, top + 19)], (233, 236, 241), 1.8)
        c.line([(68, top + 6), (69, top + 19)], (233, 236, 241), 1.8)
    elif look["body"] == "jersey":
        c.shape(torso, style["jersey"], ink, ow, shade=0.2, cel=style["cel"])
        c.flat([(60 - 13 * bulk, top + 1), (60, top + 10), (60 + 13 * bulk, top + 1), (60 + 13 * bulk, top + 4), (60, top + 13.5), (60 - 13 * bulk, top + 4)], ACCENT, smooth=False)
        if look.get("number") is not None:
            num = str(look["number"])
            f = _font(BODY, int(15 * c.k))
            c.flush()
            c.d.text((60 * c.k, min(118.0, top + 20.5) * c.k), num, font=f, fill=(14, 17, 22, 255), anchor="mm")
    else:
        c.shape(torso, coat["base"], ink, ow, shade=0.22, cel=style["cel"])
        c.flat([(60 - 22 * bulk, top + 5), (60, top + 16), (60 + 22 * bulk, top + 5), (60, top + 11)], coat["light"], 120)


def draw_hound(look: dict, breed: str, px: int) -> Image.Image:
    """The dog's tile: a square RGBA image `px` wide, rounded corners, from a whitelisted look."""
    style = _STYLE[look["style"]]
    c0 = sc.COATS[look["coat"]]
    coat = {"base": _rgb(c0[0]), "shade": _rgb(c0[1]), "light": _rgb(c0[2])}
    if breed == "dalmatian":
        coat = {"base": (233, 236, 241), "shade": (195, 201, 211), "light": (255, 255, 255)}
    ink = INK if look["style"] != "elite" else _mix(coat["shade"], INK, 0.62)
    ow = style["ow"]
    ears, mlen, wid = _BREED_TRAITS.get(breed, _BREED_TRAITS["retriever"])
    c = _Canvas(px)
    _tile_background(c, look, style)

    hw = 31.0 * wid
    chin = 56 + 40 * (0.55 + 0.45 * mlen) * 0.95
    chin = min(100.0, max(86.0, chin))
    nk = 22.0
    bulk = 1.12 if breed in ("mastiff", "rottweiler", "newfoundland", "bulldog", "pitbull", "boxer") else 1.0
    ey, edx = 53.0, 14.0
    # a little shadow on the ground, then the body, ears, head
    c.ellipse(60, 119, 46, 5, (0, 0, 0), alpha=64)
    _body(c, look, style, coat, ink, ow, chin, nk, bulk)
    _ears(c, ears, hw, coat, ink, ow)

    cran = _sym([(0, 22), (hw * 0.5, 22.4), (hw * 0.86, 29), (hw, 42), (hw, 57), (hw * 0.9, 73), (hw * 0.55, 87), (0, chin - 3)])
    c.shape(cran, coat["base"], ink, ow, shade=0.28, cel=style["cel"])
    # the lit patch on the forehead, the muzzle, the nose, the mouth
    mw = 13.5 * (0.9 + 0.1 * wid)
    muz = _sym([(0, 50), (mw * 0.62, 52), (mw, 64), (mw * 1.02, 76), (mw * 0.8, chin - 6), (mw * 0.4, chin - 1), (0, chin)])
    c.shape(muz, _mix(coat["base"], coat["light"], 0.55), ink, ow * 0.45)
    if breed == "dalmatian":
        for (x, y, r) in ((40, 34, 3), (78, 38, 2.6), (34, 56, 2.4), (86, 60, 3), (48, 28, 2), (70, 30, 2.2)):
            c.ellipse(x, y, r, r, (24, 26, 31))
    ny = 66.0 + (chin - 90) * 0.35
    c.ellipse(60, ny, 7.2, 4.6, (20, 23, 27), ink, 0.5)
    c.ellipse(58, ny - 1.5, 2, 1.2, (255, 255, 255), alpha=110)
    my = ny + 11
    c.line([(60, ny + 4), (60, my - 3)], ink, 1.5)
    c.line([(60 - 11, my - 2), (60 - 5, my + 3), (60, my - 3), (60 + 5, my + 3), (60 + 11, my - 2)], ink, 1.6, smooth=True)
    c.ellipse(60, my + 5.5, 4.2, 3.4, (217, 138, 146), ink, 0.5)
    eye = _rgb(sc.EYES[look["eyes"]])
    for sx in (-1, 1):
        ex = 60 + sx * edx
        c.ellipse(ex, ey, 6.4, 5.8, (250, 250, 252), ink, 0.9)
        c.ellipse(ex, ey + 0.4, 4.5, 4.4, eye)
        c.ellipse(ex, ey + 0.5, 2.3, 2.3, (12, 14, 18))
        c.ellipse(ex - 1.5, ey - 1.4, 1.2, 1.2, (255, 255, 255))
        c.line([(ex + sx * 6.5, ey - 10.5), (ex - sx * 6.5, ey - 8.5)], ink, 2.0)
    _face_piece(c, look, ink, ow, ey, edx)
    _head_piece(c, look, style, ink, ow, hw)
    _neck_piece(c, look, style, ink, ow, chin, nk)

    c.flush()
    out = c.img.resize((px, px), Image.LANCZOS)
    mask = Image.new("L", (px * SS, px * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, px * SS - 1, px * SS - 1], radius=int(26 / 120 * px * SS), fill=255)
    mask = mask.resize((px, px), Image.LANCZOS)
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    if style["ring"]:
        ImageDraw.Draw(out, "RGBA").rounded_rectangle([1, 1, px - 2, px - 2], radius=int(25 / 120 * px), outline=GOLD + (230,), width=max(2, px // 120))
    return out


# ---- the card ---------------------------------------------------------------------------------------------------

def _tracked(d: ImageDraw.ImageDraw, xy: tuple, text: str, font, fill: tuple, tracking: float) -> float:
    """Draw `text` letter by letter with extra spacing; returns the right edge."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + tracking
    return x - tracking


def _ellipsize(d: ImageDraw.ImageDraw, text: str, font, max_w: float) -> str:
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "...", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "..."


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_w: float, max_lines: int) -> list:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if line and d.textlength(trial, font=font) > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(d, lines[-1] + " ...", font, max_w)
    return [_ellipsize(d, ln, font, max_w) for ln in lines]


def _fit(d: ImageDraw.ImageDraw, text: str, name: str, max_w: float, start: int, minimum: int):
    size = start
    while size > minimum:
        f = _font(name, size)
        if d.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return _font(name, minimum)


def render_card(spec: "sc.CardSpec") -> bytes:
    """The 1200x630 PNG for a spec."""
    W, H = sc.CARD_W, sc.CARD_H
    card = Image.new("RGBA", (W, H), GROUND + (255,))
    top_bg = _rgb(sc.BACKGROUNDS[spec.look["bg"]][0])
    glow = Image.radial_gradient("L").resize((900, 900))
    glow = glow.point(lambda v: int(max(0.0, 255 - v * 255 / 180.0) * 0.30))     # 180: the gradient's value at the edge
    layer = Image.new("RGBA", (900, 900), top_bg + (0,))
    layer.putalpha(glow)
    card.alpha_composite(layer, (-250, -180))

    tile_px, tx, ty = 480, 56, 50
    shadow = Image.new("RGBA", (tile_px + 60, tile_px + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([30, 36, tile_px + 30, tile_px + 36], radius=int(26 / 120 * tile_px), fill=(0, 0, 0, 120))
    card.alpha_composite(shadow, (tx - 30, ty - 30))
    card.alpha_composite(draw_hound(spec.look, spec.breed, tile_px), (tx, ty))

    d = ImageDraw.Draw(card)
    x0, right = 566, W - 56
    width = right - x0
    _tracked(d, (x0, 50), sc.WORDMARK, _font(DISPLAY_BOLD, 38), ACCENT, 7)
    d.line([(x0, 100), (x0 + 56, 100)], fill=ACCENT, width=4)
    kfont = _font(BODY, 24)
    d.text((x0, 116), _ellipsize(d, spec.kennel.upper(), kfont, width), font=kfont, fill=MUTE)
    nfont = _fit(d, spec.name, DISPLAY_BOLD, width, 128, 64)
    nm = _ellipsize(d, spec.name, nfont, width)
    d.text((x0, 140), nm, font=nfont, fill=TEXT)
    y = 140 + nfont.size + 14
    tfont = _font(BODY, 29)
    for line in _wrap(d, spec.tagline, tfont, width, 2):
        d.text((x0, y), line, font=tfont, fill=SOFT)
        y += 40
    # sports chips
    cx, cy = x0, 330
    chip_font = _font(DISPLAY_SEMI, 26)
    for sport in spec.sports:
        tw = d.textlength(sport, font=chip_font)
        d.rounded_rectangle([cx, cy, cx + tw + 32, cy + 40], radius=8, fill=(30, 34, 41), outline=(58, 64, 76), width=1)
        d.text((cx + 16, cy + 4), sport, font=chip_font, fill=SOFT)
        cx += tw + 46
    if spec.generic:
        d.text((x0, 404), sc.GENERIC_LINE, font=_fit(d, sc.GENERIC_LINE, DISPLAY_BOLD, width, 54, 30), fill=TEXT)
    else:
        lab, val = _font(BODY, 20), _font(DISPLAY_BOLD, 84)
        if spec.record is not None:
            _tracked(d, (x0, 404), "RECORD", lab, MUTE, 3)
            d.text((x0, 424), spec.record, font=val, fill=TEXT)
        if spec.bankroll is not None:
            bx = x0 + 250
            _tracked(d, (bx, 404), "PAPER BANKROLL", lab, MUTE, 3)
            d.text((bx, 424), spec.bankroll, font=val, fill=TEXT)
            right_edge = bx + d.textlength(spec.bankroll, font=val) + 16
            d.text((right_edge, 478), f"start {spec.start}", font=_font(BODY, 24), fill=MUTE)
        if spec.ranked_note:
            d.text((x0, 528), spec.ranked_note, font=_font(BODY, 24), fill=MUTE)
    d.line([(56, 574), (W - 56, 574)], fill=(38, 42, 50), width=1)
    ffont = _font(BODY, 23)
    parts = [p.strip() for p in sc.FOOTER.split("·")]
    gap = 30
    total = sum(d.textlength(p, font=ffont) for p in parts) + gap * (len(parts) - 1)
    fx = (W - total) / 2
    for i, part in enumerate(parts):
        d.text((fx, 603), part, font=ffont, fill=MUTE, anchor="lm")
        fx += d.textlength(part, font=ffont)
        if i < len(parts) - 1:
            d.ellipse([fx + gap / 2 - 2, 601, fx + gap / 2 + 2, 605], fill=MUTE)
            fx += gap

    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
