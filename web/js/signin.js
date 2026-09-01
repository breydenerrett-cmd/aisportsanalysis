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
 * that, and it says so with a 401 (handled in dom.renderError).
 */

import { getToken, setToken, clearToken } from "./api.js";
import { el, clear } from "./dom.js";

export async function renderSignin(container, query = {}) {
  clear(container);
  const wrap = el("section", { class: "signin", "data-view": "signin" });
  const panel = el("form", { class: "signin__panel panel chamfer", "data-hook": "signin-form" });

  panel.appendChild(el("p", { class: "gate__eyebrow", text: "PRIVATE BETA" }));
  panel.appendChild(el("h1", { class: "signin__title", text: "Sign in to view tonight's board." }));
  panel.appendChild(el("p", { class: "signin__body",
    text: "Paste the invite token from your welcome email. It is stored on this "
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

  panel.appendChild(el("p", { class: "signin__note",
    text: "NO ACCOUNT YET? THE PUBLIC PAGE HAS THE SIGN-UP FORM." }));
  const back = el("a", { class: "gate__eyebrow", href: query.next || "#/today",
    "data-hook": "signin-continue", text: "CONTINUE TO THE BOARD" });
  panel.appendChild(back);

  panel.addEventListener("submit", (event) => {
    event.preventDefault();
    setToken(input.value.trim());
    status.textContent = "Token saved. Open Today to load the board.";
  });
  panel.querySelector("[data-hook='clear-token']").addEventListener("click", () => {
    clearToken();
    input.value = "";
    status.textContent = "Token cleared.";
  });

  wrap.appendChild(panel);
  container.appendChild(wrap);
}
