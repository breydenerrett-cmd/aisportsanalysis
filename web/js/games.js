/**
 * GAMES -- the slate (#/games/{date}) and one game
 * (#/game/{date}/{away}/{home}), from api/games.py /
 * src/analysis/gamepayload.py.
 *
 * LANE L21 -- the one-game view is rebuilt to LINEHOUND V2, tracing the
 * frozen design/linehound-v2/'LINEHOUND V2 Full Product.dc.html'
 * artboards V2-03 (COVERAGE LEDGER, lines 2625-3016), V2-13/14/15 (GAME
 * QUICK desktop/mobile/absent-states, lines 4398-4824), V2-31 (GAME
 * ADVANCED mobile, lines 6450-6560) and V2-34 (GAME SPOTLIGHT ON PRICE
 * STANDING, lines 7352-7522). See
 * design/linehound-v2/IMPLEMENTATION_MANIFEST.json's entries for the
 * exact field ledger this file's comments restate inline.
 *
 * COMPOSITION (one game route)
 * -------------------------------------------------------------------
 *   top strip        GAME · QUICK VIEW  ·  PRICES CAPTURED <time>
 *   identity         team badges, records, probables (absent-safe), VS
 *   verdict          NO_EDGE_HEADLINE / the top finding's own statement,
 *                    plus FINDINGS / EVIDENCE mini tiles
 *   price            best-available + market-implied consensus + price
 *                    improvement, BOTH sides (or V2-15's amber absent
 *                    treatment when price.available is false)
 *   spotlight        V2-34 -- the shared Featured Bet primitive
 *                    (featuredbet.js's renderFeaturedBet), fed this
 *                    game's own quick/advanced fields -- see
 *                    `mapGameToStanding`'s docstring for exactly what
 *                    this endpoint can and cannot honestly fill
 *   teams            records/win-pct/RS-RA-per-game/last-5/last-10,
 *                    every rate with its sample n
 *   actions          CHECK A BET ON THIS GAME / OPEN THE FULL BOARD
 *   [toggle]         SHOW ADVANCED ANALYSIS -- APPENDS beneath, never
 *                    replaces or re-renders Quick View (handoff rule)
 *   advanced         V2-03/31 COVERAGE LEDGER -- the real sections
 *                    dynamically listed, the real gaps (whatever the
 *                    payload's `gaps` object actually names, printed
 *                    with their own reason strings verbatim), a plain
 *                    book-versus-book table, a market-refusal note
 *
 * THE 11-GAP LEDGER IS RENDERED DYNAMICALLY, NEVER HARDCODED
 * -------------------------------------------------------------------
 * The V2-03/V2-31 artboards print their OWN example gap-name list (see
 * the .dc.html source at the manifest's line ranges) -- it is STALE and
 * does not match the real API's gap keys at current HEAD (`arsenals,
 * bullpen, lineups, market, matchup_depth, matchup_history, news,
 * splits, starters, travel, weather` -- 11 keys, 5 real sections; see
 * design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md's PRIORITY
 * ANSWER 2). This file never hardcodes either list: `gavHave`/`gavGaps`
 * below walk `advanced.sections`/`advanced.gaps` as they actually arrive
 * on the wire, so a future change to either object's keys is reflected
 * automatically rather than silently drifting from what the ledger
 * claims.
 *
 * THE SLATE LIST (renderGamesList) IS UNCHANGED / OUT OF SCOPE
 * -------------------------------------------------------------------
 * The nine-artboard game family covers Quick/Advanced/the ledger/the
 * spotlight for ONE game, not the slate grid -- as the pre-existing
 * comment here already noted, the slate list has no V2 artboard of its
 * own in this manifest. It keeps reusing the Gameday-style tile grid
 * from web/js/tiles.js untouched by this lane's work.
 *
 * FIELDS THIS SCREEN CANNOT BIND (never invented, always the honest
 * absent treatment): starter stat lines (FIP/ERA/WHIP -- B, CLI-only
 * pipeline), bullpen workload (B), weather (D -- never rendered live),
 * lineups pre-posting, matchup history, news, travel -- each of these is
 * one of the real `advanced.gaps` keys and renders with the API's own
 * reason string, never a placeholder. See `mapGameToStanding`'s
 * docstring for the spotlight's own, separate set of fields it cannot
 * honestly fill from this endpoint (PRICE STANDING, SUPPORT VS CONCERN,
 * evidence status) -- flagged in the L21 report for the orchestrator.
 */

import { apiGet } from "./api.js";
import { el, clear, renderAbsent, humanizeKey,
  verdictLabel, formatAmerican, formatBook,
  formatEasternTime, formatEasternClock, renderWordChip } from "./dom.js";
import { renderLoadingSkeleton, renderError, notYetAvailable } from "./states.js";
import { renderFeaturedBet } from "./featuredbet.js";
import { renderGameStory } from "./gamestory.js";
import { renderValueMeter } from "./valuemeter.js";
import { renderStaleness } from "./meta.js";
import { teamColors } from "./teamcolors.js";
import { teamName, bookLabel } from "./labels.js";
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
 * The slate list -- unchanged (no V2 artboard of its own; see docstring)
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
  const loadingWrap = el("div", { class: "screen-state" }, [renderLoadingSkeleton({
    eyebrow: "LOADING", headline: "LOADING THE SLATE", rows: 5 })]);
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
      // THE KNOWLEDGE GRADE rides the tile's one flag slot on this screen:
      // how complete our read of the game is (src/analysis/grade.py), the
      // sentence behind it on hover. Never `money` -- a grade is a fact
      // about what we hold, not a price advantage.
      const knowledge = row2.knowledge || null;
      const flag = knowledge && knowledge.grade
        ? { text: knowledge.grade, title: knowledge.why || "",
            kind: /^[AB]/.test(knowledge.grade) ? "live" : "neutral" }
        : null;
      grid.appendChild(slateTile(Object.assign({ date: payload.date || useDate }, row2), {
        awayPrice: best.away ? best.away.price : null,
        homePrice: best.home ? best.home.price : null,
        flag,
        delay: (i % 6) * 70,
      }));
      i += 1;
    }
    screen.appendChild(grid);
    // What the letter on each tile means -- served with the slate, never
    // typed here.
    if (Array.isArray(payload.knowledge_legend) && payload.knowledge_legend.length) {
      const legend = el("section", { class: "gutter games-grade-legend",
        "data-hook": "games-grade-legend" });
      for (const line of payload.knowledge_legend) {
        legend.appendChild(el("p", { class: "games-grade-legend__line", text: line }));
      }
      screen.appendChild(legend);
    }
  }

  // Board freshness for the slate, verbatim from the payload.
  const first = rows[0];
  if (first) {
    const staleHost = el("section", { class: "gutter", "data-hook": "slate-freshness" });
    staleHost.appendChild(renderStaleness(first.board_summary));
    screen.appendChild(staleHost);
    setShellStatusFromStaleness(first.board_summary);
  }

  // THE SLATE'S ENGINE NOTES ARE NOT RENDERED HERE, 2026-09-10.
  //
  // `briefing.build_slate` attaches the detector engine's own commentary to
  // the payload, and the slate page printed it verbatim under the games. On
  // 2026-09-10 that read:
  //
  //   "1 game(s) cleared the talent bar but had no price on the market they
  //    were routed to. That is a different result from no play, and it is
  //    common: measured on three seasons, more than a third of flagged games
  //    have no first-five market at all."
  //
  //   "No play on the whole slate. That is the normal case, not a failure of
  //    the scan..."
  //
  // TWO PROBLEMS, and the second is the serious one.
  //
  // It is jargon -- "talent bar", "routed to", "first-five market" are our
  // words for our machinery, and the owner's instruction about this exact
  // page was "keep it minimal, to the point... most of these people are
  // degenerates and even have a hard time reading English."
  //
  // And it CONTRADICTED THE CARD. "No play on the whole slate" was printed
  // beneath a slate on which the published card held three picks -- TB@ATL,
  // HOU@PHI and COL@NYY were all on it. The detector engine and the card are
  // different systems answering different questions, and a reader does not
  // reconcile that; they pick the half they like. It is the same defect
  // tests/test_today_one_answer.py was written for, on a different screen.
  //
  // Nothing is lost: these notes are the OPERATOR's view and still print in
  // the CLI briefing, which is where they were written for.
  armEntrances(screen);
}

/* =====================================================================
 * Shared field readers
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

/** "4:12pm ET" -- same compact style web/js/odds.js already established
 * for this product; kept as its own tiny copy here rather than an
 * import, matching the pattern web/js/states.js's docstring calls out
 * (each screen's own display threshold/format is that screen's call,
 * not a shared constant to reach across module boundaries for). */
function etClock(isoUtc) {
  const clock = formatEasternClock(isoUtc);
  return clock ? `${clock} ET` : null;
}

/* =====================================================================
 * GAME QUICK VIEW V2 -- V2-13 (desktop) / V2-14 (mobile) / V2-15 (the
 * two amber absent states: unannounced starters, no price board)
 * ===================================================================*/

function gqvBadge(abbr) {
  const colors = teamColors(abbr);
  const badge = el("span", { class: "gqv-badge", "aria-hidden": "true", text: abbr || "" });
  badge.style.background = colors.known ? colors.primary : "#232830";
  badge.style.color = colors.known ? colors.accent : "#D5D7DE";
  return badge;
}

function gqvTopStrip(quick) {
  const strip = el("div", { class: "gqv-topstrip", "data-rise": "" });
  strip.appendChild(el("span", { class: "gqv-topstrip__eyebrow", text: "GAME · QUICK VIEW" }));
  strip.appendChild(el("span", { class: "gqv-topstrip__rule" }));
  const price = quick.price || {};
  const captured = price.available ? etClock(price.staleness && price.staleness.observed_utc) : null;
  if (captured) {
    strip.appendChild(el("span", { class: "gqv-topstrip__chip", "data-hook": "prices-captured",
      text: `PRICES CAPTURED ${captured}` }));
  }
  return strip;
}

function teamRecordParts(teams, key) {
  if (!teams) return { text: null, sample: null };
  const w = teams[`${key}_wins`];
  const l = teams[`${key}_losses`];
  const n = teams[`${key}_games_played`];
  const text = (typeof w === "number" && typeof l === "number") ? `${w}-${l}` : null;
  const sample = typeof n === "number" ? `${n} games` : null;
  return { text, sample };
}

function gqvTeamColumn(abbr, teams, key, probable, home) {
  const col = el("div", { class: `gqv-team${home ? " gqv-team--home" : ""}` });
  col.appendChild(gqvBadge(abbr));
  col.appendChild(el("div", { class: "gqv-team__name", text: teamName(abbr, "full") || abbr || "" }));
  const { text, sample } = teamRecordParts(teams, key);
  const rec = el("div", { class: "gqv-team__record" });
  if (text) {
    rec.appendChild(el("span", { class: "gqv-team__record-figure", text }));
    if (sample) rec.appendChild(el("span", { class: "gqv-team__n", text: sample }));
  } else {
    rec.appendChild(renderAbsent());
  }
  col.appendChild(rec);
  if (probable) {
    col.appendChild(el("div", { class: "gqv-team__probable", text: probable.toUpperCase() }));
  } else {
    col.appendChild(el("div", { class: "gqv-team__probable gqv-team__probable--absent",
      "data-hook": "probable-absent", text: "NOT ANNOUNCED" }));
  }
  return col;
}

function gqvIdentity(quick, advanced) {
  const game = advanced && typeof advanced.game === "object" ? advanced.game : null;
  const teams = readSection(advanced, "teams");
  const away = quick.away_team;
  const home = quick.home_team;
  const awayProbable = game && game.away_probable ? String(game.away_probable) : null;
  const homeProbable = game && game.home_probable ? String(game.home_probable) : null;

  const wrap = el("section", { class: "gqv-identity panel chamfer", "data-hook": "game-identity",
    "data-rise": "", "data-delay": "40" });
  const row = el("div", { class: "gqv-identity__row" });
  row.appendChild(gqvTeamColumn(away, teams, "away", awayProbable, false));
  row.appendChild(el("span", { class: "gqv-vs", "aria-hidden": "true", text: "VS" }));
  row.appendChild(gqvTeamColumn(home, teams, "home", homeProbable, true));
  wrap.appendChild(row);

  const meta = [];
  const start = game ? formatEasternTime(game.start_time_utc) : null;
  if (start) meta.push(start);
  if (game && game.venue) meta.push(String(game.venue).toUpperCase());
  if (meta.length) wrap.appendChild(el("div", { class: "gqv-identity__meta", text: meta.join(" · ") }));

  // V2-15's "PROBABLES · UNANNOUNCED" amber absence -- only when NEITHER
  // side has one (a real per-team "NOT ANNOUNCED" label above already
  // covers the asymmetric case honestly without a whole-panel callout).
  if (!awayProbable && !homeProbable) {
    wrap.appendChild(notYetAvailable(
      "Starters not posted yet for this game. The field is absent, not empty — we show "
      + "nothing rather than a placeholder name. Records and splits above are unaffected.",
      "UNANNOUNCED"));
  }
  // F-2 (docs/DEMO_SHIP_CHECKLIST.md): this deployment ships without the
  // historical feature stores, so `teams` is absent on every game, not
  // just this one -- a real, structural gap, never a per-game failure.
  // The bare per-field `notYetAvailable(gapReason(...))` used to print
  // the store's own internal reason ("no historical results store")
  // as the FIRST thing a visitor sees under the matchup identity, which
  // reads as broken rather than designed. One calm, honest line in the
  // same amber/absence slot instead -- it still says plainly what is
  // missing, it just does not lead with an error string. The Advanced
  // view's own consolidated `gavGapsConsolidated` panel is untouched.
  if (!teams) {
    wrap.appendChild(notYetAvailable(
      "Team records and form are not in this build. The board, the price read and the frozen "
      + "engine record below are.",
      "NOT IN THIS BUILD"));
  }
  return wrap;
}

// The big word for a game with no finding. It was "NO DEMONSTRATED EDGE"
// until 2026-09-10, which is precise, true, and unreadable: "edge" and
// "demonstrated" are both terms of art, and a reader who has just been shown
// a bet on the card screen has no idea whether this contradicts it. It does
// not -- it says this particular matchup has no angle worth writing up --
// and now it says that in words. The API's own sentence underneath is
// unchanged and still rendered verbatim.
const NOTHING_STANDS_OUT = "NOTHING STANDS OUT HERE";

/** Big verdict word + the API's own headline sentence + FINDINGS/EVIDENCE
 * mini tiles. The big word, and the sentence
 * beneath it, are `quick.headline` when `top_findings` is empty --
 * literally `synthesis.NO_EDGE_HEADLINE` on the wire ("Interesting
 * matchup, but no demonstrated betting edge.", `src/analysis/
 * synthesis.py:186,250`) -- so this never composes new copy for the
 * dominant no_play state, it prints the API's own sentence and echoes
 * its key phrase as the oversized label the artboard specifies.
 * EVIDENCE reads the TOP FINDING's own real `evidence_label` (Proven /
 * Forward testing / Provisional / Tuning evidence / Candidate /
 * Unproven -- `synthesis.EVIDENCE_LABELS`) rather than the artboard's
 * "OBSERVATION" example, which is Bet Check's OWN, differently-scaled
 * evidence-status ladder (`contracts.py`'s Observation/Exploratory/...)
 * -- a distinct vocabulary this endpoint does not carry, never conflated
 * here. */
/* REMOVED 2026-09-10 -- the panel this comment describes no longer exists.
 *
 * It was the FIRST thing on a game screen, and on the overwhelming majority
 * of games it read, in oversized type: NOTHING STANDS OUT HERE, then
 * "Interesting matchup, but no demonstrated betting edge.", then a FINDINGS
 * tile reading 0.
 *
 * Every word of that is true and it is the worst possible thing to open
 * with. A reader who taps a game and is told immediately that nothing stands
 * out has been given no reason to read the next screen, and the product's
 * actual answer -- the day's three to five picks -- was nowhere on the page.
 *
 * `gqvTonightsPick` leads now: this game's pick if it made the card, and one
 * short line if it did not. The no-edge headline is not lost -- it is still
 * the advanced view's own summary line (see NOTHING_STANDS_OUT's remaining
 * use below), which is where a reader who wants the evidence ladder goes. */

/** BEST AVAILABLE / MARKET-IMPLIED CONSENSUS / PRICE IMPROVEMENT for
 * BOTH sides -- deliberately not the artboard's single-side layout (see
 * this file's report note): quick.price.sides carries both away and
 * home, and showing only one would mean choosing a side to feature with
 * no verdict-level basis for most games (no_play carries no `side`),
 * which risks reading as a pick this product does not make. Falls back
 * to V2-15's "PRICE · MARKET UNAVAILABLE" amber absence when
 * `price.available` is false. */
function gqvPrice(quick) {
  const price = quick.price || {};
  const panel = el("section", { class: "gqv-price panel chamfer", "data-hook": "price", "data-price": "",
    "data-rise": "", "data-delay": "120" });
  panel.appendChild(el("div", { class: "gqv-price__eyebrow", text: "PRICE · MONEYLINE" }));

  if (!price.available) {
    panel.appendChild(notYetAvailable(
      price.reason || "No price board recorded for this game.", "MARKET UNAVAILABLE"));
    panel.appendChild(el("p", { class: "gqv-price__footnote",
      text: "No board was recorded for this game, and the feed gives no reason beyond what is shown "
          + "above — so we state the fact and stop. The identity panel above is unaffected." }));
    return panel;
  }

  const sides = price.sides || {};
  const cols = el("div", { class: "gqv-price__cols" });
  for (const [key, label] of [["away", quick.away_team], ["home", quick.home_team]]) {
    const side = sides[key] || {};
    const col = el("div", { class: "gqv-price__col" });
    col.appendChild(el("div", { class: "gqv-price__label", text: `BEST AVAILABLE · ${label}` }));
    const figure = formatAmerican(side.best_price);
    col.appendChild(el("div", { class: "gqv-price__figure", "data-hook": "best-price" },
      [figure ? document.createTextNode(figure) : renderAbsent()]));
    if (side.best_book) col.appendChild(el("div", { class: "gqv-price__book", text: bookLabel(side.best_book) }));

    // THE PRICE, AND WHERE. Nothing else.
    //
    // This column used to carry, under every side: MARKET-IMPLIED CONSENSUS
    // with a percentage, then either a "+0.42 PTS BETTER" pill or the words
    // NO IMPROVEMENT ON THIS SIDE -- which is what it said on nearly every
    // side of nearly every game, since a best available price still carries
    // the book's vig while the consensus it is measured against has had the
    // vig removed. Below that came a paragraph explaining that.
    //
    // The owner, 2026-09-10: "This whole 'we do price verification and see
    // which book has the better odds, dude,' that has to stop. None of
    // that's important. Nobody fucking cares."
    //
    // He is right about the audience. A bettor needs the number and the
    // book. The de-vig arithmetic behind it is ours, it is still in the
    // payload, and it is still rendered under SHOW ADVANCED ANALYSIS for
    // anyone who wants it -- it is no longer the shape of this screen.
    cols.appendChild(col);
  }
  panel.appendChild(cols);

  // `price.note` IS NOT RENDERED HERE any more. On a normally-priced board
  // it is src/analysis/prices.py's NO_IMPROVEMENT_NOTE -- a five-line
  // explanation of why the improvement figures are negative. Those figures
  // no longer appear on this screen, so the paragraph explaining them was
  // explaining something the reader could not see. It still renders in the
  // advanced view, alongside the numbers it is about.
  panel.appendChild(el("p", { class: "gqv-price__disclaimer",
    text: "Prices only — we take no bets. Check the number at the book." }));
  return panel;
}

/* =====================================================================
 * V2-34 -- GAME SPOTLIGHT ON PRICE STANDING
 * The shared Featured Bet primitive (web/js/featuredbet.js), placed as
 * this screen's spotlight per design/linehound-v2/IMPLEMENTATION_PLAN.md
 * Wave 0/Group F. This file NEVER forks that component's markup -- it
 * only builds the `standing` object `renderFeaturedBet` consumes.
 * ===================================================================*/

/**
 * Maps THIS GAME's quick/advanced payload onto featuredbet.js's
 * `standing` shape. This is deliberately NOT
 * `mapBetCheckPayloadToStanding` (featuredbet.js's own mapper for POST
 * /betcheck): that function expects POST /betcheck's response shape
 * (`query`, `price_improvement`, `your_price_beats_consensus`,
 * `thesis_support`, `counterargument`...), and calling POST /betcheck
 * from this screen would require a STATED, priced bet nobody has typed
 * here -- the Game view analyzes a matchup, it does not check a bet.
 * featuredbet.js's own docstring explicitly allows a caller to "build
 * one by hand ... for a fixture/test"; this is that allowance used for
 * production, because it is the only honest option this endpoint gives.
 *
 * SIDE SELECTION -- HONESTY-CRITICAL, READ BEFORE CHANGING
 * -------------------------------------------------------------------
 * `quick.side` names a real side ONLY when the analysis singled one out
 * (`entry.get("side")` in gamepayload.py -- the rare "flagged" verdict,
 * ~2% of games per RECONCILED_CONTRACT_CURRENT_HEAD.md's forward
 * ledger). For the DOMINANT no_play/market_unavailable case there is no
 * side, and this mapper never invents one (e.g. "always away") to fill
 * the card's SIDE/LINE cells -- that would read as a highlighted pick
 * where the system made none, exactly the pattern this product's
 * honesty rule forbids. When no side exists, `query.parsed` stays
 * `true` (nobody mistyped anything -- there is nothing to parse) but
 * `side`/`price`/`team` are `null`, which featuredbet.js's own spec-strip
 * cells already render as NOT AVAILABLE without this file having to ask
 * it to.
 *
 * SEGMENTS THIS ENDPOINT CANNOT HONESTLY FILL
 * -------------------------------------------------------------------
 * - PRICE STANDING ("better than N of M books"): `priceStanding` is left
 *   `null` on every call. `advanced.sections.multibook_board` DOES carry
 *   the raw per-book board (unlike POST /betcheck, which does not) so a
 *   book-count rank is theoretically computable here -- but
 *   featuredbet.js's own docstring treats this segment as reserved for
 *   "a future join with the odds board's raw rows, which is an
 *   engineering request, not something this component does on its own."
 *   Inlining a bespoke rank comparison in this lane, untested anywhere
 *   else in the product, would be new analysis this lane's boundary asks
 *   to avoid ("never compute ... a rank"). Left NOT AVAILABLE for
 *   consistency with the other two placements (Bet Check, Gameday).
 * - SUPPORT VS CONCERN: featuredbet.js hardcodes this row `present: true`
 *   and always prints "N thesis_support / M counterargument" -- correct
 *   for POST /betcheck, where those arrays always exist (even empty),
 *   but this endpoint has NO thesis_support/counterargument concept at
 *   all. `Finding.side` partitioning into support/counter only happens
 *   for a STATED, priced bet (`src/analysis/betcheck.py`'s `check()` /
 *   `build_contract()`), and reproducing it here would also disagree
 *   with what Bet Check itself would say: `build_contract()` excludes
 *   CONTEXT-kind findings via `finding.kind`, a field
 *   `gamepayload.py`'s `_finding_wire` never puts on the wire, so a
 *   client-side partition of `advanced.findings` could overcount versus
 *   the real endpoint for the identical side and price. Rather than risk
 *   a wrong number, `thesisSupportCount`/`counterargumentCount` are both
 *   `0` here -- THIS IS A KNOWN, DOCUMENTED PRIMITIVE LIMITATION, NOT A
 *   CLAIM THAT ZERO ITEMS WERE EVALUATED. Flagged loudly in the L21
 *   report; featuredbet.js would need a caller-supplied override for
 *   this row to render NOT AVAILABLE instead of a number for a screen
 *   with no thesis/counterargument concept.
 * - evidenceStatus: Bet-Check-only vocabulary (`contracts.py`'s
 *   Observation/Exploratory/Historical support/Forward testing/
 *   Validated ladder). Never conflated with this payload's own,
 *   differently-scaled per-finding `evidence_label` -- left `null`,
 *   which the trust strip already renders as NOT AVAILABLE.
 */
function mapGameToStanding(quick, advanced) {
  const price = quick.price || {};
  const side = quick.side === "away" || quick.side === "home" ? quick.side : null;
  const sideDetail = side && price.available ? (price.sides || {})[side] : null;
  const teamAbbr = side === "home" ? quick.home_team : side === "away" ? quick.away_team : null;
  const game = advanced && typeof advanced.game === "object" ? advanced.game : null;
  const improvementPoints = sideDetail && typeof sideDetail.improvement_probability_points === "number"
    ? sideDetail.improvement_probability_points : null;

  return {
    query: {
      raw: (teamAbbr && sideDetail && typeof sideDetail.best_price === "number")
        ? `${teamAbbr} h2h ${formatAmerican(sideDetail.best_price)}` : "",
      parsed: true,
      parseError: null,
      market: "moneyline",
      price: sideDetail && typeof sideDetail.best_price === "number" ? sideDetail.best_price : null,
      line: null,
      side,
      team: teamAbbr,
    },
    // `game` is always passed (matchup header shows regardless of side).
    // featuredbet.js's SIDE fallback is now null-safe -- it only reads
    // `s.game.home`/`s.game.away` when `s.query.side` is literally
    // "home"/"away", so a no-side game keeps its "AWAY @ HOME" header
    // while the SIDE pill correctly renders NOT AVAILABLE instead of
    // inventing a pick. Fixed upstream in featuredbet.js (L23).
    game: { away: quick.away_team, home: quick.home_team,
      firstPitchUtc: (game && game.start_time_utc) || null },
    verdict: quick.verdict || null,
    priceStanding: null, // see docstring -- reserved as an engineering request, never inlined here
    yourPriceBeatsConsensus: improvementPoints === null ? null : improvementPoints > 0,
    priceImprovement: sideDetail ? {
      book: sideDetail.best_book,
      americanPrice: sideDetail.best_price,
      consensusImpliedProbability: sideDetail.consensus_probability,
      improvementPoints: sideDetail.improvement_probability_points,
      improvementReturnPct: sideDetail.improvement_return_pct,
      label: price.label,
    } : null,
    boardDepthBooks: typeof price.books === "number" ? price.books : null,
    thesisSupportCount: 0, // see docstring — known primitive limitation, not "zero evaluated"
    counterargumentCount: 0,
    evidenceStatus: null,
    observedUtc: (price.staleness && price.staleness.observed_utc) || null,
  };
}

function gqvSpotlight(quick, advanced) {
  const wrap = el("section", { class: "gqv-spotlight", "data-hook": "game-spotlight",
    "data-rise": "", "data-delay": "160" });
  wrap.appendChild(el("div", { class: "gqv-spotlight__eyebrow", text: "SPOTLIGHT · PRICE STANDING ON THIS MATCHUP" }));
  const findings = quick.top_findings || [];
  wrap.appendChild(el("p", { class: "gqv-spotlight__lede",
    text: findings.length === 0
      ? "Nothing clears the evidence bar, so the spotlight holds the price standing — which is "
        + "always real."
      : "A finding cleared the bar for this game — the spotlight below is its price standing." }));
  const mount = el("div", { "data-hook": "featured-bet-mount" });
  wrap.appendChild(mount);
  renderFeaturedBet(mount, mapGameToStanding(quick, advanced), {});
  return wrap;
}

/* =====================================================================
 * MODEL vs MARKET -- payload.price_verdicts (src/analysis/priceverdict.py's
 * build_price_verdict, one per side, keyed away/home -- GET /game's own
 * `price_verdicts` field, distinct from `quick.price.sides`, which carries
 * the best price + book each verdict was measured against) plus
 * payload.engine (src/report/engine_bridge.py's summarize_game rollup,
 * null when no forward-test decision joins to this game). Sits directly
 * beneath the Quick View spotlight (V2-34), before the TEAMS panel.
 *
 * "MODEL" here is never an independent model probability -- there is none
 * (see `price_verdict.independent_model`'s own literal string, rendered
 * verbatim below). This panel puts the market-derived price verdict next
 * to the engine's forward-test decisions so a reader can see both real
 * signals side by side without either one masquerading as the other.
 * ===================================================================*/

/** The ranking eyebrow for one column -- "best" gets the labeled claim
 * plus the honesty caption (ranked on price-vs-consensus only, never a
 * pick), "other" gets the plain, unadorned label, and `null` (both
 * sides unranked) renders nothing here -- the panel-level note in
 * `gqvModelVsMarket` covers that case once, not per column. */
function gmvRankBadge(rank) {
  if (rank === "best") {
    const wrap = el("div", { class: "gmv__rank-wrap" });
    wrap.appendChild(el("div", { class: "gmv__rank gmv__rank--best", "data-hook": "gmv-best-side",
      text: "BEST SUPPORTED PRICE ON THIS GAME" }));
    wrap.appendChild(el("p", { class: "gmv__rank-caption",
      text: "Ranked by price against the fair price only — not a prediction of who wins, "
          + "and not advice to bet it." }));
    return wrap;
  }
  if (rank === "other") {
    return el("div", { class: "gmv__rank gmv__rank--other", "data-hook": "gmv-other-side", text: "OTHER SIDE" });
  }
  return null;
}

/** One side's `reasons`/`risks` array under a quiet heading, rendered
 * VERBATIM -- never reworded, summarised or invented. An empty (or
 * missing) array renders nothing at all, never an empty box or a
 * padded filler line. */
function gmvEvidenceList(label, items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const tone = label === "WHY" ? " gmv__evidence--why" : label === "AGAINST" ? " gmv__evidence--against" : "";
  const block = el("div", { class: `gmv__evidence${tone}` });
  block.appendChild(el("div", { class: "gmv__evidence-label", text: label }));
  const list = el("ul", { class: "gmv__evidence-list" });
  for (const item of items) {
    list.appendChild(el("li", { text: String(item) }));
  }
  block.appendChild(list);
  return block;
}

function gmvVerdictColumn(sideKey, abbr, verdict, priceSide, rank) {
  const col = el("div", { class: "gmv__col" });
  const badge = gmvRankBadge(rank);
  if (badge) col.appendChild(badge);
  col.appendChild(gqvBadge(abbr));
  col.appendChild(el("div", { class: "gmv__col-name", text: `${teamName(abbr, "name") || abbr} moneyline` }));

  if (!verdict) {
    col.appendChild(notYetAvailable("No price verdict for this side.", "NO VERDICT"));
    return col;
  }

  col.appendChild(renderWordChip(verdict.word));

  const bestPrice = priceSide && typeof priceSide.best_price === "number" ? formatAmerican(priceSide.best_price) : null;
  if (bestPrice) {
    col.appendChild(el("div", { class: "gmv__price-line" },
      [document.createTextNode(`${bestPrice}${priceSide.best_book ? ` at ${bookLabel(priceSide.best_book)}` : ""}`)]));
  }

  col.appendChild(renderValueMeter({
    marketImplied: verdict.market_implied_probability,
    priceImplied: verdict.stated_implied_probability,
    valuePoints: verdict.value_points,
    word: null,
  }));

  if (verdict.evidence_tier) {
    col.appendChild(el("p", { class: "gmv__tier", text: `EVIDENCE TIER ${verdict.evidence_tier}` }));
  }

  const why = gmvEvidenceList("WHY", verdict.reasons);
  if (why) col.appendChild(why);
  const against = gmvEvidenceList("AGAINST", verdict.risks);
  if (against) col.appendChild(against);

  return col;
}

function provenanceLine(provenanceCounts) {
  if (!provenanceCounts || typeof provenanceCounts !== "object") return "not available";
  // Provenance keys are enum values ("market_derived", "model_derived").
  // Said out loud they are still the same categories, just not underscored.
  const parts = Object.keys(provenanceCounts).map(
    (k) => `${k.replace(/_/g, "-")}: ${provenanceCounts[k]}`);
  return parts.length ? parts.join(", ") : "not available";
}

/** A refusal reason the engine recorded, said in words.
 *
 * The engine writes these as the expression it evaluated --
 * "books_at_decision=0 < 2", "staleness_seconds=40950 > 1800" -- which is
 * exactly right in an audit ledger and reads as debug output on a page a
 * bettor is looking at. Only the shapes named here are rewritten; anything
 * else comes back UNCHANGED rather than being guessed at, because a reason
 * we cannot parse is still a reason the reader is entitled to see.
 */
function refusalText(detail) {
  const raw = String(detail || "").trim();
  const m = raw.match(/^([a-z_]+)=([\d.]+)\s*([<>]=?)\s*([\d.]+)$/);
  if (!m) return raw;
  const [, field, valueText, , limitText] = m;
  const value = Number(valueText);
  const limit = Number(limitText);
  if (field === "books_at_decision") {
    return `${value} book${value === 1 ? "" : "s"} quoted at decision time; `
      + `this system needs ${limit}`;
  }
  if (field === "staleness_seconds") {
    const hours = value / 3600;
    const age = hours >= 1 ? `${hours.toFixed(1)} hr` : `${Math.round(value / 60)} min`;
    const cap = limit >= 3600 ? `${(limit / 3600).toFixed(1)} hr` : `${Math.round(limit / 60)} min`;
    return `board was ${age} old at decision time; the limit is ${cap}`;
  }
  return raw;
}

function standDownBlock(summary) {
  // `null` means the stand-down ledger holds nothing for this game, which is
  // NOT the same as "every system had a reason" -- the slate may not have
  // reached it. Say that rather than implying the systems looked.
  if (!summary || !Array.isArray(summary.reasons) || summary.reasons.length === 0) {
    return el("p", { class: "gmv-engine__standdown gmv-engine__standdown--absent",
      text: "No reason recorded for this game — the slate may not have reached it yet." });
  }
  const wrap = el("div", { class: "gmv-engine__standdown" });
  wrap.appendChild(el("p", { class: "gmv-engine__standdown-headline",
    text: String(summary.headline || "") }));
  const list = el("ul", { class: "gmv-engine__standdown-list" });
  for (const r of summary.reasons) {
    const n = Number(r.n_systems) || 0;
    const li = el("li", { class: "gmv-engine__standdown-item" });
    li.appendChild(el("span", { class: "gmv-engine__standdown-count",
      text: `${n} system${n === 1 ? "" : "s"}` }));
    li.appendChild(el("span", { class: "gmv-engine__standdown-why",
      text: String(r.sentence || "") }));
    // Only a clock earns "yet". A settled verdict must not read as pending.
    if (r.transient) {
      li.appendChild(el("span", { class: "gmv-engine__standdown-chip",
        text: "MAY CHANGE" }));
    }
    list.appendChild(li);
  }
  wrap.appendChild(list);
  return wrap;
}

function engineDecisionsList(engine) {
  const wrap = el("div", { class: "gmv-engine" });
  wrap.appendChild(el("h4", { class: "gmv-engine__title", text: "ENGINE DECISIONS" }));
  if (!engine) {
    wrap.appendChild(notYetAvailable(
      "No frozen engine decisions joined to this game.", "ENGINE"));
    return wrap;
  }
  wrap.appendChild(el("p", { class: "gmv-engine__summary",
    text: `${engine.n_decisions} decision${engine.n_decisions === 1 ? "" : "s"} · `
      + `${engine.n_play} played · ${engine.n_staked} staked` }));

  const plays = Array.isArray(engine.forward_test_plays) ? engine.forward_test_plays : [];
  if (plays.length === 0) {
    wrap.appendChild(el("p", { class: "gmv-engine__none",
      text: "No forward-test system played this game — CONTROL and MARKET REFERENCE decisions are "
          + "never shown here as interest (they carry no checkable thesis)." }));
    // WHY none played. Without this the sentence above is a dead end: it says
    // nobody acted but not whether the systems examined the game and passed,
    // or never reached it. Those are different facts and a reader cannot tell
    // them apart from "no play" alone.
    wrap.appendChild(standDownBlock(engine.stand_downs));
  } else {
    const list = el("div", { class: "gmv-engine__plays" });
    for (const play of plays) {
      const row = el("div", { class: "gmv-engine__play" });
      row.appendChild(el("span", { class: "gmv-engine__play-system", text: play.system_id || "unknown system" }));
      row.appendChild(el("span", { class: "gmv-engine__play-side",
        text: play.side_or_selection ? String(play.side_or_selection).toUpperCase() : "" }));
      if (play.thesis) {
        const details = el("details", { class: "gmv-engine__thesis" });
        details.appendChild(el("summary", { text: "Thesis" }));
        details.appendChild(el("p", { text: String(play.thesis) }));
        row.appendChild(details);
      }
      list.appendChild(row);
    }
    wrap.appendChild(list);
  }

  const fatals = Array.isArray(engine.fatal_counterarguments) ? engine.fatal_counterarguments : [];
  if (fatals.length) {
    const warn = el("div", { class: "gmv-engine__fatals" });
    warn.appendChild(el("p", { class: "gmv-engine__fatals-title", text: `${fatals.length} FATAL COUNTERARGUMENT${fatals.length === 1 ? "" : "S"}` }));
    const list = el("ul", { class: "gmv-engine__fatals-list" });
    // Sixteen systems refusing for the same reason produced sixteen
    // identical lines. Group them: the count is information, the repetition
    // is not. Every distinct reason is still listed.
    const counts = new Map();
    for (const ca of fatals) {
      const text = refusalText(ca.detail || ca.cause || "no detail given");
      counts.set(text, (counts.get(text) || 0) + 1);
    }
    for (const [text, n] of counts) {
      list.appendChild(el("li", { text: n > 1 ? `${text} (${n} systems)` : text }));
    }
    warn.appendChild(list);
    wrap.appendChild(warn);
  }

  if (engine.market_reference_present) {
    wrap.appendChild(el("p", { class: "gmv-engine__note",
      text: "A MARKET REFERENCE system also decided this game — it republishes the board's own "
          + "consensus, a calibration reference only, never a pick." }));
  }
  return wrap;
}

/** Orders away/home for the panel's ranking eyebrow, by `value_points`
 * descending -- a null `value_points` (INSUFFICIENT DATA) always sorts
 * last, so it never outranks a priced side. Returns two `{key, rank}`
 * entries in display order; `rank` is "best"/"other", or `null` on BOTH
 * entries when neither side has a priced `value_points` to rank on. */
function gmvRankOrder(verdicts) {
  const points = (key) => {
    const v = verdicts[key];
    return v && typeof v.value_points === "number" ? v.value_points : null;
  };
  const keys = ["away", "home"].sort((a, b) => {
    const pa = points(a);
    const pb = points(b);
    if (pa === null && pb === null) return 0;
    if (pa === null) return 1;
    if (pb === null) return -1;
    return pb - pa;
  });
  const unranked = points(keys[0]) === null && points(keys[1]) === null;
  return keys.map((key, i) => ({ key, rank: unranked ? null : (i === 0 ? "best" : "other") }));
}

/* =====================================================================
 * TONIGHT'S PICK -- the first thing on the screen, and the only thing on it
 * that answers "what do I bet".
 *
 * `pick.bet` is composed in src/analysis/daily_card.py and is already the
 * sentence: "Take Pittsburgh Pirates +1.5 at -110". It is rendered VERBATIM
 * -- never reworded here, never assembled from parts in the client. The last
 * time this frontend composed its own betting language it invented TOP PLAY
 * and a reader took a price gap for a recommendation.
 * ===================================================================*/

function gqvTonightsPick(pick, quick) {
  if (!pick) {
    // A short, honest line rather than a panel of explanation. A game that
    // did not make the card is the common case and does not deserve more
    // room than the games that did.
    const none = el("section", { class: "gqv-pick gqv-pick--none chamfer",
      "data-hook": "game-pick-none" });
    none.appendChild(el("p", { class: "gqv-pick__eyebrow", text: "NOT ON TONIGHT'S CARD" }));
    none.appendChild(el("p", { class: "gqv-pick__none-body",
      text: "This one didn't make the day's three to five. The full read is below." }));
    return none;
  }

  const section = el("section", { class: "gqv-pick chamfer", "data-hook": "game-pick",
    "data-label": pick.label || "" });
  const head = el("div", { class: "gqv-pick__head" });
  head.appendChild(el("p", { class: "gqv-pick__eyebrow", text: "TONIGHT'S PICK" }));
  if (pick.label) {
    head.appendChild(el("span", { class: "gqv-pick__label", text: pick.label }));
  }
  section.appendChild(head);

  section.appendChild(el("p", { class: "gqv-pick__bet", "data-hook": "game-pick-bet",
    text: pick.bet || "" }));

  // AT MOST TWO REASONS. The card carries more; this is the game screen, not
  // the card, and a wall of justification under the bet is the fluff this
  // page was just cleared of.
  const why = Array.isArray(pick.why) ? pick.why.slice(0, 2) : [];
  if (why.length) {
    const list = el("ul", { class: "gqv-pick__why" });
    for (const sentence of why) {
      list.appendChild(el("li", { text: sentence }));
    }
    section.appendChild(list);
  }
  return section;
}


function gqvModelVsMarket(payload, quick) {
  const wrap = el("section", { class: "gmv panel chamfer", "data-hook": "model-vs-market",
    "data-rise": "" });
  wrap.appendChild(el("div", { class: "gmv__eyebrow", text: "MODEL vs MARKET" }));

  const verdicts = (payload && typeof payload.price_verdicts === "object" && payload.price_verdicts) || {};
  const sides = (quick.price && quick.price.sides) || {};
  const order = gmvRankOrder(verdicts);

  if (order.every((o) => o.rank === null)) {
    wrap.appendChild(el("p", { class: "gmv__unranked-note", "data-hook": "gmv-unranked",
      text: "No priced side to rank on this game." }));
  }

  const cols = el("div", { class: "gmv__cols" });
  for (const { key, rank } of order) {
    const abbr = key === "away" ? quick.away_team : quick.home_team;
    cols.appendChild(gmvVerdictColumn(key, abbr, verdicts[key], sides[key], rank));
  }
  wrap.appendChild(cols);

  // ENGINE TELEMETRY IS NOT QUICK VIEW. Removed 2026-09-10.
  //
  // This used to append, to the FIRST screen a reader lands on: a line
  // reading "INDEPENDENT MODEL: NO INDEPENDENT MODEL YET · engine
  // provenance: market-derived: 206, placeholder: 103, none: 16", then
  // ENGINE DECISIONS -- 325 rows of raw system hashes like
  // `4703ed67882a9d2b` each with a collapsed Thesis -- then a panel headed
  // 207 FATAL COUNTERARGUMENTS listing "board was 14.2 hr old at decision
  // time; the limit is 30 min (3 systems)" twenty-five times over.
  //
  // Every line of it is true and every line of it is for us. The owner,
  // looking at that screen: "there's just a lot of AI slop language and a
  // lot of fluff... make it impactful, concise, to the point, make them
  // want to see our bets."
  //
  // It now lives under SHOW ADVANCED ANALYSIS, which is where a reader goes
  // when they want the machinery. Nothing is deleted and no payload field
  // stopped being rendered -- it moved to the layer that asks for it.
  return wrap;
}

/* =====================================================================
 * TEAMS panel -- records, win pct, RS/RA per game, last-5/last-10, every
 * rate with its sample n. away/home split intentionally NOT shown: the
 * dossier only exposes the split as a bare win_pct fraction
 * (`away_home_win_pct`/`away_away_win_pct` in
 * src/pipeline/features.py's `team_features`) with no sample count on
 * the wire for that specific rate -- and this product's own rule is
 * that every rate carries its n, so a rate this file cannot attach one
 * to is omitted rather than shown unlabeled.
 * ===================================================================*/

function gqvStatCell(label, value, sample) {
  const cell = el("div", { class: "gqv-stat chamfer" });
  cell.appendChild(el("div", { class: "gqv-stat__label", text: label }));
  cell.appendChild(el("div", { class: "gqv-stat__value" },
    [(value === null || value === undefined) ? renderAbsent() : document.createTextNode(String(value))]));
  if (sample) cell.appendChild(el("div", { class: "gqv-stat__n", text: sample }));
  return cell;
}

/** `${wins} WINS` (not a W-L record) for a last-N window: the dossier's
 * `_rates()` computes losses as `len(decided) - wins` server-side but
 * never puts that subtraction on the wire for the last-N windows
 * (`src/pipeline/features.py`) -- reconstructing it client-side as
 * `games - wins` would assume every game in the window had a decision,
 * true in the ordinary case but not guaranteed, so this shows the two
 * real fields (wins, games) instead of a derived record this endpoint
 * does not state. */
function windowWins(teams, key, window) {
  const wins = teams[`${key}_last${window}_wins`];
  const games = teams[`${key}_last${window}_games`];
  if (typeof wins !== "number") return null;
  return {
    text: `${wins} WIN${wins === 1 ? "" : "S"}`,
    sample: typeof games === "number" ? `${games} games` : null,
  };
}

function gqvTeams(advanced, quick) {
  const panel = el("section", { class: "gqv-teams panel chamfer", "data-hook": "teams-panel", "data-rise": "" });
  panel.appendChild(el("h3", { class: "gqv-teams__title", text: "TEAMS" }));
  const teams = readSection(advanced, "teams");
  if (!teams) {
    panel.appendChild(notYetAvailable(
      gapReason(advanced, "teams") || "Team records are not available for this game.", "NOT AVAILABLE"));
    return panel;
  }
  const grid = el("div", { class: "gqv-stats" });
  for (const [key, label] of [["away", quick.away_team], ["home", quick.home_team]]) {
    const n = typeof teams[`${key}_games_played`] === "number"
      ? `${teams[`${key}_games_played`]} games` : null;
    const w = teams[`${key}_wins`];
    const l = teams[`${key}_losses`];
    grid.appendChild(gqvStatCell(`${label} RECORD`,
      (typeof w === "number" && typeof l === "number") ? `${w}-${l}` : null, n));
    grid.appendChild(gqvStatCell(`${label} WIN PCT`,
      typeof teams[`${key}_win_pct`] === "number" ? teams[`${key}_win_pct`].toFixed(3) : null, n));
    grid.appendChild(gqvStatCell(`${label} RS / GAME`, teams[`${key}_runs_scored_pg`], n));
    grid.appendChild(gqvStatCell(`${label} RA / GAME`, teams[`${key}_runs_allowed_pg`], n));
    const l5 = windowWins(teams, key, 5);
    grid.appendChild(gqvStatCell(`${label} LAST 5`, l5 ? l5.text : null, l5 ? l5.sample : null));
    const l10 = windowWins(teams, key, 10);
    grid.appendChild(gqvStatCell(`${label} LAST 10`, l10 ? l10.text : null, l10 ? l10.sample : null));
  }
  panel.appendChild(grid);
  return panel;
}

function gqvActions(date, away, home) {
  // "SAVE THIS BET" from the artboard is deliberately omitted -- Quick
  // View has no stated side+price to save (My Bets/mybets.js is a
  // different Wave-1/Wave-2 group's file, out of this lane's ownership,
  // and there is no honest default bet here for the dominant no_play
  // case). See the L21 report.
  const actions = el("div", { class: "gqv-actions" });
  actions.appendChild(el("a", {
    href: `#/betcheck?date=${encodeURIComponent(date)}&away=${encodeURIComponent(away)}&home=${encodeURIComponent(home)}`,
    class: "btn btn--cyan chamfer chamfer--btn on-live", "data-hook": "go-to-bet-check",
    text: "CHECK A BET ON THIS GAME" }));
  actions.appendChild(el("a", {
    href: `#/odds/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`,
    class: "btn btn--ghost chamfer chamfer--btn", "data-hook": "open-the-board", text: "OPEN THE FULL BOARD" }));
  return actions;
}

/* =====================================================================
 * GAME ADVANCED V2 -- V2-03 (desktop COVERAGE LEDGER) / V2-31 (mobile)
 * APPENDS BENEATH QUICK VIEW, NEVER REPLACES IT (handoff's append rule,
 * restated in V2-31's own body copy: "Advanced never replaces Quick
 * View"). The toggle below only shows/hides this host.
 * ===================================================================*/

/** Static, product-level one-liners for the FIVE section names this API
 * actually ships (per RECONCILED_CONTRACT_CURRENT_HEAD.md's PRIORITY
 * ANSWER 2) -- describing what a section MEANS, never this game's own
 * numbers (those come from `sectionFact` below, read live off the
 * payload). An unrecognized future section key gets the mechanical
 * humanized fallback instead of an invented description. */
const SECTION_BLURBS = {
  park: "Venue identifier resolved from the game record.",
  price_improvement: "Your price against the fair price across the books, with a mandatory "
    + "direction label.",
  multibook_board: "Per-book prices from one capture instant, with best-price ties.",
  what_changed: "Roster/lineup events this poller has seen for this game.",
  teams: "Records, win pct, runs for and against per game, last-5 and last-10 — every rate with "
    + "its sample n.",
};

/** One REAL, this-game fact per known section (a book count, a venue
 * name, a games-played n...), read straight off the section's own data
 * -- never a number this file computes. `null` when the section is
 * present but this file has no safe one-line fact for it (an unknown
 * future section, or a section with no obviously headline field). */
function sectionFact(name, section) {
  if (!section || typeof section !== "object") return null;
  if (name === "park") return section.name || null;
  if (name === "price_improvement") {
    const books = section.dispersion && section.dispersion.books;
    return typeof books === "number" ? `across ${books} books` : null;
  }
  if (name === "multibook_board") {
    const n = Array.isArray(section.quotes) ? section.quotes.length : null;
    return typeof n === "number" ? `${n} book${n === 1 ? "" : "s"}` : null;
  }
  if (name === "what_changed") {
    const n = Array.isArray(section.events) ? section.events.length : 0;
    return `${n} event${n === 1 ? "" : "s"} seen`;
  }
  if (name === "teams") {
    const n = section.away_games_played;
    return typeof n === "number" ? `${n} games` : null;
  }
  return null;
}

function gavRecap(quick) {
  // V2-31's mobile-only "QUICK VIEW · STILL HERE" reorientation strip --
  // hidden above the mobile breakpoint in CSS (Quick View is already on
  // screen there; this strip exists only so a reader who has scrolled
  // past it on a phone is not re-oriented by a bare gap ledger).
  const strip = el("div", { class: "gav-recap", "data-hook": "advanced-mobile-recap" });
  strip.appendChild(el("span", { class: "gav-recap__label", text: "QUICK VIEW · STILL HERE" }));
  strip.appendChild(el("span", { class: "gav-recap__matchup",
    text: `${quick.away_team} @ ${quick.home_team}` }));
  const findings = quick.top_findings || [];
  strip.appendChild(el("span", { class: "gav-recap__verdict",
    text: findings.length === 0 ? NOTHING_STANDS_OUT : (verdictLabel(quick.verdict) || "") }));
  return strip;
}

function gavIntro(advanced) {
  const sections = advanced && typeof advanced.sections === "object" ? advanced.sections : {};
  const gaps = advanced && typeof advanced.gaps === "object" ? advanced.gaps : {};
  const sectionsCount = Object.keys(sections).length;
  const gapsCount = Object.keys(gaps).length;
  const total = sectionsCount + gapsCount;

  const wrap = el("div", { class: "gav-intro" });
  wrap.appendChild(el("div", { class: "gav-intro__eyebrow", text: "COVERAGE LEDGER" }));
  wrap.appendChild(el("div", { class: "gav-intro__headline",
    text: `${sectionsCount} THING${sectionsCount === 1 ? "" : "S"} WE KNOW. ${gapsCount} WE DON'T.` }));
  wrap.appendChild(el("p", { class: "gav-intro__body",
    text: "This is the advanced view. Not a stat dump — an honest map of our coverage, with every "
        + "gap named and its reason printed as the API gave it. Knowing what is missing is worth "
        + "more than a number we made up." }));

  const tiles = el("div", { class: "gav-tiles" });
  tiles.appendChild(el("div", { class: "gav-tile gav-tile--live" }, [
    el("div", { class: "gav-tile__label", text: "SECTIONS AVAILABLE" }),
    el("div", { class: "gav-tile__value", text: String(sectionsCount) }),
    el("div", { class: "gav-tile__sample", text: `of ${total} candidates` }),
  ]));
  tiles.appendChild(el("div", { class: "gav-tile gav-tile--warn" }, [
    el("div", { class: "gav-tile__label", text: "NAMED GAPS" }),
    el("div", { class: "gav-tile__value", text: String(gapsCount) }),
    el("div", { class: "gav-tile__sample", text: "each with a reason" }),
  ]));
  tiles.appendChild(el("div", { class: "gav-tile" }, [
    el("div", { class: "gav-tile__label", text: "MARKETS SUPPORTED" }),
    el("div", { class: "gav-tile__value", text: "1" }),
    el("div", { class: "gav-tile__sample", text: "moneyline only" }),
  ]));
  wrap.appendChild(tiles);
  return wrap;
}

function gavHave(advanced) {
  const sections = advanced && typeof advanced.sections === "object" ? advanced.sections : {};
  const keys = Object.keys(sections);
  const block = el("div", { class: "gav-have" });
  block.appendChild(el("h4", { class: "gav-subhead",
    text: `WHAT WE ACTUALLY HAVE · ${keys.length} SECTION${keys.length === 1 ? "" : "S"}` }));
  const list = el("div", { class: "gav-have__list" });
  for (const key of keys) {
    const row = el("div", { class: "gav-have__row" });
    row.appendChild(el("span", { class: "gav-have__mark", "aria-hidden": "true" }));
    row.appendChild(el("span", { class: "gav-have__key", "data-raw-key": key, text: key }));
    row.appendChild(el("span", { class: "gav-have__desc", text: SECTION_BLURBS[key] || humanizeKey(key) }));
    const fact = sectionFact(key, sections[key]);
    if (fact) row.appendChild(el("span", { class: "gav-have__fact", text: fact }));
    list.appendChild(row);
  }
  block.appendChild(list);
  return block;
}

/** When a game carries a long list of gaps (four or more), naming each one
 * individually reads as a wall of NOT YET AVAILABLE panels -- broken,
 * rather than an honest boundary. This ONE consolidated panel says it once.
 *
 * It names the gaps the payload ACTUALLY reports, not a fixed list. The
 * fixed list this used to carry ("team records, bullpen, splits,
 * handedness, lineups") became false the day F-2 landed (2026-09-07:
 * api/games._enrichment_inputs now feeds those stores in), and a page
 * that showed 69-74 in the identity panel while this sentence said team
 * records were not in the build was a contradiction, not an explanation.
 * Reuses dom.js's own `notYetAvailable` panel -- see this file's RULES. */
function gavGapsConsolidated(gapKeys) {
  const named = (gapKeys || []).map((k) => humanizeKey(k).toLowerCase());
  const list = named.length <= 5
    ? named.join(", ")
    : `${named.slice(0, 5).join(", ")} and ${named.length - 5} more`;
  return notYetAvailable(
    "This build carries the schedule, the live board, the frozen engine record, and the "
    + "per-game layers it has for this game. What it does not have for this game — "
    + `${list} — is reported as ${named.length} named gap${named.length === 1 ? "" : "s"} `
    + "below, each with the reason as given, rather than guessed at.",
    "NOT AVAILABLE FOR THIS GAME");
}

/** Every gap the payload actually names, dynamically -- see this file's
 * top docstring for why nothing here hardcodes the artboard's own
 * (stale) gap-name list. Collapsed `<details>` rows: "tap for its reason
 * string. Not links -- there is nowhere to go" (V2-31's own copy).
 *
 * At four gaps or more, the per-gap list ALSO nests inside one outer
 * `<details>` ("N SECTIONS NOT IN THIS BUILD -- SHOW REASONS"), collapsed
 * by default, behind the consolidated explainer panel above it -- so a
 * reader sees one honest sentence first, not twelve stacked panels, while
 * every individual gap and its own verbatim reason string is still one
 * tap away, never deleted. Below that count (the common case: one or two
 * real gaps on an otherwise well-covered game) nothing changes -- the
 * header, lede and per-gap rows render inline exactly as before. */
function gavGaps(advanced) {
  const gaps = advanced && typeof advanced.gaps === "object" ? advanced.gaps : {};
  const keys = Object.keys(gaps);
  const block = el("div", { class: "gav-gaps" });
  const consolidate = keys.length >= 4;

  if (consolidate) block.appendChild(gavGapsConsolidated(keys));

  const header = el("h4", { class: "gav-subhead gav-subhead--warn",
    text: `THE ${keys.length} GAP${keys.length === 1 ? "" : "S"} · REASONS PRINTED AS GIVEN` });
  const lede = el("p", { class: "gav-gaps__lede",
    text: "Every one of these is a coverage finding, not an error — knowing what is missing is "
        + "worth more than a number we made up." });
  const list = el("div", { class: "gav-gaps__list" });
  for (const key of keys) {
    const row = el("details", { class: "gav-gap", "data-hook": "coverage-gap", "data-gap-key": key });
    const summary = el("summary", { class: "gav-gap__summary" });
    summary.appendChild(el("span", { class: "gav-gap__mark", "aria-hidden": "true", text: "!" }));
    summary.appendChild(el("span", { class: "gav-gap__key", "data-raw-key": key, text: humanizeKey(key) }));
    summary.appendChild(el("span", { class: "gav-gap__chip", text: "NOT AVAILABLE" }));
    row.appendChild(summary);
    row.appendChild(el("p", { class: "gav-gap__reason", "data-hook": "coverage-gap-reason",
      text: String(gaps[key]) }));
    list.appendChild(row);
  }

  if (consolidate) {
    const outer = el("details", { class: "gav-gaps__collapse", "data-hook": "coverage-gaps-collapsed" });
    outer.appendChild(el("summary", { class: "gav-gaps__collapse-summary",
      // Not "NOT IN THIS BUILD": a night with no prices on the board is a
      // gap on this game, not a gap in the build, and the list is mixed.
      text: `${keys.length} GAPS ON THIS GAME — SHOW REASONS` }));
    outer.appendChild(header);
    outer.appendChild(lede);
    outer.appendChild(list);
    block.appendChild(outer);
  } else {
    block.appendChild(header);
    block.appendChild(lede);
    block.appendChild(list);
  }
  return block;
}

/** A plain book-versus-book table -- deliberately WITHOUT the artboard's
 * "CHEAPER" marker or "CENTS FROM CONSENSUS" column. Neither figure
 * exists on `multibook_board.quotes` (each row is only
 * `{book, away_price, home_price}` -- src/analysis/prices.py's
 * `boards_by_matchup`), and computing either would mean writing a new
 * client-side American-odds comparison this codebase has no shared
 * helper for (see the L21 report). Simpler and certainly correct beats
 * a hand-rolled odds-math routine nobody else has reviewed. */
function gavBoard(advanced, quick) {
  const board = readSection(advanced, "multibook_board");
  const block = el("div", { class: "gav-board" });
  block.appendChild(el("h4", { class: "gav-subhead", text: "BOOK VERSUS BOOK" }));
  block.appendChild(el("p", { class: "gav-board__lede",
    text: "The comparison that is real. Books disagree; that is measurable." }));
  if (!board || !Array.isArray(board.quotes) || !board.quotes.length) {
    block.appendChild(notYetAvailable(
      gapReason(advanced, "market") || "No board captured for this game.", "NO BOARD"));
    return block;
  }
  const scroll = el("div", { class: "gav-board__scroll" });
  const table = el("table", { class: "gav-board__table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of ["BOOK", quick.away_team, quick.home_team]) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const quote of board.quotes) {
    const tr = el("tr");
    tr.appendChild(el("td", { text: bookLabel(quote.book) || formatBook(quote.book) || "" }));
    const away = formatAmerican(quote.away_price);
    const home = formatAmerican(quote.home_price);
    tr.appendChild(el("td", { class: "gav-board__price" }, [away ? document.createTextNode(away) : renderAbsent()]));
    tr.appendChild(el("td", { class: "gav-board__price" }, [home ? document.createTextNode(home) : renderAbsent()]));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  scroll.appendChild(table);
  block.appendChild(scroll);
  block.appendChild(el("p", { class: "gav-board__note",
    text: `Replaces the old stat-versus-stat table -- FIP, WHIP and K-BB% are gaps, not data. `
        + `Across ${board.quotes.length} books.` }));
  return block;
}

/** The itemized "run totals / player props / parlays / +N more" grid the
 * artboard shows is decorative mockup copy, not backed by any field this
 * endpoint (or any documented contract) exposes -- `src/analysis/
 * betcheck.py`'s `UNSUPPORTED_MARKETS` is Bet Check's own free-text
 * parser vocabulary, uses different canonical names than the artboard's
 * example list, and is not itself on any customer-facing wire. Rendered
 * here as the one verified, product-wide fact instead (same sentence
 * odds.js's own footnote already states elsewhere in this client). */
function gavMarketRefusal() {
  const block = el("div", { class: "gav-refusal" });
  block.appendChild(el("h4", { class: "gav-subhead", text: "MARKET REFUSAL" }));
  block.appendChild(el("p", { class: "gav-refusal__body",
    text: "This product checks moneyline (h2h) only. Every other market — spreads, totals, run "
        + "line, player props and the rest — is refused by name rather than approximated as a "
        + "moneyline bet." }));
  return block;
}

function renderAdvancedV2(advanced, quick) {
  const host = el("div", { class: "gav", "data-hook": "game-advanced" });
  host.appendChild(gavRecap(quick));
  host.appendChild(gavIntro(advanced));
  host.appendChild(gavHave(advanced));
  host.appendChild(gavGaps(advanced));
  host.appendChild(gavBoard(advanced, quick));
  host.appendChild(gavMarketRefusal());
  host.appendChild(renderStaleness(advanced.staleness));
  return host;
}

/* =====================================================================
 * Game view -- composition
 * ===================================================================*/

export async function renderGameDetail(container, date, away, home) {
  clear(container);
  const screen = el("div", { class: "screen gqv", "data-view": "game" });
  container.appendChild(screen);
  const loadingWrap = el("div", { class: "screen-state" }, [renderLoadingSkeleton({
    eyebrow: "LOADING", headline: "LOADING THIS GAME",
    subline: "Quick view first, advanced analysis appended beneath it.", rows: 5 })]);
  screen.appendChild(loadingWrap);

  let payload;
  let cardPick = null;
  try {
    // THE CARD'S PICK FOR THIS GAME, fetched alongside. It leads the screen.
    //
    // Until 2026-09-10 this page opened with NOTHING STANDS OUT HERE and a
    // price board. The owner: "make it impactful, concise, to the point,
    // make them want to see our bets." A reader who opened a game and was
    // told nothing stands out had no reason to read anything below it.
    //
    // FAILURE HERE IS NOT FATAL. The card is a separate endpoint with its
    // own cache; if it is slow or down, the game still renders without a
    // pick rather than the whole page dying for the sake of a banner.
    const both = await Promise.allSettled([
      apiGet(`/game/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`),
      apiGet(`/card/${encodeURIComponent(date)}`),
    ]);
    if (both[0].status !== "fulfilled") throw both[0].reason;
    payload = both[0].value;
    if (both[1].status === "fulfilled") {
      const picks = (both[1].value && both[1].value.picks) || [];
      cardPick = picks.find((p) => p.away_team === away && p.home_team === home) || null;
    }
  } catch (err) {
    renderError(loadingWrap, err);
    return;
  }
  loadingWrap.remove();

  const quick = payload.quick || {};
  const advanced = payload.advanced || {};

  const body = el("div", { class: "gqv-body" });
  body.appendChild(el("a", { class: "gqv-back", href: `#/games/${encodeURIComponent(date)}`,
    text: "← BACK TO THE SLATE" }));
  body.appendChild(gqvTopStrip(quick));
  body.appendChild(gqvIdentity(quick, advanced));
  // THE BET FIRST. Everything below is why, not what.
  body.appendChild(gqvTonightsPick(cardPick, quick));
  body.appendChild(gqvPrice(quick));
  // GAME STORY STAYS. Starters, bullpen workload, travel and weather are the
  // things a reader actually wants under a bet -- who is pitching, who is
  // rested, what the park is doing tonight.
  const gameStory = renderGameStory(advanced, quick); if (gameStory) body.appendChild(gameStory);
  body.appendChild(gqvTeams(advanced, quick));
  body.appendChild(gqvActions(date, away, home));

  // ADVANCED APPENDS BENEATH QUICK -- the toggle only shows/hides this
  // host; everything above is never unmounted or re-rendered by it.
  const toggle = el("button", { type: "button", class: "gqv-toggle chamfer",
    "data-hook": "advanced-toggle", "aria-expanded": "false", "aria-controls": "game-advanced-host",
    text: "SHOW ADVANCED ANALYSIS ⌄" });
  body.appendChild(toggle);
  body.appendChild(el("p", { class: "gqv-toggle__note", text: "EXPANDS BELOW · QUICK VIEW STAYS OPEN" }));

  const advHost = el("div", { id: "game-advanced-host" });
  advHost.hidden = true;
  advHost.appendChild(renderAdvancedV2(advanced, quick));
  // MOVED OFF THE QUICK VIEW 2026-09-10, both of them price-verification
  // apparatus rather than anything a reader came for.
  //
  // SPOTLIGHT read "Nothing clears the evidence bar, so the spotlight holds
  // the price standing -- which is always real", over a table whose rows were
  // PRICE STANDING / NOT AVAILABLE / "needs the full per-book board, which
  // this check does not carry", BEATS CONSENSUS / No, and a footnote reading
  // "price improvement / line-shopping value -- a better execution price, not
  // expected value and not a prediction".
  //
  // MODEL vs MARKET printed, for each side, THE MARKET'S FAIR CHANCE against
  // PROBABILITY YOUR PRICE IMPLIES, the difference in points, and then the
  // same sentence twice: "A likely winner at a bad price is still a bad
  // price; an underdog can be value when the price implies less than the
  // market's own fair price."
  //
  // All of it accurate. None of it is why anyone opened the page, and
  // together they were most of its length.
  advHost.appendChild(gqvSpotlight(quick, advanced));
  advHost.appendChild(gqvModelVsMarket(payload, quick));
  // The engine's own record, moved off the quick view -- see the comment at
  // the end of gqvModelVsMarket for what it was doing to the first screen.
  const engine = payload && payload.engine ? payload.engine : null;
  advHost.appendChild(el("p", { class: "gmv__model-line",
    text: `INDEPENDENT MODEL: NO INDEPENDENT MODEL YET · engine provenance: ${provenanceLine(engine && engine.provenance_counts)}` }));
  advHost.appendChild(engineDecisionsList(engine));
  body.appendChild(advHost);

  toggle.addEventListener("click", () => {
    const open = advHost.hidden;
    advHost.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "HIDE ADVANCED ANALYSIS ⌃" : "SHOW ADVANCED ANALYSIS ⌄";
    if (open) armEntrances(advHost);
  });

  screen.appendChild(body);
  setShellStatusFromStaleness(advanced.staleness);
  armEntrances(screen);
}
