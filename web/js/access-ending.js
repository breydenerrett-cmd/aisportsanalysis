/**
 * THE "YOUR FULL ACCESS IS ENDING" BANNER on every signed-in member page (booted from nav.js, like announcements.js).
 *
 * Reads GET /me/access (api/me_access.py). The server decides whether to show; words are access-ending-copy.js. The button
 * starts checkout for THIS account: a tester sends their own token to POST /billing/tester-checkout (the same door the
 * ended-access sign-in page uses) and follows the Stripe redirect; a cancelled trial resumes with POST /billing/reactivate.
 * "Remind me tomorrow" hides it for the local day (localStorage, per viewer: a convenience, so every read and write is
 * guarded). Any failure is silent: a banner is a courtesy and the page must work without it.
 */

import { getToken, apiGet, apiPost } from "./api.js";
import { h } from "./hounds-core.js";
import { bannerCopy, shouldShow, dayKey } from "./access-ending-copy.js";

export const DISMISS_KEY = "lh.accessEnding.dismissedDay";
let started = false;

function dismissedDay() {
  try { return window.localStorage.getItem(DISMISS_KEY); } catch (err) { return null; }
}

function rememberDismissal() {
  try { window.localStorage.setItem(DISMISS_KEY, dayKey()); } catch (err) { /* shows again on the next load */ }
}

async function upgrade(notice, button, note) {
  if (button.disabled) return;
  button.disabled = true;
  try {
    if (notice.kind === "trial") {
      await apiPost("/billing/reactivate", {});
      window.location.reload();
      return;
    }
    const out = await apiPost("/billing/tester-checkout", {});
    const url = out && out.checkout && out.checkout.checkout_url;
    if (url) { window.location.assign(url); return; }
    note.textContent = (out && out.message) || "Checkout did not start. Nothing has been charged. Try again shortly.";
  } catch (err) {
    note.textContent = "Checkout did not start. Nothing has been charged. Try again shortly.";
  }
  button.disabled = false;
}

export function showBanner(notice) {
  const c = bannerCopy(notice);
  const note = h("p", { class: "lh-ending__note", role: "status", "data-hook": "access-ending-note" });
  const button = h("button", { type: "button", class: "lh-btn lh-btn--solid lh-btn--lg", "data-hook": "access-ending-upgrade", text: c.button });
  const later = h("button", { type: "button", class: "lh-ending__later", "data-hook": "access-ending-dismiss", text: c.dismiss });
  const root = h("aside", { class: "lh-ending", role: "region", "aria-label": "Your access", "data-hook": "access-ending",
    "data-days-left": String(notice.days_left), "data-today": notice.ends_today ? "true" : "false" }, [
    h("p", { class: "lh-ending__title", "data-hook": "access-ending-title", text: c.title }),
    h("p", { class: "lh-ending__line", text: c.keep }),
    h("p", { class: "lh-ending__line", text: c.lose }),
    h("div", { class: "lh-ending__actions" }, [button, later]),
    ...(c.seats ? [h("p", { class: "lh-ending__seats", text: c.seats })] : []),
    note,
    h("p", { class: "lh-ending__fine", text: c.fine })]);
  button.addEventListener("click", () => upgrade(notice, button, note));
  later.addEventListener("click", () => { rememberDismissal(); if (root.parentNode) root.parentNode.removeChild(root); });
  const host = document.querySelector(".lh-nav");
  if (host && host.parentNode) host.parentNode.insertBefore(root, host.nextSibling);
  else document.body.insertBefore(root, document.body.firstChild);
  return root;
}

/** Fetch and show the banner when due. Safe to call twice; the second call does nothing. */
export async function startAccessEnding() {
  if (started || !getToken()) return null;
  started = true;
  try {
    const notice = await apiGet("/me/access");
    return shouldShow(notice, dismissedDay(), dayKey()) ? showBanner(notice) : null;
  } catch (err) {
    return null;
  }
}
