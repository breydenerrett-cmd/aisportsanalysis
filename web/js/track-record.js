/**
 * THE TRACK RECORD (web/record.html, ?id=<hound>): one hound's whole paper record on one page, member hound or house hound.
 * docs/HOUND_LOOP_PLAN.md phase 3. Fed by ONE read, GET /hounds/{id}/record (src/hounds/track_record.py); every number and every
 * sentence about a cut is the server's, this file only draws them.
 *
 *   HEADER      record (W-L-P), units, ROI, closing-line value (left out when the data has none: never zero), the streak, the
 *               last ten, and "only N settled bets" when the sample is small.
 *   NEXT STEPS  Backtest a tweak (the owner's Rules tab, or a copy in the builder for anyone else), Copy this hound (the builder's
 *               ?from= copy), Ask why it lost (the hound page's Ask tab). Each goes to a real, existing page.
 *   CURVE       the paper bankroll at the viewer's own sizing from the bankroll block's events, else paper units by day.
 *   BREAKDOWNS  sport, market, price band, favourite or underdog, home or away, each with the server's one-line read; a thin cut
 *               says "only 4 bets" and draws no conclusion.
 *   CALENDAR    one grid per month, a day is a win day, a loss day or level.
 *   OPEN        tickets still waiting for a result, APART from the record and never counted in it.
 *   TICKETS     the latest settled tickets, filterable by sport, result and market, each with its "why" when one was stored.
 *   COMPARE     against the house pack and the leaderboard average over the same period.
 *
 * Times come from local-time.js (the viewer's zone). A hindsight backtest never appears here: the server only sends forward bets.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, isNum, fmtPrice, houndHref, describeError, isWarming, retryWhileWarming, stopWarmingRetry, WARMING_FALLBACK_TEXT,
} from "./hounds-core.js";
import { get } from "./dog-common.js";
import { renderSparkline } from "./hounds-chart.js";
import { priced, getSizing } from "./unitsize.js";
import { formatStamp } from "./local-time.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
const WIN_COLOR = "#5BE39A";
const LOSS_COLOR = "#FF8A96";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MON_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const CALENDAR_MONTHS = 3;
export const MARKET_WORDS = { h2h: "Moneyline", moneyline: "Moneyline", spreads: "Spread", spread: "Spread", totals: "Total", total: "Total" };

const state = { id: "", season: "", data: null, owner: false, filters: { sport: "", result: "", market: "" } };

// ---- pure helpers (the tests run these under node) ------------------------------------------------------------

export const unitsText = (u) => (isNum(u) ? `${u > 0 ? "+" : ""}${u.toFixed(Math.abs(u) >= 100 ? 0 : 1)}u` : "n/a");
export const betsWord = (n) => (n === 1 ? "1 bet" : `${n} bets`);

export function marketWord(key) {
  const k = String(key || "");
  if (MARKET_WORDS[k]) return MARKET_WORDS[k];
  if (!k) return "Other";
  const words = k.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The tickets a filter keeps. An empty choice keeps everything. */
export function filterTickets(tickets, f) {
  return (tickets || []).filter((t) => (!f.sport || String(t.sport || "").toUpperCase() === f.sport)
    && (!f.result || t.result === f.result)
    && (!f.market || marketWord(t.market) === f.market));
}

/** The cumulative bankroll values (dollars, starting at the account's start) at the viewer's sizing, or paper units by day. */
export function curveOf(data, sizing = getSizing()) {
  const b = data && data.bankroll;
  const events = b && Array.isArray(b.events) ? b.events : null;
  if (events && events.length) {
    const usd = priced(events, sizing);
    const values = [0];
    let run = 0;
    events.forEach((e, i) => {
      if (e[4] === "w" || e[4] === "l" || e[4] === "p") { run += usd[i][0]; values.push(Math.round(run * 100) / 100); }
    });
    if (values.length >= 3) return { values, unit: "usd", start: isNum(sizing.start_usd) ? sizing.start_usd : (isNum(b.start) ? b.start : 1000) };
  }
  const days = (data && Array.isArray(data.curve)) ? data.curve : [];
  const values = [0, ...days.map((d) => d.units)];
  return values.length >= 3 ? { values, unit: "units", start: 0 } : null;
}

const pad2 = (n) => String(n).padStart(2, "0");

/** One grid per month, newest month first, at most `limit`. Each cell is null (outside the month) or {day, info}. */
export function monthGrids(days, limit = CALENDAR_MONTHS) {
  const byDate = new Map((days || []).map((d) => [d.date, d]));
  const months = [...new Set((days || []).map((d) => String(d.date).slice(0, 7)))].sort().reverse().slice(0, limit);
  return months.map((ym) => {
    const [y, m] = ym.split("-").map(Number);
    const first = new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
    const count = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const cells = Array.from({ length: first }, () => null);
    for (let d = 1; d <= count; d += 1) cells.push({ day: d, date: `${y}-${pad2(m)}-${pad2(d)}`, info: byDate.get(`${y}-${pad2(m)}-${pad2(d)}`) || null });
    return { ym, title: `${MONTHS[m - 1]} ${y}`, cells };
  });
}

/** The three next-step links. `owner` sends the backtest to the owner's own Rules tab, everyone else to a copy in the builder. */
export function nextSteps(id, owner) {
  const e = encodeURIComponent(id);
  return [
    { hook: "next-backtest", text: "Backtest a tweak", primary: true,
      href: owner ? `kennel.html?dog=${e}&tab=rules` : `build-a-hound.html?from=${e}`,
      hint: owner ? "Change the rules, then run a backtest." : "Opens a copy of its rules, where you can change them and run a backtest." },
    { hook: "next-copy", text: "Copy this hound", primary: false, href: `build-a-hound.html?from=${e}`, hint: "Make a hound of your own from its rules." },
    { hook: "next-ask", text: "Ask why it lost", primary: false, href: `${houndHref(id)}&tab=ask`, hint: "Ask the hound itself about its losses." },
  ];
}

// ---- drawing ---------------------------------------------------------------------------------------------------

function stat(label, value, extra = {}, sub = "") {
  return h("div", Object.assign({ class: "rc-stat" }, extra), [
    h("dt", { text: label }), h("dd", { text: value }), sub ? h("dd", { class: "rc-stat__sub", text: sub }) : null]);
}

function setState(kind, text, retry) {
  const box = q("record-state");
  clearNode(box);
  if (!text) { box.hidden = true; return; }
  box.hidden = false;
  box.setAttribute("data-kind", kind);
  box.appendChild(h("p", { text }));
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost", text: "Try again", on: { click: retry } }));
}

function renderHead(data) {
  const hd = data.hound || {};
  document.title = `${hd.name || "Hound"} track record — LINEHOUND`;
  q("record-title").textContent = hd.name ? `${hd.name}: track record` : "Track record";
  const back = q("record-back");
  back.setAttribute("href", houndHref(hd.id || state.id));
  back.textContent = `← Back to ${hd.name || "the hound"}`;
  const sports = Array.isArray(hd.sports) && hd.sports.length ? hd.sports.join(", ").toUpperCase() : "";
  const season = data.season && data.season.label ? data.season.label : "All-time";
  q("record-sub").textContent = [hd.is_house ? "House hound" : "Member hound", sports, season].filter(Boolean).join(" · ");
  const bar = q("record-season");
  clearNode(bar);
  const avail = data.season && Array.isArray(data.season.available) ? data.season.available : [];
  bar.hidden = avail.length < 2;
  for (const o of avail) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-season": o.id,
      "aria-pressed": data.season && data.season.id === o.id ? "true" : "false", text: o.label,
      on: { click: () => load(o.id) } }));
  }
}

function renderHeader(data) {
  const hd = data.header || {};
  const stats = q("record-stats");
  clearNode(stats);
  stats.appendChild(stat("Record", hd.record_text || "0-0", { "data-hook": "stat-record" }, `${betsWord(hd.settled || 0)} settled`));
  stats.appendChild(stat("Units", unitsText(hd.units), { "data-hook": "stat-units" },
    hd.units_basis === "average_price" ? "at the average price" : "at the recorded price"));
  stats.appendChild(stat("ROI", isNum(hd.roi_pct) ? `${hd.roi_pct > 0 ? "+" : ""}${hd.roi_pct.toFixed(1)}%` : "n/a", { "data-hook": "stat-roi" },
    "per flat unit staked"));
  if (hd.clv && isNum(hd.clv.mean_pts)) {
    stats.appendChild(stat("Closing-line value", `${hd.clv.mean_pts > 0 ? "+" : ""}${hd.clv.mean_pts.toFixed(2)} pts`, { "data-hook": "stat-clv" },
      `average over ${betsWord(hd.clv.n)} we could check`));
  }
  if (hd.streak && hd.streak.length) {
    stats.appendChild(stat("Streak", `${hd.streak.kind}${hd.streak.length}`, { "data-hook": "stat-streak" },
      `${hd.streak.length} ${hd.streak.kind === "W" ? "won" : "lost"} in a row`));
  }
  const sample = q("record-sample");
  sample.hidden = !hd.sample_note;
  sample.textContent = hd.sample_note || "";
  const last = q("record-last10");
  clearNode(last);
  const l10 = Array.isArray(hd.last10) ? hd.last10 : [];
  last.hidden = !l10.length;
  if (l10.length) {
    last.appendChild(h("span", { class: "rc-last10__label", text: `Last ${l10.length}` }));
    for (const r of l10) last.appendChild(h("span", { class: `rc-pip rc-pip--${r === "W" ? "win" : r === "L" ? "loss" : "push"}`, text: r }));
  }
}

function renderNext(data) {
  const box = clearNode(q("record-next"));
  const id = (data.hound && data.hound.id) || state.id;
  for (const step of nextSteps(id, state.owner)) {
    box.appendChild(h("a", { class: step.primary ? "btn btn--primary rc-next__btn" : "btn btn--ghost rc-next__btn", href: step.href,
      "data-hook": step.hook, title: step.hint, text: step.text }));
  }
  box.appendChild(h("p", { class: "rc-note rc-next__hint", text: state.owner ? "Backtests are hindsight and never count toward this record." : "A copy is a hound of your own; this record stays with this hound." }));
}

function renderCurve(data) {
  const box = clearNode(q("record-curve"));
  const curve = curveOf(data);
  if (!curve) {
    const n = (data.header && data.header.settled) || 0;
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "curve-empty", text: n
      ? `Only ${betsWord(n)} settled, too few to draw a curve. It appears once a few more settle.`
      : "No settled bets yet, so there is no curve. It starts with the first result." }));
    return;
  }
  const last = curve.values[curve.values.length - 1];
  const nowText = curve.unit === "usd" ? `${last >= 0 ? "+" : "-"}$${Math.abs(last).toFixed(0)}` : unitsText(last);
  box.appendChild(h("figure", { class: "rc-curve", "data-hook": "curve-figure" }, [
    renderSparkline({ values: curve.values, color: last >= 0 ? WIN_COLOR : LOSS_COLOR, width: 640, height: 170,
      label: `Paper ${curve.unit === "usd" ? "bankroll" : "units"} after each ${curve.unit === "usd" ? "settled bet" : "day"}, now ${nowText} from the start` }),
    h("figcaption", { class: "rc-note", text: curve.unit === "usd"
      ? `The paper account after each of its ${curve.values.length - 1} settled bets, now ${nowText} from the start.`
      : `Paper units after each of its ${curve.values.length - 1} settled days, now ${nowText}.` })]));
}

function cutRow(r) {
  const max = 100;
  const pct = isNum(r.win_pct) ? Math.max(0, Math.min(max, r.win_pct)) : null;
  return h("li", { class: `rc-cut rc-cut--${r.thin ? "thin" : r.units > 0 ? "up" : r.units < 0 ? "down" : "flat"}`, "data-hook": "cut-row" }, [
    h("span", { class: "rc-cut__label", text: r.label }),
    h("span", { class: "rc-cut__rec", text: `${r.wins}-${r.losses}${r.pushes ? `-${r.pushes}` : ""}` }),
    h("span", { class: "rc-cut__units", text: unitsText(r.units) }),
    h("span", { class: "rc-cut__n", text: r.thin ? `only ${betsWord(r.n)}` : betsWord(r.n) }),
    pct === null ? null : h("span", { class: "rc-cut__bar", "aria-hidden": "true" }, [h("i", { style: `width:${pct}%` })]),
  ]);
}

function renderBreakdowns(data) {
  const box = clearNode(q("record-breakdowns"));
  q("record-cuts-note").textContent = data.diagnosis_note || "";
  for (const g of data.breakdowns || []) {
    box.appendChild(h("article", { class: "rc-cutcard", "data-hook": `cut-${g.group}` }, [
      h("h3", { text: g.title }),
      g.rows.length ? h("ul", { class: "rc-cutlist" }, g.rows.map(cutRow)) : null,
      h("p", { class: "rc-cutline", "data-hook": "cut-line", text: g.line })]));
  }
}

function renderCalendar(data) {
  const box = clearNode(q("record-calendar"));
  const grids = monthGrids(data.calendar);
  if (!grids.length) {
    box.appendChild(h("p", { class: "hd-muted", text: "No settled days yet. Each day a bet settles is drawn here as a win day or a loss day." }));
    return;
  }
  box.appendChild(h("p", { class: "rc-legend" }, [
    h("span", { class: "rc-key rc-key--win", text: "Win day" }), h("span", { class: "rc-key rc-key--loss", text: "Loss day" }),
    h("span", { class: "rc-key rc-key--flat", text: "Level" })]));
  const wrap = h("div", { class: "rc-months" });
  for (const g of grids) {
    const grid = h("div", { class: "rc-grid", role: "grid", "aria-label": g.title });
    for (const w of ["S", "M", "T", "W", "T", "F", "S"]) grid.appendChild(h("span", { class: "rc-dow", "aria-hidden": "true", text: w }));
    for (const c of g.cells) {
      if (!c) { grid.appendChild(h("span", { class: "rc-day rc-day--blank", "aria-hidden": "true" })); continue; }
      const info = c.info;
      const label = info
        ? `${MON_SHORT[Number(c.date.slice(5, 7)) - 1]} ${c.day}: ${info.wins}-${info.losses}${info.pushes ? `-${info.pushes}` : ""}, ${unitsText(info.units)}`
        : `${MON_SHORT[Number(c.date.slice(5, 7)) - 1]} ${c.day}: no settled bets`;
      grid.appendChild(h("span", { class: `rc-day rc-day--${info ? info.result : "none"}`, role: "gridcell", title: label, "aria-label": label,
        "data-day": c.date, text: String(c.day) }));
    }
    wrap.appendChild(h("section", { class: "rc-month", "data-hook": "cal-month" }, [h("h3", { text: g.title }), grid]));
  }
  box.appendChild(wrap);
  box.appendChild(h("p", { class: "rc-note", text: "Days are the games' slate days (US Eastern). A day counts as a win day when its settled bets are above zero units." }));
}

const RESULT_WORD = { win: "Won", loss: "Lost", push: "Push" };

function ticketItem(t, { open = false } = {}) {
  const cls = open ? "open" : t.result;
  const price = isNum(t.price_average) ? t.price_average : t.price;
  const when = open
    ? (t.start_utc ? `Starts ${formatStamp("w", t.start_utc)}` : `Slate day ${t.date}`)
    : (t.recorded_utc ? `Recorded ${formatStamp("d", t.recorded_utc)}` : `Slate day ${t.date}`);
  return h("li", { class: `rc-ticket rc-ticket--${cls}`, "data-hook": open ? "open-ticket" : "ticket", "data-result": t.result || "open" }, [
    h("span", { class: `rc-chip rc-chip--${cls}`, text: open ? (t.status === "UNGRADED" ? "Waiting on a grade" : "Open") : (RESULT_WORD[t.result] || "") }),
    h("div", { class: "rc-ticket__main" }, [
      h("p", { class: "rc-ticket__pick", text: `${t.selection || "Pick"}${isNum(price) ? ` ${fmtPrice(price)}` : ""}` }),
      h("p", { class: "rc-ticket__game", text: [t.game, marketWord(t.market)].filter(Boolean).join(" · ") }),
      h("p", { class: "rc-ticket__when", text: when }),
      t.beyond_cap ? h("p", { class: "rc-ticket__tag", text: "-200 or worse (old rule)" }) : null,
      !open && t.reason ? h("p", { class: "rc-ticket__why", "data-hook": "ticket-why" }, [h("strong", { text: "Why: " }), t.reason]) : null]),
    open ? null : h("span", { class: "rc-ticket__units", text: unitsText(t.units) }),
  ]);
}

function renderOpen(data) {
  const sec = q("record-open-section");
  const open = Array.isArray(data.open) ? data.open : [];
  const waiting = Array.isArray(data.waiting) ? data.waiting : [];
  sec.hidden = !open.length && !waiting.length;
  const o = clearNode(q("record-open"));
  const w = clearNode(q("record-waiting"));
  if (open.length) {
    q("record-open-section").querySelector("h2").textContent = data.open_total === 1 ? "Open ticket" : `Open tickets (${data.open_total})`;
    o.appendChild(h("ul", { class: "rc-tickets", "data-hook": "open-list" }, open.map((t) => ticketItem(t, { open: true }))));
  } else {
    q("record-open-section").querySelector("h2").textContent = "Waiting on a grade";
  }
  if (waiting.length) {
    w.appendChild(h("h3", { class: "rc-sub3", text: `Waiting on a grade (${data.waiting_total})` }));
    w.appendChild(h("p", { class: "rc-note", text: "These games started more than 36 hours ago and have no result yet. They are not counted." }));
    w.appendChild(h("ul", { class: "rc-tickets", "data-hook": "waiting-list" }, waiting.map((t) => ticketItem(t, { open: true }))));
  }
}

function fillSelect(sel, values, current) {
  const keep = sel.querySelector("option");
  clearNode(sel);
  sel.appendChild(keep);
  for (const v of values) sel.appendChild(h("option", { value: v, text: v }));
  sel.value = values.includes(current) ? current : "";
}

function renderTickets(data) {
  const all = Array.isArray(data.tickets) ? data.tickets : [];
  const sports = [...new Set(all.map((t) => String(t.sport || "").toUpperCase()).filter(Boolean))].sort();
  const markets = [...new Set(all.map((t) => marketWord(t.market)))].sort();
  fillSelect(q("filter-sport"), sports, state.filters.sport);
  fillSelect(q("filter-market"), markets, state.filters.market);
  const box = clearNode(q("record-tickets"));
  const count = q("record-ticket-count");
  if (!all.length) {
    count.textContent = "";
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "tickets-empty", text: "No settled tickets yet, so there is no record to read. The open tickets above settle first." }));
    q("record-filters").hidden = true;
    return;
  }
  q("record-filters").hidden = false;
  const rows = filterTickets(all, state.filters);
  const total = data.tickets_total || all.length;
  count.textContent = `Showing ${rows.length} of ${all.length} settled tickets${total > all.length ? `, the latest ${all.length} of ${total}` : ""}.`;
  if (!rows.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "tickets-none", text: "No settled ticket matches these filters. Clear a filter to see more." }));
    return;
  }
  box.appendChild(h("ul", { class: "rc-tickets", "data-hook": "ticket-list" }, rows.map((t) => ticketItem(t))));
}

function cmpRow(label, g, hook) {
  const line = (v, suffix = "") => (isNum(v) ? `${v > 0 && suffix === "%" ? "+" : ""}${v.toFixed(1)}${suffix}` : "n/a");
  return h("tr", { "data-hook": hook }, [
    h("th", { scope: "row", text: label }),
    h("td", { text: g ? line(g.roi_pct, "%") : "n/a" }),
    h("td", { text: g ? line(g.win_pct, "%") : "n/a" }),
    h("td", { text: g && isNum(g.clv) ? `${g.clv > 0 ? "+" : ""}${g.clv.toFixed(2)} pts` : "n/a" }),
    h("td", { text: g ? (g.hounds ? `${g.hounds} hounds, ${betsWord(g.bets)}` : betsWord(g.n)) : "" })]);
}

function renderCompare(data) {
  const box = clearNode(q("record-compare"));
  const c = data.compare;
  if (!c) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "compare-none", text: "No other hound has settled a bet in this period, so there is nothing to compare against yet." }));
    return;
  }
  const mine = c.mine ? { roi_pct: c.mine.roi_pct, win_pct: c.mine.win_pct, clv: c.mine.clv, n: c.mine.n } : null;
  box.appendChild(h("div", { class: "rc-tablewrap" }, [h("table", { class: "rc-table", "data-hook": "compare-table" }, [
    h("caption", { class: "hd-sr-only", text: `This hound against the pack, ${c.period}` }),
    h("thead", {}, [h("tr", {}, ["", "ROI", "Win rate", "Closing-line value", "Sample"].map((x) => h("th", { scope: "col", text: x })))]),
    h("tbody", {}, [cmpRow("This hound", mine, "cmp-mine"), cmpRow("House pack average", c.house_pack, "cmp-pack"), cmpRow("Leaderboard average", c.leaderboard, "cmp-board")])])]));
  const gap = c.mine && c.house_pack && isNum(c.mine.roi_pct) && isNum(c.house_pack.roi_pct) ? c.mine.roi_pct - c.house_pack.roi_pct : null;
  const thin = !c.mine || c.mine.n < 20;
  const parts = [`Over the same period (${c.period}).`];
  if (gap !== null) parts.push(`This hound's ROI is ${Math.abs(gap).toFixed(1)} points ${gap >= 0 ? "above" : "below"} the house pack average.`);
  if (thin) parts.push(`${c.mine ? `Only ${betsWord(c.mine.n)}` : "No bets"} so far, so this gap says little.`);
  if (c.note) parts.push(c.note);
  box.appendChild(h("p", { class: "rc-note", "data-hook": "compare-line", text: parts.join(" ") }));
}

function render(data) {
  state.data = data;
  renderHead(data);
  renderHeader(data);
  renderNext(data);
  renderCurve(data);
  renderOpen(data);
  renderBreakdowns(data);
  renderCalendar(data);
  renderTickets(data);
  renderCompare(data);
  q("record-fine").textContent = `${data.hindsight_note || ""} ${data.units_note || ""}`.trim();
  q("record-body").hidden = false;
  setState("", "");
}

async function load(season) {
  state.season = season || state.season || "";
  setState("loading", "Loading the record...");
  q("record-body").hidden = true;
  const query = state.season ? `?season=${encodeURIComponent(state.season)}` : "";
  let data;
  try {
    data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/record${query}`);
  } catch (err) {
    if (err && err.status === 404) setState("missing", "There is no hound with this id. It may have been removed, or the link is wrong.");
    else setState("down", describeError(err, "this record").text, () => load(state.season));
    return;
  }
  if (isWarming(data)) {
    setState("warming", data.message || WARMING_FALLBACK_TEXT);
    retryWhileWarming("record", () => { stopWarmingRetry("record"); load(state.season); }, data);
    return;
  }
  stopWarmingRetry("record");
  render(data);
  if (state.season) {
    try { window.history.replaceState(null, "", `${window.location.pathname}?id=${encodeURIComponent(state.id)}&season=${encodeURIComponent(state.season)}`); } catch (err) { /* a file page or a fake window */ }
  }
  ownerCheck();
}

/** Is the viewer this hound's owner? Only changes where "Backtest a tweak" goes; any failure leaves the copy route. */
async function ownerCheck() {
  try {
    const kit = await get(`/hounds/${encodeURIComponent(state.id)}/kit`);
    const owner = !!(kit && kit.is_owner);
    if (owner !== state.owner) { state.owner = owner; if (state.data) renderNext(state.data); }
  } catch (err) { /* signed out, or no kit route: the visitor's links stand */ }
}

export async function boot() {
  const params = new URLSearchParams(window.location.search || "");
  state.id = params.get("id") || "";
  state.season = params.get("season") || "";
  for (const [key, hook] of [["sport", "filter-sport"], ["result", "filter-result"], ["market", "filter-market"]]) {
    const sel = q(hook);
    if (sel) sel.addEventListener("change", () => { state.filters[key] = sel.value; if (state.data) renderTickets(state.data); });
    if (sel) sel.addEventListener("input", () => { state.filters[key] = sel.value; if (state.data) renderTickets(state.data); });
  }
  if (!state.id) {
    setState("missing", "No hound was chosen. Pick one from the leaderboard to see its record.");
    return;
  }
  await load(state.season);
}

if (typeof document !== "undefined" && q("record-app")) boot();
