/**
 * THE STRATEGY INTERVIEW (web/interview.html): "Turn your strategy into a hound".
 *
 * WHAT THIS FILE DOES AND DOES NOT DO. It draws what api/hounds_interview.py sends: a chat thread, the form for the
 * current question, a clarification when two answers disagree, and a confirmation screen. It decides nothing about a
 * rule. Every question, choice, sentence of the summary and "can't automate yet" reason is the server's, and the
 * server's validator (src/hounds/user_spec.py) is the only judge of a spec. Nothing is saved until the person presses
 * the confirm button on the review screen, which posts the fingerprint they were shown, so a changed answer cannot be
 * confirmed by accident.
 *
 * EVERYTHING A PERSON TYPES IS TEXT. Every node here is made with `h(tag, {text})` (textContent), never parsed as markup, so a
 * strategy that contains markup is shown as the characters it is.
 *
 * TWO MODES, ONE FORM. When the assistant (Haiku, under a monthly cap) is resting, the server says so in
 * `assistant_note` and keeps asking the same questions with the same controls; the page draws the same form either way.
 *
 * ENDPOINTS
 *   POST /hounds/interview                     start; 402 upgrade_required for a free account at its dog limit
 *   GET  /hounds/interview/{id}[?edit=topic]   resume, or open an answered topic again
 *   POST /hounds/interview/{id}/answer         {topic, fields, texts, data, skip}
 *   POST /hounds/interview/{id}/resolve        {clarification, option}
 *   POST /hounds/interview/{id}/review         {name} -> the confirmation screen (saves nothing)
 *   POST /hounds/interview/{id}/confirm        {name, freeze_hash} -> creates the hound
 */

import { apiGet, apiPost, getToken } from "./api.js";
import { h, clearNode } from "./hounds-core.js";
import { showUpgrade, isUpgradeRefusal } from "./upgrade.js";

const HOOK = (name) => document.querySelector(`[data-hook='${name}']`);
const SIGNIN_HREF = "index.html#/signin";

let sid = null;            // the interview id
let view = null;           // the last view the server sent
let draft = emptyDraft();  // what is typed or picked for the current question
let busy = false;
let named = "";            // the hound's name, kept while the review screen is open
let shown = null;          // the review the person is looking at

function emptyDraft() {
  return { fields: {}, texts: {}, data: [] };
}

function say(hook, message, kind) {
  const node = HOOK(hook);
  if (!node) return;
  node.textContent = message || "";
  node.hidden = !message;
  if (kind) node.setAttribute("data-kind", kind);
}

function errorText(err) {
  const detail = err && err.detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") return detail.message;
  if (detail && typeof detail === "object" && detail.fields) {
    return Object.entries(detail.fields).map(([k, v]) => `${k}: ${v}`).join("; ");
  }
  if (err && err.status === null) return "Could not reach LINEHOUND. Check your connection and try again.";
  return "That did not go through. Try again in a minute.";
}

// ---- boot --------------------------------------------------------------------------------------------

export async function boot() {
  if (!getToken()) return gate("Sign in to turn your strategy into a hound. It takes a few minutes.", true);
  const params = new URLSearchParams((window.location && window.location.search) || "");
  const wanted = params.get("id");
  try {
    if (wanted) {
      sid = wanted;
      view = await apiGet(`/hounds/interview/${encodeURIComponent(wanted)}`);
    } else {
      view = await apiPost("/hounds/interview", {});
      sid = view.id;
      try { window.history.replaceState({}, "", `interview.html?id=${encodeURIComponent(sid)}`); } catch (err) { /* no history API: the page still works */ }
    }
  } catch (err) {
    return failToStart(err);
  }
  render();
}

function gate(message, signin) {
  const node = HOOK("iv-gate");
  clearNode(node);
  node.appendChild(h("p", { text: message }));
  if (signin) node.appendChild(h("p", {}, [h("a", { class: "btn btn--primary", href: SIGNIN_HREF, "data-hook": "iv-signin", text: "Sign in" })]));
  node.hidden = false;
}

function failToStart(err) {
  const node = HOOK("iv-gate");
  if (isUpgradeRefusal(err)) {
    showUpgrade(node, err);
    node.hidden = false;
    return;
  }
  if (err && err.status === 401) return gate("Sign in to turn your strategy into a hound. It takes a few minutes.", true);
  if (err && err.status === 404) return gate("That interview was not found. Start a new one.", false);
  gate(errorText(err), false);
}

// ---- rendering ---------------------------------------------------------------------------------------

function render() {
  HOOK("iv-gate").hidden = true;
  HOOK("iv-shell").hidden = false;
  HOOK("iv-review").hidden = true;
  const progress = view.progress || { done: 0, total: 11, topics: [] };
  const bar = HOOK("iv-progress");
  const pct = Math.round((progress.done / Math.max(1, progress.total)) * 100);
  bar.setAttribute("aria-valuenow", String(progress.done));
  bar.setAttribute("aria-valuemax", String(progress.total));
  bar.setAttribute("style", `--p:${pct}%`);
  const step = view.step || {};
  say("iv-stepno", step.kind === "topic" ? `Question ${step.index} of ${step.of}` : step.kind === "review" ? "Ready to review" : "");
  say("iv-assistant-note", view.assistant_note || "", "note");
  renderThread(view.log || []);
  renderCant(view.cant_automate || []);
  renderEdit(progress.topics || [], step);
  const area = clearNode(HOOK("iv-step"));
  if (step.kind === "topic") renderTopic(area, step);
  else if (step.kind === "clarify") renderClarify(area, step.clarification);
  else if (step.kind === "review") renderNameStep(area);
}

function renderThread(log) {
  const thread = clearNode(HOOK("iv-thread"));
  for (const entry of log) {
    thread.appendChild(h("p", {
      class: `iv-bubble iv-bubble--${entry.role === "person" ? "person" : "assistant"}`,
      "data-hook": entry.role === "person" ? "iv-said" : "iv-asked", text: String(entry.text || ""),
    }));
  }
  const last = thread.children && thread.children[thread.children.length - 1];
  if (last && last.scrollIntoView) last.scrollIntoView({ block: "nearest" });
}

function renderCant(items) {
  const box = HOOK("iv-cant");
  const list = clearNode(HOOK("iv-cant-list"));
  box.hidden = items.length === 0;
  HOOK("iv-cant-summary").textContent = `Can't automate yet (${items.length})`;
  for (const item of items) {
    list.appendChild(h("li", { "data-hook": "iv-cant-item" }, [
      h("strong", { text: String(item.text || "") }), " ", h("span", { class: "hd-muted", text: String(item.reason || "") })]));
  }
}

function renderEdit(topics, step) {
  const box = HOOK("iv-edit");
  const chips = clearNode(HOOK("iv-edit-chips"));
  const done = topics.filter((t) => t.state === "done" || t.state === "skipped");
  box.hidden = done.length === 0;
  for (const t of done) {
    chips.appendChild(h("button", {
      type: "button", class: "iv-chip iv-chip--quiet", "data-hook": "iv-edit-topic", "data-topic": t.id,
      "aria-pressed": step.kind === "topic" && step.topic === t.id ? "true" : "false", text: t.title,
      on: { click: () => reopen(t.id) },
    }));
  }
}

async function reopen(topic) {
  if (busy) return;
  busy = true;
  try {
    view = await apiGet(`/hounds/interview/${encodeURIComponent(sid)}?edit=${encodeURIComponent(topic)}`);
    busy = false;
    render();
  } catch (err) {
    busy = false;
    say("iv-assistant-note", errorText(err), "error");
  }
}

// ---- one question ------------------------------------------------------------------------------------

const present = (v) => v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0);

function renderTopic(area, step) {
  draft = {
    fields: Object.assign({}, (step.prefill && step.prefill.fields) || {}),
    texts: Object.assign({}, (step.prefill && step.prefill.texts) || {}),
    data: ((step.prefill && step.prefill.data) || []).slice(),
  };
  area.appendChild(h("h2", { class: "iv-step__title", tabindex: "-1", "data-hook": "iv-step-title", text: step.title }));
  const form = h("div", { class: "iv-form", "data-hook": "iv-form", "data-topic": step.topic });
  const error = h("p", { class: "iv-error", role: "alert", "data-hook": "iv-error", hidden: true });
  const go = h("button", { type: "button", class: "btn btn--primary iv-go", "data-hook": "iv-continue", text: "Continue" });

  const refresh = () => {
    const missing = (step.required || []).filter((name) => (step.needs || []).includes(name) && !present(draft.fields[name]));
    go.disabled = busy || missing.length > 0;
  };
  for (const control of step.controls || []) form.appendChild(buildControl(control, refresh));
  area.appendChild(form);
  area.appendChild(error);
  const actions = h("div", { class: "iv-actions", "data-hook": "iv-actions" });
  if (step.skippable) {
    actions.appendChild(h("button", { type: "button", class: "btn btn--ghost iv-skip", "data-hook": "iv-skip", text: "Skip",
      on: { click: () => submit(step, true, error, go) } }));
  }
  actions.appendChild(go);
  area.appendChild(actions);
  go.addEventListener("click", () => submit(step, false, error, go));
  refresh();
}

function buildControl(control, refresh) {
  const name = control.name;
  const wrap = h("div", { class: `iv-control iv-control--${control.kind}`, "data-hook": "iv-control", "data-name": name });
  if (control.label) wrap.appendChild(h("p", { class: "iv-label", text: control.label }));
  if (control.kind === "multi" || control.kind === "single") {
    const group = h("div", { class: "iv-chips", role: "group", "aria-label": control.label || name });
    for (const option of control.options || []) group.appendChild(optionChip(control, option, group, refresh));
    wrap.appendChild(group);
  } else if (control.kind === "number") {
    const group = h("div", { class: "iv-chips", role: "group", "aria-label": control.label || name });
    for (let n = control.min; n <= control.max; n += 1) group.appendChild(optionChip(control, { value: n, label: String(n) }, group, refresh));
    wrap.appendChild(group);
  } else if (control.kind === "price") {
    const select = h("select", { class: "iv-select", "data-hook": "iv-price", "data-name": name, "aria-label": control.label || name });
    select.appendChild(h("option", { value: "", text: "No preference" }));
    for (const p of control.presets || []) select.appendChild(h("option", { value: String(p), text: p > 0 ? `+${p}` : String(p) }));
    if (present(draft.fields[name])) select.value = String(draft.fields[name]);
    const change = () => {
      if (select.value === "") delete draft.fields[name];
      else draft.fields[name] = Number(select.value);
      refresh();
    };
    select.addEventListener("input", change);
    select.addEventListener("change", change);
    wrap.appendChild(select);
  } else if (control.kind === "short") {
    const input = h("input", { type: "text", class: "iv-input", maxlength: String(control.max || 40), "data-hook": "iv-short", "data-name": name,
      "aria-label": control.label || name, value: draft.fields[name] || "" });
    input.addEventListener("input", () => {
      if (input.value.trim()) draft.fields[name] = input.value;
      else delete draft.fields[name];
      refresh();
    });
    wrap.appendChild(input);
  } else if (control.kind === "text") {
    wrap.appendChild(textBox(control, name));
    if (control.role === "history") wrap.appendChild(historyUpload(control));
  }
  return wrap;
}

function textBox(control, name) {
  const area = h("textarea", { class: "iv-text", rows: String(control.rows || 3), maxlength: String(control.max || 600),
    placeholder: control.placeholder || "", "data-hook": "iv-text", "data-name": name, "aria-label": control.label || name });
  area.value = draft.texts[name] || "";
  area.addEventListener("input", () => {
    if (area.value) draft.texts[name] = area.value;
    else delete draft.texts[name];
  });
  const box = h("div", { class: "iv-textwrap" }, [area]);
  if (control.help) box.appendChild(h("p", { class: "hd-fine", text: control.help }));
  return box;
}

/** Optional dated history can be uploaded as a .csv or .txt file; the text goes into the box and is read by the server. */
function historyUpload(control) {
  if (typeof FileReader === "undefined") return h("span", {});
  const input = h("input", { type: "file", accept: ".csv,.txt,text/csv,text/plain", class: "iv-file", "data-hook": "iv-file", "aria-label": "Upload a file" });
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const box = document.querySelector("[data-hook='iv-text'][data-name='text']");
      const text = String(reader.result || "").slice(0, control.max || 40000);
      draft.texts.text = text;
      if (box) box.value = text;
    };
    reader.readAsText(file);
  });
  return h("p", { class: "hd-fine" }, ["Or upload a .csv or .txt file: ", input]);
}

function optionChip(control, option, group, refresh) {
  const name = control.name;
  const isData = name === "data";
  const multi = control.kind === "multi";
  const selected = () => {
    const v = isData ? draft.data : draft.fields[name];
    return multi ? Array.isArray(v) && v.includes(option.value) : v === option.value;
  };
  const chip = h("button", {
    type: "button", class: `iv-chip${option.unsupported ? " iv-chip--unsupported" : ""}`, "data-hook": "iv-option",
    "data-name": name, "data-value": String(option.value), "aria-pressed": selected() ? "true" : "false",
  }, [option.label, option.unsupported ? h("span", { class: "iv-tag", text: " can't automate yet" }) : ""]);
  chip.addEventListener("click", () => {
    if (multi) {
      const list = (isData ? draft.data : draft.fields[name] || []).slice();
      const at = list.indexOf(option.value);
      if (at >= 0) list.splice(at, 1); else list.push(option.value);
      if (isData) draft.data = list;
      else if (list.length) draft.fields[name] = list;
      else delete draft.fields[name];
    } else if (draft.fields[name] === option.value) {
      delete draft.fields[name];
    } else {
      draft.fields[name] = option.value;
    }
    for (const node of group.querySelectorAll("[data-hook='iv-option']")) {
      const value = node.getAttribute("data-value");
      const on = multi
        ? (isData ? draft.data : draft.fields[name] || []).map(String).includes(value)
        : String(draft.fields[name]) === value && name in draft.fields;
      node.setAttribute("aria-pressed", on ? "true" : "false");
    }
    refresh();
  });
  return chip;
}

async function submit(step, skip, error, go) {
  if (busy) return;
  busy = true;
  go.disabled = true;
  error.hidden = true;
  say("iv-assistant-note", "", "");
  try {
    view = await apiPost(`/hounds/interview/${encodeURIComponent(sid)}/answer`,
      { topic: step.topic, fields: skip ? {} : draft.fields, texts: skip ? {} : draft.texts, data: skip ? [] : draft.data, skip });
    busy = false;
    render();
  } catch (err) {
    busy = false;
    go.disabled = false;
    error.textContent = errorText(err);
    error.hidden = false;
  }
}

// ---- a clarification ---------------------------------------------------------------------------------

function renderClarify(area, clar) {
  area.appendChild(h("h2", { class: "iv-step__title", tabindex: "-1", "data-hook": "iv-step-title", text: "One thing to settle" }));
  area.appendChild(h("p", { class: "iv-clarify", "data-hook": "iv-clarify", "data-id": clar.id, text: clar.question }));
  const error = h("p", { class: "iv-error", role: "alert", "data-hook": "iv-error", hidden: true });
  const list = h("div", { class: "iv-options", "data-hook": "iv-options" });
  for (const option of clar.options || []) {
    list.appendChild(h("button", { type: "button", class: "iv-choice", "data-hook": "iv-resolve", "data-option": option.id, text: option.label,
      on: { click: () => resolve(clar, option, error) } }));
  }
  area.appendChild(list);
  area.appendChild(error);
}

async function resolve(clar, option, error) {
  if (busy) return;
  busy = true;
  try {
    view = await apiPost(`/hounds/interview/${encodeURIComponent(sid)}/resolve`, { clarification: clar.id, option: option.id });
    busy = false;
    render();
  } catch (err) {
    busy = false;
    error.textContent = errorText(err);
    error.hidden = false;
  }
}

// ---- the end: a name, the summary, one confirm -------------------------------------------------------

function renderNameStep(area) {
  area.appendChild(h("h2", { class: "iv-step__title", tabindex: "-1", "data-hook": "iv-step-title", text: "Name your hound" }));
  const input = h("input", { type: "text", class: "iv-input", maxlength: "24", "data-hook": "iv-name", "aria-label": "Hound name",
    placeholder: "3 to 24 letters, digits, spaces or hyphens", value: named });
  const error = h("p", { class: "iv-error", role: "alert", "data-hook": "iv-error", hidden: true });
  const go = h("button", { type: "button", class: "btn btn--primary iv-go", "data-hook": "iv-review-go", text: "Show me the summary" });
  input.addEventListener("input", () => { named = input.value; go.disabled = busy || named.trim().length < 3; });
  go.disabled = named.trim().length < 3;
  go.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    go.disabled = true;
    error.hidden = true;
    try {
      shown = await apiPost(`/hounds/interview/${encodeURIComponent(sid)}/review`, { name: named.trim() });
      busy = false;
      renderReview();
    } catch (err) {
      busy = false;
      go.disabled = false;
      error.textContent = errorText(err);
      error.hidden = false;
    }
  });
  area.appendChild(h("div", { class: "iv-form" }, [input]));
  area.appendChild(error);
  area.appendChild(h("div", { class: "iv-actions" }, [go]));
}

function renderReview() {
  const box = clearNode(HOOK("iv-review"));
  HOOK("iv-shell").hidden = true;
  box.hidden = false;
  box.appendChild(h("h2", { class: "iv-step__title", tabindex: "-1", "data-hook": "iv-review-title", text: `Check ${shown.name}` }));
  box.appendChild(h("p", { class: "hd-lede", text: "This is what your hound will do. Nothing is saved until you confirm." }));
  const list = h("ul", { class: "iv-summary", "data-hook": "iv-summary" });
  for (const line of shown.summary || []) list.appendChild(h("li", { "data-hook": "iv-summary-line", text: String(line) }));
  box.appendChild(list);
  if ((shown.cant_automate || []).length) {
    const cant = h("div", { class: "iv-cantbox", "data-hook": "iv-review-cant" }, [
      h("h3", { text: `Can't automate yet (${shown.cant_automate.length})` }),
      h("p", { class: "hd-fine", text: "Kept with your strategy. The hound does not run these." })]);
    const ul = h("ul", { class: "iv-cantlist" });
    for (const item of shown.cant_automate) {
      ul.appendChild(h("li", { "data-hook": "iv-review-cant-item" }, [h("strong", { text: String(item.text) }), " ", h("span", { class: "hd-muted", text: String(item.reason) })]));
    }
    cant.appendChild(ul);
    box.appendChild(cant);
  }
  if (shown.claimed_history) {
    const c = shown.claimed_history;
    box.appendChild(h("div", { class: "iv-claimed", "data-hook": "iv-claimed" }, [
      h("h3", { text: `Your history: ${c.label}` }),
      h("p", { text: `${c.rows} dated rows kept, ${c.claimed_wins}-${c.claimed_losses}-${c.claimed_pushes} as you described it.` }),
      h("p", { class: "hd-fine", text: c.note })]));
  }
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "iv-effective", text: `It starts betting paper picks on ${shown.effective_date}. Nothing before that day is counted.` }));
  const details = h("details", { class: "iv-fingerprint" }, [h("summary", { text: "Fingerprint of this strategy" }),
    h("p", { class: "hd-fine iv-hash", "data-hook": "iv-hash", text: shown.freeze_hash })]);
  box.appendChild(details);
  const error = h("p", { class: "iv-error", role: "alert", "data-hook": "iv-error", hidden: true });
  box.appendChild(error);
  const back = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "iv-review-back", text: "Change something",
    on: { click: () => { HOOK("iv-review").hidden = true; HOOK("iv-shell").hidden = false; } } });
  const confirm = h("button", { type: "button", class: "btn btn--primary iv-go", "data-hook": "iv-confirm", text: `Create ${shown.name}` });
  confirm.addEventListener("click", () => confirmIt(confirm, error));
  box.appendChild(h("div", { class: "iv-actions" }, [back, confirm]));
}

async function confirmIt(button, error) {
  if (busy) return;
  busy = true;
  button.disabled = true;
  error.hidden = true;
  try {
    const out = await apiPost(`/hounds/interview/${encodeURIComponent(sid)}/confirm`, { name: named.trim(), freeze_hash: shown.freeze_hash });
    busy = false;
    renderDone(out);
  } catch (err) {
    busy = false;
    button.disabled = false;
    if (isUpgradeRefusal(err)) {
      const box = clearNode(HOOK("iv-review"));
      showUpgrade(box, err);
      return;
    }
    error.textContent = errorText(err);
    error.hidden = false;
  }
}

function renderDone(out) {
  HOOK("iv-review").hidden = true;
  HOOK("iv-shell").hidden = true;
  const box = clearNode(HOOK("iv-done"));
  box.hidden = false;
  const hound = out.hound || {};
  const name = hound.name || named;
  box.appendChild(h("h2", { class: "iv-step__title", tabindex: "-1", "data-hook": "iv-done-title", text: `${name} is in your kennel` }));
  box.appendChild(h("p", { class: "hd-lede", "data-hook": "iv-done-line",
    text: `It bets paper picks from ${out.record && out.record.effective_date ? out.record.effective_date : "today"} on. Every pick is recorded before the game and graded after.` }));
  const links = h("p", { class: "iv-actions" }, [
    h("a", { class: "btn btn--primary", href: `hound.html?id=${encodeURIComponent(out.hound_id)}`, "data-hook": "iv-open-hound", text: `Open ${name}` }),
    h("a", { class: "btn btn--ghost", href: "kennel.html", "data-hook": "iv-open-kennel", text: "My Kennel" })]);
  box.appendChild(links);
}

if (typeof document !== "undefined" && document.querySelector && document.querySelector("[data-hook='iv-app']")) {
  boot();
}
