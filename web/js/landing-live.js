/**
 * Live hero for web/landing.html -- replaces the frozen Aug 28 sample
 * matchup (Pirates/Skenes vs Brewers/Peralta) with TONIGHT'S REAL SLATE,
 * fetched from the same public, unauthenticated surface the rest of the
 * product reads (GET /today, GET /opportunities -- api/app.py's
 * PUBLIC_DEMO gate empties `_authed_paid` for both).
 *
 * WHY THIS EXISTS (P0, owner-flagged)
 * -------------------------------------------------------------------
 * The hero used to say "Tonight · 15 games · 11 books scanned" over a
 * hardcoded August 28 matchup next to a "Sample slate · demo data"
 * badge. The word "Tonight" contradicted the badge -- a visitor's first
 * impression was stale data presented as current. The owner's rule: "no
 * normal user path may show old sample/demo games as if current." This
 * module either replaces every hero field with real, freshly-fetched
 * values, or -- on any failure -- rewrites the scanner line to plainly
 * say this is a sample and the live feed is unavailable, and keeps the
 * sample badge showing. It never lets "Tonight" sit next to games from
 * another day.
 *
 * MATCHUP CHOICE
 * -------------------------------------------------------------------
 * The top row of GET /opportunities (the ranker's own #1 pick) when one
 * exists -- never a hand-picked "best looking" game. Falls back to the
 * first game of GET /today's slate when /opportunities has no rows
 * (e.g. nothing priced yet). The featured game's probable starters and
 * full multi-book board are read from /today by matching team
 * abbreviations, since the /opportunities row itself does not carry
 * starter names.
 *
 * RECORDS (F-2 KNOWN GAP)
 * -------------------------------------------------------------------
 * Team win-loss records are not in either payload. The two
 * hero__team-record spans are hidden outright rather than showing last
 * month's numbers or a fabricated placeholder -- an empty slot beats a
 * wrong number.
 *
 * "EVERYWHERE ELSE" PRICE
 * -------------------------------------------------------------------
 * This is the worst REAL quoted price for the same side across the same
 * multi-book board -- an actual number some actual book quoted at the
 * same capture instant, never price-verdict's derived fair_price. When
 * fewer than two books quote that side, there is nothing honest to
 * compare against, so the comparison line is hidden instead of guessed.
 */

import { apiGet } from "./api.js";
import { formatEasternTime, formatAmerican } from "./dom.js";
import { teamName, bookLabel } from "./labels.js";
import { teamColors } from "./teamcolors.js";
import { beat } from "./motion.js";

const HOOK = (name) => `[data-hook="${name}"]`;

function setText(root, hookName, text) {
  const el = root.querySelector(HOOK(hookName));
  if (el) el.textContent = text;
}

function setHidden(root, hookName, hidden) {
  const el = root.querySelector(HOOK(hookName));
  if (el) el.hidden = hidden;
}

function americanToDecimal(price) {
  const n = Number(price);
  if (!Number.isFinite(n) || n === 0) return null;
  return n > 0 ? 1 + n / 100 : 1 + 100 / Math.abs(n);
}

/** The worst real quote for one side across a multi-book board (see
 * module docstring's "EVERYWHERE ELSE" note). Null unless at least two
 * books quoted this side, so there is a genuine "here vs there" to show. */
function worstRealPrice(quotes, side) {
  const key = side === "home" ? "home_price" : "away_price";
  let worst = null;
  let worstDecimal = Infinity;
  let seen = 0;
  for (const q of quotes || []) {
    const price = q && q[key];
    if (price === null || price === undefined) continue;
    seen += 1;
    const dec = americanToDecimal(price);
    if (dec !== null && dec < worstDecimal) {
      worstDecimal = dec;
      worst = price;
    }
  }
  return seen >= 2 ? worst : null;
}

/** One game's price for one side, straight from /today's own board
 * (used for the today-only fallback path, and to source "everywhere
 * else" for an /opportunities-sourced featured game). Null when this
 * game/side has no priced market -- never a fabricated price. */
function priceForSide(sections, side) {
  const pi = sections && sections.price_improvement;
  const sideData = pi && pi.sides && pi.sides[side];
  if (!sideData || sideData.best_price === null || sideData.best_price === undefined) return null;
  const quotes = (sections.multibook_board && sections.multibook_board.quotes) || [];
  return {
    bestPrice: sideData.best_price,
    bestBook: sideData.best_book,
    books: quotes.length,
    worst: worstRealPrice(quotes, side),
  };
}

/** The featured game's price when it came from the /opportunities top
 * row -- the ranker's own best_price/best_book/books, kept verbatim
 * rather than re-derived, with "everywhere else" filled in from the
 * matching /today board (if the game was found there). */
function priceFromOpportunitiesRow(row, sections) {
  if (!row || row.best_price === null || row.best_price === undefined) return null;
  const quotes = (sections && sections.multibook_board && sections.multibook_board.quotes) || [];
  return {
    bestPrice: row.best_price,
    bestBook: row.best_book,
    books: row.books !== null && row.books !== undefined ? row.books : quotes.length,
    worst: quotes.length ? worstRealPrice(quotes, row.side === "home" ? "home" : "away") : null,
  };
}

function findTodayGame(today, awayAbbr, homeAbbr) {
  const games = (today && today.games) || [];
  return games.find((g) => {
    const game = g && g.dossier && g.dossier.game;
    return game && game.away_team === awayAbbr && game.home_team === homeAbbr;
  }) || null;
}

/** Picks the featured game and its price, honestly (see module
 * docstring's MATCHUP CHOICE section). Returns null when neither payload
 * carries a usable game -- the caller treats that as a failure. */
function resolveFeatured(today, opportunities) {
  const games = (today && today.games) || [];
  const rows = (opportunities && opportunities.rows) || [];

  if (rows.length > 0) {
    const row = rows[0];
    const matched = findTodayGame(today, row.away_team, row.home_team);
    const matchedInfo = matched && matched.dossier && matched.dossier.game;
    const matchedSections = matched && matched.dossier && matched.dossier.sections;
    return {
      awayAbbr: row.away_team,
      homeAbbr: row.home_team,
      firstPitchUtc: row.first_pitch_utc,
      awayProbable: matchedInfo ? matchedInfo.away_probable : null,
      homeProbable: matchedInfo ? matchedInfo.home_probable : null,
      price: priceFromOpportunitiesRow(row, matchedSections),
    };
  }

  const game = games[0];
  const info = game && game.dossier && game.dossier.game;
  const sections = game && game.dossier && game.dossier.sections;
  if (!info || !info.away_team || !info.home_team) return null;
  return {
    awayAbbr: info.away_team,
    homeAbbr: info.home_team,
    firstPitchUtc: info.start_time_utc,
    awayProbable: info.away_probable,
    homeProbable: info.home_probable,
    price: priceForSide(sections, "away") || priceForSide(sections, "home"),
  };
}

/** Failure/empty-slate path: say plainly this is a sample and the live
 * feed is unavailable, keep the sample badge visible, and leave every
 * other hero element exactly as the markup already has it -- the frozen
 * Aug 28 demo matchup stays, but nothing claims it is "Tonight". */
function showSampleFallback(root) {
  setText(root, "hero-scanner-text", "Sample matchup · live feed unavailable");
  setHidden(root, "sample-slate-badge", false);
}

function applyLiveHero(root, { gamesCount, featured }) {
  const { awayAbbr, homeAbbr, firstPitchUtc, awayProbable, homeProbable, price } = featured;

  let scannerText = `Tonight · ${gamesCount} game${gamesCount === 1 ? "" : "s"}`;
  if (price && price.books) scannerText += ` · ${price.books} books scanned`;
  setText(root, "hero-scanner-text", scannerText);
  setHidden(root, "sample-slate-badge", true);

  // The club nickname, not the full name: this hero is set at ~64px and was
  // designed around "Pirates" / "Brewers". "Los Angeles Dodgers" wraps to two
  // lines and breaks the layout. `teamName` falls back to the abbreviation
  // for a club it does not know, which is still short enough to fit.
  setText(root, "hero-away-name", teamName(awayAbbr, "name") || awayAbbr);
  setText(root, "hero-home-name", teamName(homeAbbr, "name") || homeAbbr);

  const awayEl = root.querySelector(HOOK("hero-away-rule"));
  if (awayEl) awayEl.style.background = `linear-gradient(90deg, ${teamColors(awayAbbr).secondary}, transparent)`;
  const homeEl = root.querySelector(HOOK("hero-home-rule"));
  if (homeEl) homeEl.style.background = `linear-gradient(270deg, ${teamColors(homeAbbr).secondary}, transparent)`;

  setText(root, "hero-vs-time", formatEasternTime(firstPitchUtc) || "Time TBD");

  // Records: F-2 known gap, neither payload carries them -- remove
  // rather than show stale or placeholder numbers.
  setHidden(root, "hero-away-record", true);
  setHidden(root, "hero-home-record", true);

  if (awayProbable) {
    setText(root, "hero-away-pitcher", awayProbable);
    setHidden(root, "hero-away-pitcher", false);
  } else {
    setHidden(root, "hero-away-pitcher", true);
  }
  if (homeProbable) {
    setText(root, "hero-home-pitcher", homeProbable);
    setHidden(root, "hero-home-pitcher", false);
  } else {
    setHidden(root, "hero-home-pitcher", true);
  }

  if (price) {
    setHidden(root, "hero-price-block", false);
    setText(root, "hero-price-label",
      `Best of ${price.books || "?"} books · ${bookLabel(price.bestBook) || price.bestBook}`);
    const figureEl = root.querySelector(HOOK("hero-price-figure"));
    if (figureEl) {
      figureEl.textContent = formatAmerican(price.bestPrice);
      beat(figureEl);
    }
    if (price.worst !== null && price.worst !== undefined) {
      setText(root, "hero-price-was", formatAmerican(price.worst));
      setHidden(root, "hero-price-was-wrap", false);
    } else {
      setHidden(root, "hero-price-was-wrap", true);
    }
  } else {
    // No priced market for the featured game -- an empty slot beats a
    // fabricated price.
    setHidden(root, "hero-price-block", true);
  }
}

/**
 * Fetches tonight's real slate and wires it into the hero, or degrades
 * to the honest sample-fallback wording on any failure. Fire-and-forget
 * from landing.js's boot(), the same pattern revealPublicDemoEntry uses:
 * a slow or failed fetch must never block the rest of the page.
 */
export async function mountLiveHero(root = document) {
  let today;
  try {
    today = await apiGet("/today");
  } catch (err) {
    showSampleFallback(root);
    return;
  }
  if (!today || !Array.isArray(today.games) || today.games.length === 0) {
    showSampleFallback(root);
    return;
  }

  let opportunities = null;
  try {
    opportunities = await apiGet("/opportunities");
  } catch (err) {
    // /opportunities is optional here -- /today's first game is still an
    // honest fallback featured matchup.
    opportunities = null;
  }

  const featured = resolveFeatured(today, opportunities);
  if (!featured) {
    showSampleFallback(root);
    return;
  }

  applyLiveHero(root, { gamesCount: today.games.length, featured });
}
