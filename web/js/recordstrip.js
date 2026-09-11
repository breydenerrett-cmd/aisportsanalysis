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
  // AN EMPTY WINDOW RENDERS NOTHING, 2026-09-10.
  //
  // It used to render a panel reading NO DATA over "No paper positions
  // recorded in this window." TODAY is the empty one on most evenings --
  // nothing has settled yet -- and it is the FIRST cell, so #/today opened
  // on the words NO DATA with the real seven- and thirty-day records
  // underneath it.
  //
  // Nothing is concealed by dropping it: a window with no settled positions
  // has no record to report, and an empty box announcing that is worse than
  // no box. The windows that HAVE results still show them, and if none does
  // the caller says so once instead of three times.
  if (!window) return null;
  const cell = el("div", { class: "rec-cell panel chamfer", "data-hook": "record-window" });
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
 * THE CARD'S OWN RECORD -- GET /card/record. For the picks page.
 *
 * WHY THIS EXISTS SEPARATELY FROM `renderRecordStrip` BELOW, WHICH IS THE
 * WHOLE POINT.
 *
 * #/today mounted the /record strip directly above TONIGHT'S CARD. On
 * 2026-09-10 that read "LAST 7 DAYS 102-77-0 · +28.30u · +15.8%" and "LAST
 * 30 DAYS 143-97-3 · +47.48u · +19.8%", and immediately underneath it, three
 * published picks.
 *
 * Those numbers are not the card's. They are the forward-test detector
 * systems' paper results -- 243 settled positions from a different selection
 * rule entirely. THE CARD'S record on that date was zero days, zero bets,
 * zero wins, zero losses, because the card had been built that morning and
 * nothing had been graded yet.
 *
 * A caption said "Our forward-test systems only". That is true and it is not
 * enough: a reader who sees +19.8% above three picks attributes +19.8% to
 * the picks, and no amount of small type under it undoes that. The owner's
 * question -- "do we have a record keeping page with data truly being
 * recorded for our picks" -- is exactly the question that number answers
 * wrongly.
 *
 * So the picks page shows the PICKS' record, and when there isn't one it
 * says so in one line. An empty record honestly stated is worth more than a
 * good number that belongs to something else; it is also the only version
 * that stays true tomorrow.
 */
export async function renderCardRecordStrip(container) {
  const strip = el("div", { class: "rec-strip", "data-hook": "card-record-strip" });
  container.appendChild(strip);

  let rec;
  try {
    rec = await apiGet("/card/record");
  } catch (err) {
    renderError(strip, err);
    return strip;
  }
  clear(strip);

  const days = Number(rec && rec.days) || 0;
  if (!days) {
    strip.appendChild(el("p", { class: "rec-cell__empty", "data-hook": "card-record-none",
      text: "No graded cards yet. Every card is settled the morning after it "
          + "runs — win or lose — and this fills in from the first one." }));
    return strip;
  }

  const cells = el("div", { class: "rec-strip__cells" });
  const cell = el("div", { class: "rec-cell panel chamfer", "data-hook": "card-record-window" });
  cell.appendChild(el("div", { class: "rec-cell__label",
    text: `EVERY CARD${rec.since ? ` SINCE ${rec.since}` : ""}` }));

  const record = `${rec.wins || 0}-${rec.losses || 0}-${rec.pushes || 0}`;
  const units = unitsFmt(rec.profit_units);
  const pct = pctFmt(typeof rec.roi_pct === "number" ? rec.roi_pct / 100 : null);
  const tone = (rec.profit_units || 0) > 0 ? "--pos"
    : (rec.profit_units || 0) < 0 ? "--neg" : "";

  const fig = el("div", { class: "rec-cell__figure", "data-hook": "card-record-figure" });
  fig.appendChild(el("span", { class: "rec-cell__record", text: record }));
  if (units !== null) {
    fig.appendChild(el("span", { class: "rec-cell__sep", "aria-hidden": "true", text: "·" }));
    fig.appendChild(el("span", { class: `rec-cell__units${tone}`, text: units }));
  }
  if (pct !== null) {
    fig.appendChild(el("span", { class: "rec-cell__sep", "aria-hidden": "true", text: "·" }));
    fig.appendChild(el("span", { class: `rec-cell__pct${tone}`, text: pct }));
  }
  cell.appendChild(fig);
  cells.appendChild(cell);
  strip.appendChild(cells);

  // THE CHAIN, NAMED ON THE PAGE THAT SHOWS THE NUMBER. A tamper-evident
  // ledger nobody is told about is just a file.
  strip.appendChild(el("p", { class: "rec-strip__note", "data-hook": "card-record-note",
    text: `${days} graded card${days === 1 ? "" : "s"}, every pick frozen `
        + `before first pitch. `
        + (rec.chain_ok === false
             ? "The ledger's hash chain does NOT verify — treat these numbers "
               + "as unconfirmed until that is resolved."
             : "The ledger's hash chain verifies.") }));
  return strip;
}

/**
 * Fetches GET /record and renders the three-cell strip into `container`.
 * Never throws -- a fetch failure renders dom.js's own error treatment
 * inside the strip rather than blanking whatever screen mounted it.
 *
 * THIS IS THE FORWARD-TEST SYSTEMS' PAPER RECORD, NOT THE CARD'S. It belongs
 * on #/performance, where it sits among the other research surfaces and its
 * caption has context. It must not be mounted on the picks page -- see
 * `renderCardRecordStrip` above for what happened when it was.
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
  const rendered = [payload.today, payload.last_7, payload.last_30]
    .map(windowCell)
    .filter(Boolean);
  for (const cell of rendered) cells.appendChild(cell);
  // Every window empty is a real state -- a brand-new deploy, or a season
  // break -- and it gets ONE honest line rather than three identical empty
  // panels.
  if (!rendered.length) {
    cells.appendChild(el("p", { class: "rec-cell__empty", "data-hook": "record-none",
      text: "Nothing settled yet — the record starts with the first graded card." }));
  }
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
