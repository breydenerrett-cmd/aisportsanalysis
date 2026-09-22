/**
 * App shell wiring: the two nav shells, the top strip, and a minimal hash
 * router that mounts one view module into the outlet at a time.
 *
 * WHY HASH ROUTING, NOT History API PUSHSTATE
 * -------------------------------------------------------------------
 * This is served either via api/web.py's FileResponse router or a bare
 * `python3 -m http.server` (see web/README.md) -- neither rewrites
 * unknown paths back to index.html, so a pushState URL would 404 on
 * reload. `#/betcheck?date=...` needs no server-side rewrite rule at all.
 *
 * REDESIGN, 2026-09-15 (docs/DESIGN_SYSTEM.md section 3) -- every sport is
 * its own section (D6): MLB is live and keeps its sub menu below; NBA and
 * NHL show the one shared coming-soon page (comingsoon.js) instead of a
 * real board, however many routes they carry. #/live stays wired exactly
 * as before -- reachable by a typed URL, linked from nowhere in this
 * file's rendered chrome (D5).
 *
 * NFL AND TENNIS WENT LIVE 2026-09-19 -- both used to be coming-soon
 * sports here too; they now route to their real (kept-on-disk-until-now)
 * views instead. NFL genuinely publishes picks (card.js's `renderCard`,
 * cardrecord.js's `renderCardRecord`, both called with `{sport: "nfl"}`)
 * -- one pick has been published and graded so far, and both views render
 * an explicit sample-size line alongside NFL_NOTICE rather than a win
 * rate or ROI off that one pick. Tennis routes to `tennis.js`'s
 * `renderTennisBoard`, a de-vigged research board that publishes no pick,
 * slip or record, ever -- its own "Research only" notice stays on screen.
 *
 * ROUTES
 * -------------------------------------------------------------------
 *   #/today                                  GAMEDAY (MLB)
 *   #/nfl, #/nfl/today                       NFL GAMEDAY (the card,
 *                                             {sport: "nfl"})
 *   #/nfl/record                             NFL RESULTS (the graded
 *                                             record, {sport: "nfl"} --
 *                                             the live rule only)
 *   #/nfl/record?rule=NFL_CARD_V1            The retired favourites
 *                                             rule's own record, apart
 *                                             from the live rule's
 *   #/tennis, #/tennis/board                  TENNIS BOARD (research only,
 *                                             no picks -- tennis.js)
 *   #/nba, #/nhl                              Coming-soon page (D6, ahead
 *                                             of either sport joining the
 *                                             SPORTS registry live)
 *   #/games[/YYYY-MM-DD]                     GAMES (slate)
 *   #/game/YYYY-MM-DD/AWAY/HOME               GAMES (one game, quick+advanced)
 *   #/betcheck[?date=&away=&home=]           BET CHECK
 *   #/odds[/YYYY-MM-DD]                      ODDS (board)
 *   #/odds/YYYY-MM-DD/AWAY/HOME               ODDS (one game)
 *   #/mybets                                 BETS
 *   #/performance                            RESULTS (PAPER / RESEARCH PERFORMANCE)
 *   #/props[/YYYY-MM-DD]                     PLAYER PROPS (the priced
 *                                             board -- most likely first,
 *                                             never ranked by the gap
 *                                             against the price)
 *   #/day/YYYY-MM-DD                         DAILY RECORD (one day's
 *                                             pregame record, GET /daily/{date})
 *   #/record-card                            THE RECORD (every card ever
 *                                             published, GET /card/record +
 *                                             GET /card/history -- see
 *                                             cardrecord.js. Reachable from
 *                                             THE CARD's own summary and the
 *                                             footer, not the primary nav)
 *   #/gameday, #/matchups, #/results          Aliases for #/today, #/games,
 *                                             #/record-card (ROUTE_ALIASES
 *                                             below), resolved once here.
 *   #/live[?sport=]                          LIVE (internal testing,
 *                                             reachable by URL only)
 *   #/signin                                 SIGN IN (interim -- see signin.js)
 *   #/support                                SUPPORT
 *   #/signup                                 SIGNUP (public CTA target from
 *                                             web/landing.html)
 *   #/signup/complete[?token=...]            SIGNUP COMPLETE
 *   #/billing                                BILLING (402 subscription-
 *                                             expired landing target)
 */

import { el, clear, formatEasternDate, formatEasternClock } from "./dom.js";
import { setPublicDemo, getToken } from "./api.js";
import { setShellStatus, mountSportLevel } from "./shell.js";
import { renderDisclaimerFooter, meta as fetchMeta } from "./meta.js";
import { parseSport, SPORTS, NFL_RETIRED_RULE, MLB_SHADOW_RULE } from "./sport.js";
import { mountNews } from "./news.js";
import { renderComingSoon } from "./comingsoon.js";
import { renderToday } from "./today.js";
import { renderCard } from "./card.js";
import { renderTennisBoard } from "./tennis.js";
import { renderGamesList, renderGameDetail } from "./games.js";
import { renderBetCheck } from "./betcheck.js";
import { renderSignin } from "./signin.js";
import { renderOdds, renderOddsGame } from "./odds.js";
import { renderMyBets } from "./mybets.js";
import { renderSupport } from "./support.js";
import { renderSignup, renderSignupComplete } from "./signup.js";
import { renderBilling } from "./billing.js";
import { renderPerformance } from "./performance.js";
import { renderProps } from "./props.js";
import { renderDayDetail } from "./dayrecap.js";
import { renderCardRecord } from "./cardrecord.js";
import { renderLive } from "./live.js";
import { maybeGotcha } from "./gotcha.js";

// MLB's sub menu (docs/DESIGN_SYSTEM.md section 3, D7): 01 GAMEDAY, 02
// MATCHUPS, 03 PROPS, 04 RESULTS, 05 BETS. Hash immediately before label,
// in this order, is required by tests/test_whose_record_is_it.py's regex
// match on the RESULTS entry. BETS is hidden unless the visitor is BOTH
// signed in (an invite token is stored, see getToken() below) AND the
// server is not the public demo (D7) -- never shown as a route that only
// ever answers 401.
const NAV_ITEMS = [
  { hash: "#/today", label: "GAMEDAY", sub: "Today's picks" },
  { hash: "#/games", label: "MATCHUPS", sub: "Every game, in depth" },
  { hash: "#/props", label: "PROPS", sub: "Priced player props" },
  { hash: "#/record-card", label: "RESULTS", sub: "Every pick, graded" },
  { hash: "#/mybets", label: "BETS", sub: "Your saved bets" },
];

// Word aliases for MLB's own routes (docs/DESIGN_SYSTEM.md section 3):
// resolved once, here, inside the router -- never via location.replace and
// never as a second "strip a leading mlb" step (that half is sport.js's
// parseSport). A leading "mlb" segment is stripped by parseSport before
// this table is consulted.
const ROUTE_ALIASES = {
  gameday: "today",
  matchups: "games",
  results: "record-card",
};

// Sports with no real board yet (D6): every route under one of these goes
// to the single shared coming-soon page, whatever sub-route it carries.
// NFL and TENNIS were in this set too until 2026-09-19, when both went
// live and moved to their own dispatch branches below. NBA and NHL are
// matched both here and directly by the route's own first segment further
// down, since parseSport only recognises a sport once it is in
// sport.js's SPORTS registry.
const COMING_SOON_SPORTS = new Set(["nba", "nhl"]);

// GET /meta's public_demo flag, fetched once at boot (see boot() below).
// null until the fetch resolves -- mountNav treats "not known yet" the
// same as "not a public demo" (never hides BETS on a guess).
let publicDemo = false;

/** The rail/tab-bar heading names the live sport (today, always MLB) --
 * read from the registry rather than hardcoded, so a second sport going
 * live needs no edit here. */
function railHeadingLabel() {
  const live = SPORTS.find((entry) => entry.status === "live");
  return live ? live.label : "MLB";
}

/** Which NAV_ITEMS hash, if any, the current MLB route answers to.
 * games/game/odds all read as MATCHUPS; everything not covered here
 * (betcheck, performance, day, account routes) answers to none, which is
 * correct -- those pages are not part of the sub menu (docs/DESIGN_SYSTEM.md
 * section 3). Fixes the pre-sport-parse activeHash bug: this is compared
 * against the sport-STRIPPED route, never the raw "#/nfl/today"-shaped
 * hash NAV_ITEMS' un-prefixed hashes could never match. */
function navHashForRoute(route) {
  if (route === "games" || route === "game" || route === "odds") return "#/games";
  if (route === "record-card") return "#/record-card";
  return "#/" + route;
}

function navItem(item, isActive, withSub) {
  const a = el("a", {
    href: item.hash,
    class: withSub ? "rail__item" : "tabbar__item",
    "data-hook": "nav-link",
    "data-nav-hash": item.hash,
  });
  a.appendChild(el("span", { class: withSub ? "rail__item-label" : "tabbar__item-label", text: item.label }));
  if (withSub) a.appendChild(el("span", { class: "rail__item-sub", text: item.sub }));
  if (isActive) a.setAttribute("aria-current", "page");
  return a;
}

/**
 * `activeHash` is the menu hash the current route answers to: a NAV_ITEMS
 * hash for MLB (navHashForRoute), the sport's own submenu hash for a live
 * NFL/Tennis route, or null while browsing a coming-soon sport (NBA/NHL)
 * -- MLB's menu stays visible there with nothing in it selected, rather
 * than reusing MLB's own routes' highlight by accident. Live NFL and
 * Tennis mount their OWN registry submenu instead (docs/DESIGN_SYSTEM.md
 * section 6, "NFL and Tennis"; tests/test_web_nfl_tennis_truth.py pins
 * it).
 */
function mountNav(rail, tabbar, activeHash, sport = "mlb") {
  clear(rail);
  clear(tabbar);
  // A LIVE non-MLB sport gets its own menu from sport.js's registry
  // (2026-09-20). Before that, NFL and Tennis kept MLB's menu, so the
  // RESULTS link on the NFL page silently opened MLB's record.
  const own = sport !== "mlb"
    ? SPORTS.find((entry) => entry.key === sport && entry.status === "live"
        && entry.submenu && entry.submenu.length)
    : null;
  rail.appendChild(el("div", { class: "rail__heading",
    text: own ? own.label : railHeadingLabel() }));
  const items = el("div", { class: "rail__items" });
  // A public-demo visitor, or one with no invite token at all, has no
  // saved-bets identity -- BETS is hidden rather than shown as a route
  // that will only ever 401 (D7).
  const signedIn = !!getToken();
  const showBets = signedIn && !publicDemo;
  const visibleItems = own ? own.submenu
    : showBets ? NAV_ITEMS : NAV_ITEMS.filter((item) => item.hash !== "#/mybets");
  for (const item of visibleItems) {
    const isActive = activeHash !== null && item.hash === activeHash;
    items.appendChild(navItem(item, isActive, true));
    tabbar.appendChild(navItem(item, isActive, false));
  }
  rail.appendChild(items);
  // Per-sport plan slot (D6): empty until per-sport billing lands, so the
  // rail reserves the space rather than shifting when it does.
  rail.appendChild(el("div", { class: "rail__plan", "data-hook": "sport-plan" }));
}

function setClock() {
  const host = document.querySelector("[data-hook='shell-clock']");
  if (!host) return;
  const now = new Date().toISOString();
  // Local-time rewrite, 2026-09-14: both halves are now in the viewer's
  // own zone (formatEasternDate/formatEasternClock are dom.js aliases for
  // formatLocalDate/formatLocalClock), and the clock already carries its
  // own zone abbreviation, so no more literal " ET" appended here.
  const parts = [formatEasternDate(now), formatEasternClock(now)].filter(Boolean);
  host.textContent = parts.join(" · ");
}

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/today";
  const [pathPart, queryPart] = raw.split("?");
  const segments = pathPart.split("/").filter(Boolean);
  const query = {};
  if (queryPart) {
    for (const pair of queryPart.split("&")) {
      const [key, value] = pair.split("=");
      if (key) query[decodeURIComponent(key)] = decodeURIComponent(value || "");
    }
  }
  return { segments, query };
}

// Re-entrancy guard (2026-09-07). A cold load of /app#/performance on
// staging fired the route four times in half a second -- each entry
// cleared the outlet and painted a fresh loading panel over the previous
// entry's in-flight fetch, so the DAILY RECAP gallery never got to render
// and a visitor opening a Results link saw a spinner forever. Locally,
// where /meta resolves instantly, it dispatched once and worked, which is
// why every hash-switch sweep passed. Whatever fires the duplicates (a
// fragment-carrying redirect, /meta's finally, a hashchange), the rule is
// the same: a second dispatch for the SAME hash while one is in flight is
// noise and is dropped. A different hash still proceeds -- the superseded
// render just writes into a detached tree, harmlessly.
let _inflightHash = null;

async function renderRoute(main) {
  const hash = location.hash || "#/today";
  if (_inflightHash === hash) return;
  _inflightHash = hash;
  try {
    await _renderRouteInner(main);
  } finally {
    if (_inflightHash === hash) _inflightHash = null;
  }
}

async function _renderRouteInner(main) {
  const { segments, query } = parseHash();
  const { sport, segments: sportSegments } = parseSport(segments);
  const [rawRoute, ...rest] = sportSegments;
  const route = ROUTE_ALIASES[rawRoute] || rawRoute;
  const rail = document.querySelector("[data-hook='primary-nav']");
  const tabbar = document.querySelector("[data-hook='primary-nav-mobile']");
  const newsHost = document.querySelector("[data-hook='news-host']");

  // MLB gets NAV_ITEMS; a live NFL/Tennis gets its own registry submenu
  // (mountNav); a coming-soon sport keeps MLB's menu with nothing selected.
  let activeHash = null;
  if (sport === "mlb") activeHash = navHashForRoute(route);
  else if (sport === "nfl") activeHash = route === "record" ? "#/nfl/record" : "#/nfl";
  else if (sport === "tennis") activeHash = "#/tennis";
  else if (sport === "ufc") activeHash = route === "record" ? "#/ufc/record" : "#/ufc";
  mountNav(rail, tabbar, activeHash, sport);
  setShellStatus(null);
  setClock();
  // Runs on every route change, not once at boot -- aria-current and the
  // selected MLB tab must track the active route (docs/DESIGN_SYSTEM.md
  // section 3).
  mountSportLevel(sport);
  if (newsHost) mountNews(newsHost, {});

  clear(main);
  window.scrollTo(0, 0);
  if (route === "billing") {
    await renderBilling(main);
  } else if (sport === "nfl") {
    // NFL went live 2026-09-19: #/nfl and #/nfl/today are the card
    // (mirrors #/today's default-to-gameday fallback -- any route under
    // nfl that is not "record" shows the card, same as MLB's own router
    // falls through to renderToday at the bottom of this chain);
    // #/nfl/record is the graded record. Both are card.js's/
    // cardrecord.js's own functions, called with {sport: "nfl"} exactly
    // as they already supported before this route existed (see those
    // files' own backward-compatible options handling).
    // #/nfl/record?rule=NFL_CARD_V1 is the retired favourites rule's own
    // record (2026-09-20) -- kept apart from the live rule's, never pooled.
    // Only that one known id is passed on; any other ?rule= is ignored.
    if (route === "record" && query.rule === NFL_RETIRED_RULE) {
      await renderCardRecord(main, { sport: "nfl", rule: NFL_RETIRED_RULE });
    } else if (route === "record") {
      await renderCardRecord(main, { sport: "nfl" });
    } else {
      await renderCard(main, { sport: "nfl" });
    }
  } else if (sport === "tennis") {
    // Tennis went live 2026-09-19 too, but as a research board only --
    // every route under it, however many sub-segments it carries, shows
    // the one board (tennis.js's renderTennisBoard). No picks, no slip,
    // no record surface exists for tennis anywhere in this router.
    await renderTennisBoard(main);
  } else if (sport === "ufc") {
    // UFC went live for 2026-09-26's card, reusing the exact NFL card/
    // record renderers (card.js/cardrecord.js already read `sport` off
    // their options rather than assuming "nfl") -- the route key is "ufc"
    // (see web/js/sport.js's registry comment) but the API's own sport id
    // is "mma", so that is what is passed here, explicitly, the same way
    // the nfl branch above passes {sport: "nfl"}.
    if (route === "record") {
      await renderCardRecord(main, { sport: "mma" });
    } else {
      await renderCard(main, { sport: "mma" });
    }
  } else if (sport === "nba" || sport === "nhl") {
    // NBA and NHL are still coming-soon (D6): every route under either,
    // however many sub-segments it carries, shows the one shared page --
    // no API calls, no picks, no figures (D4).
    await renderComingSoon(main, sport);
  } else if (route === "nba" || route === "nhl") {
    // parseSport does not register nba/nhl as sport prefixes until each is
    // added to the SPORTS registry (D6) -- a bare "#/nba" or "#/nhl" still
    // reaches the shared coming-soon page rather than falling through to
    // MLB's default view.
    await renderComingSoon(main, route);
  } else if ((route === "games" || route === "game") && rest.length >= 3) {
    await renderGameDetail(main, rest[0], rest[1], rest[2]);
  } else if (route === "games") {
    await renderGamesList(main, rest[0]);
  } else if (route === "odds" && rest.length >= 3) {
    await renderOddsGame(main, rest[0], rest[1], rest[2]);
  } else if (route === "odds") {
    await renderOdds(main, rest[0]);
  } else if (route === "betcheck") {
    await renderBetCheck(main, query);
  } else if (route === "mybets") {
    await renderMyBets(main);
  } else if (route === "performance") {
    await renderPerformance(main);
  } else if (route === "props") {
    await renderProps(main, rest[0]);
  } else if (route === "day" && rest.length >= 1) {
    await renderDayDetail(main, rest[0]);
  } else if (route === "record-card") {
    // #/record-card?rule=v1 -- V1's own record, kept apart from V2's
    // (T13 cutover, docs/PREREG_CARD_V2.md R3/R5). Only that one known id
    // is ever forwarded, same guard shape as NFL's ?rule=NFL_CARD_V1 above.
    if (query.rule === MLB_SHADOW_RULE) {
      await renderCardRecord(main, { rule: MLB_SHADOW_RULE });
    } else {
      await renderCardRecord(main);
    }
  } else if (route === "live") {
    await renderLive(main);
  } else if (route === "signin") {
    await renderSignin(main, query);
  } else if (route === "support") {
    await renderSupport(main);
  } else if (route === "signup" && rest[0] === "complete") {
    await renderSignupComplete(main, query);
  } else if (route === "signup") {
    await renderSignup(main);
  } else {
    await renderToday(main);
  }
}

function boot() {
  // A joke, for one person, off a link. FIRST thing in boot and it returns
  // early, so nothing else mounts underneath it -- but it only ever returns
  // true when the URL carries the exact token in web/js/gotcha.js. No timer,
  // no stored flag, no nth-visitor roll: absent that parameter this call is
  // a string comparison that fails and nothing happens. See that file's
  // docstring for why the trigger is narrow on purpose and how to delete
  // the whole thing.
  if (maybeGotcha()) return;

  const main = document.querySelector("[data-hook='app-outlet']");
  const disclaimerHost = document.querySelector("[data-hook='disclaimer-host']");

  // Mounted once, outside renderRoute() -- the disclaimer is never
  // cleared or skipped by a view swap.
  renderDisclaimerFooter(disclaimerHost);

  // Mounted once here so the strip is not empty for the first paint;
  // updated on every route change inside _renderRouteInner above.
  mountSportLevel();

  // CHR-9: "Skip to content" (web/index.html) links to "#main-content",
  // a plain in-page anchor, not a route. Left alone, that click is a
  // hash change like any other, so the hash router (parseHash, above)
  // reads "main-content" as an unrecognised route and falls through to
  // Today -- a keyboard or screen-reader visitor anywhere else on the
  // site who uses the skip link got thrown onto Today's picks instead
  // of staying on their own page. Handled here, not as an inline
  // attribute on the link, per test_web_structure.py's no-inline-
  // event-handler rule: stop the hash navigation before it starts, and
  // move focus to <main> (tabindex="-1" in index.html) directly.
  const skipLink = document.querySelector("[data-hook='skip-link']");
  if (skipLink) {
    skipLink.addEventListener("click", (event) => {
      event.preventDefault();
      main.focus();
    });
  }

  window.addEventListener("hashchange", () => {
    // Also checked here, not only at boot: clicking the link while the app
    // is ALREADY open changes the hash without reloading, so a boot-only
    // check would silently do nothing in the most likely case -- he has
    // the site up, Brey sends the link, he taps it.
    if (maybeGotcha()) return;
    renderRoute(main);
  });

  // GET /meta once at boot, public and unauthenticated -- fetched before
  // the first renderRoute() so the very first nav mount already knows
  // whether to hide BETS, rather than showing it for one frame and then
  // yanking it away once the fetch resolves.
  // Through the shared promise, so this and the disclaimer footer and every
  // view that needs the registry counts are ONE request, not four.
  fetchMeta().then((meta) => {
    publicDemo = !!(meta && meta.public_demo);
    // Shared with the views (Bet Check picks the open route over the
    // three-for-life free route when the server is in public demo).
    setPublicDemo(publicDemo);
  }).catch(() => {
    // Unreachable /meta: fall back to showing every nav item rather than
    // guessing a visitor is in the public demo -- the individual routes
    // still enforce their own auth regardless of what the nav shows.
  }).finally(() => {
    renderRoute(main);
  });
}

document.addEventListener("DOMContentLoaded", boot);
