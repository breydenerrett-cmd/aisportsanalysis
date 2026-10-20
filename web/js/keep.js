/**
 * web/js/keep.js: "Keep {Name}", the in-page save for a signed-out visitor who has just seen their hound
 * (docs/marketing/GROWTH_PLAYBOOK.md, backlog item 1; shared by web/quiz.html and web/build-a-hound.html).
 *
 * THE ASK COMES AFTER THREE INVESTMENTS, NEVER BEFORE. The page shows this form only once the hound is built, named and has met
 * today's board. It is a form under the picks, not a modal, and not a redirect: the hound stays on screen the whole time.
 *
 * WHAT IT DOES, IN ORDER (one submit)
 *   1. Checks the form with no network: an email, a password of 10 or more characters, and the "I am 21 or older" box. Without the
 *      box nothing is sent and the sentence says why. (The server refuses it too: api/free_signup.py answers 400 `age_required`.)
 *   2. POST /auth/signup {email, password, age_confirmed: true, attribution, website}: the existing free-account door. The new
 *      account is a free MEMBER, signed in at once; the server stores the 21+ attestation with its time on the user row.
 *   3. Stores the session token (api.js setToken) and calls the page's `save()`, which is the page's OWN save door (POST /hounds,
 *      then the best-effort look), so the hound that was on screen is the one that is kept.
 *
 * THE RECORD STARTS AT THE KEEP. Nothing here backfills: the hound has no tickets until it is kept, and the page says so once
 * (KEEP_PROMISE). A "would have bet" preview and a backtest never become a record.
 *
 * A REPEAT ADDRESS is answered with the same 200 as a new one but no token (api/free_signup.py explains why); this form then shows
 * the server's own sentence and a way to sign in, and keeps the draft (the page stashes it for the sign-in round trip).
 *
 * IF THE ACCOUNT IS MADE AND THE SAVE FAILS (a full kennel is impossible on a new account, but a 422 or a lapse is not) the person
 * is signed in and the form says so; pressing the button again retries ONLY the save.
 *
 * NO EMAIL IS SENT. There is no email sender yet, so there is no "email me this hound's link" exit and no promise of an email. The
 * fine print says what is true: a free account, no card, paper bets only.
 *
 * Written against attributes only (no classList, no dataset, no innerHTML): it must run in the node test harness's small DOM.
 */

import { apiPost, getToken, setToken } from "./api.js";
import { attributionPayload } from "./attribution.js";
import { h, clearNode, describeError } from "./hounds-core.js";

export const KEEP_PROMISE = "Your record starts the moment you keep it. Every pick goes on the public record before the game and is graded win or lose.";
export const AGE_LABEL = "I am 21 or older";
export const KEEP_FINE = "A free account. No card. Paper bets only.";
export const AGE_NEEDED = "Confirm that you are 21 or older to keep your hound.";
export const SIGNIN_HREF = "index.html#/signin";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export const keepLabel = (name) => `Keep ${String(name || "").trim() || "your hound"}`;

/** The sentence for a refused signup: the server's own words when it sent some, else a plain one. */
function refusal(err) {
  const detail = err && err.detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string" && detail.message) return detail.message;
  if (err && err.status === 429) return "Too many tries from this connection. Wait a bit and try again.";
  return describeError(err, "the sign-up").text;
}

/**
 * Build the form into `host` and wire it. Options:
 *   name()      the hound's current name (the button reads "Keep {name}")
 *   save()      the page's own save door; resolves true when the hound is kept, false when it is not (the page shows its own error)
 *   onSignIn()  called when the person chooses "Sign in instead" (the page stashes its draft first)
 *   prefix      a data-hook prefix, so a page can have its own hooks ("reveal-keep" on the quiz, "build-keep" on the builder)
 *   buttonClass / ghostClass   the page's own button classes (the quiz has qz-btn, the builder has btn)
 * Returns {setName, show, hide, destroy, state}.
 */
export function mountKeep(host, opts) {
  const { name = () => "", save, onSignIn = () => {}, prefix = "keep", buttonClass = "btn btn--primary btn--lg", ghostClass = "btn btn--ghost" } = opts || {};
  const hook = (suffix) => `${prefix}${suffix ? `-${suffix}` : ""}`;
  const state = { busy: false, accountMade: false };

  const email = h("input", { id: `${prefix}-email`, type: "email", name: "email", autocomplete: "email", inputmode: "email",
    "data-hook": hook("email"), required: true });
  const password = h("input", { id: `${prefix}-password`, type: "password", name: "password", autocomplete: "new-password",
    minlength: "10", "data-hook": hook("password"), required: true });
  const age = h("input", { id: `${prefix}-age`, type: "checkbox", name: "age_confirmed", "data-hook": hook("age"), required: true });
  // the honeypot (api/free_signup.py): a bot fills every input, a person never sees this one
  const trap = h("input", { type: "text", name: "website", tabindex: "-1", autocomplete: "off", "aria-hidden": "true",
    "data-hook": hook("trap"), class: "kp-trap" });
  const button = h("button", { type: "submit", class: `${buttonClass} kp-go`, "data-hook": hook("submit") });
  const status = h("p", { class: "kp-status", role: "status", "aria-live": "polite", "data-hook": hook("status") });
  const repeat = h("p", { class: "kp-repeat", "data-hook": hook("repeat"), hidden: true });

  const form = h("form", { class: "kp-form", "data-hook": hook("form"), novalidate: "novalidate", autocomplete: "on" }, [
    h("div", { class: "kp-field" }, [h("label", { for: `${prefix}-email`, text: "Email" }), email]),
    h("div", { class: "kp-field", "data-hook": hook("password-field") }, [
      h("label", { for: `${prefix}-password`, text: "Password" }), password,
      h("span", { class: "kp-hint", text: "10 or more characters. It is how you sign back in." })]),
    h("div", { class: "kp-age" }, [age, h("label", { for: `${prefix}-age`, text: AGE_LABEL })]),
    trap, button, status, repeat]);

  const section = h("section", { class: "kp", "data-hook": prefix, "aria-labelledby": `${prefix}-h`, hidden: true }, [
    h("h2", { id: `${prefix}-h`, class: "qz-h2 kp-title", "data-hook": hook("title") }),
    h("p", { class: "kp-promise", "data-hook": hook("promise"), text: KEEP_PROMISE }),
    form,
    h("p", { class: "qz-fine kp-fine", "data-hook": hook("fine"), text: KEEP_FINE }),
    h("p", { class: "qz-fine kp-signin", "data-hook": hook("signin-row") }, [
      "Already have an account? ",
      h("a", { href: SIGNIN_HREF, "data-hook": hook("signin"), text: "Sign in", on: { click: () => { onSignIn(); } } })])]);
  host.appendChild(section);

  const label = () => keepLabel(name());
  const refresh = () => {
    const text = label();
    clearNode(section.querySelector(`[data-hook='${hook("title")}']`)).appendChild(document.createTextNode(text + "."));
    button.textContent = state.busy ? "Keeping..." : text;
    button.disabled = state.busy;
    if (state.accountMade) {
      form.querySelector(`[data-hook='${hook("password-field")}']`).hidden = true;
      section.querySelector(`[data-hook='${hook("signin-row")}']`).hidden = true;
    }
  };

  function say(text, kind) {
    status.textContent = text || "";
    status.setAttribute("data-kind", kind || "");
  }

  form.addEventListener("submit", async (evt) => {
    if (evt && evt.preventDefault) evt.preventDefault();
    if (state.busy) return;
    say("");
    repeat.hidden = true;
    clearNode(repeat);
    if (!state.accountMade) {
      const address = String(email.value || "").trim();
      if (!EMAIL_RE.test(address)) { say("Enter a valid email address.", "bad"); if (email.focus) email.focus(); return; }
      if (String(password.value || "").length < 10) { say("Use a password of 10 or more characters.", "bad"); if (password.focus) password.focus(); return; }
      if (!age.checked) { say(AGE_NEEDED, "bad"); if (age.focus) age.focus(); return; }
    }
    state.busy = true;
    refresh();
    try {
      if (!state.accountMade) {
        say("Making your account...");
        const out = await apiPost("/auth/signup", { email: String(email.value).trim(), password: String(password.value),
          age_confirmed: true, attribution: attributionPayload(), website: String(trap.value || "") });
        password.value = "";
        if (!out || !out.token) {
          // an address that already has an account (or a bot): the server's sentence, then the way on. Nothing says which.
          say(out && out.message ? String(out.message) : "", "info");
          repeat.appendChild(h("button", { type: "button", class: ghostClass, "data-hook": hook("signin-instead"),
            text: "Sign in instead", on: { click: () => { onSignIn(); if (typeof window !== "undefined" && window.location) window.location.href = SIGNIN_HREF; } } }));
          repeat.hidden = false;
          return;
        }
        setToken(out.token);
        state.accountMade = true;
      }
      say("Keeping it...");
      const kept = await save();
      if (kept) { say(""); section.hidden = true; return; }
      say("Your account is made and you are signed in. The hound did not save; the reason is above. Press the button to try again.", "bad");
    } catch (err) {
      say(refusal(err), "bad");
    } finally {
      state.busy = false;
      refresh();
    }
  });

  refresh();
  return {
    state,
    setName() { refresh(); },
    show() { if (!getToken()) { section.hidden = false; refresh(); } },
    hide() { section.hidden = true; },
    visible() { return !section.hidden; },
    destroy() { if (section.parentNode) section.parentNode.removeChild(section); },
  };
}
