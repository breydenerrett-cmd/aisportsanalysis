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
 * ROUTES
 * -------------------------------------------------------------------
 *   #/today                                  GAMEDAY
 *   #/games[/YYYY-MM-DD]                     GAMES (slate)
 *   #/game/YYYY-MM-DD/AWAY/HOME              GAMES (one game, quick+advanced)
 *   #/betcheck[?date=&away=&home=]           BET CHECK
 *   #/odds[/YYYY-MM-DD]                      ODDS (board)
 *   #/odds/YYYY-MM-DD/AWAY/HOME              ODDS (one game)
 *   #/mybets                                 BETS
 *   #/performance                            RESULTS (PAPER / RESEARCH PERFORMANCE)
 *   #/day/YYYY-MM-DD                         DAILY RECORD (one day's frozen
 *                                             pregame record, GET /daily/{date})
 *   #/signin                                 SIGN IN (interim -- see signin.js)
 *   #/support                                SUPPORT
 *   #/signup                                 SIGNUP (public CTA target from
 *                                             web/landing.html)
 *   #/signup/complete[?token=...]            SIGNUP COMPLETE
 *   #/billing                                BILLING (402 subscription-
 *                                             expired landing target)
 */

import { el, clear, formatEasternDate, formatEasternClock } from "./dom.js";
import { apiGet, setPublicDemo } from "./api.js";
import { setShellStatus } from "./shell.js";
import { renderDisclaimerFooter } from "./meta.js";
import { renderToday } from "./today.js";
import { renderGamesList, renderGameDetail } from "./games.js";
import { renderBetCheck } from "./betcheck.js";
import { renderSignin } from "./signin.js";
import { renderOdds, renderOddsGame } from "./odds.js";
import { renderMyBets } from "./mybets.js";
import { renderSupport } from "./support.js";
import { renderSignup, renderSignupComplete } from "./signup.js";
import { renderBilling } from "./billing.js";
import { renderPerformance } from "./performance.js";
import { renderDayDetail } from "./dayrecap.js";
import { BRAND_NAME } from "./brand.js";

// The six app destinations and their glyphs, verbatim from handoff
// section 06's destination table plus RESULTS (Task B3's PAPER / RESEARCH
// PERFORMANCE surface, #/performance). Support/Signin are utility routes,
// not destinations -- they never appear in either nav shell. BETS is
// hidden at mount time when GET /meta's `public_demo` is true (saved bets
// need an invite token that a public demo visitor does not have) -- see
// `applyPublicDemoNav` below.
const NAV_ITEMS = [
  { hash: "#/today", label: "TODAY", glyph: "" },
  { hash: "#/games", label: "GAMES", glyph: "" },
  { hash: "#/betcheck", label: "CHECK", glyph: "glyph--circle" },
  { hash: "#/odds", label: "ODDS", glyph: "glyph--line" },
  { hash: "#/mybets", label: "BETS", glyph: "glyph--ticket" },
  { hash: "#/performance", label: "RESULTS", glyph: "glyph--line" },
];

// Route root -> the section label printed beside the wordmark.
const SECTION_LABELS = {
  today: "GAMEDAY",
  games: "GAMES",
  game: "GAMES",
  betcheck: "BET CHECK",
  odds: "ODDS",
  mybets: "BETS",
  signin: "SIGN IN",
  support: "SUPPORT",
  signup: "SIGN UP",
  billing: "BILLING",
  performance: "PERFORMANCE",
  day: "DAILY RECORD",
};

// GET /meta's public_demo flag, fetched once at boot (see boot() below).
// null until the fetch resolves -- mountNav treats "not known yet" the
// same as "not a public demo" (never hides BETS on a guess).
let publicDemo = false;

function navItem(item, activeHash) {
  const a = el("a", { href: item.hash, class: "nav-item chamfer chamfer--badge",
    "data-hook": "nav-link", "data-nav-hash": item.hash });
  a.appendChild(el("span", { class: `glyph ${item.glyph}`.trim(), "aria-hidden": "true" }));
  a.appendChild(el("span", { class: "nav-item__label", text: item.label }));
  if (activeHash.indexOf(item.hash) === 0) a.setAttribute("aria-current", "page");
  return a;
}

function houndMark() {
  const mark = el("span", { class: "hound", "aria-hidden": "true" });
  for (let i = 0; i < 4; i += 1) mark.appendChild(el("i"));
  return mark;
}

function mountNav(rail, tabbar, activeHash) {
  clear(rail);
  clear(tabbar);
  // The rail carries the hound monogram at its head (canvas: rail head,
  // 30x26); on mobile the same mark sits in the top strip, where there
  // is no rail to carry it.
  const head = el("a", { class: "rail__mark", href: "landing.html", "aria-label": `${BRAND_NAME} home` });
  head.appendChild(houndMark());
  rail.appendChild(head);
  const items = el("div", { class: "rail__items" });
  // A public-demo visitor has no invite token, so BETS (which needs one)
  // is hidden rather than shown as a route that will only ever 401 --
  // never rendered as a broken destination.
  const visibleItems = publicDemo ? NAV_ITEMS.filter((item) => item.hash !== "#/mybets") : NAV_ITEMS;
  for (const item of visibleItems) {
    items.appendChild(navItem(item, activeHash));
    tabbar.appendChild(navItem(item, activeHash));
  }
  rail.appendChild(items);
}

function setSectionLabel(route) {
  const host = document.querySelector("[data-hook='section-label']");
  if (host) host.textContent = SECTION_LABELS[route] || "";
}

function setClock() {
  const host = document.querySelector("[data-hook='shell-clock']");
  if (!host) return;
  const now = new Date().toISOString();
  const parts = [formatEasternDate(now), `${formatEasternClock(now)} ET`].filter(Boolean);
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
  const [route, ...rest] = segments;
  const rail = document.querySelector("[data-hook='primary-nav']");
  const tabbar = document.querySelector("[data-hook='primary-nav-mobile']");
  mountNav(rail, tabbar, "#/" + segments.join("/"));
  setSectionLabel(route || "today");
  setShellStatus(null);
  setClock();

  clear(main);
  window.scrollTo(0, 0);
  if (route === "billing") {
    await renderBilling(main);
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
  } else if (route === "day" && rest.length >= 1) {
    await renderDayDetail(main, rest[0]);
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
  const main = document.querySelector("[data-hook='app-outlet']");
  const disclaimerHost = document.querySelector("[data-hook='disclaimer-host']");

  // Mounted once, outside renderRoute() -- the disclaimer is never
  // cleared or skipped by a view swap.
  renderDisclaimerFooter(disclaimerHost);

  window.addEventListener("hashchange", () => renderRoute(main));

  // GET /meta once at boot, public and unauthenticated -- fetched before
  // the first renderRoute() so the very first nav mount already knows
  // whether to hide BETS, rather than showing it for one frame and then
  // yanking it away once the fetch resolves.
  apiGet("/meta").then((meta) => {
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
