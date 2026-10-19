/**
 * web/build-a-hound.html: the dog builder.
 *
 * THREE STEPS, ONE DRAFT. The person types a strategy in English (step 1); `POST /hounds/english` reads it
 * into a spec DRAFT and says which words it understood, which it did not, and what it had to assume; the
 * draft is shown as plain sentences and as rule cards (step 2) that can be edited directly; the person
 * names and dresses the dog and saves it (step 3). Nothing a parser or a translator produced is saved
 * without that screen.
 *
 * NOTHING HERE LISTS A CONDITION. Every sport, market, side, condition and its bounds, colour, badge, stake
 * and ranking choice comes from `GET /hounds/builder/menu` (src/hounds/user_spec.py `builder_menu`); a
 * condition the menu marks unavailable is shown disabled with the menu's reason. The server is the only
 * validator: every edit is sent to `POST /hounds/builder/preview`, which validates, returns the rules as
 * sentences, counts what the spec would bet on today's board and writes nothing; a refusal comes back as
 * per-field reasons that are shown, never repaired.
 *
 * WHAT IS POSTED. A new dog: `POST /hounds {spec}`. An edit of a saved dog: `POST /hounds/{id}/diff {spec}`
 * (a plain-English list of what changes) and then `POST /hounds/{id}/version {spec}` (a new version; the old
 * record stays). Signed-out visitors can draft everything; saving asks them to sign in.
 *
 * TRANSLATOR. When the free parser cannot read everything and the owner has switched the Zapier translator
 * on, the response carries a job id; this page polls `GET /hounds/english/{job_id}` and offers the result
 * as a replacement draft. If the translator is off the page says which words were not understood and the
 * rule cards finish the job by hand.
 */

import { apiGet, apiPost, getToken } from "./api.js";
import { h, s, clearNode, describeError, houndHref, isNum, fmtPrice } from "./hounds-core.js";

export const PAPER_NOTICE =
  "Paper bets only. Your dog never places a real bet, and it never takes a price of -200 or worse.";

export const EXAMPLES = [
  "Bet home underdogs between +120 and +200 when they're on 2+ days rest. Max 2 bets a day.",
  "Fade teams after 3 straight wins",
  "Aaron Judge over 1.5 total bases when he's hit in 3 straight games",
  "Unders when the temperature is below 55 degrees",
  "Only NFL spreads under 7. Max 2 bets a day",
  "Bet the road underdogs on the road at +130 or longer, and bet unders when it's windy",
];

const PREVIEW_DEBOUNCE_MS = 250;
const JOB_POLL_MS = 2000;
const JOB_POLL_MAX = 30;

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
const clone = (x) => JSON.parse(JSON.stringify(x));

const S = {
  menu: null, spec: null, signedIn: false, mine: [], edit: null, diffReady: false, busy: false,
  understood: [], notRead: [], assumed: [], sentences: [], problems: [], saveProblems: [], previewSeq: 0, previewTimer: null,
  jobTimer: null, jobPolls: 0, jobId: null, copiedFrom: "", pendingTranslation: null,
};

// ---- the menu ---------------------------------------------------------------------------------------

function market(menu, value) { return (menu.markets || []).find((m) => m.value === value); }

function kindOf(rule) {
  const m = S.menu && rule.markets && rule.markets.length ? market(S.menu, rule.markets[0]) : null;
  return m ? m.kind : "ml_spread";
}

/** The sports every chosen market is offered in. Read from the menu; nothing here names a sport. */
function allowedSports(rule) {
  const picked = (rule.markets || []).map((v) => market(S.menu, v)).filter(Boolean);
  return S.menu.sports.map((x) => x.value).filter((sp) => picked.every((m) => !m.sports || m.sports.includes(sp)));
}

function blankRule() {
  const m = S.menu;
  const first = m.markets[0];
  return { label: "", sports: [m.sports[0].value], markets: [first.value],
    side: (m.sides.find((x) => x.value === "either") || m.sides[0]).value, price_min: m.price.lowest,
    price_max: m.price.highest, line_min: null, line_max: null,
    min_books: first.kind === "prop" ? m.min_books.default_prop : m.min_books.default_game, when: null };
}

function blankSpec() {
  const m = S.menu;
  return { version: 2, name: "", tagline: "", color: m.colors[0].value, badge: m.badges[0].value,
    lock_minutes: m.lock_minutes.default, max_bets_per_day: m.max_bets_per_day.default,
    stake_units: m.stake_units.default, rank_by: m.rank_by[0].value, rules: [blankRule()] };
}

/** Fill the defaults a parser draft leaves out, so every card has a value in every control. */
function normaliseSpec(raw) {
  const base = blankSpec();
  const out = Object.assign(base, clone(raw || {}));
  out.rules = (out.rules || []).map((r) => {
    const rule = Object.assign(blankRule(), r);
    const kind = kindOf(rule);
    if (r.min_books === undefined) rule.min_books = kind === "prop" ? S.menu.min_books.default_prop : S.menu.min_books.default_game;
    if (!rule.when || !rule.when.items || !rule.when.items.length) rule.when = null;
    return rule;
  });
  if (!out.rules.length) out.rules = [blankRule()];
  return out;
}

// ---- small widgets ----------------------------------------------------------------------------------

let uid = 0;
const nextId = (p) => `${p}-${++uid}`;

function field(labelText, control, hint) {
  const id = nextId("bd");
  control.setAttribute("id", id);
  return h("div", { class: "hd-field bd-field" }, [h("label", { for: id, text: labelText }), control,
    hint ? h("p", { class: "hd-fine", text: hint }) : null]);
}

function selectOf(options, value, onChange, attrs = {}) {
  const sel = h("select", attrs, options.map((o) => h("option", { value: o.value, text: o.label })));
  sel.value = value;
  const fire = () => onChange(sel.value);
  sel.addEventListener("change", fire);
  sel.addEventListener("input", fire);
  return sel;
}

function numberField(param, value, onChange, attrs = {}) {
  const a = Object.assign({ type: "number", inputmode: "decimal" }, attrs);
  if (isNum(param.min)) a.min = String(param.min);
  if (isNum(param.max)) a.max = String(param.max);
  if (isNum(param.step)) a.step = String(param.step);
  const input = h("input", a);
  input.value = value === null || value === undefined ? "" : String(value);
  const fire = () => {
    const raw = String(input.value).trim();
    onChange(raw === "" ? null : Number(raw));
  };
  input.addEventListener("input", fire);
  input.addEventListener("change", fire);
  return input;
}

function chipButton(label, pressed, onClick, attrs = {}) {
  return h("button", Object.assign({ type: "button", class: "bd-chip", "aria-pressed": pressed ? "true" : "false",
    text: label, on: { click: onClick } }, attrs));
}

// ---- the conditions' controls ---------------------------------------------------------------------------

function condMenu(id) { return (S.menu.conditions || []).find((c) => c.id === id); }

function allowedChoices(param, cond, kind) {
  const choices = param.choices || [];
  if (param.name === "who" && kind === "total") return choices.filter((c) => ["home", "away", "either", "both"].includes(c.value));
  if (param.name === "of") {
    if (kind === "total") return choices.filter((c) => ["home", "away"].includes(c.value));
    if (kind === "ml_spread") return choices.filter((c) => c.value !== "player");
  }
  return choices;
}

function teamsForRule(rule) {
  return (S.menu.teams || []).filter((t) => (rule.sports || []).includes(t.sport));
}

function paramControl(cond, param, item, rule, onChange) {
  const kind = kindOf(rule);
  const value = item[param.name];
  if (param.kind === "choice") {
    const opts = allowedChoices(param, cond, kind);
    const sel = selectOf(opts, opts.some((o) => o.value === value) ? value : (opts[0] || {}).value, (v) => { item[param.name] = v; onChange(); },
      { "data-param": param.name });
    if (!opts.some((o) => o.value === value) && opts[0]) item[param.name] = opts[0].value;
    return field(param.label, sel);
  }
  if (param.kind === "int" || param.kind === "number") {
    const input = numberField(param, value, (v) => { item[param.name] = v; onChange(); }, { "data-param": param.name });
    return field(param.label, input);
  }
  if (param.kind === "multi") {
    const chosen = new Set(value || []);
    const box = h("div", { class: "bd-chips", role: "group", "aria-label": param.label, "data-param": param.name });
    for (const c of param.choices) {
      box.appendChild(chipButton(c.label, chosen.has(c.value), () => {
        if (chosen.has(c.value)) chosen.delete(c.value); else chosen.add(c.value);
        item[param.name] = param.choices.map((x) => x.value).filter((v) => chosen.has(v));
        onChange(true);
      }));
    }
    return h("div", { class: "hd-field bd-field" }, [h("span", { class: "bd-label", text: param.label }), box]);
  }
  if (param.kind === "teams") {
    const list = teamsForRule(rule);
    const chosen = value || [];
    const chips = h("div", { class: "bd-chips", "data-param": param.name }, chosen.map((v) => {
      const t = (S.menu.teams || []).find((x) => x.value === v);
      return chipButton(`${t ? t.label : v} (remove)`, true, () => {
        item[param.name] = chosen.filter((x) => x !== v);
        onChange(true);
      });
    }));
    const options = [{ value: "", label: "Add a team..." }].concat(list.filter((t) => !chosen.includes(t.value))
      .map((t) => ({ value: t.value, label: `${t.label} (${t.sport})` })));
    const sel = selectOf(options, "", (v) => {
      if (!v || chosen.length >= (S.menu.limits.max_list || 5)) return;
      item[param.name] = chosen.concat([v]);
      onChange(true);
    });
    return h("div", { class: "hd-field bd-field" }, [h("span", { class: "bd-label", text: param.label }), chips, field("Team", sel)]);
  }
  if (param.kind === "players") {
    const input = h("input", { type: "text", maxlength: "200", placeholder: "Aaron Judge, Shohei Ohtani", "data-param": param.name });
    input.value = (value || []).join(", ");
    const fire = () => {
      item[param.name] = String(input.value).split(",").map((x) => x.trim()).filter(Boolean);
      onChange();
    };
    input.addEventListener("input", fire);
    input.addEventListener("change", fire);
    return field(param.label + " (names, separated by commas)", input);
  }
  if (param.kind === "letter") {
    const input = h("input", { type: "text", maxlength: "1", size: "2", "data-param": param.name });
    input.value = value || "";
    const fire = () => { item[param.name] = String(input.value).trim().toUpperCase(); onChange(); };
    input.addEventListener("input", fire);
    input.addEventListener("change", fire);
    return field(param.label, input);
  }
  return null;
}

function conditionOptionsFor(rule) {
  const kind = kindOf(rule);
  const markets = rule.markets || [];
  return (S.menu.conditions || []).filter((c) => c.kinds.includes(kind)
    && (rule.sports || []).every((sp) => c.sports.includes(sp))
    && (!c.only_markets.length || markets.every((m) => c.only_markets.includes(m))));
}

function addConditionControl(rule, group, onChange) {
  const options = conditionOptionsFor(rule);
  const sel = h("select", { "data-hook": "add-condition", "aria-label": "Add a condition" });
  sel.appendChild(h("option", { value: "", text: "Add a condition..." }));
  const groups = {};
  for (const c of options) (groups[c.group] ||= []).push(c);
  for (const [name, items] of Object.entries(groups)) {
    sel.appendChild(h("optgroup", { label: name }, items.map((c) => h("option", Object.assign({ value: c.id,
      text: c.available ? c.label : `${c.label} (not available yet)` }, c.available ? {} : { disabled: true })))));
  }
  sel.value = "";
  const fire = () => {
    const id = sel.value;
    const cond = condMenu(id);
    if (!id || !cond || !cond.available) return;
    const item = { id };
    for (const p of cond.params) item[p.name] = Array.isArray(p.default) ? p.default.slice() : p.default;
    group.items.push(item);
    onChange(true);
  };
  sel.addEventListener("change", fire);
  sel.addEventListener("input", fire);
  return sel;
}

function renderGroup(rule, group, depth, parent, onChange) {
  const node = h("div", { class: `bd-group bd-group--${depth}`, "data-hook": "cond-group" });
  const head = h("div", { class: "bd-group__head" }, [
    selectOf([{ value: "all", label: "All of these must be true (AND)" }, { value: "any", label: "Any one of these is enough (OR)" }],
      group.op || "all", (v) => { group.op = v; onChange(true); }, { "data-hook": "group-op", "aria-label": "How these conditions combine" })]);
  if (parent) head.appendChild(h("button", { type: "button", class: "btn btn--ghost bd-x", "data-hook": "remove-group",
    text: "Remove group", on: { click: () => { parent.items = parent.items.filter((x) => x !== group); onChange(true); } } }));
  node.appendChild(head);
  for (const item of group.items) {
    if (item.items) { node.appendChild(renderGroup(rule, item, depth + 1, group, onChange)); continue; }
    const cond = condMenu(item.id);
    const row = h("div", { class: "bd-cond", "data-hook": "condition", "data-cond": item.id });
    row.appendChild(h("div", { class: "bd-cond__head" }, [
      h("strong", { class: "bd-cond__name", text: cond ? cond.label : item.id }),
      h("button", { type: "button", class: "btn btn--ghost bd-x", "data-hook": "remove-condition", text: "Remove",
        "aria-label": `Remove ${cond ? cond.label : item.id}`,
        on: { click: () => { group.items = group.items.filter((x) => x !== item); if (!group.items.length && parent) parent.items = parent.items.filter((x) => x !== group); onChange(true); } } })]));
    const params = h("div", { class: "bd-cond__params" });
    if (cond) for (const p of cond.params) { const c = paramControl(cond, p, item, rule, onChange); if (c) params.appendChild(c); }
    row.appendChild(params);
    node.appendChild(row);
  }
  const foot = h("div", { class: "bd-group__foot" }, [addConditionControl(rule, group, onChange)]);
  if (depth < (S.menu.limits.max_depth || 3)) {
    foot.appendChild(h("button", { type: "button", class: "btn btn--ghost", "data-hook": "add-group", text: "Add an any-of group",
      on: { click: () => { group.items.push({ op: "any", items: [] }); onChange(true); } } }));
  }
  node.appendChild(foot);
  return node;
}

// ---- the rule cards ---------------------------------------------------------------------------------

function ruleCard(rule, index, onChange) {
  const menu = S.menu;
  const kind = kindOf(rule);
  const card = h("article", { class: "bd-card", "data-hook": "rule-card", "aria-label": `Rule ${index + 1}` });
  card.appendChild(h("div", { class: "bd-card__head" }, [
    h("h3", { class: "bd-card__title", text: `Rule ${index + 1}` }),
    S.spec.rules.length > 1 ? h("button", { type: "button", class: "btn btn--ghost bd-x", "data-hook": "remove-rule", text: "Remove rule",
      on: { click: () => { S.spec.rules.splice(index, 1); onChange(true); } } }) : null]));

  // sports
  const sports = h("div", { class: "bd-chips", role: "group", "aria-label": "Sports", "data-hook": "rule-sports" });
  for (const sp of menu.sports) {
    const on = rule.sports.includes(sp.value);
    const blocked = !allowedSports(rule).includes(sp.value);
    sports.appendChild(chipButton(sp.label, on, () => {
      const set = new Set(rule.sports);
      if (set.has(sp.value)) set.delete(sp.value); else set.add(sp.value);
      if (!set.size) return;
      rule.sports = menu.sports.map((x) => x.value).filter((v) => set.has(v));
      onChange(true);
    }, Object.assign({ "data-sport": sp.value }, blocked ? { disabled: true, title: "Not offered for the markets chosen" } : {})));
  }
  card.appendChild(h("div", { class: "hd-field bd-field" }, [h("span", { class: "bd-label", text: "Sport" }), sports]));

  // markets, grouped by kind; a rule is one kind
  const markets = h("div", { class: "bd-marketgroups", "data-hook": "rule-markets" });
  const groupsDef = [["ml_spread", "Game bets"], ["total", "Game totals"], ["prop", "Player props"]];
  for (const [gk, title] of groupsDef) {
    const ms = menu.markets.filter((m) => m.kind === gk);
    const box = h("div", { class: "bd-chips", role: "group", "aria-label": title });
    for (const m of ms) {
      const on = rule.markets.includes(m.value);
      const wrongKind = rule.markets.length && kind !== gk && !on;
      box.appendChild(chipButton(m.label, on, () => {
        let next;
        if (kind !== gk) next = [m.value];
        else if (on) next = rule.markets.filter((x) => x !== m.value);
        else next = rule.markets.concat([m.value]);
        if (!next.length) return;
        rule.markets = menu.markets.map((x) => x.value).filter((v) => next.includes(v));
        const nk = kindOf(rule);
        const ok = allowedSports(rule);
        rule.sports = rule.sports.filter((v) => ok.includes(v));
        if (!rule.sports.length) rule.sports = ok.slice(0, 1);
        const allowed = menu.side_by_kind[nk];
        if (!allowed.includes(rule.side)) rule.side = "either";
        rule.min_books = nk === "prop" ? menu.min_books.default_prop : menu.min_books.default_game;
        // a condition that does not fit the new kind would be refused; drop it with the change
        rule.when = pruneConditions(rule, rule.when);
        onChange(true);
      }, Object.assign({ "data-market": m.value }, wrongKind ? { "data-switch": "kind" } : {})));
    }
    markets.appendChild(h("div", { class: "bd-marketgroup" }, [h("span", { class: "bd-label", text: title }), box]));
  }
  card.appendChild(h("div", { class: "hd-field bd-field" }, [h("span", { class: "bd-label", text: "Market" }), markets,
    h("p", { class: "hd-fine", text: "A rule is one kind of bet: game bets, totals or player props. Picking another kind switches the rule." })]));

  // side
  const sideLabels = Object.fromEntries(menu.sides.map((x) => [x.value, x.label]));
  const sideOptions = (menu.side_by_kind[kind] || ["either"]).map((v) => ({ value: v, label: sideLabels[v] || v }));
  card.appendChild(field("Which side it backs", selectOf(sideOptions, rule.side, (v) => { rule.side = v; onChange(true); },
    { "data-hook": "rule-side" })));

  // price, line, books
  const row = h("div", { class: "bd-row" });
  row.appendChild(field("Shortest average price", numberField({ min: menu.price.lowest, max: menu.price.highest, step: 1 }, rule.price_min,
    (v) => { rule.price_min = v; onChange(); }, { "data-hook": "price-min", list: "bd-price-short" })));
  row.appendChild(field("Longest average price", numberField({ min: menu.price.lowest, max: menu.price.highest, step: 1 }, rule.price_max,
    (v) => { rule.price_max = v; onChange(); }, { "data-hook": "price-max", list: "bd-price-long" })));
  if (rule.markets.some((v) => (market(menu, v) || {}).has_line !== false)) {
    row.appendChild(field("Line from (optional)", numberField({ min: menu.line.min, max: menu.line.max, step: 0.5 }, rule.line_min,
      (v) => { rule.line_min = v; onChange(); }, { "data-hook": "line-min" })));
    row.appendChild(field("Line to (optional)", numberField({ min: menu.line.min, max: menu.line.max, step: 0.5 }, rule.line_max,
      (v) => { rule.line_max = v; onChange(); }, { "data-hook": "line-max" })));
  }
  row.appendChild(field("Books quoting at least", numberField({ min: menu.min_books.min, max: menu.min_books.max, step: 1 }, rule.min_books,
    (v) => { rule.min_books = v; onChange(); }, { "data-hook": "min-books" })));
  card.appendChild(row);
  card.appendChild(h("p", { class: "hd-fine", text: menu.price_cap_note + " A line is the spread, total or prop line of the side it backs." }));

  // conditions
  const condBox = h("div", { class: "bd-conds", "data-hook": "conditions" });
  if (!rule.when) rule.when = { op: "all", items: [] };
  condBox.appendChild(h("h4", { class: "bd-subhead", text: "Only when" }));
  condBox.appendChild(renderGroup(rule, rule.when, 1, null, onChange));
  card.appendChild(condBox);
  return card;
}

/** Drop conditions the rule's (new) kind or sports cannot use, so a market switch never leaves a refused rule behind. */
function pruneConditions(rule, tree) {
  if (!tree) return tree;
  const ok = new Set(conditionOptionsFor(rule).map((c) => c.id));
  const walk = (g) => ({ op: g.op, items: g.items.map((i) => (i.items ? walk(i) : (ok.has(i.id) ? i : null))).filter(Boolean) });
  return walk(tree);
}

function globalsGrid(onChange) {
  const m = S.menu;
  const grid = clearNode(q("globals-grid"));
  grid.appendChild(field("Decide this long before the start", selectOf(m.lock_minutes.choices.map((v) => ({ value: String(v), label: `${v} minutes` })),
    String(S.spec.lock_minutes), (v) => { S.spec.lock_minutes = Number(v); onChange(); }, { "data-hook": "g-lock" })));
  grid.appendChild(field("Most bets a day", numberField({ min: m.max_bets_per_day.min, max: m.max_bets_per_day.max, step: 1 }, S.spec.max_bets_per_day,
    (v) => { S.spec.max_bets_per_day = v; onChange(); }, { "data-hook": "g-bets" })));
  grid.appendChild(field("Stake per bet (paper units)", selectOf(m.stake_units.choices.map((v) => ({ value: String(v), label: `${v} unit${v === 1 ? "" : "s"}` })),
    String(S.spec.stake_units), (v) => { S.spec.stake_units = Number(v); onChange(); }, { "data-hook": "g-stake" }), m.stake_note));
  grid.appendChild(field("If more picks qualify than the cap, take", selectOf(m.rank_by.map((r) => ({ value: r.value, label: r.label })),
    S.spec.rank_by, (v) => { S.spec.rank_by = v; onChange(); }, { "data-hook": "g-rank" }), m.ranking_note));
}

// ---- rendering --------------------------------------------------------------------------------------

function renderRules() {
  const has = !!S.spec && S.spec.rules.length > 0 && S.started;
  q("rules-empty").hidden = has;
  q("rules-body").hidden = !has;
  if (!has) return;
  const cards = clearNode(q("rule-cards"));
  S.spec.rules.forEach((rule, i) => cards.appendChild(ruleCard(rule, i, changed)));
  q("add-rule").disabled = S.spec.rules.length >= S.menu.limits.max_rules;
  q("rule-limit").textContent = `${S.spec.rules.length} of ${S.menu.limits.max_rules} rules`;
  globalsGrid(changed);
  renderSentences();
}

function renderSentences() {
  const box = clearNode(q("rule-sentences"));
  if (S.sentences.length) {
    box.appendChild(h("ol", { class: "bd-sentence-list" }, S.sentences.map((t) => h("li", { text: t }))));
  } else {
    box.appendChild(h("p", { class: "hd-fine", text: "Checking your rules..." }));
  }
  const problems = q("build-problems");
  clearNode(problems);
  const all = S.saveProblems.concat(S.problems);
  problems.hidden = !all.length;
  if (all.length) {
    problems.appendChild(h("p", { class: "bd-problems__lead", text: "These need fixing before the dog can run:" }));
    problems.appendChild(h("ul", {}, all.map((p) => h("li", { text: p }))));
  }
}

function friendlyField(key) {
  const m = /^rules\[(\d+)\]\.(.*)$/.exec(key);
  if (m) return `Rule ${Number(m[1]) + 1}, ${m[2].replace(/\./g, " / ").replace(/_/g, " ")}`;
  return key.replace(/_/g, " ");
}

function problemsFrom(detail) {
  const fields = detail && detail.fields ? detail.fields : null;
  if (!fields) return [typeof detail === "string" ? detail : "The server did not accept that."];
  return Object.entries(fields).map(([k, v]) => `${friendlyField(k)}: ${v}`);
}

function setCount(text) {
  q("preview-count").textContent = text;
  const pill = q("preview-pill");
  pill.hidden = !text || !S.started;
  pill.textContent = text;
}

function renderPreview(res) {
  const list = clearNode(q("preview-list"));
  if (!res) {
    setCount(S.problems.length ? "Fix the rules to see a preview." : "Nothing to preview yet.");
    return;
  }
  const n = res.qualifying;
  const cap = res.max_bets_per_day;
  if (!res.games_on_board) {
    setCount("No games on today's board yet, so there is nothing to count.");
  } else if (!n) {
    setCount(`0 bets today: nothing on today's board passes your rules (${res.games_on_board} games checked).`);
  } else if (n > cap) {
    setCount(`${res.would_bet} bet${res.would_bet === 1 ? "" : "s"} today: ${n} qualify and your cap is ${cap}.`);
  } else {
    setCount(`${n} bet${n === 1 ? "" : "s"} today.`);
  }
  for (const p of res.picks || []) {
    const start = p.start_utc ? new Date(p.start_utc) : null;
    const when = start && !Number.isNaN(start.getTime()) ? start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
    list.appendChild(h("li", { class: `bd-pick${p.would_bet ? "" : " bd-pick--over"}`, "data-hook": "preview-pick" }, [
      h("strong", { text: p.selection }),
      h("span", { class: "bd-pick__price", text: ` ${fmtPrice(p.price)}` }),
      h("span", { class: "hd-fine", text: ` ${p.away_team} at ${p.home_team}${when ? ", " + when : ""}${p.locked ? "" : ", not decided yet"}${p.would_bet ? "" : ", over your daily cap"}` })]));
  }
}

function previewBody() {
  const spec = clone(S.spec);
  if (!spec.name) spec.name = "Draft Dog";
  return { spec: cleanSpec(spec) };
}

/** Send only what the server's menu knows: empty optionals become absent, empty condition groups vanish. */
function cleanSpec(spec) {
  const tree = (g) => {
    const items = (g.items || []).map((i) => (i.items ? tree(i) : i)).filter((i) => i && (!i.items || i.items.length));
    return items.length ? { op: g.op || "all", items } : null;
  };
  spec.rules = spec.rules.map((r) => {
    const out = Object.assign({}, r);
    out.when = r.when ? tree(r.when) : null;
    if (out.line_min === null || out.line_min === undefined) delete out.line_min;
    if (out.line_max === null || out.line_max === undefined) delete out.line_max;
    return out;
  });
  delete spec.sports; delete spec.markets; delete spec.side_rule;
  return spec;
}

async function runPreview() {
  const seq = ++S.previewSeq;
  if (!S.started) return;
  try {
    const res = await apiPost("/hounds/builder/preview", previewBody());
    if (seq !== S.previewSeq) return;
    S.problems = [];
    S.sentences = res.sentences || [];
    renderSentences();
    renderPreview(res);
    updateDogCard();
  } catch (err) {
    if (seq !== S.previewSeq) return;
    if (err && err.status === 422) {
      S.problems = problemsFrom(err.detail);
      renderSentences();
      renderPreview(null);
    } else {
      S.problems = [];
      setCount(describeError(err, "the preview").text);
    }
  }
}

function schedulePreview() {
  if (S.previewTimer) clearTimeout(S.previewTimer);
  S.previewTimer = setTimeout(runPreview, PREVIEW_DEBOUNCE_MS);
}

/** Something about the draft changed. `structural` rebuilds the cards; a plain value edit leaves the inputs alone. */
function changed(structural) {
  S.diffReady = false;
  q("diff").hidden = true;
  if (structural) renderRules();
  else if (S.saveProblems.length) { S.saveProblems = []; renderSentences(); }
  schedulePreview();
  updateSave();
}

// ---- step 3: identity ---------------------------------------------------------------------------------

const ICONS = {
  bone: [["M7.5 16.5 16.5 7.5", "stroke"], ["M5.8 13.6a2.3 2.3 0 1 0 3.2 3.2 2.3 2.3 0 0 0-3.2-3.2zM15 7.2a2.3 2.3 0 1 0 3.2 3.2A2.3 2.3 0 0 0 15 7.2zM4.9 17.9a2.3 2.3 0 1 0 3.2 3.2 2.3 2.3 0 0 0-3.2-3.2zM15.9 2.9a2.3 2.3 0 1 0 3.2 3.2 2.3 2.3 0 0 0-3.2-3.2z", "fill"]],
  paw: [["M12 12c3 0 6 3.3 6 6 0 2-1.8 2.5-3 2.5-1.2 0-2-.5-3-.5s-1.8.5-3 .5c-1.2 0-3-.5-3-2.5 0-2.7 3-6 6-6zM7.5 10.5c-1.4 0-2.5-1.3-2.5-2.8S6.100 5 7.500 5 10 6.200 10 7.700 8.900 10.500 7.500 10.500zM16.500 10.500c-1.400 0-2.500-1.300-2.500-2.800S15.100 5 16.500 5 19 6.200 19 7.700s-1.100 2.800-2.500 2.800zM3.500 14c-1 0-1.800-.9-1.800-2s.8-2 1.800-2 1.800.9 1.800 2-.8 2-1.800 2zM20.500 14c-1 0-1.800-.9-1.800-2s.8-2 1.800-2 1.800.9 1.800 2-.8 2-1.800 2z", "fill"]],
  bolt: [["M13 2 4 14h6l-1 8 9-12h-6z", "fill"]],
  flame: [["M12 2c1 4-3 5-3 9a4 4 0 0 0 8 0c0-2-1-3-1-5 3 2 5 5 5 8a9 9 0 0 1-18 0c0-5 5-7 9-12z", "fill"]],
  moon: [["M20 14.500A8 8 0 0 1 9.500 4a8 8 0 1 0 10.500 10.500z", "fill"]],
  star: [["M12 2l3 7 7 .6-5.300 4.700 1.600 7.200L12 17.800 5.700 21.500l1.600-7.200L2 9.600 9 9z", "fill"]],
  crown: [["M3 8l4.500 4L12 5l4.500 7L21 8l-2 11H5z", "fill"]],
  skull: [["M12 3a8 8 0 0 0-5 14.200V21h3v-2h4v2h3v-3.800A8 8 0 0 0 12 3zM9 11a1.800 1.800 0 1 1 0 3.600A1.800 1.800 0 0 1 9 11zM15 11a1.800 1.800 0 1 1 0 3.600A1.800 1.800 0 0 1 15 11z", "fillevenodd"]],
  clover: [["M12 12a4 4 0 1 1 0-8 4 4 0 0 1 0 8zM12 12a4 4 0 1 1 8 0 4 4 0 0 1-8 0zM12 12a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM12 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z", "fill"]],
  anchor: [["M12 2a3 3 0 0 0-1 5.800V10H8v2h3v7.900A7 7 0 0 1 5 13H3a9 9 0 0 0 18 0h-2a7 7 0 0 1-6 6.900V12h3v-2h-3V7.800A3 3 0 0 0 12 2zM12 4a1 1 0 1 1 0 2 1 1 0 0 1 0-2z", "fillevenodd"]],
  diamond: [["M12 2l8 7-8 13L4 9z", "fill"]],
  target: [["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM12 6a6 6 0 1 1 0 12 6 6 0 0 1 0-12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z", "fillevenodd"]],
};

export function badgeIcon(id, size = 22) {
  const parts = ICONS[id] || ICONS.bone;
  const svg = s("svg", { viewBox: "0 0 24 24", width: String(size), height: String(size), "aria-hidden": "true", class: "bd-icon", focusable: "false" });
  for (const [d, mode] of parts) {
    svg.appendChild(s("path", mode === "stroke"
      ? { d, fill: "none", stroke: "currentColor", "stroke-width": "3.2", "stroke-linecap": "round" }
      : { d, fill: "currentColor", "fill-rule": mode === "fillevenodd" ? "evenodd" : "nonzero" }));
  }
  return svg;
}

function colorHex(id) { const c = (S.menu.colors || []).find((x) => x.value === id); return c ? c.hex : "#FF7A45"; }

function renderPickers() {
  const colors = clearNode(q("color-picker"));
  for (const c of S.menu.colors) {
    colors.appendChild(h("button", { type: "button", class: "bd-swatch", role: "radio", "aria-checked": S.spec.color === c.value ? "true" : "false",
      "aria-label": c.label, title: c.label, "data-color": c.value, style: `--sw:${c.hex}`,
      on: { click: () => { S.spec.color = c.value; changed(false); renderPickers(); updateDogCard(); } } }));
  }
  const badges = clearNode(q("badge-picker"));
  for (const b of S.menu.badges) {
    badges.appendChild(h("button", { type: "button", class: "bd-badge", role: "radio", "aria-checked": S.spec.badge === b.value ? "true" : "false",
      "aria-label": b.label, title: b.label, "data-badge": b.value,
      on: { click: () => { S.spec.badge = b.value; changed(false); renderPickers(); updateDogCard(); } } }, [badgeIcon(b.value)]));
  }
}

function updateDogCard() {
  if (!S.spec || !S.menu) return;
  const card = clearNode(q("build-dog-card"));
  const hex = colorHex(S.spec.color);
  card.appendChild(h("div", { class: "bd-dog", style: `--dog:${hex}` }, [
    h("span", { class: "bd-dog__badge", "data-hook": "dog-badge", "data-badge": S.spec.badge }, [badgeIcon(S.spec.badge, 34)]),
    h("div", { class: "bd-dog__text" }, [
      h("p", { class: "bd-dog__name", "data-hook": "dog-name", text: S.spec.name || "Your dog" }),
      h("p", { class: "bd-dog__tag", "data-hook": "dog-tagline", text: S.spec.tagline || "Add a catchphrase" }),
      S.sentences.length ? h("p", { class: "bd-dog__rule hd-fine", text: S.sentences[0] }) : null])]));
}

function bindIdentity() {
  const name = q("f-name"), tag = q("f-tagline");
  const sync = () => {
    S.spec.name = String(name.value).trim();
    S.spec.tagline = String(tag.value).replace(/\s+/g, " ").trim();
    q("name-count").textContent = `${name.value.length} / ${S.menu.name.max}`;
    q("tagline-count").textContent = `${tag.value.length} / ${S.menu.tagline.max}`;
    S.diffReady = false;
    q("diff").hidden = true;
    if (S.saveProblems.length) { S.saveProblems = []; renderSentences(); }
    updateDogCard();
    updateSave();
  };
  name.addEventListener("input", sync);
  tag.addEventListener("input", sync);
  name.setAttribute("maxlength", String(S.menu.name.max));
  tag.setAttribute("maxlength", String(S.menu.tagline.max));
}

function fillIdentity() {
  q("f-name").value = S.spec.name || "";
  q("f-tagline").value = S.spec.tagline || "";
  q("name-count").textContent = `${(S.spec.name || "").length} / ${S.menu.name.max}`;
  q("tagline-count").textContent = `${(S.spec.tagline || "").length} / ${S.menu.tagline.max}`;
}

// ---- step 1: English ------------------------------------------------------------------------------------

function showRead(res) {
  const wrap = q("english-read");
  wrap.hidden = false;
  S.understood = res.understood || [];
  S.notRead = res.not_understood || [];
  S.assumed = res.assumed || [];
  const ul = clearNode(q("english-understood"));
  for (const u of S.understood) {
    ul.appendChild(h("li", {}, [h("strong", { text: `"${u.text}"` }), h("span", { text: ` is read as: ${u.meaning}` })]));
  }
  if (!S.understood.length) ul.appendChild(h("li", { class: "hd-fine", text: "Nothing in that matched a rule yet." }));
  const unread = q("english-unread");
  const nr = clearNode(q("english-notread"));
  unread.hidden = !S.notRead.length;
  for (const n of S.notRead) {
    nr.appendChild(h("li", {}, [h("strong", { text: n.text ? `"${n.text}"` : "Something" }), h("span", { text: ` was not understood: ${n.reason}` })]));
  }
  const assumed = q("english-assumed");
  assumed.hidden = !S.assumed.length;
  assumed.textContent = S.assumed.length ? `Assumed, so check the cards: ${S.assumed.join("; ")}.` : "";
  q("english-translator").textContent = "";
}

function translatorLine(res) {
  const line = q("english-translator");
  if (!S.notRead.length) { line.textContent = ""; return; }
  const t = res.translation || {};
  if (t.status === "translating") line.textContent = "A second reader is taking a look at the part I could not read. The rest is already in the cards below.";
  else if (t.status === "sign_in_required") line.textContent = res.message || "Sign in and a second reader can try the part I could not read. Meanwhile the cards below let you finish by hand.";
  else line.textContent = res.message || "The cards below let you finish it by hand.";
}

function startFromDraft(res) {
  const raw = res.spec || res.draft;
  S.started = true;
  const keepIdentity = { name: S.spec ? S.spec.name : "", tagline: S.spec ? S.spec.tagline : "", color: S.spec ? S.spec.color : null, badge: S.spec ? S.spec.badge : null };
  S.spec = normaliseSpec(raw && raw.rules && raw.rules.length ? raw : null);
  if (keepIdentity.name) S.spec.name = keepIdentity.name;
  if (keepIdentity.tagline) S.spec.tagline = keepIdentity.tagline;
  if (keepIdentity.color) S.spec.color = keepIdentity.color;
  if (keepIdentity.badge) S.spec.badge = keepIdentity.badge;
  S.sentences = res.sentences || [];
  S.problems = [];
  renderRules();
  renderPickers();
  fillIdentity();
  updateDogCard();
  schedulePreview();
  updateSave();
}

async function readEnglish() {
  const text = String(q("english-input").value || "").trim();
  const status = q("english-status");
  if (!text) { status.textContent = "Type a strategy first, or pick an example."; return; }
  status.textContent = "Reading...";
  stopJobPolling();
  let res;
  try {
    res = await apiPost("/hounds/english", { text });
  } catch (err) {
    status.textContent = err && err.status === 429 ? "Slow down a little; try again in a minute." : describeError(err, "the strategy reader").text;
    return;
  }
  status.textContent = "";
  showRead(res);
  translatorLine(res);
  startFromDraft(res);
  if (res.job_id && res.status === "translating") startJobPolling(res.job_id);
}

function stopJobPolling() {
  if (S.jobTimer) clearInterval(S.jobTimer);
  S.jobTimer = null;
  S.jobId = null;
  S.pendingTranslation = null;
  const slot = q("english-translator");
  if (slot) slot.removeAttribute("data-job");
}

function startJobPolling(jobId) {
  S.jobId = jobId;
  S.jobPolls = 0;
  S.jobTimer = setInterval(pollJob, JOB_POLL_MS);
}

async function pollJob() {
  if (!S.jobId) return;
  S.jobPolls += 1;
  const line = q("english-translator");
  try {
    const job = await apiGet(`/hounds/english/${encodeURIComponent(S.jobId)}`);
    if (job.status === "translating") {
      if (S.jobPolls >= JOB_POLL_MAX) { stopJobPolling(); line.textContent = "The second reader took too long. The cards below let you finish by hand."; }
      return;
    }
    const id = S.jobId;
    stopJobPolling();
    if (job.status === "done" && job.spec) {
      S.pendingTranslation = job;
      clearNode(line);
      line.appendChild(h("span", { text: "The second reader has a version of your whole strategy. " }));
      line.appendChild(h("button", { type: "button", class: "btn btn--ghost", "data-hook": "use-translation", text: "Use its version",
        on: { click: () => { useTranslation(job); } } }));
      line.setAttribute("data-job", id);
    } else if (job.status === "refused") {
      line.textContent = "The second reader's answer did not fit the rules: " + Object.entries(job.reasons || {}).map(([k, v]) => `${friendlyField(k)}: ${v}`).join("; ") + ". The cards below let you finish by hand.";
    } else {
      line.textContent = (job.error || "The second reader could not help.") + " The cards below let you finish by hand.";
    }
  } catch (err) {
    if (S.jobPolls >= 3) { stopJobPolling(); line.textContent = describeError(err, "the second reader").text; }
  }
}

function useTranslation(job) {
  showRead({ understood: [{ text: "your whole strategy", meaning: "the second reader's version, shown in the cards below" }], not_understood: [], assumed: [] });
  q("english-translator").textContent = "Showing the second reader's version. Check every card.";
  startFromDraft({ spec: job.spec, sentences: job.sentences });
}

function exampleChips() {
  const box = clearNode(q("example-chips"));
  EXAMPLES.forEach((text) => box.appendChild(h("button", { type: "button", class: "bd-chip bd-chip--example", "data-hook": "example-chip", text,
    on: { click: () => { q("english-input").value = text; readEnglish(); } } })));
}

// ---- saving ---------------------------------------------------------------------------------------------------

function updateSave() {
  const btn = q("build-submit");
  if (!btn || !S.menu) return;
  const editing = !!S.edit;
  q("edit-cancel").hidden = !editing;
  let label = "Send my dog in";
  if (editing) label = S.diffReady ? `Save as version ${S.edit.version_no + 1}` : "Review the changes";
  btn.textContent = label;
  btn.disabled = S.busy || !S.started;
  const limit = q("limit-text");
  if (S.signedIn && !editing) {
    const running = S.mine.filter((d) => d.status === "running").length;
    const cap = S.menu.limits.max_running_per_account;
    limit.textContent = `${running} of ${cap} dogs running.`;
  } else {
    limit.textContent = S.signedIn ? "" : "Sign in to save your dog.";
  }
}

function setMessage(text, kind) {
  const box = clearNode(q("build-message"));
  if (text) box.appendChild(h("p", { class: `bd-msg bd-msg--${kind || "ok"}`, text }));
}

function serverError(text) {
  const box = q("build-server-error");
  box.hidden = !text;
  box.textContent = text || "";
}

function gate(text) {
  const box = q("build-gate");
  box.hidden = !text;
  clearNode(box);
  if (text) {
    box.appendChild(h("p", {}, [text + " ", h("a", { href: "index.html#/signin", text: "Sign in" })]));
  }
}

function saveSpec() {
  const spec = cleanSpec(clone(S.spec));
  return spec;
}

async function submit() {
  if (S.busy || !S.started) return;
  setMessage("");
  serverError("");
  S.saveProblems = [];
  if (!S.signedIn) { gate("Sign in to save your dog. Your draft stays on this page."); return; }
  if (!String(S.spec.name || "").trim()) {
    S.saveProblems = ["Name: give your dog a name (3 to 24 letters, digits, spaces or hyphens)."];
    renderSentences();
    q("f-name").focus();
    return;
  }
  S.busy = true;
  updateSave();
  try {
    if (S.edit) {
      if (!S.diffReady) {
        const res = await apiPost(`/hounds/${encodeURIComponent(S.edit.id)}/diff`, { spec: saveSpec() });
        showDiff(res.changes || []);
      } else {
        const res = await apiPost(`/hounds/${encodeURIComponent(S.edit.id)}/version`, { spec: saveSpec(), reason: "edited in the builder" });
        const dog = res.hound || {};
        setMessage(`Saved as version ${dog.version_no}. The old version keeps its record and stops betting.`, "ok");
        if (dog.id) q("build-message").appendChild(h("p", {}, [h("a", { href: houndHref(dog.id), "data-hook": "new-dog-link", text: "See your dog" })]));
        S.edit = null; S.diffReady = false;
        q("diff").hidden = true;
        await loadMine();
      }
    } else {
      const body = { spec: saveSpec() };
      if (S.copiedFrom) body.copied_from = S.copiedFrom;
      const res = await apiPost("/hounds", body);
      const dog = res.hound || {};
      setMessage(`${dog.name || "Your dog"} is in the kennel.`, "ok");
      if (dog.id) q("build-message").appendChild(h("p", {}, [h("a", { href: houndHref(dog.id), "data-hook": "new-dog-link", text: "See your dog" })]));
      await loadMine();
    }
  } catch (err) {
    handleSaveError(err);
  } finally {
    S.busy = false;
    updateSave();
  }
}

function handleSaveError(err) {
  const status = err && err.status;
  const detail = err && err.detail;
  if (status === 401 || status === 403) {
    S.signedIn = false;
    gate("Your sign-in has lapsed or this account cannot build yet.");
  } else if (status === 422 && detail && detail.fields) {
    S.saveProblems = problemsFrom(detail);
    renderSentences();
  } else if (status === 409) {
    serverError(detail && detail.message ? detail.message : "You already have the most dogs running. Retire one first.");
  } else {
    serverError(describeError(err, "your dog").text);
  }
}

function showDiff(changes) {
  const box = q("diff");
  const list = clearNode(q("diff-list"));
  box.hidden = false;
  if (!changes.length) {
    list.appendChild(h("li", { text: "Nothing has changed from the saved version." }));
    S.diffReady = false;
    return;
  }
  for (const c of changes) {
    const parts = [h("strong", { text: c.what })];
    if (c.before) parts.push(h("div", { class: "bd-diff__before", text: `Before: ${c.before}` }));
    if (c.after) parts.push(h("div", { class: "bd-diff__after", text: `After: ${c.after}` }));
    list.appendChild(h("li", { "data-hook": "diff-item" }, parts));
  }
  S.diffReady = true;
}

// ---- my dogs ----------------------------------------------------------------------------------------------------

async function loadMine() {
  const state = q("my-dogs-state");
  const list = clearNode(q("my-dogs"));
  if (!getToken()) { S.signedIn = false; S.mine = []; state.textContent = "Sign in to see the dogs you have built."; q("nav-signin").hidden = false; updateSave(); return; }
  try {
    const res = await apiGet("/hounds/mine");
    S.signedIn = true;
    S.mine = (res.hounds || []).filter((d) => d.status !== "retired");
    q("nav-signin").hidden = true;
    state.textContent = S.mine.length ? "" : "You have not built a dog yet.";
    for (const d of S.mine) list.appendChild(dogItem(d));
  } catch (err) {
    if (err && (err.status === 401 || err.status === 403)) { S.signedIn = false; state.textContent = "Sign in to see the dogs you have built."; }
    else state.textContent = describeError(err, "your dogs").text;
  }
  updateSave();
}

function dogItem(d) {
  const rec = d.record || {};
  const record = rec.bets ? `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}, ${rec.bets} bets` : "no bets yet";
  const hex = colorHex(d.color);
  return h("li", { class: "bd-dogrow", "data-hook": "my-dog", "data-id": d.id, style: `--dog:${hex}` }, [
    h("span", { class: "bd-dog__badge bd-dog__badge--sm" }, [badgeIcon(d.badge || "bone", 20)]),
    h("div", { class: "bd-dogrow__text" }, [
      h("p", { class: "bd-dogrow__name" }, [h("a", { href: houndHref(d.id), text: d.name }),
        h("span", { class: "hd-fine", text: ` v${d.version_no} · ${d.status}` })]),
      h("p", { class: "hd-fine", text: record }),
      h("details", {}, [h("summary", { text: "Its rules" }),
        h("ol", { class: "bd-sentence-list" }, (d.rule_sentences || []).map((t) => h("li", { text: t })))]),
      h("div", { class: "bd-dogrow__actions" }, [
        h("button", { type: "button", class: "btn btn--ghost", "data-hook": "edit-dog", text: "Edit",
          on: { click: () => startEdit(d) } })])])]);
}

function startEdit(d) {
  stopJobPolling();
  S.started = true;
  S.edit = { id: d.id, version_no: d.version_no, name: d.name };
  S.copiedFrom = "";
  S.diffReady = false;
  S.spec = normaliseSpec(d.spec);
  S.spec.name = d.name;
  S.spec.tagline = d.tagline || (d.spec && d.spec.tagline) || "";
  S.sentences = d.rule_sentences || [];
  S.problems = [];
  q("diff").hidden = true;
  setMessage("");
  serverError("");
  q("english-read").hidden = true;
  renderRules();
  renderPickers();
  fillIdentity();
  updateDogCard();
  updateSave();
  schedulePreview();
  q("build-title").textContent = `Edit ${d.name}`;
  const note = q("build-from-note");
  note.hidden = false;
  note.textContent = `You are editing ${d.name}, version ${d.version_no}. Saving makes version ${d.version_no + 1}; the old version keeps its record.`;
  if (typeof window.scrollTo === "function") window.scrollTo(0, 0);
}

function stopEdit() {
  S.edit = null;
  S.diffReady = false;
  q("build-title").textContent = "Build your dog";
  q("build-from-note").hidden = true;
  q("diff").hidden = true;
  updateSave();
}

// ---- boot ---------------------------------------------------------------------------------------------------------

function stateBox(kind, text) {
  return h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status", "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
}

async function boot() {
  exampleChips();
  q("english-go").addEventListener("click", readEnglish);
  q("blank-rule").addEventListener("click", () => {
    if (!S.menu) return;
    startFromDraft({ spec: blankSpec(), sentences: [] });
  });
  q("add-rule").addEventListener("click", () => {
    if (!S.spec || S.spec.rules.length >= S.menu.limits.max_rules) return;
    S.spec.rules.push(blankRule());
    changed(true);
  });
  q("build-submit").addEventListener("click", submit);
  q("edit-cancel").addEventListener("click", stopEdit);
  q("build-submit").disabled = true;

  try {
    S.menu = await apiGet("/hounds/builder/menu");
  } catch (err) {
    const box = clearNode(q("rules-empty"));
    box.appendChild(stateBox(err && err.status === 404 ? "missing" : "down", describeError(err, "the dog builder").text));
    q("english-go").disabled = true;
    q("blank-rule").disabled = true;
    return;
  }
  S.spec = blankSpec();
  S.started = false;
  bindIdentity();
  renderPickers();
  fillIdentity();
  updateDogCard();
  const datalists = h("div", { hidden: true }, [
    h("datalist", { id: "bd-price-short" }, S.menu.price.presets_short.map((p) => h("option", { value: String(p) }))),
    h("datalist", { id: "bd-price-long" }, S.menu.price.presets_long.map((p) => h("option", { value: String(p) })))]);
  q("build-app").appendChild(datalists);
  await loadMine();

  const params = new URLSearchParams(location.search);
  const editId = params.get("edit");
  const fromId = params.get("from");
  if (editId) {
    const dog = S.mine.find((d) => d.id === editId);
    if (dog) startEdit(dog);
  } else if (fromId) {
    const note = q("build-from-note");
    try {
      const res = await apiGet(`/hounds/${encodeURIComponent(fromId)}/spec`);
      S.copiedFrom = res.copied_from || fromId;
      const draft = res.draft || res.spec;
      startFromDraft({ spec: draft, sentences: res.rule_sentences || [] });
      S.spec.name = (res.spec && res.spec.name) || S.spec.name;
      fillIdentity();
      updateDogCard();
      note.hidden = false;
      note.textContent = "You are building from a copy of another dog's rules. Change anything you like; it will be a new dog of your own.";
    } catch (err) {
      note.hidden = false;
      note.textContent = "That dog's rules could not be loaded, so this is a blank builder.";
    }
  }
  updateSave();
}

boot();
