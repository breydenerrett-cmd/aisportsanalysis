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
import { CLASS_MEANING } from "./matchups.js";

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
  // Same treatment the detail page's rows get: "OAK moneyline", not
  // "h2h AWAY". The gallery row carries only `matchup` ("OAK @ SEA"), so
  // the two abbreviations are read back off it -- and only when it really
  // has that shape. If it does not, humanizeBetLabel falls through to its
  // own no-guess path exactly as it does on the detail page.
  const sides = String(bet.matchup || "").split(" @ ");
  const gameLike = sides.length === 2
    ? { away_team: sides[0].trim(), home_team: sides[1].trim() }
    : null;
  const sideLine = humanizeBetLabel(bet, gameLike);
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
    // FORWARD-TEST ONLY, matching the record strip above this gallery.
    //
    // These cards used to print day.wins/losses/units_net, which pool
    // CONTROL and MARKET_REFERENCE -- the null baselines and the
    // market-reference republishers, roughly 90% of measured positions and
    // nothing anyone is sold. src/report/daily_record.py's record_strip was
    // fixed to exclude them and captioned "our forward-test systems only";
    // a reader scrolled two inches and met thirty daily cards computed the
    // old way, with no caption. Same product, two numbers, no explanation
    // of which was which.
    //
    // Falls back to the pooled figures ONLY when by_class is absent (an
    // older payload). It says so in that case rather than quietly implying
    // the cohort.
    const hasSplit = Boolean(day.by_class);
    const fwd = (day.by_class || {}).FORWARD_TEST;

    if (hasSplit && !fwd) {
      // A DAY WITH NO FORWARD-TEST SETTLEMENTS IS NOT A DAY WITH A RECORD.
      // Falling back to the pooled figures here would be the worst version
      // of the bug this whole change exists to fix: on 2026-09-05 and
      // 2026-09-06 the gallery showed 45-52-2 and 47-40-3, and NOT ONE of
      // those positions came from a system anybody is sold -- they were
      // entirely null baselines and market-reference republishers. The same
      // is true of the 2023 backtest day. A reader saw a losing record and
      // attributed it to us; on another night they would have seen a
      // winning one and done the same.
      card.appendChild(el("p", { class: "day-card__pending", "data-hook": "day-record-line",
        text: "No forward-test positions settled" }));
      card.appendChild(el("p", { class: "day-card__cohort", "data-hook": "day-record-cohort",
        text: "Only null baselines and market-reference systems ran this day" }));
    } else {
      const src = fwd || day;
      const staked = typeof src.units_staked === "number" ? src.units_staked : null;
      const netUnits = src.units_net;
      const ret = hasSplit ? (staked ? netUnits / staked : null) : day.return_on_units;

      const record = `${src.wins}-${src.losses}-${src.pushes}`;
      const units = unitsFmt(netUnits);
      const pct = pctFmt(ret);
      const line = el("p", { class: "day-card__record", "data-hook": "day-record-line" });
      line.appendChild(document.createTextNode(record));
      if (units !== null) {
        const tone = netUnits > 0 ? "day-card__figure--pos" : netUnits < 0 ? "day-card__figure--neg" : "";
        line.appendChild(el("span", { class: tone, text: ` · ${units}` }));
      }
      if (pct !== null) line.appendChild(document.createTextNode(` · ${pct}`));
      card.appendChild(line);
      card.appendChild(el("p", { class: "day-card__cohort", "data-hook": "day-record-cohort",
        text: hasSplit ? "Forward-test systems only"
                       : "All classes pooled — per-class split unavailable for this day" }));
    }
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
  // The headline for the whole day. It used to be two mono lines in a box,
  // which is how the rest of this page's rows are set -- so the day's own
  // result read no louder than one of the two hundred rows beneath it. The
  // same figures, given the display treatment the Results gallery cards
  // already use, with the counts kept as supporting meta.
  wrap.appendChild(el("div", { class: "day-detail__rollup-title", text: "DAY ROLLUP" }));

  const units = unitsFmt(rollup.units_net);
  const pct = pctFmt(rollup.return_on_units);
  const headline = el("p", { class: "day-detail__rollup-headline" });
  headline.appendChild(el("span", { class: "day-detail__rollup-record",
    text: `${rollup.wins}-${rollup.losses}-${rollup.pushes}` }));
  const tone = (value) => (typeof value === "number"
    ? (value >= 0 ? " day-detail__rollup-fig--pos" : " day-detail__rollup-fig--neg") : "");
  if (units !== null) {
    headline.appendChild(el("span", { class: "day-detail__rollup-sep", text: "·" }));
    headline.appendChild(el("span", {
      class: `day-detail__rollup-fig${tone(rollup.units_net)}`, text: units }));
  }
  if (pct !== null) {
    headline.appendChild(el("span", { class: "day-detail__rollup-sep", text: "·" }));
    headline.appendChild(el("span", {
      class: `day-detail__rollup-fig${tone(rollup.return_on_units)}`, text: pct }));
  }
  wrap.appendChild(headline);

  wrap.appendChild(el("p", { class: "day-detail__rollup-line",
    text: `${rollup.n_games} games · ${rollup.n_staked} staked of ${rollup.n_recommendations} recommendations`
      + `${rollup.pending ? ` · ${rollup.pending} pending` : ""}` }));
  return wrap;
}

// Local copies of matchups.js's private CLASS_CHIP_LABEL / SETTLEMENT_CHIP --
// only CLASS_MEANING is exported from that module, and this file owns its
// own row renderer now (see the ROW RENDERER comment below), so these two
// small, static display maps are kept in sync by hand rather than imported.
// Any drift here is a display-label typo, not an honesty issue: the actual
// class/settlement values driving color and meaning still come from
// matchups.js's own CLASS_MEANING and the payload's own settlement.status.
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

// market_key -> the plain-English noun for that market. Never guessed --
// an unrecognized market_key falls through to the raw key itself below.
const MARKET_NOUN = { h2h: "moneyline", spreads: "spread", totals: "total" };

/** "home"/"away"/"over"/"under" (case-insensitive) are the only side
 * values this client knows how to turn into a bet phrase. Anything else --
 * including the stray 16-hex genome id seen leaking into this field on one
 * row -- is NOT guessed at; the caller falls back to printing it verbatim. */
function knownSide(side) {
  if (typeof side !== "string") return null;
  const s = side.toLowerCase();
  return (s === "home" || s === "away" || s === "over" || s === "under") ? s : null;
}

function teamAbbrForSide(side, game) {
  if (side === "home") return (game && game.home_team) || null;
  if (side === "away") return (game && game.away_team) || null;
  return null;
}

function formatLineText(line) {
  if (line === null || line === undefined || line === "") return null;
  const n = Number(line);
  if (Number.isFinite(n)) return n > 0 ? `+${n}` : `${n}`;
  return String(line);
}

/**
 * Turns one recommendation's market_key/side/line into a bet phrase a
 * customer reads naturally -- "ARI moneyline", "Under 8.5", "HOU -1.5" --
 * using the game's OWN away/home abbreviations (never a guess). Every
 * branch either resolves a real value or falls through to the last
 * paragraph, which prints whatever raw components exist and nothing it
 * doesn't have -- the same "never a fabricated label" rule dayDateLabel
 * above states for the date. This is presentation only: no field here is
 * recomputed, just reworded.
 */
function humanizeBetLabel(rec, game) {
  const marketKey = rec.market_key;
  const side = knownSide(rec.side);
  const lineText = formatLineText(rec.line);

  if (marketKey === "h2h") {
    const abbr = teamAbbrForSide(side, game);
    if (abbr) return `${abbr} moneyline`;
  } else if (marketKey === "spreads") {
    const abbr = teamAbbrForSide(side, game);
    if (abbr && lineText) return `${abbr} ${lineText}`;
    if (abbr) return `${abbr} spread`;
  } else if (marketKey === "totals") {
    if (side === "over") return lineText ? `Over ${lineText}` : "Over";
    if (side === "under") return lineText ? `Under ${lineText}` : "Under";
  }

  // Nothing above could be resolved. Show exactly what the payload has
  // rather than fabricate a team -- with one exception that is still not a
  // fabrication: some records carry a 16-hex system id in `side` where a
  // side belongs, and printing it produced "spread · ac8dfe0cf3aeecdb ·
  // +1.5" on a customer page. That string is not a bet and not a side. The
  // row still shows the market and the line it really has, and says
  // plainly that the side was not recorded. Nothing is invented: no team
  // is guessed, and the id is not silently dropped as if the field were
  // empty -- it was populated, just not with a side.
  const marketText = MARKET_NOUN[marketKey] || marketKey || "unknown market";
  const rawSide = rec.side === null || rec.side === undefined ? "" : String(rec.side);
  const sideIsSystemId = /^[0-9a-f]{16}$/i.test(rawSide);
  const parts = [marketText];
  if (rawSide && !sideIsSystemId) parts.push(rawSide);
  if (lineText) parts.push(lineText);
  if (sideIsSystemId) parts.push("side not recorded (a system id was stored here)");
  return parts.length ? parts.join(" · ") : "no market recorded";
}

/* ---------------------------------------------------------------------
 * ROW RENDERER -- one compact recommendation row for this detail page
 * only. matchups.js's frozenPositionRow (shared with the Today grid,
 * which shows at most 4 STAKED positions per game) prints the class
 * chip's full meaning sentence and the full thin-board explanation on
 * every row; on this page that renders up to ~213 times on a single
 * slate, which is the wall this row exists to fix. Both explanations
 * stay fully reachable -- see dayDetailLegend below -- just not repeated
 * per row. The class chip color classes (mx-pos__class--*) and the
 * settlement chip classes (day-settle--*) are shared, generic selectors
 * already used by matchups.js, reused here (not redefined) so a WIN/LOSS
 * color or a class tint still can never drift between the two screens.
 * ------------------------------------------------------------------- */
function dayPositionRow(rec, game) {
  const row = el("div", { class: "day-pos", "data-hook": "day-position" });

  const top = el("div", { class: "day-pos__top" });
  const cls = rec.system_class;
  top.appendChild(el("span", {
    class: `badge chamfer chamfer--chip day-pos__class mx-pos__class--${cls ? cls.toLowerCase() : "unknown"}`,
    "data-hook": "day-position-class",
    text: CLASS_CHIP_LABEL[cls] || cls || "UNKNOWN CLASS",
  }));
  if (rec.staked) {
    const settlement = rec.settlement || {};
    const meta = SETTLEMENT_CHIP[settlement.status] || {
      text: settlement.status ? String(settlement.status).toUpperCase() : "NO SETTLEMENT DATA",
      cls: "day-settle--pending",
    };
    top.appendChild(el("span", { class: `day-settle ${meta.cls}`, "data-hook": "day-position-settlement", text: meta.text }));
  } else {
    top.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--outline", text: "NOT STAKED" }));
  }
  top.appendChild(el("span", { class: "day-pos__label", "data-hook": "day-position-label",
    text: humanizeBetLabel(rec, game) }));
  const priceText = formatAmerican(rec.price_american);
  top.appendChild(el("span", { class: "day-pos__price", text: priceText || "—" }));

  const settlement = rec.settlement || {};
  if ((settlement.status === "win" || settlement.status === "loss" || settlement.status === "push")
      && typeof settlement.profit_units === "number") {
    const tone = settlement.profit_units >= 0 ? "day-pos__profit--pos" : "day-pos__profit--neg";
    top.appendChild(el("span", { class: `day-pos__profit ${tone}`, "data-hook": "day-position-profit",
      text: `${settlement.profit_units >= 0 ? "+" : ""}${settlement.profit_units.toFixed(2)}u` }));
  }
  row.appendChild(top);

  const bottom = el("div", { class: "day-pos__bottom" });
  const books = rec.books_at_decision;
  if (typeof rec.value_points === "number") {
    bottom.appendChild(el("span", { class: "day-pos__books",
      text: typeof books === "number" ? `${books} books at decision` : "books at decision not available" }));
    bottom.appendChild(el("span", { class: "day-pos__vp",
      text: `${rec.value_points >= 0 ? "+" : ""}${rec.value_points.toFixed(2)} pts` }));
  } else if (rec.value_points_reason) {
    // The full sentence (why no value comparison exists) is stated once,
    // in dayDetailLegend -- this chip carries only this row's own book
    // count so the reason it's missing stays scannable per row.
    const n = typeof books === "number" ? books : 0;
    bottom.appendChild(el("span", { class: "day-pos__thin", "data-hook": "day-position-thin-board",
      text: `THIN BOARD · ${n} BOOK${n === 1 ? "" : "S"}` }));
  } else {
    bottom.appendChild(el("span", { class: "day-pos__books",
      text: typeof books === "number" ? `${books} books at decision` : "books at decision not available" }));
  }
  row.appendChild(bottom);

  return row;
}

/**
 * Scans every recommendation on the date for the two facts dayDetailLegend
 * needs: which system classes actually appear (so the legend never states
 * a meaning for a class not on this slate) and, if any row's value
 * comparison was suppressed by the book floor, the GENERIC half of that
 * explanation. `value_points_reason` is always
 * "<N> book(s) quoted at decision time; <generic explanation>"
 * (src/report/daily_record.py) -- the generic half after the semicolon is
 * identical on every row regardless of N, so lifting it from whichever row
 * has it first (rather than hardcoding the book floor here) means this
 * client never has to duplicate that policy number.
 */
function collectLegendFacts(games) {
  const classes = new Set();
  let thinBoardSentence = null;
  for (const game of games) {
    for (const rec of game.recommendations || []) {
      if (rec.system_class) classes.add(rec.system_class);
      if (!thinBoardSentence && rec.value_points_reason) {
        const reason = String(rec.value_points_reason);
        const sepIndex = reason.indexOf(";");
        const tail = sepIndex >= 0 ? reason.slice(sepIndex + 1).trim() : reason;
        thinBoardSentence = tail ? `${tail.charAt(0).toUpperCase()}${tail.slice(1)}.` : reason;
      }
    }
  }
  return { classes, thinBoardSentence };
}

const CLASS_LEGEND_ORDER = ["FORWARD_TEST", "MARKET_REFERENCE", "CONTROL"];

/** States each system class's meaning, and (when it applies anywhere on
 * this date) the thin-board explanation, exactly ONCE for the whole page --
 * see dayPositionRow's own comment for why this exists. Returns null when
 * there is nothing to explain (e.g. no games yet), never an empty shell. */
function dayDetailLegend(games) {
  const { classes, thinBoardSentence } = collectLegendFacts(games);
  if (classes.size === 0 && !thinBoardSentence) return null;

  const wrap = el("div", { class: "day-detail__legend panel chamfer", "data-hook": "day-detail-legend" });
  wrap.appendChild(el("div", { class: "day-detail__legend-title", text: "HOW TO READ EVERY POSITION BELOW" }));
  for (const cls of CLASS_LEGEND_ORDER) {
    if (!classes.has(cls)) continue;
    const line = el("p", { class: "day-detail__legend-line" });
    line.appendChild(el("span", {
      class: `badge chamfer chamfer--chip day-detail__legend-chip mx-pos__class--${cls.toLowerCase()}`,
      text: CLASS_CHIP_LABEL[cls] || cls,
    }));
    line.appendChild(document.createTextNode(` ${CLASS_MEANING[cls] || ""}`));
    wrap.appendChild(line);
  }
  if (thinBoardSentence) {
    wrap.appendChild(el("p", { class: "day-detail__legend-line day-detail__legend-line--thin",
      "data-hook": "day-detail-thin-board-note",
      text: `THIN BOARD · ${thinBoardSentence}` }));
  }
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
    for (const rec of recs) list.appendChild(dayPositionRow(rec, game));
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
  const legend = dayDetailLegend(games);
  if (legend) screen.appendChild(legend);

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
