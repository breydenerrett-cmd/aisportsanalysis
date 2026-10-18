/**
 * web/build-a-hound.html: build your own hound.
 *
 * THE FORM IS GENERATED FROM GET /hounds/menu AND NOTHING ELSE. No sport, market, side rule, price
 * limit or lock time is hard-coded here: if the menu does not offer it, the form does not show it. A
 * missing menu endpoint produces an honest "not switched on yet" sentence, not a form of guesses.
 *
 * SIGN-IN. Creating a hound needs an account. This page reuses the app's token handling (api.js
 * getToken); with no token it still shows the form and the live rule preview so a visitor can see what
 * they would be building, but the create button is replaced by a sign-in / request-early-access notice.
 *
 * THE PREVIEW is written by this page from the form values (hounds-core.js previewRuleSentence) and is
 * labelled "preview": the server's own rule text, shown on the hound's page after creation, is the
 * source of truth.
 *
 * LIMITS shown: name and tagline lengths, the 3-hound limit (GET /hounds/mine), and the hard notice that
 * a hound is paper only and the -200-or-worse cap is always on.
 */

import { apiGet, apiPost, getToken } from "./api.js";
import {
  h, clearNode, optionOf, buildSpec, specToForm, previewRuleSentence, describeError, houndHref, isNum,
  NAME_MAX, TAGLINE_MAX, HOUND_LIMIT,
} from "./hounds-core.js";

export const PAPER_NOTICE =
  "Paper only. Your hound never places a real bet. The -200-or-worse cap is always on.";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

const ctx = { menu: null, fields: null, signedIn: false, mine: null, limit: HOUND_LIMIT, busy: false };

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
  const items = options.map(optionOf).map((o) => {
    const input = h("input", { type, name, value: o.id, id: `hd-${name}-${o.id}` });
    return { id: o.id, input, node: h("label", { class: "hd-check", for: `hd-${name}-${o.id}` }, [input, h("span", { text: o.label })]) };
  });
  return { items, node: h("fieldset", { class: "hd-fieldset", "data-field": name }, [h("legend", { text: legend }),
    h("div", { class: "hd-checks" }, items.map((i) => i.node))]) };
}

function numberInput(range, def, extra = {}) {
  const attrs = Object.assign({ type: "number", inputmode: "numeric", step: "1" }, extra);
  if (range && isNum(range.min)) attrs.min = String(range.min);
  if (range && isNum(range.max)) attrs.max = String(range.max);
  const el = h("input", attrs);
  if (def !== undefined && def !== null) el.value = String(def);
  return el;
}

/** Build the form from the menu. Returns { form, fields } where fields exposes every control for reading. */
export function buildForm(menu) {
  const f = {};
  f.name = h("input", { type: "text", maxlength: String(NAME_MAX), autocomplete: "off", "data-hook": "f-name" });
  f.tagline = h("input", { type: "text", maxlength: String(TAGLINE_MAX), autocomplete: "off", "data-hook": "f-tagline" });
  const nameCount = h("span", { class: "hd-fine", "data-hook": "name-count", "aria-live": "off", text: `0 / ${NAME_MAX}` });
  const tagCount = h("span", { class: "hd-fine", "data-hook": "tagline-count", text: `0 / ${TAGLINE_MAX}` });
  f.nameCount = nameCount; f.tagCount = tagCount;
  f.sports = checkGroup("Sports", menu.sports || [], "checkbox", "sport");
  f.markets = checkGroup("Markets", menu.markets || [], "checkbox", "market");
  f.sides = checkGroup("Side rule", menu.side_rules || [], "radio", "side");
  f.price_min = numberInput(menu.price_band, menu.price_band && menu.price_band.min, { "data-hook": "f-price-min" });
  f.price_max = numberInput(menu.price_band, menu.price_band && menu.price_band.max, { "data-hook": "f-price-max" });
  f.min_books = numberInput(menu.books, menu.books && menu.books.min, { "data-hook": "f-books" });
  f.max_bets = numberInput(menu.max_bets_per_day, menu.max_bets_per_day && menu.max_bets_per_day.min, { "data-hook": "f-max-bets" });
  f.lock = h("select", { "data-hook": "f-lock" }, (menu.lock_minutes || []).map((m) =>
    h("option", { value: String(m), text: `${m} minutes before the start` })));
  if ((menu.lock_minutes || []).length) f.lock.value = String(menu.lock_minutes[0]);
  const pb = menu.price_band || {};
  const form = h("form", { class: "hd-form", "data-hook": "build-form", novalidate: "" }, [
    h("div", { class: "hd-field" }, [h("label", { for: "hd-name", text: "Name" }),
      (f.name.setAttribute("id", "hd-name"), f.name), h("p", { class: "hd-fine" }, [`Up to ${NAME_MAX} characters. `, nameCount])]),
    h("div", { class: "hd-field" }, [h("label", { for: "hd-tagline", text: "Tagline" }),
      (f.tagline.setAttribute("id", "hd-tagline"), f.tagline), h("p", { class: "hd-fine" }, [`Up to ${TAGLINE_MAX} characters. Describe the idea, not a promise. `, tagCount])]),
    f.sports.node, f.markets.node, f.sides.node,
    h("fieldset", { class: "hd-fieldset" }, [h("legend", { text: "Price band (American odds)" }), h("div", { class: "hd-pair" }, [
      labelled("Lowest price", f.price_min, isNum(pb.min) ? `Menu allows ${pb.min} to ${pb.max}.` : undefined),
      labelled("Highest price", f.price_max)])]),
    labelled("Books posting a price (at least)", f.min_books,
      menu.books && isNum(menu.books.min) ? `Menu allows ${menu.books.min} to ${menu.books.max}.` : undefined),
    labelled("Most bets per day", f.max_bets,
      menu.max_bets_per_day && isNum(menu.max_bets_per_day.min) ? `Menu allows ${menu.max_bets_per_day.min} to ${menu.max_bets_per_day.max}.` : undefined),
    labelled("Lock the price", f.lock),
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
  put(fields.price_min, values.price_min);
  put(fields.price_max, values.price_max);
  put(fields.min_books, values.min_books);
  put(fields.max_bets, values.max_bets_per_day);
  put(fields.lock, values.lock_minutes);
}

/** Problems with the form as it stands, in plain words; an empty list means ready to send. */
export function validate(values, menu) {
  const problems = [];
  if (!values.name) problems.push("Give your hound a name.");
  if (values.name.length > NAME_MAX) problems.push(`The name is over ${NAME_MAX} characters.`);
  if (values.tagline.length > TAGLINE_MAX) problems.push(`The tagline is over ${TAGLINE_MAX} characters.`);
  if (!values.sports.length) problems.push("Choose at least one sport.");
  if (!values.markets.length) problems.push("Choose at least one market.");
  if (!values.side_rule) problems.push("Choose a side rule.");
  const pb = menu.price_band;
  if (isNum(values.price_min) && isNum(values.price_max) && values.price_min > values.price_max) {
    problems.push("The lowest price must not be above the highest price.");
  }
  const inRange = (v, r, label) => {
    if (isNum(v) && r && ((isNum(r.min) && v < r.min) || (isNum(r.max) && v > r.max))) {
      problems.push(`${label} must be between ${r.min} and ${r.max}.`);
    }
  };
  inRange(values.price_min, pb, "The lowest price");
  inRange(values.price_max, pb, "The highest price");
  inRange(values.min_books, menu.books, "The number of books");
  inRange(values.max_bets_per_day, menu.max_bets_per_day, "Bets per day");
  return problems;
}

function errorText(err) {
  const d = err && err.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x && (x.msg || x.message)) || String(x)).join(" ");
  if (d && typeof d === "object") return d.message || d.error || JSON.stringify(d);
  return err && err.message ? err.message : "The server refused this hound.";
}

function newId(res) {
  if (!res || typeof res !== "object") return "";
  return String(res.id ?? (res.hound && res.hound.id) ?? "");
}

function renderGate() {
  const gate = q("build-gate");
  clearNode(gate);
  if (!ctx.signedIn) {
    gate.hidden = false; gate.removeAttribute("hidden");
    gate.appendChild(h("p", {}, [h("strong", { text: "Sign in to create a hound. " }),
      "You can fill in the form and watch the rule take shape; creating it needs an account."]));
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
    ? `Each person can have up to ${ctx.limit} hounds.`
    : `You have ${used} of ${ctx.limit} hounds.` }));
}

function atLimit() {
  return ctx.mine !== null && ctx.mine >= ctx.limit;
}

function refreshSubmit() {
  const btn = q("build-submit");
  if (!btn) return;
  let reason = "";
  if (!ctx.signedIn) reason = "Sign in to create your hound";
  else if (atLimit()) reason = `You already have ${ctx.limit} hounds`;
  btn.textContent = reason || "Create my hound";
  if (reason || ctx.busy) btn.setAttribute("disabled", ""); else btn.removeAttribute("disabled");
}

function refreshPreview() {
  const box = q("build-preview");
  const out = q("build-preview-text");
  if (!box || !ctx.fields) return;
  const values = readForm(ctx.fields);
  out.textContent = previewRuleSentence(values, ctx.menu);
  ctx.fields.nameCount.textContent = `${values.name.length} / ${NAME_MAX}`;
  ctx.fields.tagCount.textContent = `${values.tagline.length} / ${TAGLINE_MAX}`;
}

async function submit(evt) {
  if (evt && evt.preventDefault) evt.preventDefault();
  const msg = q("build-message");
  clearNode(msg);
  if (!ctx.signedIn) { renderGate(); return; }
  if (atLimit()) { msg.appendChild(stateBox("down", `You already have ${ctx.limit} hounds. Retire one to make room.`)); return; }
  const values = readForm(ctx.fields);
  const problems = validate(values, ctx.menu);
  if (problems.length) {
    msg.appendChild(h("div", { class: "hd-state hd-state--down", role: "alert", "data-hook": "build-problems" },
      [h("ul", {}, problems.map((p) => h("li", { text: p })))]));
    return;
  }
  ctx.busy = true; refreshSubmit();
  try {
    const res = await apiPost("/hounds", buildSpec(values));
    const id = newId(res);
    if (id) {
      msg.appendChild(h("p", { role: "status", "data-hook": "build-done", text: "Created. Taking you to your hound..." }));
      window.location.href = houndHref(id);
    } else {
      msg.appendChild(stateBox("down", "The server accepted the hound but did not say where it is. Check the race page."));
    }
  } catch (err) {
    if (err && err.status === 401) {
      ctx.signedIn = false; renderGate();
      msg.appendChild(stateBox("down", "Your sign-in was not accepted. Sign in again to create a hound."));
    } else if (err && err.status === 404) {
      msg.appendChild(stateBox("missing", "Creating hounds is not switched on yet on this server."));
    } else if (err && (err.status === null || err.status === undefined)) {
      msg.appendChild(stateBox("down", "Could not reach the server. Nothing was created; try again."));
    } else {
      msg.appendChild(h("div", { class: "hd-state hd-state--down", role: "alert", "data-hook": "build-server-error" },
        [h("p", { text: `The server did not accept this hound: ${errorText(err)}` })]));
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
  } catch (err) {
    clearNode(host);
    const e = describeError(err, "the hound menu");
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

  // the 3-hound count, when signed in
  if (ctx.signedIn) {
    try {
      const mine = await apiGet("/hounds/mine");
      const list = Array.isArray(mine) ? mine : Array.isArray(mine && mine.hounds) ? mine.hounds : [];
      ctx.mine = list.filter((x) => x && x.status !== "retired").length;
      if (mine && isNum(mine.limit)) ctx.limit = mine.limit;
    } catch (err) {
      if (err && err.status === 401) { ctx.signedIn = false; renderGate(); }
      ctx.mine = null;
    }
  }
  renderLimit();

  // ?from=<id>: pre-fill from that hound's spec
  const from = new URLSearchParams(window.location.search || "").get("from");
  if (from) {
    const note = q("build-from-note");
    try {
      const spec = await apiGet(`/hounds/${encodeURIComponent(from)}/spec`);
      applyForm(fields, specToForm(spec));
      note.textContent = "Pre-filled from that hound's rule. Give your own hound a name and change anything you like.";
    } catch (err) {
      note.textContent = "Could not load that hound's rule to pre-fill the form, so the form is blank.";
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
