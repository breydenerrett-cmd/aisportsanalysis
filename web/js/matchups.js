/**
 * THE MATCHUP GRID (#/today, GET /today + GET /daily/{date} +
 * GET /opportunities/{date}) -- one card per game on tonight's slate, the
 * Today screen's centrepiece. Wired into web/js/today.js BELOW the TOP
 * OPPORTUNITIES section and ABOVE the Featured Bet carousel head.
 *
 * THE HONESTY RULE THAT SHAPES THIS SCREEN -- read before touching this
 * file (restated from this task's own brief, not paraphrased):
 * -------------------------------------------------------------------
 * Every engine decision on the current slate comes from a CONTROL system
 * (a fixed-direction null baseline) or a MARKET_REFERENCE system (which
 * republishes the board's own de-vigged consensus as a calibration
 * reference). NEITHER IS A PICK TO FOLLOW, and neither may be labelled a
 * recommendation, a best bet, or a play this product likes. The
 * forward-test systems -- the only ones with a directional thesis --
 * frequently have nothing to say on a given slate (finding F-1: they
 * require posted lineups, and the slate freezes hours before lineups
 * post). So this screen:
 *   - calls the frozen block "PAPER POSITIONS FROZEN BEFORE FIRST PITCH",
 *     never "recommendations";
 *   - carries each position's class chip plus a one-line meaning
 *     (CLASS_MEANING below, verbatim at every render site);
 *   - says plainly, per game, when no forward-test position exists
 *     rather than hiding or promoting the CONTROL/MARKET_REFERENCE rows;
 *   - never invents a probability, an edge or a rank, and never renders a
 *     null `value_points` as zero -- `value_points_reason` (or, for a
 *     live opportunities row, its own `reasons` sentences) renders in
 *     its place.
 * The only thing this product stands behind as an opportunity is the
 * live price-vs-consensus verdict already computed by
 * GET /opportunities/{date} (web/js/opportunities.js's TOP OPPORTUNITIES
 * section) -- this screen's LIVE PRICE READ block reuses those same rows,
 * never a second, client-computed comparison.
 *
 * JOIN KEYS -- WHY TWO ABBREVIATION SYSTEMS EXIST
 * -------------------------------------------------------------------
 * GET /today and GET /opportunities/{date} agree exactly on club
 * abbreviations (AZ, ATH -- confirmed by comparing every game on a live
 * slate). GET /daily/{date} disagrees for exactly two clubs: its frozen
 * ledger was built against the engine's own canonicalization
 * (src/report/engine_bridge.py's game_key), which still uses ARI/OAK --
 * confirmed the same way, against the live 2026-09-06 slate (AZ@HOU /
 * ATH@SEA on GET /today became ARI@HOU / OAK@SEA on GET /daily/{date}).
 * DAILY_ABBR_ALIASES below normalizes only these two, documented cases --
 * never a guessed general-purpose alias table -- so a game's frozen
 * positions are never silently dropped for these two clubs.
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading, notYetAvailable,
  formatAmerican, formatConsensusShare, formatEasternTime, formatAge, renderWordChip } from "./dom.js";
import { renderValueMeter } from "./valuemeter.js";
import { teamColors } from "./teamcolors.js";
import { teamName, bookLabel } from "./labels.js";

export const FROZEN_TITLE = "PAPER POSITIONS FROZEN BEFORE FIRST PITCH";

/** The three system-class meanings, verbatim wherever a class chip
 * renders -- see this module's own honesty-rule docstring above. */
export const CLASS_MEANING = {
  CONTROL: "fixed-direction null baseline, not a pick",
  MARKET_REFERENCE: "republishes the board's own consensus, a calibration reference, not a pick",
  FORWARD_TEST: "an unproven directional thesis under forward test",
};

const CLASS_CHIP_LABEL = {
  CONTROL: "CONTROL",
  MARKET_REFERENCE: "MARKET REFERENCE",
  FORWARD_TEST: "FORWARD-TEST SYSTEM",
};

const SETTLEMENT_CHIP = {
  win: { text: "WIN", cls: "day-settle--win" },
  loss: { text: "LOSS", cls: "day-settle--loss" },
  push: { text: "PUSH", cls: "day-settle--push" },
  pending: { text: "PENDING", cls: "day-settle--pending" },
  unsettled: { text: "UNSETTLED", cls: "day-settle--pending" },
};

// See this module's own docstring -- exactly two clubs, exactly this
// documented reason, nothing guessed.
const DAILY_ABBR_ALIASES = { ARI: "AZ", OAK: "ATH" };

function normalizeAbbr(abbr) {
  return DAILY_ABBR_ALIASES[abbr] || abbr;
}

function gameKeyOf(away, home) {
  return `${away}|${home}`;
}

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

function teamBadge(abbr) {
  const colors = teamColors(abbr);
  const badge = el("span", { class: "mx-badge", "aria-hidden": "true", text: abbr || "" });
  badge.style.background = colors.known ? colors.primary : "#232830";
  badge.style.color = colors.known ? colors.accent : "#D5D7DE";
  return badge;
}

/* ---------------------------------------------------------------------
 * PAPER POSITIONS FROZEN BEFORE FIRST PITCH -- one recommendation row.
 * Shared by this screen's per-game card AND web/js/dayrecap.js's full
 * per-day audit trail (#/day/{date}), so the two can never render a
 * position differently. `rec` is one entry of GET /daily/{date}'s
 * `game.recommendations` (or GET /daily/{date}'s day-index summaries do
 * NOT use this -- those are a different, smaller shape).
 * ------------------------------------------------------------------- */
export function frozenPositionRow(rec) {
  const row = el("div", { class: "mx-pos", "data-hook": "frozen-position" });

  const head = el("div", { class: "mx-pos__head" });
  const cls = rec.system_class;
  head.appendChild(el("span", {
    class: `badge chamfer chamfer--chip mx-pos__class mx-pos__class--${cls ? cls.toLowerCase() : "unknown"}`,
    "data-hook": "frozen-position-class",
    text: CLASS_CHIP_LABEL[cls] || cls || "UNKNOWN CLASS",
  }));
  if (rec.staked) {
    const settlement = rec.settlement || {};
    const meta = SETTLEMENT_CHIP[settlement.status] || {
      text: settlement.status ? String(settlement.status).toUpperCase() : "NO SETTLEMENT DATA",
      cls: "day-settle--pending",
    };
    head.appendChild(el("span", { class: `day-settle ${meta.cls}`, "data-hook": "settlement-chip", text: meta.text }));
  } else {
    head.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--outline", text: "NOT STAKED" }));
  }
  row.appendChild(head);

  row.appendChild(el("p", { class: "mx-pos__meaning", text: CLASS_MEANING[cls] || "" }));

  const sideLine = [rec.market_key, rec.side ? String(rec.side).toUpperCase() : null,
    (rec.line !== null && rec.line !== undefined) ? String(rec.line) : null].filter(Boolean).join(" · ");
  row.appendChild(el("p", { class: "mx-pos__market", text: sideLine || "no market recorded" }));

  const figs = el("div", { class: "mx-pos__figs" });
  const priceText = formatAmerican(rec.price_american);
  figs.appendChild(el("span", { class: "mx-pos__price", text: priceText || "—" }));
  figs.appendChild(el("span", { class: "mx-pos__books",
    text: typeof rec.books_at_decision === "number"
      ? `${rec.books_at_decision} books at decision` : "books at decision not available" }));
  row.appendChild(figs);

  if (typeof rec.value_points === "number") {
    row.appendChild(el("span", { class: "mx-pos__vp",
      text: `${rec.value_points >= 0 ? "+" : ""}${rec.value_points.toFixed(2)} pts` }));
  } else {
    row.appendChild(el("p", { class: "mx-pos__vp-reason", "data-hook": "frozen-position-vp-reason",
      text: rec.value_points_reason || "No value comparison reported for this position." }));
  }

  const settlement = rec.settlement || {};
  if ((settlement.status === "win" || settlement.status === "loss" || settlement.status === "push")
      && typeof settlement.profit_units === "number") {
    const tone = settlement.profit_units >= 0 ? "mx-pos__profit--pos" : "mx-pos__profit--neg";
    row.appendChild(el("span", { class: `mx-pos__profit ${tone}`, "data-hook": "frozen-position-profit",
      text: `${settlement.profit_units >= 0 ? "+" : ""}${settlement.profit_units.toFixed(2)}u` }));
  }

  return row;
}

function noForwardTestNote(recs) {
  const hasForward = recs.some((r) => r.system_class === "FORWARD_TEST");
  if (hasForward) return null;
  return el("p", { class: "mx-frozen__none-forward", "data-hook": "no-forward-test-note",
    text: "No system with a directional thesis played this game." });
}

function frozenPositionsBlock(dailyGame) {
  const block = el("div", { class: "mx-frozen", "data-hook": "matchup-frozen-positions" });
  block.appendChild(el("div", { class: "mx-frozen__title", text: FROZEN_TITLE }));

  if (!dailyGame) {
    block.appendChild(notYetAvailable(
      "No frozen pregame record joined to this game yet.", "NO RECORD"));
    return block;
  }
  const staked = (dailyGame.recommendations || []).filter((r) => r.staked);
  if (staked.length === 0) {
    block.appendChild(el("p", { class: "mx-frozen__empty", text: "No paper position was staked on this game." }));
    return block;
  }

  const note = noForwardTestNote(staked);
  if (note) block.appendChild(note);

  const list = el("div", { class: "mx-frozen__list" });
  for (const rec of staked) list.appendChild(frozenPositionRow(rec));

  if (staked.length > 4) {
    const details = el("details", { class: "mx-frozen__details" });
    details.appendChild(el("summary", { text: `${staked.length} PAPER POSITIONS -- SHOW ALL` }));
    details.appendChild(list);
    block.appendChild(details);
  } else {
    block.appendChild(list);
  }
  return block;
}

/* ---------------------------------------------------------------------
 * The game's own record + FINAL chip + settled units net.
 * ------------------------------------------------------------------- */
function gameOutcomeLine(dailyGame) {
  const wrap = el("div", { class: "mx-outcome", "data-hook": "matchup-outcome" });
  if (!dailyGame) {
    wrap.appendChild(el("span", { class: "mx-outcome__record", text: "No settlement record joined to this game yet." }));
    return wrap;
  }
  if (dailyGame.status === "final") {
    wrap.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--neutral", "data-hook": "final-chip",
      text: "FINAL" }));
    if (dailyGame.final_score) {
      wrap.appendChild(el("span", { class: "mx-outcome__score",
        text: `${dailyGame.away_team} ${dailyGame.final_score.away} — ${dailyGame.home_team} ${dailyGame.final_score.home}` }));
    } else if (dailyGame.final_score_reason) {
      wrap.appendChild(el("span", { class: "mx-outcome__score-reason", text: dailyGame.final_score_reason }));
    }
  }
  const record = dailyGame.record || {};
  wrap.appendChild(el("span", { class: "mx-outcome__record", "data-hook": "matchup-record",
    text: `GAME RECORD ${record.wins}-${record.losses}-${record.pushes}`
      + `${record.pending ? ` · ${record.pending} PENDING` : ""}` }));
  if (typeof dailyGame.settled_units_net === "number") {
    const tone = dailyGame.settled_units_net >= 0 ? "mx-outcome__net--pos" : "mx-outcome__net--neg";
    wrap.appendChild(el("span", { class: `mx-outcome__net ${tone}`,
      text: `${dailyGame.settled_units_net >= 0 ? "+" : ""}${dailyGame.settled_units_net.toFixed(2)}u settled` }));
  }
  return wrap;
}

/* ---------------------------------------------------------------------
 * The live moneyline + LIVE PRICE READ -- both read the SAME matching
 * GET /opportunities/{date} row (market === "h2h") per side; this screen
 * never re-derives a price comparison of its own.
 * ------------------------------------------------------------------- */
function moneylineSideFigures(row) {
  const wrap = el("div", { class: "mx-ml__side" });
  const priceText = formatAmerican(row.best_price);
  wrap.appendChild(el("span", { class: "mx-ml__price", "data-hook": "matchup-best-price", text: priceText || "—" }));
  if (row.best_book) wrap.appendChild(el("span", { class: "mx-ml__book", text: bookLabel(row.best_book) }));
  const consensus = formatConsensusShare(row.market_implied_probability);
  wrap.appendChild(el("span", { class: "mx-ml__consensus",
    text: `MARKET-IMPLIED ${consensus || "—"}${typeof row.books === "number" ? ` · ${row.books} books` : ""}` }));
  const age = formatAge(row.age_seconds);
  wrap.appendChild(el("span", { class: "mx-ml__age", text: age || "capture age not available" }));
  return wrap;
}

function moneylineBlock(away, home, h2h, unpricedReason) {
  const block = el("div", { class: "mx-ml", "data-hook": "matchup-moneyline" });
  block.appendChild(el("div", { class: "mx-ml__title", text: "MONEYLINE" }));
  if (!h2h.away && !h2h.home) {
    block.appendChild(notYetAvailable(
      unpricedReason || "No priced board for this game yet.", "NO BOARD"));
    return block;
  }
  const cols = el("div", { class: "mx-ml__cols" });
  for (const [abbr, row] of [[away, h2h.away], [home, h2h.home]]) {
    const col = el("div", { class: "mx-ml__col" });
    col.appendChild(el("span", { class: "mx-ml__abbr", text: abbr }));
    if (row) col.appendChild(moneylineSideFigures(row));
    else col.appendChild(el("p", { class: "mx-ml__none", text: "No book has posted a price on this side yet." }));
    cols.appendChild(col);
  }
  block.appendChild(cols);
  return block;
}

function livePriceReadSide(abbr, row) {
  const side = el("div", { class: "mx-read__side", "data-hook": "matchup-price-read-side" });
  side.appendChild(el("span", { class: "mx-read__abbr", text: abbr }));
  side.appendChild(renderWordChip(row.price_verdict ? row.price_verdict.word : null));
  if (typeof row.value_points === "number") {
    // Only reuse the shared meter once a real value_points exists -- below
    // the six-book floor market_implied/stated_implied can both still be
    // present numbers even though the comparison itself is INSUFFICIENT
    // DATA, and valuemeter.js's own null-valuePoints fallback would
    // otherwise silently recompute a gap this product has explicitly
    // refused to report. See row.reasons for that case instead, below.
    side.appendChild(renderValueMeter({
      marketImplied: row.market_implied_probability,
      priceImplied: row.stated_implied_probability,
      valuePoints: row.value_points,
      word: null,
    }));
  } else {
    const reasons = Array.isArray(row.reasons) && row.reasons.length
      ? row.reasons.join(" ") : "No value comparison reported for this side.";
    side.appendChild(el("p", { class: "mx-read__reason", "data-hook": "matchup-price-read-reason", text: reasons }));
  }
  return side;
}

function livePriceReadBlock(away, home, h2h, unpricedReason) {
  const block = el("div", { class: "mx-read", "data-hook": "matchup-price-read" });
  block.appendChild(el("div", { class: "mx-read__title", text: "LIVE PRICE READ" }));
  if (!h2h.away && !h2h.home) {
    block.appendChild(el("p", { class: "mx-read__reason",
      text: unpricedReason || "No priced side for this game yet." }));
    return block;
  }
  for (const [abbr, row] of [[away, h2h.away], [home, h2h.home]]) {
    if (row) block.appendChild(livePriceReadSide(abbr, row));
  }
  return block;
}

/* ---------------------------------------------------------------------
 * One card
 * ------------------------------------------------------------------- */
function matchupCard(entry, date, indices) {
  const game = (entry.dossier && entry.dossier.game) || {};
  const away = game.away_team;
  const home = game.home_team;
  const key = gameKeyOf(away, home);
  const dailyGame = indices.dailyByKey.get(gameKeyOf(normalizeAbbr(away), normalizeAbbr(home))) || null;
  const h2h = indices.oppRowsByKey.get(key) || { away: null, home: null };
  const unpricedReason = indices.unpricedByKey.get(key) || null;
  const qualifies = indices.qualifyingKeys.has(key);

  const card = el("article", {
    class: `mx-card panel chamfer${qualifies ? " mx-card--qualifies" : ""}`,
    "data-hook": "matchup-card", "data-game-key": key,
  });

  const header = el("div", { class: "mx-card__header" });
  header.appendChild(teamBadge(away));
  header.appendChild(el("span", { class: "mx-card__matchup",
    text: `${teamName(away, "name") || away} @ ${teamName(home, "name") || home}` }));
  header.appendChild(teamBadge(home));
  card.appendChild(header);

  const meta = [];
  const pitch = formatEasternTime(game.start_time_utc);
  if (pitch) meta.push(pitch);
  if (game.venue) meta.push(game.venue);
  card.appendChild(el("p", { class: "mx-card__meta", text: meta.join(" · ") || "First pitch time not available." }));

  const probables = el("div", { class: "mx-card__probables", "data-hook": "matchup-probables" });
  for (const [abbr, name] of [[away, game.away_probable], [home, game.home_probable]]) {
    const line = el("span", { class: "mx-card__probable" });
    line.appendChild(el("span", { class: "mx-card__probable-abbr", text: abbr }));
    line.appendChild(name
      ? document.createTextNode(name)
      : el("span", { class: "mx-card__probable-none", text: "starter unannounced" }));
    probables.appendChild(line);
  }
  card.appendChild(probables);

  card.appendChild(moneylineBlock(away, home, h2h, unpricedReason));
  card.appendChild(livePriceReadBlock(away, home, h2h, unpricedReason));
  card.appendChild(frozenPositionsBlock(dailyGame));
  card.appendChild(gameOutcomeLine(dailyGame));

  card.appendChild(el("a", { class: "mx-card__link", "data-hook": "matchup-open-game",
    href: `#/game/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`,
    text: "OPEN THIS GAME" }));

  return card;
}

/* ---------------------------------------------------------------------
 * View
 * ------------------------------------------------------------------- */

/**
 * Renders THE MATCHUP GRID into `container` for `date` (the calendar date
 * GET /daily/{date} and GET /opportunities/{date} should be read for --
 * normally the same date GET /today itself returns, since GET /today has
 * no {date} parameter of its own). Never throws -- a fetch failure for
 * any of the three sources renders an honest in-place state instead of
 * blanking the rest of the Today screen.
 */
export async function renderMatchups(container, date) {
  const section = el("section", { class: "mx-section", "data-hook": "matchup-grid" });
  container.appendChild(section);
  section.appendChild(sectionHead("THE MATCHUP GRID", "EVERY GAME ON TONIGHT'S SLATE"));
  const body = el("div", { class: "mx-body" });
  body.appendChild(renderLoading("LOADING THE MATCHUP GRID"));
  section.appendChild(body);

  let todayPayload;
  try {
    todayPayload = await apiGet("/today");
  } catch (err) {
    clear(body);
    renderError(body, err);
    return section;
  }

  const [dailyPayload, oppPayload] = await Promise.all([
    apiGet(`/daily/${encodeURIComponent(date)}`).catch(() => null),
    apiGet(`/opportunities/${encodeURIComponent(date)}`).catch(() => null),
  ]);
  clear(body);

  const games = todayPayload.games || [];
  if (games.length === 0) {
    body.appendChild(notYetAvailable("No games on tonight's slate.", "NOTHING SCHEDULED"));
    return section;
  }

  const dailyByKey = new Map();
  for (const g of (dailyPayload && dailyPayload.games) || []) {
    dailyByKey.set(gameKeyOf(normalizeAbbr(g.away_team), normalizeAbbr(g.home_team)), g);
  }

  const oppRowsByKey = new Map();
  for (const row of (oppPayload && oppPayload.rows) || []) {
    if (row.market !== "h2h") continue;
    const key = gameKeyOf(row.away_team, row.home_team);
    const bucket = oppRowsByKey.get(key) || { away: null, home: null };
    if (row.side === "away") bucket.away = row;
    else if (row.side === "home") bucket.home = row;
    oppRowsByKey.set(key, bucket);
  }

  const unpricedByKey = new Map();
  for (const u of (oppPayload && oppPayload.unpriced) || []) {
    unpricedByKey.set(gameKeyOf(u.away_team, u.home_team), u.reason || null);
  }

  const qualifyingKeys = new Set(
    ((oppPayload && oppPayload.qualifying) || []).map((r) => gameKeyOf(r.away_team, r.home_team)));

  const indices = { dailyByKey, oppRowsByKey, unpricedByKey, qualifyingKeys };

  const sorted = games.slice().sort((a, b) => {
    const gameA = (a.dossier && a.dossier.game) || {};
    const gameB = (b.dossier && b.dossier.game) || {};
    const qualifiesA = qualifyingKeys.has(gameKeyOf(gameA.away_team, gameA.home_team)) ? 0 : 1;
    const qualifiesB = qualifyingKeys.has(gameKeyOf(gameB.away_team, gameB.home_team)) ? 0 : 1;
    if (qualifiesA !== qualifiesB) return qualifiesA - qualifiesB;
    const timeA = Date.parse(gameA.start_time_utc || "") || Infinity;
    const timeB = Date.parse(gameB.start_time_utc || "") || Infinity;
    return timeA - timeB;
  });

  const grid = el("div", { class: "mx-grid" });
  for (const entry of sorted) grid.appendChild(matchupCard(entry, date, indices));
  body.appendChild(grid);

  if (!dailyPayload) {
    body.appendChild(notYetAvailable(
      "The frozen pregame record did not load for this date -- paper positions are not shown below.",
      "RECORD UNREACHABLE"));
  }
  if (!oppPayload) {
    body.appendChild(notYetAvailable(
      "Live price data did not load for this date -- the moneyline and price-read sections are not shown below.",
      "PRICE DATA UNREACHABLE"));
  }

  return section;
}
