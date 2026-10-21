/**
 * THE LIVE BOARD (web/live.html): "What's on". Every sport the server prices, as a sportsbook's live tab: a chip per sport family,
 * LIVE first (a pulsing dot), then the next 24 hours, each row with its teams or players, its league, its start time in the
 * VIEWER'S zone and the best price quoted for each side, and a "Send a dog" button.
 *
 *   GET /sports/now   {generated_utc, families: [{code, label, live: [row], upcoming_24h: [row], next_start_utc}]}
 *       row = {event_id, league_title, home, away, start_utc, in_play, best_price_home, best_price_away, score?}
 *       `score` is read leniently: a string ("2-1, 62'") or {home, away, detail?}.
 *
 * SEND A DOG. A signed-out visitor is asked to sign in. A member sees their own dogs (GET /hounds/camp/mine, the Training camp's
 * list) and picks one; the page then calls the existing preview route (POST /hounds/{id}/fire, web/js/dog-fire.js unleash)
 * and says what that dog did with THIS game: the pick it made, the reason it passed, or that the game was not among its answers.
 * That route runs the dog's rule over the stored boards and writes nothing. Nothing here places a bet and nothing here claims a
 * price is an advantage: a best price is the best number any book is quoting, no more.
 *
 * It refreshes itself every 60 seconds while the page is visible (createPoller), keeps the board it has when a refresh fails and
 * says so, and keeps any open "Send a dog" tray across a refresh. Written against attributes only (no classList, no dataset), so
 * it runs under the small fake DOM of tests/hounds_web_harness.mjs as well as in a browser.
 */

import { apiGet, getToken } from "./api.js";
import { h, clearNode, fmtPrice, isNum, createPoller, describeError } from "./hounds-core.js";
import { dogFace } from "./dog-avatar.js";
import { get, errorText, errorCode, signInPrompt, spanText, PAPER_NOTE } from "./dog-common.js";
import { renderFireResult, unleash } from "./dog-fire.js";
import { showUpgrade } from "./upgrade.js";

export const REFRESH_MS = 60000;
const ROW_CAP = 20;
const STALE_MINUTES = 5;

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
const now = () => new Date(Date.now());

const state = {
  data: null,            // the last good /sports/now payload
  family: "all",
  loadedAt: null,
  failed: false,
  more: { live: false, upcoming: false },
  trays: new Map(),      // event_id -> the open tray node, kept across refreshes
  dogs: null,            // Promise of the member's dogs, once asked
  busy: false,
};

// ---- time ------------------------------------------------------------------------------------------------

function toDate(stamp) {
  const d = new Date(stamp);
  return !stamp || Number.isNaN(d.getTime()) ? null : d;
}

function clock(d) {
  try { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); } catch (err) { return ""; }
}

function zoneName(d) {
  try { return d.toLocaleTimeString([], { timeZoneName: "short" }).split(" ").pop(); } catch (err) { return ""; }
}

function dayStart(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); }

/** "7:05 PM" today, "Tomorrow 1:30 AM", "Thu 7:15 PM" later, in the viewer's own zone; "" when unreadable. */
export function dayClock(stamp, ref = now()) {
  const d = toDate(stamp);
  if (!d) return "";
  const days = Math.round((dayStart(d) - dayStart(ref)) / 86400000);
  if (days === 0) return clock(d);
  if (days === 1) return `Tomorrow ${clock(d)}`;
  if (days === -1) return `Yesterday ${clock(d)}`;
  let wd = "";
  try { wd = d.toLocaleDateString([], { weekday: "short" }); } catch (err) { wd = ""; }
  return `${wd} ${clock(d)}`.trim();
}

/** "Today 7:15 PM" / "Tomorrow 7:15 PM" / "Thu 7:15 PM": the day always said, for "Next: ...". */
export function nextText(stamp, ref = now()) {
  const d = toDate(stamp);
  if (!d) return "";
  const text = dayClock(stamp, ref);
  return Math.round((dayStart(d) - dayStart(ref)) / 86400000) === 0 ? `Today ${text}` : text;
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

function selected() {
  const all = families();
  const pick = state.family === "all" ? all : all.filter((f) => f.code === state.family);
  const tag = (kind) => pick.flatMap((f) => f[kind].map((ev) => Object.assign({}, ev, { _family: f.code, _familyLabel: f.label }))).sort(byStart);
  return { families: pick, live: tag("live"), upcoming: tag("upcoming") };
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
  // sports with something on first, busiest first; quiet sports stay reachable at the end
  const ordered = all.slice().sort((a, b) => (b.live.length - a.live.length) || ((b.live.length + b.upcoming.length) - (a.live.length + a.upcoming.length)));
  for (const f of ordered) host.appendChild(chip(f.code, f.label, f.live.length + f.upcoming.length, f.live.length));
}

function selectFamily(code) {
  if (state.family === code) return;
  state.family = code;
  state.more = { live: false, upcoming: false };
  try {
    if (typeof window !== "undefined" && window.history && window.history.replaceState) {
      window.history.replaceState(null, "", code === "all" ? "live.html" : `live.html?sport=${encodeURIComponent(code)}`);
    }
  } catch (err) { /* a blocked history is not a failure */ }
  render();
}

// ---- rows ------------------------------------------------------------------------------------------------

function scoreParts(ev) {
  const s = ev.score;
  if (s && typeof s === "object") {
    return { home: isNum(s.home) ? String(s.home) : "", away: isNum(s.away) ? String(s.away) : "", detail: s.detail ? String(s.detail) : "" };
  }
  return { home: "", away: "", detail: typeof s === "string" ? s : "" };
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
  if (live) meta.push(h("span", { class: "lv-pill lv-pill--live", "data-hook": "live-pill" }, [h("span", { class: "lv-dot", "aria-hidden": "true" }), "Live"]));
  else meta.push(h("span", { class: "lv-pill", text: "Upcoming" }));
  if (ev.league_title) meta.push(h("span", { class: "lv-league", text: ev.league_title }));
  if (state.family === "all" && ev._familyLabel) meta.push(h("span", { class: "lv-family", text: ev._familyLabel }));
  const timing = live ? (when ? `Started ${when}` : "") : [when, until !== null && until > 0 ? `in ${spanText(until)}` : ""].filter(Boolean).join(" · ");
  if (timing) meta.push(h("span", { class: "lv-when", "data-hook": "live-when", text: timing }));
  if (sc.detail) meta.push(h("span", { class: "lv-detail", text: sc.detail }));
  const li = h("li", { class: "lv-row", "data-hook": "live-row", "data-event": ev.event_id, "data-family": ev._family, "data-live": live ? "true" : "false" });
  li.appendChild(h("div", { class: "lv-row__body" }, [
    h("div", { class: "lv-row__meta" }, meta),
    h("div", { class: "lv-teams" }, [teamLine(ev.away, ev.best_price_away, sc.away), teamLine(ev.home, ev.best_price_home, sc.home)])]));
  const open = state.trays.has(ev.event_id);
  const btn = h("button", { type: "button", class: "btn btn--ghost lv-send", "data-hook": "live-send", "data-event": ev.event_id,
    "aria-expanded": open ? "true" : "false", "aria-label": `Send a hound at ${ev.away || "TBD"} versus ${ev.home || "TBD"}`, text: "Send a hound",
    on: { click: () => toggleTray(ev, li, btn) } });
  li.appendChild(h("div", { class: "lv-row__act" }, [btn]));
  if (open) li.appendChild(state.trays.get(ev.event_id));
  return li;
}

function section(kind, title, rows, live, emptyText) {
  const sec = h("section", { class: `lv-section lv-section--${kind}`, "data-hook": `live-${kind}-section`, "aria-label": title });
  const head = h("div", { class: "lv-section__head" }, [
    live && rows.length ? h("span", { class: "lv-dot", "aria-hidden": "true" }) : null,
    h("h2", { class: "lv-section__title", text: title }),
    h("span", { class: "lv-section__n hd-fine", "data-hook": `live-${kind}-count`, text: String(rows.length) })]);
  sec.appendChild(head);
  if (!rows.length) {
    sec.appendChild(h("p", { class: "hd-muted lv-quiet", "data-hook": `live-${kind}-empty`, text: emptyText }));
    return sec;
  }
  const shown = state.more[kind] ? rows : rows.slice(0, ROW_CAP);
  sec.appendChild(h("ul", { class: "lv-list", "data-hook": `live-${kind}-list` }, shown.map((ev) => rowFor(ev, live))));
  if (rows.length > shown.length) {
    sec.appendChild(h("button", { type: "button", class: "btn btn--ghost lv-more", "data-hook": `live-${kind}-more`,
      text: `Show ${rows.length - shown.length} more`, on: { click: () => { state.more[kind] = true; render(); } } }));
  }
  return sec;
}

function famLabel(pick) { return pick.length === 1 ? pick[0].label : "any sport"; }

function renderBoard() {
  const host = q("live-board");
  if (!host) return;
  const active = typeof document.activeElement !== "undefined" ? document.activeElement : null;
  const wasSend = active && active.getAttribute ? active.getAttribute("data-event") : null;
  clearNode(host);
  const sel = selected();
  const ids = new Set(sel.live.concat(sel.upcoming).map((e) => e.event_id));
  for (const id of [...state.trays.keys()]) if (!ids.has(id)) state.trays.delete(id);
  if (!sel.live.length && !sel.upcoming.length) {
    const next = nextText(earliestNext(sel.families));
    host.appendChild(h("div", { class: "hd-state hd-state--missing lv-empty", "data-hook": "live-empty", role: "status" }, [
      h("p", { text: `Nothing on in ${state.family === "all" ? "any sport we price" : famLabel(sel.families)} right now.${next ? ` Next: ${next}.` : ""}` })]));
    return;
  }
  const label = famLabel(sel.families);
  host.appendChild(section("live", "Live now", sel.live, true, `Nothing live in ${label} right now.`));
  host.appendChild(section("upcoming", "Next 24 hours", sel.upcoming, false,
    `Nothing else starts in ${label} in the next 24 hours.${earliestNext(sel.families) && !sel.live.length ? ` Next: ${nextText(earliestNext(sel.families))}.` : ""}`));
  if (wasSend) {
    const again = host.querySelector(`[data-hook='live-send'][data-event='${wasSend}']`);
    if (again && again.focus) again.focus();
  }
}

function renderStatus() {
  const box = q("live-status");
  if (!box) return;
  const parts = [];
  const gen = toDate(state.data && state.data.generated_utc);
  if (gen) {
    const age = Math.max(0, Math.round((now().getTime() - gen.getTime()) / 60000));
    parts.push(`Board as of ${clock(gen)} ${zoneName(gen)}`.trim());
    if (age >= STALE_MINUTES) parts.push(`${spanText(age)} old, so prices may have moved`);
  }
  parts.push("refreshes every minute");
  box.textContent = parts.join(" · ") + ".";
  box.setAttribute("data-stale", state.failed ? "true" : "false");
  const warn = q("live-refresh-note");
  if (warn) {
    if (state.failed) { warn.textContent = "The last refresh did not go through, so this is the board from before. It will try again in a minute."; warn.removeAttribute("hidden"); }
    else { warn.textContent = ""; warn.setAttribute("hidden", ""); }
  }
}

function render() {
  renderChips();
  renderBoard();
  renderStatus();
}

// ---- send a dog ------------------------------------------------------------------------------------------

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
