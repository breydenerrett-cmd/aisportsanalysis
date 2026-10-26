/**
 * ONE-TIME MEMBER ANNOUNCEMENTS: a full-screen card a signed-in member sees once (GET /me/announcements, api/announcements.py).
 *
 * Booted from nav.js, which every page loads, so "every page load" needs no per-page wiring. Only the FIRST unseen
 * announcement shows; dismissing it (the close button, or the button that goes somewhere) writes the seen row, so the
 * next one shows on the next page load. A failed read or a failed seen-write is silent: an announcement is a courtesy,
 * and a page that cannot reach it must still work (the card simply shows again next time).
 *
 * KIND "kennel_fire" is a two-step joke: step 1 is an alarm screen, step 2 takes it back and lists what is new (the
 * announcement's `steps`). OWNER RULING 2026-10-26: the two joke lines say "dogs" on purpose; everywhere else the product
 * says hounds. The repo's "no dog" copy scans read the HTML pages' visible text, not this script, so no allowlist is needed.
 * prefers-reduced-motion: the flicker is CSS under `no-preference` only (web/css/lhnav.css), so the card is still when asked.
 */

import { getToken, apiGet, apiPost } from "./api.js";
import { h } from "./hounds-core.js";

export const KENNEL_FIRE = "kennel_fire";
export const FIRE_ALARM = "Your entire kennel has been set on fire. No dogs have survived.";
export const FIRE_JOKE = "Just kidding 😅 your dogs are fine — and better trained.";
export const KENNEL_HREF = "kennel.html";

let started = false;

async function markSeen(id) {
  try { await apiPost(`/me/announcements/${encodeURIComponent(id)}/seen`, {}); } catch (err) { /* shows again next load */ }
}

function close(root) {
  if (root && root.parentNode) root.parentNode.removeChild(root);
}

function shell(kind, children, onClose) {
  const x = h("button", { type: "button", class: "lh-announce__x", "data-hook": "announce-close", "aria-label": "Close", text: "×" });
  x.addEventListener("click", onClose);
  return h("div", { class: "lh-announce", role: "dialog", "aria-modal": "true", "data-hook": "announcement", "data-kind": kind }, [
    x, h("div", { class: "lh-announce__card" }, children)]);
}

/** Show one announcement. Returns the overlay node (also appended to the body). */
export function showAnnouncement(a) {
  let root = null;
  const dismiss = async () => { close(root); await markSeen(a.id); };
  const go = async () => { close(root); await markSeen(a.id); window.location.href = KENNEL_HREF; };
  const steps = () => h("ul", { class: "lh-announce__steps", "data-hook": "announce-steps" },
    (a.steps || []).map((t) => h("li", { text: t })));

  const stepTwo = () => {
    const node = shell(a.kind, [
      h("p", { class: "lh-announce__flame", "aria-hidden": "true", text: "😅" }),
      h("h2", { class: "lh-announce__title", "data-hook": "announce-title", text: FIRE_JOKE }),
      h("p", { class: "lh-announce__lead", text: "What’s new:" }),
      steps(),
      h("button", { type: "button", class: "lh-btn lh-btn--solid lh-btn--lg", "data-hook": "announce-go", text: "Take me to my kennel" })], dismiss);
    node.querySelector("[data-hook='announce-go']").addEventListener("click", go);
    return node;
  };

  if (a.kind === KENNEL_FIRE) {
    root = shell(a.kind, [
      h("p", { class: "lh-announce__flame", "aria-hidden": "true", text: "🔥🔥🔥" }),
      h("h2", { class: "lh-announce__title", "data-hook": "announce-title", text: "🔥 " + FIRE_ALARM }),
      h("button", { type: "button", class: "lh-btn lh-btn--solid lh-btn--lg", "data-hook": "announce-what", text: "…what?" })], dismiss);
    root.setAttribute("data-step", "1");
    root.querySelector("[data-hook='announce-what']").addEventListener("click", () => {
      const next = stepTwo();
      next.setAttribute("data-step", "2");
      close(root);
      document.body.appendChild(next);
      root = next;
    });
  } else {
    root = shell(a.kind, [
      h("h2", { class: "lh-announce__title", "data-hook": "announce-title", text: a.title || "What’s new" }),
      steps(),
      h("button", { type: "button", class: "lh-btn lh-btn--solid lh-btn--lg", "data-hook": "announce-ok", text: "Got it" })], dismiss);
    root.setAttribute("data-step", "1");
    root.querySelector("[data-hook='announce-ok']").addEventListener("click", dismiss);
  }
  document.body.appendChild(root);
  return root;
}

/** Fetch the member's unseen announcements and show the first. Safe to call twice; the second call does nothing. */
export async function startAnnouncements() {
  if (started || !getToken()) return null;
  started = true;
  try {
    const out = await apiGet("/me/announcements");
    const first = out && Array.isArray(out.announcements) ? out.announcements[0] : null;
    return first ? showAnnouncement(first) : null;
  } catch (err) {
    return null;
  }
}
