/**
 * How THIS viewer reads the money: a unit size, or a percent of bankroll. A lens on the record, never the record.
 *
 * WHY (owner, 2026-10-21, relaying Jacob). At a fixed $10 unit a 1-unit and a 3-unit bet were $10 and $30: too small
 * a spread to feel like money. A viewer now chooses what a unit is worth, or sizes bets as a share of a bankroll
 * that grows and shrinks. UNITS STAY THE TRUTH: every stored bet, grade, rank and the leaderboard order is in units
 * and never reads this module. Only the dollars a page prints do, through `lensBlock` (a hound's `bankroll` block
 * in the viewer's dollars) and `lensSeriesUsd` (the balance chart).
 *
 * THE DEFINITION IS PYTHON'S. src/hounds/unit_size.py owns the dollar arithmetic and the choices below; this file
 * is its port, and tests/test_unit_size.py runs both over the same bets and demands the same dollars. In short:
 *   - FIXED   1 unit = `unit_usd` whole dollars ($1 to $1,000; chips $10/$25/$50/$100; default $25). The start is
 *     100 units, so dollars are units x the unit and return % and every rank are identical at every unit size.
 *   - PERCENT 1 unit = `pct` percent (0.5 to 5) of the balance when the bet is placed, on a starting bankroll the
 *     viewer sets ($100 to $100,000, default $2,500). It compounds: every bet of one slate day is sized off the
 *     balance before any of that day's bets settle. The return % is the compounded figure "at your sizing".
 *
 * LOCKED (owner, 2026-11-05): there is no choice any more. Every hound starts at $2,500 and 1 unit is $25; storage and
 * the account are not read (see "the lock" below). The arithmetic stays because the payload's reference block and the
 * test seam still use it.
 *
 * A PAYLOAD WITHOUT `events` (a saved copy from before this lens) still scales in fixed mode (every dollar figure
 * is linear in the unit); in percent mode it has no dollars rather than a guess.
 */

export const FIXED_MIN = 1;
export const FIXED_MAX = 1000;
export const FIXED_CHIPS = [10, 25, 50, 100];
export const DEFAULT_FIXED_USD = 25;
export const UNITS_IN_START = 100;
export const PCT_CHOICES = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5];
export const DEFAULT_PCT = 1;
export const START_MIN = 100;
export const START_MAX = 100000;
export const DEFAULT_START_USD = 2500;
export const START_USD = 2500;
export const UNIT_USD = 25;

const WINDOW_SECONDS = { h24: 24 * 3600, d7: 7 * 24 * 3600, d30: 30 * 24 * 3600 };
const isNum = (n) => typeof n === "number" && Number.isFinite(n);
// toFixed rounds the exact binary value, as Python's round() does, so a half-cent lands on the same side in both ports
const round = (x, nd = 2) => Number((x + 0).toFixed(nd));

export const fixedSizing = (unit) => ({ mode: "fixed", unit_usd: unit, pct: null, start_usd: unit * UNITS_IN_START });
export const percentSizing = (pct, start) => ({ mode: "percent", unit_usd: null, pct, start_usd: start });
export const defaultSizing = () => fixedSizing(DEFAULT_FIXED_USD);

const wholeDollars = (v, lo, hi) => (isNum(v) && Number.isInteger(v) && v >= lo && v <= hi ? v : null);

/** Why `raw` is not a legal sizing (a sentence for a form), or null when it is. Mirrors unit_size.validate. */
export function sizingProblem(raw) {
  if (!raw || typeof raw !== "object") return "Pick a sizing.";
  if (raw.mode === "fixed") {
    return wholeDollars(raw.unit_usd, FIXED_MIN, FIXED_MAX) === null
      ? `A unit is a whole number of dollars from $${FIXED_MIN} to $${FIXED_MAX.toLocaleString("en-US")}.` : null;
  }
  if (raw.mode === "percent") {
    if (!PCT_CHOICES.includes(raw.pct)) return "The percent is 0.5 to 5 in steps of 0.5.";
    return wholeDollars(raw.start_usd, START_MIN, START_MAX) === null
      ? `The starting bankroll is a whole number of dollars from $${START_MIN} to $${START_MAX.toLocaleString("en-US")}.` : null;
  }
  return "Pick fixed dollars or a percent of bankroll.";
}

/** A clean sizing from untrusted input (storage, a response), or null. Nothing is coerced from text. */
export function parseSizing(raw) {
  if (sizingProblem(raw) !== null) return null;
  return raw.mode === "fixed" ? fixedSizing(raw.unit_usd) : percentSizing(raw.pct, raw.start_usd);
}

// ---- the lock -----------------------------------------------------------------------------------------

// THE BANKROLL IS LOCKED (owner, 2026-11-05): every hound starts at $2,500 and 1 unit is $25, for every viewer.
// Nothing stored in the browser or on the account changes a figure: getSizing() always answers the lock. The ONE
// exception is a test seam, `globalThis.__lhSizingPin`, which the page-test harness sets; production never does.
const listeners = [];

/** The sizing in force: always the lock ($25 fixed, $2,500 start). Never throws. */
export function getSizing() {
  try {
    const pin = globalThis.__lhSizingPin;
    if (pin) return parseSizing(pin) || defaultSizing();
  } catch (err) { /* no globalThis */ }
  return defaultSizing();
}

/** Kept so callers that ask for the account sizing line keep working; the lock needs no request. */
export function withEvents(url) {
  return getSizing().mode === "percent" ? `${url}${url.includes("?") ? "&" : "?"}events=1` : url;
}

/** Test seam kept for the old tests: there is no remembered choice to forget. */
export function resetSizing() {}

/** Run `fn(sizing)` whenever the sizing changes. It never does now; kept so a page's registration is harmless. */
export function onSizingChange(fn) {
  listeners.push(fn);
}

/** Refused: the sizing is locked. Resolves to null so a stale caller sees "not accepted". */
export async function chooseSizing() {
  return null;
}

/** Nothing to pull from the account: the sizing is locked. Resolves to the lock; never rejects. */
export async function syncFromAccount() {
  return getSizing();
}

// ---- words ---------------------------------------------------------------------------------------------

const trim = (n) => String(round(n, 2));
const usd = (n) => `$${Number.isInteger(round(n, 2)) ? round(n, 2).toLocaleString("en-US") : round(n, 2).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** "1u = $25" or "1u = 1% of bankroll": the chip's text. */
export function unitWords(sizing = getSizing()) {
  return sizing.mode === "fixed" ? `1u = ${usd(sizing.unit_usd)}` : `1u = ${trim(sizing.pct)}% of bankroll`;
}

/** "1 unit = $25" or "1 unit = 1% of bankroll": the same words in a sentence. */
export function unitSentence(sizing = getSizing()) {
  return unitWords(sizing).replace(/^1u/, "1 unit");
}

/** "$2,500": the starting bankroll at this sizing. */
export function startText(sizing = getSizing()) {
  return usd(sizing.start_usd);
}

/** What a stake of `units` is at this sizing: "$50" in fixed mode, "2% of bankroll" in percent mode. */
export function stakeWords(units, sizing = getSizing()) {
  return sizing.mode === "fixed" ? usd(units * sizing.unit_usd) : `${trim(units * sizing.pct)}% of bankroll`;
}

/** The stake picker's label: "2u · $50" or "2u · 2% of bankroll". */
export function stakeOptionLabel(units, sizing = getSizing()) {
  return `${trim(units)}u · ${stakeWords(units, sizing)}`;
}

/** The sentence that explains the money on a board, in the viewer's own terms. */
export function rulesSentence(sizing = getSizing(), who = "model") {
  return sizing.mode === "fixed"
    ? `Every ${who} starts with the same ${startText(sizing)} paper bankroll. ${unitSentence(sizing)}.`
    : `Every ${who} starts with the same ${startText(sizing)} paper bankroll. ${unitSentence(sizing)}, so bets compound (at your sizing).`;
}

/** " (at your sizing)" in percent mode, where the return % is compounded; empty in fixed mode. */
export function sizingTag(sizing = getSizing()) {
  return sizing.mode === "percent" ? "at your sizing" : "";
}

// ---- the dollars (port of unit_size.priced and bankroll.block) -------------------------------------------

/** `[ [profitUsd, stakedUsd], ... ]` aligned with `events` ([date, settle, units, stake, result letter]). */
export function priced(events, sizing) {
  if (sizing.mode === "fixed") return events.map((e) => [e[2] * sizing.unit_usd, e[3] * sizing.unit_usd]);
  const share = sizing.pct / 100;
  const out = events.map(() => [0, 0]);
  const byDay = new Map();
  events.forEach((e, i) => { const day = String(e[0] || ""); (byDay.get(day) || byDay.set(day, []).get(day)).push(i); });
  let balance = sizing.start_usd;
  for (const day of [...byDay.keys()].sort()) {
    const base = balance;                           // every bet of the day is sized off this one balance
    let total = 0;
    for (const i of byDay.get(day)) {
      out[i] = [events[i][2] * share * base, events[i][3] * share * base];
      total += out[i][0];
    }
    balance += total;
  }
  return out;
}

// the compact event's result letter: w(in), l(oss), p(ush); anything else (open, void) is neither
const DECIDED = ["w", "l"];
const SETTLED = ["w", "l", "p"];

/** The block's own unit; a block that does not say (a hand-built one) is read as 100 units of its start. */
function ownUnit(b) {
  return isNum(b.unit_usd) && b.unit_usd > 0 ? b.unit_usd : b.start / UNITS_IN_START;
}

function scaleFixed(b, sizing) {
  const own = ownUnit(b);
  if (!(own > 0)) return null;
  const k = sizing.unit_usd / own;
  const out = { ...b, sizing, unit_usd: sizing.unit_usd, start: sizing.start_usd };
  out.current = isNum(b.current) ? round(sizing.start_usd + (b.current - b.start) * k) : null;
  out.peak = isNum(b.peak) ? round(sizing.start_usd + (b.peak - b.start) * k) : null;
  for (const key of ["pnl_usd", "max_drawdown_usd", "wagered_usd"]) out[key] = isNum(b[key]) ? round(b[key] * k) : b[key];
  if (b.windows) {
    out.windows = {};
    for (const [name, w] of Object.entries(b.windows)) out.windows[name] = { ...w, pnl_usd: isNum(w.pnl_usd) ? round(w.pnl_usd * k) : w.pnl_usd };
  }
  return out;
}

/**
 * A hound's `bankroll` block in THIS viewer's dollars, or null when there are none to show (percent mode on a
 * payload with no `events`). Units, bets, settled, the record and the basis are untouched; the same block comes
 * back when the viewer's sizing is the one the server computed. `now` is epoch seconds.
 */
export function lensBlock(b, sizing = getSizing(), now = Date.now() / 1000) {
  if (!b || !isNum(b.current) || !isNum(b.start)) return b || null;
  if (b.sizing && JSON.stringify(b.sizing) === JSON.stringify(sizing)) return b;
  // The viewer's sizing IS the server's reference account: the block already is their dollars, and its windows were
  // worked out against the server's clock for this very request, so they are kept as sent.
  if (!b.sizing && sizing.mode === "fixed" && ownUnit(b) === sizing.unit_usd && b.start === sizing.start_usd) return b;
  const events = Array.isArray(b.events) ? b.events : null;
  if (events === null) return sizing.mode === "fixed" ? scaleFixed(b, sizing) : null;
  const start = sizing.start_usd;
  const usdOf = priced(events, sizing);
  let balance = start, peak = start, worst = 0, worstPct = 0, pnl = 0, wagered = 0;
  events.forEach((e, i) => {
    balance += usdOf[i][0];
    pnl += usdOf[i][0];
    if (DECIDED.includes(e[4])) wagered += usdOf[i][1];
    peak = Math.max(peak, balance);
    const drop = peak - balance;
    if (drop > worst + 1e-9) { worst = drop; worstPct = (drop / peak) * 100; }
  });
  const windows = {};
  const win = (rows) => {
    const p = rows.reduce((s, i) => s + usdOf[i][0], 0);
    return { pnl_usd: round(p), return_pct: round((p / start) * 100), units: round(rows.reduce((s, i) => s + events[i][2], 0)),
      bets: rows.length, settled: rows.filter((i) => SETTLED.includes(events[i][4])).length };
  };
  const all = events.map((_, i) => i);
  for (const [name, secs] of Object.entries(WINDOW_SECONDS)) {
    const cutoff = now - secs;
    windows[name] = win(all.filter((i) => events[i][1] !== null && events[i][1] > cutoff));
  }
  windows.season = win(all);
  return {
    ...b, sizing, start, current: round(start + pnl), pnl_usd: round(pnl), return_pct: round((pnl / start) * 100),
    unit_usd: sizing.mode === "fixed" ? sizing.unit_usd : null, unit_pct: sizing.mode === "fixed" ? b.unit_pct : sizing.pct,
    wagered_usd: round(wagered), yield_pct: wagered > 0 ? round((pnl / wagered) * 100) : null,
    peak: round(peak), max_drawdown_usd: round(worst), max_drawdown_pct: round(worstPct), windows,
  };
}

/**
 * The balance after each point's slate day, for a chart: `points` are `{date, ...}` in date order. Fixed mode
 * and percent mode both read the events (the zero point before the first bet is the start).
 */
export function lensSeriesUsd(points, b, sizing = getSizing()) {
  const events = b && Array.isArray(b.events) ? b.events : null;
  if (events === null) {
    if (sizing.mode !== "fixed" || !b || !isNum(b.start)) return null;
    const k = sizing.unit_usd / ownUnit(b);
    return points.map((p) => (isNum(p.bankroll_usd) ? round(sizing.start_usd + (p.bankroll_usd - b.start) * k) : null));
  }
  const usdOf = priced(events, sizing);
  const perDay = new Map();
  events.forEach((e, i) => perDay.set(String(e[0]), (perDay.get(String(e[0])) || 0) + usdOf[i][0]));
  const days = [...perDay.keys()].sort();
  return points.map((p) => {
    let sum = 0;
    for (const day of days) { if (day <= String(p.date)) sum += perDay.get(day); else break; }
    return round(sizing.start_usd + sum);
  });
}


// ---- static sentences a page ships in its HTML --------------------------------------------------------------

/**
 * Sentences that sit in a page's HTML (the glossary, a table caption) and must name the viewer's own money. The
 * HTML ships the DEFAULT wording ($25 unit, $2,500 start) for a visitor with scripts off; `fillSizingText` rewrites each
 * `[data-us="key"]` element from here at load. One list, so no page types a dollar figure of its own.
 */
export const SENTENCES = {
  "bankroll-line": (s) => `Every hound starts with the same ${startText(s)} paper bankroll. Paper money, not advice.`,
  "lb-note": (s) => `Our own hounds, championed, trained, bred and culled in public. ${rulesSentence(s, "hound")}`,
  "lb-caption": (s) => `Top five hounds by paper bankroll, every hound starting from ${startText(s)}`,
  "gloss-bankroll": (s) => `Every hound is a paper account that starts with the same ${startText(s)}. Bankroll is the account now; Return is the gain or loss as a percent of that ${startText(s)} for the season shown${s.mode === "percent" ? ", compounded at your sizing" : ""}. 7d and 24h are the same percent for bets that settled in the last 7 days and the last 24 hours. Bets are settled at the average price across books when the bet was placed.`,
  "gloss-units": (s) => (s.mode === "fixed"
    ? `Total units won or lost. One unit is ${usd(s.unit_usd)} at your unit size (1% of the starting ${startText(s)}, fixed, never compounding), so units and Return always move together: 10 units is +10%. House hounds bet 1 unit a game; a member's hound bets the units its owner chose, so its units and dollars count that stake. Units are the record; the dollars are yours to size.`
    : `Total units won or lost. At your sizing one unit is ${trim(s.pct)}% of the balance when the bet is placed, so dollars compound while units stay the record. House hounds bet 1 unit a game; a member's hound bets the units its owner chose, so its units and dollars count that stake.`),
  "backtest-how": (s) => `Replay a hound's current rule over the last 7, 14 or 30 days (or Season 2 so far, at most the last 30 days) of stored boards and see what it would have done on the ${startText(s)} paper bankroll. It is a rehearsal: you can see how those games ended, so a backtest is never added to a record, a ranking or a verdict. A month can take up to a minute.`,
};

/** Rewrite every `[data-us]` element under `root` to the viewer's own sentence. Never throws (a missing DOM is fine). */
export function fillSizingText(root) {
  try {
    const scope = root || document;
    const sizing = getSizing();
    for (const node of scope.querySelectorAll("[data-us]")) {
      const make = SENTENCES[node.getAttribute("data-us")];
      if (make) node.textContent = make(sizing);
    }
  } catch (err) {
    /* no DOM, or a fake one: the HTML's default wording stands */
  }
}

if (typeof document !== "undefined") fillSizingText();
