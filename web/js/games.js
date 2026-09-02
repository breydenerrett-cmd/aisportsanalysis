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
  verdictLabel, formatAmerican, formatBook, formatConsensusShare,
  formatEasternTime, formatEasternClock } from "./dom.js";
import { renderLoadingSkeleton, renderError, notYetAvailable } from "./states.js";
import { renderFeaturedBet } from "./featuredbet.js";
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
  const sample = typeof n === "number" ? `n = ${n} games` : null;
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
      "Starters not posted yet for this game. The field is absent, not empty -- we show "
      + "nothing rather than a placeholder name. Records and splits above are unaffected.",
      "UNANNOUNCED"));
  }
  if (!teams) {
    wrap.appendChild(notYetAvailable(
      gapReason(advanced, "teams") || "Team records are not available for this game.",
      "NOT AVAILABLE"));
  }
  return wrap;
}

/** Big verdict word + the API's own headline sentence + FINDINGS/EVIDENCE
 * mini tiles. "NO DEMONSTRATED EDGE" as the big word, and the sentence
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
function gqvVerdict(quick) {
  const panel = el("section", { class: "gqv-verdict panel chamfer", "data-hook": "quick-verdict",
    "data-rise": "", "data-delay": "80" });
  const findings = quick.top_findings || [];
  const noEdge = findings.length === 0;
  const bigWord = noEdge ? "NO DEMONSTRATED EDGE" : (verdictLabel(quick.verdict) || "FINDING");
  panel.appendChild(el("div", { class: "gqv-verdict__word", "data-hook": "verdict-word", text: bigWord }));
  const body = quick.headline
    || (noEdge ? "Interesting matchup, but no demonstrated betting edge." : null);
  if (body) panel.appendChild(el("p", { class: "gqv-verdict__body", "data-hook": "quick-headline", text: body }));
  panel.appendChild(el("p", { class: "gqv-verdict__note",
    text: noEdge
      ? "top_findings came back empty, which is the normal case. Everything below is context we "
        + "can stand behind, not a case for a bet."
      : `${findings.length} finding${findings.length === 1 ? "" : "s"} cleared the bar for this game.` }));

  const tiles = el("div", { class: "gqv-mini-row" });
  tiles.appendChild(el("div", { class: "gqv-mini" }, [
    el("div", { class: "gqv-mini__label", text: "FINDINGS" }),
    el("div", { class: "gqv-mini__value", text: String(findings.length) }),
  ]));
  const topEvidence = findings.length ? findings[0].evidence_label : null;
  tiles.appendChild(el("div", { class: "gqv-mini" }, [
    el("div", { class: "gqv-mini__label", text: "EVIDENCE" }),
    el("div", { class: "gqv-mini__value" },
      [topEvidence ? document.createTextNode(String(topEvidence).toUpperCase()) : renderAbsent()]),
  ]));
  panel.appendChild(tiles);
  return panel;
}

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
      text: "has_board is false, and there is no reason field beyond what is shown above -- so we state "
          + "the fact and stop. The identity panel above is unaffected." }));
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

    const consensus = formatConsensusShare(side.consensus_probability);
    const consLine = el("div", { class: "gqv-price__consensus" });
    consLine.appendChild(el("span", { class: "gqv-price__consensus-label", text: "MARKET-IMPLIED CONSENSUS" }));
    consLine.appendChild(consensus
      ? el("span", { class: "gqv-price__consensus-figure", "data-hook": "consensus-price", text: consensus })
      : renderAbsent());
    col.appendChild(consLine);

    const positive = typeof side.improvement_probability_points === "number"
      && side.improvement_probability_points > 0;
    if (positive) {
      col.appendChild(el("span", { class: "gqv-price__pill", "data-hook": "advantage-pill",
        text: `+${(side.improvement_probability_points * 100).toFixed(2)} PTS BETTER` }));
    } else {
      col.appendChild(el("p", { class: "gqv-price__none", text: "NO IMPROVEMENT ON THIS SIDE" }));
    }
    cols.appendChild(col);
  }
  panel.appendChild(cols);

  if (typeof price.books === "number") {
    panel.appendChild(el("div", { class: "gqv-price__meta", text: `n = ${price.books} books` }));
  }
  if (price.label) {
    panel.appendChild(el("p", { class: "gqv-price__labeltext", text: String(price.label).toUpperCase() }));
  }
  if (price.note) {
    panel.appendChild(el("p", { class: "gqv-price__note", "data-hook": "price-note", text: price.note }));
  }
  panel.appendChild(el("p", { class: "gqv-price__disclaimer",
    text: "Comparison only. No sportsbook links and no wagers taken -- check the number yourself." }));
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
    thesisSupportCount: 0, // see docstring -- known primitive limitation, not "zero evaluated"
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
      ? "Nothing clears the evidence bar, so the spotlight holds the price standing -- which is "
        + "always real."
      : "A finding cleared the bar for this game -- the spotlight below is its price standing." }));
  const mount = el("div", { "data-hook": "featured-bet-mount" });
  wrap.appendChild(mount);
  renderFeaturedBet(mount, mapGameToStanding(quick, advanced), {});
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
    sample: typeof games === "number" ? `n = ${games} games` : null,
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
      ? `n = ${teams[`${key}_games_played`]} games` : null;
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
  price_improvement: "Your price against the de-vigged market-implied consensus, with a mandatory "
    + "direction label.",
  multibook_board: "Per-book prices from one capture instant, with best-price ties.",
  what_changed: "Roster/lineup events this poller has seen for this game.",
  teams: "Records, win pct, runs for and against per game, last-5 and last-10 -- every rate with "
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
    return typeof books === "number" ? `n = ${books} books` : null;
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
    return typeof n === "number" ? `n = ${n} games` : null;
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
    text: findings.length === 0 ? "NO DEMONSTRATED EDGE" : (verdictLabel(quick.verdict) || "") }));
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
    text: "This is the advanced view. Not a stat dump -- an honest map of our coverage, with every "
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

/** Every gap the payload actually names, dynamically -- see this file's
 * top docstring for why nothing here hardcodes the artboard's own
 * (stale) gap-name list. Collapsed `<details>` rows: "tap for its reason
 * string. Not links -- there is nowhere to go" (V2-31's own copy). */
function gavGaps(advanced) {
  const gaps = advanced && typeof advanced.gaps === "object" ? advanced.gaps : {};
  const keys = Object.keys(gaps);
  const block = el("div", { class: "gav-gaps" });
  block.appendChild(el("h4", { class: "gav-subhead gav-subhead--warn",
    text: `THE ${keys.length} GAP${keys.length === 1 ? "" : "S"} · REASONS PRINTED AS GIVEN` }));
  block.appendChild(el("p", { class: "gav-gaps__lede",
    text: "Every one of these is a coverage finding, not an error -- knowing what is missing is "
        + "worth more than a number we made up." }));
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
  block.appendChild(list);
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
        + `Every figure n = ${board.quotes.length} books.` }));
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
    text: "This product checks moneyline (h2h) only. Every other market -- spreads, totals, run "
        + "line, player props and the rest -- is refused by name rather than approximated as a "
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

  const body = el("div", { class: "gqv-body" });
  body.appendChild(el("a", { class: "gqv-back", href: `#/games/${encodeURIComponent(date)}`,
    text: "← BACK TO THE SLATE" }));
  body.appendChild(gqvTopStrip(quick));
  body.appendChild(gqvIdentity(quick, advanced));
  body.appendChild(gqvVerdict(quick));
  body.appendChild(gqvPrice(quick));
  body.appendChild(gqvSpotlight(quick, advanced));
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
