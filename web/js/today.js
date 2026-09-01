/**
 * GAMEDAY (#/today) -- the Today screen, composed from the frozen
 * "Gameday desktop" and "Gameday 390px" artboards in
 * design/linehound-v1/LINEHOUND Gameday.dc.html:
 *
 *   1. TONIGHT'S FEATURE hero  -- team-seam split, both wordmarks
 *   2. the price bug           -- best available price, consensus, age
 *   3. TONIGHT'S SLATE         -- the remaining games as an angled rail
 *   4. WHAT CHANGED            -- lead event + the rest of the stream
 *   5. BET CHECK entry band
 *   6. the closing band and the footer (footer mounted by main.js)
 *
 * WHERE THE DATA COMES FROM
 * -------------------------------------------------------------------
 * GET /today            slate notes + the per-game dossier (opaque; only
 *                       read defensively for records/probables)
 * GET /games/{date}     the contract-pinned identity rows -- team, venue,
 *                       first pitch, verdict, board summary
 * GET /odds/{date}      the market board: best price per side, the
 *                       market-implied consensus, staleness
 * GET /changed/{date}   the What Changed stream
 *
 * FEATURE SELECTION -- DETERMINISTIC, CHRONOLOGICAL, NOT A PICK
 * -------------------------------------------------------------------
 * The feature is THE EARLIEST NOT-YET-STARTED GAME THAT HAS A PRICED
 * BOARD. It is not the best price, not the biggest move, not the most
 * "interesting" game -- ordering by first pitch is the one rule that can
 * never be read as a recommendation, which matters because Ranker Engine
 * 2 is gated and this product never says bet it. If nothing has started
 * yet and nothing is priced, the earliest game is featured anyway and
 * the price bug states that plainly instead of showing a figure.
 *
 * THE RESERVED COLOR RULE
 * -------------------------------------------------------------------
 * Hot red appears in exactly two places on this screen and they are in
 * different regions: the price bug (a real, checkable better price) and
 * the closing band's primary action. No slate tile carries a money flag
 * unless a side genuinely beats the market-implied consensus -- "no
 * best-available flag when nothing beats consensus; the pill is absent,
 * not greyed" (handoff section 10).
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading, notYetAvailable,
  formatAmerican, formatAge, formatEasternClock, formatEasternTime,
  formatBook } from "./dom.js";
import { renderStaleness } from "./meta.js";
import { seamGradient, teamColors } from "./teamcolors.js";
import { slateTile } from "./tiles.js";
import { setShellStatusFromStaleness } from "./shell.js";
import { armEntrances, armParallax } from "./motion.js";

/* ---------------------------------------------------------------------
 * Reading the payloads
 * ------------------------------------------------------------------- */

/** /today's `dossier` is documented opaque (docs/API_CONTRACTS.md), but
 * its `game` sub-object is where the probable starters live and its
 * `sections.teams` is where the win-loss records live -- there is no
 * other source for either. Read defensively: a reshape must degrade to
 * "omit the line" (never fabricate one), not throw. */
function dossierOf(entry) {
  const dossier = entry && typeof entry.dossier === "object" ? entry.dossier : null;
  const game = dossier && typeof dossier.game === "object" ? dossier.game : null;
  const sections = dossier && typeof dossier.sections === "object" ? dossier.sections : {};
  const teams = sections && typeof sections.teams === "object" ? sections.teams : null;
  return { game, teams };
}

function recordOf(teams, sideKey) {
  if (!teams) return null;
  const wins = teams[`${sideKey}_wins`];
  const losses = teams[`${sideKey}_losses`];
  if (typeof wins !== "number" || typeof losses !== "number") return null;
  return `${wins}-${losses}`;
}

/** The h2h market block for one game_id out of GET /odds/{date}. */
function marketIndex(oddsPayload) {
  const index = new Map();
  for (const game of (oddsPayload && oddsPayload.games) || []) {
    const h2h = game.markets && game.markets.h2h ? game.markets.h2h : null;
    if (h2h) index.set(game.game_id, h2h);
  }
  return index;
}

/** Best price on one side, or null. */
function bestOn(h2h, side) {
  const best = h2h && h2h.best ? h2h.best[side] : null;
  return best && typeof best.price === "number" ? best : null;
}

/**
 * PRICE ADVANTAGE, MATHEMATICALLY VERIFIABLE OR ABSENT.
 *
 * "N.N PTS BETTER" is the difference between the best available price
 * and the market-implied consensus, in points of implied share -- both
 * numbers come straight off GET /odds/{date} and a reader can check both
 * at the books inside a minute. This is line-shopping value: a better
 * execution price, never expected value and never a prediction.
 *
 * Returns null unless the best price genuinely implies a SMALLER share
 * than consensus (i.e. it pays better). No advantage, no pill -- absent,
 * never greyed, never manufactured.
 */
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

/** The share an American price implies, vig included. Plain arithmetic
 * on the price the API supplied -- the same conversion the odds payload
 * documents for `implied_price`, done in the other direction. */
function impliedShare(american) {
  const n = Number(american);
  if (!Number.isFinite(n) || n === 0) return null;
  return n > 0 ? 100 / (n + 100) : -n / (-n + 100);
}

/* ---------------------------------------------------------------------
 * Hero
 * ------------------------------------------------------------------- */

function heroSide(abbr, { record, probable, home }) {
  const side = el("div", { class: `hero__side${home ? " hero__side--home" : ""}` });
  side.appendChild(el("div", { class: "hero__wordmark", "data-hook": "hero-team", text: abbr }));
  const colors = teamColors(abbr);
  // Team color is identity only -- the rule under the wordmark is drawn
  // only for a club this client actually knows the palette of.
  if (colors.known) side.appendChild(el("div", { class: "hero__rule" }));
  // Records and probables appear only when the payload carried them.
  // An absent starter line is omitted; it is never filled with "TBD".
  if (record || probable) {
    const line = el("div", { class: "hero__line" });
    const parts = home
      ? [probable ? el("span", { class: "hero__probable", text: probable }) : null,
         record ? el("span", { class: "hero__record", text: record }) : null]
      : [record ? el("span", { class: "hero__record", text: record }) : null,
         probable ? el("span", { class: "hero__probable", text: probable }) : null];
    for (const part of parts) if (part) line.appendChild(part);
    side.appendChild(line);
  }
  return side;
}

function priceBug(feature, h2h) {
  const bug = el("div", { class: "pricebug chamfer", "data-hook": "price-bug", "data-price": "" });
  bug.appendChild(el("span", { class: "tex-scanline" }));
  bug.appendChild(el("span", { class: "pricebug__sheen" }));

  const best = bestOn(h2h, "away");
  const consensus = h2h && h2h.consensus ? h2h.consensus.away : null;
  const staleness = h2h && h2h.staleness ? h2h.staleness : null;
  const books = h2h && h2h.consensus && typeof h2h.consensus.books === "number"
    ? h2h.consensus.books
    : (h2h && Array.isArray(h2h.board) ? h2h.board.length : null);

  if (!best) {
    // No price worth showing is a sentence, never a zero.
    bug.appendChild(el("p", { class: "pricebug__none", "data-hook": "price-bug-empty",
      text: h2h && h2h.reason
        ? h2h.reason
        : "No book has posted a price on this game yet." }));
    return { node: bug, advantage: null, books, staleness };
  }

  const head = el("div", { class: "pricebug__head" });
  head.appendChild(el("span", { class: "pricebug__dot" }));
  head.appendChild(el("span", { class: "pricebug__label",
    text: `${feature.away_team} MONEYLINE · BEST OF ${books || "?"} BOOKS · ${formatBook(best.books && best.books[0]) || ""}`.trim() }));
  const age = formatAge(staleness && staleness.age_seconds);
  if (age) {
    head.appendChild(el("span", { class: "pricebug__divider" }));
    head.appendChild(el("span", { class: "pricebug__age", text: `UPDATED ${age}` }));
  }
  bug.appendChild(head);

  const figures = el("div", { class: "pricebug__figures" });
  figures.appendChild(el("span", { class: "pricebug__price", "data-hook": "best-price",
    "data-beat": "", text: formatAmerican(best.price) }));
  if (consensus && typeof consensus.implied_price === "number") {
    const aside = el("div", { class: "pricebug__aside" });
    aside.appendChild(el("div", { class: "pricebug__was", "data-hook": "consensus-price",
      text: formatAmerican(consensus.implied_price) }));
    aside.appendChild(el("div", { class: "pricebug__was-label",
      text: `${books || ""}-BOOK MARKET-IMPLIED CONSENSUS`.replace(/^-/, "") }));
    figures.appendChild(aside);
  }
  bug.appendChild(figures);

  return { node: bug, advantage: pointsBetter(h2h, "away"), books, staleness, best };
}

function heroFor(feature, entry, h2h) {
  const { game, teams } = dossierOf(entry);
  const hero = el("section", { class: "hero", "data-hook": "gameday-hero", "data-hero": "" });
  hero.setAttribute("style",
    `--team-a:${seamGradient(feature.away_team, 148)};--team-b:${seamGradient(feature.home_team, 206)};`
    + `--rule-a:${teamColors(feature.away_team).accent};--rule-b:${teamColors(feature.home_team).accent}`);

  hero.appendChild(el("div", { class: "hero__half hero__half--a", "data-parallax": ".08" }));
  hero.appendChild(el("div", { class: "hero__half hero__half--b", "data-parallax": ".08" }));
  hero.appendChild(el("div", { class: "tex-scanline" }));
  hero.appendChild(el("div", { class: "tex-carbon" }));
  hero.appendChild(el("div", { class: "hero__wash" }));
  hero.appendChild(el("div", { class: "hero__seam" }));
  const sweep = el("div", { class: "hero__sweep" });
  sweep.appendChild(el("i"));
  hero.appendChild(sweep);

  const first = formatEasternTime(feature.first_pitch_utc);
  const eyebrow = el("div", { class: "hero__eyebrow", "data-rise": "", "data-delay": "60" });
  eyebrow.appendChild(el("span", { class: "hero__tick" }));
  eyebrow.appendChild(el("span", { class: "hero__kicker", text: "PREGAME · TONIGHT'S FEATURE" }));
  eyebrow.appendChild(el("span", { class: "hero__spacer" }));
  if (feature.venue) {
    eyebrow.appendChild(el("span", { class: "hero__venue", text: feature.venue.toUpperCase() }));
  }
  // At 390px the venue is dropped and the first pitch takes the right of
  // the eyebrow instead, exactly as the mobile artboard shows.
  if (first) {
    eyebrow.appendChild(el("span", { class: "hero__venue hero__venue--time", text: first }));
  }
  eyebrow.appendChild(el("span", { class: "hero__tick hero__tick--right" }));
  hero.appendChild(eyebrow);

  const matchup = el("div", { class: "hero__matchup", "data-rise": "", "data-delay": "180" });
  matchup.appendChild(heroSide(feature.away_team, {
    record: recordOf(teams, "away"),
    probable: game && game.away_probable ? String(game.away_probable).toUpperCase() : null,
    home: false,
  }));
  const vs = el("div", { class: "hero__vs" });
  vs.appendChild(el("span", { class: "hero__vs-mark chamfer chamfer--badge", text: "VS" }));
  if (first) vs.appendChild(el("span", { class: "hero__vs-time", text: first }));
  matchup.appendChild(vs);
  matchup.appendChild(heroSide(feature.home_team, {
    record: recordOf(teams, "home"),
    probable: game && game.home_probable ? String(game.home_probable).toUpperCase() : null,
    home: true,
  }));
  hero.appendChild(matchup);

  hero.appendChild(el("div", { class: "hero__gap" }));
  hero.appendChild(el("div", { class: "hero__scrim" }));

  const foot = el("div", { class: "hero__foot" });
  const bug = priceBug(feature, h2h);
  foot.appendChild(bug.node);

  if (bug.advantage !== null) {
    const col = el("div", { class: "hero__pill-col", "data-rise": "", "data-delay": "520" });
    col.appendChild(el("span", { class: "advantage-pill chamfer chamfer--badge",
      "data-hook": "advantage-pill", text: `${bug.advantage.toFixed(1)} PTS BETTER` }));
    col.appendChild(el("div", { class: "hero__move",
      text: "BEST AVAILABLE VS MARKET-IMPLIED CONSENSUS" }));
    foot.appendChild(col);
  }

  foot.appendChild(el("div", { class: "hero__foot-spacer" }));

  const actions = el("div", { class: "hero__actions", "data-rise": "", "data-delay": "620" });
  actions.appendChild(el("a", {
    class: "btn btn--secondary chamfer chamfer--btn",
    "data-hook": "compare-books",
    href: `#/game/${encodeURIComponent(feature.date)}/${encodeURIComponent(feature.away_team)}/${encodeURIComponent(feature.home_team)}`,
    text: bug.books ? `COMPARE ${bug.books}` : "OPEN THIS GAME",
  }));
  foot.appendChild(actions);
  hero.appendChild(foot);

  return { node: hero, staleness: bug.staleness, books: bug.books };
}

/** Empty slate: the hero geometry and the seam stay, the price bug is
 * replaced by a plain-language statement, and the work is quantified so
 * absence reads as diligence. Never a row of zeros. */
function emptyHero(date, checkedGames) {
  const hero = el("section", { class: "hero", "data-hook": "gameday-hero-empty", "data-hero": "" });
  hero.setAttribute("style", `--team-a:${seamGradient(null, 148)};--team-b:${seamGradient(null, 206)}`);
  hero.appendChild(el("div", { class: "hero__half hero__half--a" }));
  hero.appendChild(el("div", { class: "hero__half hero__half--b" }));
  hero.appendChild(el("div", { class: "tex-scanline" }));
  hero.appendChild(el("div", { class: "tex-carbon" }));
  hero.appendChild(el("div", { class: "hero__wash" }));
  hero.appendChild(el("div", { class: "hero__seam" }));
  hero.appendChild(el("div", { class: "hero__scrim" }));

  const eyebrow = el("div", { class: "hero__eyebrow", "data-rise": "" });
  eyebrow.appendChild(el("span", { class: "hero__tick" }));
  eyebrow.appendChild(el("span", { class: "hero__kicker", text: `PREGAME · ${date || "TONIGHT"}` }));
  hero.appendChild(eyebrow);
  hero.appendChild(el("div", { class: "hero__gap" }));

  const foot = el("div", { class: "hero__foot" });
  const body = el("div", { class: "noplay", "data-rise": "", "data-delay": "180" });
  body.appendChild(el("p", { class: "noplay__eyebrow", text: "NOTHING ON THE BOARD" }));
  body.appendChild(el("p", { class: "noplay__title", text: "No games to show tonight." }));
  body.appendChild(el("p", { class: "noplay__body",
    text: "There is no slate for this date, so there is nothing to price and "
        + "nothing to compare. We will have a board as soon as one exists." }));
  if (typeof checkedGames === "number") {
    body.appendChild(el("p", { class: "noplay__meta", text: `${checkedGames} GAMES CHECKED` }));
  }
  foot.appendChild(body);
  hero.appendChild(foot);
  return hero;
}

/* ---------------------------------------------------------------------
 * Sections
 * ------------------------------------------------------------------- */

function sectionHead(label, meta, { live = false, dot = false } = {}) {
  const head = el("div", { class: "sechead" });
  if (dot) head.appendChild(el("span", { class: "live-dot sechead__dot" }));
  head.appendChild(el("span", { class: `sechead__label${live ? " sechead__label--live" : ""}`, text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

function renderSlate(rows, markets, featureId, changedIds) {
  const section = el("section", { class: "slate", "data-hook": "tonights-slate" });
  section.appendChild(sectionHead("TONIGHT'S SLATE",
    `${rows.length} GAME${rows.length === 1 ? "" : "S"} · ALL TIMES ET`));
  const rail = el("div", { class: "slate__rail", "data-rail": "" });
  let i = 0;
  for (const row of rows) {
    const h2h = markets.get(row.game_id) || null;
    const away = bestOn(h2h, "away");
    const home = bestOn(h2h, "home");
    // Flags carry their designed meanings only: cyan for "something
    // changed on this game", white for the (chronological) feature.
    // Money is reserved for a price advantage and is not used here.
    let flag = null;
    if (row.game_id === featureId) flag = { text: "FEATURE", kind: "neutral" };
    else if (changedIds.has(row.game_id)) flag = { text: "CHANGED", kind: "live" };
    rail.appendChild(slateTile(row, {
      awayPrice: away ? away.price : null,
      homePrice: home ? home.price : null,
      flag,
      feature: row.game_id === featureId,
      delay: i * 90,
    }));
    i += 1;
  }
  section.appendChild(rail);
  return section;
}

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
    // A quiet slate still reports how many games were checked -- the API
    // sends its own notes for exactly this case; they are rendered
    // verbatim rather than replaced with client-composed filler.
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
  // The artboard draws a line-movement chart here. No endpoint in this
  // API returns a price series, so the canonical NOT YET AVAILABLE panel
  // occupies the chart's place rather than a drawn line standing in for
  // data nobody captured (handoff section 10) -- and rather than the
  // block quietly shrinking, which would hide the gap.
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

function renderCloser(date, gameCount, bookCount) {
  const closer = el("section", { class: "closer", "data-hook": "closing-band", "data-rise": "" });
  closer.appendChild(el("span", { class: "closer__wash" }));
  closer.appendChild(el("span", { class: "tex-carbon" }));
  closer.appendChild(el("span", { class: "tex-scanline" }));
  const row = el("div", { class: "closer__row" });
  const copy = el("div", { class: "closer__copy" });
  const counts = [
    `${gameCount} GAME${gameCount === 1 ? "" : "S"}`,
    bookCount ? `${bookCount} BOOKS SCANNED` : null,
  ].filter(Boolean).join(" · ");
  copy.appendChild(el("p", { class: "closer__eyebrow", text: counts }));
  const headline = el("p", { class: "closer__headline" });
  headline.appendChild(document.createTextNode("DON'T BET THE"));
  headline.appendChild(el("br"));
  headline.appendChild(document.createTextNode("WRONG NUMBER."));
  copy.appendChild(headline);
  copy.appendChild(el("p", { class: "closer__sub", text: "Every book. Every hour. Never off the scent." }));
  copy.appendChild(el("p", { class: "closer__meta", text: "NO PICKS · NO PROBABILITIES · ALL TIMES ET" }));
  row.appendChild(copy);

  const actions = el("div", { class: "closer__actions" });
  actions.appendChild(el("a", { class: "btn btn--primary btn--lg chamfer chamfer--btn",
    href: `#/odds/${encodeURIComponent(date || "")}`,
    "data-hook": "see-best-prices", text: "SEE TONIGHT'S BEST PRICES" }));
  actions.appendChild(el("a", { class: "btn btn--ghost btn--lg chamfer chamfer--btn",
    href: "landing.html", text: "HOW IT WORKS" }));
  row.appendChild(actions);
  closer.appendChild(row);
  return closer;
}

/* ---------------------------------------------------------------------
 * View
 * ------------------------------------------------------------------- */

export async function renderToday(container) {
  clear(container);
  const host = el("div", { class: "screen", "data-view": "today" });
  container.appendChild(host);
  const loading = renderLoading("LOADING TONIGHT'S BOARD");
  const loadingWrap = el("div", { class: "screen-state" }, [loading]);
  host.appendChild(loadingWrap);

  let today;
  try {
    today = await apiGet("/today");
  } catch (err) {
    renderError(loadingWrap, err);
    return;
  }
  const date = today.date;

  // The identity rows, the board and the change stream are three separate
  // reads; a failure in any one of them must not blank the screen (handoff
  // section 10: "never suppress a whole screen for one missing feed").
  const [slate, odds, changed] = await Promise.all([
    apiGet(`/games/${encodeURIComponent(date)}`).catch(() => null),
    apiGet(`/odds/${encodeURIComponent(date)}`).catch(() => null),
    apiGet(`/changed/${encodeURIComponent(date)}`).catch(() => null),
  ]);
  loadingWrap.remove();

  const rows = (slate && slate.games) || [];
  const markets = marketIndex(odds);
  const changedIds = new Set(((changed && changed.items) || []).map((i) => i.game_id));

  // --- feature selection: earliest not-yet-started game with a priced
  //     board. Chronological, deterministic, never "best" anything.
  const now = Date.now();
  const chronological = rows.slice().sort((a, b) => {
    const at = Date.parse(a.first_pitch_utc || "") || 0;
    const bt = Date.parse(b.first_pitch_utc || "") || 0;
    return at - bt;
  });
  const priced = (row) => {
    const h2h = markets.get(row.game_id);
    return !!(h2h && h2h.board_available && bestOn(h2h, "away"));
  };
  const upcoming = chronological.filter((r) => (Date.parse(r.first_pitch_utc || "") || 0) > now);
  const feature = upcoming.find(priced) || chronological.find(priced)
    || upcoming[0] || chronological[0] || null;

  if (!feature) {
    host.appendChild(emptyHero(date, slate ? slate.checked_games : null));
    host.appendChild(renderWhatChanged(changed));
    host.appendChild(renderCheckBand(date));
    host.appendChild(renderCloser(date, 0, null));
    armEntrances(host);
    return;
  }

  const featureEntry = (today.games || []).find((entry) => {
    const { game } = dossierOf(entry);
    return game && game.away_team === feature.away_team && game.home_team === feature.home_team;
  }) || null;

  const featureMarket = markets.get(feature.game_id) || null;
  const hero = heroFor(feature, featureEntry, featureMarket);
  host.appendChild(hero.node);
  setShellStatusFromStaleness(hero.staleness);

  // Freshness rides along when the API had to serve cached data. It is
  // surfaced, never swallowed -- but only as a sentence, and only when
  // the payload itself says the data is stale. A five-row dump of
  // machine fields is not a customer surface; the full block stays
  // reachable in the board-freshness disclosure at the foot of the page.
  if (today.freshness && today.freshness.stale) {
    const banner = el("p", { class: "freshness-banner gutter", "data-hook": "today-freshness",
      text: today.freshness.stale_reason
        ? `Serving cached prices: ${today.freshness.stale_reason}`
        : "Serving cached prices while the board catches up." });
    host.appendChild(banner);
  }

  host.appendChild(renderSlate(chronological, markets, feature.game_id, changedIds));

  // Slate notes from the API, verbatim -- this is where "no play on the
  // whole slate, and that is the normal case" reaches the reader.
  const notes = (today.notes || []);
  if (notes.length) {
    const noteBlock = el("section", { class: "gutter slate-note", "data-hook": "today-notes" });
    const panel = el("div", { class: "gv-panel chamfer" });
    panel.appendChild(el("h2", { class: "gv-panel__title gv-panel__title--mute",
      text: "WHERE THE SLATE STANDS" }));
    for (const note of notes) {
      panel.appendChild(el("p", { class: "gv-panel__body", text: note }));
    }
    noteBlock.appendChild(panel);
    host.appendChild(noteBlock);
  }

  host.appendChild(renderWhatChanged(changed));
  host.appendChild(renderCheckBand(date));

  // The raw board-freshness fields, verbatim and unlabelled by this
  // client -- reachable, but folded away: the top strip and the price
  // bug already carry the same age in reading language.
  const freshness = el("section", { class: "gutter", "data-hook": "board-freshness" });
  const disclosure = el("details", { class: "sitefoot__disclosure" });
  disclosure.appendChild(el("summary", { text: "Board freshness detail" }));
  const body = el("div", { class: "sitefoot__full chamfer" });
  body.appendChild(renderStaleness(hero.staleness));
  disclosure.appendChild(body);
  freshness.appendChild(disclosure);
  host.appendChild(freshness);

  const bookCount = (() => {
    const books = new Set();
    for (const h2h of markets.values()) {
      for (const quote of (h2h && h2h.board) || []) if (quote.book) books.add(quote.book);
    }
    return books.size || null;
  })();
  host.appendChild(renderCloser(date, chronological.length, bookCount));

  const motionNote = el("div", { class: "motion-note chamfer" });
  motionNote.appendChild(el("span", { class: "motion-note__label", text: "REDUCED MOTION" }));
  motionNote.appendChild(el("span", { class: "motion-note__body",
    text: "prefers-reduced-motion disables every sweep, parallax, stagger and beat. "
        + "Content renders in its final state; nothing is hidden." }));
  host.appendChild(motionNote);

  armEntrances(host);
  armParallax(host);
}
