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
 * NFL IS ONE RULE AT A TIME (2026-09-20). `#/nfl/record` counts the live
 * NFL rule only and says so; `#/nfl/record?rule=NFL_CARD_V1` is the
 * retired favourites rule's own record. The two are never pooled, and
 * neither page shows MLB's props/totals panels (see renderCardRecord).
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
import { NFL_NOTICE, NFL_RETIRED_RULE } from "./sport.js";

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

/** Below this many graded picks, a sport's win rate or ROI is noise dressed
 * as a track record. Mirrors card.js's own NFL_SAMPLE_FLOOR exactly (kept
 * as a separate constant, not a shared import, because this page has no
 * existing import from card.js and one two-line constant is not worth
 * introducing a cross-file dependency for) -- NFL published and graded its
 * first pick on 2026-09-17 (n=1 today); this floor is a round, conservative
 * number, not derived from that one pick. */
const NFL_SAMPLE_FLOOR = 10;

function headline(record, sport = "mlb") {
  const wrap = el("div", { class: "crp-headline panel chamfer", "data-hook": "record-headline" });
  const grid = el("div", { class: "crp-stats" });

  const staked = typeof record.n_staked === "number" ? record.n_staked : 0;
  const decided = staked > 0;
  // SAMPLE SIZE, NOT SPIN (2026-09-19, NFL going live). A win rate or ROI
  // off a handful of NFL picks reads like a track record and is not one --
  // below the floor, those two tiles show the raw count instead of a
  // percentage, and an unmissable note states the actual sample size
  // rather than leaving a reader to notice it is tiny on their own.
  const tooSmallForARate = sport === "nfl" && staked > 0 && staked < NFL_SAMPLE_FLOOR;

  // ONE STRING. Wins and losses are two numbers inside the same span, at
  // the same size, in the same colour -- never two separately-tinted
  // figures where one could end up visually louder than the other.
  const wlp = `${record.wins ?? 0}-${record.losses ?? 0}-${record.pushes ?? 0}`;
  // GAME PICKS, not RECORD: since 2026-09-12 the card also carries player
  // props, graded apart (card_ledger.record's `by_kind`). The top-level
  // figures are the game picks alone -- the label says so, and the prop
  // record has its own panel below rather than being pooled in here.
  // NFL is one population (2026-09-20): NFL_CARD_V2 puts spreads, totals
  // and moneylines in the one `picks` list and has no props, so its count
  // is every pick, labelled as such -- see the markets note below.
  grid.appendChild(statTile(sport === "nfl" ? "ALL PICKS (W-L-P)" : "GAME PICKS (W-L-P)",
    figure(wlp)));
  grid.appendChild(statTile("VOIDS", figure(String(record.voids || 0), record.voids ? "warn" : null)));
  grid.appendChild(statTile("WIN RATE", decided && !tooSmallForARate
    ? figure(winRateFmt(record.win_rate)) : absentFigure()));
  grid.appendChild(statTile("UNITS NET", decided
    ? figure(unitsFmt(record.profit_units), record.profit_units > 0 ? "pos" : record.profit_units < 0 ? "neg" : null)
    : absentFigure()));
  grid.appendChild(statTile("ROI PER UNIT STAKED", decided && !tooSmallForARate
    ? figure(roiFmt(record.roi_pct), record.roi_pct > 0 ? "pos" : record.roi_pct < 0 ? "neg" : null)
    : absentFigure()));
  grid.appendChild(statTile("DAYS SETTLED", figure(String(record.days || 0))));

  wrap.appendChild(grid);

  if (tooSmallForARate) {
    wrap.appendChild(el("p", { class: "crp-voids", "data-hook": "record-nfl-sample-note",
      text: `NFL sample size: ${staked} pick${staked === 1 ? "" : "s"} graded. That is too few for a `
          + `win rate or ROI to mean anything -- the W-L-P count above is the whole record so far, not `
          + `a percentage.` }));
  }
  return wrap;
}

/** What the NFL headline's one count holds (2026-09-20). MLB's page splits
 * game picks, props and totals into three panels; NFL has one population,
 * so instead of those panels it gets this sentence saying so. The retired
 * rule only ever took moneylines, and its sentence says that instead. */
function nflMarketsNote(rule) {
  return el("p", { class: "crp-voids", "data-hook": "record-nfl-markets-note",
    text: rule === NFL_RETIRED_RULE
      ? "Every pick the old rule made is in this one count. It only ever took moneylines."
      : "Every NFL pick is in this one count -- spreads, totals and moneylines alike. NFL has "
        + "no player props and no separate totals record." });
}

/**
 * THE PROP RECORD, APART FROM THE GAME RECORD (2026-09-12).
 *
 * Player props joined the card today (docs/PRODUCT_DOCTRINE.md §5.3) and
 * are graded on the same ledger rows, but `card_ledger.record()` keeps the
 * two populations apart in `by_kind` and this page keeps them apart on
 * screen: a 9-3 game record must not quietly absorb prop results, and a
 * prop record must not borrow the game record's nights. Same tiles, same
 * size, same weight -- one panel under the other. Before any prop has
 * graded, the panel says exactly that instead of printing 0-0-0 as if it
 * were a result.
 */
function propHeadline(record) {
  const prop = record.by_kind && record.by_kind.prop;
  if (!prop) return null;   // an older /card/record without by_kind
  const wrap = el("div", { class: "crp-headline crp-headline--props panel chamfer",
    "data-hook": "record-prop-headline" });
  wrap.appendChild(el("span", { class: "crp-chain__label", text: "PLAYER PROPS, GRADED APART" }));
  const staked = typeof prop.n_staked === "number" ? prop.n_staked : 0;
  const graded = staked + (prop.pushes || 0) + (prop.voids || 0);
  if (!graded) {
    wrap.appendChild(el("p", { class: "crp-chain__body", "data-hook": "record-prop-none",
      text: "No player prop has graded yet. Props are on the card from 2026-09-12, frozen and graded "
          + "the same way as the game picks, and their record is kept here on its own." }));
    return wrap;
  }
  const grid = el("div", { class: "crp-stats" });
  const wlp = `${prop.wins ?? 0}-${prop.losses ?? 0}-${prop.pushes ?? 0}`;
  grid.appendChild(statTile("PROPS (W-L-P)", figure(wlp)));
  grid.appendChild(statTile("VOIDS", figure(String(prop.voids || 0), prop.voids ? "warn" : null)));
  grid.appendChild(statTile("WIN RATE", staked ? figure(winRateFmt(prop.win_rate)) : absentFigure()));
  grid.appendChild(statTile("UNITS NET", staked
    ? figure(unitsFmt(prop.profit_units), prop.profit_units > 0 ? "pos" : prop.profit_units < 0 ? "neg" : null)
    : absentFigure()));
  grid.appendChild(statTile("ROI PER UNIT STAKED", staked
    ? figure(roiFmt(prop.roi_pct), prop.roi_pct > 0 ? "pos" : prop.roi_pct < 0 ? "neg" : null)
    : absentFigure()));
  wrap.appendChild(grid);
  return wrap;
}

/**
 * THE TOTALS RECORD, APART FROM THE GAME RECORD (2026-09-14).
 *
 * Totals joined the card today (the owner's note: merge every bet, not
 * just moneylines) and are graded on the same ledger rows, but
 * `card_ledger.record()` keeps the populations apart in `by_kind` --
 * `by_kind.total` beside `by_kind.prop` -- and this page follows the same
 * rule it already follows for props: a game record must not quietly
 * absorb totals results, and a totals record must not borrow the game
 * record's nights. Same tiles, same size, same weight, same panel shape as
 * `propHeadline` right above it. Before any total has graded, the panel
 * says exactly that instead of printing 0-0-0 as if it were a result.
 */
function totalHeadline(record) {
  const total = record.by_kind && record.by_kind.total;
  if (!total) return null;   // an older /card/record without by_kind, or one before totals
  const wrap = el("div", { class: "crp-headline crp-headline--totals panel chamfer",
    "data-hook": "record-total-headline" });
  wrap.appendChild(el("span", { class: "crp-chain__label", text: "TOTALS, GRADED APART" }));
  const staked = typeof total.n_staked === "number" ? total.n_staked : 0;
  const graded = staked + (total.pushes || 0) + (total.voids || 0);
  if (!graded) {
    wrap.appendChild(el("p", { class: "crp-chain__body", "data-hook": "record-total-none",
      text: "No total has graded yet. Totals are on the card from 2026-09-14, frozen and graded "
          + "the same way as the game picks, and their record is kept here on its own." }));
    return wrap;
  }
  const grid = el("div", { class: "crp-stats" });
  const wlp = `${total.wins ?? 0}-${total.losses ?? 0}-${total.pushes ?? 0}`;
  grid.appendChild(statTile("TOTALS (W-L-P)", figure(wlp)));
  grid.appendChild(statTile("VOIDS", figure(String(total.voids || 0), total.voids ? "warn" : null)));
  grid.appendChild(statTile("WIN RATE", staked ? figure(winRateFmt(total.win_rate)) : absentFigure()));
  grid.appendChild(statTile("UNITS NET", staked
    ? figure(unitsFmt(total.profit_units), total.profit_units > 0 ? "pos" : total.profit_units < 0 ? "neg" : null)
    : absentFigure()));
  grid.appendChild(statTile("ROI PER UNIT STAKED", staked
    ? figure(roiFmt(total.roi_pct), total.roi_pct > 0 ? "pos" : total.roi_pct < 0 ? "neg" : null)
    : absentFigure()));
  wrap.appendChild(grid);
  return wrap;
}

/** WHAT A UNIT IS, defined once where a reader first meets UNITS NET and
 * ROI PER UNIT STAKED (2026-09-16). A unit is a stake size the reader
 * picks for themselves -- this page never puts a dollar figure on one
 * (see this file's own docstring: paper accounts, not real-money returns).
 * Every pick here is staked a flat 1 unit, so the arithmetic is
 * reproducible by hand: a win at -150 returns +0.67u, a win at +150
 * returns +1.5u, a loss is -1.0u. ROI PER UNIT STAKED is units won
 * divided by bets made -- a return on what was risked per bet, not a
 * bankroll figure. Someone staking 5% of a $1,000 bankroll per unit and
 * up 2.6 units is up $130, which is 13% bankroll growth, a different
 * number from the ROI above -- this page reports the first number, never
 * the second. */
/**
 * EVERYTHING TOGETHER (2026-09-16).
 *
 * The three panels above are each honest and each labelled -- game picks,
 * props, totals, kept apart so one population's win rate never borrows
 * another's. But kept apart is not the same as shown, and NOTHING on this
 * page added them up. A reader met "GAME PICKS 31-17, ROI PER UNIT STAKED
 * +4.96%" first and took it for the record of the product, when the props
 * panel below it was 14-9 and DOWN 1.73 units. Whole book: 45-26 and +0.91%.
 * Reporting the better half first and never stating the sum is how a true
 * set of numbers adds up to a false impression, so this panel states the sum
 * and says exactly which populations went into it.
 *
 * Every figure is recomputed from the per-kind rows, never from a separate
 * server field, so this panel cannot drift from the panels above it.
 */
function combinedHeadline(record) {
  const kinds = record.by_kind;
  if (!kinds) return null;   // an older /card/record without by_kind
  const parts = ["game", "prop", "total"]
    .map((name) => kinds[name])
    .filter((part) => part && typeof part.n_staked === "number");
  if (parts.length < 2) return null;   // nothing to add up yet

  const sum = (field) => parts.reduce((acc, p) => acc + (p[field] || 0), 0);
  const wins = sum("wins");
  const losses = sum("losses");
  const pushes = sum("pushes");
  const voids = sum("voids");
  const staked = sum("n_staked");
  const units = parts.reduce((acc, p) => acc + (p.profit_units || 0), 0);
  if (!staked) return null;

  const wrap = el("div", { class: "crp-headline crp-headline--combined panel chamfer",
    "data-hook": "record-combined-headline" });
  wrap.appendChild(el("span", { class: "crp-chain__label", text: "EVERYTHING TOGETHER" }));
  const grid = el("div", { class: "crp-stats" });
  grid.appendChild(statTile("ALL BETS (W-L-P)", figure(`${wins}-${losses}-${pushes}`)));
  grid.appendChild(statTile("VOIDS", figure(String(voids), voids ? "warn" : null)));
  grid.appendChild(statTile("WIN RATE", figure(winRateFmt(wins / staked))));
  grid.appendChild(statTile("UNITS NET",
    figure(unitsFmt(units), units > 0 ? "pos" : units < 0 ? "neg" : null)));
  const roi = (units / staked) * 100;
  grid.appendChild(statTile("ROI PER UNIT STAKED",
    figure(roiFmt(roi), roi > 0 ? "pos" : roi < 0 ? "neg" : null)));
  wrap.appendChild(grid);
  wrap.appendChild(el("p", { class: "crp-chain__body",
    text: "Game picks, player props and totals added together — every bet this "
        + "product has published and graded, in one number. The panels above "
        + "split the same bets by type; none of them is the whole record on "
        + "its own." }));
  return wrap;
}

function unitsNote() {
  return el("p", { class: "crp-intro", "data-hook": "record-units-note",
    text: "A UNIT IS A STAKE SIZE YOU CHOOSE, not a dollar figure we set. Every pick here is staked a flat "
        + "1 unit: a win at -150 returns +0.67u, a win at +150 returns +1.5u, a loss is -1.0u. ROI PER UNIT "
        + "STAKED is units won divided by bets made -- your return on what you risked per bet, not bankroll "
        + "growth. Worked through, with made-up numbers: if your unit is 5% of a $1,000 bankroll, then a "
        + "2.6-unit gain over 52 bets is $130. That is 5% per unit staked and 13% bankroll growth -- two "
        + "different figures from the same night. The percentage above is always the first one." });
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

/** `kind` distinguishes a player-prop (or, since 2026-09-14, a total) row
 * from a game row on the same table -- all three read the same five
 * columns (BET/RESULT/PRICE/BOOK/RETURN) off the same shape, since a prop
 * or total pick is frozen exactly like a game pick (see card.js's own
 * PLAYER PROPS / totals sections). Defaults to "game" so every existing
 * call site, and every ledger row with no `prop_picks`/`total_picks` at
 * all, renders exactly as before. */
function pickRow(pick, kind = "game") {
  const isProp = kind === "prop";
  const isTotal = kind === "total";
  const tr = el("tr", { "data-hook": isTotal ? "record-total-pick-row"
    : (isProp ? "record-prop-pick-row" : "record-pick-row") });

  const betCell = el("td", { class: "crp-pick-bet" });
  betCell.appendChild(el("span", { class: "crp-pick-bet__text", text: pick.bet || "—" }));
  if (isProp) {
    betCell.appendChild(el("span", { class: "crp-pick-bet__kind", text: "PROP" }));
  } else if (isTotal) {
    betCell.appendChild(el("span", { class: "crp-pick-bet__kind", text: "TOTAL" }));
  }
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
  // `data-date` is the calendar's jump target -- see `calendarDayCell`.
  const card = el("article", { class: "crp-day panel chamfer", "data-hook": "record-day",
    "data-date": day.date || "" });

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
  // `prop_picks` is absent on every history day settled before
  // 2026-09-12 -- `|| []` is the whole compatibility story, same as
  // card.js's own frozen-card reader. `total_picks` is the same story
  // again from 2026-09-14.
  for (const pick of day.prop_picks || []) tbody.appendChild(pickRow(pick, "prop"));
  for (const pick of day.total_picks || []) tbody.appendChild(pickRow(pick, "total"));
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

/* =====================================================================
 * THE CALENDAR
 *
 * Asked for directly: "a true tally, seeable by everyone on a calendar that
 * people can click and go through and see the verifiable wins".
 *
 * A month grid over the ledger. Three states a day can be in, and they are
 * deliberately different from each other at a glance:
 *
 *   no card       dim and empty. Most days, early on, and never dressed up.
 *   published     the picks are locked but the games have not been graded.
 *                 Shows the pick count and says PENDING -- because "we said
 *                 this before the games" is the claim that matters, and it
 *                 is true the moment it is published, not the morning after.
 *   graded        W-L and the day's units, coloured. This is the receipt.
 *
 * Clicking a day scrolls to that day's full detail below, which already
 * exists (`dayBlock`) and carries every pick, its result and the hash it was
 * frozen under. The calendar is navigation, not a second source of truth --
 * it never states a result the detail below does not.
 * ===================================================================*/

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November",
                     "December"];

/** YYYY-MM-DD -> {y, m, d} with no timezone in the way.
 *
 * `new Date("2026-09-10")` is parsed as UTC midnight and then rendered in
 * the reader's local zone, which in the Americas is the day BEFORE. A
 * calendar that puts a card on the wrong square is worse than no calendar,
 * so the string is split rather than parsed. */
function ymd(dateIso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateIso || ""));
  if (!m) return null;
  return { y: Number(m[1]), m: Number(m[2]), d: Number(m[3]) };
}

function monthKey(dateIso) {
  const p = ymd(dateIso);
  return p ? `${p.y}-${String(p.m).padStart(2, "0")}` : null;
}

function calendarDayCell(dateIso, entry) {
  const p = ymd(dateIso);
  const cell = el("div", { class: "crp-cal__day", "data-hook": "calendar-day",
    "data-date": dateIso });
  cell.appendChild(el("span", { class: "crp-cal__num", text: String(p.d) }));

  if (!entry) {
    cell.classList.add("crp-cal__day--empty");
    return cell;
  }

  if (entry.kind === "pending") {
    cell.classList.add("crp-cal__day--pending");
    const n = (entry.picks || []).length;
    cell.appendChild(el("span", { class: "crp-cal__figure",
      text: `${n} pick${n === 1 ? "" : "s"}` }));
    cell.appendChild(el("span", { class: "crp-cal__note", text: "PENDING" }));
    cell.setAttribute("title",
      `${dateIso}: ${n} pick${n === 1 ? "" : "s"} published, not yet graded`);
    return cell;
  }

  const wins = entry.wins || 0;
  const losses = entry.losses || 0;
  const units = typeof entry.profit_units === "number" ? entry.profit_units : null;
  const tone = units === null ? "" : units > 0 ? "--pos" : units < 0 ? "--neg" : "";
  cell.classList.add("crp-cal__day--graded");
  if (tone) cell.classList.add(`crp-cal__day${tone}`);
  cell.appendChild(el("span", { class: "crp-cal__figure", text: `${wins}-${losses}` }));
  if (units !== null) {
    cell.appendChild(el("span", { class: `crp-cal__note crp-cal__note${tone}`,
      text: `${units > 0 ? "+" : ""}${units.toFixed(2)}u` }));
  }
  cell.setAttribute("title", `${dateIso}: ${wins} won, ${losses} lost`);

  // Clickable only where there is something to click TO. A day with no
  // detail below would scroll nowhere and feel broken.
  cell.setAttribute("role", "link");
  cell.setAttribute("tabindex", "0");
  cell.classList.add("crp-cal__day--link");
  const go = () => {
    const target = document.querySelector(
      `[data-hook="record-day"][data-date="${dateIso}"]`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      target.classList.add("crp-day--flash");
      setTimeout(() => target.classList.remove("crp-day--flash"), 1600);
    }
  };
  cell.addEventListener("click", go);
  cell.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
  });
  return cell;
}

function calendarMonth(key, byDate) {
  const [year, month] = key.split("-").map(Number);
  const section = el("section", { class: "crp-cal", "data-hook": "record-calendar",
    "data-month": key });
  section.appendChild(el("h3", { class: "crp-cal__title",
    text: `${MONTH_NAMES[month - 1]} ${year}` }));

  const grid = el("div", { class: "crp-cal__grid" });
  for (const label of ["S", "M", "T", "W", "T", "F", "S"]) {
    grid.appendChild(el("span", { class: "crp-cal__dow", text: label }));
  }
  // Date.UTC keeps the weekday calculation out of the reader's timezone,
  // for the same reason `ymd` does not parse the string.
  const firstDow = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  for (let i = 0; i < firstDow; i += 1) {
    grid.appendChild(el("span", { class: "crp-cal__pad" }));
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const iso = `${year}-${String(month).padStart(2, "0")}-`
      + `${String(day).padStart(2, "0")}`;
    grid.appendChild(calendarDayCell(iso, byDate.get(iso)));
  }
  section.appendChild(grid);
  return section;
}

/** The whole calendar: one block per month that has any card in it. */
function calendar(settledDays, pendingDays) {
  const byDate = new Map();
  for (const day of settledDays || []) {
    if (day && day.date) byDate.set(day.date, { kind: "graded", ...day });
  }
  for (const day of pendingDays || []) {
    // A settled day wins: once it is graded, that is the fact.
    if (day && day.date && !byDate.has(day.date)) {
      byDate.set(day.date, { kind: "pending", ...day });
    }
  }
  if (!byDate.size) return null;

  const months = [...new Set([...byDate.keys()].map(monthKey))]
    .filter(Boolean).sort().reverse();

  const wrap = el("section", { class: "crp-calwrap", "data-hook": "record-calendar-wrap" });
  wrap.appendChild(sectionHead("THE CALENDAR",
    `${byDate.size} DAY${byDate.size === 1 ? "" : "S"} PUBLISHED`));
  wrap.appendChild(el("p", { class: "crp-cal__legend",
    text: "Every day we published a card. Green won, red lost, and a day "
        + "still waiting on its games says PENDING. Click a graded day to "
        + "jump to its picks." }));
  for (const key of months) wrap.appendChild(calendarMonth(key, byDate));
  return wrap;
}


function emptyRecord(sport = "mlb", rule = null) {
  const wrap = el("section", { class: "gutter", "data-hook": "record-empty" });
  const panel = el("div", { class: "panel chamfer card2empty" });
  panel.appendChild(el("span", { class: "card2empty__label", text: "NOTHING SETTLED YET" }));
  // NFL's page counts one rule at a time (2026-09-20), so its empty state
  // names the rule -- "nothing has been graded" over an NFL ledger that
  // holds a graded 2026-09-17 pick under the old rule would be false.
  const nothingYet = sport !== "nfl" ? "Nothing has been graded yet."
    : rule === NFL_RETIRED_RULE ? "Nothing from the old NFL rule has been graded yet."
      : "Nothing has been graded under the current NFL rule yet.";
  panel.appendChild(el("p", { class: "card2empty__body",
    text: `${nothingYet} Every card is settled the morning after it runs, win or lose, and this `
        + "page fills in from the first settled day on — including the days it loses." }));
  const actions = el("div", { class: "card2empty__actions" });
  // Sport-aware since 2026-09-19 (NFL went live): an NFL reader here should
  // land on NFL's own card, not MLB's -- see card.js's emptyCard for the
  // same reasoning applied to the card page's own empty state.
  actions.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn",
    href: sport === "nfl" ? "#/nfl" : "#/today",
    text: sport === "nfl" ? "SEE THE NFL CARD" : "SEE TONIGHT'S CARD" }));
  panel.appendChild(actions);
  wrap.appendChild(panel);
  return wrap;
}

/* ---------------------------------------------------------------------
 * View
 * ------------------------------------------------------------------- */

/** The NFL record's heading and intro, naming the rule it counts
 * (2026-09-20). NFL's ledger holds two rules since NFL_CARD_V1 (take the
 * favourite) was retired for NFL_CARD_V2 (value lines); the page shows ONE
 * rule's record at a time and never the two pooled. So it cannot say
 * "every card we have ever published" -- it says which rule, and links to
 * the other one's record, so the old rule's losses never quietly drop out
 * of sight. */
function nflIntro(screen, rule) {
  if (rule === NFL_RETIRED_RULE) {
    screen.appendChild(el("p", { class: "card2lede card2lede--notice",
      "data-hook": "record-nfl-retired-notice",
      text: "This is the record of our old NFL rule, retired on 2026-09-20. It is kept apart from the "
          + "current rule's record and never added to it." }));
    screen.appendChild(sectionHead("THE RECORD", "THE OLD NFL RULE"));
    screen.appendChild(el("p", { class: "crp-intro",
      text: "Every pick our old NFL rule made -- it took the market favourite in every game -- frozen "
          + "before the result was known, graded as published, and chained so none of it can be quietly "
          + "edited afterward: the wins and the losses both." }));
    screen.appendChild(el("a", { class: "card2rec__link", href: "#/nfl/record",
      "data-hook": "record-current-rule-link", text: "SEE THE CURRENT NFL RULE'S RECORD →" }));
    return;
  }
  screen.appendChild(el("p", { class: "card2lede card2lede--notice",
    "data-hook": "record-nfl-notice", text: NFL_NOTICE }));
  screen.appendChild(sectionHead("THE RECORD", "EVERY CARD UNDER THE CURRENT NFL RULE"));
  screen.appendChild(el("p", { class: "crp-intro",
    text: "Every NFL pick made under the current rule -- spreads, totals and moneylines, never at -200 "
        + "or worse -- frozen before the result was known and chained so none of it can be quietly edited "
        + "afterward: the wins and the losses both. Picks made by our old rule, which took the favourite, "
        + "stay in the same ledger exactly as published and have a record of their own." }));
  screen.appendChild(el("a", { class: "card2rec__link",
    href: `#/nfl/record?rule=${NFL_RETIRED_RULE}`,
    "data-hook": "record-retired-rule-link", text: "SEE THE OLD RULE'S RECORD →" }));
}

/** Shown instead of any figure when the retired rule's record was asked
 * for and the server answered with a different rule's (a server that does
 * not know `?rule=` yet serves the live rule). Printing those numbers
 * under the old rule's heading would be a false page. */
function ruleUnavailable(screen) {
  const wrap = el("section", { class: "gutter", "data-hook": "record-rule-unavailable" });
  const panel = el("div", { class: "panel chamfer card2empty" });
  panel.appendChild(el("span", { class: "card2empty__label", text: "NOT AVAILABLE HERE YET" }));
  panel.appendChild(el("p", { class: "card2empty__body",
    text: "This server did not send the old NFL rule's record, so nothing is shown rather than another "
        + "rule's numbers under its name. Its picks are kept in the ledger exactly as published." }));
  const actions = el("div", { class: "card2empty__actions" });
  actions.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn", href: "#/nfl/record",
    text: "SEE THE CURRENT NFL RECORD" }));
  panel.appendChild(actions);
  wrap.appendChild(panel);
  screen.appendChild(wrap);
}

export async function renderCardRecord(container, options = {}) {
  // Support both old signature renderCardRecord(container) and new
  // renderCardRecord(container, {sport}) for backward compatibility
  const sport = (typeof options === "object" && options !== null)
    ? (options.sport || "mlb")
    : "mlb";
  // Only the one retired NFL rule id is ever forwarded (2026-09-20) -- a
  // typed `?rule=` reaches the API only if it is exactly that id.
  const rule = sport === "nfl" && options && options.rule === NFL_RETIRED_RULE
    ? NFL_RETIRED_RULE : null;

  clear(container);
  const screen = el("div", { class: "screen crp-screen", "data-view": "record-card" });
  container.appendChild(screen);
  screen.appendChild(renderLoading("LOADING THE RECORD"));

  let record;
  let history;
  try {
    const ruleParam = rule ? `&rule=${encodeURIComponent(rule)}` : "";
    const recordUrl = `/card/record${sport !== "mlb" ? `?sport=${sport}${ruleParam}` : ""}`;
    const historyUrl = `/card/history?limit=${HISTORY_LIMIT}${sport !== "mlb" ? `&sport=${sport}${ruleParam}` : ""}`;
    [record, history] = await Promise.all([
      apiGet(recordUrl),
      apiGet(historyUrl),
    ]);
  } catch (err) {
    clear(screen);
    renderError(screen, err);
    return;
  }
  clear(screen);

  if (sport === "nfl") {
    nflIntro(screen, rule);
    if (rule && (!record || record.rule !== rule)) {
      ruleUnavailable(screen);
      return;
    }
  } else {
    screen.appendChild(sectionHead("THE RECORD", "EVERY CARD WE HAVE EVER PUBLISHED"));
    screen.appendChild(el("p", { class: "crp-intro",
      text: "Every pick this product has made, frozen before the result was known and chained so none of it can "
          + "be quietly edited afterward — the wins and the losses both." }));
  }
  screen.appendChild(unitsNote());

  // THE CALENDAR SITS ABOVE BOTH BRANCHES, because it is the one thing on
  // this page that has something to show on day one: a published card is a
  // claim on the record the moment it is frozen, not the morning after it is
  // graded. Rendering it only in the settled branch would leave the page
  // blank on exactly the day someone first looks at it.
  const calendarBlock = calendar((history && history.days) || [],
                                 (history && history.pending_days) || []);
  if (calendarBlock) screen.appendChild(calendarBlock);

  const nothingSettled = !record.days;
  if (nothingSettled) {
    screen.appendChild(chainStatus(record));
    screen.appendChild(emptyRecord(sport, rule));
  } else {
    screen.appendChild(headline(record, sport));
    screen.appendChild(voidsNote(record));
    // MLB-ONLY PANELS (2026-09-20). Props, totals-graded-apart and their
    // sum describe MLB's card, which splits those populations. NFL's rule
    // keeps spreads, totals and moneylines in ONE `picks` list, so on NFL
    // these panels said "No total has graded yet" after a total had graded
    // (inside the headline count), named props NFL has never had, and the
    // combined panel printed WIN RATE 100.0% / ROI +105.0% off one pick --
    // straight past NFL_SAMPLE_FLOOR, one panel below the note saying no
    // rate would be shown. NFL gets one sentence saying what its count
    // holds instead.
    if (sport === "nfl") {
      screen.appendChild(nflMarketsNote(rule));
    } else {
      const props = propHeadline(record);
      if (props) screen.appendChild(props);
      const totals = totalHeadline(record);
      if (totals) screen.appendChild(totals);
      const combined = combinedHeadline(record);
      if (combined) screen.appendChild(combined);
    }
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
