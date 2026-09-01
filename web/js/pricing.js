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
 */

export const BETA_TIER = Object.freeze({
  id: "beta",
  name: "Founding beta access",
  price_cents: 1999,
  price_display: "$19.99/mo",
  billing_note:
    "Founding-member beta price. Cancel anytime in one click; 7-day no-questions refund.",
});
