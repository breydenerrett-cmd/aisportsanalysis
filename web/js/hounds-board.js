/**
 * The model leaderboard's numbers and words, as small pure helpers (no DOM, no fetch).
 *
 * NOTHING HERE MEASURES ANYTHING. Every figure comes from a payload the server already sent (src/hounds/
 * contract.py): the record, the units, the closing-line value, the last ten results, the typical price. This
 * file orders them, formats them and words them the way a bettor reads a betting table. Where the server did
 * not send a figure the answer is `null` and the page prints "n/a", never a zero and never a guess.
 *
 *   - ROI is units divided by bets, as a percent. Every ticket is one unit, so it is the units won per unit
 *     staked, from the same two numbers printed beside it.
 *   - "Beat the close" is the share of bets with a measurable closing line whose price was better than the
 *     close; the average is the verdict block's mean, in points. Both say how many bets they rest on.
 *   - The status is the referee's label in plain words ("Beating the close", "Market", "Paying the vig"),
 *     and a model with too few measurable bets says how far it is from enough ("Not enough bets (93/150)").
 *     It is keyed on the label alone and never on units.
 *   - A ticket is a bet row. Its status is PENDING until it is graded, then WON, LOST, PUSH or VOID.
 */

import {
  isNum, signed, fmtPrice, fmtWhen, shortDate, verdictLabel, verdictTone, categoryOf, categoryLabel,
  americanDecimal, dayKey, NOT_REPORTED,
} from "./hounds-core.js";
import { unitsOf } from "./hounds-voice.js";

export const MIN_CLV_BETS = 150;           // src/hounds/verdict.py: bets with a measurable close before a verdict
export const STALE_HOURS = 6;              // older than this and the page says it is updating
export const NA = "n/a";

// ---- numbers ---------------------------------------------------------------------------------------

export function betsOf(hound) {
  const rec = hound && hound.record;
  return rec && isNum(rec.bets) && rec.bets > 0 ? rec.bets : 0;
}

/** Units per bet as a percent (one unit a bet). Null with no graded bet. */
export function roiOf(hound) {
  const bets = betsOf(hound);
  const units = unitsOf(hound);
  return bets > 0 && units !== null ? (units / bets) * 100 : null;
}

/** "+4.2%" / "-1.0%" / "n/a". */
export function fmtRoi(roi) {
  return isNum(roi) ? `${signed(roi, 1)}%` : NA;
}

export function fmtUnitsPlain(units) {
  return isNum(units) ? signed(units, 2) : NA;
}

/** The typical price taken, as the server sent it (an American price), or null. */
export function avgPriceOf(hound) {
  const p = hound && hound.form && hound.form.avg_price;
  return isNum(p) ? p : null;
}

/** Closing-line value: { n, mean, beatPct, beatN } or null when nothing is measurable. `beatPct` is 0..100. */
export function clvOf(hound) {
  const clv = hound && hound.clv;
  const beat = hound && hound.form && hound.form.clv_beat;
  const mean = clv && isNum(clv.mean_pts) ? clv.mean_pts : null;
  const n = clv && isNum(clv.n) ? clv.n : (beat && isNum(beat.n) ? beat.n : 0);
  const beatPct = beat && isNum(beat.pct) ? beat.pct * 100 : null;
  if (mean === null && beatPct === null) return null;
  return { n, mean, beatPct, beatN: beat && isNum(beat.n) ? beat.n : null };
}

/** The last ten decided results, oldest first: ["W","L","P",...]. Empty when the server sent none. */
export function last10Of(hound) {
  const list = hound && hound.form && hound.form.last10;
  return Array.isArray(list) ? list.filter((x) => x === "W" || x === "L" || x === "P").slice(-10) : [];
}

export function openBetsOf(hound) {
  const n = hound && hound.open_bets;
  return isNum(n) && n > 0 ? n : 0;
}

/** "W3" / "L2" / "" from form.streak. */
export function streakText(hound) {
  const st = hound && hound.form && hound.form.streak;
  return st && isNum(st.length) && st.length >= 1 && (st.kind === "W" || st.kind === "L") ? `${st.kind}${st.length}` : "";
}

/** "58-51" or "58-51-2" (pushes). */
export function recordText(hound) {
  const rec = (hound && hound.record) || {};
  if (!isNum(rec.bets) || rec.bets <= 0) return "0-0";
  return `${rec.wins ?? 0}-${rec.losses ?? 0}${rec.pushes ? `-${rec.pushes}` : ""}`;
}

// ---- status words ----------------------------------------------------------------------------------

/**
 * The model's status in plain words, from the referee's label. { key, text, tone, title }. A retired model
 * reads "Retired". Too few measurable bets reads "Not enough bets (n/150)" with n the bets that have a
 * measurable closing price.
 */
export function statusOf(hound) {
  if (hound && hound.status === "retired") {
    return { key: "retired", text: "Retired", tone: "bad", title: "Stopped by its own retirement rule. Its record stays." };
  }
  const label = verdictLabel(hound);
  const tone = verdictTone(label);
  const n = hound && hound.clv && isNum(hound.clv.n) ? hound.clv.n : 0;
  switch (label) {
    case "BEATING THE CLOSE":
      return { key: "beating", text: "Beating the close", tone, title: "Its prices keep beating where the market closes. That is good shopping, not a promise of wins." };
    case "NO DIFFERENT FROM THE MARKET":
      return { key: "market", text: "Market", tone, title: "Its prices look like the closing line: no better, no worse." };
    case "PAYING THE VIG":
      return { key: "vig", text: "Paying the vig", tone, title: "Its prices keep landing worse than the close, so every bet costs a little extra." };
    case "TOO EARLY":
      return { key: "early", text: `Not enough bets (${n}/${MIN_CLV_BETS})`, tone,
        title: `A model needs ${MIN_CLV_BETS} bets with a measurable closing price before a verdict. Results this early are mostly luck.` };
    default:
      return { key: "unrated", text: "Not graded vs close", tone: "unknown", title: "This model was never graded against the closing line." };
  }
}

// ---- type and sport --------------------------------------------------------------------------------

export const SPORT_LABELS = { mlb: "MLB", nfl: "NFL", ufc: "UFC", tennis: "Tennis", nba: "NBA", nhl: "NHL" };

export function sportLabel(sport) {
  const key = String(sport || "").toLowerCase();
  return SPORT_LABELS[key] || key.toUpperCase();
}

export function sportsOf(hound) {
  return Array.isArray(hound && hound.sports) ? hound.sports.map((x) => String(x).toLowerCase()) : [];
}

export function marketsText(hound) {
  const m = Array.isArray(hound && hound.markets) ? hound.markets : [];
  return m.map((x) => ({ h2h: "moneyline", totals: "totals", spreads: "spread", props: "props" }[x] || String(x))).join(", ");
}

export function typeText(hound) {
  return categoryLabel(categoryOf(hound)) || "Other";
}

/** The sports present, in a stable order (MLB first). */
export function presentSports(hounds) {
  const found = new Set();
  for (const hound of hounds || []) for (const sp of sportsOf(hound)) found.add(sp);
  const order = Object.keys(SPORT_LABELS);
  return Array.from(found).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99) || a.localeCompare(b));
}

export function filterBySport(hounds, sport) {
  return !sport || sport === "all" ? (hounds || []) : (hounds || []).filter((x) => sportsOf(x).includes(sport));
}

// ---- sorting ---------------------------------------------------------------------------------------

export const COLUMNS = [
  { key: "model", label: "Model", numeric: false, first: "asc" },
  { key: "type", label: "Type", numeric: false, first: "asc" },
  { key: "record", label: "Record", numeric: true, first: "desc", hint: "Wins-losses-pushes" },
  { key: "units", label: "Units", numeric: true, first: "desc", hint: "One unit a bet, at the average price" },
  { key: "roi", label: "ROI", numeric: true, first: "desc", hint: "Units per bet, as a percent" },
  { key: "bets", label: "Bets", numeric: true, first: "desc", hint: "Graded bets" },
  { key: "price", label: "Avg price", numeric: true, first: "desc", hint: "The typical price taken" },
  { key: "clv", label: "CLV", numeric: true, first: "desc", hint: "Share of bets that beat the close, and the average points" },
  { key: "last10", label: "Last 10", numeric: true, first: "desc", hint: "Wins in the last ten decided bets" },
  { key: "status", label: "Status", numeric: false, first: "desc", hint: "The referee's verdict, in plain words" },
];

const STATUS_RANK = { beating: 0, market: 1, early: 2, unrated: 3, vig: 4, retired: 5 };

/** The value a column sorts on; `null` means "no value" and always sorts last. */
export function sortValue(hound, key) {
  switch (key) {
    case "model": return String((hound && hound.name) || "").toLowerCase();
    case "type": return typeText(hound).toLowerCase();
    case "record": {
      const rec = hound && hound.record;
      return betsOf(hound) > 0 ? ((rec.wins ?? 0) / Math.max(1, (rec.wins ?? 0) + (rec.losses ?? 0))) : null;
    }
    case "units": return unitsOf(hound);
    case "roi": return roiOf(hound);
    case "bets": return betsOf(hound) > 0 ? betsOf(hound) : null;
    case "price": { const p = avgPriceOf(hound); return p === null ? null : americanDecimal(p); }
    case "clv": { const c = clvOf(hound); return c ? (c.mean !== null ? c.mean : c.beatPct) : null; }
    case "last10": { const l = last10Of(hound); return l.length ? l.filter((x) => x === "W").length / l.length : null; }
    case "status": { const k = statusOf(hound).key; return STATUS_RANK[k] ?? 9; }
    default: return null;
  }
}

/** A sorted copy. `dir` is "asc" | "desc". A model with no value for the column goes last either way; ties by name. */
export function sortHounds(hounds, key, dir = "desc") {
  const sign = dir === "asc" ? 1 : -1;
  return (hounds || []).slice().sort((a, b) => {
    const va = sortValue(a, key), vb = sortValue(b, key);
    if (va === null && vb !== null) return 1;
    if (vb === null && va !== null) return -1;
    if (va !== null && vb !== null && va !== vb) return (va < vb ? -1 : 1) * sign;
    return String(a.name || "").localeCompare(String(b.name || ""));
  });
}

/** Models with a graded bet are the table; the rest are "warming up" (nothing graded to rank). */
export function splitWarming(hounds) {
  const active = [], warming = [];
  for (const hound of hounds || []) (betsOf(hound) > 0 ? active : warming).push(hound);
  return { active, warming };
}

// ---- tickets ---------------------------------------------------------------------------------------

export const RESULT_WORDS = { pending: "PENDING", won: "WON", lost: "LOST", push: "PUSH", void: "VOID" };

/** The ticket's status key from a bet row's `result`. */
export function ticketStatus(result) {
  const r = String(result === null || result === undefined ? "" : result).toLowerCase();
  if (r === "win" || r === "won" || r === "w") return "won";
  if (r === "loss" || r === "lost" || r === "l") return "lost";
  if (r === "push" || r === "p") return "push";
  if (r === "void" || r === "v") return "void";
  return "pending";
}

function parseMs(value) {
  const ms = Date.parse(String(value || ""));
  return Number.isFinite(ms) ? ms : null;
}

/**
 * When the ticket went on the record, against the first pitch: { kind: "before" | "after" | "recorded" | "none",
 * text }. "Before" carries how long before. A ticket recorded at or after the start says so.
 */
export function recordedText(ticket) {
  const t = ticket || {};
  const rec = parseMs(t.recorded_utc);
  if (rec === null) return { kind: "none", text: NA };
  const when = fmtWhen(t.recorded_utc);
  const start = parseMs(t.start_utc);
  if (start === null) return { kind: "recorded", text: when };
  const diff = Math.round((start - rec) / 60000);
  if (diff <= 0) return { kind: "after", text: `${when}, after the start` };
  const span = diff >= 120 ? `${Math.floor(diff / 60)}h ${String(diff % 60).padStart(2, "0")}m` : `${diff}m`;
  return { kind: "before", text: `${when}, ${span} before the start` };
}

/** The price a ticket is settled at: the board average when it has one, else the price taken. Null when neither. */
export function ticketPrice(ticket) {
  const t = ticket || {};
  if (isNum(t.price_average)) return t.price_average;
  return isNum(t.price) ? t.price : null;
}

/** The pick in a bettor's words: the selection as the server wrote it (it already carries the line). */
export function pickOf(ticket) {
  return String((ticket && ticket.selection) || "").trim() || NOT_REPORTED;
}

export function marketLabel(market) {
  const key = String(market || "").toLowerCase();
  return { h2h: "Moneyline", moneyline: "Moneyline", totals: "Total", spreads: "Spread", spread: "Spread" }[key]
    || (key ? key.charAt(0).toUpperCase() + key.slice(1) : NA);
}

/** "betrivers, 7 books" / "betrivers" / "7 books" / "". */
export function booksText(ticket) {
  const t = ticket || {};
  const n = isNum(t.book_count) && t.book_count > 0 ? t.book_count : null;
  const parts = [];
  if (t.book) parts.push(String(t.book));
  if (n !== null) parts.push(`${n} ${n === 1 ? "book" : "books"}`);
  return parts.join(", ");
}

/** Tickets worth showing as tickets: real bets, not the stream's "sat this one out" lines. */
export function onlyTickets(items) {
  return (Array.isArray(items) ? items : []).filter((x) => x && !x.refused && String(x.verdict || "play") === "play");
}

// ---- freshness -------------------------------------------------------------------------------------

/**
 * "Data as of Oct 18" and whether the page should say it is updating. `as_of` is a day ("2026-10-18", read as
 * the end of that UTC day) or a timestamp (a saved copy's build time). Older than STALE_HOURS, or a payload
 * flagged `stale`, is "updating". No readable time at all: no claim either way.
 */
export function freshness(payload, nowMs) {
  const p = payload || {};
  const raw = p.data_as_of || p.as_of || "";
  const text = String(raw || "");
  const stamp = parseMs(text.length > 10 ? text : "");
  let ms = stamp;
  if (ms === null && dayKey(text)) ms = Date.parse(`${dayKey(text)}T23:59:59Z`);
  const label = text ? (fmtWhen(text) || text) : "";
  const now = isNum(nowMs) ? nowMs : Date.now();
  const stale = p.stale === true || (ms !== null && now - ms > STALE_HOURS * 3600 * 1000);
  return { label, stale, ageHours: ms === null ? null : Math.max(0, (now - ms) / 3600000) };
}

export function shortStamp(value) {
  return fmtWhen(value) || shortDate(value) || NA;
}

export { fmtPrice };
