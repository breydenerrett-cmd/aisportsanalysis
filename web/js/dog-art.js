/**
 * THE DRAWING TOOLKIT behind the hound illustrations (dog-breeds.js, dog-face.js, dog-accessories.js, dog-rig.js).
 *
 * Everything here is pure geometry and element building: no look value, no network, no timers. Shapes are written as the
 * RIGHT half of a symmetrical outline (a list of [offset-from-centre, y] points) and turned into a smooth closed path with a
 * Catmull-Rom spline, so a breed's head is a dozen numbers instead of a hand-tuned bezier, and corners (a Doberman's jaw, a
 * Pit Bull's cheek) are one flag. Ears are written for the left side and mirrored.
 *
 * `makeKit` is the per-dog toolkit a breed builder draws with. It knows the art style (outline weight and colour, which shading
 * and rim light to lay over a shape) and the level of detail (a 32px badge drops the overlays and the fine lines), so a breed is
 * written once and comes out in all three styles at all sizes. Every colour is a hex from dog-look.js's tables or a mix of
 * two of them, or `url(#lh-...)` to a shared gradient in dog-defs.js. No look value ever reaches a markup string.
 */

import { s } from "./hounds-core.js";

export const INK = "#0B0D12";

export const n = (tag, attrs, kids) => s(tag, attrs || {}, kids || []);
export const path = (d, attrs) => n("path", Object.assign({ d }, attrs || {}));
export const ell = (cx, cy, rx, ry, fill, extra) => n("ellipse", Object.assign({ cx: f(cx), cy: f(cy), rx: f(rx), ry: f(ry), fill }, extra || {}));
export const grp = (cls, kids, attrs) => n("g", Object.assign(cls ? { class: cls } : {}, attrs || {}), kids);

/** A number rounded to a tenth, for short path strings. */
export function f(v) { return Math.round(v * 10) / 10; }

export function mix(a, b, t) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `#${pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("")}`;
}

/** Perceived lightness of a hex colour, 0 to 1. */
export function lum(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

// ---- outlines from points ------------------------------------------------------------------------------------

/** A closed smooth path through `pts` ([x, y] each). `sharp` lists the point indices that stay corners. */
export function spline(pts, sharp = []) {
  const N = pts.length;
  const sh = new Set(sharp);
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 0; i < N; i++) {
    const p0 = pts[(i - 1 + N) % N], p1 = pts[i], p2 = pts[(i + 1) % N], p3 = pts[(i + 2) % N];
    const c1 = sh.has(i) ? p1 : [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = sh.has((i + 1) % N) ? p2 : [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${f(c1[0])} ${f(c1[1])} ${f(c2[0])} ${f(c2[1])} ${f(p2[0])} ${f(p2[1])}`;
  }
  return `${d} Z`;
}

/** An OPEN smooth path through `pts` (the ends keep their direction). */
export function splineOpen(pts, sharp = []) {
  const N = pts.length;
  const sh = new Set(sharp);
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 0; i < N - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(N - 1, i + 2)];
    const c1 = sh.has(i) ? p1 : [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = sh.has(i + 1) ? p2 : [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${f(c1[0])} ${f(c1[1])} ${f(c2[0])} ${f(c2[1])} ${f(p2[0])} ${f(p2[1])}`;
  }
  return d;
}

/**
 * A symmetrical closed shape from its right half. `half` runs from the top centre (offset 0) down the right side to the bottom
 * centre (offset 0). `sharp` indexes into `half` and marks corners (the mirrored point is a corner too).
 */
export function symLoop(half, sharp = []) {
  const last = half.length - 1;
  const right = half.map(([dx, y]) => [60 + dx, y]);
  const left = [];
  for (let i = last - 1; i >= 1; i--) left.push([60 - half[i][0], half[i][1]]);
  const pts = right.concat(left);
  const idx = [];
  for (const i of sharp) {
    idx.push(i);
    if (i > 0 && i < last) idx.push(pts.length - i);
  }
  return spline(pts, idx);
}

/**
 * A symmetrical OPEN outline from its right half: the muzzle's sides and chin without a line across the top. `half` runs from
 * the top (the bridge) down the right side to the bottom centre (offset 0). Returns { open, closed }.
 */
export function symArc(half, sharp = []) {
  const last = half.length - 1;
  // from the top-left down to the centre, then the right side back up to the top-right
  const ordered = [];
  for (let i = 0; i < last; i++) ordered.push([60 - half[i][0], half[i][1]]);
  for (let i = last; i >= 0; i--) ordered.push([60 + half[i][0], half[i][1]]);
  const idx = [];
  for (const i of sharp) {
    idx.push(i);
    if (i < last) idx.push(2 * last - i);
  }
  const open = splineOpen(ordered, idx);
  return { open, closed: `${open} Z` };
}

/** Mirror an absolute point list across the centre line. */
export const mirrorPts = (pts) => pts.map(([x, y]) => [120 - x, y]);

/** A pair of ears from the LEFT ear's outline points. `inner` is an optional smaller outline drawn on top. */
export function earPair(pts, { sharp = [], fill, inner = null, innerFill = null, innerSharp = sharp, kit, rim = true }) {
  const one = (side) => {
    const m = (p) => (side === "r" ? mirrorPts(p) : p);
    const parts = kit.solid(spline(m(pts), sharp), fill, { rim });
    if (inner) parts.push(path(spline(m(inner), innerSharp), { fill: innerFill }));
    return grp(`dk-ear dk-ear--${side}`, parts);
  };
  return [one("l"), one("r")];
}

// ---- the per-dog toolkit --------------------------------------------------------------------------------------

/**
 * `style` is a spec from dog-styles.js (ow, owSmall, outline(coat), shade, rim), `lod` is "s" (a small badge) or "l".
 * The kit adds the outline, then the shade and rim overlays (large only) to every solid shape.
 */
export function makeKit({ style, coat, lod }) {
  const small = lod === "s";
  const ow = small ? Math.max(style.ow, style.owSmall) : style.ow;
  const oc = style.outline(coat);
  const shadeFill = `url(#${style.shadeId})`;
  const rimFill = `url(#${style.rimId})`;
  const kit = {
    lod, small, ow, oc, coat, style,
    /** A filled shape with the style's outline, and (large) its shade and rim light. */
    solid(d, fill, o = {}) {
      const out = [path(d, o.ol === false ? { fill } : { fill, stroke: oc, "stroke-width": f(ow * (o.w || 1)), "stroke-linejoin": "round" })];
      if (!small && o.sh !== false) out.push(path(d, { fill: shadeFill }));
      if (!small && o.rim) out.push(path(d, { fill: rimFill }));
      if (!small && o.key) out.push(path(d, { fill: "url(#lh-key)" }));
      return out;
    },
    /** A flat marking: no outline, no overlay. */
    flat(d, fill, extra) { return path(d, Object.assign({ fill }, extra || {})); },
    /** A stroked line. */
    line(d, stroke, w, extra) { return path(d, Object.assign({ fill: "none", stroke, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round" }, extra || {})); },
    /** The outline alone, for an open contour (the muzzle without its top). */
    contour(d, w = 1) { return path(d, { fill: "none", stroke: oc, "stroke-width": f(ow * w), "stroke-linecap": "round", "stroke-linejoin": "round" }); },
    /** A fine detail that a small badge leaves out. */
    fine(node) { return small ? null : node; },
  };
  return kit;
}
