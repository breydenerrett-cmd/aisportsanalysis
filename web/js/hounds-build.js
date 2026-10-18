/**
 * web/build-a-hound.html: build your own hound.
 *
 * THE FORM IS GENERATED FROM GET /hounds/menu AND NOTHING ELSE. No sport, market, side rule, price
 * limit or lock time is hard-coded here: if the menu does not offer it, the form does not show it. A
 * missing menu endpoint produces an honest "not switched on yet" sentence, not a form of guesses. The
 * menu's shape is src/hounds/user_spec.py `menu()`: name{min,max}, tagline{max}, sports[{value,label}],
 * markets[...], side_rules[{value,label,markets}], price_min{presets,lowest}, price_max{presets,highest},
 * min_books{min,max}, max_bets_per_day{min,max}, lock_minutes{choices}, max_running_per_account.
 *
 * WHAT IS POSTED is what api/hounds_create.py takes: `{spec: {...}, copied_from?}` (hounds-core.js
 * buildSpec). A copy (`?from=<id>`) is pre-filled from GET /hounds/{id}/spec, which also suggests a free
 * name, and is posted with that id as `copied_from`.
 *
 * SIGN-IN. Creating a hound needs an account. This page reuses the app's token handling (api.js
 * getToken); with no token it still shows the form and the live rule preview so a visitor can see what
 * they would be building, but the create button is replaced by a sign-in / request-early-access notice.
 *
 * THE PREVIEW is written by this page from the form values (hounds-core.js previewRuleSentence) and is
 * labelled "preview": the server's own rule text, shown on the hound's page after creation, is the
 * source of truth. A side rule that does not fit the markets chosen (a rule that names one side of a game, on a market with no sides) is
 * switched off in the form, using the `markets` list the menu gives each side rule; the server checks again.
 *
 * LIMITS shown: name and tagline lengths (from the menu), the running-hound limit (GET /hounds/mine and the
 * menu), and the hard notice that a hound is paper only and the -200-or-worse cap is always on.
 */

import { apiGet, apiPost, getToken } from "./api.js";
import {
  h, clearNode, optionOf, buildSpec, specToForm, previewRuleSentence, describeError, houndHref, isNum,
  americanDecimal, avatarSvg, NAME_MAX, TAGLINE_MAX, HOUND_LIMIT,
} from "./hounds-core.js";

export const PAPER_NOTICE =
  "Paper bets only. Your dog never places a real bet, and it never takes a price of -200 or worse.";

/**
 * Side rules, said the way bettors say them. Keyed on the menu's own `value`; the menu's plain label stays
 * beside each one as a hint, so nothing about what the rule does is hidden behind the joke. A value this
 * table does not know keeps the menu's label. `vibe` is the accessory the preview dog wears.
 */
export const SIDE_PLAY = {
  favourite: { label: "Always the chalk", vibe: "grinder" },
  underdog: { label: "Dogs only", vibe: "degen" },
  home: { label: "Home cooking", vibe: "grinder" },
  away: { label: "Road warriors", vibe: "chaos" },
  over: { label: "Overs machine", vibe: "chaos" },
  under: { label: "Unders only", vibe: "nerd" },
  market_moved_toward: { label: "Tail the steam", vibe: "degen" },
  market_moved_away: { label: "Fade the steam", vibe: "chaos" },
};

/** The menu's side rules, with the playful label first and the menu's own label kept as a hint. */
export function playfulSides(sides) {
  return (sides || []).map((o) => {
    const opt = optionOf(o);
    const play = SIDE_PLAY[opt.id];
    return play ? Object.assign({}, o, { value: opt.id, label: play.label, hint: opt.label, markets: opt.markets || o.markets })
      : o;
  });
}

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

const ctx = { menu: null, fields: null, signedIn: false, mine: null, limit: HOUND_LIMIT, busy: false,
  copiedFrom: "", nameMax: NAME_MAX, taglineMax: TAGLINE_MAX };

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

let uid = 0;
function labelled(labelText, control, hint, id) {
  const fid = id || `hd-f-${++uid}`;
  control.setAttribute("id", fid);
  return h("div", { class: "hd-field" }, [h("label", { for: fid, text: labelText }), control,
    hint ? h("p", { class: "hd-fine", text: hint }) : null]);
}

function checkGroup(legend, options, type, name) {
  const items = options.map((raw) => {
    const o = optionOf(raw);
    const hint = raw && typeof raw === "object" && raw.hint ? String(raw.hint) : "";
    const input = h("input", { type, name, value: o.id, id: `hd-${name}-${o.id}` });
    const node = h("label", { class: "hd-check", for: `hd-${name}-${o.id}` }, [input, h("span", {}, [
      h("span", { class: "hd-check__label", text: o.label }),
      hint ? h("span", { class: "hd-check__hint", text: hint }) : null])]);
    return { id: o.id, markets: o.markets, input, node };
  });
  return { items, node: h("fieldset", { class: "hd-fieldset", "data-field": name }, [h("legend", { text: legend }),
    h("div", { class: "hd-checks" }, items.map((i) => i.node))]) };
}

function numberInput(bounds, extra = {}) {
  const attrs = Object.assign({ type: "number", inputmode: "numeric", step: "1" }, extra);
  if (bounds && isNum(bounds.min)) attrs.min = String(bounds.min);
  if (bounds && isNum(bounds.max)) attrs.max = String(bounds.max);
  return h("input", attrs);
}

function presetList(id, presets) {
  return h("datalist", { id }, (presets || []).filter(isNum).map((p) => h("option", { value: String(p) })));
}

/** Build the form from the menu. Returns { form, fields } where fields exposes every control for reading. */
export function buildForm(menu) {
  const f = {};
  const nameMax = menu.name && isNum(menu.name.max) ? menu.name.max : NAME_MAX;
  const taglineMax = menu.tagline && isNum(menu.tagline.max) ? menu.tagline.max : TAGLINE_MAX;
  ctx.nameMax = nameMax;
  ctx.taglineMax = taglineMax;
  f.name = h("input", { type: "text", maxlength: String(nameMax), autocomplete: "off", "data-hook": "f-name" });
  f.tagline = h("input", { type: "text", maxlength: String(taglineMax), autocomplete: "off", "data-hook": "f-tagline" });
  const nameCount = h("span", { class: "hd-fine", "data-hook": "name-count", "aria-live": "off", text: `0 / ${nameMax}` });
  const tagCount = h("span", { class: "hd-fine", "data-hook": "tagline-count", text: `0 / ${taglineMax}` });
  f.nameCount = nameCount; f.tagCount = tagCount;
  f.sports = checkGroup("Sports", menu.sports || [], "checkbox", "sport");
  f.markets = checkGroup("Markets", menu.markets || [], "checkbox", "market");
  f.sides = checkGroup("Pick your style", playfulSides(menu.side_rules || []), "radio", "side");
  const lowest = menu.price_min && isNum(menu.price_min.lowest) ? menu.price_min.lowest : undefined;
  const highest = menu.price_max && isNum(menu.price_max.highest) ? menu.price_max.highest : undefined;
  f.price_min = numberInput({ min: lowest, max: highest }, { "data-hook": "f-price-min", list: "hd-presets-min", placeholder: "e.g. -150" });
  f.price_max = numberInput({ min: lowest, max: highest }, { "data-hook": "f-price-max", list: "hd-presets-max", placeholder: "e.g. +120" });
  f.min_books = numberInput(menu.min_books, { "data-hook": "f-books" });
  if (menu.min_books && isNum(menu.min_books.min)) f.min_books.value = String(menu.min_books.min);
  f.max_bets = numberInput(menu.max_bets_per_day, { "data-hook": "f-max-bets" });
  if (menu.max_bets_per_day && isNum(menu.max_bets_per_day.min)) f.max_bets.value = String(menu.max_bets_per_day.min);
  const choices = menu.lock_minutes && Array.isArray(menu.lock_minutes.choices) ? menu.lock_minutes.choices : [];
  f.lock = h("select", { "data-hook": "f-lock" }, choices.map((m) =>
    h("option", { value: String(m), text: `${m} minutes before the start` })));
  if (choices.length) f.lock.value = String(choices[0]);
  const bounds = (b, label) => (b && isNum(b.min) ? `${label} ${b.min} to ${b.max}.` : undefined);
  const form = h("form", { class: "hd-form", "data-hook": "build-form", novalidate: "" }, [
    h("div", { class: "hd-field" }, [h("label", { for: "hd-name", text: "Name your dog" }),
      (f.name.setAttribute("id", "hd-name"), f.name),
      h("p", { class: "hd-fine" }, [`${menu.name && isNum(menu.name.min) ? `${menu.name.min} to ` : "Up to "}${nameMax} characters. `, nameCount])]),
    h("div", { class: "hd-field" }, [h("label", { for: "hd-tagline", text: "One-line bio" }),
      (f.tagline.setAttribute("id", "hd-tagline"), f.tagline),
      h("p", { class: "hd-fine" }, [`Up to ${taglineMax} characters. Say what it does, not what it'll win. `, tagCount])]),
    f.sports.node, f.markets.node, f.sides.node,
    h("fieldset", { class: "hd-fieldset" }, [h("legend", { text: "Price range (American odds)" }), h("div", { class: "hd-pair" }, [
      labelled("Shortest price", f.price_min, menu.price_cap_note || undefined),
      labelled("Longest price", f.price_max)]),
      presetList("hd-presets-min", menu.price_min && menu.price_min.presets),
      presetList("hd-presets-max", menu.price_max && menu.price_max.presets)]),
    labelled("Books quoting the price (at least)", f.min_books, bounds(menu.min_books, "Menu allows")),
    labelled("Most bets a day", f.max_bets, bounds(menu.max_bets_per_day, "Menu allows")),
    labelled("When it bets", f.lock),
  ]);
  return { form, fields: f };
}

/** Current form values, as numbers/arrays. */
export function readForm(fields) {
  const num = (el) => (el.value === "" || el.value === undefined ? null : Number(el.value));
  const checked = (g) => g.items.filter((i) => i.input.checked).map((i) => i.id);
  return {
    name: String(fields.name.value || "").trim(),
    tagline: String(fields.tagline.value || "").trim(),
    sports: checked(fields.sports),
    markets: checked(fields.markets),
    side_rule: checked(fields.sides)[0] || "",
    price_min: num(fields.price_min),
    price_max: num(fields.price_max),
    min_books: num(fields.min_books),
    max_bets_per_day: num(fields.max_bets),
    lock_minutes: fields.lock.value === "" || fields.lock.value === undefined ? null : Number(fields.lock.value),
  };
}

/** Put prefilled values (from /hounds/{id}/spec, via specToForm) into the controls the menu offers. */
export function applyForm(fields, values) {
  const setChecks = (g, ids) => { for (const i of g.items) i.input.checked = ids.includes(i.id); };
  if (values.sports && values.sports.length) setChecks(fields.sports, values.sports);
  if (values.markets && values.markets.length) setChecks(fields.markets, values.markets);
  if (values.side_rule) setChecks(fields.sides, [values.side_rule]);
  const put = (el, v) => { if (v !== undefined && v !== null) el.value = String(v); };
  put(fields.name, values.name);
  put(fields.tagline, values.tagline);
  put(fields.price_min, values.price_min);
  put(fields.price_max, values.price_max);
  put(fields.min_books, values.min_books);
  put(fields.max_bets, values.max_bets_per_day);
  put(fields.lock, values.lock_minutes);
}

/** Switch off side rules that do not fit the markets chosen, from the `markets` list the menu gives each. */
export function refreshSideRules(fields) {
  const chosen = fields.markets.items.filter((i) => i.input.checked).map((i) => i.id);
  for (const item of fields.sides.items) {
    const fits = !item.markets || chosen.every((m) => item.markets.includes(m));
    item.input.disabled = !fits;
    if (!fits && item.input.checked) item.input.checked = false;
    if (fits) item.node.removeAttribute("title");
    else item.node.setAttribute("title", "This rule does not apply to the markets chosen.");
  }
}

/** Problems with the form as it stands, in plain words; an empty list means ready to send. */
export function validate(values, menu) {
  const problems = [];
  const nameMax = menu.name && isNum(menu.name.max) ? menu.name.max : NAME_MAX;
  const nameMin = menu.name && isNum(menu.name.min) ? menu.name.min : 1;
  const taglineMax = menu.tagline && isNum(menu.tagline.max) ? menu.tagline.max : TAGLINE_MAX;
  if (!values.name) problems.push("Give your dog a name.");
  else if (values.name.length < nameMin) problems.push(`The name needs at least ${nameMin} characters.`);
  if (values.name.length > nameMax) problems.push(`The name is over ${nameMax} characters.`);
  if (values.tagline.length > taglineMax) problems.push(`The tagline is over ${taglineMax} characters.`);
  if (!values.sports.length) problems.push("Choose at least one sport.");
  if (!values.markets.length) problems.push("Choose at least one market.");
  if (!values.side_rule) problems.push("Choose a side rule.");
  const lowest = menu.price_min && isNum(menu.price_min.lowest) ? menu.price_min.lowest : null;
  const highest = menu.price_max && isNum(menu.price_max.highest) ? menu.price_max.highest : null;
  const priceProblem = (v, label) => {
    if (!isNum(v)) return `Enter the ${label} price, such as -150 or +120.`;
    if (!Number.isInteger(v) || (v > -100 && v < 100)) return `The ${label} price must be an American price such as -150 or +120.`;
    if (lowest !== null && v < 0 && v < lowest) return `The ${label} price cannot be ${lowest - 1} or worse: this program never selects a price that short.`;
    if (highest !== null && v > highest) return `The ${label} price cannot be longer than +${highest}.`;
    return null;
  };
  const pMin = priceProblem(values.price_min, "shortest");
  const pMax = priceProblem(values.price_max, "longest");
  if (pMin) problems.push(pMin);
  if (pMax) problems.push(pMax);
  if (!pMin && !pMax && americanDecimal(values.price_min) > americanDecimal(values.price_max)) {
    problems.push("The longest price must be the same as or longer than the shortest price.");
  }
  const inRange = (v, r, label) => {
    if (!isNum(v) || !Number.isInteger(v)) { problems.push(`${label} must be a whole number.`); return; }
    if (r && ((isNum(r.min) && v < r.min) || (isNum(r.max) && v > r.max))) {
      problems.push(`${label} must be between ${r.min} and ${r.max}.`);
    }
  };
  inRange(values.min_books, menu.min_books, "The number of books");
  inRange(values.max_bets_per_day, menu.max_bets_per_day, "Bets per day");
  const choices = menu.lock_minutes && Array.isArray(menu.lock_minutes.choices) ? menu.lock_minutes.choices : null;
  if (choices && !choices.includes(values.lock_minutes)) problems.push("Choose when to lock the price.");
  return problems;
}

/** The server's refusal in words: a 422 carries `detail: {error: "spec_invalid", fields: {field: message}}`. */
export function errorText(err) {
  const d = err && err.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x && (x.msg || x.message)) || String(x)).join(" ");
  if (d && typeof d === "object") {
    if (d.fields && typeof d.fields === "object") {
      return Object.entries(d.fields).map(([field, msg]) => `${field.replace(/_/g, " ")} ${msg}`).join("; ");
    }
    return d.message || d.error || JSON.stringify(d);
  }
  return err && err.message ? err.message : "The server refused this dog.";
}

/** POST /hounds answers `{hound: {id, ...}}`. */
function newId(res) {
  if (!res || typeof res !== "object") return "";
  return String((res.hound && res.hound.id) ?? res.id ?? "");
}

function renderGate() {
  const gate = q("build-gate");
  clearNode(gate);
  if (!ctx.signedIn) {
    gate.hidden = false; gate.removeAttribute("hidden");
    gate.appendChild(h("p", {}, [h("strong", { text: "Sign in to send your dog in. " }),
      "You can fill in the form and watch your dog take shape; sending it in needs an account."]));
    gate.appendChild(h("p", { class: "hd-gate__links" }, [
      h("a", { class: "btn btn--primary", href: "index.html#/signup", "data-hook": "gate-early-access", text: "Request early access" }),
      " ", h("a", { class: "btn btn--ghost", href: "index.html#/signin", "data-hook": "gate-signin", text: "I have an account: sign in" })]));
  } else {
    gate.hidden = true; gate.setAttribute("hidden", "");
  }
}

function renderLimit() {
  const box = q("build-limit");
  clearNode(box);
  const used = ctx.mine === null ? null : ctx.mine;
  box.appendChild(h("p", { "data-hook": "limit-text", text: used === null
    ? `Up to ${ctx.limit} dogs a person.`
    : `You have ${used} of ${ctx.limit} dogs.` }));
}

function atLimit() {
  return ctx.mine !== null && ctx.mine >= ctx.limit;
}

function refreshSubmit() {
  const btn = q("build-submit");
  if (!btn) return;
  let reason = "";
  if (!ctx.signedIn) reason = "Sign in to send your dog in";
  else if (atLimit()) reason = `You already have ${ctx.limit} dogs`;
  btn.textContent = reason || "Send my dog in";
  if (reason || ctx.busy) btn.setAttribute("disabled", ""); else btn.removeAttribute("disabled");
}

/** The live card: the dog's portrait, name and bio as you type, wearing the vibe of the style you picked. */
export function renderDogCard(values, menu) {
  const box = q("build-dog-card");
  if (!box) return;
  clearNode(box);
  const sideLabel = (menu && (menu.side_rules || []).map(optionOf).find((o) => o.id === values.side_rule)) || null;
  const play = SIDE_PLAY[values.side_rule] || null;
  const style = play ? play.label : sideLabel ? sideLabel.label : "";
  const name = values.name || "Your dog";
  const labelsOf = (ids, list) => (ids || []).map((id) => {
    const found = ((menu && list) || []).map(optionOf).find((o) => o.id === id);
    return found ? found.label : id;
  });
  const where = [labelsOf(values.sports, menu && menu.sports).join(", "),
    labelsOf(values.markets, menu && menu.markets).join(", ").toLowerCase()].filter(Boolean).join(" ");
  const bio = values.tagline || (style ? `${style}${where ? `. ${where}` : ""}.` : "Still deciding what it's about.");
  box.appendChild(avatarSvg(name, { size: 96, vibe: play ? play.vibe : "grinder", category: "mixed" }));
  box.appendChild(h("div", { class: "hd-dogcard__text" }, [
    h("p", { class: "hd-dogcard__name", "data-hook": "dog-name", text: name }),
    h("p", { class: "hd-dogcard__bio", "data-hook": "dog-bio", text: bio }),
    style ? h("span", { class: "hd-badge", "data-hook": "dog-style", text: style }) : null,
  ]));
}

function refreshPreview() {
  const box = q("build-preview");
  const out = q("build-preview-text");
  if (!box || !ctx.fields) return;
  refreshSideRules(ctx.fields);
  const values = readForm(ctx.fields);
  renderDogCard(values, ctx.menu);
  out.textContent = previewRuleSentence(values, ctx.menu);
  ctx.fields.nameCount.textContent = `${values.name.length} / ${ctx.nameMax}`;
  ctx.fields.tagCount.textContent = `${values.tagline.length} / ${ctx.taglineMax}`;
}

async function submit(evt) {
  if (evt && evt.preventDefault) evt.preventDefault();
  const msg = q("build-message");
  clearNode(msg);
  if (!ctx.signedIn) { renderGate(); return; }
  if (atLimit()) { msg.appendChild(stateBox("down", `You already have ${ctx.limit} dogs. Retire one to make room.`)); return; }
  const values = readForm(ctx.fields);
  const problems = validate(values, ctx.menu);
  if (problems.length) {
    msg.appendChild(h("div", { class: "hd-state hd-state--down", role: "alert", "data-hook": "build-problems" },
      [h("ul", {}, problems.map((p) => h("li", { text: p })))]));
    return;
  }
  ctx.busy = true; refreshSubmit();
  try {
    const res = await apiPost("/hounds", buildSpec(values, ctx.copiedFrom));
    const id = newId(res);
    if (id) {
      msg.appendChild(h("p", { role: "status", "data-hook": "build-done", text: "Your dog's in the kennel. Taking you to it..." }));
      window.location.href = houndHref(id);
    } else {
      msg.appendChild(stateBox("down", "The server took the dog but didn't say where it is. Check the kennel."));
    }
  } catch (err) {
    if (err && err.status === 401) {
      ctx.signedIn = false; renderGate();
      msg.appendChild(stateBox("down", "Your sign-in was not accepted. Sign in again to send your dog in."));
    } else if (err && err.status === 404) {
      msg.appendChild(stateBox("missing", "Building dogs is not switched on yet on this server."));
    } else if (err && (err.status === null || err.status === undefined)) {
      msg.appendChild(stateBox("down", "Could not reach the server. Nothing was created; try again."));
    } else {
      msg.appendChild(h("div", { class: "hd-state hd-state--down", role: "alert", "data-hook": "build-server-error" },
        [h("p", { text: `The kennel didn't accept this dog: ${errorText(err)}` })]));
    }
  } finally {
    ctx.busy = false; refreshSubmit();
  }
}

export async function boot() {
  const host = q("build-form-host");
  ctx.signedIn = !!getToken();
  renderGate();
  clearNode(host);
  host.appendChild(h("p", { class: "hd-muted", text: "Loading the menu..." }));
  try {
    const menu = await apiGet("/hounds/menu");
    if (!menu || typeof menu !== "object") throw Object.assign(new Error("empty"), { status: 404 });
    ctx.menu = menu;
    if (isNum(menu.max_running_per_account)) ctx.limit = menu.max_running_per_account;
  } catch (err) {
    clearNode(host);
    const e = describeError(err, "the dog menu");
    host.appendChild(stateBox(e.kind, e.text, () => { boot(); }));
    q("build-preview").setAttribute("hidden", "");
    return;
  }
  const { form, fields } = buildForm(ctx.menu);
  ctx.fields = fields;
  clearNode(host);
  host.appendChild(form);
  q("build-preview").removeAttribute("hidden");
  q("build-preview").hidden = false;
  form.addEventListener("submit", submit);
  form.addEventListener("input", refreshPreview);
  form.addEventListener("change", refreshPreview);
  const submitBtn = q("build-submit");
  submitBtn.addEventListener("click", submit);

  // the running-hound count, when signed in: GET /hounds/mine -> {hounds: [HoundSummary], limit_running}
  if (ctx.signedIn) {
    try {
      const mine = await apiGet("/hounds/mine");
      const list = Array.isArray(mine) ? mine : Array.isArray(mine && mine.hounds) ? mine.hounds : [];
      ctx.mine = list.filter((x) => x && x.status !== "retired").length;
      if (mine && isNum(mine.limit_running)) ctx.limit = mine.limit_running;
    } catch (err) {
      if (err && err.status === 401) { ctx.signedIn = false; renderGate(); }
      ctx.mine = null;
    }
  }
  renderLimit();

  // ?from=<id>: pre-fill from that hound's spec (GET /hounds/{id}/spec -> {spec, copied_from, rule_text})
  const from = new URLSearchParams(window.location.search || "").get("from");
  if (from) {
    const note = q("build-from-note");
    try {
      const payload = await apiGet(`/hounds/${encodeURIComponent(from)}/spec`);
      const values = specToForm(payload);
      applyForm(fields, values);
      ctx.copiedFrom = values.copied_from || from;
      note.textContent = "Pre-filled from that dog's rules. The name is a suggestion, because every dog's name is unique; change it and anything else you like.";
    } catch (err) {
      note.textContent = "Couldn't load that dog's rules to pre-fill the form, so the form is blank.";
    }
    note.removeAttribute("hidden"); note.hidden = false;
  }
  refreshPreview();
  refreshSubmit();
}

export const __ctx = ctx;

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
