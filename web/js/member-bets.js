/**
 * LOG A BET: a member's own bet log (docs/plans/MEMBER_BET_LOG.md; server: api/member_bets.py). Nothing here is public.
 *
 *   logBetPanel(event, {prefill, onSaved})   the "Log a bet" panel, shared by the Live board (web/js/live-board.js) and a hound's ticket
 *                                            (web/js/hounds-tickets.js "Log this bet"). `event` = {event_id, sport, home_team, away_team,
 *                                            commence_time, markets?: {spread: {line}, total: {line}}}. With no `markets` the panel asks the
 *                                            server which markets the board has (GET /me/bets/price); a market with no price is not offered.
 *                                            `prefill` = {market, side, line, price} opens on that side with that price (a hound's bet).
 *   mountMyBets(host)                        the kennel's "My bets" tab: record line, open bets (Remove while the game has not started),
 *                                            settled bets, bets the server could not match, and the "Log a bet by hand" form.
 *
 * Every number and every refusal is the server's: an error is shown as the sentence the server sent, word for word. The price field is
 * filled from the board and stays editable. Written against attributes only (no classList, no dataset) so it runs under the fake DOM of
 * tests/hounds_web_harness.mjs as well as in a browser.
 */

import { apiGet, apiPost, apiDelete, getToken } from "./api.js";
import { h, clearNode, fmtPrice, isNum } from "./hounds-core.js";
import { signInPrompt, errorText } from "./dog-common.js";
import { formatStamp } from "./local-time.js";
import { SPORT_LABELS } from "./hounds-board.js";

export const MY_BETS_HREF = "kennel.html?tab=mybets";
export const STAKE_KEY = "linehound.member_bet_stake";
export const NOTE_MAX = 140;
const STAKE_MIN = 0.25;
const STAKE_MAX = 10;
const PRICE_HELP = "Type the price the way a sportsbook shows it, like -110 or +150.";
const NO_PRICE = "We have no current price for this side. Type the price you got.";

let counter = 0;
const uid = (prefix) => `${prefix}-${++counter}`;

// ---- small helpers --------------------------------------------------------------------------------

function lastStake() {
  try {
    const raw = window.localStorage.getItem(STAKE_KEY);
    const n = raw === null ? NaN : Number(raw);
    if (Number.isFinite(n) && n >= STAKE_MIN && n <= STAKE_MAX) return n;
  } catch (err) { /* storage blocked */ }
  return 1;
}

function rememberStake(n) {
  try { window.localStorage.setItem(STAKE_KEY, String(n)); } catch (err) { /* storage blocked */ }
}

/** The server's own sentence (a plain string detail), else the shared fallback wording. */
export function sentence(err, fallback) {
  if (err && typeof err.detail === "string" && err.detail.trim()) return err.detail.trim();
  return errorText(err, fallback);
}

const signedLine = (n) => (n > 0 ? `+${n}` : String(n));
const shortNum = (n) => String(Math.round(n * 100) / 100);

/** "+3.2 units" / "-1.0 units" / "0.0 units". */
export function unitsText(n) {
  const v = isNum(n) ? n : 0;
  return `${v > 0 ? "+" : v < 0 ? "-" : ""}${Math.abs(v).toFixed(1)} units`;
}

/** "3-1-0, +2.4 units": the record line, wins-losses-pushes then the units. */
export function recordLine(rec) {
  const r = rec || {};
  return `${r.w || 0}-${r.l || 0}-${r.p || 0}, ${unitsText(r.units)}`;
}

function pricePlain(n) {
  return isNum(n) ? fmtPrice(n) : "";
}

const gameName = (ev) => `${ev.away_team || "TBD"} at ${ev.home_team || "TBD"}`;

function marketKey(raw) {
  const k = String(raw || "").toLowerCase();
  if (k === "h2h" || k === "moneyline") return "moneyline";
  if (k === "totals" || k === "total") return "total";
  if (k === "spreads" || k === "spread") return "spread";
  return "";
}

/** The sides a market offers, with the line each side carries. `line` is the HOME line for a spread and the number for a total. */
function sidesOf(ev, market, line) {
  const away = ev.away_team || "Away";
  const home = ev.home_team || "Home";
  if (market === "moneyline") {
    return [{ market, side: "away", line: null, label: `${away} to win` }, { market, side: "home", line: null, label: `${home} to win` }];
  }
  if (market === "spread" && isNum(line)) {
    return [{ market, side: "away", line: -line, label: `${away} ${signedLine(-line)}` },
      { market, side: "home", line, label: `${home} ${signedLine(line)}` }];
  }
  if (market === "total" && isNum(line)) {
    return [{ market, side: "over", line, label: `Over ${line}` }, { market, side: "under", line, label: `Under ${line}` }];
  }
  return [];
}

function priceUrl(ev, market, side) {
  return `/me/bets/price?event_id=${encodeURIComponent(ev.event_id)}&market=${market}&side=${side}`;
}

// ---- the panel ------------------------------------------------------------------------------------

export function logBetPanel(ev, { prefill = null, onSaved = null } = {}) {
  ev = ev || {};
  if (!getToken()) {
    return h("div", { class: "mb-panel", "data-hook": "log-bet-panel" }, [signInPrompt(`Sign in to log a bet on ${gameName(ev)}.`)]);
  }
  const ids = { price: uid("mb-price"), stake: uid("mb-stake"), note: uid("mb-note") };
  const pre = prefill && marketKey(prefill.market) ? { ...prefill, market: marketKey(prefill.market) } : null;
  const markets = {};            // market -> the line the board is on (home line / total); null for a moneyline
  const sel = { market: null, side: null, line: null };
  let priceDirty = false;
  let priceToken = 0;
  let busy = false;

  const start = ev.commence_time ? Date.parse(ev.commence_time) : NaN;
  const inPlay = Number.isFinite(start) && start <= Date.now();

  const sideBox = h("div", { class: "mb-sides", role: "group", "aria-label": "Pick a side", "data-hook": "log-bet-sides" });
  const priceInput = h("input", { id: ids.price, class: "mb-input", type: "text", inputmode: "numeric", autocomplete: "off",
    placeholder: "-110", "data-hook": "log-bet-price", "aria-describedby": `${ids.price}-hint` });
  const priceHint = h("p", { class: "mb-hint", id: `${ids.price}-hint`, "data-hook": "log-bet-price-hint", text: "Pick a side to see the current price." });
  const stakeInput = h("input", { id: ids.stake, class: "mb-input", type: "number", inputmode: "decimal", step: "0.25", min: String(STAKE_MIN),
    max: String(STAKE_MAX), value: shortNum(lastStake()), "data-hook": "log-bet-stake" });
  const noteInput = h("input", { id: ids.note, class: "mb-input", type: "text", maxlength: String(NOTE_MAX), autocomplete: "off",
    placeholder: "Optional", "data-hook": "log-bet-note" });
  const status = h("p", { class: "mb-status", role: "status", "aria-live": "polite", "data-hook": "log-bet-error", hidden: true });
  const save = h("button", { type: "button", class: "btn btn--primary mb-save", "data-hook": "log-bet-save", text: "Save", on: { click: () => submit() } });
  priceInput.addEventListener("input", () => { priceDirty = true; });
  const form = h("div", { class: "mb-form", "data-hook": "log-bet-form" }, [
    h("div", { class: "mb-field" }, [h("span", { class: "mb-label", text: "Side" }), sideBox]),
    h("div", { class: "mb-row" }, [
      h("div", { class: "mb-field" }, [h("label", { class: "mb-label", for: ids.price, text: "Price" }), priceInput, priceHint]),
      h("div", { class: "mb-field" }, [h("label", { class: "mb-label", for: ids.stake, text: "Stake (units)" }), stakeInput])]),
    h("div", { class: "mb-field" }, [h("label", { class: "mb-label", for: ids.note, text: "Note" }), noteInput]),
    status,
    h("div", { class: "mb-actions" }, [save])]);
  const head = [h("strong", { class: "mb-game", "data-hook": "log-bet-game", text: gameName(ev) })];
  if (inPlay) head.push(h("span", { class: "mb-pill", "data-hook": "log-bet-inplay", text: "In play" }));
  const panel = h("div", { class: "mb-panel", "data-hook": "log-bet-panel", "data-event": String(ev.event_id || "") },
    [h("div", { class: "mb-head" }, head), form]);

  function say(text) {
    if (text) { status.textContent = text; status.removeAttribute("hidden"); } else { status.textContent = ""; status.setAttribute("hidden", ""); }
  }

  function optionList() {
    const out = [];
    if (pre) {
      // a hound's bet: its market only, both sides, on the line it took
      const line = pre.market === "spread" && pre.side === "away" && isNum(Number(pre.line)) ? -Number(pre.line) : Number(pre.line);
      return sidesOf(ev, pre.market, pre.market === "moneyline" ? null : (Number.isFinite(line) ? line : null));
    }
    for (const m of ["moneyline", "spread", "total"]) {
      if (m in markets) out.push(...sidesOf(ev, m, markets[m]));
    }
    return out;
  }

  function paintSides() {
    clearNode(sideBox);
    for (const o of optionList()) {
      const on = sel.market === o.market && sel.side === o.side;
      sideBox.appendChild(h("button", { type: "button", class: "mb-side", "data-hook": "log-bet-side", "data-market": o.market, "data-side": o.side,
        "data-line": o.line === null ? "" : String(o.line), "aria-pressed": on ? "true" : "false", text: o.label, on: { click: () => choose(o) } }));
    }
  }

  async function fillPrice(o) {
    const mine = ++priceToken;
    priceHint.textContent = "Looking up the current price...";
    let out = null;
    try {
      out = await apiGet(priceUrl(ev, o.market, o.side));
    } catch (err) {
      if (mine !== priceToken) return;
      if (err && err.status === 401) { say("Your sign-in has expired. Sign in again to log a bet."); }
      priceHint.textContent = NO_PRICE;
      return;
    }
    if (mine !== priceToken || priceDirty) return;
    if (out && isNum(out.price)) {
      priceInput.value = String(Math.round(out.price));
      priceHint.textContent = out.n_books ? `Average of ${out.n_books} ${out.n_books === 1 ? "book" : "books"} right now. Change it to the price you got.` : "The current average. Change it to the price you got.";
    } else {
      priceInput.value = "";
      priceHint.textContent = NO_PRICE;
    }
  }

  function choose(o) {
    sel.market = o.market; sel.side = o.side; sel.line = o.line;
    priceDirty = false;
    say("");
    paintSides();
    fillPrice(o);
  }

  async function probe() {
    if (ev.markets && typeof ev.markets === "object") {
      for (const m of ["spread", "total"]) if (ev.markets[m] && isNum(ev.markets[m].line)) markets[m] = ev.markets[m].line;
      paintSides();
      return;
    }
    const asks = [["spread", "home"], ["total", "over"]].map(async ([m, s]) => {
      try {
        const out = await apiGet(priceUrl(ev, m, s));
        if (out && isNum(out.price) && isNum(out.line)) markets[m] = out.line;
      } catch (err) { /* the board has no such market: it is not offered */ }
    });
    await Promise.all(asks);
    paintSides();
  }

  async function submit() {
    if (busy) return;
    if (!sel.market || !sel.side) { say("Pick a side first."); return; }
    const stake = Number(String(stakeInput.value).trim());
    if (!Number.isFinite(stake) || stake < STAKE_MIN || stake > STAKE_MAX) { say(`The stake has to be between ${STAKE_MIN} and ${STAKE_MAX} units.`); return; }
    const rawPrice = String(priceInput.value).trim();
    let price = null;
    if (rawPrice) {
      price = Number(rawPrice.replace(/^\+/, ""));
      if (!Number.isFinite(price)) { say(`That price does not look right. ${PRICE_HELP}`); return; }
    }
    const body = { event_id: ev.event_id, market: sel.market, side: sel.side, stake_units: stake };
    if (sel.line !== null && sel.line !== undefined && Number.isFinite(Number(sel.line))) body.line = Number(sel.line);
    if (price !== null) body.price = price;
    const note = String(noteInput.value).trim();
    if (note) body.note = note;
    busy = true;
    save.setAttribute("disabled", "");
    say("");
    try {
      const bet = await apiPost("/me/bets", body);
      rememberStake(stake);
      done(bet, sel);
      if (onSaved) onSaved(bet);
    } catch (err) {
      say(err && err.status === 401 ? "Your sign-in has expired. Sign in again to log a bet." : sentence(err, "That bet could not be saved. Try again in a minute."));
      busy = false;
      save.removeAttribute("disabled");
    }
  }

  function done(bet, picked) {
    clearNode(panel);
    const what = (bet && bet.selection) || (optionList().find((o) => o.market === picked.market && o.side === picked.side) || {}).label || "your bet";
    const at = bet && isNum(bet.price) ? ` at ${fmtPrice(bet.price)}` : "";
    panel.appendChild(h("p", { class: "mb-done", role: "status", "data-hook": "log-bet-done" }, [
      `Logged: ${what}${at}. `, h("a", { href: MY_BETS_HREF, "data-hook": "log-bet-mybets-link", text: "See your bets" }), "."]));
  }

  paintSides();
  if (pre) {
    const opts = optionList();
    const hit = opts.find((o) => o.side === pre.side) || null;
    if (hit) {
      sel.market = hit.market; sel.side = hit.side; sel.line = hit.line;
      paintSides();
      if (isNum(Number(pre.price)) && pre.price !== null && pre.price !== "") {
        priceInput.value = String(Math.round(Number(pre.price)));
        priceHint.textContent = "The price this hound took. Change it to the price you got.";
      } else {
        fillPrice(hit);
      }
    }
  } else {
    markets.moneyline = null;
    paintSides();
    probe();
  }
  return panel;
}

// ---- My bets (the kennel tab) -----------------------------------------------------------------------

const RESULT_WORDS = { WIN: "Won", LOSS: "Lost", PUSH: "Push", VOID: "Void" };

function whenText(stamp) {
  const t = stamp ? formatStamp("t", stamp) : "";
  return t;
}

function betLine(bet) {
  const price = pricePlain(bet.price);
  return [bet.selection || bet.side || "Your bet", price].filter(Boolean).join(" ");
}

function betRow(bet, { onRemove }) {
  const meta = [`${shortNum(bet.stake_units)} ${bet.stake_units === 1 ? "unit" : "units"}`];
  const when = whenText(bet.start_utc);
  if (when) meta.push(when);
  const settled = bet.status === "settled";
  const li = h("li", { class: "mb-bet", "data-hook": "mybets-bet", "data-id": bet.id, "data-status": bet.status }, [
    h("div", { class: "mb-bet__main" }, [
      h("strong", { class: "mb-bet__pick", "data-hook": "mybets-pick", text: betLine(bet) }),
      bet.in_play ? h("span", { class: "mb-pill", "data-hook": "mybets-inplay", text: "In play" }) : null]),
    h("div", { class: "mb-bet__game", text: bet.game || "" }),
    h("div", { class: "mb-bet__meta", text: meta.join(" · ") }),
    bet.note ? h("div", { class: "mb-bet__note", text: bet.note }) : null]);
  if (settled) {
    const tone = isNum(bet.units) ? (bet.units > 0 ? "up" : bet.units < 0 ? "down" : "flat") : "flat";
    const parts = [h("span", { class: "mb-res", "data-hook": "mybets-result", text: RESULT_WORDS[bet.result] || bet.result || "Settled" }),
      h("span", { class: `mb-units mb-units--${tone}`, "data-hook": "mybets-units", text: unitsText(bet.units) })];
    if (isNum(bet.close_price)) parts.push(h("span", { class: "mb-close", "data-hook": "mybets-close", text: `Closed ${fmtPrice(bet.close_price)}` }));
    if (isNum(bet.clv_pts)) parts.push(h("span", { class: "mb-close", "data-hook": "mybets-vsclose", text: `vs close ${bet.clv_pts > 0 ? "+" : bet.clv_pts < 0 ? "-" : ""}${Math.abs(bet.clv_pts).toFixed(1)} pts` }));
    li.appendChild(h("div", { class: "mb-bet__result" }, parts));
  }
  if (bet.can_void) {
    li.appendChild(h("div", { class: "mb-bet__actions" }, [h("button", { type: "button", class: "btn btn--ghost mb-remove", "data-hook": "mybets-remove",
      "aria-label": `Remove ${betLine(bet)}`, text: "Remove", on: { click: () => onRemove(bet) } })]));
  }
  return li;
}

function section(title, hook, bets, opts, note) {
  if (!bets.length) return null;
  return h("section", { class: "mb-section", "data-hook": hook }, [
    h("h3", { class: "hd-h3", text: `${title} (${bets.length})` }),
    note ? h("p", { class: "hd-fine", text: note }) : null,
    h("ul", { class: "mb-list" }, bets.map((b) => betRow(b, opts)))]);
}

/** The "Log a bet by hand" form: a game that is not on our board. Posts to /me/bets/manual; `onSaved` runs after a good save. */
export function manualBetForm(onSaved) {
  const ids = { sport: uid("mb-sport"), game: uid("mb-game"), side: uid("mb-side"), price: uid("mb-mprice"), stake: uid("mb-mstake"), note: uid("mb-mnote") };
  const sportOptions = Object.keys(SPORT_LABELS).filter((k) => k !== "ufc")
    .map((k) => h("option", { value: k.toUpperCase(), text: SPORT_LABELS[k] }));
  const sport = h("select", { id: ids.sport, class: "mb-input", "data-hook": "manual-sport" }, sportOptions);
  const game = h("input", { id: ids.game, class: "mb-input", type: "text", maxlength: "120", autocomplete: "off", placeholder: "Team A at Team B", "data-hook": "manual-game" });
  const side = h("input", { id: ids.side, class: "mb-input", type: "text", maxlength: "60", autocomplete: "off", placeholder: "Team A -3.5, or Over 8.5", "data-hook": "manual-side" });
  const price = h("input", { id: ids.price, class: "mb-input", type: "text", inputmode: "numeric", autocomplete: "off", placeholder: "-110", "data-hook": "manual-price" });
  const stake = h("input", { id: ids.stake, class: "mb-input", type: "number", inputmode: "decimal", step: "0.25", min: String(STAKE_MIN), max: String(STAKE_MAX),
    value: shortNum(lastStake()), "data-hook": "manual-stake" });
  const note = h("input", { id: ids.note, class: "mb-input", type: "text", maxlength: String(NOTE_MAX), autocomplete: "off", placeholder: "Optional", "data-hook": "manual-note" });
  const status = h("p", { class: "mb-status", role: "status", "aria-live": "polite", "data-hook": "manual-status", hidden: true });
  let busy = false;
  const say = (text, kind) => {
    if (text) { status.textContent = text; status.setAttribute("data-kind", kind || "error"); status.removeAttribute("hidden"); } else { status.textContent = ""; status.setAttribute("hidden", ""); }
  };
  const field = (label, id, input) => h("div", { class: "mb-field" }, [h("label", { class: "mb-label", for: id, text: label }), input]);
  async function submit() {
    if (busy) return;
    const n = Number(String(stake.value).trim());
    if (!Number.isFinite(n) || n < STAKE_MIN || n > STAKE_MAX) { say(`The stake has to be between ${STAKE_MIN} and ${STAKE_MAX} units.`); return; }
    const raw = String(price.value).trim();
    let p = null;
    if (raw) {
      p = Number(raw.replace(/^\+/, ""));
      if (!Number.isFinite(p)) { say(`That price does not look right. ${PRICE_HELP}`); return; }
    }
    const body = { sport: sport.value, game_text: String(game.value).trim(), side_text: String(side.value).trim(), stake_units: n };
    if (p !== null) body.price = p;
    const text = String(note.value).trim();
    if (text) body.note = text;
    busy = true;
    say("");
    try {
      const bet = await apiPost("/me/bets/manual", body);
      rememberStake(n);
      game.value = ""; side.value = ""; price.value = ""; note.value = "";
      say("Saved. We do not grade bets on games we do not carry; it stays in your list.", "ok");
      if (onSaved) onSaved(bet);
    } catch (err) {
      say(err && err.status === 401 ? "Your sign-in has expired. Sign in again to log a bet." : sentence(err, "That bet could not be saved. Try again in a minute."));
    }
    busy = false;
  }
  return h("section", { class: "mb-section mb-manual", "data-hook": "mybets-manual" }, [
    h("h3", { class: "hd-h3", text: "Log a bet by hand" }),
    h("p", { class: "hd-fine", text: "For a game that is not on our board. It stays in your list and is not graded automatically." }),
    h("div", { class: "mb-form" }, [
      field("Sport", ids.sport, sport), field("Game", ids.game, game), field("Your side", ids.side, side),
      h("div", { class: "mb-row" }, [field("Price", ids.price, price), field("Stake (units)", ids.stake, stake)]),
      field("Note", ids.note, note), status,
      h("div", { class: "mb-actions" }, [h("button", { type: "button", class: "btn btn--primary mb-save", "data-hook": "manual-save", text: "Save", on: { click: submit } })])])]);
}

/** Fill the kennel's "My bets" tab. Safe to call again: it redraws from the server. */
export async function mountMyBets(host) {
  if (!host) return;
  clearNode(host);
  if (!getToken()) {
    host.appendChild(signInPrompt("Sign in to see your bets."));
    return;
  }
  host.appendChild(h("p", { class: "hd-fine", role: "status", "data-hook": "mybets-loading", text: "Loading your bets..." }));
  let data;
  try {
    data = await apiGet("/me/bets");
  } catch (err) {
    clearNode(host);
    host.appendChild(err && err.status === 401 ? signInPrompt("Your sign-in has expired.")
      : h("p", { class: "hd-muted", role: "alert", "data-hook": "mybets-error", text: sentence(err, "Your bets could not be loaded just now. Try again in a minute.") }));
    return;
  }
  clearNode(host);
  const bets = (data && Array.isArray(data.bets) ? data.bets : []).filter((b) => b.status !== "removed");
  const rec = (data && data.record) || {};
  const redraw = () => mountMyBets(host);
  const note = h("p", { class: "mb-status", role: "status", "aria-live": "polite", "data-hook": "mybets-status", hidden: true });
  const remove = async (bet) => {
    try {
      await apiDelete(`/me/bets/${encodeURIComponent(bet.id)}`);
      await redraw();
    } catch (err) {
      note.textContent = sentence(err, "That bet could not be removed. Try again in a minute.");
      note.removeAttribute("hidden");
    }
  };
  const opts = { onRemove: remove };
  host.appendChild(h("dl", { class: "kn-stats mb-record", "data-hook": "mybets-recordbox" }, [
    h("div", { class: "kn-stat" }, [h("dt", { text: "Your record" }), h("dd", { "data-hook": "mybets-record", text: recordLine(rec) })]),
    h("div", { class: "kn-stat" }, [h("dt", { text: "Open" }), h("dd", { "data-hook": "mybets-open", text: String(bets.filter((b) => b.status === "open").length) })])]));
  host.appendChild(note);
  const open = bets.filter((b) => b.status === "open");
  const settled = bets.filter((b) => b.status === "settled");
  const unmatched = bets.filter((b) => b.status === "unmatched");
  if (!bets.length) {
    host.appendChild(h("p", { class: "hd-muted", "data-hook": "mybets-empty" }, ["You have not logged a bet yet. Tap Log a bet on a game on the ",
      h("a", { href: "live.html", text: "Live board" }), ", or log one by hand below."]));
  }
  for (const node of [section("Open", "mybets-open-list", open, opts),
    section("Settled", "mybets-settled-list", settled, opts),
    section("Not on our board", "mybets-unmatched-list", unmatched, opts, "These are not graded automatically.")]) {
    if (node) host.appendChild(node);
  }
  host.appendChild(manualBetForm(redraw));
}
