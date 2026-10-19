/**
 * Small helpers the dog kit shares (web/js/dog-*.js): talking to the server, one honest sentence for an error,
 * the owner's builder link, and the few strings every panel repeats. Nothing here measures anything.
 *
 * Every panel degrades the same way: a server without these routes (404) or one that is down leaves the panel
 * hidden or saying so, never half-drawn, and the rest of the page is untouched.
 */

import { apiFetch, apiGet, apiPost, getToken } from "./api.js";
import { h, isNum, fmtPrice } from "./hounds-core.js";

export const SIGNIN_HREF = "index.html#/signin";
export const PAPER_NOTE = "Paper only. Nothing here places a real bet.";
export const SLOW_MS = 120000;           // a month-long drill replays a month of boards

export const signedIn = () => !!getToken();

export const get = (path) => apiGet(path);
export const post = (path, body, timeoutMs) => (timeoutMs
  ? apiFetch(path, { method: "POST", body: JSON.stringify(body || {}), timeoutMs })
  : apiPost(path, body || {}));
export const put = (path, body) => apiFetch(path, { method: "PUT", body: JSON.stringify(body || {}) });

/** The server's own words for a refusal ({detail: {error, message}} or a string), else a plain sentence. */
export function errorText(err, fallback = "That did not work. Try again in a minute.") {
  const detail = err && err.detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string" && detail.message) {
    const fields = detail.fields && typeof detail.fields === "object"
      ? Object.entries(detail.fields).map(([k, v]) => `${k}: ${v}`).join("; ") : "";
    return fields ? `${detail.message} (${fields})` : detail.message;
  }
  if (err && err.status === 401) return "Sign in first.";
  if (err && err.status === 429) return "That is a lot of tries in a short time. Wait a bit and try again.";
  if (err && err.status === 404) return "That is not switched on on this server yet.";
  if (err && (err.status === null || err.status === undefined)) return "Could not reach the server. Try again in a minute.";
  return fallback;
}

export const errorCode = (err) => (err && err.detail && typeof err.detail === "object" ? err.detail.error : "");

/** A sentence with a link for a signed-out visitor. */
export function signInPrompt(text) {
  return h("p", { class: "hd-muted", "data-hook": "signin-prompt" }, [`${text} `,
    h("a", { href: SIGNIN_HREF, text: "Sign in" }), "."]);
}

/** "build-a-hound.html?from=u-1&change=price_max:150,min_books:4": the owner's builder, change pre-filled. */
export function builderHref(id, change) {
  const parts = Object.entries(change || {}).map(([k, v]) => `${k}:${v}`);
  const tail = parts.length ? `&change=${encodeURIComponent(parts.join(","))}` : "";
  return `build-a-hound.html?from=${encodeURIComponent(id)}${tail}`;
}

/** "price_max 250 -> 150" style summary of a suggested change, in the rule's own words. */
export const FIELD_WORDS = {
  price_min: "Shortest price", price_max: "Longest price", min_books: "Books quoting at least",
  max_bets_per_day: "Bets a day at most", lock_minutes: "Minutes before the start", side_rule: "Side rule",
};

export function changeText(change) {
  return Object.entries(change || {}).map(([k, v]) => `${FIELD_WORDS[k] || k}: ${k.startsWith("price") && isNum(v) ? fmtPrice(v) : v}`).join(", ");
}

/** "Oct 19 at 14:00 UTC" from an ISO stamp, "" when unreadable. */
export function whenText(stamp) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(stamp || ""));
  if (!m) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[Number(m[2]) - 1]} ${Number(m[3])} at ${m[4]}:${m[5]} UTC`;
}

/** "4 h 30 min" / "35 min" for a number of minutes. */
export function spanText(minutes) {
  const m = Math.max(0, Math.round(Number(minutes) || 0));
  if (m < 90) return `${m} min`;
  const hours = Math.floor(m / 60);
  if (hours >= 48) return `${Math.floor(hours / 24)} days`;
  const rest = m % 60;
  return rest ? `${hours} h ${String(rest).padStart(2, "0")} min` : `${hours} h`;
}

/** The id feedback uses for a ticket: its slate date and its pick (src/hounds/interact/ask.py ticket_key). */
export const ticketKey = (t) => `${String((t && t.date) || "").slice(0, 10)}|${(t && t.selection) || ""}`;

/** A labelled status line a screen reader announces. */
export function statusLine(hook) {
  return h("p", { class: "hd-fine dk-status", role: "status", "aria-live": "polite", "data-hook": hook });
}

let counter = 0;
export const nextId = (prefix) => `${prefix}-${++counter}`;
