/**
 * The locker room's dog-head badge: a small, flat, stylised SVG a builder dog wears everywhere it appears (the
 * model page header, the training camp, the My dogs list). Clean and modern, not a cartoon: a rounded tile in the
 * dog's background colour, a simple head, and the accessories its owner picked.
 *
 * THE LOOK IS A SET OF CHOICES, NEVER MARKUP. `look` is the whitelisted JSON the server validated
 * (src/hounds/interact/look.py): coat, eyes, bg, head, face, neck, body, number. This file maps those KEYS to
 * colours and shapes. A key it does not know falls back to the default, so nothing a server sends can inject a
 * colour string or a node. tests/test_hounds_interact_web.py holds the key lists here to the server's.
 *
 * `dogBadge(look)` returns an <svg> element (decorative by default: the dog's name is always written beside it).
 * `hydrateAvatars(root)` swaps the monogram for the badge wherever a page marks an element with
 * `data-dog-avatar="<hound id>"`, fetching the looks for all of them in one request.
 */

import { s } from "./hounds-core.js";
import { apiGet } from "./api.js";

export const COATS = {
  tan: { base: "#C9A06B", shade: "#9F7746", light: "#E2C79B" },
  black: { base: "#2B2F36", shade: "#14171B", light: "#4A515C" },
  white: { base: "#E9ECF1", shade: "#C3C9D3", light: "#FFFFFF" },
  grey: { base: "#8C95A4", shade: "#646C7A", light: "#B5BCC8" },
  brown: { base: "#7A5638", shade: "#573A24", light: "#9A7455" },
  golden: { base: "#E0B24A", shade: "#BC8B2A", light: "#F1D58F" },
  red: { base: "#B4533C", shade: "#8A3A29", light: "#D07C63" },
  merle: { base: "#7E93B2", shade: "#596C8A", light: "#A9B8CE" },
};
export const EYES = { brown: "#5A3A1E", amber: "#C98A1B", blue: "#4A8FD8", green: "#4BA36B", hazel: "#8A6B2F" };
export const BACKGROUNDS = {
  navy: ["#1B3157", "#0C1730"], slate: ["#38465A", "#1B2330"], charcoal: ["#3A3F48", "#181B20"],
  forest: ["#1F5A40", "#0E2A1E"], maroon: ["#63293A", "#2F121B"], teal: ["#18646C", "#0A2F34"],
  violet: ["#51397F", "#241A3E"], sand: ["#8A7450", "#493C27"],
};
export const HEAD = ["none", "cap", "headband", "visor"];
export const FACE = ["none", "sunglasses"];
export const NECK = ["none", "chain"];
export const BODY = ["none", "hoodie", "jersey"];
export const DEFAULT_LOOK = { coat: "tan", eyes: "brown", bg: "navy", head: "none", face: "none", neck: "none", body: "none", number: null };

const ACCENT = "#2FD07A";
const GOLD = "#E0B24A";
let uid = 0;

/** A look with every key checked against the tables above; anything unknown becomes the default. */
export function cleanLook(look) {
  const src = look && typeof look === "object" ? look : {};
  const pick = (value, allowed, fallback) => (typeof value === "string" && allowed.includes(value) ? value : fallback);
  const number = Number.isInteger(src.number) && src.number >= 0 && src.number <= 99 ? src.number : null;
  const body = pick(src.body, BODY, "none");
  return {
    coat: pick(src.coat, Object.keys(COATS), DEFAULT_LOOK.coat), eyes: pick(src.eyes, Object.keys(EYES), DEFAULT_LOOK.eyes),
    bg: pick(src.bg, Object.keys(BACKGROUNDS), DEFAULT_LOOK.bg), head: pick(src.head, HEAD, "none"),
    face: pick(src.face, FACE, "none"), neck: pick(src.neck, NECK, "none"), body, number: body === "jersey" ? number : null,
  };
}

function bodyShapes(look, coat) {
  if (look.body === "hoodie") {
    return [
      s("path", { d: "M6 82 C6 62 20 55 40 55 C60 55 74 62 74 82 Z", fill: "#3B4455" }),
      s("ellipse", { cx: 40, cy: 57, rx: 23, ry: 9, fill: "#2C3442" }),
      s("path", { d: "M33 60 L32 72 M47 60 L48 72", stroke: "#E9ECF1", "stroke-width": 1.6, "stroke-linecap": "round", fill: "none" }),
    ];
  }
  if (look.body === "jersey") {
    const shapes = [
      s("path", { d: "M6 82 C6 63 20 56 40 56 C60 56 74 63 74 82 Z", fill: "#F2F4F8" }),
      s("path", { d: "M31 56.5 L40 66 L49 56.5", fill: coat.shade, stroke: ACCENT, "stroke-width": 2, "stroke-linejoin": "round" }),
      s("path", { d: "M8 67.5 H72", stroke: ACCENT, "stroke-width": 1.4, opacity: ".85", fill: "none" }),
    ];
    if (look.number !== null) {
      shapes.push(s("text", { x: 40, y: 77.5, "text-anchor": "middle", "font-size": 10.5, "font-weight": 800,
        "font-family": "Arial, Helvetica, sans-serif", fill: "#0E1116", "data-number": String(look.number) }, String(look.number)));
    }
    return shapes;
  }
  return [s("path", { d: "M22 82 C22 66 29 58 40 58 C51 58 58 66 58 82 Z", fill: coat.shade })];
}

function headShapes(look) {
  if (look.head === "cap") {
    return [
      s("path", { d: "M18 29 C18 11 62 11 62 29 C52 25 28 25 18 29 Z", fill: "#1F2937" }),
      s("path", { d: "M21 25 C30 21 50 21 59 25", stroke: ACCENT, "stroke-width": 1.8, fill: "none", "stroke-linecap": "round" }),
      s("path", { d: "M44 28 C54 27 66 28 70 33 C62 35 52 34 44 31 Z", fill: "#111827" }),
      s("circle", { cx: 40, cy: 13.5, r: 2.2, fill: ACCENT }),
    ];
  }
  if (look.head === "headband") {
    return [s("path", { d: "M16 29 C28 21 52 21 64 29 L64.5 34.5 C52 27 28 27 15.5 34.5 Z", fill: ACCENT }),
      s("path", { d: "M16 29 C28 21 52 21 64 29", stroke: "#1E9E5C", "stroke-width": 1, fill: "none" })];
  }
  if (look.head === "visor") {
    return [
      s("path", { d: "M17 29 C28 22 52 22 63 29", stroke: "#E9ECF1", "stroke-width": 3, fill: "none", "stroke-linecap": "round" }),
      s("path", { d: "M23 29 C32 25 48 25 57 29 C55 38 25 38 23 29 Z", fill: "#E9ECF1", opacity: ".92" }),
      s("path", { d: "M26 31.5 C34 29 46 29 54 31.5", stroke: "#B6BDC9", "stroke-width": 1, fill: "none" }),
    ];
  }
  return [];
}

/** The badge as an SVG element. `size` is the pixel width and height. */
export function dogBadge(rawLook, { size = 56, label = "", decorative = true, mood = "idle" } = {}) {
  const look = cleanLook(rawLook);
  const coat = COATS[look.coat];
  const [bgA, bgB] = BACKGROUNDS[look.bg];
  const gradId = `dk-bg-${++uid}`;
  // The head, the eyes and the body are separate groups so CSS can move them (css/lh.css: a slow bob, a blink, a happy
  // wiggle, a slump). No script runs the motion, and prefers-reduced-motion switches it off.
  const eyes = s("g", { class: "dk-eyes" }, [
    s("circle", { cx: 31, cy: 35, r: 4, fill: "#F7F8FA" }), s("circle", { cx: 49, cy: 35, r: 4, fill: "#F7F8FA" }),
    s("circle", { cx: 31.4, cy: 35.4, r: 2.9, fill: EYES[look.eyes] }), s("circle", { cx: 49.4, cy: 35.4, r: 2.9, fill: EYES[look.eyes] }),
    s("circle", { cx: 31.6, cy: 35.6, r: 1.3, fill: "#0B0C0E" }), s("circle", { cx: 49.6, cy: 35.6, r: 1.3, fill: "#0B0C0E" }),
    s("circle", { cx: 32.4, cy: 34.4, r: .8, fill: "#fff" }), s("circle", { cx: 50.4, cy: 34.4, r: .8, fill: "#fff" })]);
  const headKids = [
    // ears behind the head, then the head, the muzzle, the nose and mouth
    s("path", { class: "dk-ear dk-ear--l", d: "M21 25 C9 27 7 45 13 54 C20 56 26 47 27 36 Z", fill: coat.shade }),
    s("path", { class: "dk-ear dk-ear--r", d: "M59 25 C71 27 73 45 67 54 C60 56 54 47 53 36 Z", fill: coat.shade }),
    s("path", { d: "M40 12 C57 12 66 25 65 40 C64 54 54 62 40 62 C26 62 16 54 15 40 C14 25 23 12 40 12 Z", fill: coat.base }),
    s("ellipse", { cx: 40, cy: 49, rx: 14, ry: 11, fill: coat.light }),
    s("ellipse", { cx: 40, cy: 43.5, rx: 5.2, ry: 3.8, fill: "#12151A" }),
    s("path", { d: "M40 47 V51 M34 52 Q40 57 46 52", stroke: "#12151A", "stroke-width": 1.5, fill: "none", "stroke-linecap": "round" }),
    eyes,
  ];
  if (look.face === "sunglasses") {
    headKids.push(
      s("path", { d: "M22 33 H58", stroke: "#0B0C0E", "stroke-width": 1.8, "stroke-linecap": "round" }),
      s("rect", { x: 23.5, y: 30.5, width: 14.5, height: 10, rx: 4, fill: "#0B0C0E" }),
      s("rect", { x: 42, y: 30.5, width: 14.5, height: 10, rx: 4, fill: "#0B0C0E" }),
      s("path", { d: "M26 33 L30 33 M44.5 33 L48.5 33", stroke: "rgba(255,255,255,.55)", "stroke-width": 1.4, "stroke-linecap": "round" }));
  }
  headKids.push(...headShapes(look));
  const kids = [
    s("defs", {}, [s("linearGradient", { id: gradId, x1: 0, y1: 0, x2: 0, y2: 1 }, [
      s("stop", { offset: "0", "stop-color": bgA }), s("stop", { offset: "1", "stop-color": bgB })])]),
    s("rect", { x: 0.5, y: 0.5, width: 79, height: 79, rx: 14, fill: `url(#${gradId})`, stroke: "rgba(255,255,255,.14)" }),
    s("g", { class: "dk-body" }, bodyShapes(look, coat)),
    s("g", { class: "dk-head" }, headKids),
  ];
  if (look.neck === "chain") {
    kids.push(
      s("path", { d: "M25 61 Q40 73 55 61", stroke: GOLD, "stroke-width": 2.4, fill: "none", "stroke-dasharray": "3.2 1.4", "stroke-linecap": "round" }),
      s("circle", { cx: 40, cy: 69, r: 3.4, fill: GOLD, stroke: "#8A6A1F", "stroke-width": .8 }));
  }
  const attrs = { class: "dk-badge", viewBox: "0 0 80 80", width: size, height: size, focusable: "false", "data-mood": mood,
    "data-coat": look.coat, "data-bg": look.bg, "data-head": look.head, "data-face": look.face, "data-neck": look.neck,
    "data-body": look.body };
  if (decorative) attrs["aria-hidden"] = "true"; else { attrs.role = "img"; attrs["aria-label"] = label || "Dog badge"; }
  return s("svg", attrs, kids);
}

// ---- looks for lists of dogs -----------------------------------------------------------------------

/** {dog id: look} for the builder dogs among `ids` that have saved one. Never throws: no looks is an empty map. */
export async function fetchLooks(ids) {
  const wanted = [...new Set((ids || []).filter(Boolean))].slice(0, 40);
  if (!wanted.length) return {};
  try {
    const data = await apiGet(`/hounds/looks?ids=${wanted.map(encodeURIComponent).join(",")}`);
    return data && typeof data.looks === "object" && data.looks ? data.looks : {};
  } catch (err) {
    return {};
  }
}

/** Swap the monogram for the badge on every element under `root` marked `data-dog-avatar="<id>"`. */
export async function hydrateAvatars(root = document, { size } = {}) {
  const nodes = root.querySelectorAll("[data-dog-avatar]");
  if (!nodes.length) return 0;
  const looks = await fetchLooks(nodes.map((n) => n.getAttribute("data-dog-avatar")));
  let swapped = 0;
  for (const node of nodes) {
    const look = looks[node.getAttribute("data-dog-avatar")];
    const parent = node.parentNode;
    if (!look || !parent) continue;
    const px = size || Number(node.getAttribute("data-dog-size")) || 36;
    const badge = dogBadge(look, { size: px });
    badge.setAttribute("data-dog-avatar", node.getAttribute("data-dog-avatar"));
    parent.insertBefore ? parent.insertBefore(badge, node) : parent.appendChild(badge);
    parent.removeChild(node);
    swapped += 1;
  }
  return swapped;
}
