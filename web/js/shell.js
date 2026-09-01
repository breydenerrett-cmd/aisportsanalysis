/**
 * Top-strip status, owned by the shell but written by whichever view is
 * mounted. Kept in its own module so a view can report freshness without
 * importing the router (main.js imports the views; the views must not
 * import it back).
 *
 * Nothing here composes a freshness claim: a view passes the API's own
 * `{observed_utc, age_seconds}` block and this only reformats it. Stale
 * drops the live dot out of its breathing loop and turns the readout
 * money-soft -- handoff section 10's stale-data treatment, where "an
 * unqualified pulsing dot next to stale odds" is named as the single
 * most damaging thing this product could ship.
 */

import { el, clear, formatAge } from "./dom.js";

/** Above this age the board is presented as stale rather than live. It
 * is a DISPLAY threshold for the dot and the wording only -- no payload
 * field is altered, and the exact age is always printed beside it. */
const STALE_AFTER_SECONDS = 900;

export function setShellStatus(text, options = {}) {
  const host = document.querySelector("[data-hook='board-status']");
  if (!host) return;
  clear(host);
  if (!text) {
    host.removeAttribute("data-stale");
    return;
  }
  const stale = !!options.stale;
  host.setAttribute("data-stale", String(stale));
  host.appendChild(el("span", { class: `live-dot${stale ? " live-dot--stale" : ""}`,
    "aria-hidden": "true" }));
  host.appendChild(el("span", { text }));
}

export function setShellStatusFromStaleness(staleness, label = "BOARD UPDATED") {
  if (!staleness || typeof staleness !== "object") {
    setShellStatus(null);
    return;
  }
  const age = staleness.age_seconds;
  if (age === null || age === undefined) {
    setShellStatus("NO BOARD YET", { stale: true });
    return;
  }
  const stale = Number(age) > STALE_AFTER_SECONDS;
  const readable = formatAge(age);
  setShellStatus(`${stale ? "LAST UPDATED" : label} ${readable || ""}`.trim(), { stale });
}
