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
import { bubbleParts, assignTiers, placeLabels, planRoom, columnsFor, labelMax, ZONE_NAME, VIEW_W, MIN_H } from "./room-layout.js";
import { loadHouse, loadKennel, POLL_MS } from "./room-data.js";
import { trainedBadge } from "./dog-headstone.js";

export const VIEW = { w: VIEW_W, h: MIN_H };     // the room is VIEW.w across and at least VIEW.h tall: room-layout.js planRoom() sets the height from the rows

const SHEET_LINKS = { board: "hounds.html", tv: "live.html", door: "kennel.html", stone: "graveyard.html" };

const pct = (v, total) => `${Math.round((v / total) * 10000) / 100}%`;
const place = (x, y, H) => `left:${pct(x, VIEW.w)};top:${pct(y, H)}`;
const clip = (str, n) => { const t = String(str == null ? "" : str); return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t; };
const r1 = (v) => Math.round(v * 10) / 10;

// ---- the room around the hounds ---------------------------------------------------------------------------

function defs() {
  return s("defs", {}, [
    s("linearGradient", { id: "rm-g-wall", x1: "0", y1: "0", x2: "0", y2: "1" }, [s("stop", { offset: "0", class: "rm-stop rm-stop--wall-a" }), s("stop", { offset: "1", class: "rm-stop rm-stop--wall-b" })]),
    s("linearGradient", { id: "rm-g-floor", x1: "0", y1: "0", x2: "0", y2: "1" }, [s("stop", { offset: "0", class: "rm-stop rm-stop--floor-a" }), s("stop", { offset: "1", class: "rm-stop rm-stop--floor-b" })]),
    s("radialGradient", { id: "rm-g-glow", cx: "0.5", cy: "0.15", r: "0.7" }, [s("stop", { offset: "0", class: "rm-stop rm-stop--glow-a" }), s("stop", { offset: "1", class: "rm-stop rm-stop--glow-b" })]),
  ]);
}

/**
 * The furniture, drawn from the plan (room-layout.js planRoom): one invisible rect per zone band (the zone's boundary, which a hound and its labels
 * stay inside), a desk under every desk seat of a drawn row, a bed under every bed seat, a bowl under a hound that just lost, the gym mat, the signs.
 * The first row of desks and of beds is always there (an honest empty room shows empty desks and beds).
 */
function backdrop(plan) {
  const { H, cols, pitch, zones } = plan;
  const k = Math.min(1, (pitch - 8) / 102);                          // the furniture narrows when the seats do
  const seatX = (i) => r1(55 + pitch * ((i % cols) + 0.5));
  const seams = [];
  for (let i = 0; i < 15; i++) seams.push(s("line", { class: "rm-seam", x1: 70 * i + (i % 2 ? 20 : 45), y1: 256, x2: 70 * i + (i % 2 ? 20 : 45) - 24, y2: H }));
  for (let y = 310; y < H - 20; y += y < 520 ? 66 : 80) seams.push(s("line", { class: "rm-seam rm-seam--h", x1: 0, y1: y, x2: 1000, y2: y }));
  const seats = (z) => { const d = zones[z]; const out = []; if (d) for (let i = 0; i < d.rows * cols; i++) out.push([seatX(i), d.feet + Math.floor(i / cols) * d.step, i]); return out; };
  const desks = seats("desk").map(([x, y]) => s("g", { class: "rm-desk" }, [
    s("rect", { class: "rm-desk__front", x: r1(x - 46 * k), y: y + 6, width: r1(92 * k), height: 30, rx: 5 }),
    s("rect", { class: "rm-desk__top", x: r1(x - 51 * k), y: y - 4, width: r1(102 * k), height: 11, rx: 4 }),
    s("rect", { class: "rm-desk__phone", x: r1(x + 33 * k), y: y - 17, width: 11, height: 15, rx: 2 }),
    s("rect", { class: "rm-desk__screen", x: r1(x + 35 * k), y: y - 15, width: 7, height: 10, rx: 1 })]));
  const beds = seats("bed").map(([x, y]) => s("g", { class: "rm-bed" }, [
    s("ellipse", { class: "rm-bed__rim", cx: x, cy: y + 9, rx: r1(52 * k), ry: 20 }),
    s("ellipse", { class: "rm-bed__fill", cx: x, cy: y + 6, rx: r1(41 * k), ry: 13 })]));
  const bowls = seats("bowl").filter(([, , i]) => zones.bowl.used.has(i)).map(([x, y]) => s("g", { class: "rm-bowl" }, [
    s("ellipse", { class: "rm-bowl__rim", cx: x, cy: y + 12, rx: r1(34 * k), ry: 11 }), s("ellipse", { class: "rm-bowl__water", cx: x, cy: y + 10, rx: r1(26 * k), ry: 7 })]));
  const bands = [];
  for (const [z, d] of Object.entries(zones)) bands.push(s("rect", { class: "rm-zone", "data-zone": z, x: 0, y: d.top, width: 1000, height: d.bottom - d.top }));
  const gym = [];
  if (zones.gym) {
    const d = zones.gym;
    gym.push(s("g", { class: "rm-gym" }, [
      s("rect", { class: "rm-gym__mat", x: 40, y: d.feet - 28, width: 920, height: 50, rx: 10 }),
      s("rect", { class: "rm-gym__bar", x: 472, y: d.feet - 6, width: 56, height: 4, rx: 2 }),
      s("rect", { class: "rm-gym__plate", x: 464, y: d.feet - 15, width: 8, height: 22, rx: 2 }), s("rect", { class: "rm-gym__plate", x: 528, y: d.feet - 15, width: 8, height: 22, rx: 2 })]));
    gym.push(s("text", { class: "rm-label", "data-sign": "gym", x: 62, y: d.top + 16, "text-anchor": "start", text: "GYM" }));
  }
  const signs = zones.bed ? [s("text", { class: "rm-label", "data-sign": "bed", x: 62, y: zones.bed.top + 16, "text-anchor": "start", text: "BEDS" })] : [];
  return s("svg", { class: "rm-bg", viewBox: `0 0 ${VIEW.w} ${H}`, preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true", focusable: "false" }, [
    defs(),
    s("rect", { class: "rm-wall", x: 0, y: 0, width: 1000, height: 256, fill: "url(#rm-g-wall)" }),
    s("rect", { class: "rm-floor", x: 0, y: 256, width: 1000, height: H - 256, fill: "url(#rm-g-floor)" }),
    s("rect", { class: "rm-glow", x: 0, y: 0, width: 1000, height: H, fill: "url(#rm-g-glow)" }),
    s("rect", { class: "rm-baseboard", x: 0, y: 248, width: 1000, height: 10 }),
    s("g", {}, seams),
    ...(zones.floor ? [s("ellipse", { class: "rm-rug", cx: 500, cy: r1((zones.floor.top + zones.floor.bottom) / 2), rx: 470, ry: r1((zones.floor.bottom - zones.floor.top) / 2 - 8) })] : []),
    ...desks, ...beds, ...bowls, ...gym, ...signs, ...bands,
  ]);
}

/** A prop that is a link (anchor) or, with no href, a button. Its box is in view units. */
function prop(kind, box, attrs, art, kids, H) {
  const [x, y, w, hh] = box;
  const style = `left:${pct(x, VIEW.w)};top:${pct(y, H)};width:${pct(w, VIEW.w)};height:${pct(hh, H)}`;
  const base = Object.assign({ class: `rm-prop rm-prop--${kind}`, style, "data-hook": `room-${kind}` }, attrs);
  const svg = s("svg", { viewBox: `0 0 ${w} ${hh}`, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" }, art);
  return h(attrs.href ? "a" : "button", attrs.href ? base : Object.assign(base, { type: "button" }), [svg, ...(kids || [])]);
}

function textLine(x, y, str, cls, extra) {
  return s("text", Object.assign({ class: cls, x, y, text: str }, extra || {}));
}

function whiteboard(model, H) {
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
  return prop("board", [40, 34, 240, 172], { href: "hounds.html", "aria-label": "Leaderboard: the full table of every hound" }, art, null, H);
}

function tv(model, H) {
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
  return prop("tv", [320, 40, 320, 150], { href: "live.html", "aria-label": `Live: what is on right now. ${facts.join(", ")}` }, art, null, H);
}

function bulletin(H) {
  const art = [
    s("rect", { class: "rm-cork__frame", x: 0, y: 0, width: 120, height: 172, rx: 8 }),
    s("rect", { class: "rm-cork__face", x: 6, y: 6, width: 108, height: 160, rx: 5 }),
    s("rect", { class: "rm-cork__paper", x: 20, y: 28, width: 80, height: 96, rx: 3 }),
    s("circle", { class: "rm-cork__pin", cx: 60, cy: 36, r: 4 }),
    textLine(60, 66, "Daily recap", "rm-t rm-t--paper", { "text-anchor": "middle" }),
    textLine(60, 86, "No recap pinned", "rm-t rm-t--paper-sub", { "text-anchor": "middle" }),
    textLine(60, 100, "yet", "rm-t rm-t--paper-sub", { "text-anchor": "middle" })];
  return prop("bulletin", [670, 40, 120, 172], { "aria-label": "Bulletin board: the daily recap", "data-sheet": "bulletin" }, art, null, H);
}

function door(H) {
  const art = [
    s("rect", { class: "rm-door__frame", x: 0, y: 0, width: 110, height: 236, rx: 6 }),
    s("rect", { class: "rm-door__leaf", x: 8, y: 8, width: 94, height: 228, rx: 3 }),
    s("rect", { class: "rm-door__panel", x: 20, y: 22, width: 70, height: 80, rx: 3 }),
    s("rect", { class: "rm-door__panel", x: 20, y: 116, width: 70, height: 96, rx: 3 }),
    s("circle", { class: "rm-door__knob", cx: 84, cy: 130, r: 5 }),
    s("rect", { class: "rm-door__plaque", x: 18, y: 4, width: 74, height: 16, rx: 3 }),
    textLine(55, 16, "MY KENNEL", "rm-t rm-t--plaque", { "text-anchor": "middle" })];
  return prop("door", [850, 18, 110, 236], { href: "kennel.html", "aria-label": "My Kennel: your hounds" }, art, null, H);
}

function stone(model, H) {
  const art = [
    s("path", { class: "rm-stone__body", d: "M4 56V22a16 16 0 0 1 32 0v34z" }),
    s("path", { class: "rm-stone__cross", d: "M20 14v20M13 22h14" }),
    s("rect", { class: "rm-stone__base", x: 0, y: 54, width: 40, height: 6, rx: 3 })];
  const n = model.headstones;
  return prop("stone", [18, 268, 40, 60], { href: "graveyard.html", "aria-label": `Graveyard: ${n} ${n === 1 ? "headstone" : "headstones"}`, "data-count": String(n) }, art, null, H);
}

function props(model, H) {
  const list = [whiteboard(model, H), tv(model, H), bulletin(H), door(H)];
  if (model.headstones > 0) list.push(stone(model, H));
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

function paintHound(view, c, slot, H) {
  const n = view.nodes.get(c.id).nodes, root = view.nodes.get(c.id).root, btn = view.nodes.get(c.id).btn;
  root.setAttribute("data-state", c.state);
  root.setAttribute("data-zone", c.zone);
  root.setAttribute("style", `${place(slot[0], slot[1], H)};z-index:${Math.round(slot[1])}`);
  root.setAttribute("data-live", c.live ? "true" : "false");
  root.setAttribute("data-label", c.label);                 // the same words the list under the room says: both come from the adapter's state
  root.setAttribute("data-slot", `${Math.round(slot[0])},${Math.round(slot[1])}`);
  btn.setAttribute("aria-label", ariaFor(c));
  setPose(n.dog, c.pose);
  n.name.textContent = c.name;                              // the whole name: the tag truncates it with an ellipsis to fit its seat (css), the title has it whole
  n.name.setAttribute("title", c.name);
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
  const view = { nodes: new Map(), slots: new Map(), plan: null, more: new Map(), filter: null, model: null, prev: new Map(), timer: null, active: true, firstPaint: true, sheetFor: null, sheetSig: "", setSig: "", rosterSig: "", opener: null, busy: false, lastOk: 0, known: opts.data || null };
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

  /** The stage's width on screen, px (0 where nothing is laid out: a fake DOM, a folded block). */
  function stageWidth() {
    try { return stage.offsetWidth || 0; } catch (err) { return 0; }
  }

  /** The status list under the room: everyone, or (after a tap on a zone's "+K more") only that zone, with a way back to everyone. */
  function paintRoster(model) {
    let list = model.characters;
    if (view.filter) {
      list = list.filter((c) => c.zone === view.filter);
      if (!list.length) { view.filter = null; list = model.characters; }
    }
    const rosterSig = JSON.stringify([view.filter, list.map((c) => [c.id, c.name, c.state, c.label])]);
    if (rosterSig === view.rosterSig) return;
    view.rosterSig = rosterSig;
    clearNode(roster);
    if (view.filter) {
      roster.appendChild(h("li", { class: "rm-roster__head", "data-hook": "room-roster-filter" }, [
        h("span", { text: `${ZONE_NAME[view.filter]}: ${list.length} of ${model.characters.length}` }),
        h("button", { type: "button", class: "rm-roster__all", "data-hook": "room-roster-all", text: "Show everyone",
          on: { click: () => { view.filter = null; paintRoster(view.model); } } })]));
    }
    for (const c of list) {
      roster.appendChild(h("li", {}, [h("button", { type: "button", class: "rm-roster__btn", "data-state": c.state, "data-hook": "room-roster-btn",
        "data-zone": c.zone, "data-label": c.label, "aria-label": `${c.name}, ${c.label}. Open card.`, on: { click: (e) => openSheet(c.id, e.currentTarget) } }, [
        h("i", { class: "rm-dot", "aria-hidden": "true" }), h("span", { class: "rm-roster__name", text: c.name }), h("span", { class: "rm-roster__state", text: c.label })])]));
    }
  }

  /** "+K more": the last seat of a zone that has more hounds than seats. A tap lists that zone's hounds under the room. */
  function paintMore(plan) {
    for (const [zone, el] of [...view.more]) if (!(plan.zones[zone] && plan.zones[zone].more)) { if (el.parentNode) el.parentNode.removeChild(el); view.more.delete(zone); }
    for (const [zone, d] of Object.entries(plan.zones)) {
      if (!d.more) continue;
      let el = view.more.get(zone);
      if (!el) {
        el = h("button", { type: "button", class: "rm-more", "data-hook": "room-more", "data-zone": zone, on: { click: () => {
          view.filter = zone; view.rosterSig = ""; if (view.model) paintRoster(view.model);
          try { roster.scrollIntoView({ block: "nearest" }); const first = roster.querySelector("[data-hook='room-roster-btn']"); if (first && first.focus) first.focus({ preventScroll: true }); } catch (err) { /* no layout */ }
        } } });
        view.more.set(zone, el);
        crowd.appendChild(el);
      }
      const word = ZONE_NAME[zone].toLowerCase();
      el.textContent = `+${d.more.k} more`;
      el.setAttribute("title", `${d.more.k} more hounds ${word}. Show them in the list.`);
      el.setAttribute("aria-label", `${d.more.k} more hounds ${word}. Show them in the list.`);
      el.setAttribute("style", `${place(d.more.xy[0], d.more.xy[1], plan.H)};z-index:${Math.round(d.more.xy[1])}`);
    }
  }

  function render(model) {
    view.model = model;
    root.setAttribute("data-empty", model.characters.length ? "false" : "true");     // first: an empty room has no frame, and a frame with no width has no seats
    const plan = planRoom(model.characters, { width: stageWidth(), previous: view.slots });
    view.plan = plan;
    view.slots = plan.seats;
    const seated = model.characters.filter((c) => plan.seats.has(c.id));
    for (const [id, n] of [...view.nodes]) if (!plan.seats.has(id)) { if (n.root.parentNode) n.root.parentNode.removeChild(n.root); view.nodes.delete(id); }
    // the room is as tall as its rows; the name tags and the labels are as wide as a seat (css reads --rm-pitch and --rm-bmax, in view units)
    stage.setAttribute("style", `aspect-ratio:${VIEW.w} / ${plan.H};--rm-pitch:${r1(plan.pitch)};--rm-bmax:${labelMax(plan.pitch)}`);
    // the set and the list are redrawn only when what they show changed, so a keyboard user's focus is not pulled out from under them every poll
    const geo = Object.entries(plan.zones).map(([z, d]) => [z, d.top, d.rows, [...d.used].sort((a, b) => a - b)]);
    const setSig = JSON.stringify([model.whiteboard, model.ticker, model.headstones, model.minRanked, plan.H, plan.cols, geo]);
    if (setSig !== view.setSig) {
      view.setSig = setSig;
      clearNode(setLayer);
      setLayer.appendChild(backdrop(plan));
      for (const p of props(model, plan.H)) setLayer.appendChild(p);
      const bull = setLayer.querySelector("[data-hook='room-bulletin']");
      if (bull) bull.addEventListener("click", () => openSheet("bulletin", bull));
    }
    for (const c of seated) {
      if (!view.nodes.has(c.id)) view.nodes.set(c.id, houndNode(c, (id) => openSheet(id, view.nodes.get(id).btn)));
      paintHound(view, c, view.slots.get(c.id).xy, plan.H);
      const node = view.nodes.get(c.id).root;
      node.setAttribute("data-dir", "up");
      if (node.parentNode !== crowd) crowd.appendChild(node);
    }
    paintMore(plan);
    // labelled neighbours in a row take turns on two heights: worked out from the labels' real widths (a guess where nothing is laid out)
    const sw = stageWidth(), unit = sw ? sw / VIEW.w : 0, widths = new Map();
    if (unit) for (const c of seated) { const nd = view.nodes.get(c.id).nodes; const el = c.state === "pending" ? nd.bubble : nd.burst; if (el.setAttribute) el.setAttribute("style", ""); const w = el.hidden ? 0 : el.offsetWidth; if (w) widths.set(c.id, w / unit); }
    const tiers = assignTiers(seated, view.slots, { widths });
    for (const c of seated) view.nodes.get(c.id).root.setAttribute("data-tier", String(tiers.get(c.id) || 0));
    paintRoster(model);
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
    if (!model.characters.length) say(scope === "kennel" ? "No hounds in your kennel yet." : "No hounds are in the room right now.", false);
    else say("", false);
  }

  /** On a phone the frame opens centred on where the hounds are, not on the empty wall. */
  function centre(model) {
    try {
      const active = model.characters.filter((c) => c.state !== "asleep" && c.state !== "nap");
      const list = active.length ? active : model.characters;
      if (!list.length || !frame.scrollWidth || frame.scrollWidth <= frame.clientWidth) return;
      const xs = list.filter((c) => view.slots.has(c.id)).map((c) => view.slots.get(c.id).xy[0]);
      if (!xs.length) return;
      const mid = xs.reduce((a, b) => a + b, 0) / xs.length;
      frame.scrollLeft = Math.max(0, (mid / VIEW.w) * frame.scrollWidth - frame.clientWidth / 2);
    } catch (err) { /* a fake DOM has no layout */ }
  }

  /**
   * On a phone the frame shows a slice of the room. A pick bubble or a settled-units float that straddles the slice's border would be cut in half, so
   * each one slides sideways until it is whole (placeLabels, room-layout.js); one whose hound is out of view and would be cut is not drawn. Worked
   * out from where the hound WILL stand, so it holds mid-walk too. Runs after each read and while the frame pans.
   */
  function keepInView() {
    try {
      const cw = frame.clientWidth, sw = stage.offsetWidth;
      if (!cw || !sw) return;
      const pad = 6, lo = frame.scrollLeft + pad, hi = frame.scrollLeft + cw - pad;
      const labels = [];
      for (const [id, v] of view.nodes) {
        const slot = view.slots.get(id);
        if (!slot) continue;
        for (const el of [v.nodes.bubble, v.nodes.burst]) {
          el.setAttribute("style", "");                                  // measured as it sits by itself: no slide, no cut (the next lines put both back)
          if (!el.hidden) labels.push({ el, v, slot });
        }
      }
      const items = [], els = [];
      for (const { el, v, slot } of labels) {
        const w = el.offsetWidth;
        if (!w) continue;
        const owner = (slot.xy[0] / VIEW.w) * sw;
        items.push({ group: `${slot.zone}|${slot.xy[1]}|${v.root.getAttribute("data-tier")}`, c: owner + el.offsetLeft, w, owner });   // offsetLeft: the label's centre from its hound
        els.push(el);
      }
      placeLabels(items, lo, hi).forEach((r, k) => {
        const el = els[k];
        const shown = r.fit || items[k].w;                               // two labels that cannot stand side by side in the slice share it: the pick is cut with an ellipsis
        const shift = Math.round(r.shift);
        const reach = Math.max(0, shown / 2 - 12);
        const tail = Math.max(-reach, Math.min(reach, -shift));
        const style = [];
        if (r.hidden) style.push("visibility:hidden");
        else {
          if (shift) style.push(`--rm-shift:${shift}px`, `--rm-tail:${Math.round(tail)}px`);
          if (r.fit && el.getAttribute("data-hook") === "room-bubble") style.push(`--rm-fit:${r.fit}px`);
        }
        el.setAttribute("style", style.join(";"));
      });
    } catch (err) { /* a fake DOM has no layout */ }
  }
  let panQueued = false;
  const onPan = () => {
    if (panQueued) return;
    panQueued = true;
    const run = () => {
      panQueued = false;
      const w = stageWidth();                                           // the stage got wider or narrower: the seats across change, so the room is laid out again
      if (w && view.plan && view.model && columnsFor(w) !== view.plan.cols) render(view.model); else keepInView();
    };
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
