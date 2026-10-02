/**
 * ONE DECISION ABOUT WHAT THE PAGES MAY SAY ABOUT PAYING.
 *
 * Whether a visitor can pay right now is a fact about the SERVER
 * (GET /meta -> `billing.checkout`: "on" | "off" | "unavailable", from
 * src/appstate/billing.py public_checkout_status). Six places used to answer
 * it for themselves, most of them with static text -- the landing page's three
 * buttons and its hero note, the sign-in page's trial link, the record page's
 * call to action, the sign-in gate's button, the signup form -- so a deploy
 * with no Stripe still promised "Start your 7-day free trial ... Cancel
 * anytime" on every page. Every one of them now asks this module, so they
 * cannot disagree.
 *
 * THE RULE
 *   - Not "on" (off, unavailable, or /meta unreachable): no trial promise, no
 *     "cancel anytime", no founding-price story. The planned price may be
 *     shown as "Planned price: $19.99/month" and nothing more, and the call to
 *     action says what the signup page actually does: it saves the email.
 *   - "on": the trial length and the price come from `billing.trial_days` and
 *     `billing.price_cents` -- the numbers Checkout itself is built from --
 *     never from static text. `trial_days` 0 means there is NO trial sentence
 *     anywhere; 14 says 14.
 *   - Unknown or malformed values are treated as "not on" / "no trial". Saying
 *     too little is the recoverable mistake; promising a trial the server
 *     cannot start is not.
 *
 * The static HTML on the landing page carries the CAUTIOUS wording, so a
 * crawler and the first paint before this runs never over-promise; the script
 * upgrades it only when /meta says "on".
 *
 * Pure functions take the already-fetched /meta payload; `loadCheckoutState`
 * reads the shared once-per-page /meta promise (meta.js). meta.js is imported
 * lazily so dom.js (which meta.js itself imports) can use this module without
 * a static import cycle.
 */

import { BETA_TIER, foundingNote } from "./pricing.js";

/** The button text everywhere checkout is not open. The link is unchanged:
 * the signup page saves the email and nothing else (no sender exists to send
 * anything). Reworded 2026-10-02 from "Get notified when checkout opens"
 * (docs/CONVERSION_REVIEW_2026-10-02.md): "checkout" is our billing state, not
 * the visitor's next step, and a waitlist is exactly what the form is. */
export const CAUTIOUS_CTA = "Join the waitlist";

/** Static-HTML default and off-state hero note: three plain sentences, the
 * planned price in the middle (only when there is one to state). */
export const NOT_OPEN_NOTE = "Not on sale yet.";
export const FREE_NOW_NOTE = "The record and the postseason odds are free now.";

/** What every page says before /meta has answered, and whenever it cannot be
 * read: not on, no trial, only the planned price. */
export const NOT_ON = Object.freeze({ on: false, trialDays: 0, priceCents: BETA_TIER.price_cents });

function positiveInt(value) {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : 0;
}

/**
 * The checkout facts from a /meta payload: `{on, trialDays, priceCents}`.
 * `priceCents` is null when checkout is on but /meta carried no price (the
 * price is then simply not stated); when it is not on, the planned price falls
 * back to the plan's own static figure, which is only ever labelled "Planned".
 */
export function checkoutState(payload) {
  const billing = payload && typeof payload === "object" ? payload.billing : null;
  const on = !!billing && billing.checkout === "on";
  if (!on) return NOT_ON;
  const price = positiveInt(billing.price_cents);
  return { on: true, trialDays: positiveInt(billing.trial_days), priceCents: price || null };
}

/** /meta -> state, via the shared per-page promise. Never rejects. */
export async function loadCheckoutState() {
  try {
    const { meta } = await import("./meta.js");
    return checkoutState(await meta());
  } catch (err) {
    return checkoutState(null);
  }
}

/** "$19.99/month", or null when there is no price to state. */
export function monthlyPrice(priceCents) {
  const amount = dollars(priceCents);
  return amount ? amount + "/month" : null;
}

/** "$19.99", or null. */
function dollars(priceCents) {
  if (!Number.isFinite(priceCents) || priceCents <= 0) return null;
  return "$" + (priceCents / 100).toFixed(2);
}

/** "Planned price: $19.99/month" -- the only price statement allowed while
 * checkout is not on. */
export function plannedPrice(state) {
  const price = monthlyPrice(state && state.priceCents);
  return price ? "Planned price: " + price : null;
}

/** "7-day free trial" or null (no trial: nothing to say). */
export function trialPhrase(state) {
  return state && state.on && state.trialDays > 0 ? `${state.trialDays}-day free trial` : null;
}

/** The primary call to action: landing buttons, signup heading and button. */
export function ctaLabel(state) {
  if (!state || !state.on) return CAUTIOUS_CTA;
  return state.trialDays > 0 ? `Start your ${state.trialDays}-day free trial` : "Start your subscription";
}

/** The short sign-in gate button. */
export function gateLabel(state) {
  if (!state || !state.on) return CAUTIOUS_CTA;
  return state.trialDays > 0 ? "Start free trial" : "Subscribe";
}

/** The record page's call to action. */
export function recordCtaLabel(state) {
  if (!state || !state.on) return CAUTIOUS_CTA;
  return state.trialDays > 0
    ? `Start your ${state.trialDays}-day free trial to see tonight's card`
    : "Subscribe to see tonight's card";
}

/** The sign-in page's two lines (shown upper-case by that page). */
export function signinNote(state) {
  if (!state || !state.on) return "NO ACCOUNT YET? CHECKOUT IS NOT OPEN YET.";
  return state.trialDays > 0 ? "NO ACCOUNT YET? START YOUR FREE TRIAL." : "NO ACCOUNT YET? SUBSCRIBE.";
}

export function signinLinkLabel(state) {
  return ctaLabel(state).toUpperCase();
}

/**
 * The line under the landing hero buttons. Off: it is not on sale yet, the
 * planned price (when there is one), and what is free now. On: the trial (only
 * if there is one), the price from /meta, and the cancellation promise the
 * billing view backs.
 */
export function heroNote(state) {
  if (!state || !state.on) {
    const amount = dollars(state && state.priceCents);
    return [NOT_OPEN_NOTE, amount ? `Planned price ${amount} a month.` : "", FREE_NOW_NOTE]
      .filter(Boolean).join(" ");
  }
  const price = monthlyPrice(state.priceCents);
  const trial = trialPhrase(state);
  const lead = trial ? (price ? `${trial}, then ${price}.` : `${trial}.`) : (price ? `${price}.` : "");
  return [lead, "Cancel anytime."].filter(Boolean).join(" ");
}

/**
 * The pricing note on the signup form and the landing pricing card. Off:
 * "Planned price: $19.99/month" and nothing more. On: the hero note plus the
 * founding-price explanation that only means anything when you can buy.
 */
export function pricingNote(state) {
  if (!state || !state.on) return plannedPrice(state) || "";
  return [heroNote(state), foundingNote(dollars(state.priceCents))].join(" ");
}

/** Shown on the signup form right above the button, before the redirect to
 * Stripe. Null unless a card really is collected for a trial. */
export function cardRequiredNotice(state) {
  if (!state || !state.on || !(state.trialDays > 0)) return null;
  return "A card is required to start the trial. "
    + `Nothing is charged for ${state.trialDays} days, and you can cancel before then.`;
}

/** After the access token has arrived. Null when there is no trial: the
 * page then claims nothing about charges at all. */
export function trialStartedNote(state) {
  if (!state || !state.on || !(state.trialDays > 0)) return null;
  return "Your free trial has started; nothing has been charged yet.";
}
