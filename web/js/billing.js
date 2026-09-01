/**
 * BILLING view -- GET /billing/status (api/billing.py). This is the
 * landing target for the 402 {"error":"subscription_expired"} state
 * every game-surface view renders via dom.renderError (see that module).
 * It does not attempt checkout here -- api/appstate/billing wiring is a
 * separate lane's surface; this view only shows the account's own
 * billing status verbatim and a link back into the app.
 */

import { apiGet } from "./api.js";
import { el, clear, renderUnknown, renderError } from "./dom.js";

export async function renderBilling(container) {
  clear(container);
  const section = el("section", { class: "view", "data-view": "billing" });
  section.appendChild(el("h1", { class: "view__title", text: "Billing" }));
  container.appendChild(section);

  const loading = el("div", { class: "state-loading panel chamfer",
    "data-hook": "view-loading" },
    [el("p", { class: "state-loading__figure", text: "Loading billing status…" })]);
  section.appendChild(loading);

  let payload;
  try {
    payload = await apiGet("/billing/status");
  } catch (err) {
    renderError(container, err);
    return;
  }
  clear(loading);
  loading.remove();

  const body = el("section", { class: "section-block panel chamfer",
    "data-hook": "billing-status" });
  body.appendChild(el("h2", { text: "Status" }));
  body.appendChild(renderUnknown(payload));
  section.appendChild(body);

  section.appendChild(el("a", { href: "#/today", class: "btn btn--ghost",
    "data-hook": "back-to-app", text: "Back to the app" }));
}
