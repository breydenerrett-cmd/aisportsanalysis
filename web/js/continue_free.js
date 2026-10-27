/**
 * An ended tester keeps their kennel as a free member (owner ruling 2026-10-27).
 *
 * A tester who signed in with their access code and never set a password has no
 * email + password to fall back on: the code itself died with the window. The
 * server (POST /auth/continue-free, src/appstate/access.py continue_as_free)
 * trades that ENDED code for a fresh free-member session, but only for a real
 * ended tester it can still vouch for; every other case is one 401. This module
 * is the one client for it, shared by the sign-in page and the board's ended
 * state, so both do the same thing. It never decides who qualifies: a refusal
 * (or a network failure) returns false and the caller shows today's ended state.
 */

import { getToken, setToken, apiPost } from "./api.js";

/** Where a free member lands: My kennel. The upgrade offer is reachable from the
 * sign-in page, which the kennel links to. */
export const FREE_HOME = "kennel.html";

/** What the page says while it opens the kennel. */
export const CONTINUE_FREE_LINE = "Your access week has ended. Opening your kennel as a free member...";

/**
 * Trade the stored (ended) access code for a free-member session. On success the
 * new token replaces the old one in storage and this resolves true; otherwise
 * the stored token is left exactly as it was and this resolves false.
 */
export async function continueAsFree() {
  if (!getToken()) return false;
  try {
    const out = await apiPost("/auth/continue-free", {});
    if (!out || typeof out.token !== "string" || !out.token) return false;
    setToken(out.token);
    return true;
  } catch (_err) {
    return false;
  }
}
