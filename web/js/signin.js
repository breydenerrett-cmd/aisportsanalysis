/**
 * #/signin -- INTERIM AUTH SCREEN.
 *
 * ============================================================
 * THIS IS NOT A DESIGNED SCREEN. It is explicitly interim.
 * ============================================================
 * design/linehound-v1 has nine artboards and none of them is an auth
 * experience; the frozen canvases never show one. Until Claude Design
 * ships that screen, this route holds the invite-token mechanics that
 * used to live in a token bar bolted to the app chrome on every page --
 * moved here so the chrome can be the compact top strip the artboards
 * actually show, and so a signed-out reader meets ONE customer-language
 * screen instead of a credential form following them around.
 *
 * It is built only from primitives that already exist (the panel/chamfer
 * surface, .btn, the shared field styling) -- no new visual language is
 * invented here, precisely so it is cheap to delete when the designed
 * screen lands. Do not treat this as visually complete and do not grow
 * it: new auth affordances belong in the design system first.
 *
 * Mechanics preserved verbatim from the retired chrome form: save the
 * token to localStorage via api.js, clear it, and say which happened.
 * This module never validates the token itself -- only the API can do
 * that, and it says so with a 401 (handled in dom.renderError). The one
 * thing it asks the API about is the ONE 401 a person can act on: an
 * early-access tester token that has run out (see expiredTesterState).
 */

import { getToken, setToken, clearToken, apiGet, ApiError } from "./api.js";
import { el, clear } from "./dom.js";
import {
  loadCheckoutState, NOT_ON, signinNote, signinLinkLabel,
  testerEndedLine, upgradeLabel, TESTER_NOT_OPEN,
} from "./checkout.js";

/** The `detail.error` api/auth.py puts on the 401 of an EXPIRED early-access
 * tester token (src/appstate/tester_upgrade.py TESTER_ACCESS_EXPIRED_ERROR). */
export const TESTER_ACCESS_EXPIRED = "tester_access_expired";

/**
 * Ask the API what the stored token is worth, by the one cheap authed read the
 * billing page already uses. Resolves `{endedAt}` (an ISO date string, or null
 * if the server sent none) ONLY when the server says the token is an expired
 * early-access tester token; anything else -- a good token, a wrong one, a
 * network failure -- resolves null and the page behaves exactly as it always
 * did. This never decides anything itself: the words and the date are the
 * server's, a wrong token is still a plain wrong token.
 */
export async function expiredTesterState() {
  if (!getToken()) return null;
  try {
    await apiGet("/billing/status");
    return null;
  } catch (err) {
    const detail = err instanceof ApiError && err.status === 401 ? err.detail : null;
    if (detail && typeof detail === "object" && detail.error === TESTER_ACCESS_EXPIRED) {
      return { endedAt: detail.expires_at || null };
    }
    return null;
  }
}

export async function renderSignin(container, query = {}) {
  clear(container);
  const wrap = el("section", { class: "signin", "data-view": "signin" });
  const panel = el("form", { class: "signin__panel panel chamfer", "data-hook": "signin-form" });

  panel.appendChild(el("p", { class: "gate__eyebrow", text: "PRIVATE BETA" }));
  panel.appendChild(el("h1", { class: "signin__title", text: "Sign in to view tonight's board." }));
  panel.appendChild(el("p", { class: "signin__body",
    text: "Paste your access token: the one you were shown after checkout, or the one "
        + "sent to you as an early-access tester. It is stored on this "
        + "device only and is sent with each request to the board." }));

  const field = el("div", { class: "signin__field" });
  field.appendChild(el("label", { for: "invite-token-input", text: "Invite token" }));
  const input = el("input", { type: "password", id: "invite-token-input", name: "token",
    autocomplete: "off", value: getToken(), "data-hook": "invite-token-input" });
  field.appendChild(input);
  panel.appendChild(field);

  const status = el("p", { class: "signin__status", role: "status", "data-hook": "signin-status" });
  const actions = el("div", { class: "signin__actions" });
  actions.appendChild(el("button", { type: "submit", class: "btn btn--primary chamfer chamfer--btn",
    text: "Save token" }));
  actions.appendChild(el("button", { type: "button", class: "btn btn--ghost chamfer chamfer--btn",
    "data-hook": "clear-token", text: "Clear token" }));
  panel.appendChild(actions);
  panel.appendChild(status);

  // AN EXPIRED EARLY-ACCESS TOKEN gets its own state, not the silence a wrong
  // token gets: what happened (the date), then the ONE next step that is true.
  // Checkout on: a button to the signup form, whose email step starts the
  // checkout for this same account (the expired token cannot authorise one
  // itself). Checkout off: the plain sentence, no button, no promise of an
  // email nothing sends. Every word that names the offer is checkout.js's.
  const ended = el("div", { class: "signin__ended", "data-hook": "tester-ended" });
  panel.appendChild(ended);
  async function showExpiredTester() {
    const found = await expiredTesterState();
    clear(ended);
    // Cleared while the question was in flight: nothing left to explain.
    if (!found || !getToken()) return false;
    const state = await loadCheckoutState();
    ended.appendChild(el("p", { class: "signin__body", role: "status",
      "data-hook": "tester-ended-line", text: testerEndedLine(found.endedAt) }));
    const label = upgradeLabel(state);
    if (label) {
      ended.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn",
        href: "#/signup", "data-hook": "tester-upgrade", text: label }));
    } else {
      ended.appendChild(el("p", { class: "signin__body", "data-hook": "tester-not-open",
        text: TESTER_NOT_OPEN }));
    }
    return true;
  }
  showExpiredTester();

  // The cautious wording first; the trial wording only when /meta says
  // checkout is on, with its own trial length (checkout.js, one decision for
  // every page).
  const signupNote = el("p", { class: "signin__note", "data-hook": "signin-note",
    text: signinNote(NOT_ON) });
  const startTrial = el("a", { class: "gate__eyebrow", href: "#/signup",
    "data-hook": "signin-start-trial", text: signinLinkLabel(NOT_ON) });
  panel.appendChild(signupNote);
  panel.appendChild(startTrial);
  loadCheckoutState().then((state) => {
    signupNote.textContent = signinNote(state);
    startTrial.textContent = signinLinkLabel(state);
  });
  const back = el("a", { class: "gate__eyebrow", href: query.next || "#/today",
    "data-hook": "signin-continue", text: "CONTINUE TO THE BOARD" });
  panel.appendChild(back);

  panel.addEventListener("submit", async (event) => {
    event.preventDefault();
    setToken(input.value.trim());
    status.textContent = "Token saved. Open Today to load the board.";
    // The board cannot load for an ended tester token: say so here, once,
    // instead of leaving "open Today" to dead-end at the gate.
    if (await showExpiredTester()) status.textContent = "Token saved.";
  });
  panel.querySelector("[data-hook='clear-token']").addEventListener("click", () => {
    clearToken();
    input.value = "";
    clear(ended);
    status.textContent = "Token cleared.";
  });

  wrap.appendChild(panel);
  container.appendChild(wrap);
}
