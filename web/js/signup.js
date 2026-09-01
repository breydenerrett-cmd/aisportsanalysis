/**
 * SIGNUP view -- POST /signup (a concurrent lane's api/signup.py; this
 * module codes against its documented contract only:
 * `{user_id, checkout: {status, checkout_url}}` on the paid-checkout
 * branch, or `{user_id, status: "waitlisted"}` on the honest waitlist
 * branch -- verified against api/signup.py's actual responses) -- and
 * SIGNUP COMPLETE view, which renders a one-time invite token handed back
 * on the URL (e.g. after a checkout redirect or an admin-issued invite
 * link) with copy instructions and a link back into the app.
 *
 * WHY A 404 RENDERS "signup not yet open", NOT A GENERIC ERROR
 * -------------------------------------------------------------------
 * api/signup.py is being built by a concurrent lane and may not exist in
 * every environment this client runs against yet. A 404 on POST /signup
 * is not the same failure as a 400/500 -- it means the endpoint itself is
 * not live, which is an honest, expected state during rollout, not a bug
 * report. dom.js's renderError still handles every other status.
 *
 * WHY THE PRICE COMES FROM pricing.js, NOT A NUMBER WRITTEN HERE
 * -------------------------------------------------------------------
 * See web/js/pricing.js's own docstring -- this view and web/landing.html
 * both read BETA_TIER so there is exactly one place a price is decided.
 */

import { apiGet, apiPost, trackFunnelEvent, ApiError } from "./api.js";
import { el, clear, renderError } from "./dom.js";
import { BETA_TIER } from "./pricing.js";

function renderTier() {
  const dl = el("dl", {
    class: "signup-tier", "data-hook": "pricing-tier",
    "data-price": String(BETA_TIER.price_cents),
  });
  dl.appendChild(el("dt", { text: "Plan" }));
  dl.appendChild(el("dd", { "data-hook": "pricing-tier-name", text: BETA_TIER.name }));
  dl.appendChild(el("dt", { text: "Price" }));
  dl.appendChild(el("dd", { "data-hook": "pricing-tier-price", text: BETA_TIER.price_display }));
  dl.appendChild(el("dt", { text: "Note" }));
  dl.appendChild(el("dd", { "data-hook": "pricing-tier-note", text: BETA_TIER.billing_note }));
  return dl;
}

export async function renderSignup(main) {
  clear(main);
  const section = el("section", { "data-view": "signup", "aria-label": "signup" });
  section.appendChild(el("h1", { text: "Start the beta" }));
  section.appendChild(renderTier());

  const form = el("form", { "data-hook": "signup-form" });
  form.appendChild(el("label", { for: "signup-email-input", text: "Email" }));
  const input = el("input", {
    type: "email", id: "signup-email-input", name: "email", required: "required",
    "data-hook": "signup-email-input",
  });
  form.appendChild(input);
  form.appendChild(el("button", { type: "submit", text: "Request beta access" }));
  const status = el("p", { role: "status", "data-hook": "signup-status" });
  form.appendChild(status);
  section.appendChild(form);

  const resultHost = el("div", { "data-hook": "signup-result" });
  section.appendChild(resultHost);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "Submitting...";
    clear(resultHost);
    try {
      const result = await apiPost("/signup", { email: input.value.trim() });
      status.textContent = "";
      if (result && result.checkout && result.checkout.checkout_url) {
        resultHost.appendChild(el("p", { "data-hook": "signup-checkout-link" },
          [el("a", { href: result.checkout.checkout_url, text: "Continue to checkout" })]));
      } else if (result && result.status === "waitlisted") {
        resultHost.appendChild(el("p", {
          "data-hook": "signup-waitlisted",
          text: "You're on the waitlist. We'll email you when a beta spot opens up.",
        }));
      } else {
        resultHost.appendChild(el("p", {
          "data-hook": "signup-unrecognized-response",
          text: "The signup request went through, but the response wasn't in the expected shape.",
        }));
      }
    } catch (err) {
      status.textContent = "";
      if (err instanceof ApiError && err.status === 404) {
        resultHost.appendChild(el("p", {
          "data-hook": "signup-not-yet-open",
          text: "Signup is not yet open.",
        }));
      } else {
        renderError(resultHost, err);
      }
    }
  });

  main.appendChild(section);
  // Reached the signup step -- see api/funnel.py's PUBLIC_FUNNEL_KINDS.
  trackFunnelEvent("signup_started");
}

export async function renderSignupComplete(main, query) {
  clear(main);
  const section = el("section", {
    "data-view": "signup-complete", "aria-label": "signup complete",
  });
  section.appendChild(el("h1", { text: "You're in" }));
  let token = (query && query.token) || "";
  // Stripe's hosted Checkout redirects here with `session_id` (see
  // src/appstate/billing.py's success_url), not a token -- there is no
  // email sender yet, so GET /signup/complete is the ONE bridge a paying
  // user has to their own access token (api/signup.py's
  // "no-email-sender activation bridge"). Exchange it here.
  //
  // A failure is reported honestly rather than swallowed into the generic
  // "no token was included in this link" branch below: the token is
  // one-time, so a user who lands here after it was already taken needs to
  // be told that, not left guessing at an empty page.
  const sessionId = (query && query.session_id) || "";
  if (!token && sessionId) {
    try {
      const body = await apiGet(
        "/signup/complete?session_id=" + encodeURIComponent(sessionId));
      token = (body && body.token) || "";
    } catch (err) {
      main.appendChild(section);
      renderError(main, err);
      return;
    }
  }
  if (token) {
    section.appendChild(el("p", {
      text: "Your one-time invite token -- copy it now, it will not be shown again:",
    }));
    section.appendChild(el("code", { "data-hook": "signup-token", text: token }));
    section.appendChild(el("p", {
      text: "Paste it into the \"Invite token\" field on the app's home screen.",
    }));
    section.appendChild(el("a", {
      href: "index.html#/today", "data-hook": "signup-complete-app-link",
      text: "Go to the app",
    }));
  } else {
    section.appendChild(el("p", {
      "data-hook": "signup-complete-no-token",
      text: "No token was included in this link.",
    }));
  }
  main.appendChild(section);
}
