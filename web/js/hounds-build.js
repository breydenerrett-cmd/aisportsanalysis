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
 * record stays). Signed-out visitors can draft everything. Once the hound is read, named and has met today's board, a "Keep {Name}"
 * form (web/js/keep.js: email, password, "I am 21 or older") makes a free account, signs them in and saves the hound on this page,
 * with no redirect. The record starts at the keep; nothing is backfilled.
 *
 * TRANSLATOR. When the free parser cannot read everything and the owner has switched the Zapier translator
 * on, the response carries a job id; this page polls `GET /hounds/english/{job_id}` (backing off, and giving up at
 * 90 seconds) and offers the result as a replacement draft. The parser's own draft is on the page the whole time:
 * the translator never gates it. If the translator is off the page says which words were not understood and the
 * rule cards finish the job by hand.
 */

import { apiGet, apiPost, getToken } from "./api.js";
import { h, s, clearNode, describeError, houndHref, isNum, fmtPrice } from "./hounds-core.js";
import { showUpgrade } from "./upgrade.js";
import { celebrate, put, removeDog, removedText } from "./dog-common.js";
import { dogBadge, dogFace, DEFAULT_LOOK, lookFor, BACKGROUNDS, cleanLook, breedOfName, breedLabel } from "./dog-avatar.js";
import { stakeLineText } from "./hounds-board.js";
import { mountKeep, keepLabel } from "./keep.js";
import { playReveal, countTo, previewState, priceText } from "./reveal-fx.js";
import { watchFirstGrade } from "./first-grade.js";
import { MY_KENNEL_HREF } from "./home-route.js";

export const PAPER_NOTICE =
  "Paper bets only. Your hound never places a real bet, and it never takes a price of -200 or worse.";

export const EXAMPLES = [
  "Bet home underdogs between +120 and +200 when they're on 2+ days rest. Max 2 bets a day.",
  "Fade teams after 3 straight wins",
  "Aaron Judge over 1.5 total bases when he's hit in 3 straight games",
  "Unders when the temperature is below 55 degrees",
  "Only NFL spreads under 7. Max 2 bets a day",
  "Bet the road underdogs on the road at +130 or longer, and bet unders when it's windy",
];

const PREVIEW_DEBOUNCE_MS = 250;

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

/** Tell the page a dog was created or a new version saved (the kennel studio listens), with a small celebration. */
function announce(type, dog, anchor) {
  celebrate(anchor || q("build-submit"), type);
  try {
    const evt = new Event("linehound:dog-saved");
    evt.detail = { type, id: dog && dog.id };
    window.dispatchEvent(evt);
  } catch (err) { /* no window or no Event */ }
}
const embedded = () => !!(q("build-app") && q("build-app").hasAttribute("data-embedded"));
const clone = (x) => JSON.parse(JSON.stringify(x));

const S = {
  menu: null, spec: null, signedIn: false, mine: [], edit: null, diffReady: false, busy: false,
  understood: [], notRead: [], assumed: [], sentences: [], problems: [], saveProblems: [], previewSeq: 0, previewTimer: null,
  jobTimer: null, jobPolls: 0, jobId: null, copiedFrom: "", pendingTranslation: null,
  jobBusy: false, jobElapsed: 0, jobStart: 0, jobNextPoll: 0, jobErrors: 0, bound: false,
  keep: null, previewSettled: false,
  kept: null,        // {id, name} once THIS draft is a hound: the Keep button becomes "Open in My Kennel" (a second keep is a duplicate name)
};

// ---- the menu ---------------------------------------------------------------------------------------

function market(menu, value) { return (menu.markets || []).find((m) => m.value === value); }

function kindOf(rule) {
  const m = S.menu && rule.markets && rule.markets.length ? market(S.menu, rule.markets[0]) : null;
  return m ? m.kind : "ml_spread";
}

/** The menu's "any sport" entry (value "ANY"): a rule that covers every sport the menu lists. */
const ANY_VALUE = "ANY";
const isAny = (sp) => !!sp && (sp.any === true || sp.value === ANY_VALUE);
const concreteSports = (menu) => (menu.sports || []).filter((x) => !isAny(x)).map((x) => x.value);

/** Does a list of sports (a market's, a condition's) cover `value`? "Any sport" is covered by a list that names ANY or every sport. */
function covers(list, value) {
  if (!list) return true;
  if (list.includes(value)) return true;
  return value === ANY_VALUE && (list.includes(ANY_VALUE) || concreteSports(S.menu).every((sp) => list.includes(sp)));
}

/** The sports every chosen market is offered in. Read from the menu; nothing here names a sport. */
function allowedSports(rule) {
  const picked = (rule.markets || []).map((v) => market(S.menu, v)).filter(Boolean);
  return S.menu.sports.map((x) => x.value).filter((sp) => picked.every((m) => covers(m.sports, sp)));
}

function blankRule() {
  const m = S.menu;
  const first = m.markets[0];
  return { label: "", sports: [(m.sports.find((x) => !isAny(x)) || m.sports[0]).value], markets: [first.value],
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

/** The base style that is the member Gematria hound (src/hounds/user_gematria.py); the menu's `styles` describes it. */
const GEMATRIA = "gematria";
const isGem = (spec = S.spec) => !!spec && spec.style === GEMATRIA;
function styleMenu(value) { return ((S.menu && S.menu.styles) || []).find((x) => x.value === value) || null; }
function gematriaFixed() { const st = styleMenu(GEMATRIA); return (st && st.fixed) || {}; }

/** Fill the defaults a parser draft leaves out, so every card has a value in every control. */
function normaliseSpec(raw) {
  const base = blankSpec();
  const out = Object.assign(base, clone(raw || {}));
  if (out.style === GEMATRIA && !(out.rules && out.rules.length)) {
    // a Gematria draft names its sports and nothing else: the one fixed rule is the style's
    out.rules = [Object.assign(blankRule(), out.sports && out.sports.length ? { sports: out.sports.slice() } : {})];
    const fixed = gematriaFixed();
    if (fixed.lock_minutes) out.lock_minutes = fixed.lock_minutes;
    out.rank_by = "earliest_lock";
  }
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

/** Does the condition run for every sport the rule picked? A stat the menu marks for some sports only does not run for the rest. */
function condSupports(c, rule) {
  return (rule.sports || []).every((sp) => covers(c.sports, sp));
}

/** The conditions the rule's kind and markets can use. `all` keeps the ones its sports cannot run (shown greyed out). */
function conditionOptionsFor(rule, { all = false } = {}) {
  const kind = kindOf(rule);
  const markets = rule.markets || [];
  return (S.menu.conditions || []).filter((c) => c.kinds.includes(kind)
    && (all || condSupports(c, rule))
    && (!c.only_markets.length || markets.every((m) => c.only_markets.includes(m))));
}

/** "MLB and NFL only": the sports the menu names for a condition, in the menu's own words. */
function onlyNote(c) {
  const names = (c.sports || []).map((v) => (S.menu.sports.find((x) => x.value === v) || {}).label || v);
  if (!names.length) return "not available";
  const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
  return `${list} only`;
}

/** One line for the rule card: how many stat conditions are greyed out for the chosen sports and why; "" when none are. */
function greyedNote(rule) {
  const greyed = conditionOptionsFor(rule, { all: true }).filter((c) => !condSupports(c, rule));
  if (!greyed.length) return "";
  const sets = [...new Set(greyed.map((c) => onlyNote(c)))];
  return `${greyed.length} stat ${greyed.length === 1 ? "condition is" : "conditions are"} greyed out (${sets.join("; ")}). Pick ${sets.length === 1 ? "that sport" : "one of those sports"} to use ${greyed.length === 1 ? "it" : "them"}.`;
}

function addConditionControl(rule, group, onChange) {
  const options = conditionOptionsFor(rule, { all: true });
  const sel = h("select", { "data-hook": "add-condition", "aria-label": "Add a condition" });
  sel.appendChild(h("option", { value: "", text: "Add a condition..." }));
  const groups = {};
  for (const c of options) (groups[c.group] ||= []).push(c);
  for (const [name, items] of Object.entries(groups)) {
    sel.appendChild(h("optgroup", { label: name }, items.map((c) => {
      const fits = condSupports(c, rule);
      const text = !fits ? `${c.label} (${onlyNote(c)})` : c.available ? c.label : `${c.label} (not available yet)`;
      return h("option", Object.assign({ value: c.id, text }, fits && c.available ? {} : { disabled: true, "data-greyed": fits ? "unavailable" : "sport" }));
    })));
  }
  sel.value = "";
  const fire = () => {
    const id = sel.value;
    const cond = condMenu(id);
    if (!id || !cond || !cond.available || !condSupports(cond, rule)) return;
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
    // what data stands behind it and how much of it exists (the menu's own note), so a thin stat is not a surprise
    if (cond && cond.note) row.appendChild(h("p", { class: "hd-fine bd-cond__note", "data-hook": "cond-note", text: cond.note }));
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

// ---- the sport chooser: a searchable chip grid -------------------------------------------------------

/** More sports than this and the grid gets a search box. */
const SEARCH_FROM = 8;

/** What dropped out of a rule when its sports changed, for one line under the grid (not part of the spec). */
const droppedNotes = new WeakMap();

/** A sport was picked or put down: the rule keeps the menu's order, "any sport" stands alone, and the stat conditions the new
 *  sports cannot run leave with the change (the line under the grid says which and why). */
function chooseSport(rule, value, onChange) {
  const menu = S.menu;
  const any = menu.sports.find(isAny);
  const set = new Set(rule.sports);
  if (any && value === any.value) { set.clear(); set.add(value); }
  else {
    if (any) set.delete(any.value);
    if (set.has(value)) set.delete(value); else set.add(value);
  }
  if (!set.size) return;
  rule.sports = menu.sports.map((x) => x.value).filter((v) => set.has(v));
  const before = rule.when ? countConditions(rule.when) : 0;
  rule.when = pruneConditions(rule, rule.when);
  const dropped = before - (rule.when ? countConditions(rule.when) : 0);
  if (dropped > 0) droppedNotes.set(rule, `${dropped} stat ${dropped === 1 ? "condition was" : "conditions were"} removed because the sport you picked does not have that data.`);
  else droppedNotes.delete(rule);
  onChange(true);
}

function countConditions(tree) { return tree.items.reduce((n, i) => n + (i.items ? countConditions(i) : 1), 0); }

/**
 * Every sport the menu lists as a chip, "Any sport" first, with a search box once there are many. The chips are drawn again
 * on each keystroke without redrawing the card, so the box keeps its focus. A sport the chosen markets are not offered in
 * is greyed out; a picked sport is never hidden by the search.
 */
function sportGrid(rule, onChange) {
  const menu = S.menu;
  const wrap = h("div", { class: "bd-sportgrid", "data-hook": "rule-sport-grid" });
  const list = menu.sports.slice().sort((a, b) => (isAny(b) ? 1 : 0) - (isAny(a) ? 1 : 0));
  const grid = h("div", { class: "bd-chips bd-sportchips", role: "group", "aria-label": "Sports", "data-hook": "rule-sports" });
  const none = h("p", { class: "hd-fine", "data-hook": "sport-none", role: "status", hidden: true, text: "No sport matches that." });
  let needle = "";
  const draw = () => {
    clearNode(grid);
    const allowed = allowedSports(rule);
    const shown = list.filter((sp) => !needle || rule.sports.includes(sp.value) || isAny(sp) || String(sp.label).toLowerCase().includes(needle));
    for (const sp of shown) {
      const blocked = !allowed.includes(sp.value);
      grid.appendChild(chipButton(sp.label, rule.sports.includes(sp.value), () => chooseSport(rule, sp.value, onChange),
        Object.assign({ "data-sport": sp.value }, blocked ? { disabled: true, title: "Not offered for the markets chosen" } : {})));
    }
    if (needle && shown.every((sp) => isAny(sp) || rule.sports.includes(sp.value))) none.removeAttribute("hidden"); else none.setAttribute("hidden", "");
  };
  if (list.length > SEARCH_FROM) {
    const search = h("input", { type: "search", class: "bd-sportsearch", placeholder: "Search sports", autocomplete: "off", "data-hook": "sport-search", "aria-label": "Search sports" });
    const fire = () => { needle = String(search.value).trim().toLowerCase(); draw(); };
    search.addEventListener("input", fire);
    search.addEventListener("change", fire);
    wrap.appendChild(search);
  }
  draw();
  wrap.appendChild(grid);
  wrap.appendChild(none);
  const dropped = droppedNotes.get(rule);
  if (dropped) wrap.appendChild(h("p", { class: "hd-fine bd-note", "data-hook": "sport-dropped", role: "status", text: dropped }));
  return wrap;
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
  card.appendChild(h("div", { class: "hd-field bd-field" }, [h("span", { class: "bd-label", text: "Sport" }), sportGrid(rule, onChange)]));

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
  const greyed = greyedNote(rule);
  if (greyed) condBox.appendChild(h("p", { class: "hd-fine bd-note", "data-hook": "conditions-greyed", text: greyed }));
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

function globalsGrid(onChange, grid = clearNode(q("globals-grid")), gem = false) {
  const m = S.menu;
  if (!gem) grid.appendChild(field("Decide this long before the start", selectOf(m.lock_minutes.choices.map((v) => ({ value: String(v), label: `${v} minutes` })),
    String(S.spec.lock_minutes), (v) => { S.spec.lock_minutes = Number(v); onChange(); }, { "data-hook": "g-lock" })));
  grid.appendChild(field("Most bets a day", numberField({ min: m.max_bets_per_day.min, max: m.max_bets_per_day.max, step: 1 }, S.spec.max_bets_per_day,
    (v) => { S.spec.max_bets_per_day = v; onChange(); }, { "data-hook": "g-bets" })));
  // The stake in dollars, live: "1 unit = $10 of your $1,000; this dog bets 2 units ($20 a bet)." The numbers come
  // from the menu's `bankroll` block (src/hounds/bankroll.py); a stake change rewrites the line at once.
  const stakeLine = h("p", { class: "hd-fine bd-stakeline", "data-hook": "g-stake-line", "aria-live": "polite",
    text: stakeLineText(S.spec.stake_units, m.bankroll) });
  const stakeField = field("Stake per bet (paper units)", selectOf(m.stake_units.choices.map((v) => ({ value: String(v), label: `${v} unit${v === 1 ? "" : "s"}` })),
    String(S.spec.stake_units), (v) => {
      S.spec.stake_units = Number(v);
      stakeLine.textContent = stakeLineText(S.spec.stake_units, m.bankroll);
      onChange();
    }, { "data-hook": "g-stake" }), m.stake_note);
  stakeField.appendChild(stakeLine);
  grid.appendChild(stakeField);
  if (!gem) grid.appendChild(field("If more picks qualify than the cap, take", selectOf(m.rank_by.map((r) => ({ value: r.value, label: r.label })),
    S.spec.rank_by, (v) => { S.spec.rank_by = v; onChange(); }, { "data-hook": "g-rank" }), m.ranking_note));
}

// ---- the base style: your own rules, or Gematria ------------------------------------------------------

/**
 * BASE STYLE. "Your own rules" is the builder as it always was. "Gematria" hands the picking to the house Gematria Hound's engine
 * and active rules (src/hounds/user_gematria.py): the member keeps the sports, the most bets a day, the stake and the name, and the
 * rest is the style's own, said in a paragraph and a link to the house hound's page. Everything shown here is read from the menu's
 * `styles`; the page holds no rule of its own. Switching back keeps the rules you had.
 */
function setStyle(value) {
  if (!S.menu || !S.spec) return;
  if (value === GEMATRIA && !isGem()) {
    S.rulesAside = clone(S.spec.rules);
    const first = S.spec.rules[0] || blankRule();
    S.spec.rules = [Object.assign(blankRule(), { label: "Gematria", sports: first.sports.slice() })];
    S.spec.style = GEMATRIA;
    const fixed = gematriaFixed();
    if (fixed.lock_minutes) S.spec.lock_minutes = fixed.lock_minutes;
    S.spec.rank_by = "earliest_lock";
    S.started = true;
  } else if (value !== GEMATRIA && isGem()) {
    delete S.spec.style;
    delete S.spec.gematria;
    S.spec.rules = S.rulesAside && S.rulesAside.length ? S.rulesAside : [Object.assign(blankRule(), { sports: S.spec.rules[0].sports.slice() })];
    S.rulesAside = null;
  } else {
    return;
  }
  changed(true);
}

function renderStyle() {
  const picker = q("style-picker");
  const panel = q("style-gematria");
  if (!picker || !panel || !S.menu) return;
  const styles = S.menu.styles || [];
  clearNode(picker);
  for (const st of styles) {
    picker.appendChild(chipButton(st.label, (isGem() ? GEMATRIA : "rules") === st.value, () => setStyle(st.value), { "data-hook": "style-choice", "data-style": st.value, title: st.summary }));
  }
  const gem = isGem() && S.started;
  panel.hidden = !gem;
  if (!gem) return;
  const def = styleMenu(GEMATRIA) || {};
  q("style-explain").textContent = def.summary || "";
  const link = q("style-house-link");
  const house = def.house_hound || {};
  if (house.href) link.setAttribute("href", house.href);
  link.textContent = `See the house ${house.name || "Gematria Hound"}`;
  q("style-fixed").textContent = gematriaFixed().text || "";
  const sportsBox = clearNode(q("style-sports"));
  sportsBox.appendChild(h("p", { class: "bd-style__label", text: "Sports" }));
  sportsBox.appendChild(sportGrid(S.spec.rules[0], changed));
  globalsGrid(changed, clearNode(q("style-globals")), true);
}

// ---- rendering --------------------------------------------------------------------------------------

function renderRules() {
  renderStyle();
  const has = !!S.spec && S.spec.rules.length > 0 && S.started;
  q("rules-empty").hidden = has;
  q("rules-body").hidden = !has;
  if (!has) return;
  q("rules-advanced").hidden = isGem();            // a Gematria hound has one fixed rule: no cards to edit
  if (!isGem()) {
    const cards = clearNode(q("rule-cards"));
    S.spec.rules.forEach((rule, i) => cards.appendChild(ruleCard(rule, i, changed)));
    q("add-rule").disabled = S.spec.rules.length >= S.menu.limits.max_rules;
    q("rule-limit").textContent = `${S.spec.rules.length} of ${S.menu.limits.max_rules} rules`;
    globalsGrid(changed);
  }
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
    problems.appendChild(h("p", { class: "bd-problems__lead", text: "These need fixing before the hound can run:" }));
    problems.appendChild(h("ul", {}, all.map((p) => h("li", { text: p }))));
  }
}

function friendlyField(key) {
  const m = /^rules\[(\d+)\]\.(.*)$/.exec(key);
  if (m) return `Rule ${Number(m[1]) + 1}, ${m[2].replace(/\./g, " / ").replace(/_/g, " ")}`;
  return key.replace(/_/g, " ");
}

/** A refusal as a list of sentences. Every shape the server can send gives at least one: the validator's per-field reasons, a
 *  request-shape error (a list of {msg}), a message, a bare string, or, failing all of those, a plain "no reason given". A refusal
 *  that rendered as an empty list would read as "nothing happened". */
/** The server's "name: is already taken", in the builder's own words (QA 2026-10-21: a second Keep of the same draft showed the raw field error). */
export const NAME_TAKEN_TEXT = "That name is taken. Try another.";

function problemsFrom(detail) {
  const fields = detail && detail.fields && typeof detail.fields === "object" ? Object.entries(detail.fields) : [];
  if (fields.length) return fields.map(([k, v]) => (k === "name" && /already taken/i.test(String(v)) ? NAME_TAKEN_TEXT : `${friendlyField(k)}: ${v}`));
  if (Array.isArray(detail)) {
    const lines = detail.map((d) => (d && typeof d.msg === "string" ? d.msg : "")).filter(Boolean);
    if (lines.length) return lines;
  }
  if (typeof detail === "string" && detail.trim()) return [detail.trim()];
  if (detail && typeof detail.message === "string" && detail.message.trim()) return [detail.message.trim()];
  return ["The server did not accept that and gave no reason."];
}

function setCount(text) {
  q("preview-count").textContent = text;
  const pill = q("preview-pill");
  pill.hidden = !text || !S.started;
  pill.textContent = text;
}

/** The preview's count line. `parts` ({n, rest}) lets the number count up on its own; the pill under the page gets the plain sentence. */
function setCountParts(parts) {
  const count = q("preview-count");
  clearNode(count);
  const n = h("span", { class: "bd-count", "data-hook": "preview-n", text: parts.n });
  count.appendChild(n);
  count.appendChild(document.createTextNode(parts.rest));
  const pill = q("preview-pill");
  pill.hidden = !S.started;
  pill.textContent = parts.n + parts.rest;
  return n;
}

function previewName() {
  return String((S.spec && S.spec.name) || "").trim() || "Your hound";
}

/** R4: "{n} of {m} games fit {Name}'s rule today", a pass, or a board that did not load. The words are in the page at once; the count-up
 *  and the ticket flip are `data-reveal` motion on top, played once (css/builder.css). */
function renderPreview(res, err = null) {
  const list = clearNode(q("preview-list"));
  const panel = q("preview-panel");
  q("preview-sub").textContent = "";
  q("preview-retry-row").hidden = true;
  if (!res && !err) {
    setCount(S.problems.length ? "Fix the rules to see a preview." : "Nothing to preview yet.");
    return;
  }
  const st = previewState(res, previewName(), err);
  panel.setAttribute("data-state", st.kind);
  S.previewSettled = true;
  syncKeep();
  q("preview-sub").textContent = st.sub || "";
  q("preview-retry-row").hidden = !st.retry;
  if (st.kind !== "picks") {
    setCount(st.line);
    if (st.kind === "zero") playReveal(panel);
    return;
  }
  const nEl = setCountParts(st.parts);
  for (const [i, p] of st.picks.entries()) {
    const start = p.start_utc ? new Date(p.start_utc) : null;
    const when = start && !Number.isNaN(start.getTime()) ? start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
    list.appendChild(h("li", { class: `bd-pick${p.would_bet ? "" : " bd-pick--over"}`, "data-hook": "preview-pick", style: `--i:${Math.min(i, 5)}` }, [
      h("strong", { text: p.selection }),
      h("span", { class: "bd-pick__price", text: ` ${priceText(p.price)}` }),
      h("span", { class: "hd-fine", text: ` ${p.away_team} at ${p.home_team}${when ? ", " + when : ""}${p.locked ? "" : ", not decided yet"}${p.would_bet ? "" : ", over your daily cap"}` })]));
  }
  if (playReveal(panel) === "play") countTo(nEl, st.fit, panel);
}

function previewBody() {
  const spec = clone(S.spec);
  if (!spec.name) spec.name = "Draft Dog";
  return { spec: cleanSpec(spec) };
}

/**
 * The fields the server's validator accepts at the top of a version-2 spec and on a rule (src/hounds/user_spec.py `V2_TOP_KEYS`
 * without its derived keys, and `V2_RULE_KEYS`; tests/test_hounds_edit_save_visible.py fails if they drift apart). The validator
 * REFUSES an unknown key, so a saved dog that carries one the editor never shows would be refused on every save, forever.
 */
const SPEC_KEYS = ["version", "name", "tagline", "color", "badge", "lock_minutes", "max_bets_per_day", "stake_units", "rank_by", "rules", "style", "gematria"];
const RULE_KEYS = ["label", "sports", "markets", "side", "price_min", "price_max", "line_min", "line_max", "min_books", "when"];

/** Send only what the server's menu knows: empty optionals become absent, empty condition groups vanish, and a field the
 *  server has no place for is left out rather than sent to be refused. */
function cleanSpec(spec) {
  const tree = (g) => {
    const items = (g.items || []).map((i) => (i.items ? tree(i) : i)).filter((i) => i && (!i.items || i.items.length));
    return items.length ? { op: g.op || "all", items } : null;
  };
  spec.rules = spec.rules.map((r) => {
    const out = {};
    for (const key of RULE_KEYS) if (r[key] !== undefined) out[key] = r[key];
    out.when = r.when ? tree(r.when) : null;
    if (out.line_min === null || out.line_min === undefined) delete out.line_min;
    if (out.line_max === null || out.line_max === undefined) delete out.line_max;
    return out;
  });
  for (const key of Object.keys(spec)) if (!SPEC_KEYS.includes(key)) delete spec[key];
  if (spec.style !== GEMATRIA) { delete spec.style; delete spec.gematria; }
  else if (spec.rules.length) spec.sports = spec.rules[0].sports;      // the style's one fixed rule covers the hound's sports
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
      renderPreview(null, err || new Error("preview failed"));
    }
  }
}

function retryPreview() {
  q("preview-retry-row").hidden = true;
  setCount("Checking today's board...");
  runPreview();
}

function schedulePreview() {
  if (S.previewTimer) clearTimeout(S.previewTimer);
  S.previewTimer = setTimeout(runPreview, PREVIEW_DEBOUNCE_MS);
}

/** Something about the draft changed. `structural` rebuilds the cards; a plain value edit leaves the inputs alone. */
function changed(structural) {
  S.diffReady = false;
  q("diff").hidden = true;
  showSaveProblems([]);                  // the reasons a save was refused are about the draft as it WAS
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

/**
 * THE PICKERS SPEAK THE DOG'S PALETTE (critic round 2, 2026-10-19). The chart colour a member picks is saved data with its own hex, so it
 * cannot become one of the dog's eight backdrops; but each swatch is DRAWN as the dog's backdrop nearest to it (a rounded tile with that
 * backdrop's gradient and the chart colour as its ring), and the live preview uses that same backdrop. After the dog is created that look
 * is saved to it (a best-effort PUT /hounds/{id}/look), so the dog is the one that was in the preview.
 */
export function nearestBackground(hex) {
  const hue = (x) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(String(x).slice(i, i + 2), 16) / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    if (d < 0.12) return null;                       // a grey has no hue
    const hh = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return ((hh * 60) + 360) % 360;
  };
  const want = /^#[0-9a-fA-F]{6}$/.test(String(hex)) ? hue(hex) : 20;
  if (want === null) return "slate";
  let best = "navy", bestD = Infinity;
  for (const [key, [top]] of Object.entries(BACKGROUNDS)) {
    const hh = hue(top);
    if (hh === null || key === "slate" || key === "charcoal") continue;   // the greys are for a grey colour; every menu colour has a hue
    const d = Math.min(Math.abs(hh - want), 360 - Math.abs(hh - want));
    if (d < bestD) { bestD = d; best = key; }
  }
  if (best === "sand" && want >= 75 && want < 170) return "forest";   // a green is a green, not a brown
  return best;
}

/** The look the preview shows, and the look a new dog is saved with: coat and eyes from its name, the backdrop from its colour, no gear. */
export function previewLook(spec, menuColors) {
  const name = String((spec && spec.name) || "").trim();
  const c = (menuColors || []).find((x) => x.value === (spec && spec.color));
  const base = lookFor(name || "new dog");
  return cleanLook(Object.assign({}, base, { bg: nearestBackground(c ? c.hex : "#FF7A45") }));
}

function renderPickers() {
  const colors = clearNode(q("color-picker"));
  for (const c of S.menu.colors) {
    const bg = BACKGROUNDS[nearestBackground(c.hex)];
    colors.appendChild(h("button", { type: "button", class: "bd-swatch", role: "radio", "aria-checked": S.spec.color === c.value ? "true" : "false",
      "aria-label": c.label, title: c.label, "data-color": c.value, "data-bg": nearestBackground(c.hex), style: `--sw:${c.hex}; --bg1:${bg[0]}; --bg2:${bg[1]}`,
      on: { click: () => { S.spec.color = c.value; changed(false); renderPickers(); updateDogCard(); } } }));
  }
  const badges = clearNode(q("badge-picker"));
  for (const b of S.menu.badges) {
    badges.appendChild(h("button", { type: "button", class: "bd-badge", role: "radio", "aria-checked": S.spec.badge === b.value ? "true" : "false",
      "aria-label": b.label, title: b.label, "data-badge": b.value,
      on: { click: () => { S.spec.badge = b.value; changed(false); renderPickers(); updateDogCard(); } } }, [badgeIcon(b.value)]));
  }
}

/** The two sidebar cards each get a dog (a sniffing beagle for "would have bet today", a retriever for "my dogs"): drawn once, never redrawn. */
function drawSideDogs() {
  const spec = { preview: { breed: "beagle", mood: "thinking" }, mine: { breed: "retriever", mood: "idle" } };
  for (const holder of document.querySelectorAll("[data-side-dog]")) {
    if (holder.firstChild) continue;
    const cfg = spec[holder.getAttribute("data-side-dog")] || spec.mine;
    holder.appendChild(dogBadge(lookFor(cfg.breed), { size: 60, mood: cfg.mood, breed: cfg.breed }));
  }
}

function updateDogCard() {
  if (!S.spec || !S.menu) return;
  drawSideDogs();
  const card = clearNode(q("build-dog-card"));
  const hex = colorHex(S.spec.color);
  // the dog reacts to what has been said so far: thinking until there is a name or a rule, happy once there are both
  const pose = S.spec.name && S.sentences.length ? "happy" : S.spec.name || S.sentences.length ? "idle" : "thinking";
  // A dog being edited shows ITS saved look and breed. A new dog is drawn live: the coat and eyes follow the name, the backdrop follows the colour,
  // a breed word in the name (Husky, Corgi, Poodle...) picks that breed, and the pose follows how much has been said. The breed of a name with no
  // breed in it is picked when the dog is created, so until then the preview draws a retriever and says so.
  const named = !S.edit && S.spec.name ? breedOfName({ name: S.spec.name }) : "";
  const look = S.edit ? (S.edit.look || lookFor(S.edit.id)) : previewLook(S.spec, S.menu.colors);
  const dogSvgEl = S.edit ? dogBadge(look, { size: 176, mood: pose, id: S.edit.id, name: S.edit.name })
    : dogBadge(look, { size: 176, mood: pose, breed: named || "retriever" });
  card.appendChild(h("div", { class: "bd-dog bd-dog--stage", style: `--dog:${hex}`, "data-bg": look.bg, "data-coat": look.coat }, [
    h("span", { class: "bd-dog__dog", "data-hook": "dog-preview-dog", "data-pose": pose }, [dogSvgEl]),
    h("span", { class: "bd-dog__badge", "data-hook": "dog-badge", "data-badge": S.spec.badge }, [badgeIcon(S.spec.badge, 34)]),
    h("div", { class: "bd-dog__text" }, [
      h("p", { class: "bd-dog__name", "data-hook": "dog-name", text: S.spec.name || "Your hound" }),
      h("p", { class: "bd-dog__tag", "data-hook": "dog-tagline", text: S.spec.tagline || "Add a catchphrase" }),
      S.sentences.length ? h("p", { class: "bd-dog__rule hd-fine", text: S.sentences[0] }) : null,
      S.edit ? null : h("p", { class: "bd-dog__breed hd-fine", "data-hook": "dog-preview-breed",
        text: named ? `${breedLabel(named)}, from the name. Coat and gear are yours to change in the studio.` : "The breed comes with the hound. Coat and gear are yours to change in the studio." })])]));
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
    if (S.kept && S.spec.name !== S.kept.name) S.kept = null;      // a new name is a new hound: Keep comes back
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

/**
 * WHY THIS SECTION IS SHAPED THE WAY IT IS (2026-10-19). A member pasted a long free-form strategy, pressed "Read my
 * strategy", and the page looked dead: Step 2 never filled in and nothing said why. Four rules came out of it:
 *
 *   1. THE PARSER'S DRAFT IS SHOWN THE MOMENT IT ARRIVES, whatever the second reader is doing. Understood lines, the
 *      words that were not understood (marked), what was assumed, suggested rewordings and the rule cards all draw from the
 *      first response. The second reader (the Zapier translator) only ever offers a replacement afterwards.
 *   2. NOTHING STAYS DISABLED OR SPINNING. The Read button is never disabled; every failure (a 422 for a long text, the
 *      per-minute limit, a dead connection, a render error) ends in a sentence under the box and leaves the text where it
 *      was. The translation poll backs off, gives up at 90 seconds and says so.
 *   3. THE LIMIT IS VISIBLE. A live "x / 600" count, no silent cut-off (the box has no maxlength, because a browser cuts a
 *      paste without a word): over the limit the first whole sentences that fit are read and what was left out is listed.
 *   4. EVERY OUTCOME HAS WORDS: signed out (a sign-in link that keeps the draft), rate limited, timed out, refused.
 */
export const ENGLISH_MAX = 600;
const JOB_TICK_MS = 1000;
const JOB_TIMEOUT_MS = 90000;
const JOB_POLL_STEPS_MS = [1000, 2000, 3000, 5000, 8000];      // after each answer of "still translating"; the last repeats
export const TRANSLATING_TEXT = "A second reader is translating the rest (about 30 seconds)...";
export const TIMEOUT_TEXT = "The second reader didn't answer. Here's what I could read; finish the rest with the rule cards or rephrase.";
const DRAFT_KEY = "linehound.builder.draft.v1";
const DRAFT_MAX_AGE_MS = 24 * 3600 * 1000;

const setStatus = (text, kind) => {
  const box = q("english-status");
  if (!box) return;
  box.textContent = text || "";
  if (kind) box.setAttribute("data-kind", kind); else box.removeAttribute("data-kind");
};

/**
 * The first whole sentences of `text` that fit in `max` characters, and the rest. One giant sentence is cut at the last
 * space that fits. Pure, so it can be reasoned about on its own.
 */
export function fitToLimit(text, max = ENGLISH_MAX) {
  const t = String(text || "").trim();
  if (t.length <= max) return { read: t, rest: "" };
  const pieces = t.match(/[^.!?;\n]+[.!?;]*\s*/g) || [t];
  let read = "";
  for (const piece of pieces) {
    if ((read + piece).length > max) break;
    read += piece;
  }
  if (!read.trim()) {
    const cut = t.lastIndexOf(" ", max);
    read = t.slice(0, cut > 0 ? cut : max);
  }
  read = read.trim();
  return { read, rest: t.slice(read.length).trim() };
}

function updateCount() {
  const box = q("english-input"), count = q("english-count"), note = q("english-limit");
  if (!box || !count) return;
  const n = String(box.value || "").length;
  count.textContent = `${n} / ${ENGLISH_MAX}`;
  const state = n > ENGLISH_MAX ? "over" : n === ENGLISH_MAX ? "limit" : n >= ENGLISH_MAX * 0.9 ? "near" : "";
  if (state) count.setAttribute("data-state", state); else count.removeAttribute("data-state");
  if (!note) return;
  note.hidden = !(state === "over" || state === "limit");
  note.textContent = state === "over"
    ? `That is ${n} characters and the limit is ${ENGLISH_MAX}. I will read the first whole sentences that fit and show you what was left out. Shorter sentences work best.`
    : state === "limit" ? `That is the ${ENGLISH_MAX} character limit. Anything longer is read in whole sentences, up to the limit.` : "";
}

function setTranslator(kind, parts) {
  const line = q("english-translator");
  if (!line) return;
  clearNode(line);
  if (kind) line.setAttribute("data-state", kind); else line.removeAttribute("data-state");
  for (const p of parts || []) line.appendChild(typeof p === "string" ? h("span", { text: p }) : p);
}

function renderSuggestions(list) {
  const box = q("english-suggestions");
  const ul = clearNode(q("english-suggest-list"));
  box.hidden = !list.length;
  for (const sug of list) {
    const parts = [];
    if (sug.phrase) parts.push(h("strong", { text: `"${sug.phrase}"` }), h("span", { text: " " }));
    if (sug.try) {
      parts.push(h("span", { text: `Try: "${sug.try}".` }),
        h("button", { type: "button", class: "btn btn--ghost", "data-hook": "suggest-add", text: "Add this wording", on: { click: () => addWording(sug.try) } }));
    }
    parts.push(h("span", { class: "hd-fine", text: sug.why || "" }));
    ul.appendChild(h("li", { "data-hook": "suggestion" }, parts));
  }
}

function addWording(wording) {
  const box = q("english-input");
  const base = String(box.value || "").trim().replace(/[.;,\s]+$/, "");
  box.value = `${base}${base ? ". " : ""}${wording}.`;
  updateCount();
  if (box.focus) box.focus();
  setStatus("Added. Press Read my strategy to read it again.");
}

function showRead(res, extraNotRead = []) {
  q("english-read").hidden = false;
  S.understood = res.understood || [];
  S.notRead = (res.not_understood || []).concat(extraNotRead);
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
    nr.appendChild(h("li", { "data-hook": "not-understood" }, [
      h("strong", { class: "bd-unread__phrase", text: n.text ? `"${n.text}"` : "Something" }), h("span", { text: ` was not understood: ${n.reason}` })]));
  }
  const assumed = q("english-assumed");
  assumed.hidden = !S.assumed.length;
  assumed.textContent = S.assumed.length ? `Assumed, so check the cards: ${S.assumed.join("; ")}.` : "";
  renderSuggestions(res.suggestions || []);
  setTranslator("", []);
}

/** Remember the draft across a sign-in (the link leaves the page): the English, and the cards as they stand. */
function saveDraft() {
  try {
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify({ at: Date.now(), text: String(q("english-input").value || ""),
      spec: S.spec && S.started ? cleanSpec(clone(S.spec)) : null }));
  } catch (err) { /* storage blocked: the sign-in still works, the draft is simply not kept */ }
}

function signInLink(text) {
  return h("a", { href: "index.html#/signin", "data-hook": "translator-signin", text, on: { click: saveDraft } });
}

function translatorLine(res) {
  if (!S.notRead.length) { setTranslator("", []); return; }
  const t = res.translation || {};
  if (t.status === "translating") {
    setTranslator("translating", [h("span", { class: "bd-spinner", "data-hook": "translator-spinner", "aria-hidden": "true" }), TRANSLATING_TEXT]);
  } else if (t.status === "sign_in_required") {
    setTranslator("signin", ["A second reader can try the part I could not read once you are signed in. ", signInLink("Sign in"),
      " (your draft is kept). Meanwhile the cards below let you finish by hand."]);
  } else if (t.status === "rate_limited") {
    setTranslator("limit", [res.message || "You have used this hour's second-reader tries. Here is what I could read; finish the rest with the rule cards or rephrase."]);
  } else {
    setTranslator("", [res.message || "The cards below let you finish it by hand."]);
  }
}

function startFromDraft(res) {
  const raw = res.spec || res.draft;
  S.started = true;
  const keepIdentity = { name: S.spec ? S.spec.name : "", tagline: S.spec ? S.spec.tagline : "", color: S.spec ? S.spec.color : null, badge: S.spec ? S.spec.badge : null };
  S.spec = normaliseSpec(raw && ((raw.rules && raw.rules.length) || raw.style === GEMATRIA) ? raw : null);
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

/** One sentence for each way the reading call can fail. The text in the box is never touched. */
function englishErrorText(err) {
  const status = err && err.status;
  const detail = err && err.detail && typeof err.detail === "object" ? err.detail : {};
  const hand = " You can also start from a blank rule and use the cards.";
  if (status === 422 && detail.message) return detail.message;
  if (status === 422) return "I could not use that text. Shorten it or send it as a few shorter sentences." + hand;
  if (status === 429) return "That is a lot of reads in a short time. Wait a few seconds and press Read my strategy again; your text is still here.";
  if (status === null || status === undefined) return "I could not reach the strategy reader (a bad connection or a short outage). Your text is still here: press Read my strategy to try again." + hand;
  return describeError(err, "the strategy reader").text + hand;
}

let readSeq = 0;

async function readEnglish() {
  const raw = String(q("english-input").value || "").trim();
  const go = q("english-go");
  setStatus("");
  if (!raw) { setStatus("Type a strategy first, or pick an example."); return; }
  const { read, rest } = fitToLimit(raw, ENGLISH_MAX);
  stopJobPolling();
  const seq = ++readSeq;
  setStatus("Reading...");
  go.setAttribute("aria-busy", "true");
  const idle = () => { if (seq === readSeq) go.removeAttribute("aria-busy"); };
  let res;
  try {
    res = await apiPost("/hounds/english", { text: read });
  } catch (err) {
    idle();
    if (seq === readSeq) setStatus(englishErrorText(err), "error");
    return;
  }
  idle();
  if (seq !== readSeq) return;
  try {
    const left = rest ? [{ text: rest.length > 70 ? `${rest.slice(0, 70)}...` : rest,
      reason: `it is past the ${ENGLISH_MAX} character limit, so it was not read. Shorten the text, or read it again in a second pass.` }] : [];
    showRead(res, left);
    translatorLine(res);
    startFromDraft(res);
  } catch (err) {
    setStatus("I read it but could not draw the result. Your text is still here; press Read my strategy to try again, or start from a blank rule.", "error");
    return;
  }
  setStatus(res.spec || (res.draft && res.draft.rules && res.draft.rules.length) ? "Read. Your draft is in step 2 below." : "I could not make a rule from that. Step 2 has a blank rule to fill in.");
  const step = q("step-rules");
  if (!embedded() && step && typeof step.scrollIntoView === "function") step.scrollIntoView();
  if (res.job_id && res.status === "translating" && S.notRead.length) startJobPolling(res.job_id);
}

function stopJobPolling() {
  if (S.jobTimer) clearInterval(S.jobTimer);
  S.jobTimer = null;
  S.jobId = null;
  S.jobBusy = false;
  S.pendingTranslation = null;
  const slot = q("english-translator");
  if (slot) slot.removeAttribute("data-job");
}

function startJobPolling(jobId) {
  S.jobId = jobId;
  S.jobPolls = 0;
  S.jobErrors = 0;
  S.jobElapsed = 0;
  S.jobStart = Date.now();
  S.jobNextPoll = JOB_POLL_STEPS_MS[0];
  S.jobBusy = false;
  S.jobTimer = setInterval(jobTick, JOB_TICK_MS);
}

const nextPollIn = (count) => JOB_POLL_STEPS_MS[Math.min(count, JOB_POLL_STEPS_MS.length - 1)];

/** One second of waiting. It polls the job on a backoff (1, 2, 3, 5, 8, 8... seconds apart) and gives up at 90 seconds. */
async function jobTick() {
  if (!S.jobId || S.jobBusy) return;
  S.jobElapsed = Math.max(S.jobElapsed + JOB_TICK_MS, Date.now() - S.jobStart);
  if (S.jobElapsed >= JOB_TIMEOUT_MS) { stopJobPolling(); setTranslator("timeout", [TIMEOUT_TEXT]); return; }
  if (S.jobElapsed < S.jobNextPoll) return;
  const id = S.jobId;
  S.jobBusy = true;
  try {
    const job = await apiGet(`/hounds/english/${encodeURIComponent(id)}`);
    if (S.jobId !== id) return;
    S.jobPolls += 1;
    if (job.status === "translating") { S.jobNextPoll = S.jobElapsed + nextPollIn(S.jobPolls); return; }
    stopJobPolling();
    finishJob(job, id);
  } catch (err) {
    if (S.jobId !== id) return;
    S.jobErrors += 1;
    if (err && (err.status === 401 || err.status === 403)) {
      stopJobPolling();
      setTranslator("signin", ["Your sign-in lapsed, so the second reader's answer cannot be shown. ", signInLink("Sign in"), " (your draft is kept)."]);
    } else if (S.jobErrors >= 3) {
      stopJobPolling();
      setTranslator("error", [`${describeError(err, "the second reader").text} Here is what I could read; finish the rest with the rule cards or rephrase.`]);
    } else {
      S.jobNextPoll = S.jobElapsed + nextPollIn(S.jobPolls + S.jobErrors);
    }
  } finally {
    if (S.jobId === id || !S.jobId) S.jobBusy = false;
  }
}

function finishJob(job, id) {
  if (job.status === "done" && job.spec) {
    S.pendingTranslation = job;
    setTranslator("done", [h("span", { text: "The second reader has a version of your whole strategy. " }),
      h("button", { type: "button", class: "btn btn--ghost", "data-hook": "use-translation", text: "Use its version", on: { click: () => { useTranslation(job); } } })]);
    q("english-translator").setAttribute("data-job", id);
  } else if (job.status === "refused") {
    setTranslator("error", ["The second reader's answer did not fit the rules: " + Object.entries(job.reasons || {}).map(([k, v]) => `${friendlyField(k)}: ${v}`).join("; ") + ". The cards below let you finish by hand."]);
  } else {
    setTranslator("error", [(job.error || "The second reader could not help.") + " The cards below let you finish by hand."]);
  }
}

function useTranslation(job) {
  showRead({ understood: [{ text: "your whole strategy", meaning: "the second reader's version, shown in the cards below" }], not_understood: [], assumed: [] });
  setTranslator("done", ["Showing the second reader's version. Check every card."]);
  startFromDraft({ spec: job.spec, sentences: job.sentences });
}

/** After a sign-in the builder gets its draft back (saved by the sign-in link above). Returns true when it did. */
function restoreDraft() {
  let saved = null;
  try {
    saved = JSON.parse(window.localStorage.getItem(DRAFT_KEY) || "null");
    window.localStorage.removeItem(DRAFT_KEY);
  } catch (err) { saved = null; }
  if (!saved || typeof saved !== "object" || !saved.at || Date.now() - saved.at > DRAFT_MAX_AGE_MS) return false;
  if (typeof saved.text === "string") { q("english-input").value = saved.text; updateCount(); }
  if (saved.spec && Array.isArray(saved.spec.rules) && saved.spec.rules.length) startFromDraft({ spec: saved.spec, sentences: [] });
  const note = q("build-from-note");
  note.hidden = false;
  note.textContent = "Welcome back. Your draft from before you signed in is below.";
  return true;
}

function exampleChips() {
  const box = clearNode(q("example-chips"));
  EXAMPLES.forEach((text) => box.appendChild(h("button", { type: "button", class: "bd-chip bd-chip--example", "data-hook": "example-chip", text,
    on: { click: () => { q("english-input").value = text; updateCount(); readEnglish(); } } })));
}

// ---- saving ---------------------------------------------------------------------------------------------------

function updateSave() {
  const btn = q("build-submit");
  if (!btn || !S.menu) return;
  const editing = !!S.edit;
  q("edit-cancel").hidden = !editing;
  let label = keepLabel(S.spec && S.spec.name);
  if (editing) label = S.diffReady ? `Save as version ${S.edit.version_no + 1}` : "Review the changes";
  const opensKennel = !editing && !!S.kept && !embedded();
  if (opensKennel) label = "Open in My Kennel";
  btn.textContent = label;
  btn.setAttribute("data-kept", opensKennel ? "true" : "false");
  btn.disabled = S.busy || !S.started;
  btn.hidden = !S.signedIn && !editing;               // a signed-out visitor keeps through the form under the identity fields
  syncKeep();
  const hint = q("save-hint");
  if (hint) hint.textContent = S.started ? "" : "The save button wakes up once your strategy is read (step 1) or you start a blank rule.";
  const limit = q("limit-text");
  if (S.signedIn && !editing) {
    const running = S.mine.filter((d) => d.status === "running").length;
    const cap = S.menu.limits.max_running_per_account;
    limit.textContent = `${running} of ${cap} hounds running.`;
  } else {
    limit.textContent = "";
  }
}

/** Who sees which save control (see web/js/keep.js): a signed-out visitor gets the form once the hound is read and has met today's board. */
function syncKeep() {
  const keep = S.keep;
  if (!keep) return;
  const ready = !S.signedIn && !S.edit && S.started && S.previewSettled;
  if (ready) keep.show(); else if (!keep.state.accountMade) keep.hide();
  keep.setName();
}

function setMessage(text, kind) {
  const box = clearNode(q("build-message"));
  if (text) box.appendChild(h("p", { class: `bd-msg bd-msg--${kind || "ok"}`, text }));
}

/**
 * Bring a message into view. On a phone the Save button sits far below the rule cards, and a message drawn anywhere else on the
 * page (the rules panel, the sign-in banner at the top) reads as "I tapped it and nothing happened" (a real member, 2026-10-20).
 */
function reveal(node) {
  if (!node) return;
  try {
    if (typeof node.scrollIntoView === "function") node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (typeof node.focus === "function") node.focus({ preventScroll: true });
  } catch (err) { /* scrolling is a courtesy; the message is already on the page */ }
}

function serverError(text, link) {
  const box = q("build-server-error");
  box.hidden = !text;
  box.textContent = text || "";
  if (text && link) { box.appendChild(h("span", { text: " " })); box.appendChild(link); }
  if (text) reveal(box);
}

/** The reasons a save was refused, in a box right above the Save button (the same list also marks the rules panel). */
function showSaveProblems(list) {
  const host = q("build-save-problems");
  if (!host) return;                     // a page without the box (an older skeleton) must never break every edit
  const box = clearNode(host);
  box.hidden = !list.length;
  if (!list.length) return;
  box.appendChild(h("p", { class: "bd-problems__lead", text: "Not saved. Fix these, then tap again:" }));
  box.appendChild(h("ul", {}, list.map((p) => h("li", { text: p }))));
  reveal(box);
}

/** Why a save did not happen, in words, for the box above the Save button. Nothing in here claims the hound was saved. */
function saveFailureText(err) {
  const status = err && err.status;
  if (status === 429) return "That is too many saves in a short while. Wait a minute and tap again. Nothing was saved.";
  if (status === null) return "Could not reach the server, so nothing was saved. It could be your connection; tap again in a moment.";
  if (typeof status === "number") return `The server answered ${status}, so nothing was saved. Tap again in a minute.`;
  const why = err && err.message ? ` (${String(err.message).slice(0, 120)})` : "";
  return `Something went wrong on this page${why}, so nothing was saved. Reload the page and try again.`;
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

/** The Save button: Keep, until this draft has been kept; then it is the way to the kept hound, never a second POST. */
function onSubmitTap() {
  if (S.kept && !S.edit && !embedded()) { window.location.href = MY_KENNEL_HREF; return false; }
  return submit();
}

/**
 * THE RULE FOR EVERY TAP ON THE SAVE BUTTON: it ends in something the person can SEE next to the button: the diff, the saved
 * message, or a box saying why not (a list of reasons, a sign-in prompt, or a plain failure). It never returns quietly.
 * It resolves true when a NEW hound was kept (the Keep form needs to know), false in every other case.
 */
async function submit() {
  if (S.busy) { serverError("Still working on your last tap. Give it a few seconds."); return false; }
  if (!S.started) { serverError("There is no rule yet. Describe a strategy in step 1 or start a blank rule, then tap again."); return false; }
  setMessage("");
  serverError("");
  showSaveProblems([]);
  S.saveProblems = [];
  if (!S.signedIn) {
    gate("Sign in to keep your hound. Your draft stays on this page.");
    serverError("Sign in to keep your hound. Your draft stays on this page.", h("a", { href: "index.html#/signin", text: "Sign in" }));
    return false;
  }
  if (!String(S.spec.name || "").trim()) {
    S.saveProblems = ["Name: give your hound a name (3 to 24 letters, digits, spaces or hyphens)."];
    renderSentences();
    q("f-name").focus();
    showSaveProblems(S.saveProblems);
    return false;
  }
  let kept = false;
  S.busy = true;
  updateSave();
  try {
    if (S.edit) {
      if (!S.diffReady) {
        const res = await apiPost(`/hounds/${encodeURIComponent(S.edit.id)}/diff`, { spec: saveSpec() });
        showDiff((res && res.changes) || []);
      } else {
        const res = await apiPost(`/hounds/${encodeURIComponent(S.edit.id)}/version`, { spec: saveSpec(), reason: "edited in the builder" });
        const dog = res.hound || {};
        setMessage(`Saved as version ${dog.version_no}. The old version keeps its record and stops betting.`, "ok");
        if (dog.id) q("build-message").appendChild(h("p", {}, [h("a", { href: houndHref(dog.id), "data-hook": "new-dog-link", text: "See your hound" })]));
        S.edit = null; S.diffReady = false;
        q("diff").hidden = true;
        reveal(q("build-message"));
        await loadMine();
        announce("version", dog);
      }
    } else {
      const body = { spec: saveSpec() };
      if (S.copiedFrom) body.copied_from = S.copiedFrom;
      const res = await apiPost("/hounds", body);
      const dog = res.hound || {};
      // the dog is the one that was in the preview: save its look (best effort, cosmetic; without it the dog wears the default look for its id)
      if (dog.id && !S.copiedFrom) { try { await put(`/hounds/${encodeURIComponent(dog.id)}/look`, { look: previewLook(S.spec, S.menu.colors) }); } catch (err) { /* default look */ } }
      setMessage(`${dog.name || "Your hound"} is in the kennel. Your record starts now.`, "ok");
      if (dog.id) q("build-message").appendChild(h("p", {}, [h("a", { href: houndHref(dog.id), "data-hook": "new-dog-link", text: "See your hound" })]));
      reveal(q("build-message"));
      await loadMine();
      announce("created", dog);
      S.kept = { id: dog.id || "", name: dog.name || S.spec.name };
      // R6 starts here: this browser now watches this hound for its first graded ticket (web/js/first-grade.js)
      if (dog.id) watchFirstGrade(dog.id);
      kept = true;
    }
  } catch (err) {
    handleSaveError(err);
  } finally {
    S.busy = false;
    updateSave();
  }
  return kept;
}

function handleSaveError(err) {
  const status = err && err.status;
  const detail = err && err.detail;
  if (status === 401 || status === 403) {
    S.signedIn = false;
    gate("Your sign-in has lapsed or this account cannot build yet.");
    serverError("Your sign-in has lapsed or this account cannot build yet, so nothing was saved. Your draft stays on this page.",
      h("a", { href: "index.html#/signin", text: "Sign in" }));
  } else if (status === 402 && showUpgrade(q("build-server-error"), err)) {
    const box = q("build-server-error");
    box.hidden = false;
    if (box.scrollIntoView) box.scrollIntoView({ block: "center", behavior: "smooth" });
  } else if (status === 422) {
    // a refusal always lists its reasons: in the rules panel (where the rule they are about is) and above the Save button
    // (where the person's thumb is)
    S.saveProblems = problemsFrom(detail);
    renderSentences();
    showSaveProblems(S.saveProblems);
  } else if (status === 409) {
    serverError(detail && detail.message ? detail.message : "You already have the most hounds running. Retire one first.");
  } else {
    serverError(saveFailureText(err));
  }
}

function showDiff(changes) {
  const box = q("diff");
  const list = clearNode(q("diff-list"));
  box.hidden = false;
  if (!changes.length) {
    list.appendChild(h("li", { text: "Nothing has changed from the saved version." }));
    S.diffReady = false;
    reveal(box);
    return;
  }
  for (const c of changes) {
    const parts = [h("strong", { text: c.what })];
    if (c.before) parts.push(h("div", { class: "bd-diff__before", text: `Before: ${c.before}` }));
    if (c.after) parts.push(h("div", { class: "bd-diff__after", text: `After: ${c.after}` }));
    list.appendChild(h("li", { "data-hook": "diff-item" }, parts));
  }
  S.diffReady = true;
  reveal(box);
}

// ---- my dogs ----------------------------------------------------------------------------------------------------

async function loadMine() {
  const state = q("my-dogs-state");
  const list = clearNode(q("my-dogs"));
  const signInLink = () => q("nav-signin");
  if (!getToken()) { S.signedIn = false; S.mine = []; state.textContent = "Sign in to see the hounds you have built."; if (signInLink()) signInLink().hidden = false; updateSave(); return; }
  try {
    const res = await apiGet("/hounds/mine");
    S.signedIn = true;
    S.mine = (res.hounds || []).filter((d) => d.status !== "retired" && d.status !== "buried");     // a buried dog is in the graveyard, not the builder
    if (signInLink()) signInLink().hidden = true;
    state.textContent = S.mine.length ? "" : "You have not built a hound yet.";
    for (const d of S.mine) list.appendChild(dogItem(d));
  } catch (err) {
    if (err && (err.status === 401 || err.status === 403)) { S.signedIn = false; state.textContent = "Sign in to see the hounds you have built."; }
    else state.textContent = describeError(err, "your hounds").text;
  }
  updateSave();
}

function dogItem(d) {
  const rec = d.record || {};
  const record = rec.bets ? `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}, ${rec.bets} bets` : "no bets yet";
  const hex = colorHex(d.color);
  return h("li", { class: "bd-dogrow", "data-hook": "my-dog", "data-id": d.id, style: `--dog:${hex}` }, [
    h("span", { class: "bd-dog__face", "aria-hidden": "true" }, [dogFace(d, { size: 44 })]),
    h("div", { class: "bd-dogrow__text" }, [
      h("p", { class: "bd-dogrow__name" }, [h("a", { href: houndHref(d.id), text: d.name }),
        h("span", { class: "hd-fine", text: ` v${d.version_no} · ${d.status}` })]),
      h("p", { class: "hd-fine", text: record }),
      h("details", {}, [h("summary", { text: "Its rules" }),
        h("ol", { class: "bd-sentence-list" }, (d.rule_sentences || []).map((t) => h("li", { text: t })))]),
      h("div", { class: "bd-dogrow__actions" }, [
        h("button", { type: "button", class: "btn btn--ghost", "data-hook": "edit-dog", text: "Edit",
          on: { click: () => startEdit(d) } }),
        h("button", { type: "button", class: "btn btn--ghost", "data-hook": "remove-dog", text: "Remove from my kennel",
          "aria-label": `Remove ${d.name} from my kennel`, on: { click: () => removeMine(d) } })])])]);
}

/** "Remove from my kennel": ask, retire (the record stays on the ledger), and say so. The kennel page hears the event too. */
async function removeMine(d) {
  serverError("");
  const res = await removeDog(d);
  if (res.cancelled) return;
  if (!res.ok) { serverError(res.message); return; }
  if (S.edit && S.edit.id === d.id) openBlank();
  setMessage(removedText(d.name), "ok");
  await loadMine();
  try {
    const evt = new Event("linehound:dog-saved");
    evt.detail = { type: "retired", id: d.id };
    window.dispatchEvent(evt);
  } catch (err) { /* no window or no Event */ }
}

function startEdit(d) {
  stopJobPolling();
  S.started = true;
  S.edit = { id: d.id, version_no: d.version_no, name: d.name, look: d.look || null };
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
  if (!embedded() && typeof window.scrollTo === "function") window.scrollTo(0, 0);
}

/** For the kennel studio (web/js/kennel.js): reset the builder to a blank dog, or open one of the signed-in member's dogs. */
export function openBlank() {
  if (!S.menu) return false;
  stopJobPolling();
  S.edit = null; S.copiedFrom = ""; S.diffReady = false; S.started = false;
  S.spec = blankSpec(); S.sentences = []; S.problems = []; S.saveProblems = [];
  q("diff").hidden = true;
  setMessage("");
  serverError("");
  q("english-read").hidden = true;
  q("english-input").value = "";
  updateCount();
  setStatus("");
  q("build-title").textContent = "Build your hound";
  q("build-from-note").hidden = true;
  renderRules(); renderPickers(); fillIdentity(); updateDogCard(); updateSave();
  return true;
}

/**
 * Open one of the member's dogs for editing. Resolves { ok: true } or { ok: false, reason } with reason "not_ready" (the rules
 * menu never loaded), "signed_out" or "not_found". A dog missing from the list is looked for once more before giving up (the
 * list may simply not have loaded yet), so the studio can say which of those it was instead of a catch-all "sign in again".
 */
export async function openEdit(id) {
  if (!S.menu) return { ok: false, reason: "not_ready" };
  let dog = S.mine.find((d) => d.id === id);
  if (!dog) { await loadMine(); dog = S.mine.find((d) => d.id === id); }
  if (!dog) return { ok: false, reason: S.signedIn ? "not_found" : "signed_out" };
  startEdit(dog);
  return { ok: true };
}

/** Re-read the member's dogs (the kennel page calls this after a removal so the limit line and the list are current). */
export async function refreshMine() {
  if (S.menu) await loadMine();
}

export const builderReady = () => !!S.menu;

/** Fetch the rules menu again after it failed to load (the kennel studio's "Try again"). True when the builder is ready. */
export async function reboot() {
  if (!S.menu) await boot();
  return !!S.menu;
}

function stopEdit() {
  S.edit = null;
  S.diffReady = false;
  q("build-title").textContent = "Build your hound";
  q("build-from-note").hidden = true;
  q("diff").hidden = true;
  updateSave();
}

// ---- boot ---------------------------------------------------------------------------------------------------------

function stateBox(kind, text) {
  return h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status", "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
}

async function boot() {
  if (!S.bound) {                       // a retry after a failed menu load runs the rest of this again, but binds once
    S.bound = true;
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
    q("build-submit").addEventListener("click", onSubmitTap);
    if (q("preview-retry")) q("preview-retry").addEventListener("click", retryPreview);
    if (q("build-keep-host")) S.keep = mountKeep(q("build-keep-host"), {
      name: () => String((S.spec && S.spec.name) || "").trim(),
      // the account was just made and the token stored: the builder is now a signed-in builder, so its own save door does the rest
      save: async () => { S.signedIn = true; return submit(); },
      onSignIn: saveDraft, prefix: "build-keep" });
    q("edit-cancel").addEventListener("click", stopEdit);
    q("english-input").addEventListener("input", updateCount);
  }
  updateCount();
  q("build-submit").disabled = true;
  q("english-go").disabled = false;
  q("blank-rule").disabled = false;

  try {
    S.menu = await apiGet("/hounds/builder/menu");
  } catch (err) {
    const box = clearNode(q("rules-empty"));
    box.appendChild(stateBox(err && err.status === 404 ? "missing" : "down", describeError(err, "the hound builder").text));
    // not a dead end: the menu is the one thing the page cannot work without, so offer to fetch it again
    box.appendChild(h("p", {}, [h("button", { type: "button", class: "btn btn--ghost", "data-hook": "menu-retry", text: "Try again",
      on: { click: () => { boot(); } } })]));
    q("english-go").disabled = true;
    q("blank-rule").disabled = true;
    return;
  }
  clearNode(q("rules-empty")).appendChild(h("p", { text: "Describe a strategy above, or start from a blank rule." }));
  S.spec = blankSpec();
  S.started = false;
  bindIdentity();
  renderStyle();
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
  } else if (params.get("quiz")) {
    loadQuizHandoff();
  } else if (!fromId && restoreDraft()) {
    // the draft the person had before they signed in is back
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
      note.textContent = "You are building from a copy of another hound's rules. Change anything you like; it will be a new hound of your own.";
    } catch (err) {
      note.hidden = false;
      note.textContent = "That hound's rules could not be loaded, so this is a blank builder.";
    }
  }
  updateSave();
}

/** "Edit rules" on the quiz's reveal (web/js/hound-quiz.js): the quiz leaves its composed spec in localStorage and opens
 * the builder with ?quiz=1. It is a DRAFT like any other: it is checked by the same preview and saved by the same door. */
function loadQuizHandoff() {
  const note = q("build-from-note");
  let data = null;
  try { data = JSON.parse(window.localStorage.getItem("linehound.quiz.handoff.v1") || "null"); } catch (err) { data = null; }
  note.hidden = false;
  if (!data || !data.spec || !Array.isArray(data.spec.rules) || !data.spec.rules.length) {
    note.textContent = "Your quiz draft could not be found, so this is a blank builder.";
    return;
  }
  startFromDraft({ spec: data.spec, sentences: data.sentences || [] });
  S.spec.name = data.spec.name || S.spec.name;
  fillIdentity();
  updateDogCard();
  note.textContent = "Built from your quiz. Change anything you like; nothing is saved until you keep it.";
}

/** Resolves when the builder has loaded its menu and the member's dogs (the kennel studio waits for it). */
export const booted = q("build-app") ? boot() : Promise.resolve();
