/**
 * RUN LINE AND TOTAL -- the prices block on the game page.
 *
 * Reads `markets.spreads` and `markets.totals` from one game's entry in GET
 * /odds/{date} (src/analysis/runline_totals.py). Those keys exist only when the
 * server's RUNLINE_TOTALS switch is on (docs/decisions/RUNLINE_TOTALS.md); with
 * it off the entry carries h2h only and this module returns null, so the page
 * shows nothing new -- never an empty box, never a placeholder.
 *
 * WHAT IT SHOWS, PER MARKET: the main line (the one most books hang), the best
 * price on each side at that line with the book(s) quoting it, the de-vigged
 * fair price when at least six books quote that line, and how many books are at
 * the line. Books on a different line are counted, not mixed in: a best price
 * across different lines is not a best price.
 *
 * EVERY PRICE HERE IS A PRE-GAME CAPTURE. Once the game has started the block
 * says LAST PRE-GAME PRICE with the capture time (livestate.js's one wording).
 */

import { el, formatAmerican, formatEasternClock, notYetAvailable } from "./dom.js";
import { bookLabel } from "./labels.js";
import { pregameLabel } from "./livestate.js";

/** "+1.5" / "-1.5" / "7.5" (a total has no sign). */
export function formatLine(value, { signed = true } = {}) {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return null;
  const text = Number.isInteger(n) ? n.toFixed(1) : String(n);
  return signed && n > 0 ? `+${text}` : text;
}

function booksText(books) {
  return (books || []).map(bookLabel).join(", ");
}

function sideModel(label, best, fair, lineText) {
  return {
    label,
    line: lineText,
    price: best ? formatAmerican(best.price) : null,
    books: best ? booksText(best.books) : null,
    fair: fair && typeof fair.implied_price === "number" ? formatAmerican(fair.implied_price) : null,
  };
}

function otherLinesText(section, key, signed) {
  return (section.other_lines || []).map((o) => {
    const line = formatLine(o[key], { signed });
    const n = o.books;
    return line ? `${line} (${n} book${n === 1 ? "" : "s"})` : null;
  }).filter(Boolean);
}

/** The block's data, or null when the entry carries no run line / total keys
 * (switch off). Pure: no DOM. */
export function lineMarketsModel(entry) {
  const markets = (entry && entry.markets) || {};
  const spreads = markets.spreads;
  const totals = markets.totals;
  if (!spreads && !totals) return null;

  const out = { observedUtc: null, markets: [] };
  const seen = [];

  if (spreads) {
    if (!spreads.board_available) {
      out.markets.push({ key: "runline", title: "RUN LINE", reason: spreads.reason || "No run line recorded." });
    } else {
      const main = spreads.main_line || {};
      const cons = spreads.consensus || {};
      out.markets.push({
        key: "runline", title: "RUN LINE", reason: null,
        sides: [
          sideModel(entry.away_team, spreads.best && spreads.best.away, cons.away, formatLine(main.away)),
          sideModel(entry.home_team, spreads.best && spreads.best.home, cons.home, formatLine(main.home)),
        ],
        booksAtLine: spreads.books_at_main_line,
        otherLines: otherLinesText(spreads, "home_line", true),
        fairNote: spreads.consensus ? null : spreads.consensus_unavailable_reason || null,
      });
      if (spreads.staleness && spreads.staleness.observed_utc) seen.push(spreads.staleness.observed_utc);
    }
  }

  if (totals) {
    if (!totals.board_available) {
      out.markets.push({ key: "total", title: "TOTAL", reason: totals.reason || "No total recorded." });
    } else {
      const main = totals.main_line || {};
      const cons = totals.consensus || {};
      const line = formatLine(main.total, { signed: false });
      out.markets.push({
        key: "total", title: "TOTAL", reason: null,
        sides: [
          sideModel("OVER", totals.best && totals.best.over, cons.over, line),
          sideModel("UNDER", totals.best && totals.best.under, cons.under, line),
        ],
        booksAtLine: totals.books_at_main_line,
        otherLines: otherLinesText(totals, "total", false),
        fairNote: totals.consensus ? null : totals.consensus_unavailable_reason || null,
      });
      if (totals.staleness && totals.staleness.observed_utc) seen.push(totals.staleness.observed_utc);
    }
  }

  out.observedUtc = seen.length ? seen.sort().slice(-1)[0] : null;
  return out;
}

function sideColumn(side) {
  const col = el("div", { class: "lm-side", "data-hook": "line-side" });
  col.appendChild(el("div", { class: "lm-side__label",
    text: side.line ? `${side.label} ${side.line}` : String(side.label) }));
  col.appendChild(el("div", { class: "lm-side__price", "data-hook": "line-best-price",
    text: side.price || "—" }));
  if (side.books) col.appendChild(el("div", { class: "lm-side__books", text: side.books }));
  if (side.fair) col.appendChild(el("div", { class: "lm-side__fair", text: `fair price ${side.fair}` }));
  return col;
}

/** The prices block element, or null when there is nothing to show.
 * `live` is the game's live row (or null): a started game's block carries the
 * last-pregame label with the capture time. */
export function renderLineMarkets(entry, live) {
  const model = lineMarketsModel(entry);
  if (!model) return null;
  const panel = el("section", { class: "lm panel chamfer", "data-hook": "line-markets" });
  panel.appendChild(el("div", { class: "lm__eyebrow", text: "PRICES · RUN LINE & TOTAL" }));
  const label = pregameLabel(live, model.observedUtc);
  if (label) {
    panel.appendChild(el("p", { class: "pregame-label", "data-hook": "pregame-label", text: label }));
  } else if (model.observedUtc) {
    const clock = formatEasternClock(model.observedUtc);
    if (clock) panel.appendChild(el("p", { class: "lm__captured", text: `CAPTURED ${clock}` }));
  }

  const cols = el("div", { class: "lm__cols" });
  for (const market of model.markets) {
    const block = el("div", { class: "lm__market", "data-hook": `line-${market.key}` });
    block.appendChild(el("div", { class: "lm__title", text: market.title }));
    if (market.reason) {
      block.appendChild(notYetAvailable(market.reason, "NO BOARD"));
    } else {
      const sides = el("div", { class: "lm__sides" });
      for (const side of market.sides) sides.appendChild(sideColumn(side));
      block.appendChild(sides);
      const facts = [`${market.booksAtLine} book${market.booksAtLine === 1 ? "" : "s"} at this line`];
      if (market.otherLines.length) facts.push(`also quoted: ${market.otherLines.join(", ")}`);
      block.appendChild(el("p", { class: "lm__facts", text: facts.join(" · ") }));
      if (market.fairNote) block.appendChild(el("p", { class: "lm__facts", text: market.fairNote }));
    }
    cols.appendChild(block);
  }
  panel.appendChild(cols);
  panel.appendChild(el("p", { class: "gqv-price__disclaimer",
    text: "Prices only — we take no bets. Check the number at the book." }));
  return panel;
}
