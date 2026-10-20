/**
 * THE SHARED SVG DEFS: the gradients, patterns and symbols every hound badge on a page draws with.
 *
 * Built ONCE per page: `ensureSharedDefs()` puts one zero-size <svg id="lh-dog-defs"> at the end of <body>, and every badge
 * refers to it with url(#lh-...) and <use href="#lh-..."> instead of carrying its own gradients. A page with forty dogs has one
 * copy of the defs, not forty. Where there is no document body to hold them (the node test harness, a script in the head) the
 * badge carries the same defs inline: `defsNode()` returns them for that, so a badge always draws.
 *
 * The shading is alpha overlays on flat coat colours, so one set of defs serves every coat: a cel shadow (a hard step) or a soft
 * one, a hard or soft rim light from the upper right (the key light is the upper left), the backgrounds' gradients, metallic gold
 * and silver, the street grain, and the symbols for the mascot sunburst, a spray splat and the howl's sound arcs.
 * Nothing here is fetched and nothing depends on a look value, but the eight background keys.
 */

import { n, path } from "./dog-art.js";
import { BACKGROUNDS } from "./dog-look.js";

export const DEFS_ID = "lh-dog-defs";
export const SPARKLE = "M0 -6 L1.7 -1.7 L6 0 L1.7 1.7 L0 6 L-1.7 1.7 L-6 0 L-1.7 -1.7 Z";

const stop = (offset, color, opacity) => n("stop", opacity === undefined ? { offset, "stop-color": color } : { offset, "stop-color": color, "stop-opacity": opacity });
const radial = (id, attrs, stops) => n("radialGradient", Object.assign({ id }, attrs), stops);
const linear = (id, attrs, stops) => n("linearGradient", Object.assign({ id }, attrs), stops);

function rays() {
  const out = [];
  for (let i = 0; i < 12; i++) {
    const a0 = (i * 30 - 6) * Math.PI / 180, a1 = (i * 30 + 6) * Math.PI / 180, r = 150;
    out.push(`M60 66 L${Math.round(60 + r * Math.cos(a0))} ${Math.round(66 + r * Math.sin(a0))} L${Math.round(60 + r * Math.cos(a1))} ${Math.round(66 + r * Math.sin(a1))} Z`);
  }
  return out.join(" ");
}

/** The <defs> node: one copy per page (or one per badge when there is nowhere to share them). */
export function defsNode() {
  const bgs = Object.entries(BACKGROUNDS).map(([key, [a, b]]) => linear(`lh-bg-${key}`, { x1: 0, y1: 0, x2: 0, y2: 1 }, [stop("0", a), stop("1", b)]));
  return n("defs", {}, [
    // shading: the key light is the upper left, the rim light the upper right
    radial("lh-sh-cel", { cx: 0.32, cy: 0.28, r: 0.9 }, [stop("0", "#000000", 0), stop("0.62", "#000000", 0), stop("0.63", "#000000", 0.27), stop("1", "#000000", 0.38)]),
    radial("lh-sh-soft", { cx: 0.32, cy: 0.28, r: 0.95 }, [stop("0", "#000000", 0), stop("0.4", "#000000", 0), stop("1", "#000000", 0.42)]),
    radial("lh-rim-hard", { cx: 0.24, cy: 0.8, r: 1.0 }, [stop("0", "#FFFFFF", 0), stop("0.82", "#FFFFFF", 0), stop("0.83", "#FFFFFF", 0.5), stop("1", "#FFFFFF", 0.62)]),
    radial("lh-rim-soft", { cx: 0.24, cy: 0.8, r: 1.0 }, [stop("0", "#FFFFFF", 0), stop("0.68", "#FFFFFF", 0), stop("1", "#FFFFFF", 0.5)]),
    radial("lh-key", { cx: 0.3, cy: 0.2, r: 0.55 }, [stop("0", "#FFFFFF", 0.22), stop("1", "#FFFFFF", 0)]),
    radial("lh-glow", { cx: 0.5, cy: 0.36, r: 0.62 }, [stop("0", "#FFFFFF", 0.2), stop("1", "#FFFFFF", 0)]),
    radial("lh-vig", { cx: 0.5, cy: 0.52, r: 0.75 }, [stop("0", "#FF2D3D", 0), stop("0.55", "#FF2D3D", 0.04), stop("1", "#FF2D3D", 0.5)]),
    // the tile backgrounds, one per whitelisted key
    ...bgs,
    // metal
    linear("lh-gold", { x1: 0, y1: 0, x2: 1, y2: 1 }, [stop("0", "#FFF3C2"), stop("0.28", "#F0C65A"), stop("0.55", "#A97A22"), stop("0.78", "#F7D77F"), stop("1", "#C99A33")]),
    linear("lh-silver", { x1: 0, y1: 0, x2: 1, y2: 1 }, [stop("0", "#FFFFFF"), stop("0.3", "#CFD6E0"), stop("0.55", "#7C8696"), stop("0.8", "#E6EBF2"), stop("1", "#9AA3B2")]),
    linear("lh-ring", { x1: 0, y1: 0, x2: 1, y2: 1 }, [stop("0", "#FFF3C2"), stop("0.35", "#D9A93C"), stop("0.7", "#7A5A1B"), stop("1", "#F0C65A")]),
    // street grain
    n("pattern", { id: "lh-grit", width: 9, height: 9, patternUnits: "userSpaceOnUse" }, [
      n("circle", { cx: 1.4, cy: 2.1, r: 0.7, fill: "#000000", opacity: ".3" }), n("circle", { cx: 6.2, cy: 5.6, r: 0.5, fill: "#000000", opacity: ".25" }),
      n("circle", { cx: 4.4, cy: 8, r: 0.6, fill: "#FFFFFF", opacity: ".16" }), path("M7 0.5 L8.6 2.4", { stroke: "#000000", "stroke-width": 0.5, opacity: ".24", fill: "none" })]),
    n("clipPath", { id: "lh-tile-clip" }, [n("rect", { x: 0, y: 0, width: 120, height: 120, rx: 26 })]),
    // symbols
    n("symbol", { id: "lh-burst", viewBox: "0 0 120 120", overflow: "visible" }, [path(rays(), { fill: "#FFFFFF", opacity: ".075" })]),
    n("symbol", { id: "lh-splat", viewBox: "0 0 40 40", overflow: "visible" }, [
      n("circle", { cx: 15, cy: 14, r: 8.5, fill: "currentColor" }), n("circle", { cx: 27, cy: 9, r: 3.2, fill: "currentColor" }), n("circle", { cx: 29, cy: 21, r: 2.2, fill: "currentColor" }),
      n("circle", { cx: 6, cy: 24, r: 2, fill: "currentColor" }), n("circle", { cx: 22, cy: 27, r: 1.4, fill: "currentColor" }),
      path("M11.6 20 V34 A1.9 1.9 0 0 0 15.4 34 V20 Z", { fill: "currentColor" })]),
    n("symbol", { id: "lh-sound", viewBox: "0 0 20 36", overflow: "visible" }, [
      path("M3 18 C8 14 8 22 3 18 M3 8 C13 12 13 24 3 28 M3 -2 C19 4 19 32 3 38", { fill: "none", stroke: "currentColor", "stroke-width": 2.4, "stroke-linecap": "round" })]),
  ]);
}

/**
 * Put the shared defs in the page once. Returns true when the page now holds them (so a badge can leave its own out), false when
 * there is nowhere to put them (no document body): the badge then draws with `defsNode()` inline.
 */
export function ensureSharedDefs() {
  try {
    if (typeof document === "undefined" || !document.body || typeof document.getElementById !== "function" || typeof document.createElementNS !== "function") return false;
    if (document.getElementById(DEFS_ID)) return true;
    const host = n("svg", { id: DEFS_ID, width: 0, height: 0, focusable: "false", "aria-hidden": "true", style: "position:absolute;width:0;height:0;overflow:hidden" }, [defsNode()]);
    document.body.appendChild(host);
    return !!document.getElementById(DEFS_ID);
  } catch (err) {
    return false;
  }
}
