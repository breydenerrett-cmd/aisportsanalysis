/**
 * THE WORDS OF THE "YOUR FULL ACCESS IS ENDING" BANNER (owner ask 2026-10-27). No imports, so a test can run it
 * under plain node. Whether the banner shows at all is the SERVER's decision (GET /me/access, src/appstate/access_ending.py:
 * inside 3 calendar days, never after the end, never for a subscriber who renews, a comp or an account with no end date);
 * this file only words it.
 *
 * What a member keeps on the free plan is their kennel and every hound in it. What they lose is the paid member board:
 * Gameday, Matchups, Props and the daily picks card (src/appstate/access.py, TWO LEVELS). Copy rules: no "beta", "new" or "dog",
 * no profit claim, never Bet Check, paper only, and 21+ / 1-800-GAMBLER because the card is named.
 */

export const KEEP_LINE = "You keep your kennel and every hound in it.";
export const LOSE_LINE = "Without a paid plan you lose Gameday, Matchups, Props and the daily picks card.";
export const FINE_PRINT = "Paper bets and analysis only. 21+. Problem gambling? Call 1-800-GAMBLER.";
export const DISMISS_LABEL = "Remind me tomorrow";

function money(cents) {
  return "$" + (cents / 100).toFixed(2);
}

/** "Your full access ends in 2 days (on Friday, October 30)." or, on the last day, "Your full access ends today." */
export function titleLine(notice) {
  if (notice.ends_today || notice.days_left === 0) return "Your full access ends today.";
  const n = notice.days_left;
  const when = notice.ends_on ? ` (on ${notice.ends_on})` : "";
  return `Your full access ends in ${n} ${n === 1 ? "day" : "days"}${when}.`;
}

/** The one primary button: the founding price while seats remain, else the standard price. */
export function buttonLabel(notice) {
  const f = notice.founding;
  if (f && f.left > 0 && f.price_cents > 0) {
    return `Keep full access at ${money(f.price_cents)}/mo`;
  }
  const cents = Number.isInteger(notice.standard_price_cents) ? notice.standard_price_cents : 1999;
  return `Keep full access at ${money(cents)}/mo`;
}

/** The founding seats line under the button, or "" when there is no founding seat to promise. */
export function seatsLine(notice) {
  const f = notice.founding;
  return f && f.left > 0 && f.cap > 0 ? `Founding price for life · ${f.left} of ${f.cap} seats left` : "";
}

/** Every line of the banner, in order. */
export function bannerCopy(notice) {
  return {
    title: titleLine(notice), keep: KEEP_LINE, lose: LOSE_LINE, button: buttonLabel(notice),
    seats: seatsLine(notice), dismiss: DISMISS_LABEL, fine: FINE_PRINT,
  };
}

/** The local calendar day, the key a "remind me tomorrow" dismissal is stored under. */
export function dayKey(date) {
  const d = date || new Date();
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/** Show only if the server said so and the member has not dismissed it today. */
export function shouldShow(notice, dismissedDay, today) {
  return !!(notice && notice.show_warning === true && dismissedDay !== today);
}
