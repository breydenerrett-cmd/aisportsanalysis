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
 *
 * VISUAL REBUILD (2026-09-06, UI/UX pass)
 * -------------------------------------------------------------------
 * The old markup was a bare <dl> + unstyled <input> -- 15 DOM nodes on a
 * dark page with nothing designed about it. This rebuild keeps every
 * data-hook and every branch of submit handling byte-for-byte (tests pin
 * them and a concurrent lane owns api/signup.py's contract), and adds
 * nothing but a centered premium card around the same mechanics. Styling
 * lives in web/css/signup.css only -- screens.css stays untouched, per
 * this lane's file ownership. Headline/subhead/benefit copy is drawn
 * from web/landing.html's own hero meta description and "why we built
 * this" / "find the better number" / "paper trail" sections (see comments
 * inline) and from api/meta.py's PRODUCT_ONE_LINER -- nothing here is a
 * new claim.
 */

import { apiGet, apiPost, trackFunnelEvent, ApiError } from "./api.js";
import { el, clear, renderError } from "./dom.js";
import { BETA_TIER } from "./pricing.js";

// Substance only -- no new claims. Each line restates something the
// product already says elsewhere (web/landing.html's "why we built this",
// "find the better number" and "paper trail" sections; api/meta.py's
// PRODUCT_ONE_LINER), just made scannable as bullets on the access card.
const BENEFITS = [
  "Every matchup priced against a de-vigged, multi-book consensus — not one line, not one book.",
  "A verdict on the price, never a tip — whether the number is good, not what to bet.",
  "Every pick frozen before first pitch, so there's no shopping the call after it's made.",
  "Paper results published win or lose — the record is checkable, not curated.",
];

function renderPricingBadge() {
  const wrap = el("div", {
    class: "signup-card__tier", "data-hook": "pricing-tier",
    "data-price": String(BETA_TIER.price_cents),
  });
  const badge = el("span", { class: "badge badge--money chamfer chamfer--chip signup-card__tier-badge" });
  badge.appendChild(el("span", { "data-hook": "pricing-tier-name", text: BETA_TIER.name }));
  badge.appendChild(el("span", { class: "signup-card__tier-sep", "aria-hidden": "true", text: "·" }));
  badge.appendChild(el("span", { "data-hook": "pricing-tier-price", text: BETA_TIER.price_display }));
  wrap.appendChild(badge);
  wrap.appendChild(el("p", {
    class: "signup-card__tier-note", "data-hook": "pricing-tier-note", text: BETA_TIER.billing_note,
  }));
  return wrap;
}

function renderBenefits() {
  const list = el("ul", { class: "signup-card__benefits", "data-hook": "signup-benefits" });
  for (const line of BENEFITS) {
    list.appendChild(el("li", { text: line }));
  }
  return list;
}

export async function renderSignup(main) {
  clear(main);
  const wrap = el("section", { class: "signup", "data-view": "signup", "aria-label": "signup" });
  const card = el("div", { class: "signup-card panel chamfer chamfer--lg" });

  card.appendChild(el("p", { class: "eyebrow eyebrow--money signup-card__eyebrow", text: "FOUNDING BETA ACCESS" }));
  // Headline is the site's own <title> line (web/landing.html); subhead is
  // that page's <meta name="description"> verbatim.
  card.appendChild(el("h1", { class: "signup-card__title", text: "Check your bet before you fire." }));
  card.appendChild(el("p", { class: "signup-card__subhead", text:
    "See the actual price, the market-implied consensus, and what changed — for one bet you're about to make." }));

  card.appendChild(renderPricingBadge());
  card.appendChild(renderBenefits());

  const form = el("form", { class: "signup-card__form", "data-hook": "signup-form" });
  const field = el("div", { class: "signup-card__field" });
  field.appendChild(el("label", { for: "signup-email-input", text: "Email" }));
  const input = el("input", {
    type: "email", id: "signup-email-input", name: "email", required: "required",
    placeholder: "you@example.com", autocomplete: "email",
    class: "signup-card__input", "data-hook": "signup-email-input",
  });
  field.appendChild(input);
  form.appendChild(field);
  form.appendChild(el("button", {
    type: "submit", class: "btn btn--primary btn--full btn--lg chamfer chamfer--btn",
    text: "Request beta access",
  }));
  const status = el("p", { class: "signup-card__status", role: "status", "data-hook": "signup-status" });
  form.appendChild(status);
  card.appendChild(form);

  const resultHost = el("div", { class: "signup-card__result", "data-hook": "signup-result" });
  card.appendChild(resultHost);

  // Reuses the disclaimer language already established for this beta
  // (src/analysis/disclaimers.py's BETA_DISCLAIMER, surfaced app-wide by
  // meta.js's shared footer, which is mounted on every route including
  // this one) rather than writing new legal-ish copy here.
  card.appendChild(el("p", { class: "signup-card__trust", "data-hook": "signup-trust", text:
    "Paper results only, not betting advice — 21+. Full beta disclaimer below." }));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "Submitting...";
    clear(resultHost);
    try {
      const result = await apiPost("/signup", { email: input.value.trim() });
      status.textContent = "";
      if (result && result.checkout && result.checkout.checkout_url) {
        resultHost.appendChild(el("p", { class: "signup-card__notice signup-card__notice--go", "data-hook": "signup-checkout-link" },
          [el("a", { class: "btn btn--primary btn--full chamfer chamfer--btn", href: result.checkout.checkout_url, text: "Continue to checkout" })]));
      } else if (result && result.status === "waitlisted") {
        resultHost.appendChild(el("p", {
          class: "signup-card__notice signup-card__notice--info",
          "data-hook": "signup-waitlisted",
          text: "You're on the waitlist. We'll email you when a beta spot opens up.",
        }));
      } else {
        resultHost.appendChild(el("p", {
          class: "signup-card__notice signup-card__notice--warn",
          "data-hook": "signup-unrecognized-response",
          text: "The signup request went through, but the response wasn't in the expected shape.",
        }));
      }
    } catch (err) {
      status.textContent = "";
      if (err instanceof ApiError && err.status === 404) {
        resultHost.appendChild(el("p", {
          class: "signup-card__notice signup-card__notice--warn",
          "data-hook": "signup-not-yet-open",
          text: "Signup is not yet open.",
        }));
      } else {
        renderError(resultHost, err);
      }
    }
  });

  wrap.appendChild(card);
  main.appendChild(wrap);
  // Reached the signup step -- see api/funnel.py's PUBLIC_FUNNEL_KINDS.
  trackFunnelEvent("signup_started");
}

export async function renderSignupComplete(main, query) {
  clear(main);
  const wrap = el("section", { class: "signup", "data-view": "signup-complete", "aria-label": "signup complete" });
  const card = el("div", { class: "signup-card panel chamfer chamfer--lg" });
  card.appendChild(el("p", { class: "eyebrow eyebrow--money signup-card__eyebrow", text: "FOUNDING BETA ACCESS" }));
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
      card.appendChild(el("h1", { class: "signup-card__title", text: "Almost there." }));
      wrap.appendChild(card);
      main.appendChild(wrap);
      renderError(main, err);
      return;
    }
  }
  card.appendChild(el("h1", { class: "signup-card__title", text: token ? "You're in." : "Check your link." }));
  if (token) {
    card.appendChild(el("p", { class: "signup-card__subhead", text:
      "Your one-time invite token — copy it now, it will not be shown again:" }));
    card.appendChild(el("code", { class: "signup-card__token", "data-hook": "signup-token", text: token }));
    card.appendChild(el("p", { class: "signup-card__trust", text:
      "Paste it into the \"Invite token\" field on the app's home screen." }));
    card.appendChild(el("a", {
      class: "btn btn--primary btn--full btn--lg chamfer chamfer--btn",
      href: "index.html#/today", "data-hook": "signup-complete-app-link",
      text: "Go to the app",
    }));
  } else {
    card.appendChild(el("p", {
      class: "signup-card__notice signup-card__notice--warn",
      "data-hook": "signup-complete-no-token",
      text: "No token was included in this link.",
    }));
  }
  wrap.appendChild(card);
  main.appendChild(wrap);
}
