/**
 * THE BREED SILHOUETTES. 25 drawings of a dog's head that differ where a breed differs: ears (pointed, floppy, folded, rose,
 * puffs), snout length, head shape, markings (blaze, mask, spots, patch, tan points), and the extras that make it that dog
 * (a beard, a ruff, wrinkles, a topknot, feathering). dog-rig.js picks the breed (name, then vibe, then a hash of the id)
 * and draws everything else (eyes, mouth, brows, accessories, poses) from the `geo` landmarks each breed returns.
 *
 * A builder takes the coat colours and returns:
 *   geo    landmarks the face and the accessories hang from (eye height and spread, nose and mouth height, brow line, head top)
 *   back   behind the head: the ears
 *   head   the skull, the muzzle, the markings
 *   front  over the face, under the eyes: beards, brows, wrinkles
 *   coat   (optional) the coat the BODY should wear when the breed is always white (dalmatian, jack russell, pointer)
 * Every colour is a hex from dog-look.js's tables, the shared whites and tans below, or a mix of two of them. No look value ever
 * reaches a string here. Built with createElementNS only (hounds-core's `s`), so the node tests can run it.
 */

import { s } from "./hounds-core.js";

const WHITE = "#F4F2EC";
const TAN = "#C48A4E";
const INK = "#12151A";
const PINK = "#E9A3A3";

export function mix(a, b, t) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `#${pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("")}`;
}

const n = (tag, attrs, kids) => s(tag, attrs || {}, kids || []);
const path = (d, attrs) => n("path", Object.assign({ d }, attrs || {}));
const ell = (cx, cy, rx, ry, fill, extra) => n("ellipse", Object.assign({ cx, cy, rx, ry, fill }, extra || {}));
const num = (v) => Math.round(v * 10) / 10;

/** Mirror a path made of absolute commands (M L C Q Z) across the centre line, x -> 120 - x. */
export function mir(d) {
  return d.replace(/(-?\d*\.?\d+)[ ,](-?\d*\.?\d+)/g, (_m, x, y) => `${num(120 - Number(x))} ${y}`);
}

/** The landmarks, with the defaults of an ordinary medium dog. */
const G = (o) => Object.assign({ ey: 56, edx: 14, er: 5.2, ny: 67, nrx: 6.2, nry: 4.4, my: 77, topY: 24, browY: 49, hw: 34, lid: null }, o);

/** A symmetric head outline. hw: widest half-width at `cheek`; jaw: how wide the chin curve stays (small is pointed). */
export function skull({ top = 24, hw = 34, cheek = 58, chin = 90, jaw = hw * 0.8, a = hw * 0.62 }) {
  const y1 = num(top + (cheek - top) * 0.42), y2 = num(cheek + (chin - cheek) * 0.55);
  return `M60 ${top} C${num(60 + a)} ${top} ${60 + hw} ${y1} ${60 + hw} ${cheek} C${60 + hw} ${y2} ${num(60 + jaw)} ${chin} 60 ${chin} `
    + `C${num(60 - jaw)} ${chin} ${60 - hw} ${y2} ${60 - hw} ${cheek} C${60 - hw} ${y1} ${num(60 - a)} ${top} 60 ${top} Z`;
}

const sheen = (c, hw, top) => ell(num(60 - hw * 0.5), top + 17, hw * 0.3, 11, c.light, { opacity: ".2", transform: `rotate(-28 ${num(60 - hw * 0.5)} ${top + 17})` });
const inside = (c) => mix(c.shade, PINK, 0.4);

/** A pair of ears from the left one's outline (the right is its mirror). `d2` is an optional inner shape. */
function ears(d, fill, d2, fill2) {
  const one = (side, dd, dd2) => n("g", { class: `dk-ear dk-ear--${side}` }, [path(dd, { fill }), dd2 ? path(dd2, { fill: fill2 }) : null]);
  return [one("l", d, d2), one("r", mir(d), d2 ? mir(d2) : null)];
}

/** A pair of pointed ears: left ear is the triangle A (at the head), B (outer base), T (tip); the inside is the same triangle shrunk. */
function pointed(A, B, T, fill, fill2, round = 2.6) {
  const tri = (p, q, r) => `M${p[0]} ${p[1]} L${q[0]} ${q[1]} L${r[0]} ${r[1]} Z`;
  const cx = (A[0] + B[0] + T[0]) / 3, cy = (A[1] + B[1] + T[1]) / 3;
  const sh = (p, k) => [num(cx + (p[0] - cx) * k), num(cy + (p[1] - cy) * k + 3)];
  const stroke = { "stroke-linejoin": "round", "stroke-width": round };
  const one = (side, fl) => {
    const m = (p) => (fl ? [120 - p[0], p[1]] : p);
    return n("g", { class: `dk-ear dk-ear--${side}` }, [
      path(tri(m(A), m(B), m(T)), Object.assign({ fill, stroke: fill }, stroke)),
      path(tri(m(sh(A, 0.5)), m(sh(B, 0.55)), m(sh(T, 0.62))), { fill: fill2 }),
    ]);
  };
  return [one("l", false), one("r", true)];
}

const BREED = {
  // ---- the retrievers and the labs: friendly, medium everything -------------------------------------------------
  retriever(c) {
    return {
      geo: G({}),
      back: ears("M35 33 C20 34 13 56 19 79 C23 83 24 79 27 84 C31 86 38 70 40 48 Z", c.shade),
      head: [
        path(skull({ top: 24, hw: 34, cheek: 56, chin: 90, jaw: 28 }), { fill: c.base }),
        sheen(c, 34, 24),
        path("M60 24 C64 30 64 38 60 46 C56 38 56 30 60 24 Z", { fill: c.light, opacity: ".28" }),
        ell(60, 75, 17, 13, c.light),
        path("M40 28 C48 22 56 22 60 24 C54 26 46 30 40 28 Z", { fill: c.light, opacity: ".5" }),
      ],
      front: [],
    };
  },
  labrador(c) {
    return {
      geo: G({ ey: 55, edx: 15, er: 5, ny: 66, nrx: 7.2, nry: 4.8, my: 77, topY: 25, hw: 36 }),
      back: ears("M37 32 C25 32 19 46 23 63 C31 67 39 56 41 43 Z", c.shade),
      head: [
        path(skull({ top: 25, hw: 36, cheek: 57, chin: 90, jaw: 30, a: 22 }), { fill: c.base }),
        sheen(c, 36, 25),
        n("rect", { x: 40, y: 62, width: 40, height: 28, rx: 14, fill: c.light }),
        path("M50 27 Q60 31 70 27", { stroke: c.shade, "stroke-width": 1.6, fill: "none", "stroke-linecap": "round", opacity: ".45" }),
      ],
      front: [],
    };
  },
  // ---- the short faces ----------------------------------------------------------------------------------------
  bulldog(c) {
    return {
      geo: G({ ey: 56, edx: 18, er: 5, ny: 66, nrx: 8.5, nry: 5.2, my: 79, topY: 27, browY: 50, hw: 40 }),
      back: ears("M38 33 C27 24 17 29 19 43 C26 49 36 45 42 40 Z", c.shade, "M37 34 C29 29 23 32 24 40 C28 42 34 40 38 38 Z", inside(c)),
      head: [
        path(skull({ top: 27, hw: 41, cheek: 62, chin: 90, jaw: 36, a: 28 }), { fill: c.base }),
        sheen(c, 41, 27),
        path("M44 37 Q60 31 76 37", { stroke: c.shade, "stroke-width": 2, fill: "none", "stroke-linecap": "round", opacity: ".5" }),
        path("M47 42 Q60 38 73 42", { stroke: c.shade, "stroke-width": 1.5, fill: "none", "stroke-linecap": "round", opacity: ".4" }),
        n("rect", { x: 36, y: 64, width: 48, height: 26, rx: 13, fill: c.light }),
        path("M34 78 C30 90 40 96 48 92 M86 78 C90 90 80 96 72 92", { stroke: c.shade, "stroke-width": 2.2, fill: "none", "stroke-linecap": "round", opacity: ".55" }),
        path("M48 88 Q60 94 72 88", { stroke: c.shade, "stroke-width": 1.8, fill: "none", "stroke-linecap": "round", opacity: ".55" }),
      ],
      front: [],
    };
  },
  newfoundland(c) {
    const dark = mix(c.base, "#0B0C0E", 0.25);
    return {
      geo: G({ ey: 55, edx: 17, er: 4.6, ny: 68, nrx: 8.4, nry: 5.4, my: 80, topY: 20, browY: 47, hw: 42 }),
      back: ears("M36 28 C20 24 12 44 17 64 C26 66 38 54 41 40 Z", dark),
      head: [
        path(skull({ top: 20, hw: 43, cheek: 58, chin: 94, jaw: 36, a: 30 }), { fill: dark }),
        sheen(c, 43, 20),
        n("rect", { x: 38, y: 62, width: 44, height: 32, rx: 16, fill: mix(c.light, c.base, 0.35) }),
        path("M36 40 C42 34 52 36 56 41 M84 40 C78 34 68 36 64 41", { stroke: mix(dark, "#0B0C0E", 0.4), "stroke-width": 3.4, fill: "none", "stroke-linecap": "round" }),
        path("M40 86 C44 98 56 100 60 94 C64 100 76 98 80 86", { stroke: c.shade, "stroke-width": 1.8, fill: "none", "stroke-linecap": "round", opacity: ".5" }),
      ],
      front: [],
    };
  },
  // ---- the herders and the sharp-eared ----------------------------------------------------------------------
  chihuahua(c) {
    return {
      geo: G({ ey: 58, edx: 15, er: 6.4, ny: 71, nrx: 5, nry: 3.6, my: 80, topY: 29, browY: 51, hw: 32 }),
      back: pointed([42, 44], [14, 40], [4, 8], c.shade, inside(c), 3),
      head: [
        path(skull({ top: 29, hw: 33, cheek: 58, chin: 89, jaw: 24, a: 26 }), { fill: c.base }),
        sheen(c, 33, 29),
        ell(60, 74, 11, 9, c.light),
        path("M54 31 Q60 36 66 31", { stroke: c.light, "stroke-width": 3, fill: "none", "stroke-linecap": "round", opacity: ".4" }),
      ],
      front: [],
    };
  },
  corgi(c) {
    return {
      geo: G({ ey: 56, edx: 15, er: 4.8, ny: 68, nrx: 6, nry: 4.2, my: 79, topY: 28, browY: 50, hw: 36 }),
      back: pointed([44, 44], [22, 44], [20, 4], c.base, WHITE, 3.4),
      head: [
        path(skull({ top: 28, hw: 37, cheek: 60, chin: 90, jaw: 26, a: 28 }), { fill: c.base }),
        path("M60 30 C68 40 70 56 78 68 C84 76 82 90 60 90 C38 90 36 76 42 68 C50 56 52 40 60 30 Z", { fill: WHITE }),
        n("rect", { x: 46, y: 64, width: 28, height: 24, rx: 12, fill: WHITE }),
        sheen(c, 37, 28),
      ],
      front: [],
    };
  },
  collie(c) {
    return {
      geo: G({ ey: 54, edx: 12, er: 4.6, ny: 78, nrx: 5.4, nry: 4, my: 88, topY: 24, browY: 47, hw: 28 }),
      back: [
        // the ruff behind the head
        path("M18 84 C12 96 22 108 34 104 C40 112 52 112 60 108 C68 112 80 112 86 104 C98 108 108 96 102 84 C90 94 30 94 18 84 Z", { fill: WHITE }),
        ...ears("M38 46 L30 12 C38 8 46 16 50 26 C46 28 46 36 48 44 Z", c.shade, "M40 42 L35 18 C40 18 44 24 46 32 Z", inside(c)),
      ],
      head: [
        path(skull({ top: 24, hw: 29, cheek: 56, chin: 98, jaw: 8, a: 20 }), { fill: c.base }),
        sheen(c, 29, 24),
        path("M60 26 C66 40 64 56 68 68 C72 78 70 92 60 98 C50 92 48 78 52 68 C56 56 54 40 60 26 Z", { fill: WHITE }),
        path("M44 74 C48 70 52 78 60 78 C68 78 72 70 76 74 C72 92 64 98 60 98 C56 98 48 92 44 74 Z", { fill: WHITE }),
      ],
      front: [],
    };
  },
  shepherd(c) {
    const mask = mix(c.shade, "#0B0C0E", 0.5);
    return {
      geo: G({ ey: 54, edx: 14, er: 4.7, ny: 74, nrx: 6, nry: 4.2, my: 85, topY: 22, browY: 47, hw: 31, lid: [mask, mask] }),
      back: pointed([46, 44], [28, 46], [20, 0], mask, inside(c), 3),
      head: [
        path(skull({ top: 22, hw: 32, cheek: 54, chin: 96, jaw: 12, a: 22 }), { fill: c.base }),
        sheen(c, 32, 22),
        path("M52 24 C60 34 60 40 60 50 C60 40 60 34 68 24 C64 22 56 22 52 24 Z", { fill: mask }),
        path("M46 70 C50 60 70 60 74 70 C76 86 68 98 60 98 C52 98 44 86 46 70 Z", { fill: mask }),
        path("M50 66 C56 60 64 60 70 66 C66 70 54 70 50 66 Z", { fill: c.light, opacity: ".55" }),
      ],
      front: [],
    };
  },
  kelpie(c) {
    const tan = mix(TAN, c.base, 0.1);
    const black = mix(c.base, "#14171B", 0.35);
    return {
      geo: G({ ey: 55, edx: 13.5, er: 4.9, ny: 71, nrx: 5.6, nry: 4, my: 82, topY: 24, browY: 48, hw: 31 }),
      back: pointed([46, 44], [24, 44], [24, 2], black, inside(c), 3),
      head: [
        path(skull({ top: 24, hw: 32, cheek: 56, chin: 93, jaw: 14, a: 22 }), { fill: black }),
        sheen(c, 32, 24),
        path("M34 52 C38 46 44 48 48 54 C44 58 38 58 34 52 Z M86 52 C82 46 76 48 72 54 C76 58 82 58 86 52 Z", { fill: tan }),
        path("M40 66 C44 60 76 60 80 66 C82 82 72 93 60 93 C48 93 38 82 40 66 Z", { fill: tan }),
        path("M44 80 C50 76 56 82 60 82 C64 82 70 76 76 80 C72 90 66 93 60 93 C54 93 48 90 44 80 Z", { fill: mix(tan, WHITE, 0.4) }),
      ],
      front: [],
    };
  },
  husky(c) {
    const mask = mix(c.shade, c.base, 0.25);
    return {
      geo: G({ ey: 56, edx: 14, er: 5.2, ny: 68, nrx: 5.6, nry: 4.2, my: 78, topY: 28, browY: 50, hw: 32, lid: [mask, mask] }),
      back: pointed([42, 38], [28, 46], [26, 10], c.shade, mix(c.light, PINK, 0.3), 2.6),
      head: [
        path(skull({ top: 28, hw: 33, cheek: 58, chin: 91, jaw: 24, a: 22 }), { fill: c.light }),
        path("M60 28 C80 28 93 40 93 55 C82 53 72 58 60 72 C48 58 38 53 27 55 C27 40 40 28 60 28 Z", { fill: mask }),
        path("M52 29 L60 52 L68 29 Z", { fill: c.light, opacity: ".9" }),
        path("M31 36 L30 22 L45 31 Z", { fill: c.light, opacity: ".85" }),
        path("M89 36 L90 22 L75 31 Z", { fill: c.light, opacity: ".85" }),
        ell(60, 75, 15, 12, mix(c.light, "#FFFFFF", 0.4)),
      ],
      front: [],
    };
  },
  // ---- the small and bright ------------------------------------------------------------------------------------
  jackrussell(c) {
    const patch = mix(c.base, "#000000", 0.05);
    const white = { base: WHITE, shade: "#CFCBC2", light: "#FFFFFF" };
    return {
      coat: white,
      geo: G({ ey: 56, edx: 14, er: 5, ny: 68, nrx: 5.4, nry: 4, my: 78, topY: 26, browY: 49, hw: 31 }),
      back: ears("M38 30 L22 33 C18 44 22 54 31 54 C40 51 44 43 44 36 Z", patch),
      head: [
        path(skull({ top: 26, hw: 32, cheek: 57, chin: 90, jaw: 22, a: 24 }), { fill: WHITE }),
        path("M60 26 C74 26 88 36 88 50 C80 48 72 44 70 36 C66 44 60 50 54 48 C50 40 56 30 60 26 Z", { fill: patch }),
        ell(76, 53, 11, 11, patch),
        path("M60 28 C63 36 62 46 60 56 C58 46 57 36 60 28 Z", { fill: WHITE }),
        ell(60, 74, 14, 11, WHITE),
      ],
      front: [],
    };
  },
  // ---- the spotted and the patched ----------------------------------------------------------------------------
  dalmatian(c) {
    const spot = mix(c.shade, "#0B0C0E", 0.55);
    const white = { base: "#F2F1EC", shade: "#CFCBC2", light: "#FFFFFF" };
    return {
      coat: white,
      geo: G({ ey: 55, edx: 14, er: 4.9, ny: 69, nrx: 6.2, nry: 4.4, my: 80, topY: 24, browY: 49, hw: 31 }),
      back: ears("M37 30 C25 30 18 46 22 62 C30 66 38 56 41 43 Z", "#F2F1EC", "M30 36 C24 40 22 50 25 58 C31 58 36 52 38 44 Z", spot),
      head: [
        path(skull({ top: 24, hw: 32, cheek: 57, chin: 92, jaw: 20, a: 24 }), { fill: "#F2F1EC" }),
        ell(40, 38, 4.5, 4, spot), ell(72, 33, 3.4, 3.2, spot), ell(80, 50, 5.4, 4.4, spot), ell(35, 56, 3.2, 3, spot),
        ell(54, 38, 2.4, 2.2, spot), ell(84, 66, 3, 2.8, spot), ell(38, 70, 3.4, 3, spot), ell(66, 84, 2.2, 2, spot),
        ell(60, 76, 14, 12, "#FFFFFF"),
      ],
      front: [],
    };
  },
  pointer(c) {
    const patch = mix(c.base, "#2A1A12", 0.2);
    const white = { base: WHITE, shade: "#CFCBC2", light: "#FFFFFF" };
    return {
      coat: white,
      geo: G({ ey: 55, edx: 13, er: 4.8, ny: 73, nrx: 6.4, nry: 4.4, my: 85, topY: 24, browY: 48, hw: 29 }),
      back: ears("M38 28 C26 26 20 42 23 62 C30 66 39 56 41 42 Z", patch),
      head: [
        path(skull({ top: 24, hw: 30, cheek: 56, chin: 96, jaw: 14, a: 22 }), { fill: WHITE }),
        path("M60 24 C74 24 84 32 86 44 C78 44 72 40 68 34 C64 42 60 44 56 40 C52 30 56 26 60 24 Z", { fill: patch }),
        ell(40, 46, 6, 8, patch),
        path("M60 28 C62 44 62 58 61 70 C59 58 58 44 60 28 Z", { fill: "#E8E4DA" }),
        n("rect", { x: 47, y: 62, width: 26, height: 34, rx: 13, fill: "#FFFFFF" }),
      ],
      front: [],
    };
  },
  beagle(c) {
    const ear = mix(c.shade, "#2A1A12", 0.3);
    return {
      geo: G({ ey: 56, edx: 14, er: 5.4, ny: 69, nrx: 6.4, nry: 4.6, my: 80, topY: 25, browY: 49, hw: 33 }),
      back: ears("M38 28 C14 26 8 58 18 80 C30 86 42 66 42 44 Z", ear),
      head: [
        path(skull({ top: 25, hw: 34, cheek: 57, chin: 91, jaw: 24, a: 24 }), { fill: c.base }),
        sheen(c, 34, 25),
        path("M60 25 C66 32 66 46 66 60 C66 72 72 80 76 88 C70 94 50 94 44 88 C48 80 54 72 54 60 C54 46 54 32 60 25 Z", { fill: WHITE }),
        n("rect", { x: 44, y: 66, width: 32, height: 26, rx: 13, fill: WHITE }),
      ],
      front: [],
    };
  },
  // ---- the droopers ---------------------------------------------------------------------------------------------
  basset(c) {
    const ear = mix(c.shade, "#2A1A12", 0.2);
    return {
      geo: G({ ey: 56, edx: 14, er: 4.8, ny: 71, nrx: 7, nry: 5, my: 83, topY: 24, browY: 49, hw: 33 }),
      back: ears("M38 34 C16 40 8 76 14 108 C26 114 42 86 44 50 Z", ear),
      head: [
        path(skull({ top: 24, hw: 33, cheek: 58, chin: 96, jaw: 20, a: 24 }), { fill: c.base }),
        sheen(c, 33, 24),
        path("M42 40 Q60 34 78 40 M46 46 Q60 42 74 46", { stroke: c.shade, "stroke-width": 1.5, fill: "none", "stroke-linecap": "round", opacity: ".45" }),
        n("rect", { x: 42, y: 66, width: 36, height: 30, rx: 15, fill: c.light }),
        path("M40 84 C38 96 48 100 54 96 M80 84 C82 96 72 100 66 96", { stroke: c.shade, "stroke-width": 2.2, fill: "none", "stroke-linecap": "round", opacity: ".55" }),
        path("M36 63 Q44 70 52 62 M84 63 Q76 70 68 62", { stroke: mix(c.shade, "#8A3A29", 0.5), "stroke-width": 2.4, fill: "none", "stroke-linecap": "round", opacity: ".6" }),
      ],
      front: [],
    };
  },
  bloodhound(c) {
    const ear = mix(c.shade, "#0B0C0E", 0.35);
    return {
      geo: G({ ey: 56, edx: 14, er: 4.6, ny: 72, nrx: 7.4, nry: 5.2, my: 85, topY: 22, browY: 48, hw: 33 }),
      back: ears("M38 32 C10 38 2 80 8 112 C22 118 42 90 44 50 Z", ear),
      head: [
        path(skull({ top: 22, hw: 33, cheek: 58, chin: 98, jaw: 22, a: 24 }), { fill: c.base }),
        sheen(c, 33, 22),
        path("M40 36 Q60 28 80 36 M42 42 Q60 35 78 42 M46 48 Q60 42 74 48", { stroke: c.shade, "stroke-width": 1.5, fill: "none", "stroke-linecap": "round", opacity: ".5" }),
        n("rect", { x: 40, y: 66, width: 40, height: 32, rx: 16, fill: mix(TAN, c.light, 0.35) }),
        path("M38 86 C36 100 48 102 54 98 M82 86 C84 100 72 102 66 98", { stroke: c.shade, "stroke-width": 2.4, fill: "none", "stroke-linecap": "round", opacity: ".6" }),
        path("M36 64 Q44 72 52 63 M84 64 Q76 72 68 63", { stroke: mix(c.shade, "#8A3A29", 0.5), "stroke-width": 2.6, fill: "none", "stroke-linecap": "round", opacity: ".65" }),
      ],
      front: [],
    };
  },
  hound(c) {
    const ear = mix(c.shade, "#0B0C0E", 0.25);
    return {
      geo: G({ ey: 55, edx: 14, er: 5, ny: 71, nrx: 6.4, nry: 4.6, my: 83, topY: 24, browY: 49, hw: 31 }),
      back: ears("M37 30 C18 38 13 72 18 101 C28 104 40 76 42 46 Z", ear),
      head: [
        path(skull({ top: 24, hw: 31, cheek: 56, chin: 94, jaw: 20, a: 22 }), { fill: c.base }),
        sheen(c, 31, 24),
        path("M60 25 C65 34 65 46 64 58 C64 68 70 76 74 86 C68 94 52 94 46 86 C50 76 56 68 56 58 C55 46 55 34 60 25 Z", { fill: mix(c.light, WHITE, 0.5), opacity: ".8" }),
        n("rect", { x: 45, y: 66, width: 30, height: 28, rx: 14, fill: c.light }),
      ],
      front: [],
    };
  },
  // ---- the slim ------------------------------------------------------------------------------------------------
  greyhound(c) {
    return {
      geo: G({ ey: 53, edx: 11.5, er: 4.4, ny: 80, nrx: 5.2, nry: 3.8, my: 90, topY: 22, browY: 46, hw: 25 }),
      back: ears("M43 33 C35 26 27 30 27 40 C29 47 37 47 44 42 Z", c.shade, "M40 35 C35 31 31 33 31 39 C33 43 37 43 41 40 Z", inside(c)),
      head: [
        path(skull({ top: 22, hw: 26, cheek: 52, chin: 100, jaw: 7, a: 18 }), { fill: c.base }),
        sheen(c, 26, 22),
        path("M60 24 C63 40 63 58 62 74 C61 86 62 94 60 100 C58 94 59 86 58 74 C57 58 57 40 60 24 Z", { fill: c.light, opacity: ".35" }),
        n("rect", { x: 52, y: 72, width: 16, height: 28, rx: 8, fill: c.light }),
      ],
      front: [],
    };
  },
  whippet(c) {
    return {
      geo: G({ ey: 54, edx: 12.5, er: 5.2, ny: 77, nrx: 5.4, nry: 3.8, my: 87, topY: 22, browY: 47, hw: 27 }),
      back: ears("M43 30 C34 24 24 22 17 29 C22 41 34 47 44 41 Z", c.shade, "M40 32 C34 28 27 27 22 31 C27 38 34 41 40 39 Z", inside(c)),
      head: [
        path(skull({ top: 22, hw: 28, cheek: 54, chin: 96, jaw: 11, a: 20 }), { fill: c.base }),
        sheen(c, 28, 22),
        n("rect", { x: 49, y: 66, width: 22, height: 28, rx: 11, fill: c.light }),
      ],
      front: [],
    };
  },
  // ---- the feathered and the fluffed ---------------------------------------------------------------------------
  setter(c) {
    const fringe = mix(c.base, c.shade, 0.5);
    return {
      geo: G({ ey: 55, edx: 13.5, er: 4.9, ny: 73, nrx: 6, nry: 4.4, my: 85, topY: 24, browY: 49, hw: 30 }),
      back: ears("M38 28 C14 34 8 72 12 98 C16 106 18 98 21 106 C25 112 27 102 31 108 C37 100 42 76 43 46 Z", fringe),
      head: [
        path(skull({ top: 24, hw: 30, cheek: 56, chin: 95, jaw: 14, a: 22 }), { fill: c.base }),
        sheen(c, 30, 24),
        path("M44 28 C48 16 56 12 60 22 C64 12 72 16 76 28 C68 24 52 24 44 28 Z", { fill: c.light, opacity: ".7" }),
        n("rect", { x: 47, y: 66, width: 26, height: 30, rx: 13, fill: c.light }),
      ],
      front: [],
    };
  },
  spaniel(c) {
    const fringe = mix(c.base, c.shade, 0.55);
    return {
      geo: G({ ey: 57, edx: 14.5, er: 5.6, ny: 68, nrx: 6.4, nry: 4.6, my: 78, topY: 22, browY: 50, hw: 34 }),
      back: ears("M38 30 C12 30 4 62 10 92 C14 98 16 91 19 98 C23 102 25 94 29 98 C37 88 42 68 43 46 Z", fringe),
      head: [
        path(skull({ top: 22, hw: 35, cheek: 56, chin: 90, jaw: 26, a: 28 }), { fill: c.base }),
        sheen(c, 35, 22),
        path("M34 30 C34 16 48 10 60 16 C72 10 86 16 86 30 C80 24 70 22 60 26 C50 22 40 24 34 30 Z", { fill: mix(c.base, c.shade, 0.25) }),
        ell(60, 75, 15, 11.5, c.light),
      ],
      front: [],
    };
  },
  poodle(c) {
    const fluff = mix(c.base, c.light, 0.15);
    const puff = (cx, cy, r) => ell(cx, cy, r, r * 0.9, fluff);
    return {
      geo: G({ ey: 57, edx: 13, er: 4.9, ny: 74, nrx: 5.4, nry: 4, my: 85, topY: 30, browY: 51, hw: 28 }),
      back: [
        n("g", { class: "dk-ear dk-ear--l" }, [puff(20, 62, 13), puff(18, 80, 12), puff(24, 96, 11)]),
        n("g", { class: "dk-ear dk-ear--r" }, [puff(100, 62, 13), puff(102, 80, 12), puff(96, 96, 11)]),
      ],
      head: [
        path(skull({ top: 30, hw: 28, cheek: 58, chin: 95, jaw: 14, a: 22 }), { fill: c.base }),
        sheen(c, 28, 30),
        puff(60, 16, 17), puff(42, 24, 12), puff(78, 24, 12), puff(50, 12, 9), puff(70, 12, 9),
        n("rect", { x: 49, y: 68, width: 22, height: 28, rx: 11, fill: c.light }),
      ],
      front: [],
    };
  },
  // ---- the wiry ------------------------------------------------------------------------------------------------
  terrier(c) {
    const brow = mix(c.light, WHITE, 0.3);
    const dark = mix(c.base, "#3B2A1C", 0.5);
    return {
      geo: G({ ey: 56, edx: 14, er: 4.8, ny: 70, nrx: 6, nry: 4.4, my: 80, topY: 26, browY: 49, hw: 32 }),
      back: ears("M46 32 L18 38 L26 60 C38 58 46 48 48 38 Z", dark),
      head: [
        path(skull({ top: 26, hw: 33, cheek: 56, chin: 91, jaw: 30, a: 28 }), { fill: c.base }),
        sheen(c, 33, 26),
        n("rect", { x: 42, y: 62, width: 36, height: 30, rx: 10, fill: c.light }),
        path("M38 86 L34 92 L41 90 L40 97 L48 93 L52 99 L58 94 L60 99 L62 94 L68 99 L72 93 L80 97 L79 90 L86 92 L82 86 C74 92 46 92 38 86 Z", { fill: brow }),
      ],
      front: [
        path("M36 44 C40 38 48 40 54 45 C48 46 42 47 36 44 Z M84 44 C80 38 72 40 66 45 C72 46 78 47 84 44 Z", { fill: brow }),
      ],
    };
  },
  schnauzer(c) {
    const beard = mix(c.light, "#FFFFFF", 0.25);
    return {
      geo: G({ ey: 55, edx: 15, er: 4.9, ny: 65, nrx: 6.6, nry: 4.6, my: 78, topY: 25, browY: 49, hw: 32 }),
      back: ears("M36 29 L17 41 C23 56 40 52 46 36 Z", c.shade),
      head: [
        path("M60 25 C82 25 93 35 93 52 L93 72 C93 85 79 93 60 93 C41 93 27 85 27 72 L27 52 C27 35 38 25 60 25 Z", { fill: c.base }),
        sheen(c, 32, 25),
        path("M34 68 C36 98 84 98 86 68 C76 82 44 82 34 68 Z", { fill: beard }),
        ell(60, 72, 15, 11, beard),
      ],
      front: [
        path("M30 45 C36 36 48 36 56 44 C48 45 40 47 30 45 Z", { fill: beard }),
        path("M90 45 C84 36 72 36 64 44 C72 45 80 47 90 45 Z", { fill: beard }),
      ],
    };
  },
  mutt(c) {
    const patch = mix(c.shade, "#0B0C0E", 0.15);
    return {
      geo: G({ ey: 56, edx: 14, er: 5.4, ny: 67, nrx: 6.2, nry: 4.4, my: 77, lid: [c.base, patch] }),
      back: [
        n("g", { class: "dk-ear dk-ear--l" }, [path("M36 40 L28 9 L57 29 Z", { fill: c.shade, stroke: c.shade, "stroke-width": 2.6, "stroke-linejoin": "round" }), path("M37 36 L32 17 L50 30 Z", { fill: inside(c) })]),
        n("g", { class: "dk-ear dk-ear--r" }, [path("M84 33 C99 38 103 60 96 78 C87 80 80 64 79 46 Z", { fill: c.shade })]),
      ],
      head: [
        path("M60 25 C82 24 95 38 94 58 C93 78 80 90 60 90 C40 90 27 78 26 58 C25 38 38 26 60 25 Z", { fill: c.base }),
        ell(75, 54, 12.5, 12, patch),
        sheen(c, 34, 25),
        ell(60, 74, 16.5, 12.5, c.light),
      ],
      front: [],
    };
  },
};

export const BREEDS = Object.keys(BREED);

/** The shown name of each breed (the drawing key is not always the shown name). */
export const BREED_LABELS = {
  retriever: "Golden Retriever", labrador: "Labrador", bulldog: "Bulldog", schnauzer: "Schnauzer", husky: "Husky", mutt: "Mutt",
  hound: "Hound", chihuahua: "Chihuahua", collie: "Collie", corgi: "Corgi", dalmatian: "Dalmatian", basset: "Basset Hound",
  greyhound: "Greyhound", jackrussell: "Jack Russell", kelpie: "Kelpie", newfoundland: "Newfoundland", shepherd: "German Shepherd",
  poodle: "Poodle", beagle: "Beagle", setter: "Setter", terrier: "Terrier", bloodhound: "Bloodhound", pointer: "Pointer",
  whippet: "Whippet", spaniel: "Spaniel",
};

/** Build one breed's pieces for a coat. Unknown breeds are a retriever. */
export function buildBreed(name, coat) {
  return (BREED[name] || BREED.retriever)(coat);
}
