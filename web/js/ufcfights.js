/**
 * FIGHT NIGHT -- the UFC page's fight analysis, drawn under the "picks are paused" notice.
 *
 * `renderFightNight(host, {eventId, analyst})` fetches GET /ufc/fight-night (or
 * /ufc/fight-night/{eventId}) and appends one <section> to `host`: the next card, one panel per
 * bout in card order (main event first). Each panel shows both fighters with their records, the
 * price and its implied chances, the headline of the written read, strengths and weaknesses side
 * by side, how each fighter could win, the history between them, what the price says, what would
 * change the read, what could not be used, and a collapsible fact sheet.
 *
 * `fightNightNode(payload, options)` is the same thing without the network, for tests.
 *
 * THIS FILE WRITES NO CLAIM OF ITS OWN
 * -------------------------------------------------------------------
 * Every sentence about a fighter is a sentence the server wrote (src/analysis/ufc_read.py) and is
 * printed verbatim. This file formats numbers the server sent (a price, a percentage, a figure in
 * the fact sheet), ranks nothing, and computes nothing that could be read as a view. Nothing here
 * names a pick, a stake or a chance of winning; the only percentages on screen are the market's
 * own, labelled that way.
 *
 * THIN DATA IS SHOWN, NOT HIDDEN
 * -------------------------------------------------------------------
 * A strength or weakness resting on fewer than 3 fights or 30 fight minutes carries a THIN SAMPLE
 * chip in the warning tone, its caveat sentence under it (never behind a toggle), and its sample
 * (fights and minutes). A bout where either fighter is thin says so at the top of its panel.
 *
 * LAYOUT RULE: no tables, no fixed widths. The page has to hold at 390px without a sideways scroll:
 * everything is blocks that wrap, and css/ufcfights.css gives every text node overflow-wrap:anywhere.
 * Evidence, the longer lists and the fact sheet sit under native <details> toggles, which need no
 * script and so also work from file://.
 *
 * WHERE THE AI ANALYST GOES
 * -------------------------------------------------------------------
 * Every bout panel carries an empty <div data-hook="ufc-analyst-slot" data-bout-id="..."> after the
 * written read and before the collapsible details, and the card carries one more,
 * <div data-hook="ufc-analyst-event-slot">, under its heading. Pass `analyst(slot, context)` in the
 * options (main.js is the one caller) and it is called once per slot: with the bout payload for a
 * bout slot, with `{event}` for the event slot. An empty slot takes no room; a callback that throws
 * leaves its slot empty and never breaks the page.
 */

import { apiGet } from "./api.js";
import { el, formatAmerican, formatEasternClock, formatEasternDate, renderError } from "./dom.js";

/** Bout-level and card-level slots the UFC analyst section can mount into. */
export const ANALYST_SLOT_HOOK = "ufc-analyst-slot";
export const ANALYST_EVENT_SLOT_HOOK = "ufc-analyst-event-slot";

/** How many strengths, weaknesses and routes print per fighter before the rest fold into a toggle. */
export const ITEMS_SHOWN = 3;
export const ROUTES_SHOWN = 2;
/** Shared opponents shown before the rest fold into a toggle. */
export const SHARED_SHOWN = 2;

const SEGMENT_WORDS = { main: "MAIN CARD", prelims: "PRELIMS", early_prelims: "EARLY PRELIMS" };
const STATUS_WORDS = {
  in_progress: "UNDER WAY", final: "FINISHED", canceled: "CANCELLED", postponed: "POSTPONED",
};
const SAMPLE_WORDS = { thin: "THIN SAMPLE", fair: "FAIR SAMPLE", solid: "SOLID SAMPLE" };

/** The figures of the fact sheet, in the order they print: [key, label, format]. */
export const FACT_ROWS = [
  ["ufc_fights", "UFC fights on file", "int"],
  ["win_rate", "Win rate on file", "pct"],
  ["sig_strikes_landed_per_min", "Significant strikes landed per minute", "dec1"],
  ["sig_strikes_absorbed_per_min", "Significant strikes absorbed per minute", "dec1"],
  ["sig_strike_accuracy", "Striking accuracy", "pct"],
  ["sig_strike_defence", "Share of strikes thrown at them that miss", "pct"],
  ["knockdowns_landed_per_15", "Knockdowns scored per 15 minutes", "dec2"],
  ["knockdowns_suffered_per_15", "Knockdowns suffered per 15 minutes", "dec2"],
  ["takedowns_landed_per_15", "Takedowns landed per 15 minutes", "dec1"],
  ["takedown_accuracy", "Takedown accuracy", "pct"],
  ["takedown_defence", "Takedowns stopped", "pct"],
  ["control_time_share", "Share of fight time in control", "pct"],
  ["submission_attempts_per_15", "Submission attempts per 15 minutes", "dec1"],
  ["finish_rate", "Fights ending in a finishing win", "pct"],
  ["been_finished_rate", "Fights ending in a finishing loss", "pct"],
  ["distance_rate", "Fights that went to the scorecards", "pct"],
  ["average_fight_time_s", "Average fight time", "clock"],
  ["strength_of_schedule", "Opponents' average win rate", "pct"],
];

const STYLE_WORDS = {
  wrestler: "wrestler", submission_threat: "submission threat", striker: "striker",
  volume_striker: "volume striker", knockout_threat: "knockout threat", finisher: "finisher",
  vulnerable_to_finish: "vulnerable to a finish", goes_the_distance: "goes the distance",
  hard_to_take_down: "hard to take down",
};

/** How a result method reads in words: the same strings the server's read uses (a test holds the two together). */
export const METHOD_WORDS = {
  KO_TKO: "knockout or TKO", SUB: "submission", DEC_UNANIMOUS: "unanimous decision", DEC_SPLIT: "split decision",
  DEC_MAJORITY: "majority decision", DECISION: "decision", DQ: "disqualification", OTHER: "another method",
  DRAW: "a draw", NC: "a no contest",
};

const NOT_ON_FILE = "not on file";

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function chip(text, tone = "plain") {
  return el("span", { class: `uf-chip uf-chip--${tone}`, text });
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function number(value, places) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(places) : null;
}

function percent(value, places = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(places)}%` : null;
}

function clock(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n)) return null;
  const whole = Math.round(n);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function evidenceValue(value) {
  if (typeof value === "number") return String(Math.round(value * 1000) / 1000);
  return String(value);
}

function recordText(record) {
  if (!record || typeof record !== "object") return null;
  const { wins, losses, draws } = record;
  if (![wins, losses].every((v) => Number.isFinite(Number(v)))) return null;
  return `${wins}-${losses}-${Number.isFinite(Number(draws)) ? draws : 0}`;
}

function subhead(text, hook) {
  const node = el("h4", { class: "uf-subhead", text });
  if (hook) node.setAttribute("data-hook", hook);
  return node;
}

function paragraphs(lines, cls) {
  const wrap = el("div", { class: cls });
  for (const line of lines || []) wrap.appendChild(el("p", { text: line }));
  return wrap;
}

function evidenceToggle(items, hook) {
  if (!items || !items.length) return null;
  const details = el("details", { class: "uf-evidence", "data-hook": hook });
  details.appendChild(el("summary", { class: "uf-evidence__summary", text: `EVIDENCE (${items.length})` }));
  const list = el("ul", { class: "uf-evidence__list" });
  for (const item of items) {
    const row = el("li", { class: "uf-evidence__row" });
    row.appendChild(el("span", { class: "uf-evidence__label", text: item.label }));
    const suffix = item.derived ? " (worked out from the figures on this page)" : "";
    row.appendChild(el("span", { class: "uf-evidence__value", text: evidenceValue(item.value) + suffix }));
    list.appendChild(row);
  }
  details.appendChild(list);
  return details;
}

function sampleChip(sample) {
  if (!sample || sample.fights === null || sample.fights === undefined) return null;
  const parts = [plural(sample.fights, "fight")];
  if (sample.minutes !== null && sample.minutes !== undefined) parts.push(`${Math.round(sample.minutes)} min`);
  return chip(parts.join(" · ").toUpperCase(), "plain");
}

// ---------------------------------------------------------------------------
// Strengths, weaknesses, routes
// ---------------------------------------------------------------------------

function itemNode(item, kind) {
  const node = el("li", { class: `uf-item uf-item--${kind}`, "data-hook": `ufc-${kind}`,
    "data-trait": item.trait });
  const chips = el("div", { class: "uf-chips" });
  chips.appendChild(chip(String(item.size).toUpperCase(), "plain"));
  chips.appendChild(chip(SAMPLE_WORDS[item.sample_level] || String(item.sample_level).toUpperCase() + " SAMPLE",
    item.thin ? "warn" : "plain"));
  const sample = sampleChip(item.sample);
  if (sample) chips.appendChild(sample);
  node.appendChild(chips);
  node.appendChild(el("p", { class: "uf-item__sentence", text: item.sentence }));
  if (item.caveat) node.appendChild(el("p", { class: "uf-item__caveat", text: item.caveat }));
  const toggle = evidenceToggle(item.evidence, "ufc-evidence");
  if (toggle) node.appendChild(toggle);
  return node;
}

function itemList(items, kind, shown) {
  const wrap = el("div", { class: "uf-listwrap" });
  const list = el("ul", { class: "uf-list" });
  for (const item of items.slice(0, shown)) list.appendChild(itemNode(item, kind));
  wrap.appendChild(list);
  if (items.length > shown) {
    const more = el("details", { class: "uf-more", "data-hook": `ufc-more-${kind}` });
    more.appendChild(el("summary", { class: "uf-more__summary", text: `MORE (${items.length - shown})` }));
    const rest = el("ul", { class: "uf-list" });
    for (const item of items.slice(shown)) rest.appendChild(itemNode(item, kind));
    more.appendChild(rest);
    wrap.appendChild(more);
  }
  return wrap;
}

function routeNode(route) {
  const node = el("li", { class: "uf-item uf-item--route", "data-hook": "ufc-route", "data-route": route.route });
  const head = el("div", { class: "uf-chips" });
  head.appendChild(el("span", { class: "uf-route__title", text: route.title }));
  if (route.route !== "none") {
    head.appendChild(chip(String(route.size).toUpperCase(), "plain"));
    head.appendChild(chip(SAMPLE_WORDS[route.sample_level] || "SAMPLE", route.thin ? "warn" : "plain"));
  }
  node.appendChild(head);
  node.appendChild(el("p", { class: "uf-item__sentence", text: route.sentence }));
  if (route.caveat) node.appendChild(el("p", { class: "uf-item__caveat", text: route.caveat }));
  const toggle = evidenceToggle(route.evidence, "ufc-route-evidence");
  if (toggle) node.appendChild(toggle);
  return node;
}

function fighterColumn(side, fighterRead) {
  const col = el("div", { class: "uf-col", "data-hook": "ufc-column", "data-side": side });
  col.appendChild(el("h4", { class: "uf-col__name", text: fighterRead.name }));
  col.appendChild(subhead("STRENGTHS"));
  col.appendChild(fighterRead.strengths.length
    ? itemList(fighterRead.strengths, "strength", ITEMS_SHOWN)
    : el("p", { class: "uf-none", text: "No strength stands out from the figures on file." }));
  col.appendChild(subhead("WEAKNESSES"));
  col.appendChild(fighterRead.weaknesses.length
    ? itemList(fighterRead.weaknesses, "weakness", ITEMS_SHOWN)
    : el("p", { class: "uf-none", text: "No weakness stands out from the figures on file." }));
  return col;
}

function routesBlock(read) {
  const block = el("div", { class: "uf-block", "data-hook": "ufc-routes" });
  block.appendChild(subhead("PATHS TO VICTORY"));
  const cols = el("div", { class: "uf-cols" });
  for (const side of ["a", "b"]) {
    const col = el("div", { class: "uf-col", "data-side": side });
    col.appendChild(el("h4", { class: "uf-col__name", text: read[side].name }));
    const routes = read[side].paths_to_victory || [];
    const list = el("ul", { class: "uf-list" });
    for (const route of routes.slice(0, ROUTES_SHOWN)) list.appendChild(routeNode(route));
    col.appendChild(list);
    if (routes.length > ROUTES_SHOWN) {
      const more = el("details", { class: "uf-more", "data-hook": "ufc-more-routes" });
      more.appendChild(el("summary", { class: "uf-more__summary", text: `MORE (${routes.length - ROUTES_SHOWN})` }));
      const rest = el("ul", { class: "uf-list" });
      for (const route of routes.slice(ROUTES_SHOWN)) rest.appendChild(routeNode(route));
      more.appendChild(rest);
      col.appendChild(more);
    }
    cols.appendChild(col);
  }
  block.appendChild(cols);
  return block;
}

// ---------------------------------------------------------------------------
// History, market, change, missing
// ---------------------------------------------------------------------------

function historyBlock(history) {
  const block = el("div", { class: "uf-block", "data-hook": "ufc-history" });
  block.appendChild(subhead("HISTORY BETWEEN THEM"));
  if (!history) return block;
  if (history.summary) block.appendChild(el("p", { class: "uf-text", text: history.summary }));
  for (const meeting of history.previous_meetings || []) {
    const row = el("p", { class: "uf-text uf-text--meeting", "data-hook": "ufc-meeting", text: meeting.sentence });
    block.appendChild(row);
  }
  const shared = history.shared_opponents || [];
  if (shared.length) {
    const lines = el("div", { class: "uf-shared", "data-hook": "ufc-shared" });
    for (const item of shared.slice(0, SHARED_SHOWN)) {
      lines.appendChild(el("p", { class: "uf-text", "data-hook": "ufc-shared-opponent", text: item.sentence }));
    }
    block.appendChild(lines);
    if (shared.length > SHARED_SHOWN) {
      const more = el("details", { class: "uf-more", "data-hook": "ufc-more-shared" });
      more.appendChild(el("summary", { class: "uf-more__summary", text: `MORE OPPONENTS IN COMMON (${shared.length - SHARED_SHOWN})` }));
      for (const item of shared.slice(SHARED_SHOWN)) {
        more.appendChild(el("p", { class: "uf-text", "data-hook": "ufc-shared-opponent", text: item.sentence }));
      }
      block.appendChild(more);
    }
    if (history.caveat) block.appendChild(el("p", { class: "uf-small", text: history.caveat }));
  }
  return block;
}

/**
 * THE SITUATION -- where each fighter stands going into the bout (src/situation/ufc.py): layoff,
 * form, the card slot, the previous meeting and weight class, as plain sentences with their samples
 * in the words. Null when the read carries no situation block.
 */
export function situationView(situation) {
  if (!situation || typeof situation !== "object") return null;
  const lines = Array.isArray(situation.lines) ? situation.lines : [];
  const missing = Array.isArray(situation.missing) ? situation.missing : [];
  if (!lines.length && !missing.length) return null;
  const block = el("div", { class: "uf-block", "data-hook": "ufc-situation" });
  block.appendChild(subhead("SITUATION"));
  if (situation.label) block.appendChild(el("p", { class: "uf-small", text: situation.label }));
  for (const line of lines) {
    block.appendChild(el("p", { class: "uf-text", "data-hook": "ufc-situation-line", text: line.sentence }));
  }
  const toggle = evidenceToggle(lines.map((l) => l.evidence).filter(Boolean), "ufc-situation-evidence");
  if (toggle) block.appendChild(toggle);
  if (missing.length) {
    const more = el("details", { class: "uf-more", "data-hook": "ufc-situation-missing" });
    more.appendChild(el("summary", { class: "uf-more__summary",
      text: `WHAT THE SITUATION COULD NOT SAY (${missing.length})` }));
    const list = el("ul", { class: "uf-plain" });
    for (const item of missing) {
      const row = el("li", { class: "uf-plain__item" });
      row.appendChild(chip(String(item.status).toUpperCase(), item.status === "stale" ? "warn" : "plain"));
      row.appendChild(el("strong", { class: "uf-plain__lead", text: " " + item.input + ". " }));
      row.appendChild(el("span", { class: "uf-plain__body", text: item.detail }));
      list.appendChild(row);
    }
    more.appendChild(list);
    block.appendChild(more);
  }
  return block;
}

function marketBlock(view) {
  const block = el("div", { class: "uf-block", "data-hook": "ufc-market" });
  block.appendChild(subhead("WHAT THE PRICE SAYS"));
  if (!view) return block;
  block.appendChild(paragraphs(view.sentences, "uf-market"));
  const toggle = evidenceToggle(view.evidence, "ufc-market-evidence");
  if (toggle) block.appendChild(toggle);
  return block;
}

function changeAndMissing(read) {
  const details = el("details", { class: "uf-more uf-more--block", "data-hook": "ufc-limits" });
  details.appendChild(el("summary", { class: "uf-more__summary",
    text: `WHAT WOULD CHANGE THIS, AND WHAT WE COULD NOT USE (${(read.missing || []).length})` }));
  const change = el("div", { class: "uf-block", "data-hook": "ufc-change" });
  change.appendChild(subhead("WHAT WOULD CHANGE IT"));
  const list = el("ul", { class: "uf-plain" });
  for (const item of read.what_would_change_it || []) {
    const row = el("li", { class: "uf-plain__item" });
    row.appendChild(el("strong", { class: "uf-plain__lead", text: item.fact }));
    row.appendChild(el("span", { class: "uf-plain__body", text: " " + item.because }));
    list.appendChild(row);
  }
  change.appendChild(list);
  details.appendChild(change);
  const missing = el("div", { class: "uf-block", "data-hook": "ufc-missing" });
  missing.appendChild(subhead(`WHAT WE COULD NOT USE (${(read.missing || []).length})`));
  const mlist = el("ul", { class: "uf-plain" });
  for (const item of read.missing || []) {
    const row = el("li", { class: "uf-plain__item" });
    row.appendChild(chip(String(item.status).toUpperCase(), item.status === "thin" || item.status === "stale" ? "warn" : "plain"));
    row.appendChild(el("strong", { class: "uf-plain__lead", text: " " + item.input + ". " }));
    row.appendChild(el("span", { class: "uf-plain__body", text: item.detail }));
    mlist.appendChild(row);
  }
  missing.appendChild(mlist);
  details.appendChild(missing);
  return details;
}

// ---------------------------------------------------------------------------
// The fact sheet
// ---------------------------------------------------------------------------

function formatFigure(value, kind) {
  if (value === null || value === undefined) return NOT_ON_FILE;
  switch (kind) {
    case "int": return String(Math.round(Number(value)));
    case "pct": return percent(value) || NOT_ON_FILE;
    case "dec1": return number(value, 1) || NOT_ON_FILE;
    case "dec2": return number(value, 2) || NOT_ON_FILE;
    case "clock": return clock(value) || NOT_ON_FILE;
    default: return String(value);
  }
}

function heightText(inches) {
  const n = Number(inches);
  if (!Number.isFinite(n) || n <= 0) return NOT_ON_FILE;
  return `${Math.floor(n / 12)} ft ${Math.round(n % 12)} in`;
}

function factRow(label, a, b, { thin = false } = {}) {
  const row = el("div", { class: "uf-fact", "data-hook": "ufc-fact" });
  row.appendChild(el("span", { class: "uf-fact__label", text: label }));
  for (const [cls, value] of [["a", a], ["b", b]]) {
    const cell = el("span", { class: `uf-fact__value uf-fact__value--${cls}` });
    cell.appendChild(el("span", { class: "uf-fact__figure", text: value.text }));
    if (value.note) cell.appendChild(el("span", { class: "uf-fact__note", text: value.note }));
    if (value.thin) cell.appendChild(chip("THIN", "warn"));
    row.appendChild(cell);
  }
  if (thin) row.setAttribute("data-thin", "true");
  return row;
}

function lastThree(features) {
  const lines = ((features && features.last_three) || []).map((f) => {
    const word = { win: "W", loss: "L", draw: "D", no_contest: "NC" }[f.result] || "?";
    const rounds = f.round ? ` R${f.round}` : "";
    const how = f.method ? " " + (METHOD_WORDS[f.method] || "an unrecorded method") : "";
    return `${word}${how}${rounds}`;
  });
  return lines.length ? lines.join(", ") : NOT_ON_FILE;
}

function factSheet(sheet, read) {
  const details = el("details", { class: "uf-facts", "data-hook": "ufc-fact-sheet" });
  details.appendChild(el("summary", { class: "uf-facts__summary", text: "FACT SHEET, SIDE BY SIDE" }));
  const names = { a: read ? read.a.name : "First fighter", b: read ? read.b.name : "Second fighter" };
  const head = el("div", { class: "uf-fact uf-fact--head" });
  head.appendChild(el("span", { class: "uf-fact__label", text: "FIGURE" }));
  head.appendChild(el("span", { class: "uf-fact__value", text: names.a }));
  head.appendChild(el("span", { class: "uf-fact__value", text: names.b }));
  details.appendChild(head);
  const feats = sheet.features || {};
  const sample = (side) => (feats[side] && feats[side].sample) || {};
  details.appendChild(factRow("Fight minutes on file",
    { text: formatFigure(sample("a").minutes, "dec1") }, { text: formatFigure(sample("b").minutes, "dec1") }));
  const rec = (side) => (feats[side] && feats[side].record) || {};
  const rtext = (side) => `${rec(side).wins ?? 0}-${rec(side).losses ?? 0}-${rec(side).draws ?? 0}`;
  details.appendChild(factRow("Record on file (wins-losses-draws)", { text: rtext("a") }, { text: rtext("b") }));
  const streak = (side) => {
    const s = (feats[side] && feats[side].streak) || {};
    return s.type ? `${s.length} ${String(s.type).replace("_", " ")}${s.length === 1 ? "" : "s"}` : NOT_ON_FILE;
  };
  details.appendChild(factRow("Current run", { text: streak("a") }, { text: streak("b") }));
  details.appendChild(factRow("Last three fights, newest first",
    { text: lastThree(feats.a) }, { text: lastThree(feats.b) }));
  const diffs = sheet.differentials || {};
  for (const [key, label, kind] of FACT_ROWS) {
    const d = diffs[key];
    if (!d) continue;
    const cell = (side) => {
      const smp = d[`${side}_sample`] || {};
      const note = key === "ufc_fights" ? "" : (smp.fights ? `${plural(smp.fights, "fight")}` : "");
      return { text: formatFigure(d[side], kind), note, thin: d.thin_sample === true && d[side] !== null };
    };
    details.appendChild(factRow(label, cell("a"), cell("b"), { thin: d.thin_sample === true }));
  }
  const phys = sheet.physical || {};
  const pa = phys.a || {};
  const pb = phys.b || {};
  details.appendChild(factRow("Age on fight night (years)",
    { text: formatFigure(pa.age_years, "dec1") }, { text: formatFigure(pb.age_years, "dec1") }));
  details.appendChild(factRow("Height", { text: heightText(pa.height_in) }, { text: heightText(pb.height_in) }));
  details.appendChild(factRow("Reach (inches)",
    { text: formatFigure(pa.reach_in, "int") }, { text: formatFigure(pb.reach_in, "int") }));
  details.appendChild(factRow("Stance", { text: pa.stance || NOT_ON_FILE }, { text: pb.stance || NOT_ON_FILE }));
  const layoff = sheet.layoff || {};
  details.appendChild(factRow("Days since the last fight on file",
    { text: formatFigure(layoff.a_days, "int") }, { text: formatFigure(layoff.b_days, "int") }));
  const styles = sheet.styles || {};
  const styleText = (side) => {
    const applies = (styles[side] && styles[side].applies) || [];
    return applies.length ? applies.map((s) => STYLE_WORDS[s.name] || String(s.name).replace(/_/g, " ")).join(", ") : "none judged";
  };
  details.appendChild(factRow("Style labels", { text: styleText("a") }, { text: styleText("b") }));
  details.appendChild(el("p", { class: "uf-small",
    text: "Counts and rates are of the fights on file only. A THIN tag means fewer than 3 fights or 30 fight minutes "
        + "behind that figure on one side or both." }));
  return details;
}

// ---------------------------------------------------------------------------
// A bout panel
// ---------------------------------------------------------------------------

function segmentChip(bout) {
  if (bout.match_number === 1 && bout.card_segment === "main") return "MAIN EVENT";
  return SEGMENT_WORDS[bout.card_segment] || String(bout.card_segment || "").replace(/_/g, " ").toUpperCase() || null;
}

function boutHead(bout) {
  const head = el("div", { class: "uf-bout__head" });
  const chips = el("div", { class: "uf-chips" });
  const seg = segmentChip(bout);
  if (seg) chips.appendChild(chip(seg, bout.match_number === 1 ? "side" : "plain"));
  if (bout.title_bout) chips.appendChild(chip("TITLE FIGHT", "side"));
  if (bout.weight_class) chips.appendChild(chip(String(bout.weight_class).toUpperCase(), "plain"));
  if (bout.scheduled_rounds) chips.appendChild(chip(`${bout.scheduled_rounds} ROUNDS`, "plain"));
  if (STATUS_WORDS[bout.status]) chips.appendChild(chip(STATUS_WORDS[bout.status], "warn"));
  head.appendChild(chips);
  const when = bout.date_utc ? formatEasternClock(bout.date_utc) : null;
  if (when) head.appendChild(el("span", { class: "uf-bout__time", text: when }));
  return head;
}

function priceText(odds, side) {
  const ml = odds && odds.moneyline && (odds.moneyline.current || odds.moneyline.open);
  if (!ml) return null;
  const price = formatAmerican(ml[side]);
  if (!price) return null;
  const fair = ml.without_margin && ml.without_margin[side];
  const share = percent(fair, 1);
  return share ? `${price} · ${share}` : price;
}

function fighterCard(side, fighter, bout, sheet) {
  const card = el("div", { class: "uf-fighter", "data-hook": "ufc-fighter", "data-side": side });
  card.appendChild(el("h3", { class: "uf-fighter__name", text: fighter.name || "Name not on file" }));
  if (fighter.nickname) card.appendChild(el("p", { class: "uf-fighter__nick", text: `"${fighter.nickname}"` }));
  const facts = el("p", { class: "uf-fighter__facts" });
  const parts = [];
  const record = recordText(fighter.record);
  if (record) parts.push(`${record} overall`);
  const phys = sheet && sheet.physical && sheet.physical[side];
  if (phys && Number.isFinite(Number(phys.age_years))) parts.push(`${Math.round(Number(phys.age_years))} years old`);
  const stance = (phys && phys.stance) || fighter.stance;
  if (stance) parts.push(stance);
  facts.textContent = parts.length ? parts.join(" · ") : "Little on file for this fighter";
  card.appendChild(facts);
  const price = priceText(bout.odds, side);
  const priceNode = el("p", { class: "uf-fighter__price", "data-hook": "ufc-price",
    text: price || "No price on file" });
  card.appendChild(priceNode);
  return card;
}

function priceCaption(odds) {
  if (!odds || !odds.moneyline) return null;
  const when = odds.fetched_utc ? formatEasternClock(odds.fetched_utc) : null;
  const day = odds.fetched_utc ? formatEasternDate(odds.fetched_utc) : null;
  const parts = [odds.provider || "The book"];
  if (when) parts.push(`fetched ${day ? day + " " : ""}${when}`);
  return `${parts.join(", ")}. Each fighter's price, then the market's own share with the bookmaker's margin taken out.`;
}

function resultLine(result) {
  if (!result) return null;
  if (result.outcome === "decided" && result.winner_name) {
    const how = result.method_words ? ` by ${result.method_words}` : "";
    const round = result.end_round ? ` in round ${result.end_round}` : "";
    return `Result: ${result.winner_name} won${how}${round}.`;
  }
  return result.outcome === "draw" ? "Result: a draw." : "Result: no contest.";
}

function depthNode(depth) {
  if (!depth) return null;
  const node = el("div", { class: `uf-depth uf-depth--${depth.level}`, "data-hook": "ufc-depth" });
  node.appendChild(chip(`${String(depth.level).toUpperCase()} DATA`, depth.level === "thin" ? "warn" : "plain"));
  node.appendChild(el("p", { class: "uf-text", text: depth.sentence }));
  return node;
}

function readBlocks(panel, bout) {
  const read = bout.read;
  panel.appendChild(el("p", { class: "uf-headline", "data-hook": "ufc-headline", text: read.headline }));
  for (const note of read.notices || []) {
    panel.appendChild(el("p", { class: "uf-notice", "data-hook": "ufc-notice", text: note }));
  }
  const depth = depthNode(read.data_depth);
  if (depth) panel.appendChild(depth);
  const cols = el("div", { class: "uf-cols uf-cols--traits", "data-hook": "ufc-traits" });
  cols.appendChild(fighterColumn("a", read.a));
  cols.appendChild(fighterColumn("b", read.b));
  panel.appendChild(cols);
  panel.appendChild(routesBlock(read));
  panel.appendChild(historyBlock(read.history));
  for (const line of (read.context || [])) {
    panel.appendChild(el("p", { class: "uf-small", "data-hook": "ufc-context", text: line.sentence }));
    if (line.caveat) panel.appendChild(el("p", { class: "uf-small", text: line.caveat }));
  }
  const situation = situationView(read.situation);
  if (situation) panel.appendChild(situation);
  panel.appendChild(marketBlock(read.market_view));
}

function boutPanel(bout, options) {
  const panel = el("article", { class: "uf-bout panel chamfer", "data-hook": "ufc-bout",
    "data-bout-id": bout.bout_id });
  panel.appendChild(boutHead(bout));
  const fighters = el("div", { class: "uf-fighters" });
  fighters.appendChild(fighterCard("a", bout.fighter_a || {}, bout, bout.sheet));
  fighters.appendChild(el("span", { class: "uf-versus", "aria-hidden": "true", text: "VS" }));
  fighters.appendChild(fighterCard("b", bout.fighter_b || {}, bout, bout.sheet));
  panel.appendChild(fighters);
  const caption = priceCaption(bout.odds);
  if (caption) panel.appendChild(el("p", { class: "uf-small", "data-hook": "ufc-price-caption", text: caption }));
  const result = resultLine(bout.result);
  if (result) panel.appendChild(el("p", { class: "uf-result", "data-hook": "ufc-result", text: result }));

  if (bout.read) {
    readBlocks(panel, bout);
  } else {
    panel.appendChild(el("p", { class: "uf-unavailable", "data-hook": "ufc-unavailable",
      text: bout.unavailable || "No written read could be built for this bout." }));
  }

  const slot = el("div", { class: "uf-analyst-slot", "data-hook": ANALYST_SLOT_HOOK, "data-bout-id": bout.bout_id });
  panel.appendChild(slot);
  if (bout.read) {
    panel.appendChild(changeAndMissing(bout.read));
  }
  if (bout.sheet) panel.appendChild(factSheet(bout.sheet, bout.read));
  if (typeof options.analyst === "function") {
    try {
      const out = options.analyst(slot, bout);
      if (out && typeof out.catch === "function") out.catch(() => {});
    } catch (_err) { /* an analyst section that fails leaves its slot empty and the page as it was */ }
  }
  return panel;
}

// ---------------------------------------------------------------------------
// The card
// ---------------------------------------------------------------------------

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

function noEventNode(payload) {
  const wrap = el("section", { class: "gutter uf", "data-hook": "ufc-fight-night" });
  wrap.appendChild(sectionHead("FIGHT NIGHT"));
  const panel = el("div", { class: "panel chamfer uf-empty", "data-hook": "ufc-no-event" });
  panel.appendChild(el("p", { class: "uf-text", "data-hook": "ufc-no-event-reason",
    text: payload.reason || "No UFC event is scheduled in our data right now." }));
  let updated = null;
  if (payload.data_updated_utc) {
    const day = formatEasternDate(payload.data_updated_utc);
    const time = formatEasternClock(payload.data_updated_utc);
    updated = day || time ? `Our UFC data was last updated ${[day, time].filter(Boolean).join(" ")}.` : null;
  }
  panel.appendChild(el("p", { class: "uf-text", "data-hook": "ufc-last-updated",
    text: updated || "We have no UFC data on file yet." }));
  const actions = el("div", { class: "uf-empty__actions" });
  actions.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn", href: "#/ufc/record",
    "data-hook": "ufc-record-link", text: "VIEW THE UFC RECORD" }));
  panel.appendChild(actions);
  wrap.appendChild(panel);
  return wrap;
}

function otherCards(payload) {
  const events = (payload.other_events || []).filter((e) => !payload.event || e.event_id !== payload.event.event_id);
  if (!events.length) return null;
  const block = el("div", { class: "uf-others", "data-hook": "ufc-other-events" });
  block.appendChild(el("span", { class: "uf-others__label", text: "OTHER CARDS" }));
  const list = el("ul", { class: "uf-others__list" });
  for (const e of events) {
    const li = el("li", { class: "uf-others__item" });
    const when = e.date_utc ? formatEasternDate(e.date_utc) : null;
    li.appendChild(el("a", { class: "uf-others__link", href: `#/ufc?event=${encodeURIComponent(e.event_id)}`,
      "data-hook": "ufc-other-event", text: [e.name, when].filter(Boolean).join(" · ") }));
    list.appendChild(li);
  }
  block.appendChild(list);
  return block;
}

/** The whole card, or the no-event state. Pure: no network. */
export function fightNightNode(payload, options = {}) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  if (!payload.event) return noEventNode(payload);
  const event = payload.event;
  const wrap = el("section", { class: "gutter uf", "data-hook": "ufc-fight-night",
    "data-event-id": event.event_id });
  const day = event.date_utc ? formatEasternDate(event.date_utc) : null;
  wrap.appendChild(sectionHead("FIGHT NIGHT",
    [event.name, day, plural((payload.bouts || []).length, "bout")].filter(Boolean).join(" · ")));
  if (payload.label) wrap.appendChild(el("p", { class: "uf-label", "data-hook": "ufc-label", text: payload.label }));
  const eventSlot = el("div", { class: "uf-analyst-slot", "data-hook": ANALYST_EVENT_SLOT_HOOK });
  wrap.appendChild(eventSlot);
  if (typeof options.analyst === "function") {
    try {
      const out = options.analyst(eventSlot, { event });
      if (out && typeof out.catch === "function") out.catch(() => {});
    } catch (_err) { /* see above */ }
  }
  if (event.development_show) {
    wrap.appendChild(el("p", { class: "uf-notice", "data-hook": "ufc-development-show",
      text: "This is a development show. Most of its fighters have no UFC fights on file, so most reads here are thin." }));
  }
  if (!(payload.bouts || []).length) {
    wrap.appendChild(el("p", { class: "uf-unavailable", "data-hook": "ufc-no-bouts",
      text: payload.reason || "This event has no bouts on file yet." }));
  }
  let segment = null;
  const grid = el("div", { class: "uf-card", "data-hook": "ufc-bouts" });
  for (const bout of payload.bouts || []) {
    if (bout.card_segment !== segment) {
      segment = bout.card_segment;
      grid.appendChild(el("h3", { class: "uf-segment", "data-hook": "ufc-segment",
        text: SEGMENT_WORDS[segment] || String(segment || "CARD").replace(/_/g, " ").toUpperCase() }));
    }
    grid.appendChild(boutPanel(bout, options));
  }
  wrap.appendChild(grid);
  const others = otherCards(payload);
  if (others) wrap.appendChild(others);
  return wrap;
}

/** Fetch the card and mount it. A failed fetch renders the error state and leaves the page above it as it was. */
export async function renderFightNight(host, options = {}) {
  const url = options.eventId
    ? `/ufc/fight-night/${encodeURIComponent(options.eventId)}?sheet=compact`
    : "/ufc/fight-night?sheet=compact";
  const holder = el("section", { class: "gutter uf uf--loading", "data-hook": "ufc-fight-night-holder" });
  holder.appendChild(el("p", { class: "uf-text", text: "Loading the fight analysis." }));
  host.appendChild(holder);
  let payload;
  try {
    payload = await apiGet(url, { timeoutMs: 30000 });
  } catch (err) {
    while (holder.firstChild) holder.removeChild(holder.firstChild);
    holder.setAttribute("class", "gutter uf");
    renderError(holder, err);
    return { rendered: false, event: null };
  }
  const node = fightNightNode(payload, options);
  if (holder.parentNode) holder.parentNode.removeChild(holder);
  if (!node) return { rendered: false, event: null };
  host.appendChild(node);
  return { rendered: Boolean(payload.event), event: payload.event || null };
}
