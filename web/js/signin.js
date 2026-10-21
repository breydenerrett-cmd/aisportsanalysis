/**
 * #/signin -- EMAIL + PASSWORD FIRST, THE ACCESS CODE SECOND.
 *
 * Members sign in with the email and password they set (POST /auth/login, which
 * hands back an ordinary session token). The pasted access code is the way in
 * for a member with no password yet, and the way back when one is forgotten: it
 * sits behind "Have an access code?". Tokens are still the session: this module
 * stores whatever token it is given via api.js and never decides what it is worth.
 * Only the API can say that, with a 401 (handled in dom.renderError). The one
 * other thing it asks the API about is the ONE 401 a person can act on: an
 * early-access tester token that has run out (see expiredTesterState).
 *
 * AFTER AN ACCESS-CODE SIGN-IN with no password set, a one-time card offers to
 * set one ("so you can sign in with your email next time"); it is shown once per
 * device and dismissible. A signed-in visitor sees an account box with "Change
 * password" and "Sign out" (the footer's "Change password" link opens it via
 * #/signin?password=1). Every sentence about a failure is the server's own
 * (detail.message): the page does not guess why a sign-in failed, which is also
 * what keeps it from telling a stranger whether an address has an account.
 *
 * CREATE A FREE ACCOUNT IS THE FIRST TAB FOR A NEW VISITOR (owner decision "yes open signups", 2026-10-19). The card has two
 * tabs: "Create a free account" (email, password, optional kennel name; POST /auth/signup, which signs the visitor in at
 * once) and "Sign in". A visitor with no stored token and no memory of ever having had an account sees Create first; anyone
 * else sees Sign in first; `?create=1` (every "Create free account" button) forces Create and `?tab=signin` forces Sign in.
 * A created account lands on My kennel with a welcome card (kennel.html?welcome=1). A repeat email gets the server's own
 * sentence and a "Sign in instead" button: the page never says whether an address has an account, only the server does, and
 * only in words that read the same for both. The honeypot input (`website`) is hidden from people and left empty.
 *
 * Styled by web/css/signin.css (the model pages' slate look). The data-hook names
 * the older token form used (invite-token-input, signin-form, clear-token,
 * signin-status) are kept on the access-code form.
 */

import { getToken, setToken, clearToken, apiGet, apiPost, ApiError } from "./api.js";
import { el, clear } from "./dom.js";
import {
  loadCheckoutState, loadTesterBilling, NOT_ON, signinNote, signinLinkLabel,
  testerEndedLine, upgradeLabel, TESTER_NOT_OPEN, TESTER_REPLY,
} from "./checkout.js";

/** What to tell a tester whose click on the checkout button was refused or
 * never arrived. Plain words, nothing charged, and the one way on that always
 * works: reply to Brey (checkout.js TESTER_REPLY). */
function testerCheckoutErrorText(err) {
  if (err instanceof ApiError && err.status === 429) {
    return "Too many tries. Wait a little and press the button again. " + TESTER_REPLY;
  }
  return "Checkout could not be started. Nothing has been charged. " + TESTER_REPLY;
}

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

/**
 * What the server says about the stored token: "ok" (it authenticates), "rejected" (401), or "offline"
 * (anything else: the server could not be asked). The expired-tester 401 is handled before this by
 * expiredTesterState().
 */
export async function accessCodeVerdict() {
  if (!getToken()) return "rejected";
  try {
    await apiGet("/billing/status");
    return "ok";
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return "rejected";
    return "offline";
  }
}

/** localStorage key remembering that the "set a password" card was shown on this
 * device. Per-viewer convenience only: nothing depends on it being readable. */
export const PASSWORD_CARD_SEEN_KEY = "linehound.password_card_seen";

/** localStorage key remembering that this device has signed in or created an account, so a returning member lands on the
 * Sign in tab and a new visitor on Create. A convenience only, never an authority. */
export const HAD_ACCOUNT_KEY = "linehound.had_account";

function hadAccount() {
  try {
    return window.localStorage.getItem(HAD_ACCOUNT_KEY) === "1";
  } catch (err) {
    return false;
  }
}

function markHadAccount() {
  try {
    window.localStorage.setItem(HAD_ACCOUNT_KEY, "1");
  } catch (err) { /* nothing to remember it in */ }
}

/** Where a new member lands: My kennel, with the welcome card. */
export const WELCOME_HREF = "kennel.html?welcome=1";

const CREATE_FALLBACK = "Could not create the account. Check your connection and try again.";

function passwordCardSeen() {
  try {
    return window.localStorage.getItem(PASSWORD_CARD_SEEN_KEY) === "1";
  } catch (err) {
    return true;     // no storage: never nag, the footer link is still there
  }
}

function markPasswordCardSeen() {
  try {
    window.localStorage.setItem(PASSWORD_CARD_SEEN_KEY, "1");
  } catch (err) { /* nothing to remember it in */ }
}

/** Whether the signed-in member has a password: true, false, or null when the
 * token is not good / the service did not answer (callers then show nothing). */
export async function passwordState() {
  if (!getToken()) return null;
  try {
    const out = await apiGet("/auth/password");
    return out && typeof out.has_password === "boolean" ? out.has_password : null;
  } catch (err) {
    return null;
  }
}

/** The server's own plain sentence for a failed sign-in or password save, with
 * a calm fallback when there is none (the service did not answer). */
export function authErrorText(err, fallback) {
  const detail = err instanceof ApiError ? err.detail : null;
  if (detail && typeof detail === "object" && typeof detail.message === "string" && detail.message) {
    return detail.message;
  }
  return fallback;
}

const LOGIN_FALLBACK = "Could not sign in. Check your connection and try again.";
const SAVE_FALLBACK = "Could not save the password. Check your connection and try again.";

/** Only an in-app hash route is a place to send someone after sign-in. */
function safeNext(next) {
  return typeof next === "string" && next.startsWith("#/") ? next : "#/today";
}

function field(label, id, attrs, wrapClass = "signin__field") {
  const wrap = el("div", { class: wrapClass });
  wrap.appendChild(el("label", { for: id, text: label }));
  const input = el("input", Object.assign({ id }, attrs));
  wrap.appendChild(input);
  return { wrap, input };
}

/**
 * The set-or-change-password form, used by the one-time card and the account
 * box. `requireCurrent` adds the current-password field (the server demands it
 * when a password exists). Resolves nothing itself: `onSaved` runs after the
 * server accepted the new password.
 */
function passwordForm({ requireCurrent, submitLabel, hook, onSaved }) {
  const form = el("form", { class: "signin__form", "data-hook": hook });
  let current = null;
  if (requireCurrent) {
    current = field("Current password", hook + "-current", {
      type: "password", name: "current_password", autocomplete: "current-password",
      "data-hook": hook + "-current" });
    form.appendChild(current.wrap);
  }
  const fresh = field("New password", hook + "-new", {
    type: "password", name: "new_password", autocomplete: "new-password",
    minlength: "10", "data-hook": hook + "-new" });
  form.appendChild(fresh.wrap);
  form.appendChild(el("p", { class: "signin__hint",
    text: "At least 10 characters. Not your email, and nothing common." }));
  const again = field("Confirm new password", hook + "-again", {
    type: "password", name: "confirm_password", autocomplete: "new-password",
    "data-hook": hook + "-again" });
  form.appendChild(again.wrap);
  const status = el("p", { class: "signin__status", role: "status", "data-hook": hook + "-status" });
  const button = el("button", { type: "submit", class: "btn btn--primary",
    "data-hook": hook + "-submit", text: submitLabel });
  const actions = el("div", { class: "signin__actions" });
  actions.appendChild(button);
  form.appendChild(actions);
  form.appendChild(status);

  let busy = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    if (fresh.input.value !== again.input.value) {
      status.textContent = "The two new passwords do not match.";
      return;
    }
    busy = true;
    button.disabled = true;
    status.textContent = "Saving...";
    try {
      const body = { new_password: fresh.input.value };
      if (current) body.current_password = current.input.value;
      await apiPost("/auth/password", body);
      fresh.input.value = "";
      again.input.value = "";
      if (current) current.input.value = "";
      status.textContent = "Password saved. You can sign in with your email and password from now on.";
      if (onSaved) onSaved();
    } catch (err) {
      status.textContent = authErrorText(err, SAVE_FALLBACK);
    } finally {
      busy = false;
      button.disabled = false;
    }
  });
  return form;
}

export async function renderSignin(container, query = {}) {
  clear(container);
  const wrap = el("section", { class: "signin", "data-view": "signin" });
  const card = el("div", { class: "signin__card", "data-hook": "signin-card" });

  const eyebrow = el("p", { class: "gate__eyebrow", "data-hook": "signin-eyebrow", text: "SIGN IN" });
  const title = el("h1", { class: "signin__title", "data-hook": "signin-title",
    text: "Sign in to view tonight's board." });
  card.appendChild(eyebrow);
  card.appendChild(title);

  // ---- the account box: only for someone whose stored code is good ----------
  const account = el("div", { class: "signin__section", "data-hook": "signin-account" });
  account.hidden = true;
  card.appendChild(account);

  // ---- the two ways in: create a free account, or sign in ---------------------
  const tabs = el("div", { class: "signin__tabs", role: "tablist", "data-hook": "signin-tabs" });
  const tabCreate = el("button", { type: "button", class: "signin__tab", role: "tab",
    "data-hook": "tab-create", text: "Create a free account" });
  const tabSignin = el("button", { type: "button", class: "signin__tab", role: "tab",
    "data-hook": "tab-signin", text: "Sign in" });
  tabs.appendChild(tabCreate);
  tabs.appendChild(tabSignin);
  card.appendChild(tabs);

  const createForm = el("form", { class: "signin__form", "data-hook": "create-form" });
  createForm.appendChild(el("p", { class: "signin__body", "data-hook": "create-lede",
    text: "Free: build your own dogs, race them on paper money and see how they do. "
        + "No card, nothing to approve." }));
  const createEmail = field("Email", "create-email", {
    type: "email", name: "email", autocomplete: "email", inputmode: "email",
    autocapitalize: "none", spellcheck: "false", required: "required",
    "data-hook": "create-email" });
  const createPassword = field("Password", "create-password", {
    type: "password", name: "new_password", autocomplete: "new-password", minlength: "10",
    required: "required", "data-hook": "create-password" });
  const createKennel = field("Kennel name (optional)", "create-kennel", {
    type: "text", name: "kennel_name", autocomplete: "off", maxlength: "40",
    "data-hook": "create-kennel" });
  createForm.appendChild(createEmail.wrap);
  createForm.appendChild(createPassword.wrap);
  createForm.appendChild(el("p", { class: "signin__hint",
    text: "At least 10 characters. Not your email, and nothing common." }));
  createForm.appendChild(createKennel.wrap);
  // The honeypot: a real person never sees or fills it; a bot that fills every input does.
  const trap = field("Website", "create-website", {
    type: "text", name: "website", autocomplete: "off", tabindex: "-1",
    "data-hook": "create-website" }, "signin__field signin__hp");
  trap.wrap.setAttribute("aria-hidden", "true");
  createForm.appendChild(trap.wrap);
  const createStatus = el("p", { class: "signin__status", role: "status", "data-hook": "create-status" });
  const createButton = el("button", { type: "submit", class: "btn btn--primary",
    "data-hook": "create-submit", text: "Create free account" });
  const createActions = el("div", { class: "signin__actions" });
  createActions.appendChild(createButton);
  createForm.appendChild(createActions);
  createForm.appendChild(createStatus);
  const createRepeat = el("div", { class: "signin__section", "data-hook": "create-repeat" });
  createRepeat.hidden = true;
  createForm.appendChild(createRepeat);
  card.appendChild(createForm);

  // ---- email + password (the primary way in) --------------------------------
  const loginForm = el("form", { class: "signin__form", "data-hook": "login-form" });
  loginForm.appendChild(el("p", { class: "signin__body",
    text: "Sign in with your email and password." }));
  const emailField = field("Email", "login-email", {
    type: "email", name: "email", autocomplete: "username", inputmode: "email",
    autocapitalize: "none", spellcheck: "false", required: "required",
    "data-hook": "login-email" });
  const passwordField = field("Password", "login-password", {
    type: "password", name: "password", autocomplete: "current-password",
    required: "required", "data-hook": "login-password" });
  loginForm.appendChild(emailField.wrap);
  loginForm.appendChild(passwordField.wrap);
  const loginStatus = el("p", { class: "signin__status", role: "status", "data-hook": "login-status" });
  const loginButton = el("button", { type: "submit", class: "btn btn--primary",
    "data-hook": "login-submit", text: "Sign in" });
  const loginActions = el("div", { class: "signin__actions" });
  loginActions.appendChild(loginButton);
  loginForm.appendChild(loginActions);
  loginForm.appendChild(loginStatus);
  card.appendChild(loginForm);

  // ---- the access code (secondary) ------------------------------------------
  const codeToggle = el("button", { type: "button", class: "btn btn--text",
    "data-hook": "show-access-code", "aria-expanded": "false",
    text: "Have an access code?" });
  card.appendChild(codeToggle);

  const panel = el("form", { class: "signin__form", "data-hook": "signin-form" });
  panel.hidden = true;
  panel.appendChild(el("p", { class: "signin__body",
    text: "Paste your access code: the one you were shown after checkout, or "
        + "the one sent to you as an early-access tester. It is stored on this device only "
        + "and is sent with each request to the board." }));
  const codeField = field("Access code", "invite-token-input", {
    type: "password", name: "token", autocomplete: "off", value: getToken(),
    "data-hook": "invite-token-input" }, "signin__field signin__field--code");
  const input = codeField.input;
  panel.appendChild(codeField.wrap);

  const status = el("p", { class: "signin__status", role: "status", "data-hook": "signin-status" });
  const actions = el("div", { class: "signin__actions" });
  actions.appendChild(el("button", { type: "submit", class: "btn btn--primary",
    text: "Save access code" }));
  const clearButton = el("button", { type: "button", class: "btn btn--ghost",
    "data-hook": "clear-token", text: "Clear access code" });
  actions.appendChild(clearButton);
  panel.appendChild(actions);
  panel.appendChild(status);
  card.appendChild(panel);

  let codeOpen = false;
  function showCodeForm(open) {
    codeOpen = open;
    panel.hidden = !open || tab !== "signin";
    codeToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  // Which tab shows, and whether the signed-in account box has taken the forms' place.
  const wantsCreate = query && (query.create === "1" || query.create === "true");
  const wantsSignin = query && (query.tab === "signin" || typeof query.next === "string");
  let tab = wantsCreate ? "create"
    : wantsSignin || getToken() || hadAccount() ? "signin" : "create";
  let signedInMode = false;

  function applyTab() {
    const create = tab === "create";
    createForm.hidden = signedInMode || !create;
    loginForm.hidden = signedInMode || create;
    codeToggle.hidden = signedInMode || create;
    panel.hidden = signedInMode || create || !codeOpen;
    tabs.hidden = signedInMode;
    tabCreate.setAttribute("aria-selected", create ? "true" : "false");
    tabSignin.setAttribute("aria-selected", create ? "false" : "true");
    eyebrow.textContent = create ? "FREE ACCOUNT" : "SIGN IN";
    title.textContent = create ? "Create a free account." : "Sign in to view tonight's board.";
  }
  function showTab(next) {
    tab = next;
    applyTab();
  }
  function setSignedInMode(on) {
    signedInMode = on;
    applyTab();
  }
  tabCreate.addEventListener("click", () => showTab("create"));
  tabSignin.addEventListener("click", () => showTab("signin"));

  codeToggle.addEventListener("click", () => showCodeForm(panel.hidden));
  // A visitor who already has a saved code (older sign-in, checkout hand-off)
  // gets the form open: it is the thing they came to look at.
  if (getToken()) showCodeForm(true);
  applyTab();

  // ---- the one-time "set a password" card ------------------------------------
  const passwordCard = el("div", { class: "signin__section", "data-hook": "password-card" });
  passwordCard.hidden = true;
  card.appendChild(passwordCard);

  // AN EXPIRED EARLY-ACCESS TOKEN gets its own state, not the silence a wrong
  // token gets: what happened (the date), then the ONE next step that is true.
  // Checkout on: a button that starts the checkout for this same account by
  // sending the stored token to POST /billing/tester-checkout (the one route
  // that accepts an ended tester token; the token, not an email address, is the
  // proof) and follows the redirect. Checkout off (the server said so): the
  // plain sentence, no button, no promise of an email nothing sends. /meta
  // unreachable: only what the page does know, that the access ended and to
  // reply to Brey. Every word that names the offer is checkout.js's.
  const ended = el("div", { class: "signin__ended", "data-hook": "tester-ended" });
  card.appendChild(ended);

  // Every await below can be overtaken: a second Save, a Save of a different
  // token, Clear. `generation` is bumped by each of those; a call that finds it
  // has moved on after an await draws nothing, so a slow answer about an OLD
  // token can never overwrite the newer one.
  let generation = 0;

  async function startTesterCheckout(mine, button, outcome) {
    if (button.disabled) return;      // one request per press, however fast the clicks
    button.disabled = true;
    clear(outcome);
    let payload;
    try {
      payload = await apiPost("/billing/tester-checkout", {});
    } catch (err) {
      if (mine !== generation) return;
      button.disabled = false;
      outcome.appendChild(el("p", { class: "signin__body", role: "status",
        "data-hook": "tester-upgrade-error", text: testerCheckoutErrorText(err) }));
      return;
    }
    if (mine !== generation) return;
    button.disabled = false;    // also on success: Back from Stripe restores this page as it was
    if (payload && payload.checkout && payload.checkout.checkout_url) {
      // Stripe-hosted checkout: card details are entered on Stripe's origin.
      window.location.assign(payload.checkout.checkout_url);
      return;
    }
    // The API's own plain words for "error" (checkout could not be started,
    // nothing charged); the not-open sentence when the server says it is off.
    const text = payload && payload.status === "error" && payload.message
      ? String(payload.message)
      : payload && payload.status === "not_configured" ? TESTER_NOT_OPEN
      : "Checkout did not start. Nothing has been charged. " + TESTER_REPLY;
    outcome.appendChild(el("p", { class: "signin__body", role: "status",
      "data-hook": "tester-upgrade-error", text }));
  }

  async function showExpiredTester() {
    const mine = ++generation;
    const found = await expiredTesterState();
    if (mine !== generation) return false;
    clear(ended);
    // Cleared while the question was in flight: nothing left to explain.
    if (!found || !getToken()) return false;
    const { state, knownNotOpen } = await loadTesterBilling();
    if (mine !== generation) return false;
    ended.appendChild(el("p", { class: "signin__body", role: "status",
      "data-hook": "tester-ended-line", text: testerEndedLine(found.endedAt) }));
    const label = upgradeLabel(state);
    if (label) {
      const outcome = el("div", { "data-hook": "tester-upgrade-outcome" });
      const button = el("button", { type: "button",
        class: "btn btn--primary",
        "data-hook": "tester-upgrade", text: label });
      button.addEventListener("click", () => startTesterCheckout(mine, button, outcome));
      ended.appendChild(button);
      ended.appendChild(outcome);
    } else {
      ended.appendChild(el("p", { class: "signin__body", "data-hook": "tester-not-open",
        text: knownNotOpen ? TESTER_NOT_OPEN : TESTER_REPLY }));
    }
    return true;
  }
  showExpiredTester();

  // ---- the account box and the password card, both driven by passwordState ----
  let accountGeneration = 0;

  function openChangePassword(slot, hasPassword) {
    clear(slot);
    slot.appendChild(passwordForm({
      requireCurrent: hasPassword, submitLabel: "Save password", hook: "change-password",
      onSaved: () => { markPasswordCardSeen(); passwordCard.hidden = true; },
    }));
    slot.hidden = false;
  }

  async function refreshAccount() {
    const mine = ++accountGeneration;
    const has = await passwordState();
    if (mine !== accountGeneration) return null;
    clear(account);
    if (has === null || !getToken()) {
      account.hidden = true;
      setSignedInMode(false);
      return null;
    }
    // Signed in: the account box replaces the email form (nothing to sign in
    // to), and the access-code form folds away unless it has something to say.
    account.hidden = false;
    setSignedInMode(true);
    if (!status.textContent) showCodeForm(false);
    account.appendChild(el("h2", { class: "signin__section-title", text: "You are signed in" }));
    account.appendChild(el("p", { class: "signin__body", "data-hook": "account-line",
      text: has ? "You can sign in with your email and password on any device."
                : "No password is set yet. Set one to sign in with your email next time." }));
    const slot = el("div", { "data-hook": "change-password-slot" });
    slot.hidden = true;
    const row = el("div", { class: "signin__actions" });
    const change = el("button", { type: "button", class: "btn btn--ghost",
      "data-hook": "change-password-open", text: has ? "Change password" : "Set a password" });
    change.addEventListener("click", () => openChangePassword(slot, has));
    const out = el("button", { type: "button", class: "btn btn--ghost",
      "data-hook": "sign-out", text: "Sign out" });
    out.addEventListener("click", signOut);
    row.appendChild(change);
    row.appendChild(out);
    account.appendChild(row);
    account.appendChild(slot);
    if (query && (query.password === "1" || query.password === "true")) openChangePassword(slot, has);
    return has;
  }

  async function signOut() {
    // Revoke the session on the server (best effort: a dead token has nothing
    // left to revoke), then forget it on this device whatever the answer was.
    try { await apiPost("/auth/logout", {}); } catch (err) { /* already gone */ }
    clearToken();
    input.value = "";
    generation++;
    accountGeneration++;
    clear(ended);
    clear(account);
    account.hidden = true;
    setSignedInMode(false);
    showTab("signin");
    showCodeForm(false);
    passwordCard.hidden = true;
    status.textContent = "";
    loginStatus.textContent = "Signed out.";
  }

  // The one-time card: shown once per device, after an access-code sign-in, when
  // the server says no password is set. Dismissing or saving both retire it.
  async function offerPasswordCard() {
    if (passwordCardSeen()) return;
    const has = await passwordState();
    if (has !== false || !getToken() || passwordCardSeen()) return;
    markPasswordCardSeen();
    clear(passwordCard);
    passwordCard.appendChild(el("h2", { class: "signin__section-title",
      text: "Set a password" }));
    passwordCard.appendChild(el("p", { class: "signin__body", "data-hook": "password-card-line",
      text: "Set a password so you can sign in with your email next time." }));
    passwordCard.appendChild(passwordForm({
      requireCurrent: false, submitLabel: "Save password", hook: "password-card-form",
      onSaved: () => { refreshAccount(); },
    }));
    const skip = el("button", { type: "button", class: "btn btn--text",
      "data-hook": "password-card-skip", text: "Not now" });
    skip.addEventListener("click", () => { passwordCard.hidden = true; });
    passwordCard.appendChild(skip);
    passwordCard.hidden = false;
  }

  if (getToken()) refreshAccount();

  // The cautious wording first; the trial wording only when /meta says
  // checkout is on, with its own trial length (checkout.js, one decision for
  // every page).
  const earlyHead = el("p", { class: "signin__note", "data-hook": "signin-early-head",
    text: "DAILY PICKS BY INVITE" });
  card.appendChild(earlyHead);
  const signupNote = el("p", { class: "signin__note", "data-hook": "signin-note",
    text: signinNote(NOT_ON) });
  const startTrial = el("a", { class: "gate__eyebrow", href: "#/signup",
    "data-hook": "signin-start-trial", text: signinLinkLabel(NOT_ON) });
  card.appendChild(signupNote);
  card.appendChild(startTrial);
  loadCheckoutState().then((state) => {
    signupNote.textContent = signinNote(state);
    startTrial.textContent = signinLinkLabel(state);
  });
  const back = el("a", { class: "gate__eyebrow", href: query.next || "#/today",
    "data-hook": "signin-continue", text: "CONTINUE TO THE BOARD" });
  card.appendChild(back);

  // ---- behaviour --------------------------------------------------------------
  let createBusy = false;
  createForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (createBusy) return;
    createBusy = true;
    createButton.disabled = true;
    createStatus.textContent = "Creating your account...";
    clear(createRepeat);
    createRepeat.hidden = true;
    try {
      const body = { email: createEmail.input.value.trim(), password: createPassword.input.value,
        website: trap.input.value };
      const kennel = createKennel.input.value.trim();
      if (kennel) body.kennel_name = kennel;
      const out = await apiPost("/auth/signup", body);
      createPassword.input.value = "";
      if (out && out.token) {
        setToken(out.token);
        markHadAccount();
        generation++;
        createStatus.textContent = "You're in. Opening your kennel...";
        window.location.assign(WELCOME_HREF);
        return;
      }
      // An address that already has an account (or a bot): the server's own sentence, then the way on. Nothing
      // here says which it was.
      createStatus.textContent = out && out.message ? String(out.message) : "";
      const again = el("button", { type: "button", class: "btn btn--ghost", "data-hook": "create-signin-instead",
        text: "Sign in instead" });
      again.addEventListener("click", () => {
        emailField.input.value = createEmail.input.value.trim();
        showTab("signin");
      });
      createRepeat.appendChild(again);
      createRepeat.hidden = false;
    } catch (err) {
      createStatus.textContent = authErrorText(err, CREATE_FALLBACK);
    } finally {
      createBusy = false;
      createButton.disabled = false;
    }
  });

  let loginBusy = false;
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (loginBusy) return;
    loginBusy = true;
    loginButton.disabled = true;
    loginStatus.textContent = "Signing in...";
    try {
      const out = await apiPost("/auth/login", {
        email: emailField.input.value.trim(), password: passwordField.input.value });
      passwordField.input.value = "";
      setToken(out.token);
      markHadAccount();
      generation++;                // a new session supersedes any check about the old one
      refreshAccount();
      if (out.access_active === false) {
        // A tester whose window has ended: the token opens nothing, but it
        // identifies them to the upgrade door, so show the ended state.
        loginStatus.textContent = "Signed in.";
        await showExpiredTester();
      } else if (!(typeof query.next === "string" && query.next)) {
        // Kennel-first (owner ruling 2026-10-20): every member's home is My Kennel, free or paid. Only a sign-in that was
        // sent here from a specific page (?next=#/...) goes back to that page.
        loginStatus.textContent = "Signed in. Opening your kennel...";
        window.location.assign("kennel.html");
      } else {
        loginStatus.textContent = "Signed in. Opening the board...";
        window.location.hash = safeNext(query.next);
      }
    } catch (err) {
      loginStatus.textContent = authErrorText(err, LOGIN_FALLBACK);
    } finally {
      loginBusy = false;
      loginButton.disabled = false;
    }
  });

  panel.addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = input.value.trim();
    if (!code) {
      status.textContent = "Paste your access code first.";
      return;
    }
    setToken(code);
    status.textContent = "Checking your access code...";
    // Ask the server before saying anything (2026-10-19: "Save token" used to report success for any
    // text, so an admin password pasted here looked like a sign-in and changed nothing).
    // The board cannot load for an ended tester token: say so here, once.
    if (await showExpiredTester()) {
      status.textContent = "Access code saved.";
      return;
    }
    const verdict = await accessCodeVerdict();
    if (verdict === "rejected") {
      clearToken();
      status.textContent = "That code wasn't accepted. Access codes are long (about 40 characters) and come from "
        + "LineHound. Your admin password goes on the admin page, not here.";
      return;
    }
    if (verdict === "offline") {
      status.textContent = "Couldn't reach LineHound to check the code. It's saved on this device; try the board in a minute.";
      return;
    }
    markHadAccount();
    status.textContent = "";
    status.appendChild(el("span", { text: "You're signed in. " }));
    status.appendChild(el("a", { href: safeNext(query.next), "data-hook": "signin-go-board",
                                 text: "Go to tonight's board →" }));
    refreshAccount();
    offerPasswordCard();
  });
  clearButton.addEventListener("click", () => {
    clearToken();
    input.value = "";
    generation++;
    accountGeneration++;
    clear(ended);
    clear(account);
    account.hidden = true;
    setSignedInMode(false);
    status.textContent = "Access code cleared.";
  });

  wrap.appendChild(card);
  container.appendChild(wrap);
}
