/**
 * ONE PLACE THAT TURNS A GRADED ENTRY INTO WHAT A READER SEES.
 *
 * Two public pages show the same V2 ledger entries: the landing page's
 * sample card (web/js/landing.js) and the record page's day-by-day section
 * (web/js/cardrecord.js). Both used to need the same words -- "Yankees to
 * win", "Michael Busch over 0.5 hits", "-135 . best of 11 books", the result
 * line, the fill label, the void reason, the postseason tag -- and a second
 * hand-written copy would drift. These pure functions are the only copy.
 * Nothing in here touches the DOM.
 *
 * WHAT A V2 ENTRY CARRIES (card_ledger.history_v2 reshapes nothing): one
 * object per published item, `entry_class` ("pick" or "fill"), `kind`
 * ("game" or "prop"), `market`, `team_name`, `player`, `side`, `line`,
 * `price`, `books` (a count of books quoted), usually no single `book`,
 * `result`, `profit_units`, scores, `withdrawn`, a void `reason`, and no
 * server-written `bet` sentence. The bet is composed from those fields; a
 * `bet` or `book` that does arrive is used as sent. A book name is never
 * invented.
 *
 * WHAT THIS MODULE DOES NOT DECIDE: which entries a page may hide. The
 * landing sample omits entries priced at -200 or shorter (isHeavyFavourite);
 * the record page is the ledger and shows them. Each caller chooses.
 */

import { formatAmerican } from "./dom.js";
import { bookLabel } from "./labels.js";

export const RESULT_WORD = { WIN: "Won", LOSS: "Lost", PUSH: "Push", VOID: "Void" };
export const NOT_GRADED_WORD = "Not graded yet";
export const POSTSEASON_GAME_TYPES = ["F", "D", "L", "W"];
export const HEAVY_FAVOURITE_PRICE = -200;
export const FILL_TAG = "Fill, not a pick";
export const POSTSEASON_TAG_SAMPLE = "Postseason game";
export const POSTSEASON_TAG_RECORD = "Postseason, graded, not counted";
export const UNNAMED_BET = "Entry could not be named from the stored fields";

export function propNoun(market) {
  return String(market || "").replace(/^(batter|pitcher)_/, "").replace(/_/g, " ");
}

export function signedLine(line) {
  const n = Number(line);
  if (!Number.isFinite(n)) return String(line);
  return n > 0 ? `+${n}` : String(n);
}

/** The bet as a reader would say it. A server `bet` sentence wins; otherwise
 * the entry's own fields. Empty string when nothing readable can be made. */
export function betText(entry) {
  if (typeof entry.bet === "string" && entry.bet.trim()) return entry.bet.trim();
  const hasLine = entry.line !== null && entry.line !== undefined;
  if (entry.kind === "prop" || entry.player) {
    if (!entry.player) return "";
    const side = entry.side ? String(entry.side).toLowerCase() : "";
    return [entry.player, side, hasLine ? String(entry.line) : "", propNoun(entry.market)]
      .filter(Boolean).join(" ");
  }
  const team = entry.team_name || entry.team || "";
  if (!team) return "";
  if (entry.market === "run_line" || (hasLine && entry.market !== "moneyline")) {
    return hasLine ? `${team} ${signedLine(entry.line)} run line` : "";
  }
  return `${team} to win`;
}

/** "+0.74 units" / "−1.00 units"; null when the value is not a number. */
export function unitsText(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)} units`;
}

export function isFill(entry) {
  return !!entry && entry.entry_class === "fill";
}

export function isPostseason(entry) {
  if (!entry) return false;
  // The server's own answer wins when it sends one (GET /card/history marks
  // each V2 entry `postseason`): a prop entry freezes game_type "R" even on a
  // postseason game, so the stored type alone tagged the moneyline and missed
  // the props on the same game.
  if (typeof entry.postseason === "boolean") return entry.postseason;
  return POSTSEASON_GAME_TYPES.includes(entry.game_type);
}

/** True for an entry priced at -200 or shorter. */
export function isHeavyFavourite(entry) {
  const price = Number(entry && entry.price);
  return Number.isFinite(price) && price <= HEAVY_FAVOURITE_PRICE;
}

/** One entry -> the row a reader sees.
 *
 * Strict (the default, the landing sample): null when it cannot be shown
 * honestly -- no readable bet, price or known result.
 * Lenient (the record page, which may not hide history): never null; an
 * entry that cannot be named says so, a missing price is null, and a result
 * that is not WIN/LOSS/PUSH/VOID reads "Not graded yet". */
export function entryRow(entry, options = {}) {
  const lenient = !!options.lenient;
  const named = betText(entry);
  const price = formatAmerican(entry.price);
  const word = RESULT_WORD[entry.result] || (lenient ? NOT_GRADED_WORD : null);
  if (!lenient && (!named || !price || !word)) return null;
  const bet = named || UNNAMED_BET;

  const bookName = entry.book ? (bookLabel(entry.book) || String(entry.book)) : null;
  const books = entry.books ? Number(entry.books) || null : null;
  const bestOf = books ? `best of ${books} books` : null;

  const meta = [bookName && price ? `${price} at ${bookName}` : price].filter(Boolean);
  if (bestOf) meta.push(bestOf);

  const result = [word];
  const settled = entry.result === "WIN" || entry.result === "LOSS" || entry.result === "PUSH";
  if (entry.result !== "VOID") {
    const units = unitsText(entry.profit_units);
    if (units && RESULT_WORD[entry.result]) result.push(units);
  } else if (entry.reason) {
    result.push(String(entry.reason));
  }
  const score = (typeof entry.away_score === "number" && typeof entry.home_score === "number")
    ? `${entry.away_team || "Away"} ${entry.away_score}, ${entry.home_team || "Home"} ${entry.home_score}`
    : null;
  if (score) result.push(score);

  const profit = Number(entry.profit_units);
  return {
    bet,
    named: !!named,
    meta: meta.join(" · "),
    price,
    bookName,
    books,
    bookText: [bookName, bestOf].filter(Boolean).join(" · ") || null,
    result: result.join(" · "),
    resultWord: word,
    reason: entry.result === "VOID" && entry.reason ? String(entry.reason) : null,
    score,
    outcome: entry.result,
    fill: isFill(entry),
    postseason: isPostseason(entry),
    units: entry.result === "WIN" || entry.result === "LOSS" ? profit || 0 : 0,
    // The number to print in a RETURN column: null for a void, an ungraded
    // entry or a missing figure -- never a made-up zero.
    returnUnits: settled && Number.isFinite(profit) && entry.profit_units !== null ? profit : null,
  };
}

/** "1 won, 0 lost, net +0.74 units". Fills get the count only on the
 * landing sample: they are not counted in the record, so a net figure over
 * them would read as a result the record does not carry. */
export function tallyText(rows, withNet) {
  const count = (outcome) => rows.filter((r) => r.outcome === outcome).length;
  const parts = [`${count("WIN")} won`, `${count("LOSS")} lost`];
  if (count("PUSH")) parts.push(`${count("PUSH")} push`);
  if (count("VOID")) parts.push(`${count("VOID")} void`);
  if (withNet && count("WIN") + count("LOSS")) {
    const net = rows.reduce((sum, r) => sum + r.units, 0);
    parts.push(`net ${unitsText(net)}`);
  }
  return parts.join(", ");
}

/** Every entry a history day carries, whichever rule's shape it is in:
 * V2's `graded`, or the older rule's three pick lists. */
export function dayEntries(day) {
  if (Array.isArray(day.graded)) return day.graded;
  const out = [];
  for (const key of ["picks", "prop_picks", "total_picks"]) {
    if (Array.isArray(day[key])) out.push(...day[key]);
  }
  return out;
}
