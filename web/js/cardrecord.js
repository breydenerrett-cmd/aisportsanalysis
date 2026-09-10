/**
 * THE RECORD (#/record-card, GET /card/record + GET /card/history) --
 * every card this product has ever published, including the ones that
 * lost, chained by hash so the page cannot flatter itself. "Picks with
 * receipts" is the whole pitch; this page is the receipts, not a summary
 * of them.
 *
 * WHY THIS IS A SEPARATE PAGE FROM web/js/card.js's recordLine()
 * -------------------------------------------------------------------
 * card.js's recordLine() is the one-paragraph pooled summary that sits
 * directly under tonight's picks, on purpose: a reader checking tonight's
 * bets should not have to scroll through a ledger first. This page IS the
 * ledger -- the same pooled totals, plus the day-by-day detail and the
 * hash-chain status neither surface needs for that one-paragraph job.
 * Reachable from that summary and from the site footer (see card.js's
 * recordLine and meta.js's renderDisclaimerFooter), never from the primary
 * nav -- it is a receipt a reader is sent to verify, not a sixth
 * destination competing with TODAY/GAMES/CHECK/ODDS/BETS/RESULTS.
 *
 * WHAT IT WILL NOT DO
 * -------------------------------------------------------------------
 * Same rules as THE CARD itself (card.js's own docstring): no "nothing
 * clears the bar", no de-vig/bps/closing-line jargon
 * (tests/test_no_nothing_clears_the_bar.py enforces this across all of
 * web/), and nothing here claims an edge or a positive expected value --
 * the disclaimer rendered near the bottom of this page is
 * `daily_card.CARD_DISCLAIMER` verbatim (GET /card/record's `disclaimer`
 * field), never a second hand-written sentence that could drift from it.
 *
 * LOSSES AND VOIDS GET NO SMALLER A TYPEFACE THAN WINS. The headline W-L-P
 * is one string in one size and one colour -- see headline() below -- and
 * voidsNote() is rendered unconditionally, not only when there happen to
 * be voids. A record that renders its wins bigger, or that only mentions
 * a postponed game when convenient, is a record making an argument
 * instead of publishing one.
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading, notYetAvailable, formatAmerican } from "./dom.js";
import { bookLabel } from "./labels.js";

// GET /card/history's own default (api/card.py's DEFAULT_HISTORY_LIMIT) --
// kept in sync by eye rather than fetched, since it only ever changes the
// FIRST page's size and the payload's own `truncated`/`total_days` are
// what this page actually reads to decide what to say about it.
const HISTORY_LIMIT = 60;

const RESULT_CHIP = {
  WIN: { text: "WIN", cls: "day-settle--win" },
  LOSS: { text: "LOSS", cls: "day-settle--loss" },
  PUSH: { text: "PUSH", cls: "day-settle--push" },
  // VOID has no equivalent on the paper ledger's own day-settle chips
  // (screens.css) -- a postponed game, not an undecided position. See
  // card.css's own .day-settle--void rule for why it reads grey, not
  // amber.
  VOID: { text: "VOID", cls: "day-settle--void" },
};

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

function unitsFmt(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}u`;
}

/** `roi_pct` arrives already scaled to a percentage (card_ledger.record's
 * `round(profit / staked * 100.0, 3)`) -- this formats it, it does not
 * rescale it. A second `* 100` here would quietly turn -9.7% into -970%,
 * which is exactly the kind of invented number this product cannot print. */
function roiFmt(pct) {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return null;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

/** `win_rate` arrives as a 0..1 fraction -- this one DOES scale, once. */
function winRateFmt(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  return `${(fraction * 100).toFixed(1)}%`;
}

/** "Sunday, Sep 7, 2026", from a bare YYYY-MM-DD read in UTC -- same
 * convention dayrecap.js's dayDateLabel uses for the paper ledger's own
 * calendar dates. Falls back to the raw ISO string rather than a guess. */
function dayDateLabel(dateIso) {
  if (!dateIso) return null;
  const d = new Date(`${dateIso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC", weekday: "long", month: "short", day: "numeric", year: "numeric",
  }).format(d);
}

/* ---------------------------------------------------------------------
 * Headline -- W-L-P, win rate, units, ROI, days. One size, one weight,
 * for every figure here (see this module's own docstring).
 * ------------------------------------------------------------------- */

function figure(text, tone) {
  return el("span", { class: `crp-stat__figure${tone ? ` crp-stat__figure--${tone}` : ""}`, text: text || "—" });
}

function absentFigure() {
  return el("span", { class: "crp-stat__figure crp-stat__figure--absent", text: "—" });
}

function statTile(label, valueNode) {
  const tile = el("div", { class: "crp-stat" });
  tile.appendChild(el("span", { class: "crp-stat__label", text: label }));
  tile.appendChild(el("div", { class: "crp-stat__value" }, [valueNode]));
  return tile;
}

function headline(record) {
  const wrap = el("div", { class: "crp-headline panel chamfer", "data-hook": "record-headline" });
  const grid = el("div", { class: "crp-stats" });

  const staked = typeof record.n_staked === "number" ? record.n_staked : 0;
  const decided = staked > 0;

  // ONE STRING. Wins and losses are two numbers inside the same span, at
  // the same size, in the same colour -- never two separately-tinted
  // figures where one could end up visually louder than the other.
  const wlp = `${record.wins ?? 0}-${record.losses ?? 0}-${record.pushes ?? 0}`;
  grid.appendChild(statTile("RECORD (W-L-P)", figure(wlp)));
  grid.appendChild(statTile("VOIDS", figure(String(record.voids || 0), record.voids ? "warn" : null)));
  grid.appendChild(statTile("WIN RATE", decided ? figure(winRateFmt(record.win_rate)) : absentFigure()));
  grid.appendChild(statTile("UNITS NET", decided
    ? figure(unitsFmt(record.profit_units), record.profit_units > 0 ? "pos" : record.profit_units < 0 ? "neg" : null)
    : absentFigure()));
  grid.appendChild(statTile("ROI", decided
    ? figure(roiFmt(record.roi_pct), record.roi_pct > 0 ? "pos" : record.roi_pct < 0 ? "neg" : null)
    : absentFigure()));
  grid.appendChild(statTile("DAYS SETTLED", figure(String(record.days || 0))));

  wrap.appendChild(grid);
  return wrap;
}

/** Rendered UNCONDITIONALLY -- whether there are zero voids or forty, the
 * reader is told which. Silence is not one of the honest options here. */
function voidsNote(record) {
  const n = record.voids || 0;
  const text = n
    ? `${n} pick${n === 1 ? "" : "s"} could not be graded — the game was postponed, or no final score is on `
      + `file for it. ${n === 1 ? "It counts" : "They count"} as neither a win nor a loss, and `
      + `${n === 1 ? "is" : "are"} left out of the win rate, units and ROI above.`
    : "No pick has gone ungraded so far — every settled pick has resolved to a win, a loss or a push.";
  return el("p", { class: "crp-voids", "data-hook": "record-voids-note", text });
}

/* ---------------------------------------------------------------------
 * Hash-chain status, in plain English.
 * ------------------------------------------------------------------- */

function chainStatus(record) {
  const wrap = el("section", { class: "crp-chain panel chamfer", "data-hook": "record-chain" });
  wrap.appendChild(el("span", { class: "crp-chain__label", text: "TAMPER-EVIDENT LEDGER" }));

  const rowsChecked = typeof record.rows_checked === "number" ? record.rows_checked : 0;
  if (!rowsChecked) {
    wrap.appendChild(el("p", { class: "crp-chain__body",
      text: "Nothing has been written to the record yet, so there is no chain to verify. The first published "
          + "card starts it." }));
    return wrap;
  }

  if (record.chain_ok) {
    wrap.appendChild(el("p", { class: "crp-chain__body",
      text: `Every card we have published or graded is written into one append-only file — ${rowsChecked} `
          + `entr${rowsChecked === 1 ? "y" : "ies"} so far — each one linked by a hash to the entry before it. `
          + "Edit or delete any past entry, even one line, and every link after it breaks. That chain verifies "
          + "right now: nothing below has been changed after the fact." }));
  } else {
    wrap.appendChild(el("p", { class: "crp-chain__warn",
      text: "This record's tamper-evident chain does NOT currently verify. Treat every figure on this page as "
          + "unconfirmed until it does." }));
    if (record.chain_detail) {
      const disclosure = el("details", { class: "crp-chain__detail" });
      disclosure.appendChild(el("summary", { text: "Technical detail" }));
      disclosure.appendChild(el("p", { text: record.chain_detail }));
      wrap.appendChild(disclosure);
    }
  }
  return wrap;
}

/* ---------------------------------------------------------------------
 * Day-by-day table -- every pick, what it was, what happened, what it
 * returned.
 * ------------------------------------------------------------------- */

function pickRow(pick) {
  const tr = el("tr", { "data-hook": "record-pick-row" });

  const betCell = el("td", { class: "crp-pick-bet" });
  betCell.appendChild(el("span", { class: "crp-pick-bet__text", text: pick.bet || "—" }));
  if (pick.label) betCell.appendChild(el("span", { class: "crp-pick-bet__label", text: pick.label }));
  tr.appendChild(betCell);

  const chip = RESULT_CHIP[pick.result] || { text: pick.result || "UNKNOWN", cls: "day-settle--pending" };
  const resultCell = el("td", { class: "crp-pick-result" });
  resultCell.appendChild(el("span", { class: `day-settle ${chip.cls}`, "data-hook": "record-pick-outcome", text: chip.text }));
  if (pick.result === "VOID" && pick.reason) {
    // The API's own words, verbatim -- never paraphrased, same rule
    // dom.js's renderError follows for a server-supplied detail string.
    resultCell.appendChild(el("p", { class: "crp-pick-reason", text: pick.reason }));
  } else if (typeof pick.away_score === "number" && typeof pick.home_score === "number") {
    resultCell.appendChild(el("p", { class: "crp-pick-score",
      text: `${pick.away_team || "AWAY"} ${pick.away_score} — ${pick.home_team || "HOME"} ${pick.home_score}` }));
  }
  tr.appendChild(resultCell);

  tr.appendChild(el("td", { text: formatAmerican(pick.price) || "—" }));

  const bookText = pick.book
    ? `${bookLabel(pick.book) || pick.book}${pick.books ? ` · best of ${pick.books}` : ""}`
    : "—";
  tr.appendChild(el("td", { text: bookText }));

  // A VOID pick returns nothing either way -- printing "0.00u" beside it
  // would read as "graded, broke even" rather than "never graded", so it
  // gets the same em-dash the rest of this client uses for an absent
  // figure instead of a fabricated zero.
  const retText = pick.result === "VOID" ? null : unitsFmt(pick.profit_units);
  const retTone = typeof pick.profit_units === "number" && pick.result !== "VOID"
    ? (pick.profit_units > 0 ? " crp-figure--pos" : pick.profit_units < 0 ? " crp-figure--neg" : "")
    : "";
  tr.appendChild(el("td", { class: retTone.trim() || null, text: retText || "—" }));
  return tr;
}

function dayBlock(day) {
  const card = el("article", { class: "crp-day panel chamfer", "data-hook": "record-day" });

  const head = el("div", { class: "crp-day__head" });
  head.appendChild(el("span", { class: "crp-day__date", text: dayDateLabel(day.date) || day.date }));
  // Same W-L-P shape as the headline above, always three numbers -- a day
  // row reading "1-1" beside a headline reading "1-1-0" looks like a
  // mismatch even though neither is wrong.
  head.appendChild(el("span", { class: "crp-day__record",
    text: `${day.wins}-${day.losses}-${day.pushes || 0}` }));
  if (day.voids) {
    head.appendChild(el("span", { class: "crp-day__voids", "data-hook": "record-day-voids",
      text: `${day.voids} void${day.voids === 1 ? "" : "s"}` }));
  }
  const net = unitsFmt(day.profit_units);
  if (net !== null) {
    const tone = day.profit_units > 0 ? "crp-day__net--pos" : day.profit_units < 0 ? "crp-day__net--neg" : "";
    head.appendChild(el("span", { class: `crp-day__net ${tone}`.trim(), text: net }));
  }
  card.appendChild(head);

  const wrap = el("div", { class: "ov2-table-wrap" });
  const table = el("table", { class: "ov2-table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of ["BET", "RESULT", "PRICE", "BOOK", "RETURN"]) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const pick of day.picks || []) tbody.appendChild(pickRow(pick));
  table.appendChild(tbody);
  wrap.appendChild(table);
  card.appendChild(wrap);

  // THE RECEIPT. The published row's own hash -- what was claimed, before
  // the games started, provably unedited since. Not the settled row's own
  // hash (a second, different value) -- see card_ledger.history's
  // docstring on why the two are not the same thing.
  card.appendChild(el("p", { class: "crp-day__hash", "data-hook": "record-day-hash",
    text: `Published receipt hash: ${day.published_row_hash || "unavailable"}` }));
  return card;
}

/* ---------------------------------------------------------------------
 * Empty state -- honest, and not hidden. Nothing graded yet is a TRUE,
 * ordinary state for a brand-new record, not a fault to paper over.
 * ------------------------------------------------------------------- */

function emptyRecord() {
  const wrap = el("section", { class: "gutter", "data-hook": "record-empty" });
  const panel = el("div", { class: "panel chamfer card2empty" });
  panel.appendChild(el("span", { class: "card2empty__label", text: "NOTHING SETTLED YET" }));
  panel.appendChild(el("p", { class: "card2empty__body",
    text: "Nothing has been graded yet. Every card is settled the morning after it runs, win or lose, and this "
        + "page fills in from the first settled day on — including the days it loses." }));
  const actions = el("div", { class: "card2empty__actions" });
  actions.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn",
    href: "#/today", text: "SEE TONIGHT'S CARD" }));
  panel.appendChild(actions);
  wrap.appendChild(panel);
  return wrap;
}

/* ---------------------------------------------------------------------
 * View
 * ------------------------------------------------------------------- */

export async function renderCardRecord(container) {
  clear(container);
  const screen = el("div", { class: "screen crp-screen", "data-view": "record-card" });
  container.appendChild(screen);
  screen.appendChild(renderLoading("LOADING THE RECORD"));

  let record;
  let history;
  try {
    [record, history] = await Promise.all([
      apiGet("/card/record"),
      apiGet(`/card/history?limit=${HISTORY_LIMIT}`),
    ]);
  } catch (err) {
    clear(screen);
    renderError(screen, err);
    return;
  }
  clear(screen);

  screen.appendChild(sectionHead("THE RECORD", "EVERY CARD WE HAVE EVER PUBLISHED"));
  screen.appendChild(el("p", { class: "crp-intro",
    text: "Every pick this product has made, frozen before the result was known and chained so none of it can "
        + "be quietly edited afterward — the wins and the losses both." }));

  const nothingSettled = !record.days;
  if (nothingSettled) {
    screen.appendChild(chainStatus(record));
    screen.appendChild(emptyRecord());
  } else {
    screen.appendChild(headline(record));
    screen.appendChild(voidsNote(record));
    screen.appendChild(chainStatus(record));

    const days = (history && history.days) || [];
    const tableSection = el("section", { class: "crp-days", "data-hook": "record-days" });
    const metaBits = history && history.truncated
      ? `${days.length} OF ${history.total_days} DAYS`
      : `${days.length} DAY${days.length === 1 ? "" : "S"}`;
    tableSection.appendChild(sectionHead("DAY BY DAY", metaBits));
    if (days.length === 0) {
      // Defensive only -- record.days > 0 here means the pooled total says
      // settled days exist, so an empty history list is the two endpoints
      // disagreeing, not a real "nothing yet" state. Said plainly rather
      // than silently falling back to the empty-record panel above, which
      // would claim nothing has settled when the pooled total says
      // otherwise.
      tableSection.appendChild(notYetAvailable(
        "The pooled record above has settled days on it, but the day-by-day detail did not load with them.",
        "NO DAY DETAIL"));
    } else {
      for (const day of days) tableSection.appendChild(dayBlock(day));
    }
    screen.appendChild(tableSection);
  }

  if (record.disclaimer) {
    screen.appendChild(el("p", { class: "crp-disclaimer", "data-hook": "record-disclaimer", text: record.disclaimer }));
  }
}
