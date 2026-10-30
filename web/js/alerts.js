/**
 * Account -> Alerts: "tell me when my hounds bet". One switch per channel, the status of each, a test button, which
 * alert types (placed, starting soon, live updates, settled), optional quiet hours, and the secret RSS address. The server (api/alerts_routes.py) decides everything that
 * matters: this file only shows its answer and sends the member's choices.
 *
 * WORDS THAT MATTER (docs/VOICE.md): the alerts REPORT a bet the hound made. Paper only; no promise of anything.
 * PUSH needs the server's VAPID key; without it the row says so and the switch is off. On iPhone, web push only
 * works once the site is on the Home Screen (iOS 16.4 or later): the panel says so in plain words.
 * SMS is a paid-member feature and needs an explicit opt-in (a phone number and the agree box).
 *
 * Every string from the server is put in with textContent (dom.js el), never as HTML.
 *
 * HOW IT DRAWS (2026-10-29, "this screen is buggy and glitchy" on an iPhone). The panel is BUILT ONCE and then UPDATED IN PLACE:
 * a toggle changes its own switch, note and test button, never the rest. Until then every save cleared and rebuilt the whole
 * panel, which threw away the focused switch (iOS scrolls the page when the focused node is removed), a half-typed phone number
 * and the member's place on the page. Rows that cannot work are not drawn at all: the mobile app (not released; a device
 * registers itself from the app, not from this page) and texts on a server that has no Twilio keys. The look is in
 * web/css/signin.css (every class here is `alerts__*`).
 */

import { apiFetch, apiPost, ApiError } from "./api.js";
import { el, clear } from "./dom.js";

/** The four alert types, in the order the page lists them; the server owns the defaults (Live updates start OFF). */
const EVENT_ROWS = [
  ["placed", "Bet placed", "When one of your hounds makes a bet."],
  ["starting", "Starting soon", "About 15 minutes before a game with one of your open bets starts."],
  ["live", "Live updates", "Game went live, halftime, a late lead change that flips a bet, and the final. At most 3 per bet."],
  ["settled", "Bet settled", "When a bet is graded."],
];

/** The morning lineup has its own switch (not a bet alert): the server sends it once a day, at 9 AM in the member's zone. */
const MORNING_NOTE = "A short note at 9 AM about the games your running hounds are watching today. Skipped on a day none of them has a game.";

const SW_URL = "/web/alerts-sw.js";
const SW_SCOPE = "/web/";

/**
 * The morning lineup and the quiet hours run on the member's own clock, and nothing else ever asked for it, so every member sat on
 * the server's Eastern default. The first time this page opens in a browser it sends that browser's zone once (remembered in
 * localStorage so a later choice is never overwritten). A refusal (an unknown zone) changes nothing.
 */
async function adoptBrowserZone(state) {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!zone || zone === state.tz || localStorage.getItem("alerts-tz-adopted")) return state;
    localStorage.setItem("alerts-tz-adopted", "1");
    return await apiFetch("/me/alerts", { method: "PUT", body: JSON.stringify({ tz: zone }) });
  } catch (err) {
    return state;
  }
}

function say(node, text, bad = false) {
  node.textContent = text;
  node.setAttribute("data-bad", bad ? "true" : "false");
}

/** How long a line stays up. It floats over the bottom of the screen (web/css/signin.css), so every line goes by itself (a tap clears it
 *  sooner); a refusal stays longer so it can be read. */
const STATUS_FADE_MS = 3500;
const STATUS_FADE_BAD_MS = 9000;

/** The words on each channel's test button: they name what will arrive, so two rows never carry the same button. */
const TEST_LABELS = { email: "Send a test email", push: "Send a test notification", sms: "Send a test text" };

/** Channels that are never drawn: the mobile app is not released, and a device registers from the app itself. */
const HIDDEN_CHANNELS = new Set(["native"]);

/** The channels this page draws. Texts are drawn only when the server has them set up (a dead row helps nobody). */
function visibleChannels(state) {
  return state.channels.filter((c) => !HIDDEN_CHANNELS.has(c.name) && !(c.name === "sms" && !c.available));
}

/** Everything that decides WHICH nodes exist. When it changes the panel is built again; otherwise it is only updated. */
function structureOf(state) {
  const rows = visibleChannels(state).map((c) => c.name + (c.name === "sms" && c.allowed ? "+form" : ""));
  return `${rows.join(",")}|${state.feed && state.feed.allowed ? "feed" : "nofeed"}`;
}

function channelBlocked(c) {
  return !c.available || (c.name === "sms" && (!c.allowed || !c.opted_in));
}

function channelNote(c) {
  if (!c.available) return c.reason;
  if (c.name === "sms" && !c.allowed) return "Text alerts are part of the member plan.";
  if (c.name === "sms" && c.stopped) return "You replied STOP. Add your number again to turn texts back on.";
  if (c.name === "sms" && !c.opted_in) return c.pending_phone ? "Type the code we texted you below." : "Add your number below to turn on texts.";
  if (c.name === "push" && !c.has_target) return "Switch on to allow notifications in this browser.";
  if (c.name === "email" && !c.has_target) return "No deliverable email address on this account.";
  return c.on ? "On." : "Off.";
}

/** Which of the text form's three steps this channel is on. The form is rebuilt only when this changes, so typing is never wiped. */
function smsStep(c) {
  if (c.opted_in) return `in:${c.phone}`;
  if (c.pending_phone) return `code:${c.pending_phone}`;
  return "number";
}

/** textContent only when it differs: an untouched note is not re-laid-out. */
function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
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
  return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
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
  const body = el("div", { class: "alerts__body", "data-hook": "alerts-body" });
  root.appendChild(el("h3", { class: "signin__section-title", text: "Alerts" }));
  root.appendChild(el("p", { class: "signin__body",
    text: "Get a message when your hounds bet, before their games start, while they play, and when a bet settles. Paper bets only; the alert reports what the hound did." }));
  root.appendChild(body);
  // The status line floats over the bottom of the screen (position: fixed), so it appearing or going never moves a row.
  const status = el("p", { class: "alerts__status", role: "status", "data-hook": "alerts-status" });
  status.addEventListener("click", () => say(status, ""));
  root.appendChild(status);

  let state = null;
  /** {key, entries}: the nodes the current state is drawn into. Built once per structure, then updated in place. */
  let view = null;
  let fadeTimer = null;
  let chain = Promise.resolve();
  let freshFeedUrl = "";

  /** Show a line in the status area. It fades on its own (``hold`` keeps a progress line up until the answer replaces it). */
  function tell(text, bad = false, hold = false) {
    say(status, text, bad);
    if (fadeTimer) clearTimeout(fadeTimer);
    fadeTimer = hold ? null : setTimeout(() => { if (status.textContent === text) say(status, ""); }, bad ? STATUS_FADE_BAD_MS : STATUS_FADE_MS);
  }

  /** One PUT. Never throws: a refusal is told and the state stays what the server last said. */
  async function put(patch) {
    try {
      state = await apiFetch("/me/alerts", { method: "PUT", body: JSON.stringify(patch) });
      tell("Saved.");
    } catch (err) {
      tell(errorText(err), true);
    }
  }

  /** Saves go to the server one at a time, in the order the member made them, so the last answer is the whole truth. */
  function save(patch) {
    const run = chain.then(() => put(patch));
    chain = run;
    return run;
  }

  /**
   * Run a change a control started. While it runs the control is ``busy`` and the sync leaves it alone (an answer to an earlier
   * change must not flip a switch the member has just moved); when it ends everything is synced from the latest state, which
   * is also what puts a switch back after a refusal.
   */
  async function guarded(entry, job) {
    entry.busy = true;
    try {
      await job();
    } catch (err) {
      tell(err && err.message ? err.message : errorText(err), true);
    }
    entry.busy = false;
    refresh();
  }

  /** A button that cannot be pressed twice while its request is out. */
  async function pressed(button, job) {
    button.disabled = true;
    try {
      await job();
    } finally {
      button.disabled = false;
    }
  }

  /** label | switch on one line, one muted note beneath. Everything else a row needs is appended by the caller. */
  function switchRow(hook, id, labelText) {
    const row = el("div", { class: "alerts__row", "data-hook": hook });
    const box = el("input", { type: "checkbox", role: "switch", class: "alerts__switch", id, "data-hook": `${hook}-toggle`,
      "aria-describedby": `${id}-note` });
    const note = el("p", { class: "alerts__note", id: `${id}-note`, "data-hook": `${hook}-note` });
    row.appendChild(el("div", { class: "alerts__line" }, [el("label", { class: "alerts__label", for: id, text: labelText }), box]));
    row.appendChild(note);
    return { row, box, note };
  }

  // ---- channels --------------------------------------------------------------------------------------------------------

  async function toggleChannel(entry, wanted) {
    const name = entry.name;
    await guarded(entry, async () => {
      if (name === "push") {
        // the browser's own permission step comes first; a refusal is told and nothing is sent
        const current = state.channels.find((c) => c.name === "push") || {};
        try {
          if (wanted) await enablePush(current.public_key);
          else await disablePush();
        } catch (err) {
          tell(err.message || errorText(err), true);
          return;
        }
      }
      await save({ channels: { [name]: wanted } });
    });
  }

  async function sendTest(name, button) {
    await pressed(button, async () => {
      tell("Sending a test...", false, true);
      try {
        const out = await apiPost("/me/alerts/test", { channel: name });
        tell(out.message || (out.ok ? "Test sent." : errorText(null)), !out.ok);
      } catch (err) {
        tell(errorText(err), true);
      }
    });
  }

  function channelEntry(first) {
    const name = first.name;
    const { row, box, note } = switchRow(`alerts-${name}`, `alerts-${name}`, first.label);
    const entry = { name, row, box, busy: false, step: null };
    box.addEventListener("change", () => toggleChannel(entry, box.checked));

    let ios = null;
    if (name === "push") {
      ios = el("p", { class: "alerts__note", "data-hook": "alerts-ios-note" });
      row.appendChild(ios);
    }
    // the test button lives in its own slot, and is in the page only while the channel is on
    const slot = el("div", { class: "alerts__actions" });
    row.appendChild(slot);
    let testButton = null;
    if (name !== "native") {
      testButton = el("button", { type: "button", class: "btn btn--ghost alerts__test", "data-hook": `alerts-${name}-test`,
        text: TEST_LABELS[name] || "Send a test" });
      testButton.addEventListener("click", () => sendTest(name, testButton));
    }
    let formHost = null;
    if (name === "sms" && first.allowed) {
      formHost = el("div", { class: "alerts__form", "data-hook": "alerts-sms-form" });
      row.appendChild(formHost);
    }

    entry.sync = () => {
      const c = state.channels.find((x) => x.name === name);
      if (!c) return;
      box.checked = !!c.on;
      box.disabled = channelBlocked(c);
      setText(note, channelNote(c));
      if (ios) {
        setText(ios, state.ios_note || "");
        // only a Safari tab on an iPhone needs the Home Screen step; an installed app and every other browser do not
        ios.hidden = !(isIphone() && !isStandalone());
      }
      if (testButton) {
        const want = !!(c.available && c.on);
        if (want && !testButton.parentNode) slot.appendChild(testButton);
        else if (!want && testButton.parentNode) slot.removeChild(testButton);
      }
      if (formHost && entry.step !== smsStep(c)) {
        entry.step = smsStep(c);
        clear(formHost);
        drawSmsForm(formHost, c);
      }
    };
    return entry;
  }

  /** The three steps of the text opt-in, drawn into the row's own form node: a number, then the code, then the verified number. */
  function drawSmsForm(form, c) {
    const finish = async (job) => {
      try { await job(); } catch (err) { tell(errorText(err), true); }
      refresh();
    };
    if (c.opted_in) {
      form.appendChild(el("p", { class: "alerts__note", text: `Texts go to ${c.phone}.` }));
      const remove = el("button", { type: "button", class: "btn btn--ghost", text: "Remove my number" });
      remove.addEventListener("click", () => pressed(remove, () => finish(async () => {
        state = await apiPost("/me/alerts/sms/remove", {});
        tell("Number removed.");
      })));
      form.appendChild(remove);
      return;
    }
    if (c.pending_phone) {
      form.appendChild(el("p", { class: "alerts__note", text: `We texted a 6-digit code to ${c.pending_phone}. Type it here to turn texts on.` }));
      const code = el("input", { type: "text", class: "alerts__field", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6",
        placeholder: "6-digit code", "aria-label": "6-digit code", "data-hook": "alerts-sms-code" });
      const verify = el("button", { type: "button", class: "btn btn--primary", "data-hook": "alerts-sms-verify", text: "Check code and turn on texts" });
      verify.addEventListener("click", () => pressed(verify, () => finish(async () => {
        state = await apiPost("/me/alerts/sms/verify", { code: code.value });
        state = await apiFetch("/me/alerts", { method: "PUT", body: JSON.stringify({ channels: { sms: true } }) });
        tell("Texts are on.");
      })));
      const cancel = el("button", { type: "button", class: "btn btn--ghost", text: "Use a different number" });
      cancel.addEventListener("click", () => pressed(cancel, async () => {
        try { state = await apiPost("/me/alerts/sms/remove", {}); } catch (err) { tell(errorText(err), true); }
        refresh();
      }));
      form.appendChild(code);
      form.appendChild(verify);
      form.appendChild(cancel);
      return;
    }
    const phone = el("input", { type: "tel", class: "alerts__field", inputmode: "tel", autocomplete: "tel", placeholder: "US mobile number",
      "aria-label": "Your US mobile number", "data-hook": "alerts-sms-phone" });
    const agree = el("input", { type: "checkbox", class: "alerts__check", id: "alerts-sms-agree", "data-hook": "alerts-sms-agree" });
    const send = el("button", { type: "button", class: "btn btn--primary", text: "Text me a code" });
    send.addEventListener("click", () => pressed(send, () => finish(async () => {
      state = await apiPost("/me/alerts/sms", { phone: phone.value, consent: agree.checked });
      tell("Code sent. Type it below.");
    })));
    form.appendChild(phone);
    form.appendChild(el("div", { class: "alerts__consent" }, [agree, el("label", { for: "alerts-sms-agree",
      text: "I agree to get text messages about my hounds' bets from LINEHOUND. Message and data rates may apply. Reply STOP to end." })]));
    form.appendChild(send);
  }

  // ---- alert types and the morning note ---------------------------------------------------------------------------------

  /** One switch row that saves one key of the preferences. ``read`` gives the switch's value and note from the latest state. */
  function prefEntry(hook, id, labelText, read, patchFor) {
    const { row, box, note } = switchRow(hook, id, labelText);
    const entry = { row, box, busy: false };
    box.addEventListener("change", () => guarded(entry, () => save(patchFor(box.checked))));
    entry.sync = () => {
      const shown = read();
      box.checked = shown.on;
      setText(note, shown.note);
    };
    return entry;
  }

  /** One switch per alert type. Each applies to every channel above that may carry it (email carries placed and settled only). */
  function eventsBlock(entries) {
    const block = el("div", { class: "alerts__events", "data-hook": "alerts-events" });
    block.appendChild(el("p", { class: "alerts__heading", text: "Send me an alert when:" }));
    const list = el("div", { class: "alerts__list" });
    const morning = prefEntry("alerts-morning", "alerts-morning", "Morning lineup",
      () => ({ on: state.morning_lineup !== false, note: MORNING_NOTE }), (on) => ({ morning_lineup: on }));
    entries.push(morning);
    list.appendChild(morning.row);
    for (const [kind, label, note] of EVENT_ROWS) {
      const entry = prefEntry(`alerts-event-${kind}`, `alerts-event-${kind}`, label, () => {
        const carried = state.event_channels || {};
        const noEmail = Array.isArray(carried[kind]) && !carried[kind].includes("email");
        return { on: !!(state.event_toggles || {})[kind], note: noEmail ? `${note} Notifications and texts only, not email.` : note };
      }, (on) => ({ event_toggles: { [kind]: on } }));
      entries.push(entry);
      list.appendChild(entry.row);
    }
    block.appendChild(list);
    return block;
  }

  // ---- quiet hours --------------------------------------------------------------------------------------------------------

  function hourSelect(label) {
    const sel = el("select", { class: "alerts__select", "aria-label": label });
    sel.appendChild(el("option", { value: "", text: "off" }));
    for (let h = 0; h < 24; h += 1) {
      sel.appendChild(el("option", { value: String(h), text: `${((h + 11) % 12) + 1}${h < 12 ? " AM" : " PM"}` }));
    }
    return sel;
  }

  function quietEntry() {
    const row = el("div", { class: "alerts__row", "data-hook": "alerts-quiet" });
    const start = hourSelect("Quiet hours start");
    const end = hourSelect("Quiet hours end");
    const entry = { row, busy: false };
    function changed() {
      const a = start.value === "" ? null : Number(start.value);
      const b = end.value === "" ? null : Number(end.value);
      if ((a === null) !== (b === null)) return;     // half a pair says nothing and saves nothing
      guarded(entry, () => save({ quiet_start: a, quiet_end: b }));
    }
    start.addEventListener("change", changed);
    end.addEventListener("change", changed);
    row.appendChild(el("p", { class: "alerts__label", text: "Quiet hours" }));
    row.appendChild(el("p", { class: "alerts__note", text: "Nothing is sent between these two times. Pick both, or leave both off." }));
    row.appendChild(el("div", { class: "alerts__quiet" }, [start, el("span", { class: "alerts__note", text: "and" }), end]));
    entry.sync = () => {
      if ((start.value === "") !== (end.value === "")) return;     // the member is part-way through choosing a pair
      const show = (v) => (v === null || v === undefined ? "" : String(v));
      start.value = show(state.quiet_start);
      end.value = show(state.quiet_end);
    };
    return entry;
  }

  // ---- the private feed -------------------------------------------------------------------------------------------------------

  /**
   * The private feed (for Zapier "RSS" -> "SMS by Zapier" until texts are live). The server keeps only a hash of the link,
   * so a link can be shown exactly once: right after it is made. After that the page can only make a new one (which stops
   * the old). Free accounts see why it is not there.
   */
  function feedEntry() {
    const row = el("div", { class: "alerts__row", "data-hook": "alerts-feed" });
    const entry = { row, busy: false, key: null };
    function draw() {
      const feedState = state.feed || {};
      clear(row);
      row.appendChild(el("p", { class: "alerts__label", text: "Private alert feed" }));
      if (!feedState.allowed) {
        row.appendChild(el("p", { class: "alerts__note", "data-hook": "alerts-feed-paid",
          text: "The private text feed is part of the member plan. Email and browser notifications are free." }));
        return;
      }
      row.appendChild(el("p", { class: "alerts__note",
        text: "Your morning lineup and each bet your hounds decide, as a feed for Zapier or a feed reader. Anyone with the link can read it." }));
      const actions = el("div", { class: "alerts__actions" });
      if (freshFeedUrl) {
        const box = el("input", { type: "text", class: "alerts__link", readonly: "readonly", value: freshFeedUrl, "data-hook": "alerts-feed-url",
          "aria-label": "Your private alert feed link" });
        const copy = el("button", { type: "button", class: "btn btn--primary", "data-hook": "alerts-feed-copy", text: "Copy feed link" });
        copy.addEventListener("click", async () => {
          try { await navigator.clipboard.writeText(freshFeedUrl); tell("Feed link copied."); } catch (err) { box.select(); tell("Select the link and copy it.", true); }
        });
        row.appendChild(box);
        actions.appendChild(copy);
      } else if (feedState.set) {
        row.appendChild(el("p", { class: "alerts__note", "data-hook": "alerts-feed-set", text: "Your feed link is set. It is not shown again." }));
      }
      const rotate = el("button", { type: "button", class: "btn btn--ghost", "data-hook": "alerts-feed-reset", text: feedState.set ? "Reset link" : "Make my feed link" });
      rotate.addEventListener("click", () => pressed(rotate, async () => {
        const wasSet = !!(state.feed && state.feed.set);
        try {
          const answer = await apiPost("/me/alerts/feed/rotate", {});
          freshFeedUrl = String(answer.feed_url_once || "");
          state = answer;
          tell(wasSet ? "New link made. The old one stopped working." : "Feed link made. Copy it now.");
        } catch (err) { tell(errorText(err), true); }
        refresh();
      }));
      actions.appendChild(rotate);
      row.appendChild(actions);
      if (freshFeedUrl) row.appendChild(el("p", { class: "alerts__note", text: "This is the only time the link is shown. Copy it now." }));
    }
    entry.sync = () => {
      const feedState = state.feed || {};
      const key = `${feedState.allowed ? 1 : 0}|${feedState.set ? 1 : 0}|${freshFeedUrl}`;
      if (key === entry.key) return;
      entry.key = key;
      draw();
    };
    return entry;
  }

  // ---- build once, update in place -----------------------------------------------------------------------------------------------

  function build() {
    clear(body);
    const entries = [];
    const channels = el("div", { class: "alerts__list", "data-hook": "alerts-channels" });
    for (const c of visibleChannels(state)) {
      const entry = channelEntry(c);
      entries.push(entry);
      channels.appendChild(entry.row);
    }
    body.appendChild(channels);
    body.appendChild(eventsBlock(entries));
    const more = el("div", { class: "alerts__list" });
    const quiet = quietEntry();
    const feed = feedEntry();
    entries.push(quiet, feed);
    more.appendChild(quiet.row);
    more.appendChild(feed.row);
    body.appendChild(more);
    body.appendChild(el("p", { class: "signin__note", text: "21+ · Paper bets only, not advice · 1-800-GAMBLER" }));
    view = { key: structureOf(state), entries };
  }

  /** Draw the latest state: build the panel the first time (or if the set of rows changed), then update each control that is not mid-change. */
  function refresh() {
    // Anything that is not the server's alerts payload (a failed load, an unexpected answer) shows nothing rather than a half page.
    if (!state || !Array.isArray(state.channels)) {
      clear(body);
      view = null;
      return;
    }
    if (!view || view.key !== structureOf(state)) build();
    for (const entry of view.entries) if (!entry.busy) entry.sync();
  }

  (async () => {
    try {
      state = await apiFetch("/me/alerts", { method: "GET" });
      state = await adoptBrowserZone(state);
    } catch (err) {
      tell(errorText(err), true);
    }
    refresh();
  })();
  return root;
}
