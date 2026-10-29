/**
 * #/reset?token=... -- the page the password-reset email links to.
 *
 * Asks for a new password (same rules as sign-up: 10+ characters, not the email, nothing common; the server enforces them
 * and its sentence is shown) and posts it with the token to POST /auth/password/reset. The link works once and ends in
 * 30 minutes. The token is read from the hash and removed from the address bar at once so it does not linger in history
 * or a screenshot. On success the server has ended every other session of the account and returns a fresh one, which is
 * stored here, and the member lands on their kennel.
 */

import { setToken, apiPost } from "./api.js";
import { el, clear } from "./dom.js";
import { authErrorText, markHadAccount } from "./signin.js";

const RESET_FALLBACK = "Could not save the password. Check your connection and try again.";
const NO_LINK = "This reset link is missing its code. Ask for a new link from the sign-in page.";

export async function renderReset(container, query = {}) {
  clear(container);
  const token = typeof query.token === "string" ? query.token : "";
  try {
    if (token && window.history && window.history.replaceState) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search + "#/reset");
    }
  } catch (err) { /* the address bar is cosmetic */ }

  const wrap = el("section", { class: "signin", "data-view": "reset" });
  const card = el("div", { class: "signin__card", "data-hook": "reset-card" });
  card.appendChild(el("p", { class: "gate__eyebrow", text: "RESET PASSWORD" }));
  card.appendChild(el("h1", { class: "signin__title", text: "Choose a new password." }));
  wrap.appendChild(card);
  container.appendChild(wrap);

  if (!token) {
    card.appendChild(el("p", { class: "signin__body", "data-hook": "reset-missing", text: NO_LINK }));
    card.appendChild(el("a", { class: "btn btn--text", href: "#/signin?tab=signin", text: "Back to sign in" }));
    return;
  }

  const form = el("form", { class: "signin__form", "data-hook": "reset-form" });
  const mk = (label, id) => {
    const w = el("div", { class: "signin__field" });
    w.appendChild(el("label", { for: id, text: label }));
    const input = el("input", { id, type: "password", autocomplete: "new-password", required: "required",
      minlength: "10", "data-hook": id });
    w.appendChild(input);
    form.appendChild(w);
    return input;
  };
  const fresh = mk("New password", "reset-new");
  form.appendChild(el("p", { class: "signin__hint", text: "At least 10 characters. Not your email, and nothing common." }));
  const again = mk("Confirm new password", "reset-again");
  const button = el("button", { type: "submit", class: "btn btn--primary", "data-hook": "reset-submit",
    text: "Save new password" });
  const status = el("p", { class: "signin__status", role: "status", "data-hook": "reset-status" });
  form.appendChild(button);
  form.appendChild(status);
  card.appendChild(form);

  let busy = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    if (fresh.value !== again.value) {
      status.textContent = "The two new passwords do not match.";
      return;
    }
    busy = true;
    button.disabled = true;
    status.textContent = "Saving...";
    try {
      const out = await apiPost("/auth/password/reset", { token, new_password: fresh.value });
      fresh.value = "";
      again.value = "";
      markHadAccount();
      if (out && out.token) {
        setToken(out.token);
        status.textContent = "Password saved. Opening your kennel...";
        window.location.assign("kennel.html");
      } else {
        status.textContent = "Password saved. Sign in with your email and password.";
        window.location.hash = "#/signin?tab=signin";
      }
    } catch (err) {
      status.textContent = authErrorText(err, RESET_FALLBACK);
    } finally {
      busy = false;
      button.disabled = false;
    }
  });
}
