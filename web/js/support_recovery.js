/**
 * SUPPORT RECOVERY, the browser half: what the checkout success page
 * (#/signup/complete) shows a person who comes back without a session id or
 * whose token the server no longer hands out (docs/billing/RECOVERY_PROCEDURE.md).
 *
 * It lives here and not in signup.js on purpose: signup.js draws the PUBLIC
 * signup form, whose answer for a tester's email must never carry or read an end
 * date (tests/test_expired_tester_paid_path.py pins that file-wide). Everything
 * in this module runs only for a person who HOLDS a token and has asked the
 * server about it, so showing that token's own end date is fine.
 *
 * The decision rests on one cheap authed read, GET /billing/status. See
 * checkStoredToken for the four answers.
 */

import { apiGet, ApiError } from "./api.js";
import { el } from "./dom.js";
import {
  testerEndedLine, loadTesterBilling, TESTER_NOT_OPEN, TESTER_REPLY,
} from "./checkout.js";
import { TESTER_ACCESS_EXPIRED } from "./signin.js";

/**
 * What the server says about the token this browser holds, by the one cheap
 * authed read that tells the cases apart (api/billing.py GET /billing/status;
 * it is deliberately not behind the paid gate, so a lapsed subscriber reads 200):
 *
 *   200                              -> {kind: "valid", billing}   a known account
 *   401 tester_access_expired        -> {kind: "expired", endedAt} known, week over
 *   any other 401 (unknown, revoked,
 *     suspended)                     -> {kind: "unknown"}
 *   a dropped connection, a timeout,
 *     a 5xx, a 429                   -> {kind: "unreachable"}      NOT an answer
 *
 * Only "unknown" may clear the token: an outage must never sign a paying
 * customer out.
 */
export async function checkStoredToken() {
  try {
    const billing = await apiGet("/billing/status");
    return { kind: "valid", billing };
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const detail = err.detail;
      if (detail && typeof detail === "object" && detail.error === TESTER_ACCESS_EXPIRED) {
        return { kind: "expired", endedAt: detail.expires_at || null };
      }
      return { kind: "unknown" };
    }
    return { kind: "unreachable" };
  }
}

function helpLinks(card) {
  card.appendChild(el("a", { class: "btn btn--primary btn--full chamfer chamfer--btn",
    href: "#/signin", "data-hook": "signup-signin-link", text: "Sign in with your token" }));
  card.appendChild(el("a", { class: "btn btn--ghost btn--full chamfer chamfer--btn",
    href: "#/support", "data-hook": "signup-support-link", text: "Get help" }));
}

/**
 * THE ONE RECOVERABLE STATE every dead end on this page now ends in: no token on
 * this device, the token was refused, or the checkout link gave nothing back.
 * It never says the link was wrong (the old "No token was included in this
 * link"); it says what is true (this device has no working token), that a
 * purchase or trial is not lost with it, and the two ways on. A buyer's token
 * can only be re-issued by support, so "Get help" leads to the page that says
 * what to send (web/js/support.js).
 */
export function renderSignedOut(card, { cleared = false, lead = null } = {}) {
  card.appendChild(el("h1", { class: "signup-card__title", text: "You're not signed in here." }));
  card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "signup-signed-out",
    text: (lead ? lead + " " : "")
      + (cleared ? "This device's saved token is no longer accepted, so it has been removed. " : "")
      + "Your purchase or trial is not lost: it belongs to your account, not to this browser. "
      + "Sign in with your access token, or get help and we will send you a new one." }));
  helpLinks(card);
}

export function renderUnreachable(card, retry) {
  card.appendChild(el("h1", { class: "signup-card__title", text: "We could not check your sign-in." }));
  card.appendChild(el("p", { class: "signup-card__notice signup-card__notice--warn",
    "data-hook": "signup-check-failed", text:
    "We could not check your access token just now. Your token is still saved on this device. "
    + "Try again in a moment." }));
  const button = el("button", { type: "button", class: "btn btn--primary btn--full chamfer chamfer--btn",
    "data-hook": "signup-check-retry", text: "Try again" });
  button.addEventListener("click", retry);
  card.appendChild(button);
  card.appendChild(el("a", { class: "btn btn--ghost btn--full chamfer chamfer--btn",
    href: "#/support", "data-hook": "signup-support-link", text: "Get help" }));
}

/** An EXPIRED tester: the real state, and the upgrade path that already exists
 * (the sign-in page reads the stored token and offers checkout when it is on). */
export async function renderTesterEnded(card, endedAt) {
  const { knownNotOpen } = await loadTesterBilling();
  card.appendChild(el("h1", { class: "signup-card__title", text: "Your early access has ended." }));
  card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "tester-ended-line",
    text: testerEndedLine(endedAt) }));
  card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "tester-not-open",
    text: knownNotOpen ? TESTER_NOT_OPEN : TESTER_REPLY }));
  card.appendChild(el("a", { class: "btn btn--primary btn--full chamfer chamfer--btn",
    href: "#/signin", "data-hook": "signup-signin-link", text: "Open the sign-in page" }));
  card.appendChild(el("a", { class: "btn btn--ghost btn--full chamfer chamfer--btn",
    href: "#/support", "data-hook": "signup-support-link", text: "Get help" }));
}

/** True for a subscription record whose paid period is over: the page says so
 * and points at billing instead of promising a card the paid gate will refuse. */
function billingLapsed(billing) {
  if (!billing || typeof billing !== "object") return false;
  const end = new Date(billing.current_period_end || "");
  return !Number.isNaN(end.getTime()) && end.getTime() <= Date.now();
}

export function renderValidated(card, billing, appLink) {
  card.appendChild(el("h1", { class: "signup-card__title", text: "You're signed in." }));
  card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "signup-already-signed-in", text:
    "This device is signed in and your access token checks out, so there is nothing more to do here." }));
  if (billingLapsed(billing)) {
    card.appendChild(el("p", { class: "signup-card__notice signup-card__notice--warn",
      "data-hook": "signup-billing-lapsed", text:
      "Your paid period has ended, so the board is closed until you renew. Billing shows where things stand." }));
    card.appendChild(el("a", { class: "btn btn--primary btn--full chamfer chamfer--btn",
      href: "#/billing", "data-hook": "signup-billing-link", text: "Open billing" }));
  }
  card.appendChild(appLink());
}
