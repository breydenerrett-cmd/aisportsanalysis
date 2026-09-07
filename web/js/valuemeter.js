/**
 * VALUE METER -- the shared two-bar primitive that visualizes one price
 * verdict's core comparison: the de-vigged MARKET-IMPLIED PROBABILITY
 * (the consensus board's own fair share, with the vig removed) against the
 * PROBABILITY THE READER'S OWN PRICE IMPLIES (plain arithmetic on the
 * American price itself, no forecast involved). Used identically on the
 * Top Opportunities cards (web/js/opportunities.js), inside Bet Check's
 * price-verdict block (web/js/betcheck.js) and on the Game screen's MODEL
 * vs MARKET panel (web/js/games.js) -- ONE definition, not three forks.
 *
 * HONESTY BOUNDARY (read before touching this file)
 * -------------------------------------------------------------------
 * Both bars plot numbers the API already computed
 * (`price_verdict.market_implied_probability` /
 * `price_verdict.stated_implied_probability`) -- this module derives
 * nothing except the bar WIDTH (a linear percentage of an existing
 * fraction) and the gap sentence (a plain subtraction of two numbers the
 * payload already carries, in the same "points" unit
 * `src/analysis/priceverdict.py`'s `value_points` already uses). It never
 * computes a probability, an edge, or a rank, and it never renders
 * `word` as anything other than the payload's own verbatim string on the
 * caller's own chip -- this module does not paint a verdict chip itself.
 *
 * A missing input renders `notYetAvailable`, never a zero-width bar
 * pretending to be a real 0% reading.
 */

import { el, notYetAvailable } from "./dom.js";

function pct(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  return Math.max(0, Math.min(100, fraction * 100));
}

function bar(label, fraction, tone) {
  const row = el("div", { class: "vmeter-row" });
  row.appendChild(el("div", { class: "vmeter-row__label", text: label }));
  const track = el("div", { class: "vmeter-row__track" });
  const width = pct(fraction);
  if (width === null) {
    track.appendChild(el("span", { class: "vmeter-row__empty", text: "NOT AVAILABLE" }));
  } else {
    const fill = el("span", { class: `vmeter-row__fill vmeter-row__fill--${tone}` });
    fill.style.width = `${width.toFixed(1)}%`;
    track.appendChild(fill);
  }
  row.appendChild(track);
  row.appendChild(el("div", { class: "vmeter-row__figure" },
    [width === null
      ? el("span", { class: "vmeter-row__na", text: "—" })
      : el("span", { text: `${width.toFixed(1)}%` })]));
  return row;
}

/**
 * @param {object} args
 *   marketImplied  fraction (0-1) or null -- de-vigged consensus share
 *   priceImplied   fraction (0-1) or null -- the stated price's own implied share
 *   valuePoints    number (points, market minus price) or null -- when
 *                   omitted, this module computes the same subtraction
 *                   itself from the two fractions above (never a new
 *                   figure -- identical math to
 *                   src/analysis/priceverdict.py's value_points)
 *   word           the payload's own verdict word string, for the caption
 *                   framing only -- never rendered as a chip here
 */
export function renderValueMeter({ marketImplied, priceImplied, valuePoints, word } = {}) {
  const wrap = el("div", { class: "vmeter", "data-hook": "value-meter" });

  if (typeof marketImplied !== "number" && typeof priceImplied !== "number") {
    wrap.appendChild(notYetAvailable(
      "No de-vigged market-implied probability and no priceable stated price for this side.",
      "NO PRICE DATA"));
    return wrap;
  }

  wrap.appendChild(bar("MARKET-IMPLIED PROBABILITY (de-vigged consensus)", marketImplied, "market"));
  wrap.appendChild(bar("PROBABILITY YOUR PRICE IMPLIES", priceImplied, "price"));

  const gap = typeof valuePoints === "number"
    ? valuePoints
    : (typeof marketImplied === "number" && typeof priceImplied === "number"
      ? Math.round((marketImplied - priceImplied) * 100 * 100) / 100
      : null);

  if (gap === null) {
    wrap.appendChild(el("p", { class: "vmeter-gap vmeter-gap--na", "data-hook": "value-meter-gap",
      text: "Gap not computable — one side of the comparison is missing." }));
  } else {
    const better = gap > 0;
    const flat = Math.abs(gap) < 0.05;
    const gapText = flat
      ? "Priced right at fair — no measurable gap either way."
      : `${better ? "+" : ""}${gap.toFixed(1)} pts ${better ? "better" : "worse"} than fair`;
    wrap.appendChild(el("p", {
      class: `vmeter-gap ${flat ? "vmeter-gap--flat" : (better ? "vmeter-gap--better" : "vmeter-gap--worse")}`,
      "data-hook": "value-meter-gap", text: gapText,
    }));
  }

  wrap.appendChild(el("p", { class: "vmeter-caption", text:
    "A likely winner at a bad price is still a bad price; an underdog can be value when the price "
    + "implies less than the market's own fair probability." }));

  if (word) {
    wrap.appendChild(el("p", { class: "vmeter-word-note", "data-hook": "value-meter-word",
      text: `Verdict on this comparison: ${word}` }));
  }

  return wrap;
}
