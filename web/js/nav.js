/**
 * THE ONE NAVIGATION (web/js/nav.js + web/css/lhnav.css), the same component on every page.
 *
 *   top bar     wordmark, Leaderboard, Kennels, Build, Training camp; on the right "Sign in" for a visitor, or
 *               "My kennel" and an account menu (My kennel, Change password, Sign out) for a member
 *   phone       a compact top bar (wordmark and the account button) and a bottom tab bar with the same five places
 *
 * SIGNED IN means a token is stored (api.js getToken), the same test every other page uses; the server still checks
 * every request, so this is a convenience, never the gate. The menu follows a sign-in or sign-out without a reload
 * (api.js announces both), and a token changed in another tab (the storage event).
 *
 * THE PAGE OWNS ONLY A HOST: `<header class="lh-nav" data-hook="site-nav">` with the signed-out links already in it,
 * so the links are on the page with scripts off. `mountNav` rebuilds the host's children, so running it twice is the
 * same as running it once. `data-current="leaderboard|kennels|mykennel|build|camp"` on the host names the page;
 * without it the place is read from the address. `data-bottom="off"` leaves the phone tab bar out (the member app has
 * its own).
 *
 * Written against attributes only (no classList, no dataset, no matchMedia): it must run in a small fake DOM too.
 */

import { getToken, clearToken, apiPost, TOKEN_CHANGED_EVENT } from "./api.js";
import { h, clearNode } from "./hounds-core.js";

export const SIGNIN_HREF = "index.html#/signin";
export const PASSWORD_HREF = "index.html#/signin?password=1";

/** The five places, in order. `key` is what `data-current` names; the tab bar shows `tab` when it has one. */
export const PLACES = [
  { key: "leaderboard", label: "Leaderboard", tab: "Board", href: "hounds.html" },
  { key: "kennels", label: "Kennels", tab: "Kennels", href: "kennels.html" },
  { key: "build", label: "Build", tab: "Build", href: "build-a-hound.html" },
  { key: "camp", label: "Training camp", tab: "Camp", href: "learning.html" },
];

const MY_KENNEL = { key: "mykennel", label: "My kennel", tab: "Mine", href: "kennel.html" };

const ICONS = {
  leaderboard: "M4 19V9m6 10V5m6 14v-7m6 7H2",
  kennels: "M3 11l9-7 9 7v9H3zM9 20v-6h6v6",
  build: "M12 5v14M5 12h14",
  camp: "M4 6h16M4 12h16M4 18h10",
  mykennel: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-6 8-6s8 2 8 6",
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

/** Which place the address means. The kennel page is "My kennel" without ?u= and a public kennel (Kennels) with it. */
export function placeFromAddress(loc = (typeof window !== "undefined" ? window.location : null)) {
  const path = String((loc && loc.pathname) || "").split("/").pop() || "";
  const params = new URLSearchParams((loc && loc.search) || "");
  if (path === "kennels.html") return "kennels";
  if (path === "hounds.html" || path === "hound.html" || path === "") return params.get("tab") === "kennels" ? "kennels" : "leaderboard";
  if (path === "kennel.html") return params.get("u") ? "kennels" : "mykennel";
  if (path === "build-a-hound.html") return "build";
  if (path === "learning.html") return "camp";
  return "";
}

function wordmark() {
  return h("a", { class: "lh-nav__brand ps-page__home", href: "landing.html", "aria-label": "LINEHOUND home" }, [
    h("span", { class: "wordmark", "data-hook": "brand-mark" }, [
      h("span", { class: "wordmark__mark" }, [h("span")]),
      h("span", { class: "wordmark__text", "data-hook": "product-name", text: "LINEHOUND" })])]);
}

function placeLink(place, current, extra = {}) {
  return h("a", Object.assign({ href: place.href, "data-nav": place.key, text: place.label,
    "aria-current": place.key === current ? "page" : undefined }, extra));
}

async function signOut() {
  try { await apiPost("/auth/logout", {}); } catch (err) { /* already gone */ }
  clearToken();
}

function accountMenu(state, close) {
  const item = (text, attrs, on) => h("a", Object.assign({ role: "menuitem", class: "lh-menu__item", text }, attrs, on ? { on } : {}));
  const menu = h("div", { class: "lh-menu", role: "menu", "data-hook": "nav-menu", hidden: true }, [
    item("My kennel", { href: MY_KENNEL.href, "data-hook": "menu-mykennel" }),
    item("Change password", { href: PASSWORD_HREF, "data-hook": "menu-password" }),
    h("button", { type: "button", role: "menuitem", class: "lh-menu__item lh-menu__item--button", "data-hook": "menu-signout", text: "Sign out",
      on: { click: async () => { close(); await signOut(); } } }),
  ]);
  state.menu = menu;
  return menu;
}

/** The right-hand side: Sign in, or My kennel and the account button with its menu. */
function accountArea(state, current) {
  if (!signedIn()) {
    return h("div", { class: "lh-nav__account", "data-hook": "nav-account-area", "data-signed-in": "false" }, [
      h("a", { class: extras && extras.length ? "lh-btn lh-btn--soft" : "lh-btn lh-btn--solid", href: SIGNIN_HREF,
        "data-hook": "nav-signin", text: "Sign in" }),
      ...(extras || [])]);
  }
  const close = () => setMenu(state, false);
  const button = h("button", { type: "button", class: "lh-avatar", "data-hook": "nav-account", "aria-haspopup": "menu",
    "aria-expanded": "false", "aria-label": "Account menu", on: { click: () => setMenu(state, state.menu.hidden) } }, [
    h("span", { class: "lh-avatar__dot", "aria-hidden": "true" }),
    h("span", { class: "lh-avatar__text", text: "Account" })]);
  state.button = button;
  return h("div", { class: "lh-nav__account", "data-hook": "nav-account-area", "data-signed-in": "true" }, [
    placeLink(MY_KENNEL, current, { class: "lh-btn lh-btn--soft", "data-hook": "nav-mykennel" }),
    h("div", { class: "lh-nav__menuwrap" }, [button, accountMenu(state, close)])]);
}

function setMenu(state, open) {
  if (!state.menu || !state.button) return;
  state.menu.hidden = !open;
  state.button.setAttribute("aria-expanded", open ? "true" : "false");
}

function tabBar(current) {
  const places = PLACES.concat([signedIn() ? MY_KENNEL : { key: "signin", label: "Sign in", tab: "Sign in", href: SIGNIN_HREF }]);
  return h("nav", { class: "lh-tabbar", "aria-label": "Sections", "data-hook": "site-tabbar" }, places.map((p) =>
    h("a", { class: "lh-tab", href: p.href, "data-nav": p.key, "aria-current": p.key === current ? "page" : undefined }, [
      icon(p.key === "signin" ? "mykennel" : p.key), h("span", { class: "lh-tab__label", text: p.tab || p.label })])));
}

let active = null;
let extras = null;

export function mountNav(host = document.querySelector(".lh-nav")) {
  if (!host) return null;
  const state = { menu: null, button: null };
  const current = host.getAttribute("data-current") || placeFromAddress();
  // an extra a page keeps in the bar for a visitor (the landing page's "Request early access"): the SAME node goes back in,
  // so a listener another script put on it survives a re-mount
  if (extras === null) extras = Array.from(host.querySelectorAll ? host.querySelectorAll("[data-nav-extra]") : []);
  clearNode(host);
  host.setAttribute("data-signed-in", signedIn() ? "true" : "false");
  host.appendChild(h("div", { class: "lh-nav__bar" }, [
    wordmark(),
    h("nav", { class: "lh-nav__links", "aria-label": "primary", "data-hook": "nav-links" }, PLACES.map((p) => placeLink(p, current))),
    accountArea(state, current)]));
  // the phone tab bar lives on the body, once
  const old = document.querySelector("[data-hook='site-tabbar']");
  if (old && old.parentNode) old.parentNode.removeChild(old);
  if (host.getAttribute("data-bottom") !== "off") document.body.appendChild(tabBar(current));
  active = state;
  return { current, signedIn: signedIn() };
}

let followed = false;
/** Mount now, and again whenever the sign-in state changes (this tab or another). */
export function bootNav() {
  const host = typeof document !== "undefined" ? document.querySelector(".lh-nav") : null;
  if (!host) return null;
  const out = mountNav(host);
  if (!followed && typeof window !== "undefined" && typeof window.addEventListener === "function") {
    followed = true;
    document.addEventListener("keydown", (evt) => { if (evt && evt.key === "Escape" && active) setMenu(active, false); });
    document.addEventListener("click", (evt) => {
      const wrap = evt && evt.target && evt.target.closest ? evt.target.closest(".lh-nav__menuwrap") : null;
      if (!wrap && active) setMenu(active, false);
    });
    const again = () => { mountNav(document.querySelector(".lh-nav")); };
    window.addEventListener(TOKEN_CHANGED_EVENT, again);
    window.addEventListener("storage", again);
  }
  return out;
}

bootNav();
