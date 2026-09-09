/**
 * RECORD STRIP -- TODAY / LAST 7 DAYS / LAST 30 DAYS (GET /record,
 * src/report/daily_record.py's record_strip). Mounted at the top of both
 * #/today (above the hero) and #/performance (above the existing paper
 * standings content) -- see web/js/today.js and web/js/performance.js's
 * own call sites.
 *
 * HONESTY BOUNDARY -- a window's `units_net`/`return_on_units` are NULL
 * whenever nothing in it has settled yet (every position in the window
 * is still pending, e.g. TODAY on a live slate). This module never
 * substitutes a zero for that null: it prints the real W-L-P counts
 * (0-0-0 when nothing has settled) plus the pending count and stops --
 * see src/report/daily_record.py's own `_window` docstring, which this
 * file's copy is deliberately a plain restatement of, never a paraphrase
 * that could drift from what the number actually means.
 */

import { apiGet } from "./api.js";
import { el, clear, renderError } from "./dom.js";

function pctFmt(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  return `${fraction > 0 ? "+" : ""}${(fraction * 100).toFixed(1)}%`;
}

function unitsFmt(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}u`;
}

function windowCell(window) {
  const cell = el("div", { class: "rec-cell panel chamfer", "data-hook": "record-window" });
  if (!window) {
    cell.appendChild(el("div", { class: "rec-cell__label", text: "NO DATA" }));
    cell.appendChild(el("p", { class: "rec-cell__empty",
      text: "No paper positions recorded in this window." }));
    return cell;
  }
  cell.appendChild(el("div", { class: "rec-cell__label", text: window.label || "" }));
  const record = `${window.wins}-${window.losses}-${window.pushes}`;
  const units = unitsFmt(window.units_net);
  const pct = pctFmt(window.return_on_units);
  if (units !== null && pct !== null) {
    const tone = window.units_net > 0 ? "--pos"
      : window.units_net < 0 ? "--neg" : "";
    // Kept as one data-hook="record-window-figure" text node (unchanged
    // contract for anything reading its full text), but built from three
    // child spans so units/return can carry the win/loss colour while the
    // W-L-P record itself stays neutral -- the record is a count, not a
    // gain or a loss.
    const fig = el("div", { class: "rec-cell__figure", "data-hook": "record-window-figure" });
    fig.appendChild(el("span", { class: "rec-cell__record", text: record }));
    fig.appendChild(el("span", { class: "rec-cell__sep", "aria-hidden": "true", text: "·" }));
    fig.appendChild(el("span", { class: `rec-cell__units${tone}`, text: units }));
    fig.appendChild(el("span", { class: "rec-cell__sep", "aria-hidden": "true", text: "·" }));
    fig.appendChild(el("span", { class: `rec-cell__pct${tone}`, text: pct }));
    cell.appendChild(fig);
  } else {
    const fig = el("div", { class: "rec-cell__figure", "data-hook": "record-window-figure" });
    fig.appendChild(el("span", { class: "rec-cell__record", text: record }));
    cell.appendChild(fig);
    cell.appendChild(el("p", { class: "rec-cell__pending", "data-hook": "record-window-pending",
      text: `${window.pending} pending, nothing settled yet` }));
  }
  return cell;
}

/**
 * Fetches GET /record and renders the three-cell strip into `container`.
 * Never throws -- a fetch failure renders dom.js's own error treatment
 * inside the strip rather than blanking whatever screen mounted it.
 */
export async function renderRecordStrip(container) {
  const strip = el("div", { class: "rec-strip", "data-hook": "record-strip" });
  container.appendChild(strip);

  let payload;
  try {
    payload = await apiGet("/record");
  } catch (err) {
    renderError(strip, err);
    return strip;
  }
  clear(strip);

  const cells = el("div", { class: "rec-strip__cells" });
  cells.appendChild(windowCell(payload.today));
  cells.appendChild(windowCell(payload.last_7));
  cells.appendChild(windowCell(payload.last_30));
  strip.appendChild(cells);

  // Named explicitly (2026-09-09): before this the windows above pooled
  // CONTROL and MARKET_REFERENCE in beside the product's own picks -- on the
  // real ledger that was roughly 90% of what the number actually was. The
  // filter changed what these tiles mean; the caption has to say so, not
  // just the number quietly getting better.
  strip.appendChild(el("p", { class: "rec-strip__note", "data-hook": "record-strip-note",
    text: `Our forward-test systems only — not the null baselines or the market-reference republishers. `
        + `Paper results, flat 1-unit stakes. Settled through ${payload.settled_through || "not yet available"}.` }));

  return strip;
}
