/**
 * EXAMPLE ACCOUNTS (the section titled "If you had followed every pick" on
 * the public record page, #/record-card; GET /card/accounts).
 *
 * WHAT IT SHOWS. What a bankroll would be today if it had bet every pick we
 * published since Sept 22, at the stake each account names ($100 on every
 * pick, 1% of the balance on every pick, and so on), day by day, for each
 * sport and for all sports. It is arithmetic over the published record, not a
 * real account and not a forecast, and the three notes the server sends say so.
 *
 * WHAT IT WILL NOT DO. It never prints a number the server did not send and
 * never works one out for itself: every balance, every day's result and every
 * count comes from the payload. The server checks the totals against the
 * published record before it answers; when they do not match it answers
 * `available: false` and this page shows ONE plain sentence instead of any
 * balance. A loss is printed with a minus sign and a plain "Down" in the
 * headline, in the same size and weight as a gain. No percentage return is
 * printed for a view with fewer graded picks than the payload's floor: it
 * prints how few have been graded instead.
 *
 * NO CHART LIBRARY. The balance line is a small inline SVG (viewBox 320 by
 * 120, scaled to the width of its box), so it fits a 390px phone with no
 * sideways scroll; the table under it is five short columns for the same
 * reason.
 */

import { apiGet } from "./api.js";
import { el, clear } from "./dom.js";

export const SECTION_TITLE = "If you had followed every pick";
export const UNAVAILABLE_SENTENCE =
  "Example account balances are not available right now, so none are shown.";
export const MIN_GRADED_FOR_PERCENT = 30;
export const SPORT_KEYS = ["mlb", "nfl", "ufc", "all"];
export const SPORT_LABEL = { mlb: "MLB", nfl: "NFL", ufc: "UFC", all: "All sports" };
// The same three sentences the server sends in `notes`; kept here only so the
// page still says them if a payload ever arrives without. A test pins these to
// src/appstate/example_accounts.NOTES so the two cannot drift apart.
export const FALLBACK_NOTES = [
  "This is a hypothetical account, not a real one. It puts the same stake on every pick at the price we published.",
  "A real account would differ: prices move, sportsbooks limit bets, and nobody bets every pick.",
  "Past results do not predict future results. This is analysis, not advice.",
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"];

/* ---------------------------------------------------------------------
 * Pure formatting. Dollars are rounded to cents HERE, at display, from the
 * full-precision figure the server carries.
 * ------------------------------------------------------------------- */

function cents(n) {
  // +1e-6 keeps an exact half-cent (186.575 stored as 186.57499999...) rounding
  // up the way the arithmetic behind it does.
  return Math.round(Math.abs(n) * 100 + 1e-6);
}

function groupThousands(whole) {
  return String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** "$9,295.12"; a negative amount is "-$12.30". `whole: true` drops ".00" from
 * a round figure ("$10,000"), which is how a starting balance is said. */
export function money(n, { whole = false } = {}) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "n/a";
  const c = cents(n);
  const text = whole && c % 100 === 0
    ? `$${groupThousands(c / 100)}`
    : `$${groupThousands(Math.floor(c / 100))}.${String(c % 100).padStart(2, "0")}`;
  return n < 0 && c !== 0 ? `-${text}` : text;
}

/** "+$19.27", "-$354.43", "$0.00": the sign is always printed, never implied. */
export function signedMoney(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "n/a";
  const c = cents(n);
  if (c === 0) return "$0.00";
  return `${n > 0 ? "+" : "-"}$${groupThousands(Math.floor(c / 100))}.${String(c % 100).padStart(2, "0")}`;
}

/** "Sept 22" from a bare YYYY-MM-DD, with no timezone in the way. */
export function dateLabel(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
  if (!m) return iso ? String(iso) : "";
  return `${MONTHS[Number(m[2]) - 1] || m[2]} ${Number(m[3])}`;
}

export function headlineText(series, startDate) {
  return `Started with ${money(series.start_balance, { whole: true })} on ${dateLabel(startDate)}. `
    + `Now ${money(series.final_balance)}.`;
}

/** The headline's plain second sentence: how far from the start, in dollars,
 * with the direction in words so a loss reads as a loss. */
export function changeText(series) {
  const diff = (Math.round(series.final_balance * 100) - Math.round(series.start_balance * 100)) / 100;
  if (diff < 0) return `Down ${money(-diff)} since the start.`;
  if (diff > 0) return `Up ${money(diff)} since the start.`;
  return "No change since the start.";
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

/** "40 picks over 9 days: 16 won, 19 lost, 5 void." Pushes shown when there are any. */
export function countsText(series) {
  if (!series.picks) return "No pick has been graded in this view yet.";
  const parts = [`${series.wins} won`, `${series.losses} lost`];
  if (series.pushes) parts.push(`${series.pushes} ${series.pushes === 1 ? "push" : "pushes"}`);
  if (series.voids) parts.push(`${series.voids} void`);
  return `${plural(series.picks, "pick", "picks")} over ${plural(series.days, "day", "days")}: ${parts.join(", ")}.`;
}

/** A percentage return, only from a big enough sample. null otherwise. */
export function percentText(series, floor = MIN_GRADED_FOR_PERCENT) {
  if (!series || !(series.graded >= floor)) return null;
  const pct = series.return_pct;
  if (typeof pct !== "number" || !Number.isFinite(pct)) return null;
  return `Return on the starting balance: ${pct > 0 ? "+" : ""}${pct.toFixed(2)}%.`;
}

/** The existing small-sample sentence's style (web/js/card.js recordLine):
 * name how few have been graded, and say the count, not a percentage, is the
 * record so far. null when the sample is big enough, or nothing graded. */
export function smallSampleText(viewKey, graded, floor = MIN_GRADED_FOR_PERCENT) {
  if (!(graded > 0) || graded >= floor) return null;
  const subject = viewKey === "all"
    ? plural(graded, "pick", "picks")
    : `${graded} ${SPORT_LABEL[viewKey] || viewKey} pick${graded === 1 ? "" : "s"}`;
  return `Only ${subject} ${graded === 1 ? "has" : "have"} been graded${viewKey === "all" ? " across all sports" : ""}. `
    + "That is too few to show a return as a percentage, so read the dollars and the count until there are more.";
}

/** The lowest end-of-day balance, or a plain statement that it never fell
 * below the start. */
export function lowestText(series) {
  if (!(series.lowest_balance < series.start_balance)) {
    return "The balance never fell below the starting balance at the end of a day.";
  }
  return `Lowest balance at the end of a day: ${money(series.lowest_balance)} on ${dateLabel(series.lowest_date)}.`;
}

/** The picks published and still waiting on their games, in the view being
 * shown: one sport's own, or all of them for All sports. */
export function pendingText(pending, viewKey = "all") {
  const list = (Array.isArray(pending) ? pending : [])
    .filter((p) => p && p.picks > 0 && (viewKey === "all" || p.sport === viewKey));
  if (!list.length) return null;
  const bits = list.map((p) => `${p.picks} ${SPORT_LABEL[p.sport] || p.sport} pick${p.picks === 1 ? "" : "s"}`);
  return `Published and waiting on their games, so in no balance yet: ${bits.join(", ")}.`;
}

/** Pushes and voids, spelled out only when they are not zero ("" when none). */
export function dayExtraText(day) {
  const extra = [];
  if (day.pushes) extra.push(`${day.pushes} ${day.pushes === 1 ? "push" : "pushes"}`);
  if (day.voids) extra.push(`${day.voids} void`);
  return extra.join(", ");
}

/** W-L, with pushes and voids after it when there are any. */
export function dayRecordText(day) {
  const extra = dayExtraText(day);
  return `${day.wins}-${day.losses}${extra ? `, ${extra}` : ""}`;
}

/* ---------------------------------------------------------------------
 * The balance line
 * ------------------------------------------------------------------- */

export const CHART = { width: 320, height: 120, left: 8, right: 8, top: 12, bottom: 20 };

/** The line's points: the start balance, then the balance after each day.
 * Pure, so it can be tested without a DOM. Even spacing, one step per day
 * that settled picks; a flat series sits on the middle line. */
export function chartPoints(series) {
  const balances = [series.start_balance, ...series.daily.map((d) => d.balance)];
  const lo = Math.min(...balances);
  const hi = Math.max(...balances);
  const innerW = CHART.width - CHART.left - CHART.right;
  const innerH = CHART.height - CHART.top - CHART.bottom;
  return balances.map((balance, i) => ({
    x: balances.length === 1 ? CHART.left : CHART.left + (i * innerW) / (balances.length - 1),
    y: hi === lo ? CHART.top + innerH / 2 : CHART.top + ((hi - balance) / (hi - lo)) * innerH,
    balance,
  }));
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svgNode(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else node.setAttribute(key, String(value));
  }
  return node;
}

export function balanceChart(series, startDate) {
  if (!series.daily.length || typeof document.createElementNS !== "function") return null;
  const points = chartPoints(series);
  const svg = svgNode("svg", {
    viewBox: `0 0 ${CHART.width} ${CHART.height}`, class: "acct-chart", role: "img",
    "data-hook": "example-accounts-chart", preserveAspectRatio: "xMidYMid meet",
    "aria-label": `Balance after each day, from ${money(series.start_balance, { whole: true })} `
      + `to ${money(series.final_balance)}.`,
  });
  const start = points[0];
  svg.appendChild(svgNode("line", {
    class: "acct-chart__start", x1: CHART.left, x2: CHART.width - CHART.right, y1: start.y, y2: start.y,
  }));
  svg.appendChild(svgNode("polyline", {
    class: "acct-chart__line", points: points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "),
  }));
  const last = points[points.length - 1];
  svg.appendChild(svgNode("circle", { class: "acct-chart__end", cx: last.x.toFixed(1), cy: last.y.toFixed(1), r: 3 }));
  svg.appendChild(svgNode("text", {
    class: "acct-chart__label", x: CHART.left, y: CHART.height - 5, text: dateLabel(startDate),
  }));
  svg.appendChild(svgNode("text", {
    class: "acct-chart__label", x: CHART.width - CHART.right, y: CHART.height - 5, "text-anchor": "end",
    text: dateLabel(series.daily[series.daily.length - 1].date),
  }));
  return svg;
}

/* ---------------------------------------------------------------------
 * The day table
 * ------------------------------------------------------------------- */

function dayRow(day) {
  const tr = el("tr", { "data-hook": "example-accounts-row", "data-date": day.date,
    "data-postseason": day.postseason ? "true" : "false" });
  const dateCell = el("td", { class: "acct-table__date" });
  const dateBox = el("div", { class: "acct-table__datebox" });
  dateBox.appendChild(el("span", { text: dateLabel(day.date) }));
  if (day.postseason) {
    dateBox.appendChild(el("span", { class: "acct-tag", "data-hook": "example-accounts-postseason-tag",
      text: "Postseason" }));
  }
  if (day.partial) {
    dateBox.appendChild(el("span", { class: "acct-tag", "data-hook": "example-accounts-partial-tag",
      text: "Some picks still waiting" }));
  }
  dateCell.appendChild(dateBox);
  tr.appendChild(dateCell);
  tr.appendChild(el("td", { text: String(day.picks) }));
  const wl = el("td", { class: "acct-table__wl" });
  wl.appendChild(el("span", { class: "acct-table__wlmain", text: `${day.wins}-${day.losses}` }));
  // Pushes and voids, one short line each, only when they are not zero.
  for (const part of dayExtraText(day).split(", ").filter(Boolean)) {
    wl.appendChild(el("span", { class: "acct-table__wlextra", text: part }));
  }
  tr.appendChild(wl);
  const tone = day.result > 0 ? "acct-pos" : day.result < 0 ? "acct-neg" : "";
  tr.appendChild(el("td", { class: `acct-table__day ${tone}`.trim(), "data-hook": "example-accounts-day-result",
    text: signedMoney(day.result) }));
  tr.appendChild(el("td", { class: "acct-table__balance", text: money(day.balance) }));
  return tr;
}

function dayTable(series) {
  const wrap = el("div", { class: "acct-table-wrap", "data-hook": "example-accounts-table" });
  const table = el("table", { class: "acct-table" });
  const thead = el("thead");
  const head = el("tr");
  for (const label of ["DATE", "PICKS", "W-L", "DAY", "BALANCE"]) {
    head.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(head);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const day of series.daily) tbody.appendChild(dayRow(day));
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

/* ---------------------------------------------------------------------
 * The section
 * ------------------------------------------------------------------- */

function heading() {
  return el("h2", { class: "acct__title", "data-hook": "example-accounts-title", text: SECTION_TITLE });
}

/** The one-sentence state: nothing but the title and the sentence. */
export function unavailableSection() {
  const wrap = el("section", { class: "acct panel chamfer", "data-hook": "example-accounts",
    "data-state": "unavailable" });
  wrap.appendChild(heading());
  wrap.appendChild(el("p", { class: "acct__sentence", "data-hook": "example-accounts-unavailable",
    text: UNAVAILABLE_SENTENCE }));
  return wrap;
}

function usable(payload) {
  return !!payload && payload.available === true && Array.isArray(payload.accounts)
    && payload.accounts.length > 0 && typeof payload.start_date === "string";
}

function seriesOf(account, key) {
  const series = account && account.series && account.series[key];
  return series && Array.isArray(series.daily) ? series : null;
}

/** The whole section for a payload. `selection` = {account, sport} names what
 * is showing first; clicking a button redraws the part under the buttons. */
export function exampleAccountsSection(payload, selection = {}) {
  if (!usable(payload)) return unavailableSection();
  const accounts = payload.accounts;
  const sports = SPORT_KEYS.filter((key) => accounts.every((a) => seriesOf(a, key)));
  if (!sports.length) return unavailableSection();

  const state = {
    account: accounts.some((a) => a.id === selection.account) ? selection.account : accounts[0].id,
    sport: sports.includes(selection.sport) ? selection.sport : (sports.includes("all") ? "all" : sports[0]),
  };
  const section = el("section", { class: "acct panel chamfer", "data-hook": "example-accounts",
    "data-state": "available" });
  section.appendChild(heading());
  const notes = Array.isArray(payload.notes) && payload.notes.length ? payload.notes : FALLBACK_NOTES;

  const accountButtons = el("div", { class: "acct__choices", role: "group", "aria-label": "Account",
    "data-hook": "example-accounts-account-choices" });
  const sportButtons = el("div", { class: "acct__choices acct__choices--sport", role: "group",
    "aria-label": "Sport", "data-hook": "example-accounts-sport-choices" });
  const body = el("div", { class: "acct__body", "data-hook": "example-accounts-body" });

  const buttons = [];
  const redraw = () => {
    for (const b of buttons) {
      const on = b.kind === "account" ? b.value === state.account : b.value === state.sport;
      b.node.setAttribute("aria-pressed", on ? "true" : "false");
      b.node.setAttribute("class", `acct-choice${on ? " acct-choice--on" : ""}`);
    }
    clear(body);
    const account = accounts.find((a) => a.id === state.account);
    body.appendChild(accountBody(payload, account, state.sport));
  };
  const addButton = (host, kind, value, label) => {
    const node = el("button", { type: "button", class: "acct-choice", "aria-pressed": "false",
      "data-hook": `example-accounts-${kind}-button`, [`data-acct-${kind}`]: value, text: label });
    node.addEventListener("click", () => { state[kind] = value; redraw(); });
    buttons.push({ kind, value, node });
    host.appendChild(node);
  };
  for (const a of accounts) addButton(accountButtons, "account", a.id, a.label);
  for (const key of sports) addButton(sportButtons, "sport", key, SPORT_LABEL[key]);

  section.appendChild(accountButtons);
  section.appendChild(sportButtons);
  section.appendChild(body);
  const noteBox = el("div", { class: "acct__notes", "data-hook": "example-accounts-notes" });
  for (const note of notes) noteBox.appendChild(el("p", { class: "acct__note", text: note }));
  section.appendChild(noteBox);
  redraw();
  return section;
}

function accountBody(payload, account, sportKey) {
  const wrap = el("div", { class: "acct__view" });
  const series = seriesOf(account, sportKey);
  if (!series) {
    wrap.appendChild(el("p", { class: "acct__sentence", text: UNAVAILABLE_SENTENCE }));
    return wrap;
  }
  wrap.appendChild(el("p", { class: "acct__headline", "data-hook": "example-accounts-headline",
    text: headlineText(series, payload.start_date) }));
  wrap.appendChild(el("p", { class: "acct__change", "data-hook": "example-accounts-change",
    text: changeText(series) }));
  wrap.appendChild(el("p", { class: "acct__counts", "data-hook": "example-accounts-counts",
    text: countsText(series) }));

  const floor = typeof payload.min_graded_for_percent === "number"
    ? payload.min_graded_for_percent : MIN_GRADED_FOR_PERCENT;
  const pct = percentText(series, floor);
  if (pct) {
    wrap.appendChild(el("p", { class: "acct__counts", "data-hook": "example-accounts-percent", text: pct }));
  }
  const small = smallSampleText(sportKey, series.graded, floor);
  if (small) {
    wrap.appendChild(el("p", { class: "acct__warn", "data-hook": "example-accounts-small-sample", text: small }));
  }
  if (series.postseason_picks > 0 && payload.postseason_note
      && (sportKey === "mlb" || sportKey === "all")) {
    wrap.appendChild(el("p", { class: "acct__counts", "data-hook": "example-accounts-postseason-note",
      text: payload.postseason_note }));
  }

  const chart = balanceChart(series, payload.start_date);
  if (chart) wrap.appendChild(chart);
  if (series.daily.length) {
    wrap.appendChild(dayTable(series));
    wrap.appendChild(el("p", { class: "acct__counts", "data-hook": "example-accounts-low",
      text: lowestText(series) }));
  }
  const pending = pendingText(payload.pending, sportKey);
  if (pending) {
    wrap.appendChild(el("p", { class: "acct__counts", "data-hook": "example-accounts-pending", text: pending }));
  }
  return wrap;
}

/** Fetch the payload and fill `host`. Any failure, or an `available` that is
 * not exactly true, is the one sentence: this section must never break the
 * record page it sits on. Returns the payload (or null) for the caller. */
export async function mountExampleAccounts(host, selection = {}, getJson = apiGet) {
  let payload = null;
  try {
    payload = await getJson("/card/accounts");
  } catch (err) {
    payload = null;
  }
  clear(host);
  let section;
  try {
    section = exampleAccountsSection(payload, selection);
  } catch (err) {
    section = unavailableSection();     // a payload this page cannot draw is not a payload to trust
  }
  host.appendChild(section);
  return payload;
}
