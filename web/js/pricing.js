/**
 * Single source for the beta pricing tier -- read by both web/landing.html
 * (via landing.js) and the in-app signup view (signup.js), per this task's
 * brief: "price rendered from a data-price attribute the signup flow also
 * reads -- one source." A single JS module, not a duplicated literal in two
 * files, is that one source; both call sites import BETA_TIER rather than
 * hardcoding a number.
 *
 * PRICE SOURCE OF TRUTH
 * -------------------------------------------------------------------
 * Must match src/appstate/billing.py's BETA_PLAN_PRICE_CENTS -- the number
 * Stripe checkout actually charges. Showing "Free" beside a paid checkout
 * would be exactly the billing dishonesty this product exists to reject.
 * $19.99/mo is the standard price (owner decision 2026-10-20; the $14.99 founding price is FOUNDING_CENTS
 * below); if it changes, billing.py and this file change together (test-checked
 * against the API in test_web_structure where feasible).
 *
 * billing_note states the trial length (src/appstate/billing.py's
 * STRIPE_TRIAL_DAYS, default 7) -- if that env var ever changes the
 * default in production, this string is the one place to update to match
 * (same "one source, not a duplicated literal" rule as the price itself).
 */

/**
 * WHAT THIS MODULE MAY NOT SAY ON ITS OWN (2026-10-01). `billing_note` below
 * still carries the static "7-day free trial ... Cancel anytime" sentence and
 * is only for the in-app billing view, which a subscriber reaches after a
 * checkout worked. Every PUBLIC page (landing, signup, sign-in, record page)
 * builds its trial/price wording from GET /meta through web/js/checkout.js,
 * which says no trial and no "cancel anytime" unless checkout is on, and takes
 * the trial length and price from the server. `foundingNote` is the
 * founding-offer line on its own so checkout.js can append it only when
 * there is a founding seat to sell.
 */
/**
 * THE FOUNDING OFFER (owner decision 2026-10-20). The first FOUNDING_CAP members pay $14.99/mo and keep it
 * while they stay continuously subscribed; everyone after pays the standard $19.99/mo. The price depends on
 * nothing but seats: it is not tied to results, a record or a clock, and no page may say otherwise.
 *
 * The seat count is the server's (GET /billing/offer, src/appstate/founding.py: the true number of live
 * founding subscriptions, never padded). Pages show the founding line only while `available`; sold out, or
 * with no founding price configured, they show the standard price alone and no scarcity wording at all.
 */
export const FOUNDING_CAP = 50;
export const STANDARD_CENTS = 1999;
export const FOUNDING_CENTS = 1499;

/** What "for life" means, said once and shown beside every founding line. */
export const FOUNDING_FINE_PRINT =
  "Your price stays $14.99 for as long as you stay subscribed; if you cancel and come back later, "
  + "the price then on offer applies.";

/**
 * GET /billing/offer -> `{priceCents, cap, left}` for a founding offer a checkout started now would be given,
 * or null (sold out, not configured, malformed). Anything unreadable is "no founding offer": saying too little is
 * the recoverable mistake, promising a seat that is not there is not.
 */
export function foundingFromOffer(payload) {
  const f = payload && typeof payload === "object" ? payload.founding : null;
  if (!f || typeof f !== "object" || f.available !== true) return null;
  const ok = (n) => typeof n === "number" && Number.isInteger(n);
  if (!ok(f.price_cents) || f.price_cents <= 0 || !ok(f.left) || f.left <= 0 || !ok(f.cap) || f.cap <= 0) {
    return null;
  }
  return { priceCents: f.price_cents, cap: f.cap, left: f.left };
}

/** "$14.99" from cents. */
function money(cents) {
  return "$" + (cents / 100).toFixed(2);
}

/** "Founding member: $14.99/mo for life · 12 of 50 left", or "" when no founding seat can be had. */
export function foundingOfferLine(founding) {
  if (!founding) return "";
  return `Founding member: ${money(founding.priceCents)}/mo for life · ${founding.left} of ${founding.cap} left`;
}

/** The offer line plus the fine print, or "" (then pages state the standard price only). */
export function foundingNote(founding) {
  return founding ? `${foundingOfferLine(founding)}. ${FOUNDING_FINE_PRINT}` : "";
}

/** The trial sentence at a monthly price in cents: "7-day free trial, then $14.99/month. Cancel anytime."
 * (Same words as BETA_TIER.billing_note at the standard price; the founding card says the price a checkout would charge.) */
export function trialNote(cents) {
  return `7-day free trial, then ${money(cents)}/month. Cancel anytime.`;
}

/**
 * THE BILLING CARD'S WORDS (owner follow-up 2026-10-21): the card must say which price Subscribe charges. Checkout hands out the founding
 * price automatically while a seat remains (`founding` is loadFoundingOffer(): null unless a seat can really be had), so then the headline,
 * the trial sentence and the button all name it, with the standard price said once as what comes after the seats are gone. With no seat the
 * card is the standard-only card it always was. Copy only: the plan id and the checkout call are not touched.
 */
export function subscribeCopy(founding) {
  if (!founding) {
    return { founding: false, headline: BETA_TIER.price_display, subline: "", note: BETA_TIER.billing_note, fine: "", button: "Subscribe" };
  }
  return {
    founding: true,
    headline: `${money(founding.priceCents)}/mo · Founding member`,
    subline: `${founding.left} of ${founding.cap} founding seats left. After that, ${money(STANDARD_CENTS)}/mo.`,
    note: trialNote(founding.priceCents),
    fine: FOUNDING_FINE_PRINT,
    button: `Subscribe at ${money(founding.priceCents)}`,
  };
}

/** GET /billing/offer, never rejecting: null on any failure. */
export async function loadFoundingOffer() {
  try {
    const { apiGet } = await import("./api.js");
    return foundingFromOffer(await apiGet("/billing/offer"));
  } catch (err) {
    return null;
  }
}

/** The $19.99 plan is "LINEHOUND membership" (QA 2026-10-21: it was labelled "Founding access" straight above the real $14.99 founding line).
 * "Founding" belongs to the founding OFFER only: foundingOfferLine, below. */
export const PLAN_EYEBROW = "MEMBERSHIP";

export const BETA_TIER = Object.freeze({
  id: "beta",
  name: "LINEHOUND membership",
  price_cents: 1999,
  price_display: "$19.99/mo",
  billing_note: "7-day free trial, then $19.99/month. Cancel anytime.",
});
