/**
 * Sport selection and routing (DESIGN_SYSTEM.md section 3, "Sport level
 * and sub menu").
 *
 * WHY THIS EXISTS
 * ---------------------------------------------------------------
 * The app serves MLB, NFL and Tennis today; NBA/NHL are registered ahead
 * of their own announcement (D6) and stay coming-soon. Routing
 * distinguishes the sport by a leading segment in the hash: #/nfl routes
 * to the real NFL card, #/tennis routes to the real (picks-free) tennis
 * research board, #/today (no leading sport segment) routes to MLB. This
 * module owns the one SPORTS registry every other file reads, `parseSport`
 * (the hash parser), and `renderSportLevel` (the sport-level bar: live
 * sports as tabs, coming-soon sports as red text links).
 *
 * NFL AND TENNIS WENT LIVE 2026-09-19 (see docs/DESIGN_SYSTEM.md section 3
 * amendment and section 6's "NFL and Tennis" paragraph, both updated in
 * the same change). Before this they were `status: "coming_soon"` and
 * every route under them rendered the shared comingsoon.js page --
 * `web/js/card.js`'s and `web/js/cardrecord.js`'s NFL branches and
 * `web/js/tennis.js` existed on disk but were never reachable by a route.
 * They are wired into main.js's router now (see that file). NFL and
 * Tennis are NOT the same kind of "live": NFL genuinely publishes picks
 * (one so far -- see NFL_NOTICE below and the unmissable sample-size
 * language card.js/cardrecord.js render alongside it); Tennis publishes a
 * de-vigged research board and NEVER a pick, a slip or a record (its own
 * notice, unchanged, says so).
 *
 * `renderSportSwitcher` (the old three-link-plus-Live switcher) and the
 * `#/live` link are deleted entirely, per D4/D5 -- Live stays reachable
 * only by a typed URL (see main.js's router; nothing in this file links
 * to it).
 */

import { el, clear } from "./dom.js";

/** Shown above the picks on the now-routed NFL card (`card.js`,
 * `cardrecord.js` -- both import this name directly). Sits beside the
 * explicit sample-size line those two files render themselves (n=1 today);
 * this sentence alone is not enough to carry that weight, which is why
 * neither file relies on it in place of stating the actual count. */
export const NFL_NOTICE = "Experimental selections. Performance is still being evaluated.";

/** The NFL rule retired on 2026-09-20 (take the market favourite in every
 * game -- it published SF -950). Its picks stay in the NFL ledger exactly
 * as published and are graded on a record of their own, never pooled with
 * the live rule's. The NFL record page shows the live rule; this id is the
 * ONE other value `#/nfl/record?rule=` may carry (main.js, cardrecord.js),
 * so a typed query string never reaches the API unchecked. card.js reads
 * it to label a card this rule made. */
export const NFL_RETIRED_RULE = "NFL_CARD_V1";

/** The MLB rule retired at cutover to `DAILY_CARD_BEST_BETS_V2`
 * (`src.report.card.CUTOVER_DATE`, registration `docs/PREREG_CARD_V2.md`
 * R3/R5) -- it published market favourites, including moneylines shorter
 * than -200, which V2's own G4 gate can never do (docs/PREREG_CARD_V2.md
 * section 3). Its picks stay in `evidence/cards_v1.jsonl` exactly as
 * published and are graded on a record of their own, in shadow, never
 * pooled with V2's. Same shape as `NFL_RETIRED_RULE` just above: the ONE
 * other value `#/record-card?rule=` may carry, so a typed query string
 * never reaches the API unchecked. */
export const MLB_SHADOW_RULE = "v1";

/**
 * THE ONE SPORT REGISTRY (DESIGN_SYSTEM.md section 3).
 *
 * Every entry is `{key, label, status: "live" | "coming_soon", home,
 * submenu, plan}`. `submenu` carries a sport's real sub-menu items in the
 * exact `{hash, label, sub}` field order `tests/test_whose_record_is_it.py`
 * requires for MLB's own RESULTS entry (hash immediately before label) --
 * every submenu entry in this registry keeps that same field order for
 * consistency, whether or not a test pins it. A coming-soon sport has no
 * sub menu yet. `plan` stays `null` for every sport until per-sport
 * billing ships (D6) -- the rail/gameday header render nothing in the
 * `data-hook="sport-plan"` slot while it is null.
 *
 * NFL AND TENNIS, LIVE (2026-09-19). NFL gets a two-item submenu -- GAMEDAY
 * (the card, `#/nfl`) and RESULTS (the graded record, `#/nfl/record`) --
 * mirroring MLB's shape at the minimum the two real NFL views need. Tennis
 * has exactly one destination (the research board) and no sub menu of its
 * own, same as MLB would if it only had one page. Neither is added to the
 * red "COMING SOON" strip links any more (see `renderSportLevel` below);
 * both render as ordinary live tabs beside MLB.
 *
 * NBA and NHL (owner addition, 2026-09-15, beyond DESIGN_BUILD_PLAN.json's
 * CHR-1 task text): registered here with `status: "coming_soon"` and
 * homes `#/nba` / `#/nhl` so those routes resolve and any other module
 * can read their labels. They are not rendered in the phone sport row
 * (DESIGN_SYSTEM.md section 3) or the desktop rail heading list (the rail
 * heading is the one MLB *live* sport's label; DESIGN_SYSTEM.md never
 * places a coming-soon sport in it). Both are simply registered and
 * otherwise unrendered until the owner asks for them to appear somewhere
 * -- `renderSportLevel`'s coming-soon strip below stays a short, explicit
 * list (currently empty) rather than a generic loop over every
 * `coming_soon` entry, precisely so adding NBA/NHL here does not silently
 * surface them in the strip too.
 */
export const SPORTS = [
  {
    key: "mlb",
    label: "MLB",
    status: "live",
    home: "#/today",
    submenu: [
      { hash: "#/today", label: "GAMEDAY", sub: "Today's picks" },
      { hash: "#/games", label: "MATCHUPS", sub: "Every game, in depth" },
      { hash: "#/props", label: "PROPS", sub: "Priced player props" },
      { hash: "#/record-card", label: "RESULTS", sub: "Every pick, graded" },
      { hash: "#/mybets", label: "BETS", sub: "Your saved bets" },
    ],
    plan: null,
  },
  {
    key: "nfl",
    label: "NFL",
    status: "live",
    home: "#/nfl",
    submenu: [
      { hash: "#/nfl", label: "GAMEDAY", sub: "Today's picks" },
      { hash: "#/nfl/record", label: "RESULTS", sub: "Every pick, graded" },
    ],
    plan: null,
  },
  {
    key: "tennis",
    label: "Tennis",
    status: "live",
    home: "#/tennis",
    submenu: [
      { hash: "#/tennis", label: "BOARD", sub: "Match board, no picks" },
    ],
    plan: null,
  },
  {
    // Route/registry key is "ufc" (the URL segment, "#/ufc"); the backend's
    // sport id is "mma" (src.sports.SPORTS, matching The Odds API's own
    // "mma_mixed_martial_arts" key) -- main.js's router passes {sport:
    // "mma"} to renderCard/renderCardRecord explicitly, the same way it
    // hardcodes {sport: "nfl"} for the "nfl" key, rather than assuming the
    // route key and the API sport id are always the same string.
    key: "ufc",
    label: "UFC",
    status: "live",
    home: "#/ufc",
    submenu: [
      { hash: "#/ufc", label: "GAMEDAY", sub: "This card's picks" },
      { hash: "#/ufc/record", label: "RESULTS", sub: "Every pick, graded" },
    ],
    plan: null,
  },
  { key: "nba", label: "NBA", status: "coming_soon", home: "#/nba", submenu: [], plan: null },
  { key: "nhl", label: "NHL", status: "coming_soon", home: "#/nhl", submenu: [], plan: null },
];

/** Which `coming_soon` sports (by key) get a red "X · COMING SOON" link in
 * the top strip -- named explicitly, never derived from `SPORTS.filter`,
 * so registering a future coming-soon sport in the array above does not
 * silently add it here too (see the SPORTS registry comment). D4 named
 * exactly `["nfl", "tennis"]`; both went live 2026-09-19 and were removed,
 * leaving this empty until the owner names the next one. */
const TOP_STRIP_COMING_SOON = [];

/**
 * Parse the hash to extract sport and segments.
 *
 * A leading segment matching a registered sport key selects that sport
 * and is removed from `segments`; a leading "mlb" segment is stripped the
 * same way even though MLB has no prefix in its own canonical routes
 * (`#/today`, not `#/mlb/today`) -- this keeps `#/mlb/...` aliases
 * resolvable from the router without a second, separate stripping step
 * (DESIGN_SYSTEM.md section 3: "parseSport also strips a leading 'mlb'
 * segment"). Anything else defaults to "mlb" with segments unchanged.
 * Returns `{sport, segments}`.
 */
export function parseSport(hash) {
  const segments = hash || [];
  if (segments.length === 0) {
    return { sport: "mlb", segments };
  }
  const first = segments[0];
  if (first === "mlb") {
    return { sport: "mlb", segments: segments.slice(1) };
  }
  if (SPORTS.some((s) => s.key === first)) {
    return { sport: first, segments: segments.slice(1) };
  }
  return { sport: "mlb", segments };
}

/**
 * Render the sport-level bar (DESIGN_SYSTEM.md section 3): live sports as
 * tabs ("MLB", "NFL", "Tennis", 3px red underline when selected) and any
 * coming-soon sports named in `TOP_STRIP_COMING_SOON` below as red
 * "X · COMING SOON" text links -- one `.sportlevel` component, one host.
 * CSS (chrome's app.css, not this file) repositions the same host between
 * the desktop strip and the phone sport row; this function does not mount
 * twice.
 *
 * NFL and Tennis moved from the second group to the first on 2026-09-19
 * (docs/DESIGN_SYSTEM.md section 3 amendment) -- the strip currently shows
 * no coming-soon links at all, which is correct: NBA/NHL are still
 * registered `coming_soon` but D6 keeps them out of this strip until the
 * owner asks for them specifically.
 *
 * `activeSport` gets `aria-current="page"` on its tab or its coming-soon
 * link. `linkPrefix` defaults to `""` so app routes are unaffected;
 * `landing.js` calls this with `linkPrefix: "index.html"` so the same
 * hrefs resolve from `landing.html` (DESIGN_SYSTEM.md section 3). An
 * optional `placement` string (e.g. "desktop", "phone", "landing") is
 * added as a `sportlevel--{placement}` modifier class purely as a CSS
 * hook -- it changes no rendered content.
 *
 * Called on every route change (from `main.js`'s `_renderRouteInner`,
 * the same place `mountNav`/`setSectionLabel` already run), not once at
 * boot, so `aria-current` tracks whichever sport is actually active.
 */
export function renderSportLevel(host, activeSport, { placement, linkPrefix = "" } = {}) {
  if (!host) return;

  const root = el("nav", {
    class: `sportlevel${placement ? ` sportlevel--${placement}` : ""}`,
    "data-hook": "sport-level",
    "aria-label": "Sports",
  });

  const tabs = el("div", { class: "sportlevel__tabs" });
  for (const sport of SPORTS) {
    if (sport.status !== "live") continue;
    const a = el("a", {
      class: "sportlevel__tab",
      href: `${linkPrefix}${sport.home}`,
      "data-hook": "sport-tab",
      "data-sport": sport.key,
      text: sport.label,
    });
    if (sport.key === activeSport) a.setAttribute("aria-current", "page");
    tabs.appendChild(a);
  }
  root.appendChild(tabs);

  root.appendChild(el("span", { class: "sportlevel__spacer", "aria-hidden": "true" }));

  // A short, explicit list -- never a generic loop over every coming_soon
  // entry (see the SPORTS registry comment above re: NBA/NHL). NFL and
  // TENNIS were the two names D4 gave this list; both graduated to live
  // tabs above on 2026-09-19, so the list is empty until the owner names a
  // sport that should show here.
  const soon = el("div", { class: "sportlevel__soon" });
  for (const key of TOP_STRIP_COMING_SOON) {
    const sport = SPORTS.find((s) => s.key === key);
    if (!sport) continue;
    const a = el("a", {
      class: "sportlevel__soon-link",
      href: `${linkPrefix}${sport.home}`,
      "data-hook": "sport-coming-soon",
      "data-sport": sport.key,
      text: `${sport.label.toUpperCase()} · COMING SOON`,
    });
    if (sport.key === activeSport) a.setAttribute("aria-current", "page");
    soon.appendChild(a);
  }
  root.appendChild(soon);

  clear(host);
  host.appendChild(root);
}
