/**
 * THE LIVE BOARD (web/live.html): "What's on". Every sport the server prices, as a sportsbook's live tab: a "now" strip of the games in
 * play (clock, score, state), then one group per sport with a sticky header and its count, each game a card with its teams or players,
 * its league, its start time in the VIEWER'S zone and the best price quoted for each side. A chip per sport family filters the groups.
 *
 *   GET /sports/now   {generated_utc, families: [{code, label, live: [row], upcoming_24h: [row], next_start_utc}]}
 *       row = {event_id, league_title, home, away, start_utc, in_play, best_price_home, best_price_away, score?}
 *       `score` is read leniently: a string ("2-1, 62'") or {home, away, detail?}.
 *   GET /hounds/live?ids=   the grader's cache for the games in play: state, score and detail (web/js/livestate.js eventLiveModel).
 *
 * HOUNDS ON A GAME. Each card says which hounds have an OPEN ticket on that game. The viewer's own hounds (GET /hounds/camp/mine, then
 * GET /hounds/{id}/bets?status=open for each that says it has some, the kennel page's own reads) show as an avatar and the side they
 * took; the house pack (GET /hounds for who is in it, GET /hounds/stream for its tickets) shows as a compact row of avatars and
 * "+3 more". All of it is read softly: a read that fails leaves the card as it was and says nothing, never a guess.
 *
 * SEND A HOUND. A small secondary button on the card. A signed-out visitor is asked to sign in. A member sees their own hounds (the
 * Training camp's list) and picks one; the page then calls the existing preview route (POST /hounds/{id}/fire, web/js/dog-fire.js
 * unleash) and says what that hound did with THIS game: the pick it made, the reason it passed, or that the game was not among its
 * answers. That route runs the hound's rule over the stored boards and writes nothing. Nothing here places a bet and nothing here
 * claims a price is an advantage: a best price is the best number any book is quoting, no more.
 *
 * It refreshes itself every 60 seconds while the page is visible (createPoller), keeps the board it has when a refresh fails and
 * says so, and keeps any open "Send a hound" tray across a refresh. Written against attributes only (no classList, no dataset), so
 * it runs under the small fake DOM of tests/hounds_web_harness.mjs as well as in a browser.
 */

import { apiGet, getToken } from "./api.js";
import { h, clearNode, fmtPrice, isNum, createPoller, describeError } from "./hounds-core.js";
import { dogFace } from "./dog-avatar.js";
import { get, errorText, errorCode, signInPrompt, spanText, PAPER_NOTE } from "./dog-common.js";
import { renderFireResult, unleash } from "./dog-fire.js";
import { showUpgrade } from "./upgrade.js";
import { formatStamp } from "./local-time.js";
import { eventLiveModel, liveStateLine } from "./livestate.js";

export const REFRESH_MS = 60000;
const ROW_CAP = 20;          // one sport chosen
const GROUP_CAP = 8;         // a group in the All view: its live games always show, then upcoming up to this many rows
const NOW_CAP = 30;          // cards in the now strip
const PACK_SHOW = 4;         // house hounds drawn on a card before "+N more"
const MINE_SHOW = 3;         // the viewer's own hounds drawn on a card before "+N more"
const MINE_READS = 10;       // at most this many of the viewer's hounds are asked for open tickets
const PACK_TTL_MS = 10 * 60 * 1000;
const STALE_MINUTES = 5;

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
const now = () => new Date(Date.now());

const state = {
  data: null,            // the last good /sports/now payload
  family: "all",
  loadedAt: null,
  failed: false,
  more: new Set(),       // sport codes whose whole list is open
  trays: new Map(),      // event_id -> the open tray node, kept across refreshes
  dogs: null,            // Promise of the member's hounds, once asked
  busy: false,
  states: new Map(),     // event_id -> the grader's state for a game in play (GET /hounds/live)
  pack: { at: 0, hounds: null },   // the house pack: Map(id -> hound), read at most every PACK_TTL_MS
  onGame: { mine: new Map(), pack: new Map() },   // event_id -> [{hound, side}]: open tickets by game
};

// ---- time (the viewer's own zone: web/js/local-time.js) ------------------------------------------------

function toDate(stamp) {
  const d = new Date(stamp);
  return !stamp || Number.isNaN(d.getTime()) ? null : d;
}

function dayStart(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); }

/** "7:05 PM PT" today, "Tomorrow 1:30 AM PT", "Thu 7:15 PM PT" later, in the viewer's own zone; "" when unreadable. */
export function dayClock(stamp, ref = now()) {
  const d = toDate(stamp);
  if (!d) return "";
  const today = Math.round((dayStart(d) - dayStart(ref)) / 86400000) === 0;
  return formatStamp(today ? "c" : "t", stamp, ref);
}

/** "Today 7:15 PM PT" / "Tomorrow 7:15 PM PT" / "Thu 7:15 PM PT": the day always said, for "Next: ...". */
export function nextText(stamp, ref = now()) {
  return toDate(stamp) ? formatStamp("t", stamp, ref) : "";
}

// ---- reading the payload ---------------------------------------------------------------------------------

function families() {
  const list = state.data && Array.isArray(state.data.families) ? state.data.families : [];
  return list.map((f) => ({
    code: String(f.code || ""), label: String(f.label || f.code || ""),
    live: Array.isArray(f.live) ? f.live : [], upcoming: Array.isArray(f.upcoming_24h) ? f.upcoming_24h : [],
    next: f.next_start_utc || null,
  })).filter((f) => f.code);
}

const byStart = (a, b) => String(a.start_utc || "").localeCompare(String(b.start_utc || "")) || String(a.event_id).localeCompare(String(b.event_id));

/** Sports with something on first, busiest first; quiet sports stay reachable at the end. The chips and the groups use one order. */
function busiestFirst(list) {
  return list.slice().sort((a, b) => (b.live.length - a.live.length) || ((b.live.length + b.upcoming.length) - (a.live.length + a.upcoming.length)));
}

function selected() {
  const all = families();
  const pick = state.family === "all" ? all : all.filter((f) => f.code === state.family);
  const tag = (f, ev) => Object.assign({}, ev, { _family: f.code, _familyLabel: f.label });
  // one group per sport that has a game: its live games, then the upcoming ones, each by start time
  const groups = busiestFirst(pick).map((f) => ({
    code: f.code, label: f.label,
    live: f.live.map((ev) => tag(f, ev)).sort(byStart), upcoming: f.upcoming.map((ev) => tag(f, ev)).sort(byStart),
  })).filter((g) => g.live.length || g.upcoming.length);
  const flat = (kind) => groups.flatMap((g) => g[kind]).sort(byStart);
  return { families: pick, groups, live: flat("live"), upcoming: flat("upcoming") };
}

/** The earliest known start among the chosen families, for "Next: ..." when nothing is on. */
function earliestNext(pick) {
  const stamps = pick.map((f) => f.next).filter(Boolean).sort();
  return stamps[0] || "";
}

// ---- chips -----------------------------------------------------------------------------------------------

function chip(code, label, count, liveCount) {
  const on = state.family === code;
  const kids = [];
  if (liveCount > 0) kids.push(h("span", { class: "lv-dot", "aria-hidden": "true" }));
  kids.push(h("span", { class: "lv-chip__label", text: label }));
  kids.push(h("span", { class: "lv-chip__n", text: String(count) }));
  return h("button", { type: "button", class: "lv-chip", "data-hook": "live-chip", "data-family": code, "aria-pressed": on ? "true" : "false",
    "aria-label": `${label}: ${count} ${count === 1 ? "game" : "games"}${liveCount ? `, ${liveCount} live` : ""}`,
    on: { click: () => selectFamily(code) } }, kids);
}

function renderChips() {
  const host = q("live-chips");
  if (!host) return;
  const all = families();
  clearNode(host);
  const total = all.reduce((n, f) => n + f.live.length + f.upcoming.length, 0);
  const totalLive = all.reduce((n, f) => n + f.live.length, 0);
  host.appendChild(chip("all", "All", total, totalLive));
  for (const f of busiestFirst(all)) host.appendChild(chip(f.code, f.label, f.live.length + f.upcoming.length, f.live.length));
}

function selectFamily(code) {
  if (state.family === code) return;
  state.family = code;
  state.more = new Set();
  try {
    if (typeof window !== "undefined" && window.history && window.history.replaceState) {
      window.history.replaceState(null, "", code === "all" ? "live.html" : `live.html?sport=${encodeURIComponent(code)}`);
    }
  } catch (err) { /* a blocked history is not a failure */ }
  render();
}

// ---- the now strip ---------------------------------------------------------------------------------------

function nowCard(ev) {
  const m = eventLiveModel(ev, state.states.get(ev.event_id));
  const side = (t) => h("span", { class: "lv-now__side" }, [
    h("span", { class: "lv-now__team", text: t.name }),
    t.score === null ? null : h("span", { class: "lv-now__score hd-num", text: String(t.score) })]);
  const scored = m.away.score !== null && m.home.score !== null;
  const word = m.label.charAt(0) + m.label.slice(1).toLowerCase();
  return h("a", { class: "lv-now__card", href: `#lv-ev-${ev.event_id}`, "data-hook": "live-now-card", "data-event": ev.event_id, "data-kind": m.kind,
    "aria-label": `${ev._familyLabel || ""} ${m.away.name} at ${m.home.name}${scored ? `, ${m.away.score} to ${m.home.score}` : ""}${m.detail ? `, ${m.detail}` : ""}, ${word.toLowerCase()}`.trim() }, [
    h("span", { class: "lv-now__top" }, [
      m.kind === "live" ? h("span", { class: "lv-dot", "aria-hidden": "true" }) : null,
      h("span", { class: `lv-now__state lv-now__state--${m.kind}`, "data-hook": "live-now-state", text: word }),
      h("span", { class: "lv-now__sport", text: ev._familyLabel || "" })]),
    side(m.away), side(m.home),
    m.detail ? h("span", { class: "lv-now__detail hd-num", "data-hook": "live-now-detail", text: m.detail }) : null]);
}

function renderNow(sel) {
  const host = q("live-now");
  if (!host) return;
  clearNode(host);
  const rows = sel.live;
  if (!rows.length) { host.setAttribute("hidden", ""); return; }
  host.removeAttribute("hidden");
  host.appendChild(h("div", { class: "lv-now__head" }, [
    h("span", { class: "lv-dot", "aria-hidden": "true" }),
    h("h2", { class: "lv-now__title", text: "In play now" }),
    h("span", { class: "lv-now__n hd-fine", "data-hook": "live-now-count", text: String(rows.length) })]));
  host.appendChild(h("div", { class: "lv-now__list", "data-hook": "live-now-list", role: "list", tabindex: "0", "aria-label": "Games in play" },
    rows.slice(0, NOW_CAP).map((ev) => h("div", { role: "listitem", class: "lv-now__item" }, [nowCard(ev)]))));
}

// ---- hounds on a game ------------------------------------------------------------------------------------

const houndLine = (list) => list.map((x) => `${x.hound.name} backs ${x.side}`).join("; ");

function mineChip(entry) {
  return h("span", { class: "lv-mine", "data-hook": "live-mine", "data-dog": entry.hound.id, title: `${entry.hound.name} backs ${entry.side}`,
    "aria-label": `${entry.hound.name} backs ${entry.side}` }, [
    h("span", { class: "lv-mine__face", "aria-hidden": "true" }, [dogFace(entry.hound, { size: 26 })]),
    h("span", { class: "lv-mine__side", text: entry.side })]);
}

const moreText = (n) => `+${n} more`;

function houndsOnGame(ev) {
  const mine = state.onGame.mine.get(ev.event_id) || [];
  const pack = state.onGame.pack.get(ev.event_id) || [];
  if (!mine.length && !pack.length) return null;
  const kids = [];
  if (mine.length) {
    const hidden = mine.length - MINE_SHOW;
    kids.push(h("div", { class: "lv-hounds__mine", "data-hook": "live-mine-row", role: "group", "aria-label": `Your hounds on this game: ${houndLine(mine)}` }, [
      h("span", { class: "lv-hounds__label", text: "Yours" }),
      ...mine.slice(0, MINE_SHOW).map(mineChip),
      hidden > 0 ? h("span", { class: "lv-hounds__more", "data-hook": "live-mine-more", text: moreText(hidden) }) : null]));
  }
  if (pack.length) {
    const hidden = pack.length - PACK_SHOW;
    kids.push(h("div", { class: "lv-hounds__pack", "data-hook": "live-pack", role: "group",
      "aria-label": `House pack on this game: ${pack.slice(0, PACK_SHOW).map((x) => x.hound.name).join(", ")}${hidden > 0 ? ` and ${hidden} more` : ""}` }, [
      h("span", { class: "lv-hounds__label", text: "Pack" }),
      h("span", { class: "lv-faces" }, pack.slice(0, PACK_SHOW).map((x) =>
        h("span", { class: "lv-faces__one", "data-hook": "live-pack-face", "data-dog": x.hound.id, title: `${x.hound.name} backs ${x.side}`, "aria-hidden": "true" }, [dogFace(x.hound, { size: 24 })]))),
      hidden > 0 ? h("span", { class: "lv-hounds__more", "data-hook": "live-pack-more", text: moreText(hidden) }) : null]));
  }
  return h("div", { class: "lv-hounds", "data-hook": "live-hounds" }, kids);
}

// ---- rows ------------------------------------------------------------------------------------------------

function scoreParts(ev) {
  const s = ev.score;
  const line = liveStateLine(ev);       // NHL / tennis: the server's one line (period, clock, shots, power play; set, games, server, breaks)
  if (s && typeof s === "object") {
    return { home: isNum(s.home) ? String(s.home) : "", away: isNum(s.away) ? String(s.away) : "", detail: line || (s.detail ? String(s.detail) : ""),
      completed: s.completed === true, delayed: s.delayed === true, line: !!line };
  }
  return { home: "", away: "", detail: line || (typeof s === "string" ? s : ""), completed: false, delayed: false, line: !!line };
}

function priceCell(price, name) {
  return isNum(price)
    ? h("span", { class: "lv-price hd-num", "aria-label": `best price for ${name}: ${fmtPrice(price)}`, text: fmtPrice(price) })
    : h("span", { class: "lv-price lv-price--none hd-num", "aria-label": `no price for ${name}`, text: "no price" });
}

function teamLine(name, price, score) {
  return h("div", { class: "lv-team" }, [
    h("span", { class: "lv-team__name", text: name || "TBD" }),
    score ? h("span", { class: "lv-team__score hd-num", "data-hook": "live-score", text: score }) : null,
    priceCell(price, name || "TBD")]);
}

function rowFor(ev, live) {
  const sc = scoreParts(ev);
  const start = toDate(ev.start_utc);
  const when = start ? dayClock(ev.start_utc) : "";
  const until = start && !live ? Math.round((start.getTime() - now().getTime()) / 60000) : null;
  const meta = [];
  if (live && sc.completed) meta.push(h("span", { class: "lv-pill", "data-hook": "live-pill", "data-state": "final", text: "Final" }));
  else if (live) meta.push(h("span", { class: "lv-pill lv-pill--live", "data-hook": "live-pill" }, [h("span", { class: "lv-dot", "aria-hidden": "true" }), "Live"]));
  else meta.push(h("span", { class: "lv-pill", text: "Upcoming" }));
  if (ev.league_title) meta.push(h("span", { class: "lv-league", text: ev.league_title }));
  const timing = live ? (when ? `Started ${when}` : "") : [when, until !== null && until > 0 ? `in ${spanText(until)}` : ""].filter(Boolean).join(" · ");
  if (timing) meta.push(h("span", { class: "lv-when", "data-hook": "live-when", text: timing }));
  if (sc.detail && !(sc.completed && /^final$/i.test(sc.detail))) {
    meta.push(h("span", { class: `lv-detail${sc.delayed ? " lv-detail--delayed" : ""}`, "data-hook": sc.delayed ? "live-score-delayed" : sc.line ? "live-state-line" : "live-period", text: sc.detail }));
  }
  // an in-play price is the last one a book showed, not a quote to bet at: say when it was read, per game
  if (live && !sc.completed && toDate(ev.observed_utc)) {
    meta.push(h("span", { class: "lv-when", "data-hook": "live-price-read", text: `Price read ${formatStamp("t", ev.observed_utc)}` }));
  }
  const li = h("li", { class: "lv-row", id: `lv-ev-${ev.event_id}`, "data-hook": "live-row", "data-event": ev.event_id, "data-family": ev._family, "data-live": live ? "true" : "false" });
  const open = state.trays.has(ev.event_id);
  const btn = h("button", { type: "button", class: "lv-send", "data-hook": "live-send", "data-event": ev.event_id,
    "aria-expanded": open ? "true" : "false", "aria-label": `Send a hound at ${ev.away || "TBD"} versus ${ev.home || "TBD"}`, text: "Send a hound",
    on: { click: () => toggleTray(ev, li, btn) } });
  li.appendChild(h("div", { class: "lv-row__top" }, [h("div", { class: "lv-row__meta" }, meta), btn]));   // the small secondary action sits at the end of the card's top line
  li.appendChild(h("div", { class: "lv-teams" }, [teamLine(ev.away, ev.best_price_away, sc.away), teamLine(ev.home, ev.best_price_home, sc.home)]));
  const on = houndsOnGame(ev);
  if (on) li.appendChild(on);
  if (open) li.appendChild(state.trays.get(ev.event_id));
  return li;
}

function group(g, capped) {
  const total = g.live.length + g.upcoming.length;
  const sec = h("section", { class: "lv-sport", "data-hook": "live-sport", "data-family": g.code, "aria-label": g.label });
  const counts = [`${total} ${total === 1 ? "game" : "games"}`];
  if (g.live.length) counts.push(`${g.live.length} live`);
  sec.appendChild(h("div", { class: "lv-sport__head", "data-hook": "live-sport-head" }, [
    g.live.length ? h("span", { class: "lv-dot", "aria-hidden": "true" }) : null,
    h("h2", { class: "lv-sport__title", text: g.label }),
    h("span", { class: "lv-sport__n hd-fine", "data-hook": "live-sport-count", text: counts.join(" · ") })]));
  const rows = g.live.map((ev) => ({ ev, live: true })).concat(g.upcoming.map((ev) => ({ ev, live: false })));
  const cap = state.more.has(g.code) ? rows.length : Math.max(capped, g.live.length);
  const shown = rows.slice(0, cap);
  sec.appendChild(h("ul", { class: "lv-list", "data-hook": "live-sport-list" }, shown.map((r) => rowFor(r.ev, r.live))));
  if (rows.length > shown.length) {
    sec.appendChild(h("button", { type: "button", class: "btn btn--ghost lv-more", "data-hook": "live-sport-more", "data-family": g.code,
      text: `Show ${rows.length - shown.length} more ${g.label}`, on: { click: () => { state.more.add(g.code); render(); } } }));
  }
  return sec;
}

function renderBoard(sel) {
  const host = q("live-board");
  if (!host) return;
  const active = typeof document.activeElement !== "undefined" ? document.activeElement : null;
  const wasSend = active && active.getAttribute ? active.getAttribute("data-event") : null;
  clearNode(host);
  const ids = new Set(sel.live.concat(sel.upcoming).map((e) => e.event_id));
  for (const id of [...state.trays.keys()]) if (!ids.has(id)) state.trays.delete(id);
  if (!sel.live.length && !sel.upcoming.length) {
    const next = nextText(earliestNext(sel.families));
    const named = sel.families.length === 1 ? sel.families[0].label : "any sport";
    host.appendChild(h("div", { class: "hd-state hd-state--missing lv-empty", "data-hook": "live-empty", role: "status" }, [
      h("p", { text: `Nothing on in ${state.family === "all" ? "any sport we price" : named} right now.${next ? ` Next: ${next}.` : ""}` })]));
    return;
  }
  const capped = state.family === "all" ? GROUP_CAP : ROW_CAP;
  for (const g of sel.groups) host.appendChild(group(g, capped));
  if (wasSend) {
    const again = host.querySelector(`[data-hook='live-send'][data-event='${wasSend}']`);
    if (again && again.focus) again.focus();
  }
}

function renderStatus() {
  const box = q("live-status");
  if (!box) return;
  const parts = [];
  const anyLive = families().some((f) => f.live.some((e) => !(e.score && e.score.completed)));
  const sc = state.data && state.data.scores;
  const upd = toDate(sc && sc.updated_utc);
  if (upd) {
    const secs = Math.max(0, Math.round((now().getTime() - upd.getTime()) / 1000));
    parts.push(secs < 90 ? `Scores updated ${secs} sec ago` : `Scores updated ${spanText(Math.round(secs / 60))} ago`);
  } else if (anyLive) {
    parts.push("Scores delayed");
  }
  const read = toDate(state.data && state.data.prices_observed_utc);
  if (read) {
    const age = Math.max(0, Math.round((now().getTime() - read.getTime()) / 60000));
    parts.push(`Prices read ${formatStamp("c", state.data.prices_observed_utc)}`);
    if (age >= STALE_MINUTES) parts.push(`${spanText(age)} old, so prices may have moved`);
  }
  parts.push("page checks again every minute");
  box.textContent = parts.join(" · ") + ".";
  box.setAttribute("data-stale", state.failed ? "true" : "false");
  const warn = q("live-refresh-note");
  if (warn) {
    if (state.failed) { warn.textContent = "The last refresh did not go through, so this is the board from before. It will try again in a minute."; warn.removeAttribute("hidden"); }
    else { warn.textContent = ""; warn.setAttribute("hidden", ""); }
  }
}

function render() {
  const sel = selected();
  renderChips();
  renderNow(sel);
  renderBoard(sel);
  renderStatus();
}

// ---- send a hound ------------------------------------------------------------------------------------------

function myDogs() {
  if (!state.dogs) {
    state.dogs = get("/hounds/camp/mine").then((data) => (Array.isArray(data && data.dogs) ? data.dogs : [])).catch((err) => { state.dogs = null; throw err; });
  }
  return state.dogs;
}

/** Does `dog` bet the sport family `code` (a game's family, as /sports/now names it)? The server lists a hound's sports in lower case
 * (GET /hounds/camp/mine `sports`). A hound whose list is missing or empty is not known NOT to bet it, so it stays on offer. */
export function betsSport(dog, code) {
  const sports = Array.isArray(dog && dog.sports) ? dog.sports.map((x) => String(x).toLowerCase()) : [];
  if (!sports.length || !code) return true;
  return sports.includes(String(code).toLowerCase());
}

const gameName = (ev) => `${ev.away || "TBD"} at ${ev.home || "TBD"}`;

/** What `dog`'s fire answer says about THIS game: its pick, why it passed, or that the game was not among its answers. */
export function eventSummary(data, ev, dogName) {
  const lines = [];
  if (data && data.event_id === ev.event_id && typeof data.picked === "boolean") {       // the per-game answer (fire_event.py)
    const p = data.pick || (Array.isArray(data.picks) ? data.picks[0] : null);
    if (data.picked && p) {
      const bits = [`Average price ${fmtPrice(p.price_average)}`];
      if (isNum(p.n_books)) bits.push(`${p.n_books} books quoting`);
      lines.push({ kind: "pick", head: `${dogName} would back ${p.selection}${p.market_label ? ` (${p.market_label})` : ""}.`, detail: `${bits.join(", ")}. ${p.reason || data.reason || ""}`.trim() });
    } else {
      lines.push({ kind: "miss", head: `${dogName} passes on this one.`, detail: data.reason || "" });
    }
    return lines;
  }
  const picks = (Array.isArray(data && data.picks) ? data.picks : []).filter((p) => p.event_id === ev.event_id);
  const sameGame = (m) => m.event_id === ev.event_id || (m.game && ev.home && ev.away && String(m.game).includes(ev.home) && String(m.game).includes(ev.away));
  const misses = (Array.isArray(data && data.closest_misses) ? data.closest_misses : []).filter(sameGame);
  for (const p of picks) {
    const bits = [`Average price ${fmtPrice(p.price_average)}`];
    if (isNum(p.n_books)) bits.push(`${p.n_books} books quoting`);
    lines.push({ kind: "pick", head: `${dogName} would back ${p.selection}${p.market_label ? ` (${p.market_label})` : ""}.`, detail: `${bits.join(", ")}. ${p.reason || ""}`.trim() });
  }
  if (!picks.length) {
    for (const m of misses) lines.push({ kind: "miss", head: `${dogName} passes on this one.`, detail: `${m.title ? `${m.title}. ` : ""}${m.why || ""}`.trim() });
  }
  if (!lines.length) {
    lines.push({ kind: "none", head: `${dogName} did not return this game.`,
      detail: `It is not among the picks or the passes in the answer. ${data && data.headline ? data.headline : ""}`.trim() });
  }
  return lines;
}

function trayShell(ev) {
  return h("div", { class: "lv-tray", "data-hook": "live-tray", "data-event": ev.event_id, "aria-live": "polite" });
}

function closeTray(ev, li, btn) {
  const tray = state.trays.get(ev.event_id);
  state.trays.delete(ev.event_id);
  if (tray && tray.parentNode) tray.parentNode.removeChild(tray);
  btn.setAttribute("aria-expanded", "false");
}

function toggleTray(ev, li, btn) {
  if (state.trays.has(ev.event_id)) { closeTray(ev, li, btn); return; }
  const tray = trayShell(ev);
  state.trays.set(ev.event_id, tray);
  li.appendChild(tray);
  btn.setAttribute("aria-expanded", "true");
  showPicker(tray, ev);
}

async function showPicker(tray, ev) {
  clearNode(tray);
  if (!getToken()) {
    tray.appendChild(signInPrompt(`Sign in to send one of your hounds at ${gameName(ev)}.`));
    tray.appendChild(h("p", { class: "hd-fine" }, ["No hound yet? ", h("a", { href: "quiz.html", text: "Create one" }), "."]));
    return;
  }
  tray.appendChild(h("p", { class: "hd-fine", role: "status", "data-hook": "live-dogs-loading", text: "Loading your hounds..." }));
  let dogs;
  try {
    dogs = await myDogs();
  } catch (err) {
    clearNode(tray);
    tray.appendChild(err && err.status === 401 ? signInPrompt("Your sign-in has expired.")
      : h("p", { class: "hd-muted", "data-hook": "live-dogs-error", text: errorText(err, "Your hounds could not be loaded just now. Try again in a minute.") }));
    return;
  }
  clearNode(tray);
  const running = dogs.filter((d) => d.status !== "retired");
  if (!running.length) {
    tray.appendChild(h("p", { class: "hd-muted", "data-hook": "live-no-dogs" }, ["You have no running hound to send. ", h("a", { href: "quiz.html", text: "Create one" }), "."]));
    return;
  }
  // only a hound that bets this game's sport can be sent at it (QA 2026-10-21: MLB hounds were offered for hockey)
  const usable = running.filter((d) => betsSport(d, ev._family));
  if (!usable.length) {
    tray.appendChild(h("p", { class: "hd-muted", "data-hook": "live-no-sport-dogs" }, [
      `None of your hounds bet ${ev._familyLabel || "this sport"} yet. `, h("a", { href: "quiz.html", text: "Create one" }), "."]));
    return;
  }
  tray.appendChild(h("p", { class: "lv-tray__ask", text: `Send which hound at ${gameName(ev)}?` }));
  tray.appendChild(h("div", { class: "lv-dogs", role: "group", "aria-label": "Your hounds", "data-hook": "live-dog-list" }, usable.map((d) =>
    h("button", { type: "button", class: "lv-dog", "data-hook": "live-dog", "data-dog": d.id, on: { click: () => sendDog(tray, ev, d) } }, [
      h("span", { class: "lv-dog__face", "aria-hidden": "true" }, [dogFace(d, { size: 28 })]),
      h("span", { class: "lv-dog__name", text: d.name }),
      h("span", { class: "lv-dog__state hd-fine", text: d.status === "running" ? "Running" : "Idle" })]))));
  tray.appendChild(h("p", { class: "hd-fine", text: "This runs the hound's rule on the stored boards and shows what it would pick. Nothing is placed." }));
}

async function sendDog(tray, ev, dog) {
  clearNode(tray);
  tray.appendChild(h("p", { class: "hd-fine", role: "status", "data-hook": "live-send-status", text: `Sending ${dog.name} at ${gameName(ev)}...` }));
  let data;
  try {
    data = await unleash(dog.id, ev.event_id);       // a LIVE send is the per-game call: member accounts only
  } catch (err) {
    clearNode(tray);
    if (showUpgrade(tray, err)) return;
    tray.appendChild(h("p", { class: "hd-muted", "data-hook": "live-send-error", "data-code": errorCode(err),
      text: errorText(err, "The boards could not be read just now. Try again in a minute.") }));
    tray.appendChild(h("button", { type: "button", class: "btn btn--ghost", text: "Pick a hound again", on: { click: () => showPicker(tray, ev) } }));
    return;
  }
  clearNode(tray);
  const lines = eventSummary(data, ev, dog.name);
  tray.appendChild(h("div", { class: "lv-result", "data-hook": "live-result" }, lines.map((l) => h("div", { class: `lv-result__line lv-result__line--${l.kind}`, "data-kind": l.kind }, [
    h("strong", { text: l.head }), l.detail ? h("p", { class: "hd-muted", text: l.detail }) : null]))));
  const full = h("div", { class: "dk-result" });
  renderFireResult(full, data, { id: dog.id, name: dog.name });
  tray.appendChild(h("details", { class: "lv-full" }, [h("summary", { text: `Everything ${dog.name} returned` }), full]));
  tray.appendChild(h("div", { class: "lv-tray__actions" }, [
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "live-another", text: "Send a different hound", on: { click: () => showPicker(tray, ev) } }),
    dog.page_href ? h("a", { class: "btn btn--ghost", href: dog.page_href, text: `Open ${dog.name}` }) : null]));
  tray.appendChild(h("p", { class: "hd-fine", text: data.preview_note || PAPER_NOTE }));
}

// ---- reading what is on the board: live state and open tickets ---------------------------------------------

async function soft(path) {
  try { return await apiGet(path); } catch (err) { return null; }
}

/** The grader's state for the games in play, 60 ids a call (GET /hounds/live). A failed read keeps what was there. */
async function loadStates() {
  const ids = families().flatMap((f) => f.live.map((ev) => ev.event_id)).filter(Boolean);
  if (!ids.length) { state.states = new Map(); return; }
  const next = new Map();
  let read = false;
  for (let i = 0; i < ids.length; i += 60) {
    const out = await soft(`/hounds/live?ids=${ids.slice(i, i + 60).map(encodeURIComponent).join(",")}`);
    const games = out && out.games && typeof out.games === "object" ? out.games : null;
    if (!games) continue;
    read = true;
    for (const [id, st] of Object.entries(games)) next.set(id, st);
  }
  if (read) state.states = next;
}

const isOpenTicket = (t) => t && t.event_id && t.segment !== "replay" && !t.refused
  && (t.status ? String(t.status).toUpperCase() === "OPEN" : !t.result);

function addTicket(map, hound, t) {
  const side = String(t.selection || "").trim();
  if (!side) return;
  const list = map.get(t.event_id) || [];
  const have = list.find((x) => x.hound.id === hound.id);
  if (have) { if (!have.side.split(" · ").includes(side) && have.side.split(" · ").length < 2) have.side += ` · ${side}`; }
  else list.push({ hound, side });
  map.set(t.event_id, list);
}

/** The house pack: Map(id -> hound) from GET /hounds (kind "house"), read at most every ten minutes. null when unreadable. */
async function loadPack() {
  if (state.pack.hounds && now().getTime() - state.pack.at < PACK_TTL_MS) return state.pack.hounds;
  const data = await soft("/hounds");
  if (!data || !Array.isArray(data.hounds)) return state.pack.hounds;
  const map = new Map();
  for (const x of data.hounds) if (x && x.id && x.kind === "house" && !x.retired) map.set(x.id, x);
  state.pack = { at: now().getTime(), hounds: map };
  return map;
}

async function loadHounds() {
  const shown = new Set(families().flatMap((f) => f.live.concat(f.upcoming)).map((ev) => ev.event_id));
  const pack = new Map();
  const mine = new Map();
  const [house, stream, dogs] = await Promise.all([
    loadPack(), soft("/hounds/stream?page=1&page_size=100"),
    getToken() ? myDogs().catch(() => null) : Promise.resolve(null)]);
  if (house && stream && Array.isArray(stream.items)) {
    for (const t of stream.items) if (isOpenTicket(t) && shown.has(t.event_id) && house.has(t.hound_id)) addTicket(pack, house.get(t.hound_id), t);
    state.onGame.pack = pack;
  }
  if (Array.isArray(dogs)) {
    const asked = dogs.filter((d) => d && d.status !== "retired" && isNum(d.open_bets) && d.open_bets > 0).slice(0, MINE_READS);
    let read = 0;
    await Promise.all(asked.map(async (d) => {
      const out = await soft(`/hounds/${encodeURIComponent(d.id)}/bets?page=1&page_size=8&segment=forward&status=open`);
      if (!out || !Array.isArray(out.items)) return;
      read += 1;
      for (const t of out.items) if (isOpenTicket(t) && shown.has(t.event_id)) addTicket(mine, d, t);
    }));
    if (read || !asked.length) state.onGame.mine = mine;
  }
}

// ---- loading ---------------------------------------------------------------------------------------------

export async function load() {
  if (state.busy) return state.data;
  state.busy = true;
  const refresh = q("live-refresh");
  if (refresh) refresh.setAttribute("disabled", "");
  try {
    const data = await apiGet("/sports/now");
    if (!data || !Array.isArray(data.families)) throw Object.assign(new Error("bad payload"), { status: 502 });
    state.data = data;
    // an unknown ?sport= falls back to All instead of an empty page
    if (state.family !== "all" && !families().some((f) => f.code === state.family)) state.family = "all";
    state.failed = false;
    state.loadedAt = now();
    render();
    // the board is on the page; the live scores and the hounds on each game arrive after it, and each read is soft
    await Promise.all([loadStates(), loadHounds()]).catch(() => null);
    render();
  } catch (err) {
    if (!state.data) {
      const host = q("live-board");
      if (host) {
        clearNode(host);
        // a visitor (Live is one of the signed-out places) gets a way in, not a dead end (rebuild QA 2026-10-21)
        const auth = describeError(err, "the live board").kind === "auth";
        host.appendChild(h("div", { class: `hd-state hd-state--${err && err.status === 404 ? "missing" : "down"}`, role: "status", "data-hook": "live-error",
          "data-kind": auth ? "auth" : "error" }, [
          auth ? signInPrompt("The live board is for signed-in members: see what is on in every sport and send your hounds at it.")
            : h("p", { text: describeError(err, "the live board").text })]));
      }
      // "Loading the board..." is not true once the load has failed with nothing to show
      const status = q("live-status");
      if (status) status.textContent = "";
      const chips = q("live-chips");
      if (chips) clearNode(chips);
    } else {
      state.failed = true;
      renderStatus();
    }
  } finally {
    state.busy = false;
    if (refresh) refresh.removeAttribute("disabled");
  }
  return state.data;
}

export function boot() {
  if (!q("live-board")) return null;
  let wanted = "";
  try { wanted = new URLSearchParams((typeof location !== "undefined" && location.search) || "").get("sport") || ""; } catch (err) { wanted = ""; }
  if (wanted) state.family = wanted;
  const refresh = q("live-refresh");
  if (refresh) refresh.addEventListener("click", () => load());
  const first = load();
  const poller = createPoller({ run: () => load(), intervalMs: REFRESH_MS });
  poller.start();
  return { first, poller };
}

boot();
