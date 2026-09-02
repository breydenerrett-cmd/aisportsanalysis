/**
 * ODDS / MARKET BOARD (#/odds) -- GET /odds/{date} (the whole slate's
 * board) and GET /odds/{date}/{away}/{home} (one game's), both from
 * api/odds.py / src/analysis/oddspayload.py.
 *
 * Composed from the frozen LINEHOUND V2 "ODDS BOARD -- THE CENTREPIECE"
 * artboard (design/linehound-v2/'LINEHOUND V2 Full Product.dc.html',
 * section 06, ~lines 2125-2686: desktop V2-02 at 1280x1460 and mobile
 * V2-23 at 390x844), the same artboard-traced / data-hooks-first pattern
 * web/js/today.js already established for Track 1.
 *
 * THE DATA CONTRACT (docs/API_CONTRACTS.md:159-198,
 * tests/test_api_contracts.py:453-580, verified against
 * src/analysis/oddspayload.py -- read directly, not assumed):
 *
 *   markets.h2h = {
 *     board_available, reason,
 *     board: [{book, away_price, home_price, captured_at}],
 *     best: {away, home} each {price, books[]} | null,
 *     consensus: {away, home} each {implied_probability, implied_price}
 *                | null, plus consensus.books (int) when not null,
 *     consensus_unavailable_reason: KEY ABSENT when board_available is
 *                false; present (string | null) when it is true,
 *     spread_cents: {away, home} each number | null -- ALWAYS an object,
 *                even with no board. This is cents of raw disagreement
 *                between the best and worst quote on one side, never a
 *                point spread, and (per oddspayload.py) it does NOT
 *                require a computed consensus -- it only needs two
 *                priced quotes on that side. A below-floor "thin" board
 *                can still carry a real spread_cents; this client shows
 *                it when the value is actually present rather than
 *                asserting the categorical (and false) "no consensus
 *                means no spread_cents" the artboard's own copy implies.
 *     staleness: {observed_utc, age_seconds, has_board},
 *   }
 *
 * THREE BOARD VARIANTS (handoff's "V2-02" spec, `boardVariant()` below):
 *   full     board_available && consensus !== null
 *   thin     board_available && consensus === null   (below the 6-book
 *            floor; consensus_unavailable_reason names why)
 *   no-board !board_available                        (reason is the raw
 *            API string; the customer-facing headline is always the
 *            mandated sentence per handoff rule 3.10, never "no odds" --
 *            has_board:false also covers a club-name match failure, and
 *            "no odds" would claim the market itself is empty)
 *
 * RESERVED COLOR: hot red (--v-money-*) marks only a genuinely-best price
 * (the tied-books panel, the matching board cells) and the one primary
 * action per card -- never a category or a warning. Amber (--v-warn-*)
 * is the new V2 signal for "caution / below floor / stale", used for the
 * thin-board alert and any board row past OUR 30-minute freshness
 * threshold (STALE_AFTER_SECONDS below -- a client judgment call, no
 * server staleness verdict exists, so it is drawn and labelled as ours).
 *
 * NO OUTBOUND SPORTSBOOK LINKS. Every price cell hands off in-app to Bet
 * Check (pre-filled with date/away/home; the API documents "team-name
 * resolution is the client's job" and offers no side/price prefill
 * surface yet, so those two fields still land on Bet Check's default).
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading,
  formatAmerican, formatConsensusShare, formatEasternClock } from "./dom.js";
import { teamColors } from "./teamcolors.js";
import { teamName, bookLabel } from "./labels.js";
import { setShellStatus } from "./shell.js";
import { armEntrances } from "./motion.js";

/** Above this age a board ROW (one book's quote) is flagged stale. This
 * is a CLIENT decision, not a server verdict (handoff rule 3.11: "no
 * server staleness verdict exists ... draw it at 1800s and label it as
 * ours") -- drawn independently per book row, because the multi-book
 * store can hold a lagging book's older capture alongside a fresher
 * board (the artboard's own "mybookieag ... 3:24pm ET" example row). */
const STALE_AFTER_SECONDS = 1800;

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function hasOwn(obj, key) {
  return !!obj && Object.prototype.hasOwnProperty.call(obj, key);
}

/** "4:12pm ET" -- the compact lowercase clock style the artboard uses
 * throughout this screen (formatEasternClock is the same helper
 * web/js/tiles.js already reuses; this only appends the ET marker every
 * call site on this screen wants). Null in, null out. */
function et(isoUtc) {
  const clock = formatEasternClock(isoUtc);
  return clock ? `${clock} ET` : null;
}

/** No seconds-level liveness claim on this screen (capture cadence is
 * hourly; a sub-minute "UPDATED X SEC AGO" would misrepresent that) --
 * unlike dom.js's shared formatAge, anything under a minute reads
 * "<1 MIN AGO" rather than counting seconds. */
function ageNoSeconds(ageSeconds) {
  if (ageSeconds === null || ageSeconds === undefined) return null;
  const seconds = Number(ageSeconds);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return "<1 MIN AGO";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} MIN AGO`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} HR AGO`;
  return `${Math.round(hours / 24)} DAY AGO`;
}

function h2hOf(gameEntry) {
  return (gameEntry && gameEntry.markets && gameEntry.markets.h2h) || null;
}

/** full | thin | no-board -- see module docstring. */
function boardVariant(h2h) {
  if (!h2h || !h2h.board_available) return "no-board";
  if (h2h.consensus === null || h2h.consensus === undefined) return "thin";
  return "full";
}

function freshestObservedUtc(games) {
  let best = null;
  for (const entry of games) {
    const h2h = h2hOf(entry);
    const observed = h2h && h2h.staleness && h2h.staleness.observed_utc;
    if (!observed) continue;
    if (!best || Date.parse(observed) > Date.parse(best)) best = observed;
  }
  return best;
}

/* ---------------------------------------------------------------------
 * Small building blocks
 * ------------------------------------------------------------------- */

function teamBadge(abbr) {
  const colors = teamColors(abbr);
  const badge = el("span", { class: "ov2-badge", "aria-hidden": "true", text: abbr || "" });
  badge.style.background = colors.known ? colors.primary : "#232830";
  badge.style.color = colors.known ? colors.accent : "#D5D7DE";
  return badge;
}

function statTile(label, valueText, sample, { accent = false, textFigure = false } = {}) {
  const tile = el("div", { class: `ov2-stat${accent ? " ov2-stat--accent" : ""}` });
  tile.appendChild(el("div", { class: "ov2-stat__label", text: label }));
  const row = el("div", { class: "ov2-stat__row" });
  row.appendChild(el("span", { class: `ov2-stat__figure${textFigure ? " ov2-stat__figure--text" : ""}`,
    text: valueText }));
  if (sample) row.appendChild(el("span", { class: "ov2-stat__sample", text: sample }));
  tile.appendChild(row);
  return tile;
}

/** The widest-spread stat needs the matchup identity, which
 * `summary.widest_spread_game` (game_id, side, spread_cents) does not
 * itself carry -- looked up against the slate rows this client already
 * has rather than displaying a bare game_id. */
function widestSpreadLabel(summary, games) {
  const widest = summary && summary.widest_spread_game;
  if (!widest) return null;
  const entry = games.find((g) => g.game_id === widest.game_id);
  if (!entry) return null;
  const sideAbbr = widest.side === "home" ? entry.home_team : entry.away_team;
  return {
    matchup: `${entry.away_team} @ ${entry.home_team}`,
    detail: `spread_cents ${sideAbbr} ${widest.spread_cents}c`,
  };
}

/* ---------------------------------------------------------------------
 * Best-price / consensus panels
 * ------------------------------------------------------------------- */

function bestPanel(sideAbbr, best) {
  const panel = el("div", { class: "ov2-panel ov2-panel--best" });
  const count = best && Array.isArray(best.books) ? best.books.length : 0;
  panel.appendChild(el("div", { class: "ov2-panel__label",
    text: best ? `BEST ${sideAbbr} · ${count} BOOK${count === 1 ? "" : "S"} TIED` : `BEST ${sideAbbr}` }));
  if (!best || typeof best.price !== "number") {
    panel.appendChild(el("p", { class: "ov2-panel__empty", text: "No priced quote on this side." }));
    return panel;
  }
  panel.appendChild(el("div", { class: "ov2-panel__price", "data-hook": "odds-best-price",
    text: formatAmerican(best.price) }));
  const books = el("div", { class: "ov2-panel__books" });
  for (const book of best.books || []) {
    books.appendChild(el("span", { class: "ov2-panel__book", text: bookLabel(book) }));
  }
  panel.appendChild(books);
  return panel;
}

/** Real shape: `consensus.{away,home}` are independent per-side objects
 * (never one combined figure) plus a single shared `consensus.books`
 * count -- rendered as two columns under one "MARKET-IMPLIED CONSENSUS"
 * panel rather than the artboard's single-side example box, since a real
 * game payload always carries both sides. */
function consensusPanel(consensus, spreadCents, awayAbbr, homeAbbr) {
  const panel = el("div", { class: "ov2-panel ov2-panel--consensus" });
  panel.appendChild(el("div", { class: "ov2-panel__label", text: "MARKET-IMPLIED CONSENSUS (DE-VIGGED)" }));
  const cols = el("div", { class: "ov2-consensus-cols" });
  for (const [side, abbr] of [["away", awayAbbr], ["home", homeAbbr]]) {
    const detail = consensus ? consensus[side] : null;
    const col = el("div", { class: "ov2-consensus-col" });
    col.appendChild(el("div", { class: "ov2-consensus-col__side", text: abbr }));
    if (!detail || hasOwn(detail, "skipped") || typeof detail.implied_price !== "number") {
      col.appendChild(el("p", { class: "ov2-panel__empty", text: "Not enough books on this side." }));
    } else {
      col.appendChild(el("div", { class: "ov2-consensus-col__price", "data-hook": "odds-consensus-price",
        text: formatAmerican(detail.implied_price) }));
      const prob = formatConsensusShare(detail.implied_probability);
      if (prob) {
        col.appendChild(el("div", { class: "ov2-consensus-col__meta",
          text: `IMPLIED PROBABILITY ${prob}` }));
      }
      const spread = spreadCents ? spreadCents[side] : null;
      if (typeof spread === "number") {
        col.appendChild(el("div", { class: "ov2-consensus-col__meta",
          text: `SPREAD_CENTS ${spread}c between books` }));
      }
    }
    cols.appendChild(col);
  }
  panel.appendChild(cols);
  if (consensus && typeof consensus.books === "number") {
    panel.appendChild(el("div", { class: "ov2-panel__sample", text: `n = ${consensus.books} books` }));
  }
  return panel;
}

/** Thin-board only: spread_cents is real and independent of the
 * below-floor consensus (see module docstring) -- shown when the API
 * actually supplied a value, omitted (never fabricated) otherwise. */
function spreadLine(spreadCents, awayAbbr, homeAbbr) {
  if (!spreadCents) return null;
  const parts = [];
  if (typeof spreadCents.away === "number") parts.push(`${awayAbbr} ${spreadCents.away}c`);
  if (typeof spreadCents.home === "number") parts.push(`${homeAbbr} ${spreadCents.home}c`);
  if (!parts.length) return null;
  return el("p", { class: "ov2-spreadline", "data-hook": "odds-spread-cents",
    text: `SPREAD_CENTS — ${parts.join(" · ")} (raw disagreement between books, not a point spread)` });
}

function thinAlert(h2h, bookCount) {
  const box = el("div", { class: "ov2-alert" });
  const head = el("div", { class: "ov2-alert__head" });
  head.appendChild(el("span", { class: "ov2-alert__mark", "aria-hidden": "true", text: "!" }));
  const body = el("div", { class: "ov2-alert__copy" });
  body.appendChild(el("div", { class: "ov2-alert__title", text: "NO CONSENSUS · REASON GIVEN" }));
  // Verbatim artboard line (design/linehound-v2 section 06, V2-02's thin-
  // board example: "Three books is not a market. We won't average it."),
  // with the real per-game book count interpolated -- the artboard's "3"
  // is that one example's own board size, not a fixed word.
  body.appendChild(el("div", { class: "ov2-alert__headline", "data-hook": "odds-thin-headline",
    text: `${bookCount} book${bookCount === 1 ? "" : "s"} is not a market. We won't average it.` }));
  body.appendChild(el("p", { class: "ov2-alert__body",
    text: "Too few books on this board for a market-wide read, so we do not average one. The raw board "
        + "still renders below." }));
  const reason = hasOwn(h2h, "consensus_unavailable_reason") && h2h.consensus_unavailable_reason
    ? h2h.consensus_unavailable_reason
    : "insufficient books for a market-wide read";
  body.appendChild(el("p", { class: "ov2-alert__reason", "data-hook": "odds-consensus-reason",
    text: `consensus_unavailable_reason: "${reason}"` }));
  head.appendChild(body);
  box.appendChild(head);
  return box;
}

function noBoardBlock(h2h) {
  const box = el("div", { class: "ov2-noboard" });
  // Mandated customer sentence (handoff rule 3.10) -- has_board:false also
  // covers a club-name match failure, so this never says "no odds" (that
  // would claim the market itself is empty) and never quotes the raw
  // internal `reason` string as the headline.
  box.appendChild(el("p", { class: "ov2-noboard__title", "data-hook": "odds-no-board",
    text: "No price board recorded for this game." }));
  box.appendChild(el("p", { class: "ov2-noboard__body",
    text: "There is no board and this could be a genuine gap in coverage or a club-name match failure on "
        + "our side -- both look identical from here, so we say exactly this and nothing further." }));
  const staleness = h2h.staleness || {};
  const fields = el("div", { class: "ov2-noboard__fields" });
  const field = (key, value) => {
    fields.appendChild(el("span", { class: "ov2-noboard__key", text: key }));
    fields.appendChild(el("span", { class: "ov2-noboard__val", text: value }));
  };
  field("has_board", String(!!staleness.has_board));
  field("books", "0");
  field("consensus_unavailable_reason",
    hasOwn(h2h, "consensus_unavailable_reason") ? String(h2h.consensus_unavailable_reason) : "key absent");
  field("observed_utc", staleness.observed_utc == null ? "null" : String(staleness.observed_utc));
  if (h2h.reason) field("reason", h2h.reason);
  box.appendChild(fields);
  box.appendChild(el("p", { class: "ov2-noboard__note",
    text: "Never “no odds” — that would claim the market is empty when our own match may have "
        + "failed instead." }));
  return box;
}

/* ---------------------------------------------------------------------
 * The raw board table
 * ------------------------------------------------------------------- */

function priceCell(price, isBest, gotoHash, stale) {
  const td = el("td", { class: `ov2-pricecell${isBest ? " ov2-pricecell--best" : ""}`
    + `${stale ? " ov2-pricecell--stale" : ""}` });
  const text = formatAmerican(price);
  if (text === null) {
    td.appendChild(el("span", { class: "value-absent", text: "—" }));
    return td;
  }
  const cell = el("button", { type: "button", class: "ov2-cell", "data-cell": "", "data-hook": "odds-price-cell",
    text });
  if (gotoHash) cell.addEventListener("click", () => { window.location.hash = gotoHash; });
  td.appendChild(cell);
  return td;
}

/** Below 900px the artboard (V2-23) truncates the raw board to its first
 * 5 rows and hands the rest to a tap-to-expand line rather than a
 * horizontal scroll -- desktop always shows every row. */
const MOBILE_ROWS_SHOWN = 5;

function boardTable(h2h, awayAbbr, homeAbbr, date, referenceNow) {
  const wrap = el("div", { class: "ov2-table-wrap" });
  const table = el("table", { class: "ov2-table", "data-hook": "odds-board" });
  table.appendChild(el("caption", { text: `Full price board, ${awayAbbr} at ${homeAbbr}` }));
  const thead = el("thead");
  const headRow = el("tr");
  headRow.appendChild(el("th", { scope: "col", text: "BOOK KEY" }));
  headRow.appendChild(el("th", { scope: "col", text: awayAbbr }));
  headRow.appendChild(el("th", { scope: "col", text: homeAbbr }));
  headRow.appendChild(el("th", { scope: "col", text: "CAPTURED AT" }));
  thead.appendChild(headRow);
  table.appendChild(thead);

  const bestAwayBooks = new Set((h2h.best && h2h.best.away && h2h.best.away.books) || []);
  const bestHomeBooks = new Set((h2h.best && h2h.best.home && h2h.best.home.books) || []);
  const board = h2h.board || [];
  const tbody = el("tbody");
  let index = 0;
  for (const row of board) {
    const ageSeconds = (Number.isFinite(referenceNow) && row.captured_at)
      ? Math.max((referenceNow - Date.parse(row.captured_at)) / 1000, 0)
      : null;
    const stale = typeof ageSeconds === "number" && Number.isFinite(ageSeconds)
      && ageSeconds > STALE_AFTER_SECONDS;
    const extra = index >= MOBILE_ROWS_SHOWN;
    index += 1;

    const tr = el("tr", { "data-hook": "odds-row", "data-stale": String(stale),
      class: extra ? "ov2-row--extra" : undefined });
    const bookCell = el("td", { class: "ov2-bookcell" });
    bookCell.appendChild(el("span", { class: `ov2-bookname${stale ? " ov2-bookname--stale" : ""}`,
      text: bookLabel(row.book) }));
    if (stale) {
      bookCell.appendChild(el("span", { class: "ov2-rowflag", "data-hook": "odds-row-stale",
        text: "OVER 30 MIN (OUR THRESHOLD)" }));
    }
    tr.appendChild(bookCell);
    const hash = `#/betcheck?date=${encodeURIComponent(date)}&away=${encodeURIComponent(awayAbbr)}`
      + `&home=${encodeURIComponent(homeAbbr)}`;
    tr.appendChild(priceCell(row.away_price, bestAwayBooks.has(row.book), hash, stale));
    tr.appendChild(priceCell(row.home_price, bestHomeBooks.has(row.book), hash, stale));
    const captured = et(row.captured_at);
    tr.appendChild(el("td", { class: `ov2-capturedcell${stale ? " ov2-capturedcell--stale" : ""}`,
      text: captured || "—" }));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  // Mobile-only tap-to-expand for rows beyond MOBILE_ROWS_SHOWN (CSS
  // hides .ov2-row--extra and this line at >899px, where the table is
  // already showing every row -- see screens.css's ODDS V2 section).
  const moreCount = Math.max(board.length - MOBILE_ROWS_SHOWN, 0);
  if (moreCount > 0) {
    const more = el("button", { type: "button", class: "ov2-more", "data-hook": "odds-more-books",
      text: `${moreCount} MORE BOOK${moreCount === 1 ? "" : "S"} · TAP ANY PRICE TO CHECK IT` });
    more.addEventListener("click", () => {
      wrap.classList.add("ov2-table-wrap--expanded");
    });
    wrap.appendChild(more);
  }
  return wrap;
}

/* ---------------------------------------------------------------------
 * One game's card -- shared by the slate board and the single-game route
 * ------------------------------------------------------------------- */

function gameCard(gameEntry, { date, referenceNow }) {
  const h2h = h2hOf(gameEntry) || {};
  const variant = boardVariant(h2h);
  const away = gameEntry.away_team;
  const home = gameEntry.home_team;

  const card = el("article", {
    class: `ov2-game panel chamfer ov2-game--${variant}`,
    "data-hook": "odds-game-card", "data-game-id": gameEntry.game_id || "",
    "data-variant": variant, "data-rise": "",
  });
  const head = el("div", { class: "ov2-game__head" });
  head.appendChild(teamBadge(away));
  const matchup = el("span", { class: "ov2-matchup" });
  const awayFull = teamName(away, "full");
  const homeFull = teamName(home, "full");
  matchup.appendChild(el("span", awayFull ? { text: away, title: awayFull } : { text: away }));
  matchup.appendChild(el("span", { class: "ov2-matchup__at", text: "@" }));
  matchup.appendChild(el("span", homeFull ? { text: home, title: homeFull } : { text: home }));
  head.appendChild(matchup);
  const firstPitch = et(gameEntry.first_pitch_utc);
  if (firstPitch) head.appendChild(el("span", { class: "ov2-clock", text: firstPitch }));
  head.appendChild(el("span", { class: "ov2-spacer" }));

  // The REAL per-game book count -- board.length, never a fixed number
  // (handoff: "median 11, min observed 5"; a slate-wide constant does
  // not exist on this endpoint, so this is always this game's own row
  // count from this response).
  const bookCount = Array.isArray(h2h.board) ? h2h.board.length : 0;
  head.appendChild(el("span", { class: "ov2-bookcount", "data-hook": "odds-book-count",
    text: `${bookCount} BOOK${bookCount === 1 ? "" : "S"} ON THE BOARD` }));

  const staleness = h2h.staleness || {};
  const observed = et(staleness.observed_utc);
  if (observed) {
    const age = ageNoSeconds(staleness.age_seconds);
    const chip = el("span", { class: "ov2-captured" });
    chip.appendChild(el("span", { class: "ov2-captured__dot" }));
    chip.appendChild(el("span", { text: age ? `CAPTURED ${observed} · ${age}` : `CAPTURED ${observed}` }));
    head.appendChild(chip);
  }
  card.appendChild(head);

  const body = el("div", { class: "ov2-body" });
  if (variant === "no-board") {
    body.appendChild(noBoardBlock(h2h));
  } else {
    if (variant === "thin") body.appendChild(thinAlert(h2h, bookCount));

    const panels = el("div", { class: "ov2-panels" });
    panels.appendChild(bestPanel(away, h2h.best && h2h.best.away));
    panels.appendChild(bestPanel(home, h2h.best && h2h.best.home));
    if (variant === "full") panels.appendChild(consensusPanel(h2h.consensus, h2h.spread_cents, away, home));
    body.appendChild(panels);

    if (variant === "thin") {
      const line = spreadLine(h2h.spread_cents, away, home);
      if (line) body.appendChild(line);
    }

    body.appendChild(boardTable(h2h, away, home, date, referenceNow));
  }
  card.appendChild(body);

  const actions = el("div", { class: "ov2-actions" });
  actions.appendChild(el("a", {
    class: "btn btn--secondary chamfer chamfer--btn",
    href: `#/game/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`,
    "data-hook": "odds-open-game", text: "OPEN THIS GAME",
  }));
  actions.appendChild(el("a", {
    class: "btn btn--primary chamfer chamfer--btn",
    href: `#/betcheck?date=${encodeURIComponent(date)}&away=${encodeURIComponent(away)}&home=${encodeURIComponent(home)}`,
    "data-hook": "odds-run-check", text: "RUN BET CHECK",
  }));
  card.appendChild(actions);
  card.appendChild(el("p", { class: "ov2-disclaimer",
    text: "Comparison only. No sportsbook link and no bet-placement endpoint here -- we show the number, "
        + "not a way to it." }));

  return card;
}

/* ---------------------------------------------------------------------
 * Slate summary
 * ------------------------------------------------------------------- */

function dateForm(currentDate) {
  const form = el("form", { class: "ov2-datebar", "data-hook": "odds-date-form" });
  form.appendChild(el("label", { for: "odds-date-input", class: "ov2-datebar__label", text: "DATE" }));
  const input = el("input", { type: "date", id: "odds-date-input", name: "date",
    value: currentDate || todayIso(), "data-hook": "odds-date-input" });
  form.appendChild(input);
  form.appendChild(el("button", { type: "submit", class: "btn btn--secondary chamfer chamfer--btn",
    text: "LOAD BOARD" }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.hash = `#/odds/${input.value}`;
  });
  return form;
}

function masthead(summary, games, freshLabel) {
  const section = el("section", { class: "ov2-summary panel chamfer gutter", "data-hook": "odds-summary",
    "data-rise": "" });
  section.appendChild(el("span", { class: "eyebrow", text: "SLATE SUMMARY · MONEYLINE ONLY" }));

  const gamesCount = typeof summary.games_count === "number" ? summary.games_count : games.length;
  const disagree = typeof summary.books_disagree_on_favorite_count === "number"
    ? summary.books_disagree_on_favorite_count : null;

  let headline;
  if (gamesCount === 0) headline = "No games on the board.";
  else if (disagree === null) headline = `${gamesCount} game${gamesCount === 1 ? "" : "s"} on tonight's board.`;
  else if (disagree === 0) headline = "Every book on tonight's board agrees who's favoured.";
  else headline = `${disagree} of tonight's ${gamesCount} games — the books disagree on who's favoured.`;
  section.appendChild(el("div", { class: "ov2-summary__headline", "data-hook": "odds-headline", text: headline }));
  section.appendChild(el("p", { class: "ov2-summary__body",
    text: "Not a prediction — a measurement. When the board disagrees on the favourite, that is the "
        + "most honest thing this data can tell you." }));

  const stats = el("div", { class: "ov2-summary__stats" });
  stats.appendChild(statTile("BOOKS DISAGREE ON FAVOURITE",
    disagree === null ? "—" : String(disagree),
    `n = ${gamesCount} game${gamesCount === 1 ? "" : "s"}`, { accent: true }));
  const widest = widestSpreadLabel(summary, games);
  stats.appendChild(statTile("WIDEST SPREAD",
    widest ? widest.matchup : "—",
    widest ? widest.detail : "no priceable spread on this slate", { textFigure: true }));
  stats.appendChild(statTile("GAMES ON THE SLATE", String(gamesCount), "games_count"));
  section.appendChild(stats);

  const legend = el("div", { class: "ov2-legend" });
  const item1 = el("span", { class: "ov2-legend__item" });
  item1.appendChild(el("span", { class: "ov2-legend__swatch ov2-legend__swatch--money" }));
  item1.appendChild(el("span", { text: "BEST — ALL TYING BOOKS" }));
  const item2 = el("span", { class: "ov2-legend__item" });
  item2.appendChild(el("span", { class: "ov2-legend__swatch ov2-legend__swatch--warn" }));
  item2.appendChild(el("span", { text: "OVER OUR 30-MINUTE THRESHOLD" }));
  legend.appendChild(item1);
  legend.appendChild(item2);
  section.appendChild(legend);

  const fresh = el("p", { class: "ov2-freshness", "data-hook": "odds-freshness" });
  fresh.appendChild(el("span", { class: "ov2-freshness__dot" }));
  fresh.appendChild(el("span", {
    text: freshLabel ? `PRICES AS OF ${freshLabel}` : "No board captured for this slate yet.",
  }));
  section.appendChild(fresh);

  return section;
}

/* ---------------------------------------------------------------------
 * Views
 * ------------------------------------------------------------------- */

export async function renderOdds(container, date) {
  clear(container);
  const useDate = date || todayIso();
  const host = el("div", { class: "screen", "data-view": "odds" });
  container.appendChild(host);

  const loading = renderLoading("LOADING TONIGHT'S BOARD");
  const loadingWrap = el("div", { class: "screen-state" }, [loading]);
  host.appendChild(loadingWrap);

  let payload;
  try {
    payload = await apiGet(`/odds/${encodeURIComponent(useDate)}`);
  } catch (err) {
    renderError(loadingWrap, err);
    return;
  }
  loadingWrap.remove();

  const games = payload.games || [];
  const summary = payload.summary || {};
  const effectiveDate = payload.date || useDate;
  const referenceNow = Date.parse(payload.generated_at);

  host.appendChild(dateForm(effectiveDate));

  const freshest = freshestObservedUtc(games);
  const freshLabel = et(freshest);
  setShellStatus(freshLabel ? `PRICES AS OF ${freshLabel}` : null);

  host.appendChild(masthead(summary, games, freshLabel));

  if (games.length === 0) {
    const empty = el("div", { class: "state-empty gutter", "data-hook": "odds-empty" }, [
      el("p", { class: "state-empty__title", text: "No games to board." }),
      el("p", { class: "state-empty__body", text: `No games are scheduled for ${effectiveDate}.` }),
    ]);
    host.appendChild(empty);
    armEntrances(host);
    return;
  }

  const list = el("div", { class: "ov2-list gutter" });
  let i = 0;
  for (const entry of games) {
    const card = gameCard(entry, { date: effectiveDate, referenceNow });
    card.setAttribute("data-delay", String(Math.min(i, 6) * 60));
    list.appendChild(card);
    i += 1;
  }
  host.appendChild(list);

  host.appendChild(el("p", { class: "ov2-footnote gutter",
    text: "Moneyline only — other markets are refused by name. Book count above is the real count on "
        + "each game's own board, never a fixed number. The 30-minute stale flag is a threshold we draw, "
        + "not one the sportsbooks report." }));

  armEntrances(host);
}

export async function renderOddsGame(container, date, away, home) {
  clear(container);
  const host = el("div", { class: "screen", "data-view": "odds-game" });
  host.appendChild(el("a", { href: `#/odds/${encodeURIComponent(date)}`,
    class: "odds-game__back", text: "BACK TO ODDS BOARD" }));
  container.appendChild(host);

  const loading = renderLoading("LOADING ODDS");
  const loadingWrap = el("div", { class: "screen-state" }, [loading]);
  host.appendChild(loadingWrap);

  let payload;
  try {
    payload = await apiGet(
      `/odds/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`);
  } catch (err) {
    renderError(loadingWrap, err);
    return;
  }
  loadingWrap.remove();

  if (payload.note) {
    host.appendChild(el("p", { class: "odds-game__note gutter", "data-hook": "doubleheader-note",
      text: payload.note }));
  }

  const list = el("div", { class: "ov2-list gutter" });
  list.appendChild(gameCard(payload, { date: payload.date || date, referenceNow: Date.now() }));
  host.appendChild(list);

  armEntrances(host);
}
