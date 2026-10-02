/**
 * ARRIVING ON A PUBLIC PAGE OTHER THAN THE LANDING PAGE.
 *
 * Outreach links do not all point at landing.html. The record page
 * (index.html?utm_source=<lead>&utm_medium=<channel>&utm_campaign=<batch>#/record-card)
 * and the free postseason page (postseason.html?...) are the pages the
 * outreach copy actually sends people to, and until 2026-10-01 neither one
 * stored the first touch or told the funnel anybody had arrived: only
 * landing.js did. A lead who read the record and signed up later was
 * "(direct)", and the batch that found them looked like it had produced
 * nothing.
 *
 * Two things happen here, once per page LOAD:
 *   1. the URL's UTM tags are stored as the first touch (attribution.js:
 *      first touch wins, never overwritten, storage failures swallowed), so
 *      a later signup, Checkout session and paid event carry them;
 *   2. one `public_page_view` beacon is sent with that first touch, the
 *      visitor id (api.js adds it) and `page`, a short fixed label.
 *
 * WHY A NEW KIND AND NOT `landing_view`. `landing_view` is "somebody loaded
 * landing.html" and is the baseline every conversion percentage in
 * GET /admin/funnel is measured from. Counting record-page and postseason
 * loads into it would inflate that baseline and silently halve the reported
 * landing -> signup conversion the day outreach starts. See api/funnel.py.
 *
 * The beacon sends the page's own label ("record-card", "postseason"), never
 * the URL, the hash or the query string beyond the already-validated UTM
 * tags, so a signed-in visitor's token (which lives in the hash on some
 * routes) can never ride along.
 *
 * Fire-and-forget like every funnel beacon: nothing here may throw into, or
 * delay, the page it measures.
 */

import { trackFunnelEvent } from "./api.js";
import { captureFirstTouch } from "./attribution.js";

export const PUBLIC_PAGE_VIEW_KIND = "public_page_view";

// App-shell routes that are public content an outreach link may point at,
// keyed "<sport>/<route>" (the router's own resolved names: sport.js's
// parseSport and main.js's ROUTE_ALIASES have already run). Anything else --
// signin, billing, bets, support, the signup form (which sends its own
// signup_started) -- is not a public arrival page and sends nothing.
const SHELL_PUBLIC_PAGES = {
  "mlb/record-card": "record-card",
  "nfl/record": "nfl-record",
  "ufc/record": "ufc-record",
  "mlb/postseason": "postseason",
};

/** The label for an app-shell route, or null when the route is not one of
 * the public arrival pages. */
export function publicPageName(sport, route) {
  return SHELL_PUBLIC_PAGES[`${sport}/${route}`] || null;
}

/** Store this load's first touch and send ONE public_page_view for `page`.
 * Returns the page label sent, or null when nothing was (no page). */
export function trackPublicPageView(page) {
  try {
    if (!page) return null;
    // The touch now on record -- or, when storage is blocked, this load's own
    // tags, so a visit that cannot be remembered is still attributed.
    const touch = captureFirstTouch();
    trackFunnelEvent(PUBLIC_PAGE_VIEW_KIND, Object.assign({}, touch, { page }));
    return page;
  } catch (err) {
    // Tracking must never break the page it rides on.
    return null;
  }
}

/** Store the first touch only, for app-shell routes that are not themselves a
 * counted arrival page (a link to #/signup still names its source). */
export function rememberFirstTouch() {
  try {
    captureFirstTouch();
  } catch (err) {
    /* never break the page */
  }
}
