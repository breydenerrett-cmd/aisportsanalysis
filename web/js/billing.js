/**
 * BILLING view -- GET /billing/status, POST /billing/checkout,
 * POST /billing/cancel, POST /billing/reactivate (api/billing.py).
 *
 * WHY THIS VIEW WAS REWRITTEN (2026-09-10)
 * -------------------------------------------------------------------
 * The previous version rendered `renderUnknown(payload)` -- the raw status
 * JSON -- and its own docstring said it "does not attempt checkout here."
 * Meanwhile api/billing.py has had a complete, allowlisted, rate-limited
 * checkout endpoint the whole time. So the server could take money and the
 * product had no button that asked for it: this view WAS the reason nobody
 * could subscribe, and it is the landing target every paid surface sends a
 * 402 to. A customer who hit the paywall arrived here, read a JSON object,
 * and left.
 *
 * WHAT IT STILL REFUSES TO DO
 * -------------------------------------------------------------------
 * No card fields, ever. Checkout hands back a Stripe-hosted URL and this
 * redirects to it; card data never touches this origin. And every state
 * below is rendered from what the API actually returned -- a
 * `not_configured` deploy says so plainly rather than showing a Subscribe
 * button that would fail on click, because a checkout button that cannot
 * check out is the billing dishonesty this product exists to reject.
 *
 * FRESHNESS
 * -------------------------------------------------------------------
 * GET /billing/status reads a local table fed by verified Stripe webhooks,
 * never a live Stripe call (see that endpoint's docstring). It is therefore
 * at most as fresh as the last webhook delivery, and `updated_at` is shown
 * so a customer can see that lag rather than be told a stale answer is
 * current. Cancel and reactivate write through locally, so those two are
 * correct immediately regardless of webhook timing.
 */

import { apiGet, apiPost } from "./api.js";
import { el, clear, renderError } from "./dom.js";
import { BETA_TIER } from "./pricing.js";

const STATUS_NOT_CONFIGURED = "not_configured";
const STATUS_REDIRECT = "redirect";
const STATUS_ERROR = "error";

/** Stripe's own subscription words, in the customer's words. */
const STATUS_COPY = {
  active: "Active",
  trialing: "Trial",
  past_due: "Payment failed",
  unpaid: "Payment failed",
  canceled: "Ended",
  incomplete: "Not finished",
  incomplete_expired: "Not finished",
};

/** Statuses where the next charge will NOT simply happen on schedule. */
const NOT_RENEWING = new Set(["past_due", "unpaid", "canceled",
  "incomplete", "incomplete_expired"]);

function statusLine(status) {
  return STATUS_COPY[status] || status;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * A billing date, in UTC, deliberately NOT through dom.js's
 * formatEasternDate.
 *
 * Every other date in this app describes a baseball game, which happens at a
 * wall-clock time in a US timezone, so Eastern is right there. A billing
 * period boundary is a Stripe timestamp, and Stripe returns them at UTC
 * midnight -- which formatEasternDate renders as the PREVIOUS DAY, four or
 * five hours earlier. Caught by reading the rendered output rather than the
 * code: `current_period_end: 2026-10-09T00:00:00Z` displayed as "OCT 8",
 * telling a paying customer their access ended a day before it does.
 */
function whenText(iso) {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${MONTHS[at.getUTCMonth()]} ${at.getUTCDate()}, `
    + `${at.getUTCFullYear()}`;
}

function panel(hook) {
  return el("section", { class: "section-block panel chamfer",
    "data-hook": hook });
}

function note(text, tone) {
  return el("p", { class: tone ? `billing__note billing__note--${tone}`
                                : "billing__note", text });
}

/**
 * Disable a button for the duration of an async call. A double-clicked
 * Subscribe would open two checkout sessions; cancel and reactivate are
 * idempotent per the provider protocol, but a second click still races the
 * re-render underneath it.
 */
async function whileBusy(button, busyText, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = busyText;
  try {
    return await fn();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function renderSubscribe(section, container) {
  // NOT "billing-subscribe" -- that hook belongs to the button below, and a
  // panel sharing it wins every querySelector because it comes first in the
  // document. The click then lands on a <section>, which does nothing at all:
  // no request, no navigation, no error. Found by clicking the rendered
  // button, not by reading the code or the passing tests.
  const body = panel("billing-subscribe-panel");
  body.appendChild(el("h2", { text: BETA_TIER.name }));
  body.appendChild(el("p", { class: "billing__price",
    "data-price": String(BETA_TIER.price_cents),
    text: BETA_TIER.price_display }));
  body.appendChild(note(BETA_TIER.billing_note));

  const button = el("button", { type: "button", class: "btn btn--primary",
    "data-hook": "billing-subscribe", text: "Subscribe" });
  // Branch-scoped rather than a shared "billing-outcome". renderSubscribe and
  // renderManage never render together today, so a shared hook would work --
  // right up until they do, at which point it fails the same silent way the
  // panel/button collision above did. Distinct names cost nothing.
  const outcome = el("div", { "data-hook": "billing-subscribe-outcome" });

  button.addEventListener("click", async () => {
    clear(outcome);
    let payload;
    try {
      payload = await whileBusy(button, "Opening checkout…",
        () => apiPost("/billing/checkout", { plan_id: BETA_TIER.id }));
    } catch (err) {
      renderError(outcome, err);
      return;
    }
    if (payload && payload.status === STATUS_REDIRECT && payload.checkout_url) {
      // Stripe-hosted checkout. Card details are entered on Stripe's origin,
      // never this one.
      window.location.assign(payload.checkout_url);
      return;
    }
    // Every non-redirect answer is reported in the API's own words. The
    // endpoint deliberately returns 200 with a status field rather than an
    // HTTP error for these (docs/LAUNCH_DECISIONS.md Decision 2), so they
    // arrive here rather than through renderError.
    if (payload && payload.status === STATUS_NOT_CONFIGURED) {
      outcome.appendChild(note(
        payload.message
        || "Payments are not switched on for this deployment yet.", "warn"));
      return;
    }
    if (payload && payload.status === STATUS_ERROR) {
      outcome.appendChild(note(
        payload.message || "Checkout could not be started; try again shortly.",
        "warn"));
      return;
    }
    outcome.appendChild(note(
      "Checkout did not return a payment link. Nothing has been charged.",
      "warn"));
  });

  body.appendChild(button);
  body.appendChild(outcome);
  section.appendChild(body);
}

function renderManage(section, container, payload) {
  const body = panel("billing-status");
  body.appendChild(el("h2", { text: "Your subscription" }));

  const row = el("p", { class: "billing__status" });
  row.appendChild(el("strong", { "data-hook": "billing-state",
    text: statusLine(payload.status) }));
  body.appendChild(row);

  const scheduledEnd = whenText(payload.cancel_at);
  const paidThrough = whenText(payload.current_period_end);

  if (scheduledEnd) {
    // Cancel is a SCHEDULED cancel: access continues to the paid-through
    // date. Saying "cancelled" flat would misdescribe a customer who still
    // has weeks left, which is exactly what the endpoint refuses to do.
    body.appendChild(note(
      `Renewal is off. Your access continues through ${paidThrough
       || scheduledEnd}.`));
  } else if (paidThrough && NOT_RENEWING.has(payload.status)) {
    // "Payment failed / Renews Sep 19" is a contradiction, and the reassuring
    // half is the false half. On a failed payment the date is how long the
    // access already paid for lasts, not a promise of another charge.
    body.appendChild(note(
      `Your access runs through ${paidThrough}. Renewal needs a working `
      + `payment method.`, "warn"));
  } else if (paidThrough) {
    body.appendChild(note(`Renews ${paidThrough}.`));
  }

  if (payload.updated_at) {
    body.appendChild(note(
      `Last confirmed by our payment provider ${whenText(payload.updated_at)}.`,
      "quiet"));
  }

  const outcome = el("div", { "data-hook": "billing-manage-outcome" });
  const action = scheduledEnd
    ? { path: "/billing/reactivate", label: "Resume renewal",
        busy: "Resuming…", hook: "billing-reactivate" }
    : { path: "/billing/cancel", label: "Cancel renewal",
        busy: "Cancelling…", hook: "billing-cancel" };

  const button = el("button", { type: "button", class: "btn btn--ghost",
    "data-hook": action.hook, text: action.label });
  button.addEventListener("click", async () => {
    clear(outcome);
    let result;
    try {
      result = await whileBusy(button, action.busy,
        () => apiPost(action.path, {}));
    } catch (err) {
      renderError(outcome, err);
      return;
    }
    if (result && result.status === STATUS_ERROR) {
      outcome.appendChild(note(
        result.message || "That could not be completed; try again shortly.",
        "warn"));
      return;
    }
    // Both endpoints write through locally, so a re-read reflects the change
    // immediately rather than waiting on webhook delivery.
    renderBilling(container);
  });

  body.appendChild(button);
  body.appendChild(outcome);
  section.appendChild(body);
}

export async function renderBilling(container) {
  clear(container);
  const section = el("section", { class: "view", "data-view": "billing" });
  section.appendChild(el("h1", { class: "view__title", text: "Billing" }));
  container.appendChild(section);

  const loading = el("div", { class: "state-loading panel chamfer",
    "data-hook": "view-loading" },
    [el("p", { class: "state-loading__figure",
      text: "Loading billing status…" })]);
  section.appendChild(loading);

  let payload;
  try {
    payload = await apiGet("/billing/status");
  } catch (err) {
    renderError(container, err);
    return;
  }
  loading.remove();

  // `not_configured` means no webhook has ever reported a subscription for
  // this account -- which is the state of every prospective customer, so it
  // is the SUBSCRIBE state, not an error state.
  if (!payload || payload.status === STATUS_NOT_CONFIGURED) {
    renderSubscribe(section, container);
  } else {
    renderManage(section, container, payload);
  }

  section.appendChild(el("a", { href: "#/today", class: "btn btn--ghost",
    "data-hook": "back-to-app", text: "Back to the app" }));
}
