/**
 * WHERE A SIGNED-IN MEMBER LANDS (owner ruling 2026-10-20, kennel-first: docs/design/KENNEL_FIRST_BRIEF.md).
 *
 * The kennel is the product, so a member who opens a front door (the app shell with no route, or the landing page) goes
 * straight to My Kennel. The old picks card is still there for anyone who asks for it: an explicit route
 * (`index.html#/today`, the footer's links, a shared record link) is never redirected.
 *
 * Pure: it takes what it needs and returns a path or null, so the app shell (main.js) and the shared navigation
 * (nav.js, which is on the landing page too) share one rule and a test can run it without a DOM.
 */

export const MY_KENNEL_HREF = "kennel.html";

/** The last path segment, "" for a bare directory address. */
function pageOf(pathname) {
  return String(pathname || "").split("/").pop() || "";
}

/**
 * @param {{signedIn: boolean, pathname?: string, hash?: string, search?: string}} where
 * @returns {string|null} the address to replace this one with, or null to stay
 */
export function memberHomeTarget(where) {
  const w = where || {};
  if (!w.signedIn) return null;
  const page = pageOf(w.pathname);
  const hash = String(w.hash || "");
  const params = new URLSearchParams(String(w.search || ""));
  if (params.get("stay") === "1") return null;
  // the app shell with no route of its own ("", "#", "#/"): the old default opened on the picks card
  if (page === "index.html" && (hash === "" || hash === "#" || hash === "#/")) return MY_KENNEL_HREF;
  // the landing page is the signed-out front door
  if (page === "landing.html") return MY_KENNEL_HREF;
  return null;
}

/** Replace the address when the rule says so. Returns true when it did (the caller stops booting). */
export function redirectMemberHome(win, signedIn) {
  try {
    const loc = win && win.location;
    if (!loc) return false;
    const target = memberHomeTarget({ signedIn, pathname: loc.pathname, hash: loc.hash, search: loc.search });
    if (!target) return false;
    if (typeof loc.replace === "function") loc.replace(target);
    else loc.href = target;
    return true;
  } catch (err) {
    return false;     // a fake window or a locked-down one: stay where we are
  }
}
