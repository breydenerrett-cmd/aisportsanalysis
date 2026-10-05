/**
 * SIGNUP view -- POST /signup (a concurrent lane's api/signup.py; this
 * module codes against its documented contract only:
 * `{user_id, checkout: {status, checkout_url}}` on the paid-checkout
 * branch, or `{user_id, status: "waitlisted"}` on the honest waitlist
 * branch, or `{user_id, status: "tester_expired" | "tester_active"}` for an
 * email that belongs to an early-access tester (checkout on or off, never a
 * date, never a checkout link) -- verified against api/signup.py's actual
 * responses) -- and
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

import { apiGet, apiPost, trackFunnelEvent, ApiError, getToken, setToken, clearToken } from "./api.js";
import { attributionPayload, firstTouchProperties } from "./attribution.js";
import { el, clear, renderError } from "./dom.js";
import { BETA_TIER } from "./pricing.js";
import {
  loadCheckoutState, ctaLabel, pricingNote, plannedPrice, monthlyPrice,
  cardRequiredNotice, trialStartedNote, WAITLIST_CONFIRMATION, testerSignupNotice,
  testerEndedLine, loadTesterBilling, TESTER_NOT_OPEN, TESTER_REPLY,
} from "./checkout.js";
import { TESTER_ACCESS_EXPIRED } from "./signin.js";

// Substance only -- no new claims. Each line restates something the
// product already says elsewhere (web/landing.html's "why we built this",
// "find the better number" and "paper trail" sections; api/meta.py's
// PRODUCT_ONE_LINER), just made scannable as bullets on the access card.
// The order is the owner's rule, verbatim: "none of that price matters
// until we know it's a more than likely bet" -- likelihood first, then what
// the price needs. This list used to sell the fair price across every book,
// which is the register he retired.
const BENEFITS = [
  "Each pick starts with who is more likely to win — by the whole market and by our own numbers — then what the price needs to break even.",
  "Every pick published before first pitch; locked at the last price check, so the call doesn't change after that.",
  "Results published win or lose — the record is checkable, not curated.",
  "Player props on the same footing: how often it actually happens first, what the price needs second.",
];

/**
 * The price and trial wording, decided by checkout.js from /meta.
 *
 * Not "on": the planned price and NOTHING else -- no trial, no "cancel
 * anytime", no founding-price story, none of which a visitor can use while
 * nothing can be bought. "on": the badge shows the plan name and the price
 * /meta reports, and the note states the trial only if `trial_days` > 0.
 */
function renderPricingBadge(billing) {
  const wrap = el("div", {
    class: "signup-card__tier", "data-hook": "pricing-tier",
    "data-price": String(BETA_TIER.price_cents),
  });
  if (!billing.on) {
    wrap.appendChild(el("p", {
      class: "signup-card__tier-note", "data-hook": "pricing-tier-note",
      text: plannedPrice(billing) || "",
    }));
    return wrap;
  }
  const badge = el("span", { class: "badge badge--money chamfer chamfer--chip signup-card__tier-badge" });
  badge.appendChild(el("span", { "data-hook": "pricing-tier-name", text: BETA_TIER.name }));
  const price = monthlyPrice(billing.priceCents);
  if (price) {
    badge.appendChild(el("span", { class: "signup-card__tier-sep", "aria-hidden": "true", text: "·" }));
    badge.appendChild(el("span", { "data-hook": "pricing-tier-price", text: price }));
  }
  wrap.appendChild(badge);
  wrap.appendChild(el("p", {
    class: "signup-card__tier-note", "data-hook": "pricing-tier-note", text: pricingNote(billing),
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

/**
 * Whether paying works on this deploy, and the trial and price Checkout is
 * built from: checkout.js's loadCheckoutState (GET /meta `billing`). Unknown
 * (an unreachable /meta) is treated as NOT on: promising a trial the server
 * cannot start is the failure this guards against, and a form that says "not
 * open" on a bad day is the recoverable mistake.
 */
const readBilling = loadCheckoutState;

// The signup page while nothing is on sale: the offer in one sentence, under a
// heading that is checkout.js's own button label (one decision, one file). No
// trial, no price promise.
export const OFF_OFFER = "The first 20 testers get one week of early access, no card. "
  + "Performance is not proven and nothing is on sale yet. Leave your email and, if "
  + "you're picked, your access link comes from Brey.";

export async function renderSignup(main) {
  clear(main);
  const wrap = el("section", { class: "signup", "data-view": "signup", "aria-label": "signup" });
  const card = el("div", { class: "signup-card panel chamfer chamfer--lg" });
  const billing = await readBilling();
  const ctaText = ctaLabel(billing);

  card.appendChild(el("p", { class: "eyebrow eyebrow--money signup-card__eyebrow", text: "FOUNDING BETA ACCESS" }));
  // The heading and the button say the same thing the landing page's button
  // says (checkout.js ctaLabel) -- but ONLY when a checkout exists.
  // With billing off the same words would be a promise nothing can keep, so
  // the form says what is true instead.
  card.appendChild(el("h1", { class: "signup-card__title", "data-hook": "signup-title",
    text: ctaText }));
  card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "signup-kicker",
    text: "Tonight's bets, written down before first pitch." }));
  if (billing.on) {
    card.appendChild(el("p", { class: "signup-card__subhead", text:
      // No count promised (2026-09-21): the card held 7-13 picks a day, not 3-5.
      "Every pick on the card: which side is more likely, what the price needs, and the record of every one — win or lose." }));
    card.appendChild(renderPricingBadge(billing));
    card.appendChild(renderBenefits());
  } else {
    // NOTHING IS ON SALE, SO THE FORM COMES FIRST (2026-10-02). On a phone
    // the email field sat under a page of copy headed "Checkout is not open
    // yet." -- a visitor who had just pressed the early-access button was told
    // no and then asked to scroll. The offer in one sentence, the field, the
    // button; what the product is follows below for anyone who wants it.
    card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "signup-offer",
      text: OFF_OFFER }));
  }

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
  // Before the redirect to Stripe: a card IS required for the trial, and the
  // buyer is told so plainly -- only when checkout is on and there is a trial.
  const cardNotice = cardRequiredNotice(billing);
  if (cardNotice) {
    form.appendChild(el("p", { class: "signup-card__trust", "data-hook": "signup-card-required",
      text: cardNotice }));
  }
  form.appendChild(el("button", {
    type: "submit", class: "btn btn--primary btn--full btn--lg chamfer chamfer--btn",
    "data-hook": "signup-submit",
    text: ctaText,
  }));
  const status = el("p", { class: "signup-card__status", role: "status", "data-hook": "signup-status" });
  form.appendChild(status);
  card.appendChild(form);

  const resultHost = el("div", { class: "signup-card__result", "data-hook": "signup-result" });
  card.appendChild(resultHost);
  if (!billing.on) {
    card.appendChild(renderPricingBadge(billing));
    card.appendChild(renderBenefits());
  }

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
      // First-touch UTM tags + referrer host + the random visitor id ride
      // with the signup so the account, the checkout and the paid event can
      // name the channel (attribution.js; the server re-validates all of it).
      const result = await apiPost("/signup", {
        email: input.value.trim(),
        attribution: attributionPayload(),
      });
      status.textContent = "";
      if (result && result.checkout && result.checkout.checkout_url) {
        resultHost.appendChild(el("p", { class: "signup-card__notice signup-card__notice--go", "data-hook": "signup-checkout-link" },
          [el("a", { class: "btn btn--primary btn--full chamfer chamfer--btn", href: result.checkout.checkout_url, text: "Continue to checkout" })]));
      } else if (result && result.status === "waitlisted") {
        // WHAT IS TRUE: the email is stored (a `waitlisted` user row), nothing
        // was charged, and no card was asked for. There is still no email
        // SENDER in this app: the only email promised is the one the owner
        // writes by hand to a tester he picked (checkout.js's
        // WAITLIST_CONFIRMATION, where the whole wording is decided).
        resultHost.appendChild(el("p", {
          class: "signup-card__notice signup-card__notice--info",
          "data-hook": "signup-waitlisted",
          text: WAITLIST_CONFIRMATION,
        }));
      } else if (result && result.status === "error" && result.message) {
        // The API's own plain words ("payments are not available right now;
        // nothing has been charged", "checkout could not be started; try
        // again shortly") -- shown rather than the unrecognized-shape line.
        resultHost.appendChild(el("p", {
          class: "signup-card__notice signup-card__notice--warn",
          "data-hook": "signup-error-message",
          text: String(result.message),
        }));
      } else if (result && (result.status === "tester_expired" || result.status === "tester_active")) {
        // An email that already belongs to an early-access tester, whether
        // checkout is on or not. The server sends a status word only (no date,
        // never a checkout link: an email address proves nothing about who is
        // typing it), so this says what that means and where to go: the
        // sign-in page, where the person's own token starts a checkout. The
        // words are checkout.js's, shared with the sign-in page.
        resultHost.appendChild(el("p", {
          class: "signup-card__notice signup-card__notice--info",
          "data-hook": result.status === "tester_active" ? "signup-tester-active" : "signup-tester-expired",
        }, [
          testerSignupNotice(result.status) + " ",
          el("a", { href: "#/signin", "data-hook": "signup-tester-signin-link",
            text: "Open the sign-in page" }),
          ".",
        ]));
      } else if (result && ["active", "suspended", "invited"].includes(result.status)) {
        resultHost.appendChild(el("p", {
          class: "signup-card__notice signup-card__notice--info",
          "data-hook": "signup-existing-account",
        }, [
          "That email already has an account. ",
          el("a", { href: "#/signin", text: "Sign in with your access token" }),
          ".",
        ]));
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
  // Reached the signup step -- see api/funnel.py's PUBLIC_FUNNEL_KINDS. The
  // first-touch tags ride on the beacon so the funnel can split this step by
  // source (trackFunnelEvent adds the visitor id itself).
  trackFunnelEvent("signup_started", firstTouchProperties());
}

/** How often, and for how long, the success page asks for the token. Stripe
 * redirects the buyer to the success page the moment payment completes, and
 * the webhook that mints the token is a separate request that can land a few
 * seconds either side of it -- until it does GET /signup/complete is a 404. */
export const SIGNUP_POLL_INTERVAL_MS = 2000;
export const SIGNUP_POLL_TIMEOUT_MS = 60000;

const _defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Exchange a Stripe Checkout session id for the access token, polling while
 * the server says "not yet" (404). Resolves `{token}` on success, or
 * `{timedOut: true}` when the deadline passes with only 404s / network
 * failures, or `{error}` for any other API answer (a 4xx/5xx that polling
 * will not fix). `isCancelled` lets the caller stop the loop when the page
 * has been navigated away from. `sleep` and `now` are injectable for tests.
 */
export async function pollSignupToken(sessionId, {
  intervalMs = SIGNUP_POLL_INTERVAL_MS, timeoutMs = SIGNUP_POLL_TIMEOUT_MS,
  isCancelled = () => false, sleep = _defaultSleep, now = Date.now,
  onWaiting = () => {},
} = {}) {
  const deadline = now() + timeoutMs;
  for (;;) {
    if (isCancelled()) return { cancelled: true };
    try {
      const body = await apiGet(
        "/signup/complete?session_id=" + encodeURIComponent(sessionId));
      const token = body && body.token;
      if (token) return { token };
    } catch (err) {
      const notYet = err instanceof ApiError && err.status === 404;
      const flaky = err instanceof ApiError && err.status === null;
      const throttled = err instanceof ApiError && err.status === 429;
      if (!(notYet || flaky || throttled)) return { error: err };
    }
    if (now() + intervalMs > deadline) return { timedOut: true };
    onWaiting();
    await sleep(intervalMs);
  }
}

function copyButton(token) {
  const button = el("button", {
    type: "button", class: "btn btn--ghost btn--full chamfer chamfer--btn",
    "data-hook": "signup-copy-token", text: "Copy token",
  });
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(token);
      button.textContent = "Copied";
    } catch (err) {
      // Clipboard blocked: the token is on screen to select by hand.
      button.textContent = "Copy it by hand from above";
    }
  });
  return button;
}

function appLink() {
  return el("a", {
    class: "btn btn--primary btn--full btn--lg chamfer chamfer--btn",
    href: "index.html#/today", "data-hook": "signup-complete-app-link",
    text: "Go to tonight's card",
  });
}

function renderSignedIn(card, token, billing) {
  card.appendChild(el("h1", { class: "signup-card__title", text: "You're in." }));
  // Only when a trial really exists (checkout on, trial_days > 0) -- and it
  // says nothing was charged, never that a payment happened.
  const started = trialStartedNote(billing);
  if (started) {
    card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "signup-trial-started",
      text: started }));
  }
  card.appendChild(el("p", { class: "signup-card__subhead", text:
    "You are signed in on this device. This is your access token — save this; it is your login on other devices:" }));
  card.appendChild(el("code", { class: "signup-card__token", "data-hook": "signup-token", text: token }));
  card.appendChild(copyButton(token));
  card.appendChild(el("p", { class: "signup-card__trust", "data-hook": "signup-save-note", text:
    "Paste it into the sign-in page on another phone or computer. Keep it private; "
    + "anyone who has it can use your subscription." }));
  card.appendChild(appLink());
}

const COMPLETE_ADDRESS_HASH = "#/signup/complete";

/**
 * Take the session id (or a token that arrived on the address) out of the
 * address bar and the history entry, leaving `#/signup/complete` alone
 * (replaceState does not fire hashchange). KEPT ON PURPOSE and extended to every
 * outcome: the owner rejected leaving the session id in history for the re-read
 * window ("Option B", docs/decisions/closed-tab-token-recovery.md, 2026-10-05).
 * A buyer who comes back later is recovered by asking the SERVER about the token
 * this browser holds (checkStoredToken), never by keeping a secret in the URL.
 */
function scrubAddress() {
  try {
    window.history.replaceState(null, "", window.location.pathname
      + window.location.search + COMPLETE_ADDRESS_HASH);
  } catch (err) { /* no history API: leave the URL */ }
}

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
function renderSignedOut(card, { cleared = false, lead = null } = {}) {
  card.appendChild(el("h1", { class: "signup-card__title", text: "You're not signed in here." }));
  card.appendChild(el("p", { class: "signup-card__subhead", "data-hook": "signup-signed-out",
    text: (lead ? lead + " " : "")
      + (cleared ? "This device's saved token is no longer accepted, so it has been removed. " : "")
      + "Your purchase or trial is not lost: it belongs to your account, not to this browser. "
      + "Sign in with your access token, or get help and we will send you a new one." }));
  helpLinks(card);
}

function renderUnreachable(card, retry) {
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
async function renderTesterEnded(card, endedAt) {
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

function renderValidated(card, billing) {
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

function freshCard(card) {
  clear(card);
  card.appendChild(el("p", { class: "eyebrow eyebrow--money signup-card__eyebrow", text: "FOUNDING BETA ACCESS" }));
}

/**
 * The page is about to rely on the token this browser holds (the buyer came
 * back to `#/signup/complete` with no session id, or with a session id whose
 * token the server no longer gives out). Ask the server about it and draw what
 * is true. `stillFinishing` is passed when a checkout session id is in flight
 * and the poll gave up: a stale stored token then does not hide the "still
 * finishing" screen the buyer actually needs.
 */
async function resolveStoredToken(main, card, query, stillFinishing = null) {
  const retry = () => renderSignupComplete(main, query);
  const result = await checkStoredToken();
  if (!card.isConnected) return;
  freshCard(card);
  if (result.kind === "valid") {
    renderValidated(card, result.billing);
  } else if (result.kind === "unreachable") {
    renderUnreachable(card, retry);
  } else if (result.kind === "expired") {
    if (stillFinishing) stillFinishing(); else await renderTesterEnded(card, result.endedAt);
  } else {
    clearToken();
    if (stillFinishing) stillFinishing(); else renderSignedOut(card, { cleared: true });
  }
}

export async function renderSignupComplete(main, query) {
  clear(main);
  const wrap = el("section", { class: "signup", "data-view": "signup-complete", "aria-label": "signup complete" });
  const card = el("div", { class: "signup-card panel chamfer chamfer--lg" });
  card.appendChild(el("p", { class: "eyebrow eyebrow--money signup-card__eyebrow", text: "FOUNDING BETA ACCESS" }));
  wrap.appendChild(card);
  main.appendChild(wrap);

  let token = (query && query.token) || "";
  // Stripe's hosted Checkout redirects here with `session_id` (see
  // src/appstate/billing.py's success_url), not a token -- there is no
  // email sender, so GET /signup/complete is the ONE bridge a paying user
  // has to their own access token (api/signup.py's "no-email-sender
  // activation bridge"). Exchange it here, and keep asking while the
  // server says the payment has not been confirmed YET.
  const sessionId = (query && query.session_id) || "";
  if (!token && sessionId) {
    const waiting = el("div", { "data-hook": "signup-finishing" });
    waiting.appendChild(el("h1", { class: "signup-card__title", text: "Finishing your signup..." }));
    // Never "payment received": for a trial nothing has been charged, and a
    // typed or forged session id shows this same screen. Say only what is
    // happening.
    waiting.appendChild(el("p", { class: "signup-card__subhead", text:
      "We are confirming your signup with the card processor — this usually takes a few seconds. Keep this page open." }));
    card.appendChild(waiting);
    const outcome = await pollSignupToken(sessionId, {
      isCancelled: () => !wrap.isConnected,
    });
    if (outcome.cancelled) return;
    freshCard(card);
    // Drawn from two places (here, and after a stale stored token), so it is
    // one function.
    const drawStillFinishing = () => {
      card.appendChild(el("h1", { class: "signup-card__title", text: "Still finishing your signup." }));
      card.appendChild(el("p", { class: "signup-card__notice signup-card__notice--warn",
        "data-hook": "signup-timed-out", text:
        "We have not received confirmation from the card processor yet. Nothing is lost: try again in a minute. "
        + "If it still does not come through, contact support and we will sort it out." }));
      const retry = el("button", { type: "button", class: "btn btn--primary btn--full chamfer chamfer--btn",
        "data-hook": "signup-retry", text: "Check again" });
      retry.addEventListener("click", () => renderSignupComplete(main, query));
      card.appendChild(retry);
      card.appendChild(el("a", { class: "btn btn--ghost btn--full chamfer chamfer--btn",
        href: "#/support", "data-hook": "signup-support-link", text: "Contact support" }));
    };
    if (outcome.token) {
      token = outcome.token;
      // SIGNED IN IMMEDIATELY: the same storage key the sign-in page writes,
      // so the buyer never has to paste anything to reach tonight's card.
      setToken(token);
      // Keep the session id out of the address bar and the history once it
      // has done its job.
      scrubAddress();
    } else if (getToken()) {
      // The re-read window closed (or the poll gave up) on a device that holds
      // a token. That token used to be trusted unseen; now the server is asked.
      if (!outcome.timedOut) scrubAddress();
      await resolveStoredToken(main, card, query, outcome.timedOut ? drawStillFinishing : null);
      return;
    } else if (outcome.timedOut) {
      drawStillFinishing();
      return;
    } else {
      // A real API refusal (not "not yet"): the token is not retrievable --
      // the session id is wrong, or its re-read window has closed. That used
      // to end on "Almost there." and nothing to do; it is the same honest,
      // recoverable state as every other way of arriving without a token.
      scrubAddress();
      renderSignedOut(card, { lead: "We could not get an access token from this checkout link." });
      return;
    }
  }
  if (token) {
    if (query && query.token) {
      setToken(token);
      // An admin-issued link carried the token in the address: once it is
      // stored, take it out of the bar and the history.
      scrubAddress();
    }
    clear(card);
    card.appendChild(el("p", { class: "eyebrow eyebrow--money signup-card__eyebrow", text: "FOUNDING BETA ACCESS" }));
    // The trial wording is only for a buyer who came through checkout (a
    // session id); a token pasted on the URL (an admin-issued link) says nothing
    // about a trial.
    renderSignedIn(card, token, sessionId ? await readBilling() : null);
    return;
  }
  if (getToken()) {
    // Back on the success page with the session id already scrubbed: this
    // browser holds a token, so ask the server about it.
    await resolveStoredToken(main, card, query);
    return;
  }
  renderSignedOut(card);
}
