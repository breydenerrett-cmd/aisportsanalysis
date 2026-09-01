/**
 * Minimal DOM-construction and generic-JSON-rendering helpers shared by
 * every view module.
 *
 * WHY A GENERIC JSON RENDERER EXISTS AT ALL
 * -------------------------------------------------------------------
 * docs/API_CONTRACTS.md states plainly that some fields are not yet a
 * stable per-field contract ("dossier": "full internal dossier dump --
 * not yet a stable per-field contract; treat as opaque today"; the same
 * for `sections`/`gaps` on the advanced game view). A structural client
 * cannot hardcode field names inside an opaque blob without becoming the
 * thing that breaks the day that blob's shape changes. `renderUnknown`
 * walks whatever JSON comes back into semantic <dl>/<ul> markup instead
 * of composing a claim about it -- this is display, not interpretation.
 */

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (key === "text") {
      node.textContent = value;
    } else if (key.startsWith("data-") || key.startsWith("aria-")) {
      node.setAttribute(key, value);
    } else {
      node.setAttribute(key, value);
    }
  }
  const kids = Array.isArray(children) ? children : [children];
  for (const child of kids) {
    if (child === undefined || child === null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function clear(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
}

/** A single "value not present" marker. Not a composed claim -- a
 * placeholder for JSON `null`/`undefined`, distinct from any API-supplied
 * unavailability string, which is always rendered verbatim instead. */
export function renderAbsent() {
  return el("span", { class: "value-absent", "data-hook": "value-absent", text: "—" });
}

/** Render any JSON value (object/array/primitive) as semantic markup,
 * for fields the contract does not yet pin field-by-field. See module
 * docstring. */
export function renderUnknown(value) {
  if (value === null || value === undefined) {
    return renderAbsent();
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return renderAbsent();
    const list = el("ul", { class: "raw-list" });
    for (const item of value) {
      list.appendChild(el("li", { class: "raw-list__item" }, [renderUnknown(item)]));
    }
    return list;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 0) return renderAbsent();
    const dl = el("dl", { class: "raw-fields" });
    for (const key of keys) {
      dl.appendChild(el("dt", { class: "raw-fields__key", text: key }));
      dl.appendChild(el("dd", { class: "raw-fields__value" }, [renderUnknown(value[key])]));
    }
    return dl;
  }
  return document.createTextNode(String(value));
}

/** A missing/invalid invite token -- distinct from a generic server error
 * so the reader knows exactly what to do (BOUNDARIES: this client never
 * decides *why* the token is wrong, it only names the state). */
function renderAuthRequired(container, err) {
  const detail = err && err.detail !== undefined ? err.detail : null;
  const section = el("section", {
    class: "auth-required", role: "alert", "data-hook": "auth-required",
  });
  section.appendChild(el("p", { class: "auth-required__title", text: "Sign-in required" }));
  section.appendChild(el("p", { class: "auth-required__body",
    text: "Your invite token is missing or no longer valid. Enter it above to continue." }));
  if (detail) {
    section.appendChild(el("div", { class: "auth-required__detail", "data-hook": "auth-required-detail" },
      [typeof detail === "string" ? document.createTextNode(detail) : renderUnknown(detail)]));
  }
  container.appendChild(section);
}

/** A lapsed subscription (402 {"error":"subscription_expired"}) -- a
 * distinct state from a missing token, with the one honest next step:
 * a link to the billing route (never a client-composed upsell). */
function renderSubscriptionExpired(container) {
  const section = el("section", {
    class: "subscription-expired", role: "alert", "data-hook": "subscription-expired",
  });
  section.appendChild(el("p", { class: "subscription-expired__title", text: "Subscription expired" }));
  section.appendChild(el("p", { class: "subscription-expired__body",
    text: "Your subscription has expired, so this page is not available right now." }));
  section.appendChild(el("a", { href: "#/billing", class: "btn btn--ghost subscription-expired__link",
    "data-hook": "billing-link", text: "Go to billing" }));
  container.appendChild(section);
}

/** Render a fetch/API failure as a semantic status region rather than a
 * blank pane -- BOUNDARIES: never fabricate a message; render the API's
 * own detail verbatim when there is one. 401 and 402-subscription-expired
 * get their own distinct treatment (see above) rather than reading as a
 * generic "request failed" -- and a `null` status (the fetch itself never
 * completed) is worded as "could not be reached" rather than implying the
 * server answered and said no, since those are different failures for the
 * reader even though this client cannot tell local network trouble from a
 * real service outage (docs/OPERATIONS_RUNBOOK.md sect 7). */
export function renderError(container, err) {
  clear(container);
  const status = err && err.status != null ? String(err.status) : "network";
  if (status === "401") {
    renderAuthRequired(container, err);
    return;
  }
  if (status === "402" && err && err.detail && typeof err.detail === "object"
      && err.detail.error === "subscription_expired") {
    renderSubscriptionExpired(container);
    return;
  }
  const detail = err && err.detail !== undefined ? err.detail
    : (err && err.message) || "request failed";
  const section = el("section", {
    class: "view-error state-error", role: "alert", "data-hook": "view-error",
    "data-status": status,
  });
  section.appendChild(el("p", { class: "state-error__title", text: "Request failed" }));
  if (status === "network") {
    section.appendChild(el("p", { class: "state-error__body", text:
      "This page could not reach the server. That could be your own connection or "
      + "a service outage -- it is not the same as the server answering \"no games\"." }));
  } else {
    section.appendChild(el("p", { class: "view-error__status state-error__body", text: `Status: ${status}` }));
  }
  section.appendChild(el("div", { class: "view-error__detail" },
    [typeof detail === "string" ? document.createTextNode(detail) : renderUnknown(detail)]));
  container.appendChild(section);
}
