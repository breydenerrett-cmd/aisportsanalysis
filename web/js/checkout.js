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
 * THE ONE EXCEPTION WHILE CHECKOUT IS NOT ON: EARLY ACCESS (owner decision,
 * 2026-10-02). The first 20 qualified testers get 7 days of access, no card,
 * chosen and granted by hand from the admin page (src/appstate/testers.py;
 * the 20 and the 7 are TESTER_LIMIT and TESTER_ACCESS_TTL there, and
 * tests/test_tester_access.py pins that the words below say the same
 * numbers). It is an invitation the owner extends person by person, not a
 * trial anyone can start, so it is worded as early access and never as a
 * "trial": there is no card, nothing renews, nothing is charged. Everywhere the
 * offer is described it carries the same five facts -- it is early access;
 * performance is not proven; the analysis is informational, not advice; public
 * results are preserved, losses included; tester access is temporary -- and it
 * never promises profit, an edge or winning picks.
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
 * anything; the owner picks testers by hand and sends each access link
 * himself). Reworded 2026-10-02 from "Get notified when checkout opens" to
 * "Join the waitlist" (docs/CONVERSION_REVIEW_2026-10-02.md), and the same day
 * to "Request early access" when the owner decided who the first 20 testers
 * are and how they get in: a request is what the form now is. */
export const CAUTIOUS_CTA = "Request early access";

/** Static-HTML default and off-state hero note: the early-access offer, then
 * the not-on-sale sentence with the planned price (only when there is one to
 * state), then what is free now. */
export const EARLY_ACCESS_NOTE = "Early access: the first 20 testers get 7 days free, no card.";
export const NOT_OPEN_NOTE = "Not on sale yet.";
export const FREE_NOW_NOTE = "The record and the postseason odds are free now.";

/** What the signup page says after a waitlist signup succeeded. Plain words,
 * the five facts of the early-access offer, and no promise beyond what the
 * owner does by hand: he picks the first 20 himself and sends the link himself. */
export const WAITLIST_CONFIRMATION =
  "You're on the list. The first 20 testers get 7 days of early access, no card needed. "
  + "Brey picks the first 20 by hand, so not everyone is picked. "
  + "If you're picked, he sends you the access link himself. "
  + "What you should know: this is early access; performance is not proven; "
  + "the analysis is informational, not advice; every result stays on the public record, "
  + "losses included; tester access is temporary.";

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
 * AN EARLY-ACCESS TESTER WHOSE WEEK HAS ENDED (or who wants to pay inside it).
 *
 * The server tells the pages two things about such a person. The sign-in call
 * answers 401 `tester_access_expired` with the date their access ended
 * (api/auth.py): the caller holds the token, so the date is theirs to read. And
 * POST /signup answers `tester_expired` / `tester_active` for a tester's email,
 * with billing on or off, and NO date and no checkout link (api/signup.py,
 * src/appstate/tester_upgrade.py): an email address proves nothing, so the form
 * can only point the person at the sign-in page, where their token starts the
 * checkout (POST /billing/tester-checkout). The words for all of it live here so
 * the sign-in page and the signup form say the same thing and the paid offer is
 * still named by one file.
 *
 * `TESTER_NOT_OPEN` is the whole next step while the server has said nothing can
 * be bought: no button, no trial, no promise of an automatic email -- the owner
 * answers by hand, the way he sent the access link in the first place.
 * `TESTER_REPLY` is the part that is true even when the page does not know
 * whether anything can be bought (/meta could not be read).
 */
export const TESTER_NOT_OPEN = "Paid plans are not open yet. Reply to Brey if you want to keep going.";
export const TESTER_REPLY = "Reply to Brey if you want to keep going.";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];

/** "3 October 2026" (UTC, so every reader and every test sees the same day),
 * or null for anything that is not a date. */
export function endDateLabel(iso) {
  const when = new Date(iso);
  if (!iso || Number.isNaN(when.getTime())) return null;
  return `${when.getUTCDate()} ${MONTHS[when.getUTCMonth()]} ${when.getUTCFullYear()}`;
}

/** "Your early access ended on 3 October 2026." */
export function testerEndedLine(iso) {
  const day = endDateLabel(iso);
  return day ? `Your early access ended on ${day}.` : "Your early access has ended.";
}

/** The signup form's answer to `tester_expired` / `tester_active`. No date (the
 * server sends none: an end date beside an email address would tell anyone who
 * types it when that person's access ends) and no offer wording: it says the
 * email already has early access and that the access token, on the sign-in page,
 * is the way on. */
export function testerSignupNotice(status) {
  const lost = "If you lost the token, reply to Brey.";
  if (status === "tester_active") {
    return `That email already has early access. Sign in with the access token Brey sent you. ${lost}`;
  }
  return "That email already has early access, and it has ended. "
    + `The sign-in page is where to continue: use your access token there. ${lost}`;
}

/** The label of the button that starts checkout for a tester whose access
 * ended, or null when checkout is not on (then there is no button at all, only
 * the sentence). It is the signup form's own heading and button text, so the
 * button and the page it leads to name the offer in the same words. */
export function upgradeLabel(state) {
  return state && state.on ? ctaLabel(state) : null;
}

/** True only when /meta ANSWERED and said checkout is "off" or "unavailable":
 * the server told the page paid plans are not open. An unreachable /meta, or one
 * with no billing block, is not that: the page does not know, and must not state
 * it as a fact. */
export function checkoutKnownNotOpen(payload) {
  const billing = payload && typeof payload === "object" ? payload.billing : null;
  return !!billing && (billing.checkout === "off" || billing.checkout === "unavailable");
}

/** What the ended-access page needs from /meta: the checkout state (as
 * loadCheckoutState gives it) and whether the server said nothing is on sale.
 * Never rejects; an unreadable /meta is `{state: not on, knownNotOpen: false}`. */
export async function loadTesterBilling() {
  try {
    const { meta } = await import("./meta.js");
    const payload = await meta();
    return { state: checkoutState(payload), knownNotOpen: checkoutKnownNotOpen(payload) };
  } catch (err) {
    return { state: checkoutState(null), knownNotOpen: false };
  }
}

/**
 * The line under the landing hero buttons. Off: the early-access offer, that it
 * is not on sale yet with the planned price (when there is one), and what is
 * free now. On: the trial (only if there is one), the price from /meta, and the
 * cancellation promise the billing view backs.
 */
export function heroNote(state) {
  if (!state || !state.on) {
    const amount = dollars(state && state.priceCents);
    const sale = amount ? `Not on sale yet; planned price ${amount} a month.` : NOT_OPEN_NOTE;
    return [EARLY_ACCESS_NOTE, sale, FREE_NOW_NOTE].join(" ");
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
