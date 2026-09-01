/**
 * App shell wiring: nav landmark, the invite-token entry form, and a
 * minimal hash router that mounts one view module into <main> at a time.
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
 *   #/today                                  TODAY
 *   #/games[/YYYY-MM-DD]                     GAMES (slate list)
 *   #/game/YYYY-MM-DD/AWAY/HOME               GAMES (one game, quick+advanced)
 *   #/betcheck[?date=&away=&home=]            BET CHECK
 *   #/odds[/YYYY-MM-DD]                       ODDS (board)
 *   #/odds/YYYY-MM-DD/AWAY/HOME                ODDS (one game)
 *   #/mybets                                  MY BETS
 *   #/support                                 SUPPORT
 *   #/signup                                  SIGNUP (public CTA target from
 *                                              web/landing.html)
 *   #/signup/complete[?token=...]             SIGNUP COMPLETE
 *   #/billing                                 BILLING (402 subscription-
 *                                              expired landing target)
 */

import { getToken, setToken, clearToken } from "./api.js";
import { el, clear } from "./dom.js";
import { renderDisclaimerFooter } from "./meta.js";
import { renderToday } from "./today.js";
import { renderGamesList, renderGameDetail } from "./games.js";
import { renderBetCheck } from "./betcheck.js";
import { renderOdds, renderOddsGame } from "./odds.js";
import { renderMyBets } from "./mybets.js";
import { renderSupport } from "./support.js";
import { renderSignup, renderSignupComplete } from "./signup.js";
import { renderBilling } from "./billing.js";

// The five app destinations (handoff section 06, "5 destinations, two
// shells") -- Support is a utility link in the app-topbar, not one of
// these five, per that section's destination table.
const NAV_ITEMS = [
  { hash: "#/today", label: "Today", glyph: "square" },
  { hash: "#/games", label: "Games", glyph: "stack" },
  { hash: "#/betcheck", label: "Check", glyph: "circle" },
  { hash: "#/odds", label: "Odds", glyph: "line" },
  { hash: "#/mybets", label: "Bets", glyph: "ticket" },
];

function buildNavItem(item, itemClass, labelClass) {
  const a = el("a", { href: item.hash, "data-hook": "nav-link",
    "data-nav-hash": item.hash, class: itemClass });
  a.appendChild(el("span", { class: `nav-glyph nav-glyph--${item.glyph} chamfer chamfer--marker` }));
  a.appendChild(el("span", { class: labelClass, text: item.label }));
  return a;
}

function mountNav(rail, tabbar) {
  clear(rail);
  clear(tabbar);
  for (const item of NAV_ITEMS) {
    rail.appendChild(buildNavItem(item, "icon-rail__item", "icon-rail__label"));
    tabbar.appendChild(buildNavItem(item, "tab-bar__item", "tab-bar__label"));
  }
}

function updateNavCurrent(activeHash) {
  for (const link of document.querySelectorAll("[data-nav-hash]")) {
    if (activeHash.indexOf(link.getAttribute("data-nav-hash")) === 0) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
}

function mountTokenForm(host) {
  clear(host);
  const form = el("form", { class: "token-form field-form", "data-hook": "token-form" });
  const row = el("p", { class: "field-row" });
  row.appendChild(el("label", { for: "invite-token-input", text: "Invite token" }));
  const input = el("input", { type: "password", id: "invite-token-input", name: "token",
    autocomplete: "off", value: getToken(), "data-hook": "invite-token-input" });
  row.appendChild(input);
  form.appendChild(row);
  const saveButton = el("button", { type: "submit", class: "btn btn--ghost", text: "Save token" });
  const clearButton = el("button", { type: "button", class: "btn btn--ghost",
    "data-hook": "clear-token", text: "Clear token" });
  const status = el("span", { class: "token-form__status field-form__status", role: "status",
    "data-hook": "token-form-status" });

  form.appendChild(saveButton);
  form.appendChild(clearButton);
  form.appendChild(status);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    setToken(input.value.trim());
    status.textContent = "Token saved.";
  });
  clearButton.addEventListener("click", () => {
    clearToken();
    input.value = "";
    status.textContent = "Token cleared.";
  });

  host.appendChild(form);
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

async function renderRoute(main) {
  const { segments, query } = parseHash();
  updateNavCurrent("#/" + segments.join("/"));
  const [route, ...rest] = segments;

  clear(main);
  if (route === "billing") {
    await renderBilling(main);
  } else if (route === "games" && rest.length >= 3) {
    await renderGameDetail(main, rest[0], rest[1], rest[2]);
  } else if (route === "game" && rest.length >= 3) {
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
  const rail = document.querySelector("[data-hook='primary-nav']");
  const tabbar = document.querySelector("[data-hook='primary-nav-mobile']");
  const tokenHost = document.querySelector("[data-hook='token-form-host']");
  const main = document.querySelector("[data-hook='app-outlet']");
  const disclaimerHost = document.querySelector("[data-hook='disclaimer-host']");

  mountNav(rail, tabbar);
  mountTokenForm(tokenHost);
  renderDisclaimerFooter(disclaimerHost);

  window.addEventListener("hashchange", () => renderRoute(main));
  renderRoute(main);
}

document.addEventListener("DOMContentLoaded", boot);
