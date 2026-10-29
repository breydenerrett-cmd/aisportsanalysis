/**
 * PICK METERS -- the two ratings on a pick, drawn as two half-dial gauges: CONFIDENCE (Low to High) and VALUE (Overpriced,
 * Fair, Value), each with a needle, a numeric score, a word, and the sentence behind it. Owner ruling 2026-10-29: "each pick
 * publicly graded based on confidence and value ... with the reasoning behind them."
 *
 * HONESTY BOUNDARY (the same one web/js/valuemeter.js keeps -- read before touching this file)
 * -------------------------------------------------------------------
 * The client computes NOTHING. Every number, word and sentence here is the `grades` block the server sent for the ticket
 * (GET /hounds/{id}/bets, src/hounds/pick_grades.py): the scores, the labels, the reasons, the closing-line chip. This file
 * turns a score into a needle ANGLE (geometry, like a bar's width) and a label into a zone COLOUR (the label is the server's
 * word, never re-derived from the score). A missing or malformed input renders "Not yet available" -- a greyed dial with no
 * needle -- never a needle parked at 0, because 0 is a reading and "no reading" is not.
 *
 * WHAT THE METERS ARE: the hound's own record against the prices it took, settled before the pick was placed. Confidence is
 * NOT a win chance and the page says so; the whole block ends "Not a promise. Paper bets only."
 *
 * MOTION. The needle sweeps from the left end to its score over ~600 ms, once, and ONLY for a viewer who has not asked for
 * reduced motion (`prefers-reduced-motion: no-preference`). Everyone else gets the needle already at rest on its score.
 * The sweep starts when the dial is actually on screen (IntersectionObserver), so a long ticket list animates what the person
 * is looking at, and a dial inside a closed "Why this bet" fold sweeps when it is opened.
 *
 * STYLES. The page does not have to list css/pick-meters.css: the first render links it once (see `ensurePickMeterStyles`).
 */

import { h, s, isNum } from "./hounds-core.js";

export const NOTE = "Not a promise. Paper bets only.";
export const NOT_A_WIN_CHANCE = "Confidence is not a win chance.";
export const NA = "Not yet available";

/** The dial's geometry in the SVG's own units: a half circle centred on (CX, CY). */
const CX = 60;
const CY = 60;
const R = 46;
const NEEDLE_LEN = 38;
const GAP_DEG = 1.6;

/**
 * Where the coloured zones of each dial start and end, in score points. These MIRROR the server's label thresholds
 * (src/hounds/pick_grades.py: value under 40 / 40-60 / over 60, confidence under 35 / 35-65 / over 65); a test pins that they
 * agree. They only decide where the arc changes colour; the word under the dial is always the server's.
 */
export const ZONES = {
  confidence: { bounds: [0, 35, 65, 100], names: ["Low", "Medium", "High"], ends: ["Low", "", "High"] },
  value: { bounds: [0, 40, 60, 100], names: ["Overpriced", "Fair", "Value"], ends: ["Overpriced", "Fair", "Value"] },
};
const TITLES = { confidence: "Confidence", value: "Value" };
const ZONE_CLASS = ["lo", "mid", "hi"];

const CSS_HREF_FALLBACK = "css/pick-meters.css";
const STYLE_ATTR = "data-pick-meters-css";

// ---- tiny class helpers (the page harness's fake elements have no classList) ----------------------

function addClass(node, name) {
  const have = (node.getAttribute("class") || "").split(/\s+/).filter(Boolean);
  if (!have.includes(name)) node.setAttribute("class", have.concat(name).join(" "));
}

// ---- styles, once ----------------------------------------------------------------------------------

let styleHref = null;

function cssHref() {
  if (styleHref) return styleHref;
  try {
    styleHref = new URL("../css/pick-meters.css", import.meta.url).href;
  } catch (err) {
    styleHref = CSS_HREF_FALLBACK;     // a page one level up from js/ finds it at css/
  }
  return styleHref;
}

/**
 * Link css/pick-meters.css into the page's <head> once, so no HTML file has to list it. Returns true when it added the link,
 * false when it was already there or the page has no <head> (a test's fake document). Never throws: styles are decoration.
 */
export function ensurePickMeterStyles(doc = globalThis.document) {
  try {
    const head = doc && (doc.head || (doc.querySelector && doc.querySelector("head")));
    if (!head) return false;
    if (doc.querySelector && doc.querySelector(`link[${STYLE_ATTR}]`)) return false;
    const link = doc.createElement("link");
    link.setAttribute("rel", "stylesheet");
    link.setAttribute("href", cssHref());
    link.setAttribute(STYLE_ATTR, "1");
    head.appendChild(link);
    return true;
  } catch (err) {
    return false;
  }
}

// ---- motion ----------------------------------------------------------------------------------------

/** True only when the viewer has NOT asked for reduced motion. With no matchMedia at all the answer is no: static is the safe side. */
export function motionAllowed() {
  try {
    const mm = (globalThis.window && globalThis.window.matchMedia) || globalThis.matchMedia;
    return typeof mm === "function" && !!mm.call(globalThis.window || globalThis, "(prefers-reduced-motion: no-preference)").matches;
  } catch (err) {
    return false;
  }
}

/** Start the sweep: add the "in" class (CSS moves the needle from the left end to its score). */
function armSweep(root) {
  const go = () => addClass(root, "pm--in");
  if (typeof IntersectionObserver === "function") {
    const watcher = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { watcher.disconnect(); go(); }
    }, { threshold: 0.3 });
    watcher.observe(root);
    return;
  }
  setTimeout(go, 30);
}

/** Play the sweep again (a fold being opened): back to the left end, then to the score on the next frame. */
export function replayPickMeters(root) {
  if (!root || !root.getAttribute || !/\bpm--anim\b/.test(root.getAttribute("class") || "")) return;
  const rest = (root.getAttribute("class") || "").split(/\s+/).filter((c) => c && c !== "pm--in");
  root.setAttribute("class", rest.join(" "));
  const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn) => setTimeout(fn, 16);
  raf(() => raf(() => addClass(root, "pm--in")));
}

// ---- the dial --------------------------------------------------------------------------------------

function point(deg, radius) {
  const rad = (deg * Math.PI) / 180;               // 0 is the left end, 180 the right end, the arc passes over the top
  return [CX - radius * Math.cos(rad), CY - radius * Math.sin(rad)];
}

function arc(fromDeg, toDeg) {
  const [x0, y0] = point(fromDeg, R);
  const [x1, y1] = point(toDeg, R);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${R} ${R} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/** The needle's rest angle for a score: 0 is the far left (-90deg), 50 straight up, 100 the far right (+90deg). */
export function needleAngle(score) {
  return ((Math.max(0, Math.min(100, score)) - 50) * 1.8);
}

/** The zone (0, 1, 2) the SERVER's word for the reading names, or -1 when it is not one of the dial's words. */
function zoneOf(kind, label) {
  return ZONES[kind].names.indexOf(label);
}

function gauge(kind, score, label) {
  const { bounds } = ZONES[kind];
  const live = isNum(score);
  const active = live ? zoneOf(kind, label) : -1;
  const arcs = [];
  for (let i = 0; i < 3; i += 1) {
    const from = bounds[i] * 1.8 + (i === 0 ? 0 : GAP_DEG / 2);
    const to = bounds[i + 1] * 1.8 - (i === 2 ? 0 : GAP_DEG / 2);
    arcs.push(s("path", { d: arc(from, to), class: `pm__zone pm__zone--${ZONE_CLASS[i]}${i === active ? " pm__zone--on" : ""}`,
      fill: "none" }));
  }
  const kids = arcs.slice();
  if (live) {
    kids.push(s("g", { class: "pm__needle", style: `--pm-angle:${needleAngle(score).toFixed(1)}deg` }, [
      s("line", { x1: CX, y1: CY, x2: CX, y2: CY - NEEDLE_LEN, class: "pm__stem" })]));
  }
  kids.push(s("circle", { cx: CX, cy: CY, r: 4.5, class: "pm__hub" }));
  return s("svg", { viewBox: "0 0 120 68", class: "pm__svg", "aria-hidden": "true", focusable: "false" }, kids);
}

/** One dial with its title, its reading and (full size) the ends of its scale. */
function dial(kind, block, compact) {
  const live = !!block && typeof block === "object" && isNum(block.score);
  const label = live && typeof block.label === "string" ? block.label : "";
  const title = TITLES[kind];
  const box = h("div", { class: `pm__dial pm__dial--${kind}${live ? "" : " pm__dial--na"}`, "data-meter": kind });
  box.appendChild(h("div", { class: "pm__title", text: title }));
  const face = h("div", live
    ? { class: "pm__gauge", role: "meter", "aria-label": title, "aria-valuemin": "0", "aria-valuemax": "100",
      "aria-valuenow": String(block.score), "aria-valuetext": label || String(block.score) }
    : { class: "pm__gauge", role: "img", "aria-label": `${title}: ${NA.toLowerCase()}` });
  face.appendChild(gauge(kind, live ? block.score : null, label));
  box.appendChild(face);
  box.appendChild(h("div", { class: "pm__read" }, live
    ? [h("strong", { class: "pm__num", "data-hook": `meter-${kind}-score`, text: String(block.score) }),
      h("span", { class: "pm__label", "data-hook": `meter-${kind}-label`, text: label })]
    : [h("span", { class: "pm__label pm__label--na", "data-hook": `meter-${kind}-label`, text: NA })]));
  if (!compact) {
    const ends = ZONES[kind].ends;
    box.appendChild(h("div", { class: "pm__scale", "aria-hidden": "true" }, ends.map((word) => h("span", { text: word }))));
  }
  return box;
}

function reasonText(block) {
  return block && typeof block === "object" && typeof block.reason === "string" ? block.reason : "";
}

/** The sentence behind each score. When both dials have the same sentence (no record to read yet) it is said once. */
function reasonLines(g) {
  const conf = reasonText(g.confidence);
  const value = reasonText(g.value);
  if (conf && conf === value) return [h("p", { class: "pm__reason", "data-hook": "meter-reason", text: conf })];
  return [["confidence", conf], ["value", value]].filter(([, text]) => text).map(([kind, text]) =>
    h("p", { class: `pm__reason pm__reason--${kind}`, "data-hook": `meter-${kind}-reason` }, [
      h("strong", { text: `${TITLES[kind]}. ` }), text]));
}

/** "Beat the close +1.3 pts": the closing-line chip of a settled pick, from the server's block. null for an open pick. */
function clvChip(clv) {
  if (!clv || typeof clv !== "object" || typeof clv.label !== "string") return null;
  const pts = isNum(clv.pts) ? ` ${clv.pts > 0 ? "+" : clv.pts < 0 ? "-" : ""}${Math.abs(clv.pts).toFixed(1)} pts` : "";
  const tone = clv.label.startsWith("Beat") ? "up" : clv.label.startsWith("Missed") ? "down" : "flat";
  return h("span", { class: `pm__clv pm__clv--${tone}`, "data-hook": "meter-clv", text: `${clv.label}${pts}` });
}

/**
 * The two gauges for one pick.
 *
 * @param {object|null} grades  the ticket's `grades` block ({value, confidence, clv}); null or malformed: both dials read "Not yet available"
 * @param {object} opts
 *   compact  true: dials and their readings only, for a ticket card's face. false (default): the scale ends, the two
 *            sentences behind the scores and the closing-line chip as well.
 *   dials    false leaves the dials out and keeps only the sentences and the closing-line chip (a card's "Why this bet" fold,
 *            whose face already shows the dials).
 *   note     false leaves the "Not a promise" line off (that same fold: its face carries the line).
 */
export function renderPickMeters(grades, { compact = false, dials = true, note = true } = {}) {
  ensurePickMeterStyles();
  const g = grades && typeof grades === "object" ? grades : {};
  const animate = dials && motionAllowed();
  const root = h("section", { class: `pm ${compact ? "pm--compact" : "pm--full"} ${animate ? "pm--anim" : "pm--static"}`,
    "data-hook": dials ? "pick-meters" : "pick-reasons", "aria-label": dials ? "Pick ratings: confidence and value" : "Why these ratings" });
  if (dials) root.appendChild(h("div", { class: "pm__dials" }, [dial("confidence", g.confidence, compact), dial("value", g.value, compact)]));
  if (!compact) {
    const lines = reasonLines(g);
    if (lines.length) root.appendChild(h("div", { class: "pm__why" }, lines));
    const chip = clvChip(g.clv);
    if (chip) root.appendChild(h("div", { class: "pm__clvrow" }, [chip]));
  }
  if (note) {
    root.appendChild(h("p", { class: "pm__note", "data-hook": "meter-note", text: compact ? `${NOT_A_WIN_CHANCE} ${NOTE}` : NOTE }));
  }
  if (animate) armSweep(root);
  return root;
}

/**
 * The one-line form for a table cell: "C 72 · V 61" (confidence, value), with the words in the tooltip. "–" stands for a
 * dial that is not yet available. null when the ticket carries no grades block at all.
 */
export function gradeChip(grades) {
  if (!grades || typeof grades !== "object") return null;
  const part = (block) => (block && isNum(block.score) ? String(block.score) : "–");
  const word = (kind, block) => (block && isNum(block.score) ? `${TITLES[kind]} ${block.score} (${block.label || ""})` : `${TITLES[kind]}: ${NA.toLowerCase()}`);
  return h("small", { class: "pm-chip", "data-hook": "grade-chip",
    title: `${word("confidence", grades.confidence)}; ${word("value", grades.value)}. ${NOT_A_WIN_CHANCE} ${NOTE}`,
    text: `C ${part(grades.confidence)} · V ${part(grades.value)}` });
}

/**
 * The table and list-row form: a fold whose summary is the one-line chip ("C 72 · V 61") and whose body is the full meters with
 * their sentences. The body is built the first time the fold is opened, so a 50-row table pays for nothing it does not show.
 * null when the ticket carries no grades block.
 */
export function gradeFold(grades) {
  const chip = gradeChip(grades);
  if (!chip) return null;
  const box = h("details", { class: "pm-fold", "data-hook": "grade-fold" }, [h("summary", { "aria-label": "Show the ratings and the reasons behind them" }, [chip])]);
  let built = false;
  box.addEventListener("toggle", () => {
    if (box.getAttribute("open") === null) return;
    if (!built) {
      built = true;
      box.appendChild(renderPickMeters(grades, { compact: false }));
    } else {
      replayPickMeters(box.querySelector ? box.querySelector(".pm") : null);
    }
  });
  return box;
}
