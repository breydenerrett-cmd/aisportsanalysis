/**
 * The hound quiz's inline SVG art (web/quiz.html, web/js/hound-quiz.js): one stroke icon per card, drawn here as path data on a
 * 24x24 grid and built with createElementNS only (hounds-core's `s`), so the node test harness can run it. Nothing is fetched,
 * nothing is raster, no emoji. Every icon key the library uses (config/hounds_archetypes.json) has a drawing here; a test holds
 * the two lists together.
 *
 * `icon(key, {size})` is the glyph; `tile(key, {tone, size})` is the glyph on its rounded, tinted card art tile, the "pin" of the
 * Pinterest-style grid. Colour comes from CSS (`--qz-a` / `--qz-b` per tone in css/quiz.css), never from data.
 */

import { s } from "./hounds-core.js";

/** key -> list of path strings (stroke, no fill). Hand-drawn to read at 28 to 64px. */
export const PATHS = {
  flame: ["M12 3c1 3 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-9z"],
  moon: ["M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z", "M16 4v3M14.5 5.5h3"],
  wave: ["M2 8c3-3 5 3 8 0s5 3 8 0 3-1 4 0", "M2 15c3-3 5 3 8 0s5 3 8 0 3-1 4 0"],
  target: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z", "M12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"],
  hourglass: ["M6 3h12M6 21h12", "M7 3c0 5 5 6 5 9s-5 4-5 9M17 3c0 5-5 6-5 9s5 4 5 9"],
  road: ["M8 3 5 21M16 3l3 18", "M12 5v3M12 11v3M12 17v3"],
  house: ["M3 11l9-7 9 7", "M5 10v10h14V10", "M10 20v-6h4v6"],
  bolt: ["M13 2 4 14h7l-1 8 9-12h-7z"],
  crown: ["M3 8l4 4 5-7 5 7 4-4-2 11H5z"],
  wind: ["M3 8h11a3 3 0 1 0-3-3", "M3 12h16a3 3 0 1 1-3 3", "M3 16h8a2 2 0 1 1-2 2"],
  coin: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 7v10", "M9.5 9.8c0-1.2 1.2-1.8 2.5-1.8s2.5.6 2.5 1.8-1.2 1.6-2.5 2-2.5.8-2.5 2 1.2 1.9 2.5 1.9 2.5-.7 2.5-1.9"],
  letters: ["M3 19 7.5 6 12 19M5 14.5h5", "M15 6h5l-5 13h5"],
  stars: ["M12 3l1.8 4.6 4.7.4-3.6 3 1.1 4.7L12 13.3 8 15.7l1.1-4.7-3.6-3 4.7-.4z", "M19 4v3M17.5 5.5h3M5 17v3M3.5 18.5h3"],
  football: ["M4.5 19.5C3 12 8 4.5 19.5 4.5 21 12 16 19.5 4.5 19.5z", "M9 15l6-6M10.5 12.5l1 1M12.5 10.5l1 1"],
  plus: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 8v8M8 12h8"],
  bone: ["M7.2 4.2a2.3 2.3 0 0 0-3.1 3.1 2.3 2.3 0 0 0 1.3 4.2L12.5 18.6a2.3 2.3 0 0 0 4.2 1.3 2.3 2.3 0 0 0 3.1-3.1 2.3 2.3 0 0 0-1.3-4.2L11.4 5.4A2.3 2.3 0 0 0 7.2 4.2z"],
  gremlin: ["M4 10l2-6 4 3M20 10l-2-6-4 3", "M5 13a7 7 0 0 0 14 0c0-4-3-6-7-6s-7 2-7 6z", "M9 12h.01M15 12h.01M9.5 16.5c1.5 1 3.5 1 5 0"],
  tv: ["M4 7h16v12H4z", "M9 3l3 4 3-4"],
  snow: ["M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9", "M9 4l3 2 3-2M9 20l3-2 3 2"],
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"],
  rain: ["M7 15a4 4 0 0 1 .5-8 5 5 0 0 1 9.5 1.5A3.5 3.5 0 0 1 17 15z", "M8 18l-1 3M12 18l-1 3M16 18l-1 3"],
  plane: ["M21 3 3 11l6 2 2 6z", "M9 13 21 3"],
  calendar: ["M4 6h16v14H4z", "M4 10h16M8 3v4M16 3v4", "M8 14h2M14 14h2M8 17h2"],
  key: ["M14 10a4 4 0 1 0-1 2.5L20 20", "M17 17l2-2M15 15l2-2"],
  kick: ["M4 21V9M20 21V9M4 9h16M12 9v12", "M9 3v6M15 3v6"],
  feather: ["M20 4c-8 0-14 5-14 13l-2 3", "M20 4c0 8-5 13-13 13M10 14l6-6"],
  rocket: ["M12 3c4 2 6 7 4 13H8c-2-6 0-11 4-13z", "M9 16l-3 3 3 1M15 16l3 3-3 1", "M12 8.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z"],
  twins: ["M9 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z", "M15 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"],
  chart: ["M4 20V4M4 20h16", "M8 16l4-5 3 3 5-7"],
  paw: ["M12 12.5c-3 0-5.5 2.4-5.5 4.7 0 1.8 2 2.8 5.5 2.8s5.5-1 5.5-2.8c0-2.3-2.5-4.7-5.5-4.7z",
        "M5.5 9.5a1.5 2.1 0 1 0 0 .1M9.5 5.5a1.5 2.2 0 1 0 0 .1M14.5 5.5a1.5 2.2 0 1 0 0 .1M18.5 9.5a1.5 2.1 0 1 0 0 .1"],
  cloud: ["M7 18a4 4 0 0 1 .5-8 5 5 0 0 1 9.5 1.5A3.5 3.5 0 0 1 17 18z"],
  trophy: ["M8 4h8v5a4 4 0 0 1-8 0z", "M8 6H4v1a4 4 0 0 0 4 4M16 6h4v1a4 4 0 0 1-4 4", "M12 13v4M8 21h8M10 17h4"],
  ruler: ["M3 15 15 3l6 6L9 21z", "M7 11l2 2M10 8l2 2M13 5l2 2"],
  updown: ["M8 20V5M5 8l3-3 3 3", "M16 4v15M13 16l3 3 3-3"],
  bat: ["M4 20 14.5 9.5", "M3 21l1.5-1.5", "M14.5 9.5c2-2 4-3.5 6.5-5.5-2 2.5-3.5 4.5-5.5 6.5z", "M19 17a2 2 0 1 0 0 .1"],
  dice: ["M5 5h14v14H5z", "M9 9h.01M15 9h.01M12 12h.01M9 15h.01M15 15h.01"],
  scale: ["M12 4v16M6 20h12M5 8h14", "M5 8l-3 7a3 3 0 0 0 6 0z", "M19 8l-3 7a3 3 0 0 0 6 0z"],
  anchor: ["M12 3.5a1.8 1.8 0 1 0 0 .1", "M12 6v15M8 10h8", "M5 13a7 7 0 0 0 14 0M4 13h3M17 13h3"],
  sunrise: ["M3 18h18M7 18a5 5 0 0 1 10 0", "M12 5v4M5 10l2 2M19 10l-2 2M9 6l3-3 3 3"],
  clock: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 7v5l3 2"],
  baseball: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M6 5c3 3 3 11 0 14M18 5c-3 3-3 11 0 14", "M7.5 8.5l1.5-.5M7.5 12l1.8 0M7.5 15.5l1.5.5M16.5 8.5 15 8M16.5 12h-1.8M16.5 15.5 15 16"],
  both: ["M3 14a5 5 0 1 0 10 0 5 5 0 0 0-10 0z", "M11 8.5l7.5 7M14 5.5C19 6 21 9.5 20.5 14c-4-.5-7-3-6.5-8.5z"],
  look: ["M12 5c-4 0-7 3-7 7v6h14v-6c0-4-3-7-7-7z", "M9 12h.01M15 12h.01M10 16c1 .8 3 .8 4 0", "M5 9 3 4l4 2M19 9l2-5-4 2"],
  mix: ["M4 7h16M4 12h16M4 17h16", "M8 4v6M16 9v6M11 14v6"],
  check: ["M5 12.5 10 17.5 19 7"],
  arrow: ["M5 12h14M13 6l6 6-6 6"],
  back: ["M19 12H5M11 6l-6 6 6 6"],
};

export const ICON_KEYS = Object.keys(PATHS);

/** The glyph as an <svg>. An unknown key draws a paw rather than nothing. */
export function icon(key, { size = 28, stroke = 1.6, cls = "" } = {}) {
  const paths = PATHS[key] || PATHS.paw;
  return s("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", "stroke-width": stroke,
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false",
    class: `qz-icon${cls ? ` ${cls}` : ""}`, "data-icon": PATHS[key] ? key : "paw" }, paths.map((d) => s("path", { d })));
}

/** The glyph on its tinted art tile: the picture half of a pin. `tone` picks the colours in css/quiz.css. */
export function tile(key, { tone = "mint", size = 40 } = {}) {
  const wrap = document.createElement("span");
  wrap.setAttribute("class", "qz-art");
  wrap.setAttribute("data-tone", tone);
  wrap.setAttribute("aria-hidden", "true");
  wrap.appendChild(s("svg", { viewBox: "0 0 120 72", class: "qz-art__bg", focusable: "false", "aria-hidden": "true" }, [
    s("circle", { cx: 98, cy: 12, r: 34, class: "qz-art__blob qz-art__blob--a" }),
    s("circle", { cx: 14, cy: 66, r: 28, class: "qz-art__blob qz-art__blob--b" }),
    s("path", { d: "M0 56 Q30 44 60 54 T120 48", class: "qz-art__line", fill: "none" })]));
  const glyph = document.createElement("span");
  glyph.setAttribute("class", "qz-art__glyph");
  glyph.appendChild(icon(key, { size }));
  wrap.appendChild(glyph);
  return wrap;
}

/** A tone for a library card from what it is about, so the grid reads as a palette and not as one colour. */
export function toneFor(row) {
  const tags = (row && row.tags) || [];
  const has = (t) => tags.includes(t);
  if (has("mystic") || has("moon") || has("silly")) return "violet";
  if (has("weather")) return "sky";
  if (has("steam") || has("market")) return "gold";
  if (has("props")) return "mint";
  if (has("nfl")) return "lime";
  if (row && row.stance === "dog") return "ember";
  if (row && row.stance === "chalk") return "sky";
  return "rose";
}
