/**
 * GAMES -- the slate (#/games/{date}) and one game
 * (#/game/{date}/{away}/{home}), from api/games.py.
 *
 * The game screen is composed from the frozen "Game Quick View", "Game
 * Advanced View" and "Game View mobile" artboards:
 *
 *   the team-colour seam header
 *   QUICK VIEW      WHY THIS GAME MATTERS · THE PRICE · three cards ·
 *                   HISTORICAL EVIDENCE
 *   the toggle      SHOW ADVANCED ANALYSIS
 *   ADVANCED        six blocks, APPENDED BENEATH Quick View
 *
 * ADVANCED APPENDS, NEVER REPLACES (HANDOFF_README.md, verbatim rule).
 * The toggle only shows and hides the advanced host; Quick View is never
 * unmounted, never moved, and never re-rendered by it.
 *
 * `sections` / `gaps` on the advanced payload are, like /today's
 * `dossier`, "not yet a stable per-field contract", so the six blocks
 * read them defensively and anything this file does not have a designed
 * block for is still rendered -- verbatim, through dom.renderUnknown --
 * in the appendix, so nothing is silently dropped.
 *
 * THE SLATE LIST has no artboard of its own (the nine-screen inventory
 * covers Gameday, Bet Check and the two Game depths). It therefore
 * reuses the Gameday slate tile as a responsive grid rather than
 * inventing a second visual language for the same content -- flagged in
 * the handback as an extension, not a reproduction.
 */

import { apiGet } from "./api.js";
import { el, clear, renderUnknown, renderError, renderLoading, notYetAvailable,
  humanizeKey, verdictLabel, verdictChipClass, formatAmerican, formatAge,
  formatBook, formatConsensusShare, formatEasternTime } from "./dom.js";
import { renderStaleness } from "./meta.js";
import { seamGradient, teamColors } from "./teamcolors.js";
import { slateTile } from "./tiles.js";
import { setShellStatusFromStaleness } from "./shell.js";
import { armEntrances } from "./motion.js";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

/* =====================================================================
 * The slate list
 * ===================================================================*/

export async function renderGamesList(container, date) {
  clear(container);
  const useDate = date || todayIso();
  const screen = el("div", { class: "screen", "data-view": "games" });
  container.appendChild(screen);

  const toolbar = el("div", { class: "games-toolbar" });
  const form = el("form", { class: "field-form panel chamfer", "data-hook": "games-date-form" });
  const row = el("p", { class: "field-row" });
  row.appendChild(el("label", { for: "games-date-input", text: "Slate date" }));
  const input = el("input", { type: "date", id: "games-date-input", value: useDate,
    name: "date", "data-hook": "games-date-input" });
  row.appendChild(input);
  form.appendChild(row);
  form.appendChild(el("button", { type: "submit", class: "btn btn--cyan chamfer chamfer--btn on-live",
    text: "LOAD SLATE" }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.hash = `#/games/${input.value}`;
  });
  toolbar.appendChild(form);
  screen.appendChild(toolbar);

  const headHost = el("div", { class: "gutter" });
  screen.appendChild(headHost);
  const loadingWrap = el("div", { class: "screen-state" }, [renderLoading("LOADING THE SLATE")]);
  screen.appendChild(loadingWrap);

  let payload;
  let odds = null;
  try {
    payload = await apiGet(`/games/${encodeURIComponent(useDate)}`);
    odds = await apiGet(`/odds/${encodeURIComponent(useDate)}`).catch(() => null);
  } catch (err) {
    renderError(loadingWrap, err);
    return;
  }
  loadingWrap.remove();

  headHost.appendChild(sectionHead(`SLATE · ${payload.date || useDate}`,
    `${payload.checked_games} GAMES CHECKED · ALL TIMES ET`));

  const markets = new Map();
  for (const game of (odds && odds.games) || []) {
    if (game.markets && game.markets.h2h) markets.set(game.game_id, game.markets.h2h);
  }

  const rows = payload.games || [];
  if (rows.length === 0) {
    const empty = el("div", { class: "screen-state" });
    const gate = el("section", { class: "gate chamfer", "data-hook": "games-empty" });
    gate.appendChild(el("p", { class: "gate__eyebrow", text: "NOTHING SCHEDULED" }));
    gate.appendChild(el("p", { class: "gate__title", text: "No games on this slate." }));
    gate.appendChild(el("p", { class: "gate__body",
      text: `${payload.checked_games} games checked for this date. There is nothing to price.` }));
    empty.appendChild(gate);
    screen.appendChild(empty);
  } else {
    const grid = el("div", { class: "games-grid" });
    let i = 0;
    for (const row2 of rows) {
      const h2h = markets.get(row2.game_id) || null;
      const best = h2h && h2h.best ? h2h.best : {};
      grid.appendChild(slateTile(Object.assign({ date: payload.date || useDate }, row2), {
        awayPrice: best.away ? best.away.price : null,
        homePrice: best.home ? best.home.price : null,
        delay: (i % 6) * 70,
      }));
      i += 1;
    }
    screen.appendChild(grid);
  }

  // Board freshness for the slate, verbatim from the payload.
  const first = rows[0];
  if (first) {
    const staleHost = el("section", { class: "gutter", "data-hook": "slate-freshness" });
    staleHost.appendChild(renderStaleness(first.board_summary));
    screen.appendChild(staleHost);
    setShellStatusFromStaleness(first.board_summary);
  }

  for (const note of payload.notes || []) {
    screen.appendChild(el("p", { class: "gutter changed__sub", text: note }));
  }
  armEntrances(screen);
}

/* =====================================================================
 * Game view -- header
 * ===================================================================*/

function readSection(advanced, name) {
  const sections = advanced && typeof advanced.sections === "object" ? advanced.sections : {};
  const value = sections ? sections[name] : undefined;
  return value === undefined ? null : value;
}

function gapReason(advanced, name) {
  const gaps = advanced && typeof advanced.gaps === "object" ? advanced.gaps : {};
  return gaps && gaps[name] ? String(gaps[name]) : null;
}

function headerSide(abbr, record, probable, home) {
  const side = el("div", { class: `gv-head__side${home ? " gv-head__side--home" : ""}` });
  side.appendChild(el("div", { class: "gv-head__wordmark", text: abbr }));
  if (teamColors(abbr).known) side.appendChild(el("div", { class: "gv-head__rule" }));
  if (record || probable) {
    const line = el("div", { class: "gv-head__line" });
    const parts = home
      ? [probable ? el("span", { class: "gv-head__probable", text: probable }) : null,
         record ? el("span", { class: "gv-head__record", text: record }) : null]
      : [record ? el("span", { class: "gv-head__record", text: record }) : null,
         probable ? el("span", { class: "gv-head__probable", text: probable }) : null];
    for (const p of parts) if (p) line.appendChild(p);
    side.appendChild(line);
  }
  return side;
}

function gameHeader(quick, advanced) {
  const game = advanced && typeof advanced.game === "object" ? advanced.game : null;
  const teams = readSection(advanced, "teams");
  const away = quick.away_team;
  const home = quick.home_team;

  const header = el("section", { class: "gv-head", "data-hook": "game-header" });
  header.setAttribute("style",
    `--team-a:${seamGradient(away, 148)};--team-b:${seamGradient(home, 206)};`
    + `--rule-a:${teamColors(away).accent};--rule-b:${teamColors(home).accent}`);
  header.appendChild(el("div", { class: "gv-head__half gv-head__half--a" }));
  header.appendChild(el("div", { class: "gv-head__half gv-head__half--b" }));
  header.appendChild(el("div", { class: "tex-scanline" }));
  header.appendChild(el("div", { class: "tex-carbon" }));
  header.appendChild(el("div", { class: "hero__wash" }));
  header.appendChild(el("div", { class: "hero__seam" }));

  const eyebrow = el("div", { class: "hero__eyebrow", "data-rise": "" });
  eyebrow.appendChild(el("span", { class: "hero__tick" }));
  const bits = ["GAME VIEW"];
  const start = game ? formatEasternTime(game.start_time_utc) : null;
  if (start) bits.push(start);
  if (game && game.venue) bits.push(String(game.venue).toUpperCase());
  eyebrow.appendChild(el("span", { class: "hero__kicker", text: bits.join(" · ") }));
  header.appendChild(eyebrow);

  const record = (key) => {
    if (!teams || typeof teams !== "object") return null;
    const w = teams[`${key}_wins`];
    const l = teams[`${key}_losses`];
    return typeof w === "number" && typeof l === "number" ? `${w}-${l}` : null;
  };
  const row = el("div", { class: "gv-head__row", "data-rise": "", "data-delay": "80" });
  row.appendChild(headerSide(away, record("away"),
    game && game.away_probable ? String(game.away_probable).toUpperCase() : null, false));
  row.appendChild(el("span", { class: "hero__vs-mark", text: "VS" }));
  row.appendChild(headerSide(home, record("home"),
    game && game.home_probable ? String(game.home_probable).toUpperCase() : null, true));
  header.appendChild(row);
  return header;
}

/* =====================================================================
 * Quick View
 * ===================================================================*/

function factorLine(finding) {
  if (typeof finding === "string") return { text: finding, sample: null, caution: false };
  if (!finding || typeof finding !== "object") return { text: String(finding), sample: null, caution: false };
  const text = finding.text || finding.claim || finding.headline || finding.summary || null;
  const sample = finding.sample
    || (finding.sample_n !== undefined && finding.sample_n !== null ? `n = ${finding.sample_n}` : null);
  // A finding is only shown as a caution when the payload says so -- an
  // ordinary fact is never dressed up as a warning (Integrity Rule 1).
  const caution = finding.direction === "against" || finding.caution === true;
  return { text, sample, caution, raw: finding };
}

function renderWhyItMatters(quick) {
  const panel = el("section", { class: "gv-panel gv-panel--case chamfer", "data-hook": "top-findings",
    "data-rise": "" });
  panel.appendChild(el("h2", { class: "gv-panel__title", text: "WHY THIS GAME MATTERS" }));
  const findings = quick.top_findings || [];
  if (findings.length === 0) {
    // Honest empty state: the factor list collapses to one line rather
    // than being padded (handoff section 10, Game Quick EMPTY).
    panel.appendChild(el("p", { class: "gv-panel__body", "data-hook": "quick-summary",
      text: quick.summary || "Nothing notable in this game." }));
    return panel;
  }
  const list = el("ul", { class: "bc-lines" });
  for (const finding of findings) {
    const { text, sample, caution, raw } = factorLine(finding);
    const row = el("li", { class: "bc-line" });
    row.appendChild(el("span", {
      class: `bc-line__mark chamfer chamfer--marker bc-line__mark--${caution ? "no" : "yes"}`,
      "aria-hidden": "true", text: caution ? "!" : "✓",
    }));
    if (text) row.appendChild(el("span", { text }));
    else row.appendChild(renderUnknown(raw));
    if (sample) row.appendChild(el("span", { class: "bc-line__n", text: sample }));
    list.appendChild(row);
  }
  panel.appendChild(list);
  if (quick.summary) {
    panel.appendChild(el("p", { class: "gv-panel__meta", text: quick.summary }));
  }
  return panel;
}

function renderThePrice(quick) {
  const price = quick.price || {};
  const panel = el("section", { class: "bc-price chamfer", "data-hook": "price", "data-price": "" });
  panel.appendChild(el("span", { class: "tex-scanline" }));

  if (!price.available) {
    const body = el("div", { class: "bc-price__row" });
    body.appendChild(el("p", { class: "pricebug__none",
      text: price.reason || "No book has posted a price on this game yet." }));
    panel.appendChild(body);
    return panel;
  }

  const sides = price.sides || {};
  const away = sides.away || {};
  const home = sides.home || {};
  const row = el("div", { class: "bc-price__row" });
  row.appendChild(el("span", { class: "bc-price__figure", "data-hook": "best-price", "data-beat": "",
    text: formatAmerican(away.best_price) || "" }));

  const awayCell = el("div", { class: "bc-price__cell" });
  awayCell.appendChild(el("div", { class: "bc-price__cell-label",
    text: `${quick.away_team} BEST · ${formatBook(away.best_book) || ""}`.trim() }));
  awayCell.appendChild(el("div", { class: "bc-price__cell-value",
    text: formatConsensusShare(away.consensus_probability)
      ? `CONSENSUS ${formatConsensusShare(away.consensus_probability)}` : "" }));
  row.appendChild(awayCell);

  const homeCell = el("div", { class: "bc-price__cell" });
  homeCell.appendChild(el("div", { class: "bc-price__cell-label",
    text: `${quick.home_team} BEST · ${formatBook(home.best_book) || ""}`.trim() }));
  homeCell.appendChild(el("div", { class: "bc-price__cell-value",
    text: formatAmerican(home.best_price) || "" }));
  row.appendChild(homeCell);

  row.appendChild(el("span", { class: "bc-price__spacer" }));

  const aside = el("div", { class: "bc-price__aside" });
  // The advantage pill appears only where a side genuinely beats the
  // market-implied consensus. On most boards no side does, and the pill
  // is then absent rather than greyed.
  const positive = [["away", away], ["home", home]]
    .filter(([, s]) => typeof s.improvement_probability_points === "number"
      && s.improvement_probability_points > 0)
    .sort((a, b) => b[1].improvement_probability_points - a[1].improvement_probability_points)[0];
  if (positive) {
    const [key, side] = positive;
    aside.appendChild(el("span", { class: "advantage-pill chamfer chamfer--badge",
      "data-hook": "advantage-pill",
      text: `${(side.improvement_probability_points * 100).toFixed(1)} PTS BETTER · ${key === "away" ? quick.away_team : quick.home_team}` }));
  }
  const meta = [];
  if (typeof price.books === "number") meta.push(`BEST OF ${price.books} BOOKS`);
  const age = formatAge(price.staleness && price.staleness.age_seconds);
  if (age) meta.push(`UPDATED ${age}`);
  if (meta.length) aside.appendChild(el("div", { class: "bc-price__aside-meta", text: meta.join("  ·  ") }));
  row.appendChild(aside);
  panel.appendChild(row);

  // The API's own framing of what this number is, verbatim.
  if (price.label) {
    panel.appendChild(el("p", { class: "bc-price__aside-meta", text: String(price.label).toUpperCase() }));
  }
  return panel;
}

/** The API's own explanation of why the improvement figures read the way
 * they do -- prose, in body type, beneath the money panel. Verbatim: it
 * is the sentence that keeps the number honest, so it is never trimmed
 * and never hidden. */
function renderPriceNote(quick) {
  const note = quick.price && quick.price.note ? quick.price.note : null;
  if (!note) return null;
  const wrap = el("p", { class: "price-note", "data-hook": "price-note" });
  wrap.appendChild(el("span", { class: "price-note__label", text: "READ THE PRICE THIS WAY" }));
  wrap.appendChild(document.createTextNode(note));
  return wrap;
}

function renderQuickCards(quick, advanced) {
  const trio = el("div", { class: "gv-trio", "data-rise": "" });

  // DATA SUPPORT -- a qualitative three-step reading, never a percentage
  // and never presented as confidence in an outcome. Absent unless the
  // payload carried one.
  const support = el("section", { class: "gv-panel chamfer" });
  support.appendChild(el("h3", { class: "gv-panel__title", text: "DATA SUPPORT" }));
  support.appendChild(notYetAvailable(
    "Data support is a qualitative three-step reading and this game's payload "
    + "carries none, so no level is shown rather than one being estimated.",
    "NOT RECORDED"));
  trio.appendChild(support);

  // THE STRONGEST PART
  const strongest = el("section", { class: "gv-panel gv-panel--case chamfer" });
  strongest.appendChild(el("h3", { class: "gv-panel__title", text: "THE STRONGEST PART" }));
  if (quick.headline) {
    strongest.appendChild(el("p", { class: "gv-panel__body", "data-hook": "quick-headline",
      text: quick.headline }));
  } else {
    strongest.appendChild(notYetAvailable(
      "No factor in this game's evidence was identified as the most durable one.",
      "NOT DISTINGUISHED"));
  }
  trio.appendChild(strongest);

  // WHAT COULD BURN YOU -- structurally required to appear, heading and
  // red edge rule intact (Integrity Rule 1). Never padded with an
  // invented risk, never hidden.
  const burn = el("section", { class: "gv-panel gv-panel--risk chamfer", "data-hook": "what-could-burn-you" });
  burn.appendChild(el("h3", { class: "gv-panel__title gv-panel__title--risk", text: "WHAT COULD BURN YOU" }));
  const cautions = (quick.top_findings || []).map(factorLine).filter((f) => f.caution && f.text);
  if (cautions.length) {
    const list = el("ul", { class: "bc-lines" });
    for (const c of cautions) list.appendChild(el("li", { class: "bc-line" }, [
      el("span", { class: "bc-line__mark chamfer chamfer--marker bc-line__mark--no",
        "aria-hidden": "true", text: "!" }),
      el("span", { text: c.text }),
    ]));
    burn.appendChild(list);
  } else {
    const reasons = ["matchup_depth", "lineups", "bullpen"]
      .map((name) => gapReason(advanced, name)).filter(Boolean);
    burn.appendChild(notYetAvailable(
      reasons.length
        ? "No material concern was identified. The factors that would surface one are "
          + "not ingested for this game: " + reasons.join("; ") + "."
        : "No material concern was identified for this game.",
      "NONE IDENTIFIED"));
  }
  trio.appendChild(burn);
  return trio;
}

function renderHistoricalEvidence(quick) {
  const panel = el("section", { class: "gv-panel chamfer", "data-hook": "historical-evidence",
    "data-rise": "" });
  panel.appendChild(el("h3", { class: "gv-panel__title gv-panel__title--mute", text: "HISTORICAL EVIDENCE" }));
  panel.appendChild(el("p", { class: "gv-panel__body",
    text: quick.headline || "Nothing here has been measured against outcomes yet." }));
  panel.appendChild(el("p", { class: "gv-panel__meta",
    text: "27 PRE-REGISTERED HYPOTHESES MEASURED · NONE SURVIVED · NOT FORWARD TESTED" }));
  return panel;
}

/* =====================================================================
 * Advanced -- six blocks, appended beneath Quick
 * ===================================================================*/

function advBlock(no, title) {
  const block = el("section", { class: "gv-adv__block chamfer" });
  const head = el("div", { class: "gv-adv__head" });
  head.appendChild(el("span", { class: "gv-adv__no", text: no }));
  head.appendChild(el("h3", { class: "gv-adv__title", text: title }));
  head.appendChild(el("span", { class: "gv-adv__hair" }));
  block.appendChild(head);
  return block;
}

function stat(label, value, sample) {
  const cell = el("div", { class: "gv-stat chamfer" });
  cell.appendChild(el("div", { class: "gv-stat__label", text: label }));
  cell.appendChild(el("div", { class: "gv-stat__value" }, [
    value === null || value === undefined ? renderUnknown(null) : document.createTextNode(String(value)),
  ]));
  // Every rate, average or percentage ships with its n adjacent to it.
  if (sample) cell.appendChild(el("div", { class: "gv-stat__n", text: sample }));
  return cell;
}

function renderAdvanced(advanced, quick) {
  const host = el("div", { class: "gv-adv", "data-hook": "game-advanced" });
  const consumed = new Set();

  // 01 STARTING PITCHERS
  const pitchers = advBlock("01", "STARTING PITCHERS");
  const starters = readSection(advanced, "starters");
  if (starters) { consumed.add("starters"); pitchers.appendChild(renderUnknown(starters)); }
  else {
    pitchers.appendChild(notYetAvailable(
      gapReason(advanced, "starters") || "Starter logs are not built for this slate.",
      "NOT INGESTED"));
  }
  pitchers.appendChild(notYetAvailable(
    "Pitch mix, velocity trend, xFIP and xwOBA -- not ingested from a verified "
    + "source yet, so nothing is shown rather than estimated.", "NOT INGESTED"));
  host.appendChild(pitchers);

  // 02 LINEUPS
  const lineups = advBlock("02", "LINEUPS");
  const lineupSection = readSection(advanced, "lineups");
  if (lineupSection) { consumed.add("lineups"); lineups.appendChild(renderUnknown(lineupSection)); }
  else {
    lineups.appendChild(notYetAvailable(
      gapReason(advanced, "lineups") || "No lineup has been posted or fetched for this game.",
      "NOT POSTED"));
  }
  host.appendChild(lineups);

  // 03 BULLPEN
  const bullpen = advBlock("03", "BULLPEN");
  const bullpenSection = readSection(advanced, "bullpen");
  if (bullpenSection) { consumed.add("bullpen"); bullpen.appendChild(renderUnknown(bullpenSection)); }
  else {
    bullpen.appendChild(notYetAvailable(
      gapReason(advanced, "bullpen") || "Bullpen workload is not built for this slate.",
      "NOT INGESTED"));
  }
  host.appendChild(bullpen);

  // 04 MARKET -- the full board, plus the de-vig framing stated as what
  //    it is: the market's own implied share with the margin removed.
  const market = advBlock("04", "MARKET");
  const board = readSection(advanced, "multibook_board");
  if (board && Array.isArray(board.quotes) && board.quotes.length) {
    consumed.add("multibook_board");
    const scroll = el("div", { class: "board-scroll chamfer" });
    const table = el("table", { class: "board-table" });
    const thead = el("thead");
    const hr = el("tr");
    for (const label of ["Book", quick.away_team, quick.home_team]) {
      hr.appendChild(el("th", { scope: "col", text: label }));
    }
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = el("tbody");
    for (const quote of board.quotes) {
      const tr = el("tr");
      tr.appendChild(el("td", { text: formatBook(quote.book) || "" }));
      tr.appendChild(el("td", { text: formatAmerican(quote.away_price) || "" }));
      tr.appendChild(el("td", { text: formatAmerican(quote.home_price) || "" }));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    scroll.appendChild(table);
    market.appendChild(scroll);
  } else {
    market.appendChild(notYetAvailable(
      gapReason(advanced, "market") || "No prices on the board for this game.", "NO BOARD"));
  }
  const improvement = readSection(advanced, "price_improvement");
  if (improvement) {
    consumed.add("price_improvement");
    const stats = el("div", { class: "gv-stats" });
    const sides = improvement.sides || {};
    const books = improvement.dispersion && improvement.dispersion.books;
    for (const [key, label] of [["away", quick.away_team], ["home", quick.home_team]]) {
      const side = sides[key] || {};
      stats.appendChild(stat(`${label} BEST`, formatAmerican(side.best_price),
        side.best_book ? formatBook(side.best_book) : null));
      stats.appendChild(stat(`${label} MARKET-IMPLIED CONSENSUS`,
        formatConsensusShare(side.consensus_probability),
        books ? `n = ${books} books` : null));
    }
    market.appendChild(stats);
    // The improvement note is already printed once, in reading language,
    // beneath the Quick View price panel. Printing it again here would
    // be the same sentence twice on one screen.
  }
  host.appendChild(market);

  // 05 CONTEXT
  const context = advBlock("05", "CONTEXT");
  const park = readSection(advanced, "park");
  const teams = readSection(advanced, "teams");
  const stats = el("div", { class: "gv-stats" });
  if (park) {
    consumed.add("park");
    stats.appendChild(stat("VENUE", park.name, null));
    stats.appendChild(stat("ROOF", park.roof, null));
    stats.appendChild(stat("ALTITUDE (M)", park.altitude_m, null));
  }
  if (teams) {
    consumed.add("teams");
    stats.appendChild(stat(`${quick.away_team} REST`, teams.away_rest_days,
      typeof teams.away_games_played === "number" ? `n = ${teams.away_games_played} games` : null));
    stats.appendChild(stat(`${quick.home_team} REST`, teams.home_rest_days,
      typeof teams.home_games_played === "number" ? `n = ${teams.home_games_played} games` : null));
    stats.appendChild(stat(`${quick.away_team} RUN DIFF / G`, teams.away_run_diff_pg,
      typeof teams.away_games_played === "number" ? `n = ${teams.away_games_played} games` : null));
    stats.appendChild(stat(`${quick.home_team} RUN DIFF / G`, teams.home_run_diff_pg,
      typeof teams.home_games_played === "number" ? `n = ${teams.home_games_played} games` : null));
  }
  if (stats.childNodes.length) context.appendChild(stats);
  const weather = gapReason(advanced, "weather");
  if (weather) context.appendChild(notYetAvailable(weather, "NOT FETCHED"));
  const travel = gapReason(advanced, "travel");
  if (travel) context.appendChild(notYetAvailable(travel, "NOT COMPUTED"));
  host.appendChild(context);

  // 06 EVIDENCE AND METHOD
  const evidence = advBlock("06", "EVIDENCE AND METHOD");
  const findings = advanced.findings || [];
  if (findings.length) {
    evidence.appendChild(renderUnknown(findings));
  } else {
    evidence.appendChild(el("p", { class: "gv-panel__body",
      text: "No finding cleared the bar for this game. That is the ordinary outcome, "
          + "not a gap in the scan." }));
  }
  const ladder = el("div", { class: "ladder" });
  for (const rung of ["OBSERVATION", "EXPLORATORY", "HISTORICAL SUPPORT", "FORWARD TESTING", "VALIDATED"]) {
    const rowEl = el("div", { class: "ladder__rung" });
    rowEl.appendChild(el("span", { class: "ladder__bar chamfer" }));
    rowEl.appendChild(el("span", { class: "ladder__name", text: rung }));
    ladder.appendChild(rowEl);
  }
  evidence.appendChild(el("p", { class: "gv-subhead", text: "EVIDENCE LADDER" }));
  evidence.appendChild(ladder);
  evidence.appendChild(notYetAvailable(
    "No rung is lit: this payload reports no evidence status, and nothing in the "
    + "product has reached forward testing. xwOBA, xFIP and every pitch-level or "
    + "velocity-derived claim are not ingested, so no derived metric appears anywhere "
    + "in this view.", "NOT INGESTED"));
  evidence.appendChild(renderStaleness(advanced.staleness));
  host.appendChild(evidence);

  // Anything the six designed blocks did not consume is still shown --
  // verbatim, unread, in the appendix. Nothing is silently dropped.
  const sections = advanced && typeof advanced.sections === "object" ? advanced.sections : {};
  const leftovers = Object.keys(sections).filter((k) => !consumed.has(k));
  if (leftovers.length) {
    const appendix = el("details", { class: "gv-adv__block chamfer gv-appendix",
      "data-hook": "advanced-sections" });
    appendix.appendChild(el("summary", { text: `Other sections (${leftovers.length})` }));
    const body = el("div", { class: "gv-appendix__body" });
    for (const key of leftovers) {
      body.appendChild(el("p", { class: "gv-subhead", text: humanizeKey(key) }));
      body.appendChild(renderUnknown(sections[key]));
    }
    appendix.appendChild(body);
    host.appendChild(appendix);
  }

  const gapsAppendix = el("details", { class: "gv-adv__block chamfer gv-appendix",
    "data-hook": "advanced-gaps" });
  gapsAppendix.appendChild(el("summary", { text: "Everything not ingested for this game" }));
  gapsAppendix.appendChild(el("div", { class: "gv-appendix__body" }, [renderUnknown(advanced.gaps)]));
  host.appendChild(gapsAppendix);

  return host;
}

/* =====================================================================
 * Game view
 * ===================================================================*/

export async function renderGameDetail(container, date, away, home) {
  clear(container);
  const screen = el("div", { class: "screen", "data-view": "game" });
  container.appendChild(screen);
  const loadingWrap = el("div", { class: "screen-state" }, [renderLoading("LOADING THIS GAME")]);
  screen.appendChild(loadingWrap);

  let payload;
  try {
    payload = await apiGet(
      `/game/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`);
  } catch (err) {
    renderError(loadingWrap, err);
    return;
  }
  loadingWrap.remove();

  const quick = payload.quick || {};
  const advanced = payload.advanced || {};
  screen.appendChild(gameHeader(quick, advanced));

  const body = el("div", { class: "gv-body" });
  body.appendChild(el("a", { class: "gv-back", href: `#/games/${encodeURIComponent(date)}`,
    text: "← BACK TO THE SLATE" }));
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: "QUICK VIEW" }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  const chip = el("span", { class: `badge chamfer chamfer--chip ${verdictChipClass(quick.verdict)}`,
    "data-hook": "verdict", "data-verdict-raw": quick.verdict || "" });
  chip.appendChild(quick.verdict ? document.createTextNode(verdictLabel(quick.verdict)) : renderUnknown(null));
  head.appendChild(chip);
  head.appendChild(el("span", { class: "sechead__meta", text: "PLAIN ENGLISH · 30 SECONDS" }));
  body.appendChild(head);

  body.appendChild(renderWhyItMatters(quick));
  body.appendChild(renderThePrice(quick));
  const priceNote = renderPriceNote(quick);
  if (priceNote) body.appendChild(priceNote);
  body.appendChild(renderQuickCards(quick, advanced));
  body.appendChild(renderHistoricalEvidence(quick));

  // ADVANCED APPENDS BENEATH QUICK -- the toggle only shows/hides this
  // host; Quick View above is never unmounted or re-rendered.
  const toggle = el("button", { type: "button", class: "gv-toggle chamfer",
    "data-hook": "advanced-toggle", "aria-expanded": "false", "aria-controls": "game-advanced-host",
    text: "SHOW ADVANCED ANALYSIS ⌄" });
  body.appendChild(toggle);
  body.appendChild(el("p", { class: "gv-toggle__note", text: "EXPANDS BELOW · QUICK VIEW STAYS OPEN" }));

  const advHost = el("div", { id: "game-advanced-host" });
  advHost.hidden = true;
  advHost.appendChild(el("div", { class: "sechead" }, [
    el("span", { class: "sechead__label sechead__label--live", text: "ADVANCED ANALYSIS" }),
    el("span", { class: "sechead__hair" }),
    el("span", { class: "sechead__meta", text: "EVERY RATE CARRIES ITS SAMPLE SIZE" }),
  ]));
  advHost.appendChild(renderAdvanced(advanced, quick));
  body.appendChild(advHost);

  toggle.addEventListener("click", () => {
    const open = advHost.hidden;
    advHost.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "HIDE ADVANCED ANALYSIS ⌃" : "SHOW ADVANCED ANALYSIS ⌄";
  });

  const actions = el("div", { class: "bc-bottom__actions" });
  actions.appendChild(el("a", {
    href: `#/betcheck?date=${encodeURIComponent(date)}&away=${encodeURIComponent(away)}&home=${encodeURIComponent(home)}`,
    class: "btn btn--cyan chamfer chamfer--btn on-live", "data-hook": "go-to-bet-check",
    text: "CHECK A BET ON THIS GAME",
  }));
  actions.appendChild(el("a", {
    href: `#/odds/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`,
    class: "btn btn--ghost chamfer chamfer--btn", text: "COMPARE BOOKS",
  }));
  body.appendChild(actions);

  screen.appendChild(body);
  setShellStatusFromStaleness(advanced.staleness);
  armEntrances(screen);
}
