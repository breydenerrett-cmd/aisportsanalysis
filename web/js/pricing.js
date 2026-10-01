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
 * $19.99/mo is the founding-beta recommendation from
 * docs/PRICING_OFFER_VALIDATION.md, pending Brey's final sign-off; if he
 * changes it, billing.py and this file change together (test-checked
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
 * the trial length and price from the server. `founding_note` is the
 * founding-price explanation on its own so checkout.js can append it only when
 * there is something to buy.
 */
const FOUNDING_NOTE =
  "This is the founding price: it rises as the public record grows, and it can fall "
  + "if the record does. Founding members keep $19.99 for as long as their "
  + "subscription stays active.";

/**
 * The same explanation with the price the server reports (GET /meta
 * `billing.price_cents`) instead of the typed $19.99. `price` is a figure like
 * "$19.99"; with none, the sentence about keeping it is dropped rather than
 * guessed.
 */
export function foundingNote(price) {
  const head = "This is the founding price: it rises as the public record grows, and it can fall "
    + "if the record does.";
  return price
    ? `${head} Founding members keep ${price} for as long as their subscription stays active.`
    : head;
}

export const BETA_TIER = Object.freeze({
  id: "beta",
  name: "Founding access",
  price_cents: 1999,
  price_display: "$19.99/mo",
  founding_note: FOUNDING_NOTE,
  billing_note: "7-day free trial, then $19.99/month. Cancel anytime. " + FOUNDING_NOTE,
});
