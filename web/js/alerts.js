/**
 * Account -> Alerts: "tell me when my hounds bet". One switch per channel, the status of each, a test button, which
 * events, optional quiet hours, and the secret RSS address. The server (api/alerts_routes.py) decides everything that
 * matters: this file only shows its answer and sends the member's choices.
 *
 * WORDS THAT MATTER (docs/VOICE.md): the alerts REPORT a bet the hound made. Paper only; no promise of anything.
 * PUSH needs the server's VAPID key; without it the row says so and the switch is off. On iPhone, web push only
 * works once the site is on the Home Screen (iOS 16.4 or later): the panel says so in plain words.
 * SMS is a paid-member feature and needs an explicit opt-in (a phone number and the agree box).
 *
 * Every string from the server is put in with textContent (dom.js el), never as HTML.
 */

import { apiFetch, apiPost, ApiError } from "./api.js";
import { el, clear } from "./dom.js";

const SW_URL = "/web/alerts-sw.js";
const SW_SCOPE = "/web/";

function say(node, text, bad = false) {
  node.textContent = text;
  node.setAttribute("data-bad", bad ? "true" : "false");
}

function errorText(err) {
  if (err instanceof ApiError && err.detail && typeof err.detail === "object" && err.detail.message) return String(err.detail.message);
  return "That did not work. Try again in a minute.";
}

function urlBase64ToUint8Array(text) {
  const pad = "=".repeat((4 - (text.length % 4)) % 4);
  const raw = atob((text + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

function browserCanPush() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function isIphone() {
  return /iPhone|iPad|iPod/.test(navigator.userAgent);
}

function isStandalone() {
  return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
}

/** Subscribe THIS browser and send the subscription to the server. Throws a short Error with words for the member. */
export async function enablePush(publicKey) {
  if (!browserCanPush()) {
    throw new Error(isIphone() && !isStandalone()
      ? "On iPhone, add LINEHOUND to your Home Screen first (Share, then Add to Home Screen), then open it from the icon."
      : "This browser cannot show push notifications.");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are blocked for this site. Allow them in your browser settings.");
  const registration = await navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE });
  await navigator.serviceWorker.ready;
  let sub = await registration.pushManager.getSubscription();
  if (!sub) {
    sub = await registration.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
  }
  const json = sub.toJSON();
  await apiPost("/me/alerts/push", { endpoint: json.endpoint, keys: json.keys });
}

export async function disablePush() {
  if (!browserCanPush()) return;
  const registration = await navigator.serviceWorker.getRegistration(SW_SCOPE);
  const sub = registration ? await registration.pushManager.getSubscription() : null;
  if (!sub) return;
  await apiPost("/me/alerts/push/remove", { endpoint: sub.endpoint });
  await sub.unsubscribe();
}

export function alertsPanel() {
  const root = el("div", { class: "alerts", "data-hook": "account-alerts" });
  const body = el("div", { "data-hook": "alerts-body" });
  root.appendChild(el("h3", { class: "signin__section-title", text: "Alerts" }));
  root.appendChild(el("p", { class: "signin__body",
    text: "Get a message when your hounds bet and when a bet settles. Paper bets only; the alert reports what the hound did." }));
  root.appendChild(body);
  let state = null;
  const status = el("p", { class: "signin__status", role: "status", "data-hook": "alerts-status" });
  root.appendChild(status);

  async function save(patch) {
    try {
      state = await apiFetch("/me/alerts", { method: "PUT", body: JSON.stringify(patch) });
      say(status, "Saved.");
    } catch (err) {
      say(status, errorText(err), true);
    }
    render();
  }

  async function test(channel) {
    say(status, "Sending a test...");
    try {
      const out = await apiPost("/me/alerts/test", { channel });
      say(status, out.message, !out.ok);
    } catch (err) {
      say(status, errorText(err), true);
    }
  }

  function channelRow(c) {
    const row = el("div", { class: "alerts__row", "data-hook": `alerts-${c.name}` });
    const box = el("input", { type: "checkbox", "data-hook": `alerts-${c.name}-toggle`, id: `alerts-${c.name}` });
    box.checked = !!c.on;
    const blocked = !c.available || (c.name === "sms" && (!c.allowed || !c.opted_in)) || c.name === "native";
    box.disabled = blocked;
    box.addEventListener("change", async () => {
      if (c.name === "push") {
        try {
          if (box.checked) await enablePush(c.public_key);
          else await disablePush();
        } catch (err) {
          say(status, err.message || errorText(err), true);
          box.checked = false;
          return;
        }
      }
      save({ channels: { [c.name]: box.checked } });
    });
    row.appendChild(el("label", { for: `alerts-${c.name}`, text: c.label }));
    row.appendChild(box);
    let note = "";
    if (!c.available) note = c.reason;
    else if (c.name === "sms" && !c.allowed) note = "Text alerts are part of the member plan.";
    else if (c.name === "sms" && c.stopped) note = "You replied STOP. Add your number again to turn texts back on.";
    else if (c.name === "sms" && !c.opted_in) note = "Add your number below to turn on texts.";
    else if (c.name === "push" && !c.has_target) note = "Switch on to allow notifications in this browser.";
    else if (c.name === "email" && !c.has_target) note = "No deliverable email address on this account.";
    else note = c.on ? "On." : "Off.";
    row.appendChild(el("span", { class: "alerts__note", "data-hook": `alerts-${c.name}-note`, text: note }));
    if (c.available && c.name !== "native") {
      const t = el("button", { type: "button", class: "btn btn--ghost", "data-hook": `alerts-${c.name}-test`,
        text: "Send me a test alert" });
      t.addEventListener("click", () => test(c.name));
      row.appendChild(t);
    }
    if (c.name === "push") {
      row.appendChild(el("p", { class: "signin__body", "data-hook": "alerts-ios-note", text: state.ios_note }));
    }
    if (c.name === "sms" && c.allowed && c.available) row.appendChild(smsForm(c));
    return row;
  }

  function smsForm(c) {
    const form = el("div", { "data-hook": "alerts-sms-form" });
    if (c.opted_in) {
      form.appendChild(el("p", { class: "signin__body", text: `Texts go to ${c.phone}.` }));
      const remove = el("button", { type: "button", class: "btn btn--ghost", text: "Remove my number" });
      remove.addEventListener("click", async () => {
        try { state = await apiPost("/me/alerts/sms/remove", {}); say(status, "Number removed."); } catch (err) { say(status, errorText(err), true); }
        render();
      });
      form.appendChild(remove);
      return form;
    }
    const phone = el("input", { type: "tel", inputmode: "tel", autocomplete: "tel", placeholder: "US mobile number", "data-hook": "alerts-sms-phone" });
    const agree = el("input", { type: "checkbox", id: "alerts-sms-agree", "data-hook": "alerts-sms-agree" });
    const save1 = el("button", { type: "button", class: "btn btn--primary", text: "Save number and turn on texts" });
    save1.addEventListener("click", async () => {
      try {
        state = await apiPost("/me/alerts/sms", { phone: phone.value, consent: agree.checked });
        state = await apiFetch("/me/alerts", { method: "PUT", body: JSON.stringify({ channels: { sms: true } }) });
        say(status, "Texts are on.");
      } catch (err) { say(status, errorText(err), true); }
      render();
    });
    form.appendChild(phone);
    form.appendChild(agree);
    form.appendChild(el("label", { for: "alerts-sms-agree",
      text: "I agree to get text messages about my hounds' bets from LINEHOUND. Message and data rates may apply. Reply STOP to end." }));
    form.appendChild(save1);
    return form;
  }

  function hourSelect(value, onChange, label) {
    const sel = el("select", { "aria-label": label });
    sel.appendChild(el("option", { value: "", text: "off" }));
    for (let h = 0; h < 24; h += 1) {
      const o = el("option", { value: String(h), text: `${((h + 11) % 12) + 1}${h < 12 ? " AM" : " PM"}` });
      if (value === h) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", onChange);
    return sel;
  }

  function render() {
    clear(body);
    if (!state) return;
    for (const c of state.channels) body.appendChild(channelRow(c));
    const events = el("select", { "aria-label": "Which alerts", "data-hook": "alerts-events" });
    for (const [v, t] of [["both", "Bets placed and settled"], ["placed", "Only when a hound bets"], ["settled", "Only when a bet settles"]]) {
      const o = el("option", { value: v, text: t });
      if (state.events === v) o.selected = true;
      events.appendChild(o);
    }
    events.addEventListener("change", () => save({ events: events.value }));
    body.appendChild(el("div", { class: "alerts__row" }, [el("label", { text: "Send me" }), events]));
    const qs = hourSelect(state.quiet_start, () => quiet(), "Quiet hours start");
    const qe = hourSelect(state.quiet_end, () => quiet(), "Quiet hours end");
    function quiet() {
      const a = qs.value === "" ? null : Number(qs.value);
      const b = qe.value === "" ? null : Number(qe.value);
      if ((a === null) !== (b === null)) return;
      save({ quiet_start: a, quiet_end: b });
    }
    body.appendChild(el("div", { class: "alerts__row", "data-hook": "alerts-quiet" },
      [el("label", { text: "Quiet hours (nothing sent between)" }), qs, el("span", { text: "and" }), qe]));
    const feed = el("input", { type: "text", readonly: "readonly", value: state.feed_url, "data-hook": "alerts-feed-url", "aria-label": "Your private alert feed" });
    const rotate = el("button", { type: "button", class: "btn btn--ghost", text: "Make a new private address" });
    rotate.addEventListener("click", async () => {
      try { state = await apiPost("/me/alerts/feed/rotate", {}); say(status, "New address made. The old one stopped working."); } catch (err) { say(status, errorText(err), true); }
      render();
    });
    body.appendChild(el("div", { class: "alerts__row", "data-hook": "alerts-feed" }, [
      el("label", { text: "Private feed of your bet alerts (for Zapier or a feed reader). Anyone with this address can read it." }), feed, rotate]));
    body.appendChild(el("p", { class: "signin__body", text: "21+ · Paper bets only, not advice · 1-800-GAMBLER" }));
  }

  (async () => {
    try {
      state = await apiFetch("/me/alerts", { method: "GET" });
    } catch (err) {
      say(status, errorText(err), true);
    }
    render();
  })();
  return root;
}
