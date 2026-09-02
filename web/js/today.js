/**
 * GAMEDAY V2 (#/today) -- V2-01 (carousel default), its three dedicated
 * verdict-state artboards V2-01a NO_PLAY / V2-01b FLAGGED / V2-01c
 * MARKET_UNAVAILABLE, V2-22 (mobile, same markup at <=899px) and V2-33
 * (the Featured Bet carousel head), composed from
 * design/linehound-v2/'LINEHOUND V2 Full Product.dc.html':
 *   V2-01   lines 1126-1673   V2-01a  lines 1674-1880
 *   V2-01b  lines 1881-1981   V2-01c  lines 1982-2135
 *   V2-22   lines 5435-5568   V2-33   lines 7182-7347
 *
 * PRIORITY ANSWER 1 (design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md):
 * no_play is measured at 93.0% of forward-ledger entries (n=129) -- THE
 * PRIMARY state, not an empty one. This screen designs for it: a
 * confident, two-line verdict sentence with real price context beside
 * it, never an apology. flagged (~2.3%) is the rare exception; it is the
 * only state that blooms. market_unavailable (~4.7%) is an honest,
 * amber absence, never styled as an error.
 *
 * WHAT THIS SCREEN DOES NOT PRINT, AND WHY
 * -------------------------------------------------------------------
 * The artboard's own historical badges ("NO_PLAY . 93.0%", "FLAGGED .
 * 2.3% . OF 129 LEDGER ENTRIES") are sourced from
 * evidence/forward_ledger.jsonl -- a file with no customer endpoint.
 * RECONCILED_CONTRACT_CURRENT_HEAD.md's own V2-01a note says "recompute
 * as the ledger grows, never hardcode the percentage" -- since nothing
 * on GET /today, GET /games/{date} or GET /changed/{date} exposes that
 * ledger, this screen never prints 93.0/2.3/4.7% anywhere. It prints the
 * one fraction it CAN compute honestly: how many of TONIGHT's own games
 * share the featured game's verdict (e.g. "1 of 15 tonight"). The
 * "27 hypotheses pre-registered, zero survivors" line is different: the
 * artboard itself labels it "a static constant, not tonight's count" --
 * that is this product's own closed V1-V5 research record (this
 * session's own instructions confirm the same number), so it is safe to
 * print as a fixed fact, exactly like featuredbet.js's own MIN_BOOKS
 * constant.
 *
 * The artboard's rich matchup-context panel (win-loss record, RS/RA per
 * game, L5/L10, probable starters) reads from the dossier's `teams`
 * section and `game.{away,home}_probable` -- fields that exist only
 * inside GET /today's `dossier`, which docs/API_CONTRACTS.md documents
 * as "not yet a stable per-field contract; treat as opaque today", and
 * that are NOT listed in this artboard's own IMPLEMENTATION_MANIFEST.json
 * fields_used (unlike board_summary.books/age_seconds, which the
 * manifest does list and which really are present --
 * src/analysis/gamepayload.py's `_board_summary`/`_board_staleness`,
 * confirmed by reading the source directly). Given that omission looks
 * deliberate rather than an oversight, this rebuild does NOT reach into
 * the opaque dossier at all (V1's today.js did, defensively) -- the
 * matchup-context panel here shows only contract-safe identity and the
 * de-vigged market-implied consensus. Full team/starter detail is the
 * Game screen's job (GET /game/{date}/{away}/{home}'s `sections.teams`,
 * a documented, stable field on THAT endpoint). Reported as a deliberate
 * deviation.
 *
 * FEATURE SELECTION -- ONE RULE FOR THE WHOLE SCREEN
 * -------------------------------------------------------------------
 * V2-33's own eyebrow states its rule in words: "FEATURED . LARGEST
 * PRICE GAP AGAINST CONSENSUS -- Computed from tonight's boards, a
 * measured gap, not a judgement." This screen uses that ONE rule for
 * both the top hero's verdict state AND the Featured Bet slot, rather
 * than V1's separate "earliest not-yet-started" rule for the hero --
 * running two different "features" on one screen would be confusing,
 * and this rule is already deterministic, real-data-only and carries no
 * favourite bias (it is picked from realised price gaps, not from who
 * is favoured). When no game has a priced board with a genuine gap, the
 * hero falls back to the earliest game chronologically (V1's rule,
 * still non-editorial) and the Featured Bet slot renders its own
 * honest-absence state.
 *
 * V2-33's FEATURED BET CARD -- WHY THIS CALLS POST /betcheck
 * -------------------------------------------------------------------
 * web/js/featuredbet.js's own docstring TODO for this exact call site
 * says the Featured Bet primitive needs "a matched game and a Bet
 * Check-shaped payload for it (e.g. by also calling POST /betcheck for
 * the slate's featured game ... not decided here)". This screen decides
 * it: once the largest-gap game+side is known (a real, deterministic,
 * non-favourite pick -- never "always check the away side"), it POSTs
 * that exact bet (real american_price already on the board) to
 * /betcheck and maps the real response through
 * `mapBetCheckPayloadToStanding`. Every figure the Featured Bet card
 * then shows is server-computed, real analysis -- nothing here invents
 * a probability, a rating or a rank. When no gap exists anywhere on
 * tonight's board, the slot renders featuredbet.js's own honest
 * could-not-check state with a real reason, never a fabricated query.
 *
 * GET /odds/{date} IS NOT ONE OF THIS ARTBOARD FAMILY'S LISTED
 * ENDPOINTS (IMPLEMENTATION_MANIFEST.json lists only /today,
 * /games/{date}, /changed/{date} for V2-01/01a/b/c/22/33) -- fetched
 * anyway, continuing the exact pattern V1's today.js already used, and
 * required by the "largest price gap" rule above (there is no other
 * source for a per-book best price or a de-vigged consensus price to
 * compare it against). Reported as a likely manifest omission.
 *
 * WHAT WAS DELIBERATELY LEFT ALONE
 * -------------------------------------------------------------------
 * WHAT CHANGED and the Bet Check invite band are not part of this
 * artboard family (no V2-01-adjacent artboard redesigns them here) --
 * their V1 structure and CSS (screens.css's existing "WHAT CHANGED" /
 * "BET CHECK ENTRY BAND" sections) are kept verbatim rather than
 * rewritten out of scope. Likewise `web/js/tiles.js`'s shared
 * `slateTile` (also used by games.js's grid) is reused unchanged for
 * the slate rail rather than forked into a V2-only tile.
 */

import { apiGet, apiPost } from "./api.js";
import { el, clear, formatAmerican, formatConsensusShare,
  formatEasternClock, verdictLabel, notYetAvailable } from "./dom.js";
import { renderError, renderLoadingSkeleton, renderEmptySlate,
  renderCaptureUnavailable } from "./states.js";
import { renderFeaturedBet, mapBetCheckPayloadToStanding } from "./featuredbet.js";
import { renderStaleness } from "./meta.js";
import { teamColors } from "./teamcolors.js";
import { teamName } from "./labels.js";
import { slateTile } from "./tiles.js";
import { setShellStatus } from "./shell.js";
import { armEntrances } from "./motion.js";

/* ---------------------------------------------------------------------
 * Reading the payloads -- contract-safe only (see module docstring)
 * ------------------------------------------------------------------- */

function h2hOf(oddsGameEntry) {
  return (oddsGameEntry && oddsGameEntry.markets && oddsGameEntry.markets.h2h) || null;
}

function oddsIndexOf(oddsPayload) {
  const index = new Map();
  for (const entry of (oddsPayload && oddsPayload.games) || []) {
    const h2h = h2hOf(entry);
    if (h2h) index.set(entry.game_id, h2h);
  }
  return index;
}

function bestOn(h2h, side) {
  const best = h2h && h2h.best ? h2h.best[side] : null;
  return best && typeof best.price === "number" ? best : null;
}

/** The share an American price implies, vig included -- plain
 * arithmetic on a price the API supplied, the same conversion
 * oddspayload.py documents for `implied_price`, run the other way. */
function impliedShare(american) {
  const n = Number(american);
  if (!Number.isFinite(n) || n === 0) return null;
  return n > 0 ? 100 / (n + 100) : -n / (-n + 100);
}

/** Points of implied-share advantage the best price carries over the
 * de-vigged consensus, on one side -- line-shopping value, never EV,
 * never a prediction (same math V1's today.js used). Null unless the
 * best price genuinely pays a smaller implied share than consensus. */
function pointsBetter(h2h, side) {
  const best = bestOn(h2h, side);
  const consensus = h2h && h2h.consensus ? h2h.consensus[side] : null;
  if (!best || !consensus || typeof consensus.implied_probability !== "number") return null;
  const bestShare = impliedShare(best.price);
  if (bestShare === null) return null;
  const delta = consensus.implied_probability - bestShare;
  if (!(delta > 0)) return null;
  return delta * 100;
}

/** V2-33's own rule, in code: the game+side with the largest real price
 * gap against consensus, across every game with a priced board tonight.
 * Never a favourite pick -- the side is whichever one the market itself
 * produced the bigger gap on. */
function chooseGapCandidate(rows, oddsIndex) {
  let winner = null;
  for (const row of rows) {
    const h2h = oddsIndex.get(row.game_id);
    if (!h2h || !h2h.board_available) continue;
    for (const side of ["away", "home"]) {
      const gap = pointsBetter(h2h, side);
      if (gap === null) continue;
      if (!winner || gap > winner.gap) {
        winner = { row, side, gap, h2h, best: bestOn(h2h, side) };
      }
    }
  }
  return winner;
}

function chronologicalFallback(rows) {
  const sorted = rows.slice().sort((a, b) => {
    const at = Date.parse(a.first_pitch_utc || "") || 0;
    const bt = Date.parse(b.first_pitch_utc || "") || 0;
    return at - bt;
  });
  return sorted[0] || null;
}

/** "WHAT WE CHECKED TONIGHT" -- every figure computed client-side from
 * board_summary on the rows this screen already received (the artboard's
 * own note: "no slate-wide book or quote total exists on this feed").
 * `books`/`age_seconds` on board_summary are real (gamepayload.py's
 * `_board_summary`) even though docs/API_CONTRACTS.md's table only
 * documents observed_utc/has_board -- IMPLEMENTATION_MANIFEST.json's
 * V2-01 fields_used lists both, confirmed against source. */
function boardAggregates(rows) {
  let boardsReceived = 0;
  let noBoard = 0;
  let deepest = null;
  let thinnest = null;
  let freshest = null;
  for (const row of rows) {
    const bs = row.board_summary || {};
    if (bs.has_board) boardsReceived += 1; else noBoard += 1;
    if (typeof bs.books === "number") {
      deepest = deepest === null ? bs.books : Math.max(deepest, bs.books);
      thinnest = thinnest === null ? bs.books : Math.min(thinnest, bs.books);
    }
    if (bs.observed_utc && (!freshest || Date.parse(bs.observed_utc) > Date.parse(freshest))) {
      freshest = bs.observed_utc;
    }
  }
  return { gamesCount: rows.length, boardsReceived, noBoard, deepest, thinnest, freshest };
}

function et(isoUtc) {
  const clock = formatEasternClock(isoUtc);
  return clock ? `${clock} ET` : null;
}

/** "<1 MIN AGO" .. "N DAY AGO" -- no seconds-level liveness claim
 * (capture cadence is 15-60 min; see odds.js's identical helper). */
function ageNoSeconds(isoUtc) {
  if (!isoUtc) return null;
  const ms = Date.now() - Date.parse(isoUtc);
  if (!Number.isFinite(ms) || ms < 0) return null;
  const minutes = Math.round(ms / 60000);
  if (minutes < 1) return "<1 MIN AGO";
  if (minutes < 90) return `${minutes} MIN AGO`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} HR AGO`;
  return `${Math.round(hours / 24)} DAY AGO`;
}

/* ---------------------------------------------------------------------
 * Small building blocks
 * ------------------------------------------------------------------- */

function teamBadge(abbr) {
  const colors = teamColors(abbr);
  const badge = el("span", { class: "gv2-badge", "aria-hidden": "true", text: abbr || "" });
  badge.style.background = colors.known ? colors.primary : "#232830";
  badge.style.color = colors.known ? colors.accent : "#D5D7DE";
  return badge;
}

function verdictChip(text, tone) {
  return el("span", { class: `gv2-chip gv2-chip--${tone}` }, [
    el("span", { class: "gv2-chip__mark", "aria-hidden": "true" }),
    el("span", { text }),
  ]);
}

function checkedTile(label, value, note) {
  const tile = el("div", { class: "gv2-checked__tile" });
  tile.appendChild(el("div", { class: "gv2-checked__label", text: label }));
  const row = el("div", { class: "gv2-checked__row" });
  row.appendChild(el("span", { class: "gv2-checked__value", text: value === null ? "—" : String(value) }));
  if (note) row.appendChild(el("span", { class: "gv2-checked__note", text: note }));
  tile.appendChild(row);
  return tile;
}

function checkedTonightPanel(aggregates) {
  const panel = el("div", { class: "gv2-checked panel chamfer" });
  panel.appendChild(el("div", { class: "gv2-checked__title", text: "WHAT WE CHECKED TONIGHT" }));
  panel.appendChild(checkedTile("GAMES EXAMINED", aggregates.gamesCount, "games_count"));
  panel.appendChild(checkedTile("BOARDS RECEIVED", aggregates.boardsReceived, "count has_board"));
  panel.appendChild(checkedTile("NO BOARD", aggregates.noBoard, "count !has_board"));
  panel.appendChild(checkedTile("DEEPEST BOARD",
    aggregates.deepest === null ? null : aggregates.deepest, "max board_summary.books"));
  panel.appendChild(checkedTile("THINNEST BOARD",
    aggregates.thinnest === null ? null : aggregates.thinnest, "min board_summary.books"));
  panel.appendChild(el("p", { class: "gv2-checked__footnote",
    text: "Every row above is computed client-side from board_summary on the games this screen "
        + "received. No slate-wide book or quote total exists on this feed." }));
  const research = el("div", { class: "gv2-checked__research" });
  research.appendChild(el("span", { class: "gv2-checked__research-tag", text: "OBSERVATION" }));
  research.appendChild(el("span", { class: "gv2-checked__research-body",
    text: "Max evidence tier reachable today." }));
  panel.appendChild(research);
  const programme = el("div", { class: "gv2-checked__programme" });
  programme.appendChild(el("span", { class: "gv2-checked__programme-tag", text: "RESEARCH PROGRAMME" }));
  // Fixed, closed-record constant -- see module docstring. Never
  // tonight's count, never recomputed from a live field.
  programme.appendChild(el("span", { class: "gv2-checked__programme-body",
    text: "27 hypotheses pre-registered across this product's V1-V5 research record, zero surviving. "
        + "Static constant, not tonight's count." }));
  panel.appendChild(programme);
  return panel;
}

/** A compact, honest price-context panel for one game+side -- best price,
 * the de-vigged consensus beside it, and the real points-better gap when
 * one exists. Used by the no_play hero ("price context always real")
 * and the flagged hero (the price finding itself). */
function priceContextPanel(row, side, h2h, gap) {
  const panel = el("div", { class: "gv2-price panel chamfer" });
  if (!h2h || !h2h.board_available) {
    panel.appendChild(el("div", { class: "gv2-price__title", text: "PRICE CONTEXT" }));
    panel.appendChild(el("p", { class: "gv2-price__empty",
      text: "No priced board for this game yet." }));
    return panel;
  }
  const abbr = side === "home" ? row.home_team : row.away_team;
  const best = bestOn(h2h, side);
  const consensus = h2h.consensus ? h2h.consensus[side] : null;
  const bookCount = Array.isArray(h2h.board) ? h2h.board.length : null;

  panel.appendChild(el("div", { class: "gv2-price__head" }, [
    teamBadge(abbr),
    el("span", { class: "gv2-price__label", text: `${teamName(abbr, "name") || abbr} moneyline` }),
  ]));

  if (!best) {
    panel.appendChild(el("p", { class: "gv2-price__empty", "data-hook": "gameday-price-empty",
      text: "No book has posted a price on this side yet." }));
    return panel;
  }

  const figures = el("div", { class: "gv2-price__figures" });
  figures.appendChild(el("span", { class: "gv2-price__figure", "data-hook": "gameday-best-price",
    text: formatAmerican(best.price) }));
  const aside = el("div", { class: "gv2-price__aside" });
  aside.appendChild(el("span", { class: "gv2-price__books",
    text: `${(best.books || []).join(", ") || "—"}` }));
  if (consensus && typeof consensus.implied_price === "number") {
    aside.appendChild(el("span", { class: "gv2-price__consensus",
      text: `de-vigged consensus ${formatAmerican(consensus.implied_price)}` }));
  }
  figures.appendChild(aside);
  panel.appendChild(figures);

  if (typeof gap === "number") {
    panel.appendChild(el("span", { class: "gv2-price__pill", "data-hook": "gameday-points-better",
      text: `${gap.toFixed(1)} PTS BETTER · best price vs. de-vigged consensus` }));
  }
  panel.appendChild(el("p", { class: "gv2-price__note",
    text: `BEST OF ${bookCount === null ? "—" : bookCount} BOOKS · OBSERVATION` }));
  return panel;
}

function matchupContextPanel(row) {
  const panel = el("div", { class: "gv2-matchup panel chamfer" });
  panel.appendChild(el("div", { class: "gv2-matchup__title", text: "TONIGHT'S MATCHUP CONTEXT" }));
  const head = el("div", { class: "gv2-matchup__head" });
  head.appendChild(teamBadge(row.away_team));
  head.appendChild(el("span", { class: "gv2-matchup__names", text: `${row.away_team} @ ${row.home_team}` }));
  panel.appendChild(head);

  const consensus = row.market_implied_consensus;
  if (consensus && typeof consensus.away_fair === "number") {
    const cols = el("div", { class: "gv2-matchup__consensus" });
    cols.appendChild(el("div", { class: "gv2-matchup__col" }, [
      el("span", { class: "gv2-matchup__col-label", text: row.away_team }),
      el("span", { class: "gv2-matchup__col-value", text: formatConsensusShare(consensus.away_fair) }),
    ]));
    cols.appendChild(el("div", { class: "gv2-matchup__col" }, [
      el("span", { class: "gv2-matchup__col-label", text: row.home_team }),
      el("span", { class: "gv2-matchup__col-value", text: formatConsensusShare(consensus.home_fair) }),
    ]));
    panel.appendChild(cols);
    panel.appendChild(el("p", { class: "gv2-matchup__caption",
      text: "MARKET-IMPLIED CONSENSUS, DE-VIGGED -- a measurement of the board, not a forecast." }));
  } else {
    panel.appendChild(notYetAvailable(
      "No priced market for this game yet, so there is no consensus share to show.", "NO MARKET"));
  }
  if (row.venue) {
    panel.appendChild(el("p", { class: "gv2-matchup__venue", text: row.venue.toUpperCase() }));
  }
  // Team records and probable starters are deliberately not shown here --
  // see the module docstring's "what this screen does not print" note.
  panel.appendChild(el("p", { class: "gv2-matchup__gap-note",
    text: "Team records and probable starters live on the Game screen, not here -- "
        + "this endpoint set does not carry them." }));
  return panel;
}

/* ---------------------------------------------------------------------
 * Hero -- the three verdict states (V2-01a / b / c)
 * ------------------------------------------------------------------- */

function heroShell(tone, extraClass) {
  const hero = el("section", { class: `gv2-hero panel chamfer gv2-hero--${tone}${extraClass ? ` ${extraClass}` : ""}`,
    "data-hook": "gameday-hero", "data-verdict-tone": tone, "data-rise": "" });
  hero.appendChild(el("span", { class: "gv2-hero__tex", "aria-hidden": "true" }));
  return hero;
}

function heroActions(date) {
  const row = el("div", { class: "gv2-hero__actions" });
  row.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn",
    href: `#/betcheck?date=${encodeURIComponent(date || "")}`,
    "data-hook": "gameday-check-own-bet", text: "CHECK A BET OF YOUR OWN" }));
  row.appendChild(el("a", { class: "btn btn--ghost chamfer chamfer--btn",
    href: `#/odds/${encodeURIComponent(date || "")}`,
    "data-hook": "gameday-open-board", text: "OPEN THE FULL BOARD" }));
  row.appendChild(el("a", { class: "btn btn--ghost chamfer chamfer--btn",
    href: "#/mybets", "data-hook": "gameday-saved-bets", text: "SAVED BETS" }));
  return row;
}

/** V2-01a -- NO_PLAY, the confident default (~93% of nights per the
 * forward ledger, though that percentage itself is not printed here --
 * see module docstring). */
function heroNoPlay(row, h2h, aggregates, sameVerdictCount, totalGames) {
  const hero = heroShell("noplay");
  const top = el("div", { class: "gv2-hero__top" });
  top.appendChild(verdictChip("NO DEMONSTRATED EDGE", "noplay"));
  top.appendChild(el("span", { class: "gv2-hero__fraction", "data-hook": "gameday-verdict-fraction",
    text: `${sameVerdictCount} OF ${totalGames} GAMES TONIGHT · SAME VERDICT` }));
  hero.appendChild(top);

  hero.appendChild(el("div", { class: "gv2-hero__headline",
    text: "WE CHECKED THE SLATE. NOTHING CLEARS THE BAR." }));
  hero.appendChild(el("p", { class: "gv2-hero__body",
    text: "That is the honest answer most nights, and it is the answer this product is built to give. "
        + "The market and the matchup below are still real -- we just will not invent a reason to act on "
        + "them." }));
  hero.appendChild(heroActions());

  const grid = el("div", { class: "gv2-hero__grid" });
  grid.appendChild(checkedTonightPanel(aggregates));
  grid.appendChild(matchupContextPanel(row));
  hero.appendChild(grid);

  const still = el("div", { class: "gv2-hero__still" });
  still.appendChild(el("span", { class: "gv2-hero__still-tag", text: "STILL WORTH YOUR TIME" }));
  still.appendChild(el("span", { class: "gv2-hero__still-body",
    text: "The market and the matchup are real whether or not we have a finding." }));
  const fresh = aggregates.freshest ? et(aggregates.freshest) : null;
  if (fresh) {
    still.appendChild(el("span", { class: "gv2-hero__still-time",
      text: `PRICES CAPTURED ${fresh}${ageNoSeconds(aggregates.freshest) ? ` · ${ageNoSeconds(aggregates.freshest)}` : ""}` }));
  }
  hero.appendChild(still);

  hero.appendChild(priceContextPanel(row, "away", h2h, null));
  return hero;
}

/** V2-01b -- FLAGGED, the rare exception (~2.3% per the ledger; the only
 * verdict state that carries the bloom accent). */
function heroFlagged(row, side, h2h, gap, sameVerdictCount, totalGames) {
  const hero = heroShell("flagged", "gv2-hero--bloom");
  const top = el("div", { class: "gv2-hero__top" });
  top.appendChild(verdictChip("FLAGGED", "flagged"));
  top.appendChild(el("span", { class: "gv2-hero__fraction", "data-hook": "gameday-verdict-fraction",
    text: `${sameVerdictCount} OF ${totalGames} TONIGHT` }));
  hero.appendChild(top);

  const away = teamName(row.away_team, "full") || row.away_team;
  const home = teamName(row.home_team, "full") || row.home_team;
  hero.appendChild(el("div", { class: "gv2-hero__headline", text: "ONE GAME CLEARED IT." }));
  hero.appendChild(el("p", { class: "gv2-hero__body",
    text: `Rare enough that this product does not dress it up when it happens. One finding survived `
        + `pre-registration on ${away} at ${home}, and it is a price finding, not a prediction.` }));

  hero.appendChild(priceContextPanel(row, side, h2h, gap));
  hero.appendChild(heroActions());
  return hero;
}

/** V2-01c -- MARKET_UNAVAILABLE, honest absence (~4.7% per the ledger).
 * Amber throughout, never styled as an error. */
function heroMarketUnavailable(row, date, aggregates, sameVerdictCount, totalGames) {
  const hero = heroShell("unavailable");
  const top = el("div", { class: "gv2-hero__top" });
  top.appendChild(verdictChip("MARKET UNAVAILABLE", "unavailable"));
  top.appendChild(el("span", { class: "gv2-hero__fraction", "data-hook": "gameday-verdict-fraction",
    text: `${sameVerdictCount} OF ${totalGames} TONIGHT` }));
  hero.appendChild(top);

  hero.appendChild(el("div", { class: "gv2-hero__headline",
    text: "NO PRICE BOARD RECORDED FOR THIS GAME." }));
  hero.appendChild(el("p", { class: "gv2-hero__body gv2-hero__body--warn",
    text: "Nothing is broken. Either no book posted this game at capture time, or the club name did not "
        + "match this product's map -- and since there is no reason field distinguishing the two, it does "
        + "not guess between them." }));

  const gaps = (row.data_quality && row.data_quality.gaps) || {};
  const reason = gaps.market || null;
  const box = el("div", { class: "gv2-payload panel chamfer" });
  box.appendChild(el("div", { class: "gv2-payload__title", text: "WHAT THE PAYLOAD SAYS" }));
  const bs = row.board_summary || {};
  const field = (key, value) => box.appendChild(el("div", { class: "gv2-payload__row" }, [
    el("span", { class: "gv2-payload__key", text: key }),
    el("span", { class: "gv2-payload__val", text: value }),
  ]));
  field("has_board", String(!!bs.has_board));
  field("books", bs.books === null || bs.books === undefined ? "null" : String(bs.books));
  field("observed_utc", bs.observed_utc == null ? "null" : String(bs.observed_utc));
  field("gaps.market", reason ? reason : "no reason given");
  box.appendChild(el("p", { class: "gv2-payload__note",
    text: "Amber, not red. Absence of a board is not a risk to a bet." }));
  hero.appendChild(box);

  const actions = el("div", { class: "gv2-hero__actions" });
  actions.appendChild(el("a", { class: "btn btn--ghost chamfer chamfer--btn",
    href: `#/games/${encodeURIComponent(date || "")}`,
    "data-hook": "gameday-see-other-games",
    text: `SEE THE OTHER ${Math.max(totalGames - 1, 0)} GAME${totalGames - 1 === 1 ? "" : "S"}` }));
  hero.appendChild(actions);
  hero.appendChild(el("p", { class: "gv2-hero__meta", text: "MATCHUP CONTEXT BELOW IS STILL REAL" }));
  hero.appendChild(matchupContextPanel(row));
  return hero;
}

function renderHero(host, featured, aggregates, rows, date) {
  const verdict = featured.row.verdict;
  const sameVerdictCount = rows.filter((r) => r.verdict === verdict).length;
  const totalGames = rows.length;
  let node;
  if (verdict === "flagged" || verdict === "candidate") {
    node = heroFlagged(featured.row, featured.side || "away", featured.h2h || null,
      typeof featured.gap === "number" ? featured.gap : null, sameVerdictCount, totalGames);
  } else if (verdict === "market_unavailable") {
    node = heroMarketUnavailable(featured.row, date, aggregates, sameVerdictCount, totalGames);
  } else {
    node = heroNoPlay(featured.row, featured.h2h || null, aggregates, sameVerdictCount, totalGames);
  }
  host.appendChild(node);
}

/* ---------------------------------------------------------------------
 * V2-33 -- Featured Bet carousel head
 * ------------------------------------------------------------------- */

async function loadFeaturedStanding(candidate, date, featuredVerdict) {
  if (!candidate || !candidate.best || typeof candidate.best.price !== "number") return null;
  const { row, side, best } = candidate;
  try {
    const payload = await apiPost("/betcheck", {
      date: row.date || date,
      away: row.away_team,
      home: row.home_team,
      side,
      american_price: best.price,
    });
    return mapBetCheckPayloadToStanding(payload, { verdict: featuredVerdict });
  } catch (err) {
    return null;
  }
}

function renderFeaturedSection(host, candidate, totalGames) {
  const section = el("section", { class: "gv2-featured", "data-hook": "gameday-featured-bet", "data-rise": "" });
  const head = el("div", { class: "gv2-featured__head" });
  head.appendChild(el("span", { class: "gv2-featured__tag", text: "FEATURED · LARGEST PRICE GAP AGAINST CONSENSUS" }));
  head.appendChild(el("span", { class: "gv2-featured__sub",
    text: "Computed from tonight's boards -- a measured gap, not a judgement." }));
  if (candidate) {
    head.appendChild(el("span", { class: "gv2-featured__count",
      text: `1 OF ${totalGames} · SWIPE FOR THE REST` }));
  }
  section.appendChild(head);

  const slot = el("div", { class: "gv2-featured__slot", "data-hook": "gameday-featured-bet-slot" });
  section.appendChild(slot);
  host.appendChild(section);
  return slot;
}

/* ---------------------------------------------------------------------
 * Slate rail -- reuses web/js/tiles.js's shared slateTile unchanged
 * ------------------------------------------------------------------- */

function sectionHead(label, meta, { live = false, dot = false } = {}) {
  const head = el("div", { class: "sechead" });
  if (dot) head.appendChild(el("span", { class: "live-dot sechead__dot" }));
  head.appendChild(el("span", { class: `sechead__label${live ? " sechead__label--live" : ""}`, text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

function renderSlateRail(rows, oddsIndex, featuredGameId, changedIds) {
  const section = el("section", { class: "slate", "data-hook": "tonights-slate" });
  section.appendChild(sectionHead("TONIGHT'S SLATE",
    `${rows.length} GAME${rows.length === 1 ? "" : "S"} · ALL TIMES ET`));
  const rail = el("div", { class: "slate__rail", "data-rail": "" });
  let i = 0;
  for (const row of rows) {
    const h2h = oddsIndex.get(row.game_id) || null;
    const away = bestOn(h2h, "away");
    const home = bestOn(h2h, "home");
    let flag = null;
    if (row.game_id === featuredGameId) flag = { text: "FEATURED", kind: "neutral" };
    else if (changedIds.has(row.game_id)) flag = { text: "CHANGED", kind: "live" };
    else flag = { text: verdictLabel(row.verdict) || "", kind: "neutral" };
    rail.appendChild(slateTile(row, {
      awayPrice: away ? away.price : null,
      homePrice: home ? home.price : null,
      flag,
      feature: row.game_id === featuredGameId,
      delay: i * 90,
    }));
    i += 1;
  }
  section.appendChild(rail);
  return section;
}

/* ---------------------------------------------------------------------
 * What Changed and the Bet Check invite band -- kept from V1 verbatim;
 * not part of this artboard family (see module docstring).
 * ------------------------------------------------------------------- */

function changedRow(item) {
  const row = el("article", { class: "changed__row", "data-hook": "changed-row",
    "data-tier": item.tier || "", "data-inadmissible": String(!!item.inadmissible) });
  const meta = el("div", { class: "changed__meta" });
  const seen = formatEasternClock(item.seen_utc);
  if (seen) meta.appendChild(el("span", { class: "changed__time", text: seen }));
  meta.appendChild(el("span", { class: "changed__cat", text: `${item.away_team} @ ${item.home_team}` }));
  if (item.tier) meta.appendChild(el("span", { class: "changed__cat", text: `RELEVANCE ${item.tier}` }));
  row.appendChild(meta);
  row.appendChild(el("p", { class: "changed__row-headline", text: item.headline || "" }));
  return row;
}

function renderWhatChanged(changed) {
  const section = el("section", { class: "changed", "data-hook": "what-changed" });
  const left = el("div");
  const checked = changed && typeof changed.checked_games === "number" ? changed.checked_games : null;
  left.appendChild(sectionHead("WHAT CHANGED",
    checked !== null ? `${checked} GAMES CHECKED` : null, { live: true, dot: true }));

  const items = (changed && changed.items) || [];
  if (items.length === 0) {
    const lead = el("div", { class: "changed__lead", "data-rise": "" });
    lead.appendChild(el("p", { class: "changed__headline", text: "Nothing has moved yet." }));
    lead.appendChild(el("p", { class: "changed__sub",
      text: checked !== null
        ? `${checked} games watched since the last poll. No lineup, starter or market change has come through.`
        : "No lineup, starter or market change has come through." }));
    for (const note of (changed && changed.notes) || []) {
      lead.appendChild(el("p", { class: "changed__sub", text: note }));
    }
    left.appendChild(lead);
    section.appendChild(left);
    return section;
  }

  const [head, ...rest] = items;
  const lead = el("div", { class: "changed__lead", "data-rise": "" });
  const meta = el("div", { class: "changed__meta" });
  const seen = formatEasternClock(head.seen_utc);
  if (seen) meta.appendChild(el("span", { class: "changed__time", text: seen }));
  meta.appendChild(el("span", {
    class: `changed__cat${head.tier === "HIGH" ? " changed__cat--risk" : ""}`,
    text: `${head.away_team} @ ${head.home_team} · RELEVANCE ${head.tier || "UNKNOWN"}`,
  }));
  lead.appendChild(meta);
  lead.appendChild(el("p", { class: "changed__headline", "data-hook": "changed-lead",
    text: head.headline || "" }));
  lead.appendChild(el("p", { class: "changed__sub",
    text: head.inadmissible
      ? "Recorded, but not admissible as evidence."
      : "Recorded as a pre-event observation. It is not a prediction." }));
  lead.appendChild(notYetAvailable(
    "The market's reaction to this change -- the line movement behind it -- is "
    + "not served by this board yet, so no chart is drawn.", "NO SERIES"));
  left.appendChild(lead);
  section.appendChild(left);

  const stream = el("div", { class: "changed__stream" });
  for (const item of rest.slice(0, 3)) stream.appendChild(changedRow(item));
  if (rest.length > 3) {
    stream.appendChild(el("p", { class: "changed__more",
      text: `+ ${rest.length - 3} MORE CHANGES ON THIS SLATE` }));
  }
  section.appendChild(stream);
  return section;
}

function renderCheckBand(date) {
  const band = el("section", { class: "checkband chamfer", "data-hook": "check-band", "data-rise": "" });
  band.appendChild(el("span", { class: "tex-carbon" }));
  band.appendChild(el("span", { class: "tex-scanline" }));
  band.appendChild(el("span", { class: "checkband__glow" }));
  const eyebrow = el("div", { class: "checkband__eyebrow" });
  eyebrow.appendChild(el("span", { class: "checkband__tick" }));
  eyebrow.appendChild(el("span", { class: "checkband__label", text: "BET CHECK" }));
  band.appendChild(eyebrow);

  const row = el("div", { class: "checkband__row" });
  const field = el("a", { class: "checkband__field chamfer",
    href: `#/betcheck?date=${encodeURIComponent(date || "")}` });
  field.appendChild(el("span", { class: "checkband__bullet" }));
  field.appendChild(el("span", { class: "checkband__prompt", text: "Check a bet you are looking at…" }));
  row.appendChild(field);
  row.appendChild(el("a", { class: "btn btn--cyan chamfer chamfer--btn on-live",
    href: `#/betcheck?date=${encodeURIComponent(date || "")}`,
    "data-hook": "go-to-bet-check", text: "CHECK IT" }));
  band.appendChild(row);
  band.appendChild(el("p", { class: "checkband__note",
    text: "We show what supports it, what argues against it, and where the price is better." }));
  return band;
}

/* ---------------------------------------------------------------------
 * View
 * ------------------------------------------------------------------- */

export async function renderToday(container) {
  clear(container);
  const host = el("div", { class: "screen", "data-view": "today" });
  container.appendChild(host);
  const loadingWrap = el("div", { class: "screen-state" },
    [renderLoadingSkeleton({ headline: "LOADING TONIGHT'S BOARD",
      subline: "Pulling the slate, the board and tonight's changes." })]);
  host.appendChild(loadingWrap);

  let today;
  try {
    today = await apiGet("/today");
  } catch (err) {
    renderError(loadingWrap, err);
    return;
  }
  const date = today.date;

  // Three independent reads; a failure in any one must not blank the
  // whole screen (odds.js and V1's today.js follow the same rule).
  const [slate, odds, changed] = await Promise.all([
    apiGet(`/games/${encodeURIComponent(date)}`).catch(() => null),
    apiGet(`/odds/${encodeURIComponent(date)}`).catch(() => null),
    apiGet(`/changed/${encodeURIComponent(date)}`).catch(() => null),
  ]);
  loadingWrap.remove();

  // A failed /games/{date} fetch must never look like an honest empty
  // slate -- those are two different real conditions (V1's own bug
  // class this rebuild avoids: `(slate && slate.games) || []` alone
  // would render "no games to show tonight" on a network failure).
  if (!slate) {
    host.appendChild(renderCaptureUnavailable({
      eyebrow: "SLATE UNREACHABLE",
      headline: "Tonight's slate didn't come back.",
      body: "This is a fetch failure, not an honest empty night -- try reloading.",
      reason: "GET /games/{date} did not respond.",
    }));
    host.appendChild(renderWhatChanged(changed));
    armEntrances(host);
    return;
  }

  const rows = slate.games || [];
  const changedIds = new Set(((changed && changed.items) || []).map((i) => i.game_id));

  if (rows.length === 0) {
    host.appendChild(renderEmptySlate({
      eyebrow: "NOTHING SCHEDULED",
      headline: "No games to show tonight.",
      count: slate.checked_games,
      countField: "checked_games",
      actions: [
        { label: "OPEN THE FULL BOARD", href: `#/odds/${encodeURIComponent(date || "")}` },
        { label: "SAVED BETS", href: "#/mybets" },
      ],
    }));
    host.appendChild(renderWhatChanged(changed));
    armEntrances(host);
    return;
  }

  if (!odds) {
    host.appendChild(renderCaptureUnavailable({
      eyebrow: "PRICE BOARD UNREACHABLE",
      headline: "Prices didn't come back this time.",
      body: "The slate and verdicts below are real -- only the price board failed to load.",
      reason: "GET /odds/{date} did not respond.",
    }));
  }
  const oddsIndex = odds ? oddsIndexOf(odds) : new Map();

  const gapCandidate = chooseGapCandidate(rows, oddsIndex);
  const fallbackRow = chronologicalFallback(rows);
  const featured = gapCandidate || { row: fallbackRow, side: null, gap: null, h2h: null, best: null };
  const aggregates = boardAggregates(rows);

  renderHero(host, featured, aggregates, rows, date);
  setShellStatus(aggregates.freshest ? `PRICES AS OF ${et(aggregates.freshest)}` : null);

  const slot = renderFeaturedSection(host, gapCandidate, rows.length);
  slot.appendChild(el("div", { class: "gv2-featured__loading",
    text: "Checking tonight's largest price gap…" }));
  loadFeaturedStanding(gapCandidate, date, featured.row.verdict).then((standing) => {
    clear(slot);
    if (standing) {
      renderFeaturedBet(slot, standing, {});
    } else {
      renderFeaturedBet(slot, {
        query: { raw: gapCandidate ? `${gapCandidate.row.away_team} @ ${gapCandidate.row.home_team}` : "",
          parsed: false,
          parseError: gapCandidate
            ? "The bet check for tonight's largest price gap did not come back."
            : "No priceable gap against consensus on tonight's board -- there is nothing to feature." },
      }, {});
    }
  });

  host.appendChild(renderSlateRail(rows, oddsIndex, featured.row.game_id, changedIds));

  const notes = today.notes || [];
  if (notes.length) {
    const noteBlock = el("section", { class: "gutter slate-note", "data-hook": "today-notes" });
    const panel = el("div", { class: "gv-panel chamfer" });
    panel.appendChild(el("h2", { class: "gv-panel__title gv-panel__title--mute",
      text: "WHERE THE SLATE STANDS" }));
    for (const note of notes) panel.appendChild(el("p", { class: "gv-panel__body", text: note }));
    noteBlock.appendChild(panel);
    host.appendChild(noteBlock);
  }

  host.appendChild(renderWhatChanged(changed));
  host.appendChild(renderCheckBand(date));

  // The raw board-freshness fields for the featured game, verbatim and
  // unlabelled by this client -- reachable, but folded away, matching
  // V1's own "board freshness detail" disclosure pattern (games.js keeps
  // the same convention on its own screen).
  const featuredStaleness = (featured.h2h && featured.h2h.staleness)
    || featured.row.board_summary || null;
  const freshness = el("section", { class: "gutter", "data-hook": "board-freshness" });
  const disclosure = el("details", { class: "sitefoot__disclosure" });
  disclosure.appendChild(el("summary", { text: "Board freshness detail" }));
  const body = el("div", { class: "sitefoot__full chamfer" });
  body.appendChild(renderStaleness(featuredStaleness));
  disclosure.appendChild(body);
  freshness.appendChild(disclosure);
  host.appendChild(freshness);

  const motionNote = el("div", { class: "motion-note chamfer" });
  motionNote.appendChild(el("span", { class: "motion-note__label", text: "REDUCED MOTION" }));
  motionNote.appendChild(el("span", { class: "motion-note__body",
    text: "prefers-reduced-motion disables every bloom, rise and stagger on this screen. Content renders "
        + "in its final state; nothing is hidden." }));
  host.appendChild(motionNote);

  armEntrances(host);
}
