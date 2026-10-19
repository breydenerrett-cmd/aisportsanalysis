/**
 * THE ADMIN DASHBOARD -- web/admin.html (owner request, 2026-10-19: "needs UI and an actual html
 * page and easy to use admin privileges"). One page, five tabs: Overview, People, Funnel, Health,
 * Support. This file owns the flow; what each tab draws is in admin-views.js, the dialog and small
 * elements are in admin-ui.js, and the token store and the one fetch wrapper are in admin.js.
 *
 * THE TOKEN
 * -------------------------------------------------------------------
 * The admin token is the one credential here that can read every email and hand out access. It
 * lives in sessionStorage (admin.js explains why, and tests/test_web_structure.py pins it), is sent
 * only as the `X-Admin-Token` header, and is NEVER shown back: the sign-in field starts empty every
 * time. The sign-in card appears when no token is saved or the server rejects the one that is
 * (401, which also forgets it); a 404 means the admin surface is switched off on this server and
 * says so, which is a different problem from a wrong token.
 *
 * AN ACCESS TOKEN IS A DIFFERENT THING
 * -------------------------------------------------------------------
 * Granting a tester, approving a free member or re-issuing a login returns a customer's access
 * token ONCE. It is shown in one dialog (with the sign-in link and a message ready to send) and
 * the dialog's root is emptied when it closes. It is never written to storage, never put in a URL,
 * never logged, and no later read of the admin API returns it.
 *
 * EVERY ACTION GOES THROUGH A CONFIRM DIALOG, and where the API requires a reason the dialog will
 * not send without one. A refusal from the server is shown in the server's own words.
 */

import { el, clear } from "./dom.js";
import {
  getAdminToken, setAdminToken, clearAdminToken, adminGet, adminPost, testerErrorText, signinUrl,
} from "./admin.js";
import {
  chip, button, toast, isInside, copyText, focusSoon, formDialog, showDialog, closeDialog, momentLabel,
} from "./admin-ui.js";
import {
  renderOverview, renderPeople, renderFunnel, renderHealth, renderSupport, rowActions, peopleRows, storeCards,
} from "./admin-views.js";

const ROUTES = ["overview", "people", "funnel", "health", "support"];
const ROUTE_TITLE = { overview: "Overview", people: "People", funnel: "Funnel", health: "Health", support: "Support" };

const SOURCES = {
  overview: "/admin/overview",
  users: "/admin/users",
  testers: "/admin/testers",
  comps: "/admin/comps",
  funnel: "/admin/funnel",
  support: "/admin/support",
  revenue: "/admin/revenue",
};

const hook = (name) => document.querySelector(`[data-hook='${name}']`);

/** The message the owner sends with a new access token. It carries the token, so it exists only
 * as the dialog's read-only text and as clipboard text on a click. */
export function accessMessage(issued, plan) {
  const lines = [
    `Here's your LineHound access: open ${signinUrl()} and paste this code where it asks for your access token, then press Save token.`,
    "",
    issued.token,
    "",
    plan.forever
      ? "It works with no card and no end date. Keep it to yourself."
      : `It works until ${momentLabel(issued.expires_at)}. Keep it to yourself.`,
    "If you lose it, reply here and I'll send a new one.",
  ];
  return lines.join("\n");
}

function boot() {
  const app = hook("admin-app");
  if (!app) return;
  const hosts = {
    top: hook("admin-header"),
    gate: hook("admin-gate"),
    gateInput: hook("admin-token-input"),
    gateMessage: hook("admin-gate-message"),
    gateForm: hook("admin-gate-form"),
    loading: hook("admin-loading"),
    shell: hook("admin-shell"),
    chip: hook("admin-token-chip"),
    signout: hook("admin-signout"),
    refresh: hook("admin-refresh"),
    updated: hook("admin-updated"),
    banner: hook("admin-banner"),
    toasts: hook("admin-toasts"),
    modal: hook("admin-modal-root"),
    menu: hook("admin-menu-root"),
    views: Object.fromEntries(ROUTES.map((r) => [r, hook(`admin-view-${r}`)])),
    hosts: Object.fromEntries(ROUTES.map((r) => [r, hook(`admin-host-${r}`)])),
    nav: Array.from(document.querySelectorAll("[data-hook='admin-nav-item']")),
    badges: Array.from(document.querySelectorAll("[data-hook='admin-nav-badge']")),
  };
  const inert = [hosts.top, hosts.gate, hosts.loading, hosts.shell].filter(Boolean);

  const state = {
    data: {}, errors: {}, route: "overview", loadedAt: null,
    filter: { q: "", group: "all", limit: 100 },
    supportFilter: { status: "open" },
  };

  let loadId = 0;

  // ---- sign-in card and token chip ----------------------------------------------------------

  function setChip(word, tone) {
    clear(hosts.chip);
    hosts.chip.setAttribute("data-tone", tone);
    hosts.chip.setAttribute("class", `adm-chip adm-chip--${tone}`);
    hosts.chip.textContent = word;
  }

  function showGate(message, tone = "mute", chipWord = "Not signed in") {
    loadId += 1;                                // an in-flight load must not bring the data back
    closeDialog();
    closeMenu();
    state.data = {};
    state.errors = {};
    hosts.shell.hidden = true;
    hosts.loading.hidden = true;
    hosts.gate.hidden = false;
    hosts.signout.hidden = true;
    hosts.refresh.hidden = true;
    hosts.updated.textContent = "";
    hosts.gateInput.value = "";
    hosts.gateMessage.textContent = message || "";
    hosts.gateMessage.setAttribute("data-tone", tone);
    setChip(chipWord, tone === "bad" ? "bad" : "mute");
    focusSoon(hosts.gateInput);
  }

  function showApp() {
    hosts.gate.hidden = true;
    hosts.loading.hidden = true;
    hosts.shell.hidden = false;
    hosts.signout.hidden = false;
    hosts.refresh.hidden = false;
    setChip("Signed in", "ok");
  }

  /** The server said this token is wrong: forget it and ask again. */
  function rejectToken() {
    clearAdminToken();
    showGate("That token was rejected. Paste the current admin token to continue.", "bad", "Token rejected");
  }

  function signOut() {
    clearAdminToken();
    showGate("You are signed out of admin on this tab.", "mute");
  }

  // ---- loading ------------------------------------------------------------------------------

  async function loadAll({ quiet = false } = {}) {
    const mine = ++loadId;
    if (!quiet) {
      hosts.shell.hidden = true;
      hosts.gate.hidden = true;
      hosts.loading.hidden = false;
    }
    hosts.updated.textContent = "Refreshing...";
    const names = Object.keys(SOURCES);
    const results = await Promise.allSettled(names.map((name) => adminGet(SOURCES[name])));
    if (mine !== loadId) return;               // a newer load (or a sign-out) took over
    const data = {};
    const errors = {};
    names.forEach((name, i) => {
      const r = results[i];
      if (r.status === "fulfilled") { data[name] = r.value; errors[name] = null; }
      else { data[name] = null; errors[name] = r.reason; }
    });
    const rejected = names.find((n) => errors[n] && errors[n].status === 401);
    if (rejected) { rejectToken(); return; }
    if (errors.overview && errors.overview.status === 404) {
      showGate("The admin pages are switched off on this server: APP_ADMIN_TOKEN is not set here. "
        + "No token can work until it is.", "bad", "Admin off");
      return;
    }
    state.data = data;
    state.errors = errors;
    state.loadedAt = Date.now();
    showApp();
    renderBanner();
    renderAll();
    hosts.updated.textContent = `Updated ${momentLabel(new Date(state.loadedAt).toISOString())}`;
  }

  function renderBanner() {
    clear(hosts.banner);
    const failed = Object.keys(state.errors).filter((n) => state.errors[n]);
    if (failed.length === Object.keys(SOURCES).length) {
      hosts.banner.appendChild(el("p", { class: "adm-note adm-note--bad", "data-hook": "admin-banner-text",
        text: "Could not reach the admin API. Check the connection and press Refresh." }));
    }
  }

  // ---- rendering ----------------------------------------------------------------------------

  const ctx = {
    now: () => Date.now(),
    get errors() { return state.errors; },
    filter: state.filter,
    supportFilter: state.supportFilter,
    passwordReset: false,      // flips on when POST /admin/users/password-reset exists on this server
    go, runAction, openMenu,
    addPerson,
    rerenderPeople: () => renderPeople(hosts.hosts.people, state.data, ctx),
    rerenderSupport: () => { renderSupport(hosts.hosts.support, state.data.support, ctx); renderBadges(); },
    setSupportStatus,
  };

  function renderAll() {
    renderOverview(hosts.hosts.overview, state.data, ctx);
    renderPeople(hosts.hosts.people, state.data, ctx);
    renderFunnel(hosts.hosts.funnel, state.data.funnel, ctx);
    renderHealth(hosts.hosts.health, state.data.overview, ctx);
    renderSupport(hosts.hosts.support, state.data.support, ctx);
    renderBadges();
    showRoute();
  }

  function renderBadges() {
    const now = Date.now();
    const waiting = state.data.users ? peopleRows(state.data, now).filter((r) => r.state.group === "waitlist").length : 0;
    const open = ((state.data.support || {}).messages || []).filter((m) => m.status === "open").length;
    const cards = storeCards(state.data.overview);
    const bad = cards ? cards.groups.flatMap((g) => g.cards).filter((c) => c.tone === "bad").length : 0;
    const counts = { people: waiting, support: open, health: bad };
    for (const badge of hosts.badges) {
      const n = counts[badge.getAttribute("data-for")] || 0;
      badge.textContent = String(n);
      badge.hidden = n === 0;
    }
  }

  function showRoute() {
    for (const route of ROUTES) hosts.views[route].hidden = route !== state.route;
    for (const item of hosts.nav) {
      if (item.getAttribute("data-route") === state.route) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    document.title = `${ROUTE_TITLE[state.route]} - LINEHOUND Admin`;
  }

  function go(route, group) {
    if (!ROUTES.includes(route)) route = "overview";
    state.route = route;
    if (route === "people" && group) {
      state.filter.group = group;
      state.filter.limit = 100;
      if (state.data.users) ctx.rerenderPeople();
    }
    showRoute();
    try {
      if (window.location.hash !== `#/${route}`) window.location.hash = `#/${route}`;
    } catch (err) {
      /* the hash is a convenience for reload and back */
    }
  }

  // ---- the row menu -------------------------------------------------------------------------

  let menuState = null;

  function closeMenu() {
    if (!menuState) return;
    const { node, trigger } = menuState;
    menuState = null;
    if (node.parentNode) node.parentNode.removeChild(node);
    trigger.setAttribute("aria-expanded", "false");
  }

  function openMenu(trigger, row, items) {
    if (menuState && menuState.trigger === trigger) { closeMenu(); return; }
    closeMenu();
    const node = el("div", { class: "adm-menu", role: "menu", "data-hook": "admin-menu", "data-user-id": String(row.id) });
    for (const item of items) {
      const entry = el("button", { type: "button", role: "menuitem", class: `adm-menu__item${item.danger ? " adm-menu__item--danger" : ""}`,
        "data-hook": "admin-menu-item", "data-action": item.key, title: item.note });
      entry.appendChild(el("span", { class: "adm-menu__label", text: item.label }));
      if (item.note) entry.appendChild(el("span", { class: "adm-menu__note", text: item.note }));
      if (item.disabled) {
        entry.disabled = true;
        entry.setAttribute("aria-disabled", "true");
      } else {
        entry.addEventListener("click", () => { closeMenu(); runAction(item.key, row); });
      }
      node.appendChild(entry);
    }
    hosts.menu.appendChild(node);
    trigger.setAttribute("aria-expanded", "true");
    try {
      const rect = trigger.getBoundingClientRect();
      const width = (typeof window.innerWidth === "number" && window.innerWidth) || 1200;
      const height = (typeof window.innerHeight === "number" && window.innerHeight) || 800;
      const below = rect.bottom + 6;
      const room = height - below;
      node.style.right = `${Math.max(8, width - rect.right)}px`;
      if (room < 60 + items.length * 44 && rect.top > room) node.style.bottom = `${height - rect.top + 6}px`;
      else node.style.top = `${below}px`;
    } catch (err) {
      /* placement is cosmetic */
    }
    menuState = { node, trigger };
    const first = node.querySelector("[data-action]");
    focusSoon(first);
  }

  document.addEventListener("click", (event) => {
    if (!menuState) return;
    const target = event && event.target;
    if (!isInside(target, menuState.node) && !isInside(target, menuState.trigger)) closeMenu();
  });
  document.addEventListener("keydown", (event) => { if (event && event.key === "Escape") closeMenu(); });
  window.addEventListener("scroll", closeMenu, true);
  window.addEventListener("resize", closeMenu);

  // ---- actions ------------------------------------------------------------------------------

  const REASON_NOTE = "Kept in the audit log. Do not paste a token or key.";

  function unauthorized() { rejectToken(); }

  /** A confirm dialog around one request; on success shows the access token (if the request
   * returned one) and refreshes the data. */
  function confirmAction({ title, intro, fields = [], label, variant = "primary", run, plan, done }) {
    formDialog(hosts.modal, {
      title, intro, fields, inertTargets: inert, errorText: testerErrorText, onUnauthorized: unauthorized,
      hook: "admin-confirm",
      actions: [{ label, variant, hook: "admin-confirm-submit", pendingLabel: "Working...", run }],
      onDone: async (result) => {
        if (result && result.token) showToken(result, plan || { verb: "Access issued", forever: false });
        else if (done) toast(hosts.toasts, done(result), "ok");
        await loadAll({ quiet: true });
      },
    });
  }

  function runAction(key, row) {
    const who = row.email;
    if (key === "approve") {
      confirmAction({
        title: "Approve as free member",
        intro: [`${who} gets full access with no card and no end date, until you revoke it.`,
                "Any older login codes of theirs stop working and you get one new code to send them."],
        fields: [{ key: "reason", label: "Why does this person get free access?", type: "textarea", required: true,
                   requiredMessage: "say why (it is kept in the log)", hint: REASON_NOTE }],
        label: "Approve as free member",
        run: (v) => adminPost("/admin/comps", { user_id: row.id, reason: v.reason }),
        plan: { verb: "Approved as a free member", forever: true },
      });
    } else if (key === "grant") {
      confirmAction({
        title: "Grant 7-day tester access",
        intro: [`${who} gets 7 days of early access with no card. It uses one of the 20 tester places.`,
                "You get a login code to send them."],
        label: "Grant 7-day tester",
        run: () => adminPost("/admin/testers", { user_id: row.id }),
        plan: { verb: "Tester access granted", forever: false },
      });
    } else if (key === "extend") {
      confirmAction({
        title: "Extend tester access",
        intro: [`Another 7 days for ${who}, because feedback earned it. This issues a new login code; older ones keep their own end date.`],
        fields: [{ key: "reason", label: "What feedback earned the extension?", type: "textarea", required: true,
                   requiredMessage: "say what feedback earned it", hint: REASON_NOTE }],
        label: "Extend 7 days",
        run: (v) => adminPost("/admin/testers/extend", { user_id: row.id, reason: v.reason }),
        plan: { verb: "Access extended", forever: false },
      });
    } else if (key === "reissue") {
      confirmAction({
        title: "Re-issue login",
        intro: [`Replaces the login code of ${who}: every older code stops working at once. Their end date does not change.`,
                "Only do this after a reply came from that mailbox confirming the request."],
        fields: [{ key: "reason", label: "What did you verify, and for which ticket?", type: "textarea", required: true,
                   requiredMessage: "say what was verified", hint: REASON_NOTE }],
        label: "Re-issue login",
        run: (v) => adminPost("/admin/users/reissue", { user_id: row.id, reason: v.reason }),
        plan: { verb: "New login code issued", forever: Boolean(row.comp) },
      });
    } else if (key === "revoke") {
      confirmAction({
        title: "Revoke free member",
        intro: [`Ends the free access of ${who} and revokes every login code they have. Their account stays.`],
        fields: [{ key: "reason", label: "Why is the access ending?", type: "textarea", required: true,
                   requiredMessage: "say why the access is ending", hint: REASON_NOTE }],
        label: "Revoke free member", variant: "danger",
        run: (v) => adminPost("/admin/comps/revoke", { user_id: row.id, reason: v.reason }),
        done: () => `Free access revoked for ${who}.`,
      });
    }
  }

  function addPerson() {
    formDialog(hosts.modal, {
      title: "Add a person",
      intro: ["Give someone access by email. A new email creates the account.",
              "A tester gets 7 days; a free member gets access with no end date and needs a reason."],
      fields: [
        { key: "email", label: "Email", type: "email", placeholder: "name@example.com" },
        { key: "reason", label: "Why (needed for free access)", type: "textarea", hint: REASON_NOTE,
          requiredMessage: "say why (it is kept in the log)" },
      ],
      inertTargets: inert, errorText: testerErrorText, onUnauthorized: unauthorized, hook: "admin-add-dialog",
      actions: [
        { label: "Grant 7-day tester", variant: "ghost", hook: "admin-add-tester", requires: ["email"],
          run: async (v) => ({ result: await adminPost("/admin/testers", { email: v.email }),
                               plan: { verb: "Tester access granted", forever: false } }) },
        { label: "Give free access", variant: "primary", hook: "admin-add-free", requires: ["email", "reason"],
          run: async (v) => ({ result: await adminPost("/admin/comps", { email: v.email, reason: v.reason }),
                               plan: { verb: "Free access given", forever: true } }) },
      ],
      onDone: async (out) => {
        showToken(out.result, out.plan);
        await loadAll({ quiet: true });
      },
    });
  }

  async function setSupportStatus(message, status) {
    try {
      await adminPost(`/admin/support/${message.id}/status`, { status });
    } catch (err) {
      if (err && err.status === 401) { rejectToken(); return; }
      toast(hosts.toasts, testerErrorText(err), "bad");
      return;
    }
    try {
      state.data.support = await adminGet(SOURCES.support);
      state.errors.support = null;
    } catch (err) {
      if (err && err.status === 401) { rejectToken(); return; }
      state.errors.support = err;
    }
    ctx.rerenderSupport();
    renderOverview(hosts.hosts.overview, state.data, ctx);
    toast(hosts.toasts, `Message marked ${status}.`, "ok");
  }

  // ---- the one place an access token is shown -------------------------------------------------

  /** `issued` is a response of the admin API that carries `token`. The dialog is sticky (a click
   * outside does not close it) and closing it empties its root, which removes the token from the
   * page. Nothing here stores it. */
  function showToken(issued, plan) {
    const dialog = showDialog(hosts.modal, { title: `${plan.verb}: ${issued.email}`, hook: "admin-token-dialog",
      sticky: true, inertTargets: inert });
    const body = dialog.body;
    body.appendChild(el("p", { class: "adm-dialog__text", "data-hook": "admin-token-summary", text: plan.forever
      ? "This access does not expire; it works until you revoke it."
      : `This access ends ${momentLabel(issued.expires_at)}.` }));
    body.appendChild(el("p", { class: "adm-warning", "data-hook": "admin-token-warning", role: "alert", text:
      "Shown once. This code is not stored and cannot be shown again. Closing this window clears it from the page." }));

    const codeRow = el("div", { class: "adm-field" });
    codeRow.appendChild(el("label", { class: "adm-field__label", for: "adm-token-value", text: "Login code" }));
    const box = el("input", { id: "adm-token-value", type: "text", readonly: "readonly", class: "adm-code",
      value: issued.token, "aria-label": "Access token", autocomplete: "off", "data-hook": "admin-token-value" });
    codeRow.appendChild(box);
    const copy = button("Copy code", { variant: "primary", hook: "admin-token-copy" });
    copy.addEventListener("click", async () => {
      copy.textContent = (await copyText(issued.token)) ? "Copied" : "Copy blocked: select it by hand";
    });
    codeRow.appendChild(copy);
    body.appendChild(codeRow);

    const link = signinUrl();
    const linkRow = el("div", { class: "adm-field" });
    linkRow.appendChild(el("span", { class: "adm-field__label", text: "Sign-in page to send them" }));
    linkRow.appendChild(el("a", { href: link, target: "_blank", rel: "noopener", "data-hook": "admin-token-link", text: link }));
    body.appendChild(linkRow);

    const messageRow = el("div", { class: "adm-field" });
    messageRow.appendChild(el("label", { class: "adm-field__label", for: "adm-token-message", text: "Message, ready to send" }));
    const message = accessMessage(issued, plan);
    const preview = el("textarea", { id: "adm-token-message", readonly: "readonly", rows: "8", class: "adm-code adm-code--message",
      "aria-label": "Message to send", "data-hook": "admin-token-message" });
    preview.value = message;
    preview.textContent = message;
    messageRow.appendChild(preview);
    const copyMessage = button("Copy message", { variant: "ghost", hook: "admin-token-copy-message" });
    copyMessage.addEventListener("click", async () => {
      copyMessage.textContent = (await copyText(message)) ? "Message copied" : "Copy blocked: select it by hand";
    });
    messageRow.appendChild(copyMessage);
    body.appendChild(messageRow);

    dialog.footer.appendChild(button("Done, I have sent it", { variant: "ghost", hook: "admin-token-close", onClick: closeDialog }));
    focusSoon(copy);
  }

  // ---- wiring -------------------------------------------------------------------------------

  hosts.gateForm.addEventListener("submit", (event) => {
    if (event && typeof event.preventDefault === "function") event.preventDefault();
    const token = String(hosts.gateInput.value || "").trim();
    if (!token) {
      hosts.gateMessage.textContent = "Paste the admin token first.";
      hosts.gateMessage.setAttribute("data-tone", "bad");
      focusSoon(hosts.gateInput);
      return;
    }
    setAdminToken(token);
    hosts.gateInput.value = "";
    hosts.gateMessage.textContent = "";
    loadAll();
  });
  hosts.signout.addEventListener("click", signOut);
  hosts.refresh.addEventListener("click", () => { if (getAdminToken()) loadAll({ quiet: true }); });
  for (const item of hosts.nav) {
    item.addEventListener("click", () => go(item.getAttribute("data-route")));
  }
  window.addEventListener("hashchange", () => {
    const route = String(window.location.hash || "").replace(/^#\/?/, "");
    if (ROUTES.includes(route) && route !== state.route) go(route);
  });

  const initial = String(window.location.hash || "").replace(/^#\/?/, "");
  if (ROUTES.includes(initial)) state.route = initial;
  showRoute();
  if (getAdminToken()) loadAll();
  else showGate("");
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
