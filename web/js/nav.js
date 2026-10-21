/**
 * THE ONE NAVIGATION (web/js/nav.js + web/css/lhnav.css), the same component on every page.
 *
 * KENNEL-FIRST (owner ruling 2026-10-20, docs/design/KENNEL_FIRST_BRIEF.md): five places, never more.
 *
 *   signed in    My Kennel  Create  Live  Leaderboard  Account        (desktop bar and the phone tab bar are the same five)
 *   signed out   Leaderboard  Live  Sign in  and one primary button, "Find your hound" (the quiz)
 *
 * Where the old places went: Kennels (everyone's kennels) is the Leaderboard's second view; the Graveyard is linked from the
 * Leaderboard and from each kennel; the Training camp is part of My Kennel (learning.html keeps working and counts as My
 * Kennel here); the daily picks card and research pages are reached from the house kennel and the footer.
 *
 * SIGNED IN means a token is stored (api.js getToken), the same test every other page uses; the server still checks
 * every request, so this is a convenience, never the gate. The bar follows a sign-in or sign-out without a reload
 * (api.js announces both), and a token changed in another tab (the storage event).
 *
 * THE PAGE OWNS ONLY A HOST: `<header class="lh-nav" data-hook="site-nav">` with the signed-out links already in it, so the
 * links are on the page with scripts off. `mountNav` rebuilds the host's children, so running it twice is the same as
 * running it once. `data-current="mykennel|create|live|leaderboard|account"` on the host names the page (the old keys
 * build, camp and kennels still work: see ALIASES); without it the place is read from the address. `data-bottom="off"`
 * leaves the phone tab bar out (the member app has its own). `data-cta="off"` leaves the "Find your hound" button out
 * (the quiz and the builder are where it leads). A `[data-nav-extra]` node in the static host replaces the default
 * button for a visitor (the landing page keeps its own, with its own funnel hook); the SAME node goes back in on a re-mount.
 *
 * A signed-in member who opens the landing page is sent to My Kennel (home-route.js), unless the address says ?stay=1.
 *
 * Written against attributes only (no classList, no dataset, no matchMedia): it must run in a small fake DOM too.
 */

import { getToken, TOKEN_CHANGED_EVENT } from "./api.js";
import { h, clearNode } from "./hounds-core.js";
import { redirectMemberHome, MY_KENNEL_HREF } from "./home-route.js";

export const SIGNIN_HREF = "index.html#/signin";
export const PASSWORD_HREF = "index.html#/signin?password=1";
export const ACCOUNT_HREF = "index.html#/account";
export const CREATE_HREF = "quiz.html";
export const CTA_LABEL = "Find your hound";

/** The member's five places, in order. `key` is what `data-current` names; the tab bar uses the same words. */
export const PLACES = [
  { key: "mykennel", label: "My Kennel", href: MY_KENNEL_HREF },
  { key: "create", label: "Create", href: CREATE_HREF },
  { key: "live", label: "Live", href: "live.html" },
  { key: "leaderboard", label: "Leaderboard", href: "hounds.html" },
  { key: "account", label: "Account", href: ACCOUNT_HREF },
];

/** A visitor's places: the two public ones (Sign in and the button sit on the right). */
export const PUBLIC_PLACES = [PLACES[3], PLACES[2]];

/** The keys the old six-place bar used, and where they live now. */
export const ALIASES = { build: "create", camp: "mykennel", kennels: "leaderboard", signin: "account" };

const ICONS = {
  mykennel: "M3 11l9-7 9 7v9H3zM9 20v-6h6v6",
  create: "M12 5v14M5 12h14",
  live: "M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M4.9 4.9a10 10 0 0 0 0 14.2M19.1 4.9a10 10 0 0 1 0 14.2",
  leaderboard: "M4 19V9m6 10V5m6 14v-7m6 7H2",
  account: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-6 8-6s8 2 8 6",
  signin: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-6 8-6s8 2 8 6",
};

function icon(key) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "22");
  svg.setAttribute("height", "22");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.setAttribute("class", "lh-tab__icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[key] || ICONS.leaderboard);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.7");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.appendChild(path);
  return svg;
}

export const signedIn = () => !!getToken();

/** An old or new key, as one of the five (or ""). */
export function normalizePlace(key) {
  const k = String(key || "");
  return ALIASES[k] || k;
}

/** Which place the address means. The kennel page is My Kennel without ?u= and someone's public kennel (Leaderboard) with it. */
export function placeFromAddress(loc = (typeof window !== "undefined" ? window.location : null)) {
  const path = String((loc && loc.pathname) || "").split("/").pop() || "";
  const params = new URLSearchParams((loc && loc.search) || "");
  const hash = String((loc && loc.hash) || "");
  if (path === "live.html") return "live";
  if (path === "kennel.html") return params.get("u") ? "leaderboard" : "mykennel";
  if (path === "learning.html") return "mykennel";                       // the training camp is part of My Kennel
  if (path === "build-a-hound.html" || path === "quiz.html") return "create";
  if (path === "hounds.html" || path === "hound.html" || path === "kennels.html" || path === "graveyard.html" || path === "") return "leaderboard";
  if (path === "index.html") return /^#\/(signin|account|billing)/.test(hash) ? "account" : "";
  return "";
}

function wordmark(home) {
  return h("a", { class: "lh-nav__brand ps-page__home", href: home, "aria-label": "LINEHOUND home" }, [
    h("span", { class: "wordmark", "data-hook": "brand-mark" }, [
      h("span", { class: "wordmark__mark" }, [h("span")]),
      h("span", { class: "wordmark__text", "data-hook": "product-name", text: "LINEHOUND" })])]);
}

function placeLink(place, current, extra = {}) {
  return h("a", Object.assign({ href: place.href, "data-nav": place.key, text: place.label,
    "aria-current": place.key === current ? "page" : undefined }, extra));
}

/** The right-hand side. A visitor: Sign in, then the one primary button. A member: the Account place. */
function accountArea(current, host) {
  if (!signedIn()) {
    const parts = [h("a", { class: "lh-btn lh-btn--soft", href: SIGNIN_HREF, "data-hook": "nav-signin", text: "Sign in" })];
    const hideCta = host.getAttribute("data-cta") === "off" || current === "create";
    if (!hideCta) parts.push(...(extras && extras.length ? extras
      : [h("a", { class: "lh-btn lh-btn--solid", href: CREATE_HREF, "data-hook": "nav-cta", text: CTA_LABEL })]));
    return h("div", { class: "lh-nav__account", "data-hook": "nav-account-area", "data-signed-in": "false" }, parts);
  }
  const account = PLACES[4];
  return h("div", { class: "lh-nav__account", "data-hook": "nav-account-area", "data-signed-in": "true" }, [
    placeLink(account, current, { class: "lh-avatar", "data-hook": "nav-account" }),
  ]);
}

/** The phone tab bar. A member: the same five places. A visitor: Leaderboard, Live, Sign in and the primary button. */
function tabBar(current, hideCta = false) {
  const tab = (p) => h("a", { class: "lh-tab", href: p.href, "data-nav": p.key, "aria-current": p.key === current ? "page" : undefined }, [
    icon(p.key), h("span", { class: "lh-tab__label", text: p.label })]);
  if (signedIn()) {
    return h("nav", { class: "lh-tabbar", "aria-label": "Sections", "data-hook": "site-tabbar", "data-count": "5" }, PLACES.map(tab));
  }
  // On the quiz and the builder (where the button leads) the bar drops it, as the desktop bar does: one primary per screen.
  const visitor = PUBLIC_PLACES.map(tab).concat([tab({ key: "signin", label: "Sign in", href: SIGNIN_HREF })]);
  if (!hideCta) visitor.push(h("a", { class: "lh-tab lh-tab--cta", href: CREATE_HREF, "data-hook": "tab-cta", "data-nav": "create" }, [
    h("span", { class: "lh-tab__label", text: CTA_LABEL })]));
  return h("nav", { class: "lh-tabbar", "aria-label": "Sections", "data-hook": "site-tabbar", "data-count": String(visitor.length) }, visitor);
}

let extras = null;

export function mountNav(host = document.querySelector(".lh-nav")) {
  if (!host) return null;
  const current = normalizePlace(host.getAttribute("data-current") || placeFromAddress());
  // an extra a page keeps in the bar for a visitor (the landing page's own button): the SAME node goes back in, so a
  // listener another script put on it survives a re-mount
  if (extras === null) extras = Array.from(host.querySelectorAll ? host.querySelectorAll("[data-nav-extra]") : []);
  clearNode(host);
  host.setAttribute("data-signed-in", signedIn() ? "true" : "false");
  const links = signedIn() ? PLACES.slice(0, 4) : PUBLIC_PLACES;
  host.appendChild(h("div", { class: "lh-nav__bar" }, [
    wordmark(signedIn() ? MY_KENNEL_HREF : "landing.html"),
    h("nav", { class: "lh-nav__links", "aria-label": "primary", "data-hook": "nav-links" }, links.map((p) => placeLink(p, current))),
    accountArea(current, host)]));
  // the phone tab bar lives on the body, once
  const old = document.querySelector("[data-hook='site-tabbar']");
  if (old && old.parentNode) old.parentNode.removeChild(old);
  if (host.getAttribute("data-bottom") !== "off") document.body.appendChild(tabBar(current, host.getAttribute("data-cta") === "off" || current === "create"));
  return { current, signedIn: signedIn() };
}

let followed = false;
/** Mount now, and again whenever the sign-in state changes (this tab or another). */
export function bootNav() {
  const host = typeof document !== "undefined" ? document.querySelector(".lh-nav") : null;
  if (!host) return null;
  // a member on the landing page goes home (My Kennel) before anything else is drawn
  if (typeof window !== "undefined" && redirectMemberHome(window, signedIn())) return null;
  const out = mountNav(host);
  if (!followed && typeof window !== "undefined" && typeof window.addEventListener === "function") {
    followed = true;
    const again = () => { mountNav(document.querySelector(".lh-nav")); };
    window.addEventListener(TOKEN_CHANGED_EVENT, again);
    window.addEventListener("storage", again);
  }
  return out;
}

bootNav();
