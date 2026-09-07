/**
 * DAILY RECAP -- the gallery (renderDayRecap, GET /daily) and the full
 * per-day audit trail (renderDayDetail, GET /daily/{date}, #/day/{date}).
 * The gallery is mounted at the top of #/performance, above the existing
 * paper-standings content (web/js/performance.js's own call site); the
 * detail route is registered in main.js as SECTION_LABELS.day.
 *
 * WHY THE DETAIL VIEW EXISTS AT ALL
 * -------------------------------------------------------------------
 * GET /daily/{date} is Task C1's FROZEN PREGAME RECORD -- every
 * recommendation exactly as the engine wrote it before first pitch,
 * joined (never recomputed) against whatever settlement fact exists for
 * it today. This screen's whole job is to read as "this is exactly what
 * was decided, before, and here is what happened" -- so, unlike
 * web/js/matchups.js's Today-screen card (which shows only STAKED
 * positions, collapsed past four), this view lists every recommendation
 * GET /daily/{date} returns, staked or not, uncollapsed: the audit trail
 * is not the place to hide anything for tidiness.
 *
 * `frozenPositionRow` and `CLASS_MEANING` are imported from
 * web/js/matchups.js rather than redefined here -- ONE renderer for one
 * recommendation row, reused by both surfaces, so a class chip or a
 * settlement color can never drift between the Today grid and this audit
 * trail.
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading, notYetAvailable, formatAmerican } from "./dom.js";
import { frozenPositionRow } from "./matchups.js";

// This product's forward-testing record only runs within 2026 (see
// CLAUDE.md's "2025 tuning-only, sealed 2026" policy) -- GET /daily can
// still surface an older, sealed backtest date mixed into the same
// ledger (2023-04-18 is the one currently known). Nothing on the payload
// itself flags this, so the honest, generic signal this client can check
// without guessing is the calendar year: any date before this product's
// live season reads as a historical backtest, never presented as a
// normal night's slate.
const LIVE_SEASON_CUTOFF = "2025-01-01";

function isHistoricalBacktest(dateIso) {
  return typeof dateIso === "string" && dateIso.length >= 10 && dateIso < LIVE_SEASON_CUTOFF;
}

function unitsFmt(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}u`;
}

function pctFmt(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  return `${fraction > 0 ? "+" : ""}${(fraction * 100).toFixed(1)}%`;
}

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

/** "Sunday, Apr 18, 2023" -- a bare `YYYY-MM-DD` slate date formatted in
 * UTC (a calendar date, not an instant -- same convention today.js's own
 * slateDateLabel uses). Falls back to the raw ISO string when the date
 * cannot be parsed, never a fabricated label. */
function dayDateLabel(dateIso) {
  if (!dateIso) return null;
  const d = new Date(`${dateIso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC", weekday: "long", month: "short", day: "numeric", year: "numeric",
  }).format(d);
}

/* ---------------------------------------------------------------------
 * Gallery -- one card per GET /daily row
 * ------------------------------------------------------------------- */

function dayBetLine(label, bet, withBasis) {
  const wrap = el("div", { class: "day-card__bet", "data-hook": "day-card-bet" });
  wrap.appendChild(el("span", { class: "day-card__bet-label", text: label }));
  const priceText = formatAmerican(bet.price_american);
  const sideLine = [bet.market_key, bet.side ? String(bet.side).toUpperCase() : null,
    (bet.line !== null && bet.line !== undefined) ? String(bet.line) : null].filter(Boolean).join(" ");
  wrap.appendChild(el("span", { class: "day-card__bet-line",
    text: `${bet.matchup || "—"} · ${sideLine || "—"} at ${priceText || "—"}` }));
  if (typeof bet.profit_units === "number") {
    const tone = bet.profit_units >= 0 ? "day-card__bet-profit--pos" : "day-card__bet-profit--neg";
    wrap.appendChild(el("span", { class: tone,
      text: `${bet.profit_units >= 0 ? "+" : ""}${bet.profit_units.toFixed(2)}u` }));
  } else if (typeof bet.value_points === "number") {
    wrap.appendChild(el("span", { class: "day-card__bet-vp",
      text: `${bet.value_points >= 0 ? "+" : ""}${bet.value_points.toFixed(2)} pts` }));
  } else if (bet.value_points_reason) {
    wrap.appendChild(el("p", { class: "day-card__bet-basis", text: bet.value_points_reason }));
  }
  if (withBasis && bet.basis) wrap.appendChild(el("p", { class: "day-card__bet-basis", text: bet.basis }));
  return wrap;
}

function dayCard(day) {
  const card = el("article", { class: "day-card panel chamfer", "data-hook": "day-card" });

  const head = el("div", { class: "day-card__head" });
  head.appendChild(el("a", { class: "day-card__date", href: `#/day/${encodeURIComponent(day.date)}`,
    text: dayDateLabel(day.date) || day.date }));
  if (isHistoricalBacktest(day.date)) {
    head.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--outline day-card__backtest",
      "data-hook": "historical-backtest-chip", text: "HISTORICAL BACKTEST" }));
  }
  card.appendChild(head);

  if (day.settled) {
    const record = `${day.wins}-${day.losses}-${day.pushes}`;
    const units = unitsFmt(day.units_net);
    const pct = pctFmt(day.return_on_units);
    const line = el("p", { class: "day-card__record", "data-hook": "day-record-line" });
    line.appendChild(document.createTextNode(record));
    if (units !== null) {
      const tone = day.units_net > 0 ? "day-card__figure--pos" : day.units_net < 0 ? "day-card__figure--neg" : "";
      line.appendChild(el("span", { class: tone, text: ` · ${units}` }));
    }
    if (pct !== null) line.appendChild(document.createTextNode(` · ${pct}`));
    card.appendChild(line);
  } else {
    card.appendChild(el("p", { class: "day-card__pending", "data-hook": "day-record-line",
      text: `${day.pending} position${day.pending === 1 ? "" : "s"} pending` }));
  }

  card.appendChild(el("p", { class: "day-card__meta",
    text: `${day.n_staked} staked`
      + `${typeof day.avg_odds_decimal === "number" ? ` · avg odds ${day.avg_odds_decimal.toFixed(2)} (decimal)` : ""}` }));

  if (day.best_bet) card.appendChild(dayBetLine("BEST", day.best_bet));
  if (day.worst_bet) card.appendChild(dayBetLine("WORST", day.worst_bet));
  if (day.strongest_pregame) card.appendChild(dayBetLine("STRONGEST PREGAME", day.strongest_pregame, true));

  card.appendChild(el("a", { class: "day-card__link", href: `#/day/${encodeURIComponent(day.date)}`,
    text: "OPEN THE FULL RECORD" }));
  return card;
}

/**
 * Fetches GET /daily and renders the newest-first recap gallery into
 * `container`. Never throws -- a fetch failure renders dom.js's own
 * error treatment inside the section instead of blanking the rest of
 * whatever screen mounted it (web/js/performance.js).
 */
export async function renderDayRecap(container) {
  const section = el("section", { class: "day-gallery-section", "data-hook": "day-recap-gallery" });
  container.appendChild(section);
  section.appendChild(sectionHead("DAILY RECAP", "EVERY SLATE, SETTLED AND PENDING"));
  const body = el("div", { class: "day-gallery-body" });
  body.appendChild(renderLoading("LOADING THE DAILY RECAP"));
  section.appendChild(body);

  let payload;
  try {
    payload = await apiGet("/daily?limit=30");
  } catch (err) {
    clear(body);
    renderError(body, err);
    return section;
  }
  clear(body);

  const days = payload.days || [];
  if (days.length === 0) {
    body.appendChild(notYetAvailable("No days recorded yet.", "NO DAYS"));
    return section;
  }
  const grid = el("div", { class: "day-gallery" });
  for (const day of days) grid.appendChild(dayCard(day));
  body.appendChild(grid);
  return section;
}

/* ---------------------------------------------------------------------
 * Detail -- #/day/{date}, GET /daily/{date}, the full audit trail
 * ------------------------------------------------------------------- */

function dayRollupSummary(rollup) {
  const wrap = el("div", { class: "day-detail__rollup panel chamfer", "data-hook": "day-detail-rollup" });
  if (!rollup) {
    wrap.appendChild(notYetAvailable("No rollup for this date.", "NO ROLLUP"));
    return wrap;
  }
  wrap.appendChild(el("div", { class: "day-detail__rollup-title", text: "DAY ROLLUP" }));
  wrap.appendChild(el("p", { class: "day-detail__rollup-line",
    text: `${rollup.n_games} games · ${rollup.n_staked} staked of ${rollup.n_recommendations} recommendations · `
      + `${rollup.wins}-${rollup.losses}-${rollup.pushes}`
      + `${rollup.pending ? ` · ${rollup.pending} pending` : ""}` }));
  const units = unitsFmt(rollup.units_net);
  const pct = pctFmt(rollup.return_on_units);
  const figs = [units, pct].filter((v) => v !== null);
  if (figs.length) wrap.appendChild(el("p", { class: "day-detail__rollup-figs", text: figs.join(" · ") }));
  return wrap;
}

function dayDetailGame(game) {
  const card = el("article", { class: "day-detail__game panel chamfer", "data-hook": "day-detail-game" });

  const head = el("div", { class: "day-detail__game-head" });
  head.appendChild(el("span", { class: "day-detail__game-matchup",
    text: `${game.away_name || game.away_team} @ ${game.home_name || game.home_team}` }));
  if (game.status === "final") {
    head.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--neutral", text: "FINAL" }));
  }
  card.appendChild(head);

  if (game.final_score) {
    card.appendChild(el("p", { class: "day-detail__game-score",
      text: `${game.away_team} ${game.final_score.away} — ${game.home_team} ${game.final_score.home}` }));
  } else if (game.final_score_reason) {
    card.appendChild(el("p", { class: "day-detail__game-score-reason", text: game.final_score_reason }));
  }

  const record = game.record || {};
  card.appendChild(el("p", { class: "day-detail__game-record",
    text: `GAME RECORD ${record.wins}-${record.losses}-${record.pushes}`
      + `${record.pending ? ` · ${record.pending} PENDING` : ""}` }));
  if (typeof game.settled_units_net === "number") {
    const tone = game.settled_units_net >= 0 ? "day-detail__game-net--pos" : "day-detail__game-net--neg";
    card.appendChild(el("p", { class: tone,
      text: `${game.settled_units_net >= 0 ? "+" : ""}${game.settled_units_net.toFixed(2)}u settled` }));
  }

  const recs = game.recommendations || [];
  if (recs.length === 0) {
    card.appendChild(notYetAvailable("No recommendations recorded for this game.", "NO RECOMMENDATIONS"));
  } else {
    const list = el("div", { class: "day-detail__positions" });
    for (const rec of recs) list.appendChild(frozenPositionRow(rec));
    card.appendChild(list);
  }
  return card;
}

/**
 * Fetches GET /daily/{date} and renders the full FROZEN PREGAME RECORD
 * audit trail into `container`. Never throws -- a fetch failure renders
 * dom.js's own error treatment in place of the whole view.
 */
export async function renderDayDetail(container, date) {
  clear(container);
  const screen = el("div", { class: "screen day-detail-screen", "data-view": "day" });
  container.appendChild(screen);
  screen.appendChild(renderLoading("LOADING THE FROZEN RECORD"));

  let payload;
  try {
    payload = await apiGet(`/daily/${encodeURIComponent(date)}`);
  } catch (err) {
    clear(screen);
    renderError(screen, err);
    return;
  }
  clear(screen);

  screen.appendChild(el("a", { class: "day-detail__back", href: "#/performance", text: "← BACK TO PERFORMANCE" }));

  const head = el("div", { class: "day-detail__head" });
  head.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--outline",
    text: payload.label || "FROZEN PREGAME RECORD" }));
  head.appendChild(el("h2", { class: "day-detail__date", text: dayDateLabel(payload.date) || payload.date }));
  if (isHistoricalBacktest(payload.date)) {
    head.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--outline",
      "data-hook": "historical-backtest-chip", text: "HISTORICAL BACKTEST" }));
  }
  screen.appendChild(head);

  screen.appendChild(el("p", { class: "day-detail__basis", text: payload.basis || "" }));
  screen.appendChild(el("p", { class: "day-detail__stake-policy",
    text: `Stake policy: ${payload.stake_policy || "—"}` }));
  screen.appendChild(el("p", { class: "day-detail__settled-through",
    text: `Settled through ${(payload.freshness && payload.freshness.settled_through) || "not yet available"}` }));

  screen.appendChild(dayRollupSummary(payload.rollup));

  const games = payload.games || [];
  if (games.length === 0) {
    screen.appendChild(notYetAvailable("No games recorded for this date.", "NO GAMES"));
  } else {
    const list = el("div", { class: "day-detail__games" });
    for (const game of games) list.appendChild(dayDetailGame(game));
    screen.appendChild(list);
  }

  for (const note of payload.notes || []) {
    screen.appendChild(el("p", { class: "day-detail__note", text: note }));
  }
}
