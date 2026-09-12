/**
 * Live hero for web/landing.html -- replaces the frozen Aug 28 sample
 * matchup (Pirates/Skenes vs Brewers/Peralta) with TONIGHT'S REAL CARD,
 * fetched from the same public, unauthenticated surface the rest of the
 * product reads (GET /card, GET /today -- api/app.py's PUBLIC_DEMO gate
 * empties `_authed_paid` for both).
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
 * The card's own first pick (GET /card, `picks[0]`, already in the order
 * the card serves) -- the product, not a price board. It used to be the
 * top row of GET /opportunities, which ranks by price gap against
 * consensus, so the landing hero led with the register the owner retired:
 * "Best of 11 books · Caesars +175, ~~+160~~ Everywhere else". Falls back
 * to the first game of GET /today's slate when there is no card yet. The
 * featured game's probable starters are read from /today by matching
 * team abbreviations.
 *
 * RECORDS (F-2 KNOWN GAP)
 * -------------------------------------------------------------------
 * Team win-loss records are not in either payload. The two
 * hero__team-record spans are hidden outright rather than showing last
 * month's numbers or a fabricated placeholder -- an empty slot beats a
 * wrong number.
 *
 * WHAT THE PRICE NEEDS
 * -------------------------------------------------------------------
 * Likelihood first, then the price -- the owner's order. The label says
 * who and how likely (the market's own number), the figure is the price,
 * and the line under it is the win rate that price needs to break even,
 * beside our own number when the card has one for the moneyline. There
 * is no "everywhere else" comparison: which book was worst is not a
 * thing a reader needs.
 */

import { apiGet } from "./api.js";
import { formatEasternTime, formatAmerican } from "./dom.js";
import { teamName } from "./labels.js";
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

/** The win rate an American price needs to break even, as a whole
 * percentage: -205 needs 67, +118 needs 46. Null for anything that is not
 * a price. Arithmetic on the stated price, not a de-vig -- the same
 * number the card's own break-even sentence uses. */
export function breakevenPct(price) {
  const n = Number(price);
  if (!Number.isFinite(n) || n === 0) return null;
  const p = n < 0 ? Math.abs(n) / (Math.abs(n) + 100) : 100 / (n + 100);
  return Math.round(p * 100);
}

function pct(probability) {
  // `Number(null)` is 0, which is finite -- and "we make it 0%" was on the
  // hero for a pick whose number was simply absent. Absent is not zero.
  if (typeof probability !== "number" || !Number.isFinite(probability)) return null;
  return `${Math.round(probability * 100)}%`;
}

function signedLine(line) {
  const n = Number(line);
  if (!Number.isFinite(n)) return String(line);
  return n > 0 ? `+${n}` : `${n}`;
}

/** The card's first pick as the hero's price block. `market_probability`
 * is the moneyline consensus on every pick. Our own moneyline number is
 * `model_probability` on a moneyline pick and `model_probability_moneyline`
 * on a run-line pick (src/analysis/daily_card.py reads them that way), so
 * both are shown for moneyline picks only and the run-line case takes the
 * moneyline field when it is there. */
function priceFromCardPick(pick) {
  if (!pick || pick.price === null || pick.price === undefined) return null;
  const moneyline = pick.market === "moneyline";
  const model = typeof pick.model_probability_moneyline === "number"
    ? pick.model_probability_moneyline
    : (moneyline ? pick.model_probability : null);
  return {
    price: pick.price,
    teamName: pick.team_name || teamName(pick.team, "name") || pick.team || "",
    books: pick.books,
    market: pick.market,
    line: pick.line,
    marketProbability: moneyline && typeof pick.market_probability === "number"
      ? pick.market_probability : null,
    modelProbability: moneyline && typeof model === "number" ? model : null,
  };
}

/** One game's moneyline for one side, straight from /today's own board
 * (the no-card fallback). Null when this game/side has no priced market
 * -- never a fabricated price. */
function priceForSide(sections, side, abbr) {
  const pi = sections && sections.price_improvement;
  const sideData = pi && pi.sides && pi.sides[side];
  if (!sideData || sideData.best_price === null || sideData.best_price === undefined) return null;
  const quotes = (sections.multibook_board && sections.multibook_board.quotes) || [];
  return {
    price: sideData.best_price,
    teamName: teamName(abbr, "name") || abbr,
    books: quotes.length,
    market: "moneyline",
    line: null,
    marketProbability: typeof sideData.consensus_probability === "number"
      ? sideData.consensus_probability : null,
    modelProbability: null,
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
function resolveFeatured(today, card) {
  const games = (today && today.games) || [];
  const picks = card && Array.isArray(card.picks) ? card.picks : [];
  const pick = picks.find((p) => p && p.away_team && p.home_team) || null;

  if (pick) {
    const matched = findTodayGame(today, pick.away_team, pick.home_team);
    const info = matched && matched.dossier && matched.dossier.game;
    return {
      awayAbbr: pick.away_team,
      homeAbbr: pick.home_team,
      firstPitchUtc: pick.first_pitch_utc || (info && info.start_time_utc) || null,
      awayProbable: info ? info.away_probable : null,
      homeProbable: info ? info.home_probable : null,
      price: priceFromCardPick(pick),
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
    price: priceForSide(sections, "away", info.away_team)
      || priceForSide(sections, "home", info.home_team),
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
  if (price && price.books) scannerText += ` · ${price.books} books quoting`;
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
    // Who, then how likely (the market's own number), then the price.
    const who = price.market === "moneyline" || price.line === null || price.line === undefined
      ? `${price.teamName} to win`
      : `${price.teamName} ${signedLine(price.line)} run line`;
    const market = pct(price.marketProbability);
    setText(root, "hero-price-label", market ? `${who} · the market makes it ${market}` : who);
    const figureEl = root.querySelector(HOOK("hero-price-figure"));
    if (figureEl) {
      figureEl.textContent = formatAmerican(price.price);
      beat(figureEl);
    }
    const needs = breakevenPct(price.price);
    if (needs !== null) {
      const ours = pct(price.modelProbability);
      setText(root, "hero-price-needs",
        `Needs ${needs}% to break even${ours ? ` · we make it ${ours}` : ""}`);
      setHidden(root, "hero-price-needs-wrap", false);
    } else {
      setHidden(root, "hero-price-needs-wrap", true);
    }
  } else {
    // No priced market for the featured game -- an empty slot beats a
    // fabricated price.
    setHidden(root, "hero-price-block", true);
  }
}

/**
 * Fetches tonight's real card and slate and wires them into the hero, or
 * degrades to the honest sample-fallback wording on any failure.
 * Fire-and-forget from landing.js's boot(), the same pattern
 * revealPublicDemoEntry uses: a slow or failed fetch must never block the
 * rest of the page.
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

  let card = null;
  try {
    card = await apiGet("/card");
  } catch (err) {
    // /card is optional here -- /today's first game is still an honest
    // fallback featured matchup.
    card = null;
  }

  const featured = resolveFeatured(today, card);
  if (!featured) {
    showSampleFallback(root);
    return;
  }

  applyLiveHero(root, { gamesCount: today.games.length, featured });
}
