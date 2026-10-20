/**
 * THE BREED HEADS. 33 hound and working-breed heads, drawn as front-facing mascot illustrations that differ where a breed
 * differs: the skull (a Rottweiler's block, a Greyhound's wedge), the muzzle (a Bulldog's slab, a Doberman's blade), the ears
 * (cropped, rose, drop, long, pricked), the markings (tan points, a mask, a blaze, spots, a saddle) and the extras that make it that dog
 * (wrinkles, a beard, brow tufts, a ruff, jowls, a scar). dog-rig.js picks the breed (the look's override, then the name, then the
 * persona vibe, then a hash of the id) and draws the face, the accessories and the poses from the `geo` landmarks each breed returns.
 *
 * A builder takes the coat colours and the toolkit (dog-art.js makeKit: the style's outline and shading, the level of detail)
 * and returns:
 *   geo    landmarks the face and the accessories hang from: eye height, spread and size, nose and mouth height, brow line, head top,
 *          chin, how wide the neck is and how bulky the body
 *   back   behind the head: the ears
 *   head   the skull, the muzzle, the markings
 *   front  over the face, under the eyes: wrinkles, brow tufts, a scar
 *   coat   (optional) the coat the BODY should wear when the breed is always white or spotted (Dalmatian, Jack Russell, Pointer)
 * Every colour is a hex from dog-look.js's tables, the shared whites and tans below, or a mix of two of them. No look value ever
 * reaches a string here. Built with createElementNS only (hounds-core's `s`), so the node tests can run it.
 *
 * `anchorsOf(geo)` turns the landmarks into the named anchors every accessory (cap, headband, visor, sunglasses, bandana, collar,
 * chain, hoodie, jersey) is placed from, so each one lines up on every breed's head. A test holds every breed to having them.
 */

import { BREED_IDS } from "./dog-look.js";
import { INK, mix, lum, n, path, ell, symLoop, symArc, spline, splineOpen, mirrorPts, earPair, f } from "./dog-art.js";

export { mix };

const HEAD_SCALE = 0.9;
const HEAD_BASE = 95;
const WHITE = "#F4F2EC";
const CREAM = "#EFE6D2";
const TAN = "#C8823F";
const PINK = "#D98A92";

/** The landmarks, with the defaults of an ordinary medium dog. */
const G = (o) => Object.assign({
  ey: 54, edx: 15, ew: 6.4, eh: 3.4, tilt: 1.5, ny: 71, nrx: 7, nry: 4.6, my: 82, mw: 12.5,
  topY: 21, browY: 45, hw: 34, chin: 96, neck: 25, bulk: 1,
}, o);

/** Half-outlines (offset from the centre line, y) for the cranium and the muzzle, from a few numbers. */
const cranHalf = ({ top = 21, crown = 22, hw = 34, cheek = 58, jaw = 22, end = 90 } = {}) => [
  [0, top], [Math.min(crown, hw * 0.5), top + 0.4], [hw * 0.82, top + 6.5], [hw, cheek - 16], [hw, cheek], [hw * 0.9, cheek + 13], [jaw, cheek + 25], [0, end]];
const muzHalf = ({ top = 46, w0 = 9, w1 = 15, mid = 74, chin = 96 } = {}) => [
  [w0, top], [w0 + (w1 - w0) * 0.45, top + 9], [w1 * 0.96, mid - 8], [w1, mid + 2], [w1 * 0.86, chin - 9], [w1 * 0.45, chin - 1.5], [0, chin]];

/** The colour a breed's "points" take: tan on a dark coat, a rust of the coat's own shade on a light one. */
const pointsOf = (c) => (lum(c.base) < 0.4 ? TAN : mix(c.shade, "#8A4A22", 0.55));
const darkOf = (c) => mix(c.shade, INK, 0.5);
const inside = (c) => mix(c.shade, PINK, 0.45);

/** A pointed ear for the LEFT side from its inner base A, outer base B and tip T, with a little outward bulge on the sides. */
function tri(A, B, T, bulge = 0.08, innerK = 0.56) {
  const cx = (A[0] + B[0] + T[0]) / 3, cy = (A[1] + B[1] + T[1]) / 3;
  const side = (p, q, b) => {
    const mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2;
    const dx = mx - cx, dy = my - cy, len = Math.hypot(dx, dy) || 1, span = Math.hypot(q[0] - p[0], q[1] - p[1]);
    return [mx + (dx / len) * span * b, my + (dy / len) * span * b];
  };
  const pts = [A, side(A, T, bulge), T, side(T, B, bulge), B, side(B, A, 0)];
  const sh = (p) => [cx + (p[0] - cx) * innerK, cy + (p[1] - cy) * innerK + 3];
  return { pts, sharp: [2], inner: [sh(A), sh(side(A, T, bulge)), sh(T), sh(side(T, B, bulge)), sh(B), sh(side(B, A, 0))] };
}

/** A pair of ears from `tri`'s result or a plain outline. */
function earsOf(K, spec, fill, innerFill, extra = {}) {
  return earPair(spec.pts, Object.assign({ sharp: spec.sharp || [], fill, inner: spec.inner || null, innerFill, kit: K }, extra));
}

/** Assemble one breed from its parts (see the header). */
function compose(c, K, o) {
  const cranHalfPts = Array.isArray(o.cran) ? o.cran : cranHalf(o.cran || {});
  const muzHalfPts = Array.isArray(o.muz) ? o.muz : muzHalf(o.muz || {});
  const g = G(Object.assign({ chin: muzHalfPts[muzHalfPts.length - 1][1] }, o.geo || {}));
  g.ew = f(g.ew * 1.2); g.eh = f(g.eh * 1.3);
  const skin = o.skin || c.base;
  const muzFill = o.muzFill || mix(c.base, c.light, 0.55);
  const arc = symArc(muzHalfPts, o.muzSharp || []);
  const live = (list) => (list || []).filter(Boolean);
  let head = [
    ...K.solid(symLoop(cranHalfPts, o.cranSharp || []), skin, { key: true }),
    K.fine(rimLine(K, cranHalfPts)),
    ...live(o.under),
    ...K.solid(arc.closed, muzFill, { ol: false }),
    K.contour(arc.open, 0.45),
    ...live(o.marks),
  ];
  let back = live(o.ears), front = live(o.front), geo = g;
  // every head is drawn at 0.9 about (60, 95) so there is room under it for the body, the jersey number and the neck pieces; a long
  // or tall head (`o.sc`) is smaller still so it keeps its silhouette inside the badge. The landmarks follow the drawing.
  const sc = (o.sc || 1) * HEAD_SCALE, base = o.base === undefined ? HEAD_BASE : o.base;
  {
    const tf = `translate(60 ${base}) scale(${sc}) translate(-60 -100)`;
    const wrap = (list) => (list.length ? [n("g", { transform: tf }, list)] : []);
    head = wrap(head); back = wrap(back); front = wrap(front);
    const Y = (y) => f(base + (y - 100) * sc);
    geo = Object.assign({}, g, {
      ey: Y(g.ey), ny: Y(g.ny), my: Y(g.my), topY: Y(g.topY), browY: Y(g.browY), chin: Y(g.chin),
      ew: f(g.ew * sc), eh: f(g.eh * sc), edx: f(g.edx * sc), nrx: f(g.nrx * sc), nry: f(g.nry * sc), mw: f(g.mw * sc), hw: f(g.hw * sc), tilt: f(g.tilt * sc),
    });
  }
  return { geo, back, head, front, coat: o.coat || null };
}

/** The rim light: a thin bright line just inside the upper-right rim of the skull (the key light is the upper left). */
function rimLine(K, half) {
  const take = half.slice(0, Math.min(5, half.length - 2));
  const pts = take.map(([dx, y]) => [60 + dx - 2.3, y + 2.4]);
  pts[0] = [56, pts[0][1]];
  return path(splineOpen(pts), { class: "dk-rim", fill: "none", stroke: "#FFFFFF", "stroke-width": K.style.id === "elite" ? 1.2 : 1.9, "stroke-linecap": "round", opacity: K.style.id === "elite" ? ".42" : ".6" });
}

// ---- small drawing helpers shared by the breeds ---------------------------------------------------------------

/** A vertical blaze down the face: from the crown to the nose, `w` wide at the forehead. */
function blaze(K, fill, { top = 24, end = 70, w = 5, tip = 6 } = {}) {
  return K.flat(symLoop([[0, top], [w * 0.6, top + 2], [w, top + 14], [w * 0.8, (top + end) / 2], [tip, end - 4], [0, end + 2]]), fill);
}
/** The two tan or rust dots over the eyes. */
function browDots(K, g, fill, r = 2.4) {
  return [ell(60 - g.edx - 0.5, g.ey - 9.6, r + 0.8, r, fill), ell(60 + g.edx + 0.5, g.ey - 9.6, r + 0.8, r, fill)];
}
/** Wrinkle lines (a bulldog's forehead, a bloodhound's brow) as thin curved strokes. */
function wrinkles(K, c, ds, w = 1.5, a = 0.55) {
  return K.fine(n("g", { class: "dk-fine" }, ds.map((d) => K.line(d, mix(c.shade, INK, 0.35), w, { opacity: String(a) }))));
}
/** A scar across the brow: a pale diagonal with two stitch ticks. */
function scar(K, x, y, flip = 1) {
  const x2 = x + 7 * flip, y2 = y + 11;
  return n("g", { class: "dk-scar" }, [
    K.line(`M${f(x)} ${f(y)} L${f(x2)} ${f(y2)}`, "#E9C9C0", 1.7, { opacity: ".9" }),
    K.fine(K.line(`M${f(x + 1.6 * flip)} ${f(y + 3)} l${f(2.4 * flip)} -1 M${f(x + 3.4 * flip)} ${f(y + 6.6)} l${f(2.4 * flip)} -1`, "#E9C9C0", 1, { opacity: ".8" })),
  ]);
}
/** A pair of jowl lines hanging from the muzzle, for the heavy breeds. */
function jowls(K, c, g, w, drop = 14) {
  const ds = [`M${60 - w} ${g.my - 2} C${60 - w - 4} ${g.my + drop * 0.5} ${60 - w + 2} ${g.my + drop} ${60 - w + 9} ${g.my + drop - 1}`,
    `M${60 + w} ${g.my - 2} C${60 + w + 4} ${g.my + drop * 0.5} ${60 + w - 2} ${g.my + drop} ${60 + w - 9} ${g.my + drop - 1}`];
  return ds.map((d) => K.line(d, mix(c.shade, INK, 0.4), 1.8, { opacity: ".6" }));
}
/** Spots for the Dalmatian and its relatives, deterministic. */
function spots(fill, list) {
  return list.map(([x, y, rx, ry]) => ell(x, y, rx, ry || rx * 0.9, fill));
}
/** A jagged tuft outline along a list of points, for beards and ruffs. */
function tuft(pts) { return spline(pts, pts.map((_p, i) => i)); }

const BREED = {
  // ---- the guard and working breeds ------------------------------------------------------------------------------
  doberman(c, K) {
    const pt = pointsOf(c);
    const ear = tri([43, 29], [25, 46], [30, -5], 0.04);
    return compose(c, K, {
      geo: { ey: 53, edx: 14.2, ew: 6, eh: 3.2, tilt: 1.8, ny: 79, nrx: 6.4, nry: 4.1, my: 89, mw: 11, topY: 20, browY: 44, hw: 31, neck: 21 },
      sc: 0.94,
      cran: { top: 20, crown: 20, hw: 29, cheek: 56, jaw: 16, end: 94 }, cranSharp: [3],
      muz: { top: 44, w0: 8, w1: 12.6, mid: 82, chin: 103 }, muzSharp: [4],
      muzFill: pt,
      ears: earsOf(K, ear, c.base, inside(c)),
      marks: [
        K.flat("M56.5 42 L63.5 42 L65 84 Q60 86 55 84 Z", mix(c.base, c.shade, 0.15)),
        ...browDots(K, { edx: 14.2, ey: 53 }, pt, 2.2),
        K.fine(ell(60, 74, 7, 14, mix(c.base, "#000000", 0.0), { opacity: "0" })),
      ].filter(Boolean),
      front: [],
    });
  },
  rottweiler(c, K) {
    const pt = pointsOf(c);
    const spec = { pts: [[42, 29], [30, 24], [19, 31], [16, 45], [21, 55], [31, 51], [40, 41]], sharp: [4], inner: [[37, 31], [29, 28], [23, 33], [21, 43], [24, 48], [31, 45], [36, 39]] };
    return compose(c, K, {
      geo: { ey: 54, edx: 17, ew: 6.3, eh: 3.1, tilt: 1.7, ny: 72, nrx: 8.6, nry: 5.2, my: 83, mw: 15, topY: 19, browY: 44, hw: 41, neck: 31, bulk: 1.12 },
      cran: { top: 19, crown: 26, hw: 40, cheek: 58, jaw: 28, end: 90 }, cranSharp: [4],
      muz: { top: 46, w0: 11, w1: 20, mid: 76, chin: 98 }, muzSharp: [4],
      muzFill: mix(c.base, c.shade, 0.15),
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.3), inside(c)),
      under: [K.flat("M30 60 C28 72 36 80 46 80 C44 71 40 64 30 60 Z", pt), K.flat("M90 60 C92 72 84 80 74 80 C76 71 80 64 90 60 Z", pt)],
      marks: [...browDots(K, { edx: 17, ey: 54 }, pt, 2.6), K.fine(ell(60, 83, 11, 4, mix(c.base, INK, 0.2), { opacity: ".5" }))].filter(Boolean),
      front: [scar(K, 45, 41, 1)],
    });
  },
  pitbull(c, K) {
    const spec = { pts: [[43, 28], [34, 22], [24, 23], [18, 33], [23, 41], [33, 38]], sharp: [3], inner: [[38, 29], [32, 26], [25, 27], [22, 33], [26, 36], [33, 34]] };
    return compose(c, K, {
      geo: { ey: 54, edx: 17.2, ew: 6.2, eh: 3.1, tilt: 1.7, ny: 72, nrx: 8.4, nry: 5.1, my: 83, mw: 15.5, topY: 22, browY: 45, hw: 40, neck: 31, bulk: 1.1 },
      cran: { top: 22, crown: 25, hw: 39, cheek: 59, jaw: 29, end: 90 }, cranSharp: [4],
      muz: { top: 48, w0: 12, w1: 21.5, mid: 78, chin: 97 }, muzSharp: [4],
      muzFill: mix(c.base, c.light, 0.5),
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.25), inside(c)),
      marks: [blaze(K, mix(c.light, WHITE, 0.55), { top: 24, end: 72, w: 4.4 }),
        K.fine(path("M27 66 C30 82 44 90 60 90 C76 90 90 82 93 66", { fill: "none", stroke: mix(c.shade, INK, 0.3), "stroke-width": 1.4, opacity: ".35" }))].filter(Boolean),
      front: [scar(K, 71, 40, 1), wrinkles(K, c, ["M43 38 Q60 33 77 38"], 1.3, 0.35)],
    });
  },
  shepherd(c, K) {
    const mask = mix(c.shade, INK, 0.55);
    const ear = tri([46, 30], [26, 47], [28, -2], 0.07);
    return compose(c, K, {
      geo: { ey: 54, edx: 14.2, ew: 5.9, eh: 3.2, tilt: 1.7, ny: 75, nrx: 6.6, nry: 4.3, my: 86, mw: 11.5, topY: 21, browY: 45, hw: 31, neck: 24, bulk: 1 },
      sc: 0.96,
      cran: { top: 21, crown: 21, hw: 31, cheek: 56, jaw: 17, end: 93 },
      muz: { top: 45, w0: 8.5, w1: 14, mid: 78, chin: 100 }, muzSharp: [4],
      muzFill: mix(c.base, mask, 0.78),
      ears: earsOf(K, ear, c.base, mask),
      marks: [
        K.flat(symLoop([[0, 22], [5, 24], [9, 36], [7, 46], [0, 50]]), mask, { opacity: ".85" }),
        K.fine(ell(60, 84, 9, 4, mix(c.light, c.base, 0.3), { opacity: ".55" })),
        ...browDots(K, { edx: 14.2, ey: 54 }, mix(c.light, c.base, 0.4), 2),
      ].filter(Boolean),
      front: [],
    });
  },
  malinois(c, K) {
    const mask = mix(INK, c.shade, 0.15);
    const ear = tri([46, 30], [28, 46], [31, -6], 0.04);
    return compose(c, K, {
      geo: { ey: 53, edx: 13.6, ew: 5.8, eh: 3.1, tilt: 1.9, ny: 78, nrx: 6.2, nry: 4, my: 88, mw: 10.5, topY: 20, browY: 44, hw: 28, neck: 22, bulk: 0.96 },
      sc: 0.94,
      cran: { top: 20, crown: 19, hw: 28, cheek: 55, jaw: 15, end: 94 },
      muz: { top: 44, w0: 8, w1: 12, mid: 81, chin: 103 }, muzSharp: [4],
      muzFill: mask,
      ears: earsOf(K, ear, mix(c.base, mask, 0.55), mask),
      marks: [
        K.flat(symLoop([[0, 41], [13, 43], [24, 49], [22, 59], [10, 56], [0, 58]]), mask, { opacity: ".92" }),
        K.fine(K.flat("M54.5 58 L65.5 58 L63 80 Q60 82 57 80 Z", mix(mask, c.shade, 0.45), { opacity: ".6" })),
      ].filter(Boolean),
      front: [],
    });
  },
  boxer(c, K) {
    const mask = mix(c.shade, INK, 0.62);
    const spec = { pts: [[41, 28], [31, 22], [22, 25], [18, 36], [26, 44], [37, 39]], sharp: [3], inner: [[37, 30], [31, 27], [25, 29], [23, 36], [28, 40], [35, 36]] };
    return compose(c, K, {
      geo: { ey: 55, edx: 16.2, ew: 6.2, eh: 3.2, tilt: 1.6, ny: 72, nrx: 8.2, nry: 5.1, my: 84, mw: 14.8, topY: 21, browY: 46, hw: 37, neck: 28, bulk: 1.08 },
      cran: { top: 21, crown: 23, hw: 37, cheek: 58, jaw: 25, end: 90 }, cranSharp: [4],
      muz: { top: 47, w0: 13, w1: 21.5, mid: 78, chin: 95 }, muzSharp: [4, 5],
      muzFill: mask,
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.3), inside(c)),
      marks: [
        blaze(K, WHITE, { top: 26, end: 72, w: 3.8, tip: 3 }),
        K.flat(symLoop([[0, 84], [10, 84], [15, 90], [8, 96], [0, 96]]), WHITE),
        K.fine(path("M40 78 C46 90 74 90 80 78", { fill: "none", stroke: mix(INK, c.shade, 0.3), "stroke-width": 1.6, opacity: ".4" })),
      ].filter(Boolean),
      front: [wrinkles(K, c, ["M48 36 Q60 33 72 36"], 1.2, 0.3)],
    });
  },
  bulldog(c, K) {
    const spec = { pts: [[44, 30], [35, 24], [25, 25], [20, 34], [27, 42], [38, 38]], sharp: [3], inner: [[39, 31], [33, 28], [26, 29], [24, 34], [28, 37], [35, 35]] };
    return compose(c, K, {
      geo: { ey: 55, edx: 18.4, ew: 6.2, eh: 3.1, tilt: 1.6, ny: 71, nrx: 9.2, nry: 5.5, my: 83, mw: 17.5, topY: 24, browY: 46, hw: 42, neck: 34, bulk: 1.18 },
      cran: { top: 24, crown: 27, hw: 42, cheek: 60, jaw: 31, end: 90 }, cranSharp: [4],
      muz: { top: 50, w0: 15, w1: 26, mid: 77, chin: 94 }, muzSharp: [4, 5],
      muzFill: mix(c.base, c.light, 0.6),
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.25), inside(c)),
      marks: [
        blaze(K, mix(c.light, WHITE, 0.6), { top: 28, end: 62, w: 3.6, tip: 2 }),
        K.fine(path("M60 56 Q60 62 60 66", { fill: "none", stroke: mix(c.shade, INK, 0.4), "stroke-width": 1.8, opacity: ".7" })),
        ...jowls(K, c, { my: 83 }, 20, 12),
      ].filter(Boolean),
      front: [
        wrinkles(K, c, ["M42 37 Q60 31 78 37", "M46 42 Q60 38 74 42", "M50 61 Q60 57 70 61", "M44 67 Q60 62 76 67"], 1.5, 0.5),
        scar(K, 70, 38, -1),
      ],
    });
  },
  mastiff(c, K) {
    const mask = mix(c.shade, INK, 0.62);
    const spec = { pts: [[43, 29], [31, 25], [20, 33], [18, 49], [23, 60], [33, 52], [42, 40]], sharp: [4], inner: [[39, 31], [31, 29], [23, 35], [22, 47], [25, 53], [32, 48], [38, 40]] };
    return compose(c, K, {
      geo: { ey: 54, edx: 17.4, ew: 5.8, eh: 2.9, tilt: 1.6, ny: 73, nrx: 9.4, nry: 5.7, my: 85, mw: 17.5, topY: 20, browY: 45, hw: 43, neck: 36, bulk: 1.22 },
      cran: { top: 20, crown: 27, hw: 43, cheek: 59, jaw: 30, end: 92 }, cranSharp: [4],
      muz: { top: 47, w0: 14, w1: 24.5, mid: 80, chin: 100 }, muzSharp: [4],
      muzFill: mask,
      ears: earsOf(K, spec, mix(c.base, mask, 0.55), mask),
      under: [K.flat(symLoop([[0, 36], [12, 38], [26, 46], [28, 58], [14, 62], [0, 64]]), mask, { opacity: ".55" })],
      marks: [...jowls(K, c, { my: 85 }, 21, 15),
        K.fine(path("M48 87 Q60 94 72 87", { fill: "none", stroke: mix(c.light, mask, 0.4), "stroke-width": 1.3, opacity: ".4" }))].filter(Boolean),
      front: [wrinkles(K, c, ["M40 35 Q60 28 80 35", "M44 40 Q60 35 76 40", "M48 45 Q60 41 72 45"], 1.4, 0.4), scar(K, 78, 39, -1)],
    });
  },
  husky(c, K) {
    const mask = mix(c.shade, c.base, 0.2);
    const pale = mix(c.light, "#FFFFFF", 0.55);
    const ear = tri([45, 33], [27, 46], [25, 4], 0.06);
    return compose(c, K, {
      geo: { ey: 55, edx: 14.4, ew: 6.2, eh: 3.3, tilt: 1.6, ny: 71, nrx: 6.2, nry: 4.2, my: 83, mw: 12, topY: 24, browY: 47, hw: 36, neck: 26, bulk: 1.04 },
      cran: [[0, 24], [22, 24], [31, 32], [35, 44], [39, 58], [35, 65], [39, 74], [31, 83], [0, 90]], cranSharp: [4, 6],
      muz: { top: 48, w0: 8.5, w1: 13.5, mid: 76, chin: 97 },
      muzFill: pale,
      ears: earsOf(K, ear, mask, mix(pale, PINK, 0.35)),
      under: [],
      marks: [
        K.flat("M60 24 C80 24 92 36 92 52 C84 50 74 56 60 70 C46 56 36 50 28 52 C28 36 40 24 60 24 Z", mask),
        K.flat("M52 25 L60 56 L68 25 Z", pale),
        ...[[-1, 0], [1, 0]].map(([s2]) => ell(60 + s2 * 15, 44.5, 3.4, 2.4, pale)),
        K.fine(ell(60, 78, 11, 9, pale, { opacity: ".7" })),
      ].filter(Boolean),
      front: [],
    });
  },
  wolfhound(c, K) {
    const wire = mix(c.base, c.light, 0.15);
    const beard = mix(c.base, c.shade, 0.25);
    const spec = { pts: [[40, 28], [31, 22], [22, 27], [19, 37], [27, 44], [36, 40]], sharp: [3], inner: [[36, 30], [31, 27], [25, 31], [23, 37], [28, 40], [34, 37]] };
    return compose(c, K, {
      geo: { ey: 54, edx: 13.8, ew: 5.7, eh: 3.1, tilt: 1.6, ny: 79, nrx: 6.4, nry: 4.3, my: 90, mw: 11.4, topY: 20, browY: 44, hw: 32, neck: 24 },
      cran: [[0, 20], [20, 20], [29, 28], [32, 41], [30, 50], [33, 58], [28, 68], [30, 76], [21, 86], [0, 94]], cranSharp: [4, 5, 7],
      muz: { top: 45, w0: 8, w1: 12.8, mid: 84, chin: 104 },
      muzFill: wire,
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.3), inside(c)),
      under: [],
      marks: [
        K.flat(tuft([[60, 88], [47, 91], [45, 98], [50, 97], [49, 106], [55, 100], [60, 110], [65, 100], [71, 106], [70, 97], [75, 98], [73, 91]]), beard),
        K.fine(K.flat(tuft([[44, 36], [37, 38], [31, 36], [33, 41], [38, 41], [44, 41]]), mix(beard, INK, 0.1))),
        K.fine(K.flat(tuft([[76, 36], [83, 38], [89, 36], [87, 41], [82, 41], [76, 41]]), mix(beard, INK, 0.1))),
      ].filter(Boolean),
      front: [
        K.flat(tuft([[43, 47], [34, 45], [26, 42], [30, 49], [36, 50], [44, 52]]), beard),
        K.flat(tuft([[77, 47], [86, 45], [94, 42], [90, 49], [84, 50], [76, 52]]), beard),
      ],
    });
  },
  shiba(c, K) {
    const cream = mix(WHITE, c.light, 0.35);
    const ear = tri([44, 31], [26, 44], [27, 5], 0.05);
    return compose(c, K, {
      geo: { ey: 56, edx: 15.4, ew: 6, eh: 3.2, tilt: 1.6, ny: 71, nrx: 5.4, nry: 3.8, my: 81, mw: 11, topY: 23, browY: 47, hw: 35, neck: 25 },
      cran: [[0, 23], [22, 23], [31, 31], [35, 44], [38, 56], [34, 63], [36, 70], [29, 81], [0, 89]], cranSharp: [4, 6],
      muz: { top: 49, w0: 8.5, w1: 13.5, mid: 76, chin: 95 },
      muzFill: cream,
      ears: earsOf(K, ear, c.base, mix(cream, PINK, 0.3)),
      marks: [
        K.flat("M24 60 C26 74 38 82 48 80 C42 70 36 64 24 60 Z", cream), K.flat("M96 60 C94 74 82 82 72 80 C78 70 84 64 96 60 Z", cream),
        ...[-1, 1].map((s2) => ell(60 + s2 * 15.6, 45, 3.4, 2.4, cream)),
        K.flat("M60 24 C64 32 63 40 60 48 C57 40 56 32 60 24 Z", mix(c.light, c.base, 0.5), { opacity: ".5" }),
      ].filter(Boolean),
      front: [],
    });
  },
  // ---- the long-faced hunters -------------------------------------------------------------------------------------
  greyhound(c, K) {
    const spec = tri([38, 32], [34, 42], [20, 31], 0.1, 0.5);
    return compose(c, K, {
      geo: { ey: 53, edx: 12.2, ew: 5.4, eh: 3, tilt: 1.8, ny: 83, nrx: 5.4, nry: 3.7, my: 93, mw: 8.6, topY: 20, browY: 44, hw: 26, neck: 20, bulk: 0.9 },
      cran: { top: 20, crown: 16, hw: 25, cheek: 54, jaw: 12, end: 96 },
      muz: { top: 44, w0: 6.4, w1: 9.6, mid: 88, chin: 107 }, muzSharp: [4],
      muzFill: mix(c.base, c.light, 0.45),
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.2), inside(c)),
      marks: [K.fine(path("M60 23 C62 44 62 70 61 100 C60 70 59 44 60 23 Z", { fill: c.light, opacity: ".25" }))].filter(Boolean),
      front: [],
    });
  },
  bloodhound(c, K) {
    const earC = mix(c.shade, INK, 0.38);
    const spec = { pts: [[35, 30], [24, 32], [14, 50], [9, 78], [11, 108], [20, 118], [31, 104], [38, 74], [41, 46]], sharp: [], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 14.6, ew: 5.6, eh: 3, tilt: 1.3, ny: 77, nrx: 8, nry: 5.3, my: 89, mw: 14, topY: 19, browY: 45, hw: 33, neck: 28, bulk: 1.05 },
      cran: { top: 19, crown: 20, hw: 32, cheek: 58, jaw: 20, end: 94 },
      muz: { top: 46, w0: 10, w1: 18.5, mid: 82, chin: 106 }, muzSharp: [],
      muzFill: mix(TAN, c.light, 0.4),
      ears: earsOf(K, spec, earC, null),
      marks: [...jowls(K, c, { my: 89 }, 16.5, 14),
        K.fine(path("M36 63 Q44 70 52 62 M84 63 Q76 70 68 62", { fill: "none", stroke: "#8A2E2E", "stroke-width": 2.2, "stroke-linecap": "round", opacity: ".55" }))].filter(Boolean),
      front: [wrinkles(K, c, ["M40 34 Q60 27 80 34", "M42 39 Q60 33 78 39", "M46 44 Q60 39 74 44"], 1.4, 0.45)],
    });
  },
  basset(c, K) {
    const earC = mix(c.shade, INK, 0.3);
    const spec = { pts: [[36, 32], [24, 36], [14, 54], [10, 80], [13, 102], [22, 109], [32, 96], [38, 72], [41, 48]], sharp: [], inner: null };
    return compose(c, K, {
      geo: { ey: 56, edx: 14.4, ew: 5.6, eh: 3, tilt: 1.2, ny: 75, nrx: 7.6, nry: 5.1, my: 87, mw: 13.2, topY: 21, browY: 46, hw: 33, neck: 26, bulk: 1.05 },
      cran: { top: 21, crown: 21, hw: 32, cheek: 59, jaw: 21, end: 92 },
      muz: { top: 48, w0: 10, w1: 17, mid: 80, chin: 102 },
      muzFill: mix(c.light, WHITE, 0.4),
      ears: earsOf(K, spec, earC, null),
      marks: [blaze(K, WHITE, { top: 24, end: 70, w: 4.4, tip: 5 }), ...jowls(K, c, { my: 87 }, 15, 13),
        K.fine(path("M36 65 Q44 72 52 64 M84 65 Q76 72 68 64", { fill: "none", stroke: "#8A2E2E", "stroke-width": 2, "stroke-linecap": "round", opacity: ".5" }))].filter(Boolean),
      front: [wrinkles(K, c, ["M42 38 Q60 32 78 38"], 1.4, 0.4)],
    });
  },
  beagle(c, K) {
    const earC = mix(c.shade, "#2A1A12", 0.35);
    const spec = { pts: [[38, 28], [26, 26], [17, 40], [14, 62], [20, 78], [31, 72], [39, 54], [41, 40]], sharp: [], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 15, ew: 6, eh: 3.3, tilt: 1.4, ny: 73, nrx: 7, nry: 4.8, my: 84, mw: 12.8, topY: 21, browY: 45, hw: 34, neck: 25 },
      cran: { top: 21, crown: 23, hw: 33, cheek: 58, jaw: 22, end: 92 },
      muz: { top: 46, w0: 9, w1: 15.5, mid: 78, chin: 98 },
      muzFill: WHITE,
      ears: earsOf(K, spec, earC, null),
      marks: [blaze(K, WHITE, { top: 22, end: 70, w: 4.8, tip: 6 }),
        K.fine(K.flat("M32 34 C40 26 48 28 52 36 C44 40 38 40 32 34 Z", mix(c.shade, c.base, 0.4), { opacity: ".5" }))].filter(Boolean),
      front: [],
    });
  },
  hound(c, K) {
    const earC = mix(c.shade, INK, 0.25);
    const spec = { pts: [[37, 30], [24, 34], [15, 56], [14, 86], [19, 104], [28, 100], [37, 72], [41, 48]], sharp: [], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 14.4, ew: 5.9, eh: 3.2, tilt: 1.5, ny: 74, nrx: 6.8, nry: 4.7, my: 85, mw: 12.2, topY: 21, browY: 45, hw: 32, neck: 25 },
      cran: { top: 21, crown: 22, hw: 32, cheek: 57, jaw: 20, end: 92 },
      muz: { top: 46, w0: 9, w1: 14.5, mid: 80, chin: 100 },
      muzFill: mix(c.light, WHITE, 0.4),
      ears: earsOf(K, spec, earC, null),
      marks: [blaze(K, mix(c.light, WHITE, 0.5), { top: 22, end: 72, w: 4.2, tip: 5 })].filter(Boolean),
      front: [],
    });
  },
  dalmatian(c, K) {
    const white = { base: "#F2F1EC", shade: "#CFCBC2", light: "#FFFFFF" };
    const spot = mix(c.shade, INK, 0.62);
    const spec = { pts: [[38, 28], [28, 25], [19, 36], [18, 56], [25, 63], [34, 55], [40, 42]], sharp: [], inner: null };
    const r = compose(white, K, {
      geo: { ey: 54, edx: 14.4, ew: 6, eh: 3.3, tilt: 1.6, ny: 75, nrx: 6.8, nry: 4.5, my: 86, mw: 12, topY: 21, browY: 45, hw: 31, neck: 24 },
      cran: { top: 21, crown: 22, hw: 31, cheek: 57, jaw: 19, end: 94 },
      muz: { top: 46, w0: 9, w1: 14, mid: 80, chin: 101 },
      muzFill: "#FFFFFF",
      ears: earsOf(K, spec, "#F2F1EC", null),
      marks: spots(spot, [[40, 36, 4.2], [73, 31, 3.2], [82, 49, 5.2], [34, 55, 3], [54, 33, 2.2], [86, 68, 3], [36, 70, 3.2], [67, 40, 1.8], [49, 28, 1.8]]),
      front: [],
    });
    r.back = r.back.concat([]);
    r.coat = white;
    return r;
  },
  // ---- the herding and the sharp-eared -----------------------------------------------------------------------------
  kelpie(c, K) {
    const tan = mix(TAN, c.base, 0.1), black = mix(c.base, "#14171B", 0.4);
    const ear = tri([46, 30], [25, 46], [25, 0], 0.05);
    return compose(c, K, {
      geo: { ey: 55, edx: 13.6, ew: 5.8, eh: 3.2, tilt: 1.7, ny: 73, nrx: 6.2, nry: 4.1, my: 84, mw: 11, topY: 22, browY: 46, hw: 31, neck: 24 },
      cran: { top: 22, crown: 21, hw: 31, cheek: 56, jaw: 17, end: 94 },
      muz: { top: 46, w0: 8.5, w1: 13.5, mid: 79, chin: 99 }, muzSharp: [4],
      muzFill: tan,
      skin: black,
      ears: earsOf(K, ear, black, inside(c)),
      marks: [...browDots(K, { edx: 13.6, ey: 55 }, tan, 2.4), K.fine(ell(60, 90, 9, 3, mix(tan, WHITE, 0.4), { opacity: ".7" }))].filter(Boolean),
      front: [],
    });
  },
  collie(c, K) {
    const ear = tri([42, 33], [30, 44], [27, 8], 0.05);
    const ruff = (cx) => `M${cx} 90 C${cx - 38} 94 ${cx - 40} 112 ${cx - 28} 120 L${cx + 28} 120 C${cx + 40} 112 ${cx + 38} 94 ${cx} 90 Z`;
    return compose(c, K, {
      geo: { ey: 54, edx: 12.8, ew: 5.6, eh: 3.1, tilt: 1.6, ny: 80, nrx: 5.8, nry: 4, my: 90, mw: 10, topY: 22, browY: 45, hw: 28, neck: 25, bulk: 1.03 },
      cran: { top: 22, crown: 18, hw: 28, cheek: 54, jaw: 12, end: 96 },
      muz: { top: 45, w0: 8, w1: 11.4, mid: 86, chin: 106 },
      muzFill: mix(c.base, c.light, 0.4),
      ears: [...K.solid(ruff(60), WHITE, { rim: false }), ...earsOf(K, ear, mix(c.shade, c.base, 0.3), inside(c))],
      marks: [blaze(K, WHITE, { top: 24, end: 82, w: 4.4, tip: 4 }), K.flat("M40 76 C44 74 52 82 60 82 C68 82 76 74 80 76 C76 94 66 104 60 104 C54 104 44 94 40 76 Z", WHITE)].filter(Boolean),
      front: [],
    });
  },
  corgi(c, K) {
    const ear = tri([45, 32], [24, 46], [22, 3], 0.05);
    return compose(c, K, {
      geo: { ey: 56, edx: 15, ew: 6, eh: 3.2, tilt: 1.5, ny: 72, nrx: 6.2, nry: 4.2, my: 83, mw: 11.4, topY: 24, browY: 47, hw: 36, neck: 26 },
      cran: { top: 24, crown: 23, hw: 36, cheek: 60, jaw: 24, end: 92 },
      muz: { top: 49, w0: 9.5, w1: 14, mid: 78, chin: 96 },
      muzFill: WHITE,
      ears: earsOf(K, ear, c.base, WHITE),
      marks: [K.flat("M60 28 C68 38 70 54 78 66 C82 74 80 90 60 90 C40 90 38 74 42 66 C50 54 52 38 60 28 Z", WHITE)].filter(Boolean),
      front: [],
    });
  },
  jackrussell(c, K) {
    const white = { base: WHITE, shade: "#CFCBC2", light: "#FFFFFF" };
    const patch = mix(c.base, "#000000", 0.12);
    const spec = { pts: [[40, 28], [26, 29], [19, 42], [22, 55], [32, 55], [41, 44]], sharp: [], inner: null };
    const r = compose(white, K, {
      geo: { ey: 56, edx: 14.4, ew: 5.9, eh: 3.2, tilt: 1.5, ny: 72, nrx: 5.6, nry: 4, my: 82, mw: 11, topY: 26, browY: 48, hw: 32, neck: 24 },
      cran: { top: 26, crown: 22, hw: 32, cheek: 58, jaw: 21, end: 92 },
      muz: { top: 48, w0: 8.5, w1: 13.5, mid: 77, chin: 97 },
      muzFill: WHITE,
      ears: earsOf(K, spec, patch, null),
      marks: [K.flat("M60 27 C74 27 88 36 88 50 C80 48 72 44 70 36 C66 44 60 50 54 48 C50 40 56 31 60 27 Z", patch), ell(76, 53, 11, 11, patch)],
      front: [],
    });
    r.coat = white;
    return r;
  },
  pointer(c, K) {
    const patch = mix(c.base, "#2A1A12", 0.25);
    const white = { base: WHITE, shade: "#CFCBC2", light: "#FFFFFF" };
    const spec = { pts: [[38, 29], [27, 27], [19, 42], [20, 62], [28, 66], [37, 54], [41, 42]], sharp: [], inner: null };
    const r = compose(white, K, {
      geo: { ey: 55, edx: 13.4, ew: 5.8, eh: 3.2, tilt: 1.5, ny: 75, nrx: 6.6, nry: 4.5, my: 87, mw: 11.6, topY: 22, browY: 46, hw: 29, neck: 23 },
      cran: { top: 22, crown: 19, hw: 29, cheek: 56, jaw: 16, end: 96 },
      muz: { top: 46, w0: 8.5, w1: 13.5, mid: 82, chin: 102 },
      muzFill: "#FFFFFF",
      ears: earsOf(K, spec, patch, null),
      marks: [K.flat("M60 24 C74 24 84 32 86 44 C78 44 72 40 68 34 C64 42 60 44 56 40 C52 30 56 26 60 24 Z", patch), ell(40, 46, 6, 8, patch)],
      front: [],
    });
    r.coat = white;
    return r;
  },
  whippet(c, K) {
    const spec = tri([39, 32], [35, 43], [17, 31], 0.1, 0.5);
    return compose(c, K, {
      geo: { ey: 54, edx: 12.8, ew: 5.5, eh: 3.1, tilt: 1.7, ny: 79, nrx: 5.6, nry: 3.8, my: 89, mw: 9.4, topY: 21, browY: 45, hw: 27, neck: 20, bulk: 0.92 },
      cran: { top: 21, crown: 17, hw: 26, cheek: 54, jaw: 13, end: 95 },
      muz: { top: 45, w0: 7, w1: 10.5, mid: 84, chin: 104 }, muzSharp: [4],
      muzFill: mix(c.base, c.light, 0.45),
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.2), inside(c)),
      marks: [],
      front: [],
    });
  },
  // ---- the retrievers, spaniels and setters ------------------------------------------------------------------------
  retriever(c, K) {
    const spec = { pts: [[36, 29], [25, 29], [17, 44], [15, 66], [20, 84], [28, 80], [37, 62], [40, 44]], sharp: [], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 15.4, ew: 6.3, eh: 3.4, tilt: 1.4, ny: 72, nrx: 7.2, nry: 4.9, my: 83, mw: 13.4, topY: 21, browY: 46, hw: 35, neck: 27 },
      cran: { top: 21, crown: 23, hw: 34.5, cheek: 57, jaw: 24, end: 92 },
      muz: { top: 47, w0: 10.5, w1: 16.5, mid: 78, chin: 98 },
      muzFill: mix(c.base, c.light, 0.6),
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.45), null),
      marks: [K.fine(path("M60 22 C64 30 64 38 60 46 C56 38 56 30 60 22 Z", { fill: c.light, opacity: ".3" }))].filter(Boolean),
      front: [],
    });
  },
  labrador(c, K) {
    const spec = { pts: [[38, 29], [28, 29], [20, 42], [19, 60], [25, 68], [33, 60], [40, 46]], sharp: [], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 15.8, ew: 6.2, eh: 3.3, tilt: 1.4, ny: 72, nrx: 8, nry: 5.2, my: 83, mw: 14.6, topY: 22, browY: 46, hw: 37, neck: 29, bulk: 1.06 },
      cran: { top: 22, crown: 25, hw: 37, cheek: 58, jaw: 27, end: 91 },
      muz: { top: 48, w0: 11.5, w1: 18, mid: 78, chin: 97 },
      muzFill: mix(c.base, c.light, 0.5),
      ears: earsOf(K, spec, mix(c.base, c.shade, 0.4), null),
      marks: [K.fine(path("M50 25 Q60 29 70 25", { fill: "none", stroke: c.shade, "stroke-width": 1.5, "stroke-linecap": "round", opacity: ".4" }))].filter(Boolean),
      front: [],
    });
  },
  setter(c, K) {
    const fringe = mix(c.base, c.shade, 0.55);
    const spec = { pts: [[36, 29], [22, 32], [14, 52], [12, 78], [14, 96], [19, 106], [23, 98], [27, 110], [33, 98], [38, 72], [41, 46]], sharp: [5, 7], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 13.8, ew: 5.8, eh: 3.2, tilt: 1.5, ny: 76, nrx: 6.4, nry: 4.5, my: 87, mw: 11.6, topY: 23, browY: 46, hw: 30, neck: 24 },
      cran: { top: 23, crown: 20, hw: 30, cheek: 57, jaw: 17, end: 96 },
      muz: { top: 47, w0: 9, w1: 13.5, mid: 81, chin: 102 },
      muzFill: mix(c.base, c.light, 0.5),
      ears: earsOf(K, spec, fringe, null),
      marks: [K.flat("M44 29 C48 17 56 13 60 23 C64 13 72 17 76 29 C68 25 52 25 44 29 Z", c.light, { opacity: ".7" })],
      front: [],
    });
  },
  spaniel(c, K) {
    const fringe = mix(c.base, c.shade, 0.58);
    const spec = { pts: [[37, 29], [20, 30], [10, 52], [8, 76], [11, 90], [16, 98], [20, 92], [24, 100], [30, 90], [38, 70], [42, 46]], sharp: [5, 7], inner: null };
    return compose(c, K, {
      geo: { ey: 57, edx: 14.8, ew: 6, eh: 3.4, tilt: 1.4, ny: 72, nrx: 6.8, nry: 4.7, my: 83, mw: 12.4, topY: 22, browY: 48, hw: 35, neck: 27 },
      cran: { top: 22, crown: 25, hw: 35, cheek: 58, jaw: 24, end: 92 },
      muz: { top: 50, w0: 9.5, w1: 15.5, mid: 78, chin: 98 },
      muzFill: mix(c.base, c.light, 0.5),
      ears: earsOf(K, spec, fringe, null),
      marks: [K.flat("M33 31 C33 15 48 9 60 15 C72 9 87 15 87 31 C80 25 70 23 60 27 C50 23 40 25 33 31 Z", mix(c.base, c.shade, 0.25))],
      front: [],
    });
  },
  // ---- the wiry and the bearded ------------------------------------------------------------------------------------
  terrier(c, K) {
    const brow = mix(c.light, WHITE, 0.3);
    const dark = mix(c.base, "#3B2A1C", 0.5);
    const spec = { pts: [[46, 32], [20, 36], [17, 46], [27, 60], [40, 52], [47, 40]], sharp: [2], inner: null };
    return compose(c, K, {
      geo: { ey: 56, edx: 14.4, ew: 5.8, eh: 3.2, tilt: 1.6, ny: 71, nrx: 6.2, nry: 4.4, my: 82, mw: 12, topY: 26, browY: 49, hw: 33, neck: 25 },
      cran: { top: 26, crown: 25, hw: 33, cheek: 56, jaw: 28, end: 92 },
      muz: { top: 49, w0: 10, w1: 18, mid: 78, chin: 98 }, muzSharp: [4],
      muzFill: c.light,
      ears: earsOf(K, spec, dark, null),
      marks: [K.flat(tuft([[38, 88], [32, 94], [41, 92], [40, 99], [48, 95], [52, 102], [58, 96], [60, 102], [62, 96], [68, 102], [72, 95], [80, 99], [79, 92], [88, 94], [82, 88]]), brow)],
      front: [K.flat(tuft([[34, 46], [41, 40], [49, 40], [56, 46], [48, 49], [40, 50]]), brow), K.flat(tuft([[86, 46], [79, 40], [71, 40], [64, 46], [72, 49], [80, 50]]), brow)],
    });
  },
  schnauzer(c, K) {
    const beard = mix(c.light, "#FFFFFF", 0.25);
    const spec = { pts: [[38, 30], [24, 36], [16, 48], [25, 57], [39, 51], [44, 40]], sharp: [2], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 15, ew: 5.8, eh: 3.2, tilt: 1.6, ny: 66, nrx: 6.8, nry: 4.6, my: 80, mw: 12.6, topY: 25, browY: 49, hw: 32, neck: 25 },
      cran: [[0, 25], [24, 25], [32, 33], [33, 50], [33, 66], [29, 80], [0, 92]], cranSharp: [1, 3],
      muz: { top: 48, w0: 11, w1: 17.5, mid: 74, chin: 92 },
      muzFill: beard,
      ears: earsOf(K, spec, c.shade, null),
      marks: [K.flat("M33 68 C34 98 86 98 87 68 C76 83 44 83 33 68 Z", beard), ell(60, 73, 15, 11, beard)],
      front: [K.flat("M30 45 C36 35 48 35 57 44 C48 45 40 47 30 45 Z", beard), K.flat("M90 45 C84 35 72 35 63 44 C72 45 80 47 90 45 Z", beard)],
    });
  },
  // ---- the big bears, the small and the mixed ------------------------------------------------------------------------
  newfoundland(c, K) {
    const dark = mix(c.base, INK, 0.3);
    const spec = { pts: [[38, 29], [24, 28], [14, 44], [15, 64], [22, 72], [32, 62], [41, 44]], sharp: [], inner: null };
    return compose(c, K, {
      geo: { ey: 55, edx: 17, ew: 5.8, eh: 3, tilt: 1.3, ny: 69, nrx: 8.6, nry: 5.5, my: 82, mw: 15, topY: 20, browY: 47, hw: 42, neck: 33, bulk: 1.18 },
      cran: { top: 20, crown: 28, hw: 42, cheek: 58, jaw: 31, end: 94 },
      muz: { top: 48, w0: 12, w1: 20, mid: 80, chin: 100 },
      skin: dark,
      muzFill: mix(c.light, c.base, 0.4),
      ears: earsOf(K, spec, mix(dark, INK, 0.2), null),
      marks: [...jowls(K, c, { my: 82 }, 17, 12)],
      front: [K.line("M38 41 C44 35 53 37 57 42 M82 41 C76 35 67 37 63 42", mix(dark, INK, 0.4), 3.2, {})],
    });
  },
  chihuahua(c, K) {
    const ear = tri([43, 44], [12, 42], [3, 6], 0.06);
    return compose(c, K, {
      geo: { ey: 57, edx: 14.6, ew: 6.4, eh: 3.6, tilt: 1.6, ny: 73, nrx: 5.2, nry: 3.7, my: 81, mw: 9.8, topY: 29, browY: 51, hw: 32, neck: 22, bulk: 0.9 },
      cran: { top: 29, crown: 25, hw: 33, cheek: 58, jaw: 22, end: 90 },
      muz: { top: 54, w0: 8, w1: 11.5, mid: 78, chin: 93 }, muzSharp: [4],
      muzFill: mix(c.base, c.light, 0.55),
      ears: earsOf(K, ear, c.shade, inside(c)),
      marks: [K.fine(K.flat("M52 31 Q60 37 68 31", c.light, { opacity: ".4" }))].filter(Boolean),
      front: [],
    });
  },
  poodle(c, K) {
    const fluff = mix(c.base, c.light, 0.18);
    const circ = (cx, cy, r) => `M${f(cx - r)} ${f(cy)} a${r} ${r} 0 1 0 ${2 * r} 0 a${r} ${r} 0 1 0 ${-2 * r} 0 Z`;
    const cloud = (list) => list.flatMap(([cx, cy, r]) => K.solid(circ(cx, cy, r), fluff, { rim: false }));
    return compose(c, K, {
      geo: { ey: 58, edx: 13.4, ew: 5.7, eh: 3.2, tilt: 1.7, ny: 75, nrx: 5.4, nry: 3.9, my: 85, mw: 10.4, topY: 31, browY: 52, hw: 28, neck: 22 },
      cran: { top: 31, crown: 20, hw: 28, cheek: 59, jaw: 16, end: 94 },
      muz: { top: 54, w0: 8, w1: 11.5, mid: 82, chin: 101 }, muzSharp: [4],
      muzFill: mix(c.base, c.light, 0.5),
      ears: [
        n("g", { class: "dk-ear dk-ear--l" }, cloud([[19, 62, 10], [15, 77, 10], [19, 92, 9.5]])),
        n("g", { class: "dk-ear dk-ear--r" }, cloud([[101, 62, 10], [105, 77, 10], [101, 92, 9.5]])),
      ],
      marks: [...cloud([[60, 14, 12.5], [45, 21, 10], [75, 21, 10], [34, 31, 7.5], [86, 31, 7.5]])],
      front: [],
    });
  },
  mutt(c, K) {
    const patch = mix(c.shade, INK, 0.2);
    const point = tri([42, 34], [28, 44], [27, 6], 0.05);
    const drop = { pts: [[84, 32], [98, 38], [104, 60], [98, 80], [88, 78], [81, 60], [79, 44]], sharp: [], inner: null };
    const earL = earPair(point.pts, { sharp: point.sharp, fill: c.shade, inner: point.inner, innerFill: inside(c), kit: K }).slice(0, 1);
    const earR = earPair(mirrorPts(drop.pts), { sharp: [], fill: mix(c.shade, c.base, 0.2), kit: K }).slice(1);
    return compose(c, K, {
      geo: { ey: 56, edx: 14.4, ew: 6.2, eh: 3.4, tilt: 1.5, ny: 70, nrx: 6.8, nry: 4.7, my: 81, mw: 13, topY: 24, browY: 46, hw: 35, neck: 26 },
      cran: { top: 24, crown: 24, hw: 35, cheek: 58, jaw: 24, end: 90 },
      muz: { top: 47, w0: 10, w1: 16.5, mid: 77, chin: 96 },
      muzFill: mix(c.base, c.light, 0.55),
      ears: [...earL, ...earR],
      marks: [ell(76, 53, 12.5, 12, patch, { opacity: ".92" })],
      front: [scar(K, 41, 42, 1)],
    });
  },
};

export const BREEDS = BREED_IDS.filter((id) => BREED[id]);

/** The shown name of each breed (the drawing key is not always the shown name). */
export const BREED_LABELS = {
  retriever: "Golden Retriever", labrador: "Labrador", bulldog: "Bulldog", schnauzer: "Schnauzer", husky: "Husky", mutt: "Mutt",
  hound: "Hound", chihuahua: "Chihuahua", collie: "Collie", corgi: "Corgi", dalmatian: "Dalmatian", basset: "Basset Hound",
  greyhound: "Greyhound", jackrussell: "Jack Russell", kelpie: "Kelpie", newfoundland: "Newfoundland", shepherd: "German Shepherd",
  poodle: "Poodle", beagle: "Beagle", setter: "Setter", terrier: "Terrier", bloodhound: "Bloodhound", pointer: "Pointer",
  whippet: "Whippet", spaniel: "Spaniel",
  doberman: "Doberman", rottweiler: "Rottweiler", pitbull: "Pit Bull", wolfhound: "Wolfhound", boxer: "Boxer", mastiff: "Mastiff",
  shiba: "Shiba Inu", malinois: "Belgian Malinois",
};

/**
 * The named anchors every accessory is placed from, in the 120 x 120 badge. They come from the breed's landmarks, so a cap, a
 * headband, a visor, a pair of shades, a bandana, a spiked collar, a chain, a hood and a jersey line up on every head.
 */
export function anchorsOf(geo) {
  const half = geo.hw, eyeHalf = geo.edx + geo.ew;
  return {
    crown: { x: 60, y: geo.topY, half },
    brow: { y: geo.browY, left: 60 - half - 1, right: 60 + half + 1 },
    eyes: { y: geo.ey, left: 60 - geo.edx, right: 60 + geo.edx, half: eyeHalf, ew: geo.ew, eh: geo.eh },
    nose: { x: 60, y: geo.ny },
    mouth: { x: 60, y: geo.my, half: geo.mw },
    chin: { x: 60, y: geo.chin },
    neck: { y: geo.chin + 1, half: geo.neck },
    chest: { y: Math.max(geo.chin + 6, 96), half: geo.neck + 14 },
    hood: { y: geo.chin - 8, half: Math.max(geo.hw + 10, geo.neck + 18) },
  };
}

/** Build one breed's pieces for a coat and a toolkit. Unknown breeds are a retriever. */
export function buildBreed(name, coat, kit) {
  const built = (BREED[name] || BREED.retriever)(coat, kit);
  built.anchors = anchorsOf(built.geo);
  return built;
}
