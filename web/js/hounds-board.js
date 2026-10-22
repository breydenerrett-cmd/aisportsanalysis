/**
 * The model leaderboard's numbers and words, as small pure helpers (no DOM, no fetch).
 *
 * NOTHING HERE MEASURES ANYTHING. Every figure comes from a payload the server already sent (src/hounds/
 * contract.py): the record, the units, the closing-line value, the last ten results, the typical price. This
 * file orders them, formats them and words them the way a bettor reads a betting table. Where the server did
 * not send a figure the answer is `null` and the page prints "n/a", never a zero and never a guess.
 *
 *   - THE BANKROLL (owner ruling 2026-10-19, docs/BANKROLL.md). Every model is a paper account of 100 units. The
 *     record is kept at a $1,000 / $10-unit reference, and every dollar a page prints is that same account in the
 *     VIEWER's own sizing (owner 2026-10-21: a unit size, or a percent of bankroll; web/js/unitsize.js). Ranks and
 *     sort keys read the REFERENCE account (`referenceBankrollOf`), never the viewer's dollars, so no setting moves a
 *     rank. The headline figures are the account balance and the % it moved (season, 7 days, 24 hours),
 *     all read from the payload's `bankroll` block; units are the stake-weighted total. "ROI" (units per bet) is
 *     gone from the board: `roiOf` stays only as the fallback for a payload from before the bankroll view, and
 *     the model page's yield tile is the server's `yield_pct`.
 *   - ROI (legacy) is units divided by bets, as a percent. Every ticket is one unit, so it is the units won per
 *     unit staked, from the same two numbers printed beside it.
 *   - "Beat the close" is the share of bets with a measurable closing line whose price was better than the
 *     close; the average is the verdict block's mean, in points. Both say how many bets they rest on.
 *   - The status is the referee's label in plain words ("Beating the close", "Market", "Paying the vig"),
 *     and a model with too few measurable bets says how far it is from a verdict ("Verdict at 150 bets (93/150)").
 *     It is keyed on the label alone and never on units.
 *   - A ticket is a bet row. Its status is PENDING until it is graded, then WON, LOST, PUSH or VOID.
 */

import {
  isNum, signed, fmtPrice, fmtWhen, shortDate, verdictLabel, verdictTone, categoryOf, categoryLabel,
  americanDecimal, dayKey, NOT_REPORTED,
} from "./hounds-core.js";
import { unitsOf } from "./hounds-voice.js";
import { MIN_RANKED_BETS } from "./hounds-season.js";
import { lensBlock, getSizing, startText, unitWords, unitSentence, rulesSentence, stakeWords, sizingTag } from "./unitsize.js";

export const MIN_CLV_BETS = 150;           // src/hounds/verdict.py: bets with a measurable close before a verdict
export const STALE_HOURS = 6;              // older than this and the page says it is updating
export const NA = "n/a";

// ---- numbers ---------------------------------------------------------------------------------------

export function betsOf(hound) {
  const rec = hound && hound.record;
  return rec && isNum(rec.bets) && rec.bets > 0 ? rec.bets : 0;
}

/**
 * Settled bets in the view the payload describes (win, loss or push): the record's own wins + losses + pushes,
 * so the rank can never disagree with the record printed beside it. (The server also sends `settled` and
 * `ranked`, from the same numbers; the digest reads those.)
 */
export function settledOf(hound) {
  const rec = (hound && hound.record) || {};
  return (isNum(rec.wins) ? rec.wins : 0) + (isNum(rec.losses) ? rec.losses : 0) + (isNum(rec.pushes) ? rec.pushes : 0);
}

/**
 * Is the model ranked in this view? It needs `min` settled bets there (10 unless the payload's season block says
 * otherwise). A 1-0 start is a record, never a rank.
 */
export function isRanked(hound, min = MIN_RANKED_BETS) {
  return settledOf(hound) >= min;
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

/** The Bets figure on a row: every bet the hound has made, open ones included, with the open count beside it ("5 (5 open)").
 *  `record.bets` counts SETTLED bets only, so printing it alone read "0" beside a hound holding five open tickets. */
export function betsShown(hound) {
  const open = openBetsOf(hound);
  return open > 0 ? `${betsOf(hound) + open} (${open} open)` : String(betsOf(hound));
}

/** Forward tickets more than 36 hours past their start with no grade (never counted as open). */
export function ungradedBetsOf(hound) {
  const n = hound && hound.ungraded_bets;
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

// ---- the bankroll ------------------------------------------------------------------------------------

/** The reference account's numbers (config/bankroll.json). Used for a payload that carries no `bankroll_rules` (a saved
 * copy from before the bankroll view) and for the sort fallback; never for a dollar a viewer reads. */
export const START_USD = 1000;
export const UNIT_USD = 10;
export const SMALL_SAMPLE_SETTLED = 20;      // src/hounds/bankroll.py small_sample_min_settled (the server's flag wins)
export const WINDOW_LABELS = { h24: "24h", d7: "7d", d30: "30d", season: "Season" };
export const WINDOW_WORDS = { h24: "the last 24 hours", d7: "the last 7 days", d30: "the last 30 days", season: "the season shown" };

/** The `bankroll` block exactly as the server sent it (the reference account), or null. Ranks and sorts read this. */
export function referenceBankrollOf(hound) {
  const b = hound && hound.bankroll;
  return b && isNum(b.current) && isNum(b.start) ? b : null;
}

const lensed = new WeakMap();

/**
 * The `bankroll` block a model carries IN THE VIEWER'S DOLLARS (web/js/unitsize.js), or null (an old payload, a model
 * the server could not work out, or percent sizing on a payload that predates the lens). Units, bets and the record
 * in it are the server's. Memoised per block, sizing and minute so a table of forty rows prices each bet list once.
 */
export function bankrollOf(hound) {
  const raw = referenceBankrollOf(hound);
  if (!raw) return null;
  const sizing = getSizing();
  const minute = Math.floor(Date.now() / 60000);
  const key = `${JSON.stringify(sizing)}|${minute}`;
  const hit = lensed.get(raw);
  if (hit && hit.key === key) return hit.value;
  const value = lensBlock(raw, sizing, Date.now() / 1000);
  const ok = value && isNum(value.current) && isNum(value.start) ? value : null;
  lensed.set(raw, { key, value: ok });
  return ok;
}

/** "$1,021" (or "$1,021.41" with `cents`); "-$5" below zero; "n/a" for a missing figure. */
export function fmtUsd(n, cents = false) {
  if (!isNum(n)) return NA;
  const digits = cents ? 2 : 0;
  const shown = Number(Math.abs(n).toFixed(digits));
  const body = shown.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${n < 0 && shown !== 0 ? "-" : ""}$${body}`;
}

/** "+$14" / "-$7" / "+$0": paper dollars with the sign. */
export function fmtSignedUsd(n, cents = false) {
  if (!isNum(n)) return NA;
  const shown = Number(Math.abs(n).toFixed(cents ? 2 : 0));
  return `${n < 0 && shown !== 0 ? "-" : "+"}${fmtUsd(shown, cents)}`;
}

/** "+2.1%" / "-0.4%" / "n/a". */
export function fmtPct(pct, digits = 1) {
  return isNum(pct) ? `${signed(pct, digits)}%` : NA;
}

/**
 * { start, unit, label } in the VIEWER's dollars: the starting bankroll, what one unit is (null in percent mode, where
 * it is a share of the balance) and the sentence that says so. The payload's own `bankroll_rules` is the reference
 * account (the server's sentence is its label); the viewer's sizing decides what a page prints.
 */
export function bankrollRules(payload) {
  const sizing = getSizing();
  return { start: sizing.start_usd, unit: sizing.mode === "fixed" ? sizing.unit_usd : null, label: rulesSentence(sizing),
    reference: referenceRules(payload) };
}

/** The server's reference account: { start, unit, label } as `bankroll_rules` sent it (or the fallbacks). */
export function referenceRules(payload) {
  const r = (payload && payload.bankroll_rules) || {};
  const start = isNum(r.start_usd) ? r.start_usd : START_USD;
  const unit = isNum(r.unit_usd) ? r.unit_usd : UNIT_USD;
  const label = typeof r.label === "string" && r.label
    ? r.label : `Every model starts with the same ${fmtUsd(start)} paper bankroll. 1 unit = ${fmtUsd(unit)}.`;
  return { start, unit, label };
}

/** The balance now, or null. */
export function bankrollNow(hound) {
  const b = bankrollOf(hound);
  return b ? b.current : null;
}

/** The view's return on the starting bankroll, in percent, or null. */
export function returnPctOf(hound) {
  const b = bankrollOf(hound);
  return b && isNum(b.return_pct) ? b.return_pct : null;
}

/** One window of the account: { pnl, pct, units, bets, settled } for "h24" | "d7" | "d30" | "season", or null. */
export function windowOf(hound, key) {
  const b = bankrollOf(hound);
  const w = b && b.windows && b.windows[key];
  if (!w || !isNum(w.return_pct)) return null;
  return { pnl: isNum(w.pnl_usd) ? w.pnl_usd : null, pct: w.return_pct, units: isNum(w.units) ? w.units : null,
    bets: isNum(w.bets) ? w.bets : 0, settled: isNum(w.settled) ? w.settled : 0 };
}

/** The % return for a window, or null when no bet settled in it (a window with nothing in it is not "0.0%"). */
export function windowPct(hound, key) {
  const w = windowOf(hound, key);
  return w && w.bets > 0 ? w.pct : null;
}

/**
 * Which price the dollars and units are settled at: "average_price" (the board average when the bet was placed, the
 * headline) or "recorded_price" (the price the model took, used for a model whose average-price board is missing for
 * more than 10% of its bets). One basis per model, chosen by the server (`bankroll.basis`), never mixed within a
 * model. Null when the payload carries no bankroll block.
 */
export function basisOf(hound) {
  const b = bankrollOf(hound);
  return b && (b.basis === "average_price" || b.basis === "recorded_price") ? b.basis : null;
}

export const RECORDED_TAG = "best price";
export const RECORDED_TITLE = "This model's bets are settled at the price it took (its best recorded quote), because the average-price board is missing for more than 10% of its bets. Other models are settled at the average price, so compare with care.";

/** "best price" when this model is settled at its recorded price instead of the average, else "". */
export function basisTagText(hound) {
  return basisOf(hound) === "recorded_price" ? RECORDED_TAG : "";
}

/** Words for the price basis, for a tile or a footnote. */
export function basisWords(hound) {
  const b = basisOf(hound);
  return b === "recorded_price" ? "at the price it took (best price)" : b === "average_price" ? "at the average price across books" : "";
}

/** The tag a ticket at -200 or worse carries in every ticket list (the server's `beyond_cap`). */
export const OLD_RULE_TAG = "-200 or worse (old rule)";
export const OLD_RULE_TITLE = "Taken before the -200 price cap. It stays in the record and the money, and is never featured.";
export function isOldRule(ticket) {
  return !!ticket && ticket.beyond_cap === true;
}

/** Stake-weighted units won or lost. A payload without the bankroll block falls back to the flat units. */
export function totalUnitsOf(hound) {
  const b = bankrollOf(hound);
  if (b && isNum(b.bets) && b.bets <= 0) return null;        // nothing graded: n/a, not a zero
  return b && isNum(b.units_total) ? b.units_total : unitsOf(hound);
}

/** Fewer than 20 settled bets in the view (the server's `small_sample`), so the row is greyed. */
export function isSmallSample(hound) {
  const b = bankrollOf(hound);
  return b && typeof b.small_sample === "boolean" ? b.small_sample : settledOf(hound) < SMALL_SAMPLE_SETTLED;
}

export function smallSampleTitle(hound) {
  const b = bankrollOf(hound);
  const min = b && isNum(b.small_sample_min) ? b.small_sample_min : SMALL_SAMPLE_SETTLED;
  return `Ranked in full at ${min} settled bets: ${settledOf(hound)} so far.`;
}

/** Yield: result per dollar staked on decided bets, in percent (the old ROI), or null. Model page only. */
export function yieldOf(hound) {
  const b = bankrollOf(hound);
  return b && isNum(b.yield_pct) ? b.yield_pct : null;
}

/** { usd, pct, peak } for the worst fall of the balance from a high, or null. */
export function drawdownOf(hound) {
  const b = bankrollOf(hound);
  if (!b || !isNum(b.max_drawdown_usd) || (isNum(b.bets) && b.bets <= 0)) return null;
  return { usd: b.max_drawdown_usd, pct: isNum(b.max_drawdown_pct) ? b.max_drawdown_pct : null, peak: isNum(b.peak) ? b.peak : null };
}

/** The sort value for the balance: the account now, else (an old payload) the start plus flat units at a unit. */
function balanceKey(hound) {
  const b = referenceBankrollOf(hound);                      // the reference account: a rank never reads the viewer's dollars
  if (b && isNum(b.bets) && b.bets <= 0) return null;       // nothing graded: no sort value, always last (never a tie at $1,000)
  if (b) return b.current;
  const u = unitsOf(hound);
  return u === null ? null : START_USD + u * UNIT_USD;
}

/** The reference account's return % and window %, for sorting: unit-based, so identical for every viewer sizing. */
function referenceReturn(hound) {
  const b = referenceBankrollOf(hound);
  return b && isNum(b.return_pct) ? b.return_pct : null;
}
function referenceWindow(hound, key) {
  const b = referenceBankrollOf(hound);
  const w = b && b.windows && b.windows[key];
  return w && isNum(w.return_pct) && isNum(w.bets) && w.bets > 0 ? w.return_pct : null;
}

/** Most dollars first; a model with no graded bet last; ties by more bets, then name. */
export function sortByBankroll(hounds) {
  return (hounds || []).slice().sort((a, b) => {
    const ka = balanceKey(a), kb = balanceKey(b);
    if (ka === null && kb !== null) return 1;
    if (kb === null && ka !== null) return -1;
    return (kb ?? 0) - (ka ?? 0) || betsOf(b) - betsOf(a) || String(a.name || "").localeCompare(String(b.name || ""));
  });
}

/**
 * The builder's stake line at the VIEWER's sizing: "1 unit = $25 of your $2,500; this dog bets 2 units ($50 a bet)." or,
 * in percent mode, "1 unit = 2% of your bankroll ($5,000 to start); this dog bets 2 units (4% of bankroll a bet)."
 * `sizing` defaults to the viewer's; the units are the dog's own.
 */
export function stakeLineText(units, sizingIn) {
  const sizing = sizingIn && sizingIn.mode ? sizingIn : getSizing();       // an old caller passing the menu's bankroll block gets the viewer's
  const n = isNum(units) ? units : 1;
  const word = `${n} ${n === 1 ? "unit" : "units"}`;
  if (sizing.mode === "fixed") {
    return `1 unit = ${fmtUsd(sizing.unit_usd)} of your ${fmtUsd(sizing.start_usd)}; this dog bets ${word} (${stakeWords(n, sizing)} a bet).`;
  }
  return `${unitSentence(sizing)} (${fmtUsd(sizing.start_usd)} to start); this dog bets ${word} (${stakeWords(n, sizing)} a bet).`;
}

// ---- status words ----------------------------------------------------------------------------------

/**
 * The model's status in plain words, from the referee's label. { key, text, tone, title }. A retired model
 * reads "Retired". Too few measurable bets reads "Verdict at 150 bets (n/150)" with n the bets that have a
 * measurable closing price.
 */
export function statusOf(hound) {
  if (hound && hound.status === "retired") {
    return { key: "retired", text: "Retired", tone: "bad", title: "Stopped by its own retirement rule. Its record stays." };
  }
  if (hound && hound.status === "not_started") {
    return { key: "notstarted", text: "Not started", tone: "early", title: "This model has not made its first bet yet." };
  }
  const label = verdictLabel(hound);
  const tone = verdictTone(label);
  // The badge is the referee's and is all-time, so the count under it is too (`verdict.n`); `clv.n` follows the season.
  const n = hound && hound.verdict && isNum(hound.verdict.n) ? hound.verdict.n
    : (hound && hound.clv && isNum(hound.clv.n) ? hound.clv.n : 0);
  switch (label) {
    case "BEATING THE CLOSE":
      return { key: "beating", text: "Beating the close", tone, title: "Its prices keep beating where the market closes. That is good shopping, not a promise of wins." };
    case "NO DIFFERENT FROM THE MARKET":
      return { key: "market", text: "Market", tone, title: "Its prices look like the closing line: no better, no worse." };
    case "PAYING THE VIG":
      return { key: "vig", text: "Paying the vig", tone, title: "Its prices keep landing worse than the close, so every bet costs a little extra." };
    case "TOO EARLY":
      return { key: "early", text: `Verdict at ${MIN_CLV_BETS} bets (${n}/${MIN_CLV_BETS})`, tone,
        title: `A verdict needs ${MIN_CLV_BETS} bets with a measurable closing price. ${n} so far.` };
    default:
      return { key: "unrated", text: "Not graded vs close", tone: "unknown", title: "This model was never graded against the closing line." };
  }
}

// ---- type and sport --------------------------------------------------------------------------------

// every sport key a hound can carry (the quiz and builder offer all of them): the bare uppercased key read "GRIDIRON" and
// "BASKETBALL" on the hound page (rebuild QA 2026-10-21, the Gematria Hound plays all seventeen)
export const SPORT_LABELS = { mlb: "MLB", nfl: "NFL", ufc: "UFC", tennis: "Tennis", nba: "NBA", nhl: "NHL", ncaaf: "College football",
  gridiron: "CFL and UFL", wnba: "WNBA", ncaab: "College basketball", basketball: "Other basketball", hockey: "Other hockey",
  baseball: "Other baseball", soccer: "Soccer", cricket: "Cricket", mma: "MMA", rugby: "Rugby", afl: "Aussie rules" };

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


/**
 * The leaderboard's columns since the bankroll ruling (2026-10-19). Return is the view's % on the starting
 * bankroll; 7d and 24h are the windows by settle time inside that view. The default sort is the balance.
 */
export const COLUMNS = [
  { key: "model", label: "Model", numeric: false, first: "asc" },
  { key: "type", label: "Type", numeric: false, first: "asc" },
  { key: "record", label: "Record", numeric: true, first: "desc", hint: "Wins-losses-pushes" },
  // The hints name the viewer's own start and unit, so they are read when asked (a getter), not frozen at import.
  { key: "bankroll", label: "Bankroll", numeric: true, first: "desc", get hint() { return `The paper account now, from the shared ${startText()} start`; } },
  { key: "return", label: "Return", numeric: true, first: "desc", get hint() { return `Gain or loss as a percent of the ${startText()} start, for the season shown${sizingTag() ? ` (${sizingTag()}: compounded)` : ""}`; } },
  { key: "d7", label: "7d", numeric: true, first: "desc", get hint() { return `Return on the ${startText()} start from bets settled in the last 7 days`; } },
  { key: "h24", label: "24h", numeric: true, first: "desc", get hint() { return `Return on the ${startText()} start from bets settled in the last 24 hours`; } },
  { key: "units", label: "Units", numeric: true, first: "desc", get hint() { return `Total units won or lost (${unitWords()}; member dogs bet the units they chose)`; } },
  { key: "bets", label: "Bets", numeric: true, first: "desc", hint: "Every bet made, with the open ones (not settled yet) counted beside it. The record and the rank use settled bets only." },
  { key: "price", label: "Avg price", numeric: true, first: "desc", hint: "The typical price taken" },
  { key: "clv", label: "CLV", numeric: true, first: "desc", hint: "Share of bets that beat the close, and the average points" },
  { key: "last10", label: "Last 10", numeric: true, first: "desc", hint: "Wins in the last ten decided bets" },
  { key: "status", label: "Status", numeric: false, first: "desc", hint: "The referee's verdict, in plain words. All-time, not limited to the season shown." },
];
export const DEFAULT_SORT = "bankroll";

const STATUS_RANK = { beating: 0, market: 1, early: 2, notstarted: 3, unrated: 4, vig: 5, retired: 6 };

/** The value a column sorts on; `null` means "no value" and always sorts last. */
export function sortValue(hound, key) {
  switch (key) {
    case "model": return String((hound && hound.name) || "").toLowerCase();
    case "type": return typeText(hound).toLowerCase();
    case "record": {
      const rec = hound && hound.record;
      return betsOf(hound) > 0 ? ((rec.wins ?? 0) / Math.max(1, (rec.wins ?? 0) + (rec.losses ?? 0))) : null;
    }
    case "units": return totalUnitsOf(hound);
    case "bankroll": return balanceKey(hound);
    case "return": return referenceReturn(hound);
    case "d7": return referenceWindow(hound, "d7");
    case "h24": return referenceWindow(hound, "h24");
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

/**
 * The table and the "Warming up" group. A model with `min` settled bets in the view is RANKED and sits in the
 * table; every other model is warming up, however good its few bets look. Sorting happens inside the ranked
 * list only (`sortHounds` on `active`), so no sort key can lift a warming model above a ranked one. The warming
 * group lists the most-settled first, then by name.
 */
export function splitRanked(hounds, min = MIN_RANKED_BETS) {
  const active = [], warming = [];
  for (const hound of hounds || []) (isRanked(hound, min) ? active : warming).push(hound);
  warming.sort((a, b) => settledOf(b) - settledOf(a) || openBetsOf(b) - openBetsOf(a)
    || String(a.name || "").localeCompare(String(b.name || "")));
  return { active, warming };
}

/** Fewer ranked models than this and the page shows the QUALIFYING ROUND (everyone with a bet, with progress) above the ranked table. */
export const QUALIFYING_UNDER = 3;

export function inQualifyingRound(rankedCount) {
  return rankedCount < QUALIFYING_UNDER;
}

/** A dog a member built (not a house or desk model). Members' dogs are always listed, even before their first bet. */
export function isMemberDog(hound) {
  return !!hound && hound.kind === "user";
}

/** A member's dog with nothing yet: no settled bet and no open ticket. It is listed, flagged "New". */
export function isNewDog(hound) {
  return isMemberDog(hound) && settledOf(hound) === 0 && openBetsOf(hound) === 0;
}

/** "3/10 bets": settled bets so far over the bar (never shown above the bar). A member's brand-new dog says so. */
export function progressText(hound, min = MIN_RANKED_BETS) {
  if (isNewDog(hound)) return "New: no bets yet";
  return `${Math.min(settledOf(hound), min)}/${min} bets`;
}

/**
 * The qualifying round's rows from the models that are not ranked: those with a settled bet or an open ticket,
 * and EVERY member's dog (a new one has no bet yet and is flagged "New"), most dollars first, then the better record
 * (wins over wins + losses), then the more settled bets, then by name. A house or desk model with nothing yet is
 * left out (the page counts those in one line); a member's dog never is.
 */
export function qualifyingRows(hounds) {
  const share = (x) => {
    const rec = (x && x.record) || {};
    const w = isNum(rec.wins) ? rec.wins : 0, l = isNum(rec.losses) ? rec.losses : 0;
    return w + l > 0 ? w / (w + l) : -1;
  };
  return (hounds || []).filter((x) => settledOf(x) > 0 || openBetsOf(x) > 0 || isMemberDog(x)).sort((a, b) => {
    const ua = balanceKey(a), ub = balanceKey(b);
    if (ua === null && ub !== null) return 1;
    if (ub === null && ua !== null) return -1;
    return (ub ?? 0) - (ua ?? 0) || share(b) - share(a) || settledOf(b) - settledOf(a)
      || String(a.name || "").localeCompare(String(b.name || ""));
  });
}

// ---- tickets ---------------------------------------------------------------------------------------

export const RESULT_WORDS = { pending: "PENDING", won: "WON", lost: "LOST", push: "PUSH", void: "VOID", ungraded: "UNGRADED" };

/** The ticket's status key from a bet row's `result`. */
export function ticketStatus(result) {
  const r = String(result === null || result === undefined ? "" : result).toLowerCase();
  if (r === "win" || r === "won" || r === "w") return "won";
  if (r === "loss" || r === "lost" || r === "l") return "lost";
  if (r === "push" || r === "p") return "push";
  if (r === "void" || r === "v") return "void";
  return "pending";
}

/**
 * The ticket's status key from the whole ticket: the server's `status` says UNGRADED when the game started more
 * than 36 hours ago and nothing graded it (src/hounds/contract.py ticket_status); anything else follows `result`.
 * The page never decides that for itself: a missing `status` (an older payload) reads from `result` alone.
 */
export function ticketState(ticket) {
  const t = ticket || {};
  if (String(t.status || "").toUpperCase() === "UNGRADED" && ticketStatus(t.result) === "pending") return "ungraded";
  return ticketStatus(t.result);
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
