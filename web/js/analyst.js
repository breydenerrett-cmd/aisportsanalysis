/**
 * THE AI ANALYST on the page -- two self-contained renderers and the one
 * fetch they need.
 *
 *   renderAnalystSection(data)   one game's published analysis: the summary,
 *                                then the calls grouped by market. The game
 *                                page appends it and does nothing else with it.
 *   renderAnalystRecord(record)  the public record, by market family, and
 *                                (when the server sends one) the supervised-session
 *                                briefs' own record under its own heading.
 *   mountAnalystRecord(screen)   fetches GET /analyst/record and appends the
 *                                section; a failed fetch leaves the page as it
 *                                was.
 *
 * WHAT THIS PAGE MUST NEVER DO
 * -------------------------------------------------------------------
 * - Make a pass look smaller than a take. PASS is the analyst's default and
 *   an honest answer; it gets the same type, the same row and the same
 *   reasons as a take. A page that dressed up its takes and mumbled its
 *   passes would be advertising, not publishing.
 * - Print a win rate or a return under 30 graded calls in a family. The
 *   server already sends null for both; this file prints the reason it was
 *   given instead of a figure, and never computes a rate of its own.
 * - Drop the label. Every render starts with the same sentence, from the
 *   server (`label`), with the same wording as the constant below if the
 *   server ever omits it.
 * - Show a call the checker could not verify as though it were analysis. Those
 *   arrive as a PASS whose reason says so; they are drawn like any PASS.
 * - Hide the case against. Every take arrives with the strongest reason from the
 *   packet that it loses (`case_against`); it is drawn under the reasons in the
 *   same type, so a reader weighs both. A pass has none and shows none.
 * - Hide what the analysis could not use. `analysis.missing` is the packet's own
 *   list of absent, stale or thin inputs; it is listed (capped, with a count),
 *   and when the server could not read it (null) nothing is claimed either way.
 * - Show a calculated number without saying where it came from. A reason that rests on a
 *   number the analyst worked out (days between two dates, a gap between two ERAs) arrives with
 *   `derivations`: short plain sentences the server wrote from what the checker recomputed. They are
 *   drawn small, under the reason. The page prints them as sent, never a path or a formula of its own.
 * - Write its own label. A supervised-session brief arrives with a different
 *   label from the API analyst's; the page prints whichever the server sent.
 *
 * The API serves what the ledger froze before first pitch. This file reads
 * it. It makes no call to a model, computes no price and re-derives nothing.
 */

import { apiGet } from "./api.js";
import { el, formatAmerican, formatEasternClock } from "./dom.js";
import { bookLabel } from "./labels.js";

export const ANALYST_LABEL =
  "Written by an AI model from the data on this page. Unproven. Analysis, not advice.";

/* Families in the order they are shown; the words a reader sees for each. */
export const FAMILY_ORDER = ["moneyline", "run_line", "total", "team_total", "prop"];
export const FAMILY_LABEL = {
  moneyline: "Moneyline",
  run_line: "Run line",
  total: "Game total",
  team_total: "Team totals",
  prop: "Player props",
};

const VERDICT_WORDS = {
  TAKE: "Take",
  TAKE_OTHER_SIDE: "Take the other side",
  PASS: "Pass",
};

const RESULT_WORDS = { WIN: "Won", LOSS: "Lost", PUSH: "Push", VOID: "Void" };
const WOULD_HAVE_WORDS = {
  WIN: "The side passed on won.",
  LOSS: "The side passed on lost.",
  PUSH: "The side passed on pushed.",
};

export function verdictWord(verdict) {
  return VERDICT_WORDS[verdict] || String(verdict || "");
}

export function priceText(call) {
  const p = formatAmerican(call.price);
  if (!p) return "No price named";
  const book = call.book ? ` at ${bookLabel(call.book)}` : "";
  return `${p}${book}`;
}

export function percentText(fraction) {
  if (fraction === null || fraction === undefined) return null;
  const n = Number(fraction);
  if (!Number.isFinite(n)) return null;
  return `${Math.round(n * 100)}%`;
}

/** Calls grouped by family, in FAMILY_ORDER, each group in the order the
 * server sent. A family with no calls is omitted. */
export function groupCalls(calls) {
  const by = new Map();
  for (const call of calls || []) {
    const fam = call.family || call.market || "other";
    if (!by.has(fam)) by.set(fam, []);
    by.get(fam).push(call);
  }
  const order = FAMILY_ORDER.filter((f) => by.has(f))
    .concat([...by.keys()].filter((f) => !FAMILY_ORDER.includes(f)));
  return order.map((family) => ({ family, calls: by.get(family) }));
}

function unverified(call) {
  return Boolean(call.verification && call.verification.status === "could not be verified");
}

/* =====================================================================
 * One call
 * ===================================================================*/

/** One reason as a list item: its claim, then (when the checker verified a calculation behind a number
 * in it) a small sentence per calculation saying where the number came from. */
function reasonItem(reason) {
  const li = el("li", { text: reason.claim });
  for (const sentence of reason.derivations || []) {
    if (sentence) li.appendChild(el("small", { class: "an-derived", "data-hook": "analyst-derivation", text: sentence }));
  }
  return li;
}

function reasonList(call) {
  const list = el("ul", { class: "an-call__reasons", "data-hook": "analyst-reasons" });
  for (const reason of call.reasons || []) {
    if (reason && reason.claim) list.appendChild(reasonItem(reason));
  }
  return list;
}

function resultLine(call) {
  if (call.result && RESULT_WORDS[call.result]) {
    return el("p", { class: `an-call__result an-call__result--${call.result.toLowerCase()}`,
      "data-hook": "analyst-result", text: RESULT_WORDS[call.result] });
  }
  if (call.verdict === "PASS" && call.would_have && WOULD_HAVE_WORDS[call.would_have.result]) {
    return el("p", { class: "an-call__result an-call__result--pass", "data-hook": "analyst-result",
      text: WOULD_HAVE_WORDS[call.would_have.result] });
  }
  return null;
}

function caseAgainst(call) {
  const against = call.case_against;
  if (unverified(call) || !against || !against.claim) return null;
  const block = el("div", { class: "an-call__against", "data-hook": "analyst-case-against" });
  block.appendChild(el("h4", { class: "an-call__against-head", text: "The case against" }));
  const list = el("ul", { class: "an-call__reasons" });
  list.appendChild(reasonItem(against));
  block.appendChild(list);
  return block;
}

export function callNode(call) {
  const node = el("article", {
    class: `an-call an-call--${String(call.verdict || "").toLowerCase()}`,
    "data-hook": "analyst-call", "data-verdict": call.verdict || "",
    "data-slot": call.slot_id || "",
  });
  const head = el("div", { class: "an-call__head" });
  head.appendChild(el("span", { class: "an-call__verdict", "data-hook": "analyst-verdict",
    text: verdictWord(call.verdict) }));
  head.appendChild(el("span", { class: "an-call__what",
    text: `${call.title ? call.title + ": " : ""}${call.selection || ""}` }));
  node.appendChild(head);

  const facts = el("div", { class: "an-call__facts" });
  facts.appendChild(el("span", { class: "an-call__price", "data-hook": "analyst-price",
    text: priceText(call) }));
  if (call.confidence) {
    facts.appendChild(el("span", { class: "an-call__confidence", "data-hook": "analyst-confidence",
      text: `${call.confidence} confidence` }));
  }
  const est = percentText(call.fair_estimate);
  if (est) facts.appendChild(el("span", { class: "an-call__estimate", text: `Analyst number ${est}` }));
  node.appendChild(facts);

  node.appendChild(reasonList(call));
  const against = caseAgainst(call);
  if (against) node.appendChild(against);

  if (!unverified(call) && call.pass_price !== null && call.pass_price !== undefined) {
    const when = call.verdict === "PASS" ? "Would start to take it at" : "Stops being worth it at";
    node.appendChild(el("p", { class: "an-call__pass-price", "data-hook": "analyst-pass-price",
      text: `${when} ${formatAmerican(call.pass_price)}` }));
  }
  if (call.what_would_change_it && !unverified(call)) {
    node.appendChild(el("p", { class: "an-call__change", text: `What would change it: ${call.what_would_change_it}` }));
  }
  const result = resultLine(call);
  if (result) node.appendChild(result);
  return node;
}

/* =====================================================================
 * The game section
 * ===================================================================*/

function head(label, meta) {
  const h = el("div", { class: "sechead" });
  h.appendChild(el("span", { class: "sechead__label", text: label }));
  h.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) h.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return h;
}

/** Most items listed under "What the analysis could not use"; the rest are counted. */
export const MISSING_SHOWN = 6;

function asSentence(text) {
  const t = String(text || "").trim();
  if (!t) return "";
  const s = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.]$/.test(s) ? s : `${s}.`;
}

/** The packet's own list of inputs the analysis could not use. `missing` null means the server
 * could not read the list: nothing is said, rather than "nothing was missing". */
export function missingBlock(missing) {
  if (!Array.isArray(missing)) return null;
  const block = el("div", { class: "an-missing", "data-hook": "analyst-missing" });
  block.appendChild(el("h3", { class: "an-family__head", text: "What the analysis could not use" }));
  if (!missing.length) {
    block.appendChild(el("p", { class: "an-none", text: "Nothing the data was expected to hold was missing." }));
    return block;
  }
  const list = el("ul", { class: "an-missing__list" });
  for (const m of missing.slice(0, MISSING_SHOWN)) {
    const text = asSentence(m && m.reason);
    if (text) list.appendChild(el("li", { text }));
  }
  block.appendChild(list);
  const more = missing.length - MISSING_SHOWN;
  if (more > 0) {
    block.appendChild(el("p", { class: "an-missing__more", "data-hook": "analyst-missing-more",
      text: `And ${more} more ${more === 1 ? "item" : "items"} not listed here.` }));
  }
  return block;
}

/** @param data  GET /analyst/{date}/{away}/{home}: {available, label, analysis, reason} */
export function renderAnalystSection(data) {
  const host = el("section", { class: "an-section", "data-hook": "analyst" });
  const label = (data && data.label) || ANALYST_LABEL;
  const analysis = data && data.analysis;
  host.appendChild(head("AI ANALYST",
    analysis && analysis.published_utc ? `PUBLISHED ${formatEasternClock(analysis.published_utc)}` : null));
  host.appendChild(el("p", { class: "an-label", "data-hook": "analyst-label", text: label }));

  if (!data || !data.available || !analysis) {
    host.appendChild(el("p", { class: "an-none", "data-hook": "analyst-none",
      text: (data && data.reason) || "No analysis has been published for this game." }));
    return host;
  }

  if (analysis.summary_status === "ok" && analysis.summary) {
    for (const para of String(analysis.summary).split(/\n{2,}/)) {
      if (para.trim()) host.appendChild(el("p", { class: "an-summary", "data-hook": "analyst-summary", text: para.trim() }));
    }
    for (const sentence of analysis.summary_derivations || []) {
      if (sentence) host.appendChild(el("p", { class: "an-derived an-derived--summary", "data-hook": "analyst-derivation", text: sentence }));
    }
  } else {
    host.appendChild(el("p", { class: "an-summary an-summary--withheld", "data-hook": "analyst-summary",
      text: "The written summary could not be verified against the data, so it is not shown. The calls below stand on their own." }));
  }

  const groups = groupCalls(analysis.calls);
  for (const { family, calls } of groups) {
    const block = el("div", { class: "an-family", "data-hook": "analyst-family", "data-family": family });
    block.appendChild(el("h3", { class: "an-family__head", text: FAMILY_LABEL[family] || family }));
    for (const call of calls) block.appendChild(callNode(call));
    host.appendChild(block);
  }
  const missing = missingBlock(analysis.missing);
  if (missing) host.appendChild(missing);
  host.appendChild(el("p", { class: "an-foot",
    text: "Published before first pitch and graded afterward, on the record page. Passes are shown as plainly as takes." }));
  return host;
}

/** The fetch the game page needs. A failure is an absent section, never an error page. */
export async function fetchAnalyst(date, away, home) {
  try {
    return await apiGet(`/analyst/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`);
  } catch (err) {
    return null;
  }
}

/* =====================================================================
 * The record
 * ===================================================================*/

export function unitsText(units) {
  if (units === null || units === undefined) return null;
  const n = Number(units);
  if (!Number.isFinite(n)) return null;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}u`;
}

export function rateText(family) {
  if (family.win_rate === null || family.win_rate === undefined) return null;
  return `${(Number(family.win_rate) * 100).toFixed(1)}%`;
}

function cell(tag, text, hook) {
  return el(tag, { text, "data-hook": hook });
}

function familyRow(name, f) {
  const tr = el("tr", { "data-hook": "analyst-record-row", "data-family": name });
  tr.appendChild(cell("th", FAMILY_LABEL[name] || name));
  tr.appendChild(cell("td", String(f.taken), "analyst-record-taken"));
  tr.appendChild(cell("td", String(f.passes), "analyst-record-passes"));
  tr.appendChild(cell("td", String(f.graded), "analyst-record-graded"));
  tr.appendChild(cell("td", `${f.wins}-${f.losses}-${f.pushes}`, "analyst-record-wlp"));
  tr.appendChild(cell("td", String(f.voids), "analyst-record-voids"));
  const rate = rateText(f);
  const units = unitsText(f.units);
  if (rate === null || units === null) {
    const held = el("td", { class: "an-rec__withheld", colspan: "2", "data-hook": "analyst-record-withheld",
      text: f.withheld_reason || "Not enough graded calls yet" });
    tr.appendChild(held);
  } else {
    tr.appendChild(cell("td", rate, "analyst-record-rate"));
    tr.appendChild(cell("td", units, "analyst-record-units"));
  }
  return tr;
}

/** The family table and the latest graded calls, appended to `host`. Shared by the analyst's
 * record and the supervised-session briefs' record: the same numbers drawn the same way. */
function appendRecordBody(host, record) {
  const table = el("table", { class: "an-rec__table", "data-hook": "analyst-record-table" });
  const headRow = el("tr");
  for (const h of ["Market", "Taken", "Passed", "Graded", "W-L-P", "Void", "Win rate", "Units"]) {
    headRow.appendChild(el("th", { text: h }));
  }
  table.appendChild(el("thead", {}, headRow));
  const body = el("tbody");
  const fams = record.families || {};
  for (const name of FAMILY_ORDER) {
    if (fams[name]) body.appendChild(familyRow(name, fams[name]));
  }
  table.appendChild(body);
  host.appendChild(table);

  const recent = record.recent || [];
  if (recent.length) {
    const list = el("ul", { class: "an-rec__recent", "data-hook": "analyst-record-recent" });
    for (const r of recent) {
      const who = r.player ? `${r.player} ${r.selection}` : `${r.away} at ${r.home}, ${r.selection}`;
      const price = formatAmerican(r.price);
      list.appendChild(el("li", {
        text: `${r.date}: ${who}${price ? ` at ${price}` : ""} — ${RESULT_WORDS[r.result] || r.result}`,
      }));
    }
    host.appendChild(el("h3", { class: "an-family__head", text: "Latest graded calls" }));
    host.appendChild(list);
  }
}

/** @param record  GET /analyst/record */
export function renderAnalystRecord(record) {
  const host = el("section", { class: "an-section an-rec", "data-hook": "analyst-record" });
  host.appendChild(head("AI ANALYST RECORD", "UNPROVEN"));
  host.appendChild(el("p", { class: "an-label", "data-hook": "analyst-label",
    text: (record && record.label) || ANALYST_LABEL }));
  if (!record) return host;
  const min = record.min_graded || 30;
  host.appendChild(el("p", { class: "an-rec__intro", "data-hook": "analyst-record-intro",
    text: `${record.games_published} games analysed so far, ${record.games_settled} fully settled. `
      + `Counts are always shown. A win rate and units appear for a market only after it has ${min} graded calls. `
      + "This record is kept apart from the card record and never added to it." }));
  appendRecordBody(host, record);
  if (record.pilot) host.appendChild(renderPilotRecord(record.pilot));
  return host;
}

/** The supervised-session briefs' record: its own block under its own heading, with the label the
 * server sent for it. Never merged into the counts above it. */
export function renderPilotRecord(pilot) {
  const host = el("section", { class: "an-rec an-rec--pilot", "data-hook": "analyst-pilot-record" });
  host.appendChild(el("h3", { class: "an-family__head", "data-hook": "analyst-pilot-heading",
    text: "Supervised-session briefs" }));
  host.appendChild(el("p", { class: "an-label", "data-hook": "analyst-pilot-label",
    text: pilot.label || "" }));
  const min = pilot.min_graded || 30;
  host.appendChild(el("p", { class: "an-rec__intro", "data-hook": "analyst-pilot-intro",
    text: `${pilot.games_published} games briefed so far, ${pilot.games_settled} fully settled. `
      + `A win rate and units appear for a market only after it has ${min} graded calls. `
      + "These briefs are counted apart from the analyst record above and from the card record." }));
  appendRecordBody(host, pilot);
  return host;
}

export async function mountAnalystRecord(screen) {
  let record;
  try {
    record = await apiGet("/analyst/record");
  } catch (err) {
    return null;
  }
  if (!record) return null;
  const node = renderAnalystRecord(record);
  screen.appendChild(node);
  return node;
}
