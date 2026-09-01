/**
 * ADMIN view -- web/admin.html. A structural (zero-aesthetic) ops page
 * over the admin surface: GET /admin/overview, GET /admin/funnel,
 * GET /admin/support, GET /admin/users, POST /admin/support/{id}/status
 * (api/admin.py, api/funnel.py, api/support.py), all gated by
 * `X-Admin-Token` (api/auth.py's `_require_admin`).
 *
 * WHY sessionStorage, NEVER localStorage, FOR THE ADMIN TOKEN
 * -------------------------------------------------------------------
 * web/js/api.js keeps the invite token in localStorage because that
 * client is meant to survive a refresh for an ordinary user across many
 * sessions. The admin token is a different risk shape entirely: it is
 * the one credential in this whole client that can read every user's
 * email (GET /admin/users) and change support-ticket state. localStorage
 * persists indefinitely on whatever machine this page was opened on,
 * with no natural expiry, until something explicitly clears it.
 * sessionStorage dies with the tab/window -- closing this page is enough
 * to end its blast radius, which is the right default for a credential
 * this powerful on a page meant to be opened occasionally, not lived in.
 * Never widen this back to localStorage; a design pass restyling this
 * page does not get to change that decision.
 *
 * WHY THE TOKEN NEVER TOUCHES A URL
 * -------------------------------------------------------------------
 * A URL (including a querystring) ends up in browser history, server
 * access logs, and Referer headers -- all places a bearer credential
 * must never sit. Every call below sends the token as the `X-Admin-Token`
 * request header, exactly as api/auth.py's `_require_admin` expects, and
 * `adminFetch` builds no querystring from it. tests/test_web_structure.py
 * greps this file for a token-in-URL pattern to keep that true.
 *
 * WHY EACH SECTION STAYS IN THE DOM, TOGGLED VIA [hidden]
 * -------------------------------------------------------------------
 * Same reasoning as web/index.html's app shell: a design system attaches
 * a stylesheet to stable elements later, not to markup this module
 * builds and tears down on every load. Sections start `hidden` (the one
 * CSS rule this whole client is allowed, web/index.html's
 * `[hidden]{display:none}` -- but web/admin.html has no <style> of its
 * own, so this file relies on the HTML spec's own default: `hidden` is
 * `display:none` in every browser without any CSS at all) and are
 * un-hidden once real data has actually rendered into them.
 *
 * WHY 401 AND 404 ARE RENDERED AS DISTINCT STATES, NOT ONE "ERROR" BLOB
 * -------------------------------------------------------------------
 * api/auth.py's `_require_admin` docstring is explicit that these mean
 * different things: 404 is "this endpoint does not exist because
 * APP_ADMIN_TOKEN was never set" (an ops/deploy fact, no token would ever
 * work), while 401 is "this endpoint exists and your token is wrong" (a
 * credential problem, a different token might work). Collapsing both into
 * one generic "request failed" message would send Brey looking for a typo
 * in his token when the real problem is that the admin surface was never
 * turned on for this environment, or vice versa.
 */

import { el, clear, renderUnknown, renderAbsent } from "./dom.js";

export const ADMIN_TOKEN_STORAGE_KEY = "aisportsanalysis.admin_token";

export function getAdminToken() {
  try {
    return window.sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) || "";
  } catch (err) {
    // Private-browsing / storage-disabled: treat as "no token" rather
    // than throwing out of every caller.
    return "";
  }
}

export function setAdminToken(token) {
  try {
    window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token);
  } catch (err) {
    // Storage unavailable -- the token simply will not persist across a
    // reload; nothing here should crash the page over it.
  }
}

export function clearAdminToken() {
  try {
    window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
  } catch (err) {
    /* see setAdminToken */
  }
}

/** Distinguishes "the server said no, here is the status/detail" from a
 * network failure -- same shape as api.js's ApiError, kept as its own
 * class here rather than imported, since this module's error states
 * (401 vs 404 vs other) are handled differently from every other view's. */
export class AdminApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

/** GET/POST against the admin surface with `X-Admin-Token` attached --
 * never `Authorization`, never a querystring. See module docstring. */
async function adminFetch(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  headers["X-Admin-Token"] = getAdminToken();
  if (options.body !== undefined && headers["Content-Type"] === undefined) {
    headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(path, Object.assign({}, options, { headers }));
  } catch (err) {
    throw new AdminApiError(null, "network request failed: " + err.message);
  }
  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (err) {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = payload && payload.detail !== undefined ? payload.detail : payload;
    throw new AdminApiError(response.status, detail);
  }
  return payload;
}

function adminGet(path) {
  return adminFetch(path, { method: "GET" });
}

function adminPost(path, body) {
  return adminFetch(path, { method: "POST", body: JSON.stringify(body) });
}

function mountTokenForm(host, onSubmit) {
  clear(host);
  const form = el("form", { class: "admin-token-form", "data-hook": "admin-token-form" });
  const label = el("label", { for: "admin-token-input", text: "Admin token" });
  const input = el("input", { type: "password", id: "admin-token-input", name: "token",
    autocomplete: "off", value: getAdminToken(), "data-hook": "admin-token-input" });
  const saveButton = el("button", { type: "submit", text: "Save token" });
  const clearButton = el("button", { type: "button", "data-hook": "admin-clear-token",
    text: "Clear token" });
  const status = el("span", { class: "admin-token-form__status", role: "status",
    "data-hook": "admin-token-form-status" });

  form.appendChild(label);
  form.appendChild(input);
  form.appendChild(saveButton);
  form.appendChild(clearButton);
  form.appendChild(status);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    setAdminToken(input.value.trim());
    status.textContent = "Token saved.";
    onSubmit();
  });
  clearButton.addEventListener("click", () => {
    clearAdminToken();
    input.value = "";
    status.textContent = "Token cleared.";
    onSubmit();
  });

  host.appendChild(form);
}

/** Render the 401/404/other auth-state message, or clear it entirely on
 * success -- see module docstring's "distinct honest states" section. */
function renderAuthState(host, err) {
  clear(host);
  if (err === null) return;
  const section = el("section", { role: "alert", "data-hook": "admin-auth-state" });
  if (err.status === 404) {
    section.setAttribute("data-hook", "admin-auth-disabled");
    section.appendChild(el("p", {
      text: "Admin surface is disabled: APP_ADMIN_TOKEN is not set in "
        + "this environment. No token can work here until it is.",
    }));
  } else if (err.status === 401) {
    section.setAttribute("data-hook", "admin-auth-invalid");
    section.appendChild(el("p", {
      text: "That token was rejected. Enter the current APP_ADMIN_TOKEN "
        + "and save it again.",
    }));
  } else {
    section.setAttribute("data-hook", "admin-auth-error");
    const status = err.status != null ? String(err.status) : "network";
    const detail = err.detail !== undefined ? err.detail : err.message || "request failed";
    section.appendChild(el("p", { text: `Request failed (${status}).` }));
    section.appendChild(typeof detail === "string"
      ? el("p", { text: detail }) : renderUnknown(detail));
  }
  host.appendChild(section);
}

function renderCounts(counts) {
  const dl = el("dl", { class: "admin-counts" });
  for (const [key, value] of Object.entries(counts)) {
    dl.appendChild(el("dt", { text: key }));
    dl.appendChild(el("dd", { text: String(value) }));
  }
  return Object.keys(counts).length ? dl : renderAbsent();
}

/** overview.events.daily_counts_by_kind: {day: {kind: count}}. Rendered
 * as one row per day rather than a fixed kind-per-column table, since
 * events.EVENT_KINDS is not this file's contract to hardcode -- a kind
 * that has never fired on a given day simply has no entry that day,
 * exactly as the API sent it. */
function renderDailyCounts(dailyCounts) {
  const days = Object.keys(dailyCounts).sort();
  if (days.length === 0) return renderAbsent();
  const table = el("table", { class: "admin-daily-counts", "data-hook": "admin-daily-counts" });
  const head = el("tr");
  head.appendChild(el("th", { text: "Date" }));
  head.appendChild(el("th", { text: "Counts by kind" }));
  table.appendChild(el("thead", {}, [head]));
  const body = el("tbody");
  for (const day of days) {
    const row = el("tr");
    row.appendChild(el("td", { text: day }));
    row.appendChild(el("td", {}, [renderCounts(dailyCounts[day])]));
    body.appendChild(row);
  }
  table.appendChild(body);
  return table;
}

/** apphealth.report()'s per-store shape (present/rows/newest_row_age_
 * seconds/newest_row_utc/status/reason) -- `reason` is rendered verbatim,
 * never paraphrased (this task's brief: "store health with degraded
 * reasons verbatim"). */
function renderStoreCheck(name, check) {
  const dl = el("dl", { class: "admin-store-check", "data-hook": "admin-store-check",
    "data-store-name": name });
  for (const key of ["present", "rows", "newest_row_age_seconds", "newest_row_utc",
                     "status", "reason"]) {
    dl.appendChild(el("dt", { text: key }));
    dl.appendChild(el("dd", {}, [check[key] === null || check[key] === undefined
      ? renderAbsent() : document.createTextNode(String(check[key]))]));
  }
  return dl;
}

function renderStoreHealth(storeHealth) {
  const wrap = el("div", { "data-hook": "admin-store-health" });
  wrap.appendChild(el("p", { text: `Status: ${storeHealth.status}` }));
  wrap.appendChild(el("p", { text: `Generated at: ${storeHealth.generated_at}` }));

  const reasonsHeading = el("h4", { text: "Reasons" });
  wrap.appendChild(reasonsHeading);
  if (storeHealth.reasons && storeHealth.reasons.length) {
    const list = el("ul", { "data-hook": "admin-store-health-reasons" });
    for (const reason of storeHealth.reasons) {
      // Verbatim -- see function docstring. No paraphrase, no truncation.
      list.appendChild(el("li", { text: reason }));
    }
    wrap.appendChild(list);
  } else {
    wrap.appendChild(el("p", { "data-hook": "admin-store-health-reasons", text: "None." }));
  }

  wrap.appendChild(el("h4", { text: "App DB" }));
  wrap.appendChild(renderUnknown(storeHealth.app_db));

  wrap.appendChild(el("h4", { text: "Odds store" }));
  for (const [name, check] of Object.entries(storeHealth.odds || {})) {
    wrap.appendChild(renderStoreCheck(name, check));
  }

  wrap.appendChild(el("h4", { text: "Forward captures" }));
  for (const [name, check] of Object.entries(storeHealth.forward_captures || {})) {
    wrap.appendChild(renderStoreCheck(name, check));
  }

  return wrap;
}

function renderOverview(host, overview) {
  clear(host);
  const wrap = el("div", { "data-hook": "admin-overview" });

  wrap.appendChild(el("h3", { text: "Users" }));
  const users = overview.users || {};
  wrap.appendChild(el("p", { text: `Total: ${users.total}` }));
  wrap.appendChild(el("h4", { text: "By status" }));
  wrap.appendChild(renderCounts(users.by_status || {}));
  wrap.appendChild(el("h4", { text: "By plan" }));
  wrap.appendChild(renderCounts(users.by_plan || {}));

  wrap.appendChild(el("p", { "data-hook": "admin-invites-outstanding",
    text: `Invites outstanding: ${overview.invites_outstanding}` }));

  wrap.appendChild(el("h3", { text: "Events (last 14 days)" }));
  wrap.appendChild(renderDailyCounts((overview.events || {}).daily_counts_by_kind || {}));

  wrap.appendChild(el("h3", { text: "Store health" }));
  wrap.appendChild(renderStoreHealth(overview.store_health || {}));

  wrap.appendChild(el("p", { "data-hook": "admin-version", text: `Version: ${overview.version}` }));

  host.appendChild(wrap);
}

function renderFunnel(host, funnel) {
  clear(host);
  const wrap = el("div", { "data-hook": "admin-funnel" });
  wrap.appendChild(el("p", { text: `${funnel.start} to ${funnel.end}` }));
  const table = el("table", { class: "admin-funnel-table", "data-hook": "admin-funnel-table" });
  const head = el("tr");
  head.appendChild(el("th", { text: "Step" }));
  head.appendChild(el("th", { text: "Count" }));
  head.appendChild(el("th", { text: "Conversion % from previous" }));
  table.appendChild(el("thead", {}, [head]));
  const body = el("tbody");
  for (const step of funnel.steps || []) {
    const row = el("tr", { "data-hook": "admin-funnel-step", "data-step": step.kind });
    row.appendChild(el("td", { text: step.kind }));
    row.appendChild(el("td", { text: String(step.count) }));
    row.appendChild(el("td", { text: step.conversion_pct_from_previous === null
      ? "—" : `${step.conversion_pct_from_previous}%` }));
    body.appendChild(row);
  }
  table.appendChild(body);
  wrap.appendChild(table);
  host.appendChild(wrap);
}

// support_store.VALID_STATUSES -- kept here as the fixed set of buttons a
// triage operator can move a message to, not re-derived from the message
// itself (a message's CURRENT status is always excluded from its own
// button row below, so there is never a button that is a no-op).
const SUPPORT_STATUSES = ["open", "answered", "closed"];

function renderSupportMessage(message, onStatusChange) {
  const item = el("li", { class: "admin-support-message", "data-hook": "admin-support-message",
    "data-message-id": String(message.id), "data-status": message.status });
  const dl = el("dl");
  dl.appendChild(el("dt", { text: "Subject" }));
  dl.appendChild(el("dd", { text: message.subject }));
  dl.appendChild(el("dt", { text: "Body" }));
  dl.appendChild(el("dd", { text: message.body }));
  dl.appendChild(el("dt", { text: "From" }));
  dl.appendChild(el("dd", { text: message.email || (message.user_id != null
    ? `user #${message.user_id}` : "unknown") }));
  dl.appendChild(el("dt", { text: "Status" }));
  dl.appendChild(el("dd", { "data-hook": "admin-support-message-status", text: message.status }));
  dl.appendChild(el("dt", { text: "Created" }));
  dl.appendChild(el("dd", { text: message.created_at }));
  dl.appendChild(el("dt", { text: "Answered" }));
  dl.appendChild(el("dd", {}, [message.answered_at ? document.createTextNode(message.answered_at)
    : renderAbsent()]));
  item.appendChild(dl);

  const actions = el("p", { class: "admin-support-message__actions" });
  for (const status of SUPPORT_STATUSES) {
    if (status === message.status) continue;
    const button = el("button", { type: "button", "data-hook": "admin-support-status-button",
      "data-target-status": status, text: `Mark ${status}` });
    button.addEventListener("click", () => onStatusChange(message.id, status));
    actions.appendChild(button);
  }
  item.appendChild(actions);
  return item;
}

async function renderSupportInbox(host) {
  clear(host);
  const wrap = el("div", { "data-hook": "admin-support" });
  const statusRegion = el("p", { role: "status", "data-hook": "admin-support-status" });
  const listHost = el("ul", { class: "admin-support-list", "data-hook": "admin-support-list" });
  wrap.appendChild(statusRegion);
  wrap.appendChild(listHost);
  host.appendChild(wrap);

  async function reload() {
    clear(listHost);
    let result;
    try {
      result = await adminGet("/admin/support");
    } catch (err) {
      renderAuthState(statusRegion, err);
      return;
    }
    clear(statusRegion);
    const messages = result.messages || [];
    if (messages.length === 0) {
      listHost.appendChild(el("li", { text: "No support messages." }));
      return;
    }
    for (const message of messages) {
      listHost.appendChild(renderSupportMessage(message, async (id, status) => {
        try {
          await adminPost(`/admin/support/${id}/status`, { status });
        } catch (err) {
          renderAuthState(statusRegion, err);
          return;
        }
        await reload();
      }));
    }
  }

  await reload();
}

function renderUsers(host, users) {
  clear(host);
  const table = el("table", { class: "admin-users-table", "data-hook": "admin-users-table" });
  const head = el("tr");
  for (const column of ["id", "email", "status", "plan", "created_at"]) {
    head.appendChild(el("th", { text: column }));
  }
  table.appendChild(el("thead", {}, [head]));
  const body = el("tbody");
  for (const user of users) {
    const row = el("tr", { "data-hook": "admin-user-row", "data-user-id": String(user.id) });
    for (const column of ["id", "email", "status", "plan", "created_at"]) {
      row.appendChild(el("td", { text: String(user[column]) }));
    }
    body.appendChild(row);
  }
  table.appendChild(body);
  host.appendChild(table);
}

async function loadAdmin(hosts) {
  clear(hosts.authState);
  for (const section of [hosts.overviewSection, hosts.funnelSection,
                         hosts.supportSection, hosts.usersSection]) {
    section.hidden = true;
  }

  let overview;
  try {
    overview = await adminGet("/admin/overview");
  } catch (err) {
    renderAuthState(hosts.authState, err);
    return;
  }
  renderOverview(hosts.overviewHost, overview);
  hosts.overviewSection.hidden = false;

  try {
    const funnel = await adminGet("/admin/funnel");
    renderFunnel(hosts.funnelHost, funnel);
    hosts.funnelSection.hidden = false;
  } catch (err) {
    renderAuthState(hosts.funnelHost, err);
    hosts.funnelSection.hidden = false;
  }

  try {
    await renderSupportInbox(hosts.supportHost);
    hosts.supportSection.hidden = false;
  } catch (err) {
    renderAuthState(hosts.supportHost, err);
    hosts.supportSection.hidden = false;
  }

  try {
    const usersResult = await adminGet("/admin/users");
    renderUsers(hosts.usersHost, usersResult.users || []);
    hosts.usersSection.hidden = false;
  } catch (err) {
    renderAuthState(hosts.usersHost, err);
    hosts.usersSection.hidden = false;
  }
}

function boot() {
  const hosts = {
    authState: document.querySelector("[data-hook='admin-auth-state-host']"),
    overviewSection: document.querySelector("[data-hook='admin-overview-section']"),
    overviewHost: document.querySelector("[data-hook='admin-overview-host']"),
    funnelSection: document.querySelector("[data-hook='admin-funnel-section']"),
    funnelHost: document.querySelector("[data-hook='admin-funnel-host']"),
    supportSection: document.querySelector("[data-hook='admin-support-section']"),
    supportHost: document.querySelector("[data-hook='admin-support-host']"),
    usersSection: document.querySelector("[data-hook='admin-users-section']"),
    usersHost: document.querySelector("[data-hook='admin-users-host']"),
  };
  const tokenFormHost = document.querySelector("[data-hook='admin-token-form-host']");

  mountTokenForm(tokenFormHost, () => loadAdmin(hosts));
  if (getAdminToken()) {
    loadAdmin(hosts);
  }
}

document.addEventListener("DOMContentLoaded", boot);
