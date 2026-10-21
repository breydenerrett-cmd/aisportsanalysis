/**
 * THE KENNEL ROOM, drawn: pure SVG, CSS and DOM (no image file, no script tag on the page, no innerHTML). The hounds are the product's own illustrated
 * dogs (dog-avatar.js dogFace, the same art as the kennel cards and the leaderboard), so each one looks like itself; the room around them is flat
 * vector furniture in the dark theme. Every state a hound shows comes from room-adapter.js, and that from real endpoints (room-data.js): nothing here
 * moves, jumps or rains unless the record says so. docs/design/KENNEL_ROOM.md is the state table.
 *
 *   mountRoom(host, { scope, data, onStudio, note })       the public house room (room.html) or a member's room
 *   mountKennelRoom(host, kennelPayload, { onStudio })     "Your kennel room", a collapsible block at the top of My Kennel (kennel.js calls it)
 *
 * TAPPABLE: a hound opens its card (a sheet with a link to hound.html?id=...; a member's own hound adds the studio actions); the whiteboard is the
 * Leaderboard, the TV is Live, the door is My Kennel, the corner stone is the Graveyard; the bulletin board is a placeholder for the daily recap.
 * PHONE FIRST: the stage keeps a minimum width inside its frame and pans there; the page itself never scrolls sideways (css/room.css).
 * MOTION: every animation is CSS inside prefers-reduced-motion: no-preference; reduced motion keeps each state's static pose and props.
 * SOUND: off. The toggle is an extra; it plays a short tone when a hound's state CHANGES to won or lost between two polls (a first load is silent).
 * POLLING: every POLL_MS (45 s), paused while the tab is hidden, refreshed at once when it comes back, stopped while the block is folded away.
 *
 * Written against attributes only (no classList / dataset / innerHTML) so the node test harness's small DOM can run it.
 */

import { h, s, clearNode, isNum, houndHref } from "./hounds-core.js";
import { dogFace, setPose } from "./dog-avatar.js";
import { build, fmtUnits, inText } from "./room-adapter.js";
import { bubbleParts, assignTiers, placeLabels } from "./room-layout.js";
import { loadHouse, loadKennel, POLL_MS } from "./room-data.js";
import { trainedBadge } from "./dog-headstone.js";

export const VIEW = { w: 1000, h: 600 };

/** Feet positions in view units (x 0-1000, y 0-600) for each zone, in the order hounds take them. */
export const SLOTS = {
  desk: [[110, 478], [216, 478], [322, 478], [428, 478], [534, 478], [640, 478], [110, 562], [216, 562], [322, 562], [428, 562], [534, 562], [640, 562]],
  floor: [[130, 322], [240, 322], [350, 322], [460, 322]],
  bowl: [[540, 352], [610, 352], [680, 352]],
  bed: [[775, 478], [860, 478], [945, 478], [775, 562], [860, 562], [945, 562]],
  gym: [[790, 338], [890, 338]],
};
/** Where a hound goes when its zone is full: spare floor, left to right. */
export const SPARE = [[100, 404], [210, 404], [320, 404], [430, 404], [540, 404], [650, 404], [760, 404], [870, 404]];

const SHEET_LINKS = { board: "hounds.html", tv: "live.html", door: "kennel.html", stone: "graveyard.html" };

const pct = (v, total) => `${Math.round((v / total) * 10000) / 100}%`;
const place = (x, y) => `left:${pct(x, VIEW.w)};top:${pct(y, VIEW.h)}`;
const clip = (str, n) => { const t = String(str == null ? "" : str); return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t; };

// ---- the room around the hounds ---------------------------------------------------------------------------

function defs() {
  return s("defs", {}, [
    s("linearGradient", { id: "rm-g-wall", x1: "0", y1: "0", x2: "0", y2: "1" }, [s("stop", { offset: "0", class: "rm-stop rm-stop--wall-a" }), s("stop", { offset: "1", class: "rm-stop rm-stop--wall-b" })]),
    s("linearGradient", { id: "rm-g-floor", x1: "0", y1: "0", x2: "0", y2: "1" }, [s("stop", { offset: "0", class: "rm-stop rm-stop--floor-a" }), s("stop", { offset: "1", class: "rm-stop rm-stop--floor-b" })]),
    s("radialGradient", { id: "rm-g-glow", cx: "0.5", cy: "0.15", r: "0.7" }, [s("stop", { offset: "0", class: "rm-stop rm-stop--glow-a" }), s("stop", { offset: "1", class: "rm-stop rm-stop--glow-b" })]),
  ]);
}

function backdrop(usedDesks, usedBeds) {
  const seams = [];
  for (let i = 0; i < 15; i++) seams.push(s("line", { class: "rm-seam", x1: 70 * i + (i % 2 ? 20 : 45), y1: 256, x2: 70 * i + (i % 2 ? 20 : 45) - 24, y2: 600 }));
  [310, 372, 440, 518].forEach((y) => seams.push(s("line", { class: "rm-seam rm-seam--h", x1: 0, y1: y, x2: 1000, y2: y })));
  const desks = SLOTS.desk.filter((_, i) => i < 6 || usedDesks.has(i)).map(([x, y]) => s("g", { class: "rm-desk" }, [
    s("rect", { class: "rm-desk__front", x: x - 46, y: y + 6, width: 92, height: 30, rx: 5 }),
    s("rect", { class: "rm-desk__top", x: x - 51, y: y - 4, width: 102, height: 11, rx: 4 }),
    s("rect", { class: "rm-desk__phone", x: x + 33, y: y - 17, width: 11, height: 15, rx: 2 }),
    s("rect", { class: "rm-desk__screen", x: x + 35, y: y - 15, width: 7, height: 10, rx: 1 })]));
  // the first row of beds is always there (an honest empty room shows empty beds); the second row only when a hound is in it
  const beds = SLOTS.bed.filter((_, i) => i < 3 || usedBeds.has(i)).map(([x, y]) => s("g", { class: "rm-bed" }, [
    s("ellipse", { class: "rm-bed__rim", cx: x, cy: y + 9, rx: 52, ry: 20 }),
    s("ellipse", { class: "rm-bed__fill", cx: x, cy: y + 6, rx: 41, ry: 13 })]));
  return s("svg", { class: "rm-bg", viewBox: `0 0 ${VIEW.w} ${VIEW.h}`, preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true", focusable: "false" }, [
    defs(),
    s("rect", { class: "rm-wall", x: 0, y: 0, width: 1000, height: 256, fill: "url(#rm-g-wall)" }),
    s("rect", { class: "rm-floor", x: 0, y: 256, width: 1000, height: 344, fill: "url(#rm-g-floor)" }),
    s("rect", { class: "rm-glow", x: 0, y: 0, width: 1000, height: 600, fill: "url(#rm-g-glow)" }),
    s("rect", { class: "rm-baseboard", x: 0, y: 248, width: 1000, height: 10 }),
    s("g", {}, seams),
    s("ellipse", { class: "rm-rug", cx: 295, cy: 334, rx: 270, ry: 36 }),
    ...desks,
    ...beds,
    // the water bowl
    s("g", { class: "rm-bowl" }, [s("ellipse", { class: "rm-bowl__rim", cx: 610, cy: 372, rx: 34, ry: 11 }), s("ellipse", { class: "rm-bowl__water", cx: 610, cy: 370, rx: 26, ry: 7 })]),
    // the gym mat, the dumbbell and the sign
    s("g", { class: "rm-gym" }, [
      s("rect", { class: "rm-gym__mat", x: 730, y: 310, width: 220, height: 50, rx: 10 }),
      s("rect", { class: "rm-gym__bar", x: 822, y: 332, width: 56, height: 4, rx: 2 }),
      s("rect", { class: "rm-gym__plate", x: 814, y: 323, width: 8, height: 22, rx: 2 }), s("rect", { class: "rm-gym__plate", x: 878, y: 323, width: 8, height: 22, rx: 2 }),
      s("text", { class: "rm-label", x: 740, y: 302, "text-anchor": "start", text: "GYM" })]),
    s("text", { class: "rm-label", x: 775, y: 384, "text-anchor": "start", text: "BEDS" }),
  ]);
}

/** A prop that is a link (anchor) or, with no href, a button. Its box is in view units. */
function prop(kind, box, attrs, art, kids) {
  const [x, y, w, hh] = box;
  const style = `left:${pct(x, VIEW.w)};top:${pct(y, VIEW.h)};width:${pct(w, VIEW.w)};height:${pct(hh, VIEW.h)}`;
  const base = Object.assign({ class: `rm-prop rm-prop--${kind}`, style, "data-hook": `room-${kind}` }, attrs);
  const svg = s("svg", { viewBox: `0 0 ${w} ${hh}`, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" }, art);
  return h(attrs.href ? "a" : "button", attrs.href ? base : Object.assign(base, { type: "button" }), [svg, ...(kids || [])]);
}

function textLine(x, y, str, cls, extra) {
  return s("text", Object.assign({ class: cls, x, y, text: str }, extra || {}));
}

function whiteboard(model) {
  const rows = model.whiteboard.map((r, i) => [
    textLine(16, 62 + i * 34, String(i + 1), "rm-t rm-t--rank"),
    textLine(36, 62 + i * 34, clip(r.name, 15), "rm-t rm-t--name"),
    textLine(224, 62 + i * 34, `${fmtUnits(r.units)}`, "rm-t rm-t--units", { "text-anchor": "end" }),
    textLine(224, 74 + i * 34, `${r.bets} settled`, "rm-t rm-t--sub", { "text-anchor": "end" })]);
  const art = [
    s("rect", { class: "rm-board__frame", x: 0, y: 0, width: 240, height: 172, rx: 8 }),
    s("rect", { class: "rm-board__face", x: 6, y: 6, width: 228, height: 160, rx: 5 }),
    textLine(16, 28, "LEADERBOARD", "rm-t rm-t--title"),
    ...(rows.length ? rows.flat() : [textLine(16, 66, `Ranked at ${model.minRanked} settled bets.`, "rm-t rm-t--sub"), textLine(16, 90, "Tap for the full table.", "rm-t rm-t--sub")]),
    s("rect", { class: "rm-board__tray", x: 20, y: 166, width: 200, height: 6, rx: 3 })];
  return prop("board", [40, 34, 240, 172], { href: "hounds.html", "aria-label": "Leaderboard: the full table of every hound" }, art);
}

function tv(model) {
  const t = model.ticker;
  const facts = [`${t.open} open ${t.open === 1 ? "ticket" : "tickets"}`, t.live ? `${t.live} ${t.live === 1 ? "hound" : "hounds"} with a game live` : "", t.games !== null ? `${t.games} ${t.games === 1 ? "game" : "games"} left on today's board` : ""].filter(Boolean);
  const art = [
    s("rect", { class: "rm-tv__bezel", x: 0, y: 0, width: 320, height: 150, rx: 10 }),
    s("rect", { class: "rm-tv__screen", x: 8, y: 8, width: 304, height: 134, rx: 6 }),
    s("circle", { class: "rm-tv__dot", cx: 24, cy: 26, r: 4 }),
    textLine(36, 30, "LIVE", "rm-t rm-t--title"),
    ...facts.slice(0, 3).map((f, i) => textLine(20, 62 + i * 26, clip(f, 34), "rm-t rm-t--tv")),
    s("rect", { class: "rm-tv__strip", x: 8, y: 118, width: 304, height: 24, rx: 4 }),
    textLine(18, 134, "Every ticket is paper and graded in public", "rm-t rm-t--tick", { "data-hook": "room-tick" })];
  return prop("tv", [320, 40, 320, 150], { href: "live.html", "aria-label": `Live: what is on right now. ${facts.join(", ")}` }, art);
}

function bulletin() {
  const art = [
    s("rect", { class: "rm-cork__frame", x: 0, y: 0, width: 120, height: 172, rx: 8 }),
    s("rect", { class: "rm-cork__face", x: 6, y: 6, width: 108, height: 160, rx: 5 }),
    s("rect", { class: "rm-cork__paper", x: 20, y: 28, width: 80, height: 96, rx: 3 }),
    s("circle", { class: "rm-cork__pin", cx: 60, cy: 36, r: 4 }),
    textLine(60, 66, "Daily recap", "rm-t rm-t--paper", { "text-anchor": "middle" }),
    textLine(60, 86, "No recap pinned", "rm-t rm-t--paper-sub", { "text-anchor": "middle" }),
    textLine(60, 100, "yet", "rm-t rm-t--paper-sub", { "text-anchor": "middle" })];
  return prop("bulletin", [670, 40, 120, 172], { "aria-label": "Bulletin board: the daily recap", "data-sheet": "bulletin" }, art);
}

function door() {
  const art = [
    s("rect", { class: "rm-door__frame", x: 0, y: 0, width: 110, height: 236, rx: 6 }),
    s("rect", { class: "rm-door__leaf", x: 8, y: 8, width: 94, height: 228, rx: 3 }),
    s("rect", { class: "rm-door__panel", x: 20, y: 22, width: 70, height: 80, rx: 3 }),
    s("rect", { class: "rm-door__panel", x: 20, y: 116, width: 70, height: 96, rx: 3 }),
    s("circle", { class: "rm-door__knob", cx: 84, cy: 130, r: 5 }),
    s("rect", { class: "rm-door__plaque", x: 18, y: 4, width: 74, height: 16, rx: 3 }),
    textLine(55, 16, "MY KENNEL", "rm-t rm-t--plaque", { "text-anchor": "middle" })];
  return prop("door", [850, 18, 110, 236], { href: "kennel.html", "aria-label": "My Kennel: your hounds" }, art);
}

function stone(model) {
  const art = [
    s("path", { class: "rm-stone__body", d: "M4 56V22a16 16 0 0 1 32 0v34z" }),
    s("path", { class: "rm-stone__cross", d: "M20 14v20M13 22h14" }),
    s("rect", { class: "rm-stone__base", x: 0, y: 54, width: 40, height: 6, rx: 3 })];
  const n = model.headstones;
  return prop("stone", [18, 268, 40, 60], { href: "graveyard.html", "aria-label": `Graveyard: ${n} ${n === 1 ? "headstone" : "headstones"}`, "data-count": String(n) }, art);
}

function props(model) {
  const list = [whiteboard(model), tv(model), bulletin(), door()];
  if (model.headstones > 0) list.push(stone(model));
  return list;
}

// ---- one hound ----------------------------------------------------------------------------------------------

const ICON = {
  cloud: () => s("svg", { viewBox: "0 0 60 40", "aria-hidden": "true", focusable: "false" }, [
    s("path", { class: "rm-cloud__body", d: "M14 28a9 9 0 0 1 1-18 12 12 0 0 1 23-2 10 10 0 0 1 8 20z" }),
    s("path", { class: "rm-cloud__rain", d: "M18 33l-2 5M30 33l-2 5M42 33l-2 5" })]),
  whistle: () => s("svg", { viewBox: "0 0 40 28", "aria-hidden": "true", focusable: "false" }, [
    s("path", { class: "rm-whistle__body", d: "M4 10h18l6-5h8v14h-9a10 10 0 1 1-23-9z" }), s("circle", { class: "rm-whistle__hole", cx: 18, cy: 16, r: 3 })]),
  crown: () => s("svg", { viewBox: "0 0 32 22", "aria-hidden": "true", focusable: "false" }, [
    s("path", { class: "rm-crown__body", d: "M3 19l2-12 7 6 4-9 4 9 7-6 2 12z" }), s("rect", { class: "rm-crown__band", x: 3, y: 18, width: 26, height: 3, rx: 1 })]),
};

function houndNode(c, onOpen) {
  const dog = dogFace(c.hound, { size: 72, pose: c.pose, label: "", decorative: true });
  const nodes = {
    // one line: the pick truncates with an ellipsis, the "+N more" never does (two spans, one string for a reader)
    bubble: h("span", { class: "rm-bubble", "data-hook": "room-bubble", hidden: true }, [h("span", { class: "rm-bubble__t" }), h("span", { class: "rm-bubble__x" })]),
    burst: h("span", { class: "rm-burst", "data-hook": "room-burst", hidden: true, "aria-hidden": "true" }),
    name: h("span", { class: "rm-name", "data-hook": "room-name" }),
    trained: h("span", { class: "rm-trained", "data-hook": "room-trained", hidden: true }),
    crown: h("span", { class: "rm-crown", "data-hook": "room-crown", hidden: true, title: "Season leader" }, [ICON.crown()]),
    dog,
  };
  const btn = h("button", { type: "button", class: "rm-hound__btn", "data-hook": "room-hound-btn", on: { click: () => onOpen(c.id) } }, [
    h("span", { class: "rm-fx rm-fx--cloud", "aria-hidden": "true" }, [ICON.cloud()]),
    h("span", { class: "rm-fx rm-fx--confetti", "aria-hidden": "true" }, [h("i"), h("i"), h("i"), h("i"), h("i"), h("i")]),
    h("span", { class: "rm-fx rm-fx--z", "aria-hidden": "true" }, [h("i", { text: "z" }), h("i", { text: "z" }), h("i", { text: "Z" })]),
    h("span", { class: "rm-fx rm-fx--whistle", "aria-hidden": "true" }, [ICON.whistle()]),
    nodes.crown,
    h("span", { class: "rm-dog", "aria-hidden": "true" }, [dog]),
    nodes.name, nodes.trained]);
  const root = h("div", { class: "rm-hound", "data-hook": "room-hound", "data-id": c.id }, [
    h("div", { class: "rm-walk" }, [nodes.bubble, nodes.burst, btn])]);
  return { root, btn, nodes };
}

function ariaFor(c) {
  const bits = [c.name, c.label];
  if (c.bubble && c.state === "pending") bits.push(c.bubble.text);
  if (c.crown) bits.push("season leader");
  bits.push("open card");
  return bits.join(", ");
}

function paintHound(view, c, slot) {
  const n = view.nodes.get(c.id).nodes, root = view.nodes.get(c.id).root, btn = view.nodes.get(c.id).btn;
  root.setAttribute("data-state", c.state);
  root.setAttribute("data-zone", c.zone);
  root.setAttribute("style", `${place(slot[0], slot[1])};z-index:${Math.round(slot[1])}`);
  root.setAttribute("data-live", c.live ? "true" : "false");
  root.setAttribute("data-label", c.label);                 // the same words the list under the room says: both come from the adapter's state
  root.setAttribute("data-slot", `${Math.round(slot[0])},${Math.round(slot[1])}`);
  btn.setAttribute("aria-label", ariaFor(c));
  setPose(n.dog, c.pose);
  n.name.textContent = clip(c.name, 14);
  const showBubble = !!c.bubble && (c.state === "pending" || c.state === "won" || c.state === "lost");
  n.bubble.hidden = !showBubble;
  const [main, more] = bubbleParts(showBubble ? c.bubble : null);
  n.bubble.childNodes[0].textContent = main;
  n.bubble.childNodes[1].textContent = more;
  n.bubble.setAttribute("data-tone", showBubble ? c.bubble.tone : "");
  n.burst.hidden = !c.burst;
  n.burst.textContent = c.burst || "";
  n.burst.setAttribute("data-tone", c.state === "lost" ? "loss" : "win");
  n.crown.hidden = !c.crown;
  n.trained.hidden = !(c.trained > 0);
  n.trained.textContent = c.trained > 0 ? `×${c.trained}` : "";
  if (c.trained > 0) n.trained.setAttribute("title", `Trained ×${c.trained}`);
}

/** Sticky slots: a hound keeps its seat while it stays in a zone; a new arrival takes the first free one; a full zone spills onto spare floor. */
export function assignSlots(chars, previous) {
  const taken = {}, spare = new Set();
  const out = new Map();
  const free = (zone) => { const used = taken[zone] || (taken[zone] = new Set()); let i = 0; while (used.has(i)) i += 1; return i; };
  for (const c of chars) {                                   // keep the seat a hound already has in this zone
    const prev = previous.get(c.id);
    const used = taken[c.zone] || (taken[c.zone] = new Set());
    if (prev && prev.zone === c.zone && !prev.spare && prev.i < SLOTS[c.zone].length && !used.has(prev.i)) {
      used.add(prev.i);
      out.set(c.id, { zone: c.zone, i: prev.i, xy: SLOTS[c.zone][prev.i] });
    }
  }
  for (const c of chars) {
    if (out.has(c.id)) continue;
    const i = free(c.zone);
    if (i < SLOTS[c.zone].length) { taken[c.zone].add(i); out.set(c.id, { zone: c.zone, i, xy: SLOTS[c.zone][i] }); continue; }
    let k = 0; while (spare.has(k)) k += 1;
    spare.add(k);
    out.set(c.id, { zone: c.zone, i: k, spare: true, xy: SPARE[k % SPARE.length] });
  }
  return out;
}

// ---- the card ----------------------------------------------------------------------------------------------

function recordText(rec) {
  return `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}`;
}

function fact(label, value, hook) {
  return h("div", { class: "rm-fact" }, [h("dt", { text: label }), h("dd", Object.assign({ text: value }, hook ? { "data-hook": hook } : {}))]);
}

function houndSheet(c, model, ctl) {
  const rec = c.record;
  const small = rec.settled < model.minRanked;
  const units = isNum(rec.units) ? fmtUnits(rec.units) : "n/a";
  const links = [h("a", { class: "lh-btn lh-btn--solid", href: houndHref(c.id), "data-hook": "room-card-open", text: "Open hound page" })];
  if (c.mine) {
    for (const [label, tab, hook] of [["Open studio", "look", "room-card-studio"], ["Unleash", "fire", "room-card-unleash"], ["Edit rules", "rules", "room-card-edit"]]) {
      links.push(h("a", { class: "lh-btn lh-btn--soft", href: `kennel.html?dog=${encodeURIComponent(c.id)}&tab=${tab}`, "data-hook": hook, text: label,
        on: { click: (e) => { if (ctl.onStudio) { if (e && e.preventDefault) e.preventDefault();
          ctl.closeSheet(); ctl.onStudio(c.id, tab); } } } }));
    }
  }
  return [
    h("div", { class: "rm-sheet__id" }, [
      h("span", { class: "rm-sheet__dog", "aria-hidden": "true" }, [dogFace(c.hound, { size: 84, pose: c.pose })]),
      h("div", {}, [
        h("h2", { class: "rm-sheet__name", id: "rm-sheet-title", text: c.name }),
        h("div", { class: "rm-sheet__chips" }, [
          h("span", { class: "rm-chip", "data-state": c.state, "data-hook": "room-card-state", text: c.label }),
          c.crown ? h("span", { class: "rm-chip rm-chip--crown", text: "Season leader" }) : null,
          trainedBadge(c.trained)])])]),
    c.tagline ? h("p", { class: "rm-sheet__tag", text: c.tagline }) : null,
    c.bubble && c.state === "pending" ? h("p", { class: "rm-sheet__pick", "data-hook": "room-card-pick", text: c.bubble.text }) : null,
    h("p", { class: "rm-sheet__detail", "data-hook": "room-card-detail", text: c.detail }),
    h("dl", { class: "rm-facts" }, [
      fact("Record", `${recordText(rec)} · ${rec.settled} settled`, "room-card-record"),
      fact("Units", units, "room-card-units"),
      fact("Open tickets", String(c.openCount), "room-card-open-count"),
      c.lastSettle ? fact("Last settled", `${fmtUnits(c.lastSettle.net)} · ${c.lastSettle.wins}-${c.lastSettle.losses} · ${c.lastSettle.ageMin < 1 ? "just now" : `${inText(c.lastSettle.ageMin * 60000)} ago`}${c.lastSettle.estimated ? " (time estimated)" : ""}`, "room-card-last") : null]),
    small ? h("p", { class: "rm-sheet__fine", "data-hook": "room-card-small", text: `Small sample: ${rec.settled} settled. Ranked at ${model.minRanked}.` }) : null,
    h("div", { class: "rm-sheet__actions" }, links),
  ];
}

function bulletinSheet() {
  return [
    h("h2", { class: "rm-sheet__name", id: "rm-sheet-title", text: "Daily recap" }),
    h("p", { class: "rm-sheet__detail", "data-hook": "room-card-detail", text: "No recap pinned yet." }),
    h("div", { class: "rm-sheet__actions" }, [h("a", { class: "lh-btn lh-btn--soft", href: "hounds.html", text: "See the leaderboard" })])];
}

// ---- sound (off by default) --------------------------------------------------------------------------------

function makeSound() {
  let ctx = null, on = false;
  const tone = (freq, at, len, vol) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "sine"; o.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, ctx.currentTime + at);
    g.gain.exponentialRampToValueAtTime(vol, ctx.currentTime + at + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + len);
    o.connect(g); g.connect(ctx.destination); o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + len + 0.05);
  };
  return {
    get on() { return on; },
    set(v) {
      on = !!v;
      if (on && !ctx) { try { const AC = window.AudioContext || window.webkitAudioContext; ctx = AC ? new AC() : null; } catch (err) { ctx = null; } }
      if (on && !ctx) on = false;
      return on;
    },
    play(kind) {
      if (!on || !ctx) return;
      try {
        if (ctx.state === "suspended") ctx.resume();
        if (kind === "win") { tone(523, 0, 0.16, 0.05); tone(659, 0.12, 0.16, 0.05); tone(784, 0.24, 0.3, 0.05); }
        else { tone(330, 0, 0.22, 0.05); tone(247, 0.2, 0.4, 0.05); }
      } catch (err) { /* sound is an extra */ }
    },
  };
}

const reduced = () => { try { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (err) { return false; } };

// ---- the room ------------------------------------------------------------------------------------------------

/**
 * Mount a room into `host`. opts: { scope: "house" | "kennel", data (a kennel payload, for scope "kennel"), onStudio(id, tab), note (default true),
 * fetchInput (tests: replaces the loaders) }. Returns { refresh, start, stop, destroy, model }.
 */
export function mountRoom(host, opts = {}) {
  const scope = opts.scope === "kennel" ? "kennel" : "house";
  const view = { nodes: new Map(), slots: new Map(), model: null, prev: new Map(), timer: null, active: true, firstPaint: true, sheetFor: null, sheetSig: "", setSig: "", rosterSig: "", opener: null, busy: false, lastOk: 0, known: opts.data || null };
  const sound = makeSound();

  const status = h("p", { class: "rm-status hd-fine", role: "status", "aria-live": "polite", "data-hook": "room-status" });
  const soundBtn = h("button", { type: "button", class: "rm-sound", "data-hook": "room-sound", "aria-pressed": "false", text: "Sound off",
    on: { click: () => { const on = sound.set(!sound.on); soundBtn.setAttribute("aria-pressed", on ? "true" : "false"); soundBtn.textContent = on ? "Sound on" : "Sound off"; } } });
  const setLayer = h("div", { class: "rm-set", "data-hook": "room-set" });      // the room and its props: redrawn on each read
  const crowd = h("div", { class: "rm-crowd", "data-hook": "room-crowd" });     // the hounds: kept, so a move is a CSS transition and not a redraw
  const stage = h("div", { class: "rm-stage", "data-hook": "room-stage" }, [setLayer, crowd]);
  const frame = h("div", { class: "rm-frame", "data-hook": "room-frame", role: "region", "aria-label": "The kennel room. Scrolls sideways on a phone.", tabindex: "0" }, [stage]);
  const roster = h("ul", { class: "rm-roster", "data-hook": "room-roster", "aria-label": "Who is where" });
  const note = opts.note === false ? null : h("p", { class: "rm-note hd-fine", "data-hook": "room-note", text: "Paper bets only. Units are the scoreboard, not money." });
  const message = h("div", { class: "rm-message", "data-hook": "room-message", role: "status" });
  const scrim = h("div", { class: "rm-scrim", "data-hook": "room-scrim", hidden: true });
  const sheet = h("aside", { class: "rm-sheet", "data-hook": "room-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "rm-sheet-title", hidden: true });
  const close = h("button", { type: "button", class: "rm-sheet__close", "data-hook": "room-sheet-close", "aria-label": "Close the card", text: "×" });
  const body = h("div", { class: "rm-sheet__body", "data-hook": "room-sheet-body" });
  sheet.appendChild(close); sheet.appendChild(body);

  const root = h("section", { class: "rm", "data-hook": "room", "data-scope": scope }, [
    h("div", { class: "rm-bar" }, [status, soundBtn]), message, frame, roster, note]);
  clearNode(host).appendChild(root);
  // the card and its scrim hang off <body>: a page that animates its column (a transform) would otherwise become their containing block and
  // pin the card to the column instead of the screen
  const overlay = h("div", { class: "rm rm-overlay", "data-hook": "room-overlay" }, [scrim, sheet]);
  if (typeof document !== "undefined" && document.body && document.body.appendChild) document.body.appendChild(overlay);
  else root.appendChild(overlay);

  const ctl = {
    onStudio: opts.onStudio || null,
    closeSheet() {
      sheet.hidden = true; scrim.hidden = true; view.sheetFor = null;
      if (view.opener && view.opener.focus) view.opener.focus();
      view.opener = null;
    },
  };
  close.addEventListener("click", ctl.closeSheet);
  scrim.addEventListener("click", ctl.closeSheet);
  if (typeof document !== "undefined" && document.addEventListener) document.addEventListener("keydown", (e) => { if (e && e.key === "Escape" && view.sheetFor) ctl.closeSheet(); });

  /** Fill the open card from the newest read. Returns false when its hound has left the room. */
  function fillSheet(kind) {
    const c = kind === "bulletin" ? null : view.model && view.model.characters.find((x) => x.id === kind);
    if (kind !== "bulletin" && !c) return false;
    const sig = JSON.stringify(c ? [c.id, c.state, c.label, c.detail, c.bubble, c.record, c.crown, c.trained, c.openCount, c.lastSettle] : "bulletin");
    if (sig === view.sheetSig && body.firstChild) return true;
    view.sheetSig = sig;
    clearNode(body);
    for (const node of (c ? houndSheet(c, view.model, ctl) : bulletinSheet())) if (node) body.appendChild(node);
    return true;
  }

  function openSheet(kind, opener) {
    view.sheetFor = kind; view.opener = opener || null; view.sheetSig = "";
    if (!fillSheet(kind)) return;
    sheet.hidden = false; scrim.hidden = false;
    if (close.focus) close.focus();
  }

  function paintStatus(text, kind) {
    status.textContent = text;
    if (kind) status.setAttribute("data-kind", kind); else status.removeAttribute("data-kind");
  }

  function say(text, retry) {
    clearNode(message);
    message.hidden = !text;
    if (!text) return;
    message.appendChild(h("p", { text }));
    if (retry) message.appendChild(h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "room-retry", text: "Try again", on: { click: () => refresh() } }));
  }

  function render(model) {
    view.model = model;
    const ids = new Set(model.characters.map((c) => c.id));
    for (const [id, n] of [...view.nodes]) if (!ids.has(id)) { if (n.root.parentNode) n.root.parentNode.removeChild(n.root); view.nodes.delete(id); view.slots.delete(id); }
    view.slots = assignSlots(model.characters, view.slots);
    // the set and the list are redrawn only when what they show changed, so a keyboard user's focus is not pulled out from under them every poll
    const desks = [...view.slots.values()].filter((v) => v.zone === "desk" && !v.spare).map((v) => v.i);
    const beds = [...view.slots.values()].filter((v) => v.zone === "bed" && !v.spare).map((v) => v.i);
    const setSig = JSON.stringify([model.whiteboard, model.ticker, model.headstones, model.minRanked, desks.filter((i) => i >= 6).sort(), beds.filter((i) => i >= 3).sort()]);
    if (setSig !== view.setSig) {
      view.setSig = setSig;
      clearNode(setLayer);
      setLayer.appendChild(backdrop(new Set(desks), new Set(beds)));
      for (const p of props(model)) setLayer.appendChild(p);
      const bull = setLayer.querySelector("[data-hook='room-bulletin']");
      if (bull) bull.addEventListener("click", () => openSheet("bulletin", bull));
    }
    const tiers = assignTiers(model.characters, view.slots);
    const row2 = [...view.slots.values()].some((v) => v.zone === "desk" && v.xy[1] !== SLOTS.desk[0][1]);
    for (const c of model.characters) {
      if (!view.nodes.has(c.id)) view.nodes.set(c.id, houndNode(c, (id) => openSheet(id, view.nodes.get(id).btn)));
      const slot = view.slots.get(c.id);
      paintHound(view, c, slot.xy);
      const node = view.nodes.get(c.id).root;
      node.setAttribute("data-tier", String(tiers.get(c.id) || 0));
      // the front desk row's second height sits just under the desk's lip (nothing there but the desk); a second desk row is in the way, so it goes up
      node.setAttribute("data-dir", slot.zone === "desk" && slot.xy[1] === SLOTS.desk[0][1] && !row2 ? "down" : "up");
      if (node.parentNode !== crowd) crowd.appendChild(node);
    }
    // the roster: everyone, by name, for a phone and a screen reader
    const rosterSig = JSON.stringify(model.characters.map((c) => [c.id, c.name, c.state, c.label]));
    if (rosterSig !== view.rosterSig) {
      view.rosterSig = rosterSig;
      clearNode(roster);
      for (const c of model.characters) {
        roster.appendChild(h("li", {}, [h("button", { type: "button", class: "rm-roster__btn", "data-state": c.state, "data-hook": "room-roster-btn",
          "data-zone": c.zone, "data-label": c.label, "aria-label": `${c.name}, ${c.label}. Open card.`, on: { click: (e) => openSheet(c.id, e.currentTarget) } }, [
          h("i", { class: "rm-dot", "aria-hidden": "true" }), h("span", { class: "rm-roster__name", text: c.name }), h("span", { class: "rm-roster__state", text: c.label })])]));
      }
    }
    // a card that is open follows the new state
    if (view.sheetFor && view.sheetFor !== "bulletin" && !fillSheet(view.sheetFor)) ctl.closeSheet();
    // sound: only a CHANGE between two real reads
    if (!view.firstPaint) {
      for (const c of model.characters) {
        const before = view.prev.get(c.id);
        if (before && before !== c.state && (c.state === "won" || c.state === "lost")) sound.play(c.state === "won" ? "win" : "loss");
      }
    }
    view.prev = new Map(model.characters.map((c) => [c.id, c.state]));
    if (view.firstPaint) { view.firstPaint = false; centre(model); }
    keepInView();
    root.setAttribute("data-empty", model.characters.length ? "false" : "true");
    if (!model.characters.length) say(scope === "kennel" ? "No hounds in your kennel yet." : "No hounds are in the room right now.", false);
    else say("", false);
  }

  /** On a phone the frame opens centred on where the hounds are, not on the empty wall. */
  function centre(model) {
    try {
      const active = model.characters.filter((c) => c.state !== "asleep" && c.state !== "nap");
      const list = active.length ? active : model.characters;
      if (!list.length || !frame.scrollWidth || frame.scrollWidth <= frame.clientWidth) return;
      const xs = list.map((c) => (view.slots.get(c.id) || { xy: [500] }).xy[0]);
      const mid = xs.reduce((a, b) => a + b, 0) / xs.length;
      frame.scrollLeft = Math.max(0, (mid / VIEW.w) * frame.scrollWidth - frame.clientWidth / 2);
    } catch (err) { /* a fake DOM has no layout */ }
  }

  /**
   * On a phone the frame shows a slice of the room. A pick bubble or a settled-units float that straddles the slice's border would be cut in half, so
   * each one slides sideways until it is whole (placeLabels, room-layout.js); one whose hound is out of view and would be cut is not drawn. Worked
   * out from where the hound WILL stand, so it holds mid-walk too. Runs after each read and while the frame pans.
   */
  const shifts = new WeakMap();
  function keepInView() {
    try {
      const cw = frame.clientWidth, sw = stage.offsetWidth;
      if (!cw || !sw) return;
      const pad = 4, lo = frame.scrollLeft + pad, hi = frame.scrollLeft + cw - pad;
      const items = [], els = [];
      for (const [id, v] of view.nodes) {
        const slot = view.slots.get(id);
        if (!slot) continue;
        const owner = (slot.xy[0] / VIEW.w) * sw;
        for (const el of [v.nodes.bubble, v.nodes.burst]) {
          if (el.hidden) { el.setAttribute("style", ""); shifts.set(el, 0); continue; }
          const w = el.offsetWidth;
          if (!w) continue;
          const dx = el.offsetLeft - (shifts.get(el) || 0);              // where the label's centre sits from its hound, before any slide
          items.push({ group: `${slot.zone}|${slot.xy[1]}|${v.root.getAttribute("data-tier")}`, c: owner + dx, w, owner });
          els.push(el);
        }
      }
      placeLabels(items, lo, hi).forEach((r, k) => {
        const el = els[k], w = items[k].w;
        const shift = Math.round(r.shift);
        const reach = Math.max(0, w / 2 - 12);
        const tail = Math.max(-reach, Math.min(reach, -shift));
        shifts.set(el, shift);
        el.setAttribute("style", r.hidden ? "visibility:hidden" : shift ? `--rm-shift:${shift}px;--rm-tail:${Math.round(tail)}px` : "");
      });
    } catch (err) { /* a fake DOM has no layout */ }
  }
  let panQueued = false;
  const onPan = () => {
    if (panQueued) return;
    panQueued = true;
    const run = () => { panQueued = false; keepInView(); };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(run); else run();
  };
  frame.addEventListener("scroll", onPan);
  if (typeof window !== "undefined" && window.addEventListener) window.addEventListener("resize", onPan);

  async function refresh() {
    if (view.busy || !view.active) return view.model;
    view.busy = true;
    const nowMs = Date.now();
    try {
      const known = view.known;
      view.known = null;                 // a payload My Kennel handed over is used once; every later read asks the server
      const input = opts.fetchInput ? await opts.fetchInput(scope, known) : scope === "kennel" ? await loadKennel(known, nowMs) : await loadHouse(nowMs);
      if (input && input.warming) {
        if (!view.model) say("The leaderboard is warming up. The room fills in a few seconds.", false);
        paintStatus("Warming up", "warn");
        if (typeof setTimeout === "function") setTimeout(() => { refresh(); }, 6000);
      } else if (!input || input.error) {
        if (!view.model) say("The kennel room could not load right now.", true);
        paintStatus(view.model ? `Could not refresh. Showing ${stamp(view.lastOk)}.` : "Not answering", "warn");
      } else {
        const model = build(input, { now: nowMs });
        render(model);
        view.lastOk = nowMs;
        paintStatus(`Live from the record · updated ${stamp(nowMs)}`);
      }
    } catch (err) {
      if (!view.model) say("The kennel room could not load right now.", true);
      paintStatus("Could not refresh", "warn");
    } finally {
      view.busy = false;
    }
    return view.model;
  }

  const stamp = (t) => { try { return new Date(t).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); } catch (err) { return ""; } };

  function arm() {
    if (view.timer !== null || !view.active) return;
    view.timer = setInterval(() => { if (!isHidden()) refresh(); }, opts.pollMs || POLL_MS);
  }
  function disarm() {
    if (view.timer !== null) { clearInterval(view.timer); view.timer = null; }
  }
  const isHidden = () => typeof document !== "undefined" && document.visibilityState === "hidden";
  function onVisibility() {
    if (isHidden()) disarm();
    else if (view.active) { if (Date.now() - view.lastOk > 30000) refresh(); arm(); }
  }
  if (typeof document !== "undefined" && document.addEventListener) document.addEventListener("visibilitychange", onVisibility);

  const api = {
    refresh,
    start() { view.active = true; if (!isHidden()) arm(); return refresh(); },
    /** Folded away: stop polling until it is opened again. */
    stop() { view.active = false; disarm(); },
    destroy() {
      view.active = false; disarm();
      if (typeof document !== "undefined" && document.removeEventListener) document.removeEventListener("visibilitychange", onVisibility);
      if (typeof window !== "undefined" && window.removeEventListener) window.removeEventListener("resize", onPan);
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      clearNode(host);
    },
    feed(data) { view.known = data; },
    get model() { return view.model; },
    get reduced() { return reduced(); },
  };
  if (opts.paused) view.active = false; else api.start();
  return api;
}

// ---- "Your kennel room": the collapsible block at the top of My Kennel ----------------------------------------

const OPEN_KEY = "linehound.kennel-room.open";
function storedOpen() {
  try { const v = window.localStorage.getItem(OPEN_KEY); return v === "1" ? true : v === "0" ? false : null; } catch (err) { return null; }
}
function storeOpen(open) {
  try { window.localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch (err) { /* a private window: the fold just starts the same way next time */ }
}

const kennelRooms = new WeakMap();

/**
 * Idempotent: the first call builds the fold and the room; a later call (My Kennel redrew after a rite or a save) feeds the new payload and
 * refreshes. With no active hound the block is removed (the page is then one button).
 */
export function mountKennelRoom(host, data, opts = {}) {
  if (!host) return null;
  const active = data && Array.isArray(data.dogs) ? data.dogs.filter((d) => d && !d.retired) : [];
  let rec = kennelRooms.get(host);
  if (!active.length) {
    if (rec) { rec.room.destroy(); kennelRooms.delete(host); }
    clearNode(host);
    return null;
  }
  if (rec) { rec.room.feed(data); rec.room.refresh(); return rec.room; }
  const stored = storedOpen();
  const wide = typeof window !== "undefined" && isNum(window.innerWidth) ? window.innerWidth >= 700 : true;
  const open = stored === null ? wide : stored;
  const inner = h("div", { class: "rm-fold__body", "data-hook": "kennel-room-body" });
  const summary = h("summary", { class: "rm-fold__summary", "data-hook": "kennel-room-summary" }, [h("span", { class: "rm-fold__title", text: "Your kennel room" })]);
  const fold = h("details", Object.assign({ class: "rm-fold", "data-hook": "kennel-room-fold" }, open ? { open: "" } : {}), [summary, inner]);
  clearNode(host).appendChild(fold);
  const room = mountRoom(inner, { scope: "kennel", data, onStudio: opts.onStudio, note: false, paused: !open });
  fold.addEventListener("toggle", () => {
    const isOpen = fold.hasAttribute("open");
    storeOpen(isOpen);
    if (isOpen) room.start(); else room.stop();
  });
  kennelRooms.set(host, { room, fold });
  return room;
}
