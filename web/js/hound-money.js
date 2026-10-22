/**
 * Paper dollars for ONE ticket, at THIS viewer's sizing (web/js/unitsize.js is the one definition of what a unit is worth).
 *
 * A graded ticket's `units` is what it moved in units, and units never change with the viewer's sizing. Here that figure is read
 * in the viewer's terms: fixed mode is units x the unit ("+$22.50"); percent-of-bankroll mode cannot name a dollar for a single
 * ticket without the whole compounding run, so it says what the ticket was worth as a share of the bankroll ("+0.91% of bankroll").
 * Never "you would have made": the caller says "on paper".
 */

import { getSizing } from "./unitsize.js";

const isNum = (n) => typeof n === "number" && Number.isFinite(n);
const trim = (n) => String(Number(n.toFixed(2)));

/** "+$22.50" / "-$10" / "+0.91% of bankroll" / "" when there is no figure. */
export function signedMoney(units, sizing = getSizing()) {
  if (!isNum(units)) return "";
  if (sizing.mode === "percent") {
    const share = units * sizing.pct;
    return `${share > 0 ? "+" : share < 0 ? "-" : ""}${trim(Math.abs(share))}% of bankroll`;
  }
  const usd = units * sizing.unit_usd;
  const shown = Number(Math.abs(usd).toFixed(2));
  const body = Number.isInteger(shown) ? shown.toLocaleString("en-US") : shown.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${usd > 0 && shown !== 0 ? "+" : usd < 0 && shown !== 0 ? "-" : ""}$${body}`;
}

/** What a stake of `units` is: "$50" or "2% of bankroll". (unitsize.js `stakeWords`, kept here so a card imports one module.) */
export { stakeWords } from "./unitsize.js";
