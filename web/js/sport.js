/**
 * Sport selection and routing (DESIGN_SYSTEM.md section 3, "Sport level
 * and sub menu").
 *
 * WHY THIS EXISTS
 * ---------------------------------------------------------------
 * The app serves MLB today, with NFL and Tennis marked coming soon in the
 * top-right (D4) and NBA/NHL registered ahead of their own announcement
 * (D6). Routing distinguishes the sport by a leading segment in the hash:
 * #/nfl routes to the NFL coming-soon page, #/today (no leading sport
 * segment) routes to MLB. This module owns the one SPORTS registry every
 * other file reads, `parseSport` (the hash parser), and `renderSportLevel`
 * (the sport-level bar: live sports as tabs, coming-soon sports as the
 * two red text links).
 *
 * `renderSportSwitcher` (the old three-link-plus-Live switcher) and the
 * `#/live` link are deleted entirely, per D4/D5 -- Live stays reachable
 * only by a typed URL (see main.js's router; nothing in this file links
 * to it).
 */

import { el, clear } from "./dom.js";

/** Shown once above the picks on the (unrouted, kept-on-disk) NFL card
 * builder -- card.js and cardrecord.js still import this name directly
 * (DESIGN_SYSTEM.md section 6: "The NFL card and tennis board code ...
 * stay on disk, unmodified and unrouted"), so it stays exported here
 * unchanged even though nothing in the routed app shows it today. */
export const NFL_NOTICE = "Experimental selections. Performance is still being evaluated.";

/**
 * THE ONE SPORT REGISTRY (DESIGN_SYSTEM.md section 3).
 *
 * Every entry is `{key, label, status: "live" | "coming_soon", home,
 * submenu, plan}`. `submenu` carries MLB's real sub-menu items in the
 * exact `{hash, label, sub}` field order `tests/test_whose_record_is_it.py`
 * requires (hash immediately before label); a coming-soon sport has no
 * sub menu yet. `plan` stays `null` for every sport until per-sport
 * billing ships (D6) -- the rail/gameday header render nothing in the
 * `data-hook="sport-plan"` slot while it is null.
 *
 * NBA and NHL (owner addition, 2026-09-15, beyond DESIGN_BUILD_PLAN.json's
 * CHR-1 task text): registered here with `status: "coming_soon"` and
 * homes `#/nba` / `#/nhl` so those routes resolve and any other module
 * can read their labels -- but D4 fixes the top-right red strip to
 * exactly "NFL · COMING SOON" and "TENNIS · COMING SOON". `renderSportLevel`
 * below never loops generically over every `coming_soon` entry for the
 * strip; it renders only the `nfl` and `tennis` entries by key. NBA and
 * NHL are likewise not rendered in the phone sport row (DESIGN_SYSTEM.md
 * section 3's phone row lists "MLB tab on the left, both red items on the
 * right" -- exactly two) or the desktop rail heading list (the rail
 * heading is the one *live* sport's label; DESIGN_SYSTEM.md never places
 * a coming-soon sport in it). Both are simply registered and otherwise
 * unrendered until the owner asks for them to appear somewhere.
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
  { key: "nfl", label: "NFL", status: "coming_soon", home: "#/nfl", submenu: [], plan: null },
  { key: "tennis", label: "Tennis", status: "coming_soon", home: "#/tennis", submenu: [], plan: null },
  { key: "nba", label: "NBA", status: "coming_soon", home: "#/nba", submenu: [], plan: null },
  { key: "nhl", label: "NHL", status: "coming_soon", home: "#/nhl", submenu: [], plan: null },
];

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
 * tabs ("MLB", 3px red underline when selected) and the coming-soon
 * sports as the two red "NFL/TENNIS · COMING SOON" text links -- one
 * `.sportlevel` component, one host. CSS (chrome's app.css, not this
 * file) repositions the same host between the desktop strip and the
 * phone sport row; this function does not mount twice.
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

  // Exactly the two red links D4 names -- never a generic loop over every
  // coming_soon entry (see the SPORTS registry comment above re: NBA/NHL).
  const soon = el("div", { class: "sportlevel__soon" });
  for (const key of ["nfl", "tennis"]) {
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
