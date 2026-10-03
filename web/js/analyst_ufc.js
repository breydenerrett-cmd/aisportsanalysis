/**
 * THE UFC AI ANALYST on the page -- one self-contained module: the renderers and the
 * fetches they need. It is the MLB analyst's page code (analyst.js) for fights, built on
 * it: every call is drawn by the same `callNode`, so a PASS looks exactly like a TAKE here
 * too.
 *
 *   renderUfcAnalystEvent(data)    one event's published analysis: for each bout in card
 *                                  order, who is fighting, the summary, then the calls
 *                                  grouped by market. The fight-night page appends it and
 *                                  does nothing else with it.
 *   fetchUfcAnalyst(eventId)       GET /analyst/ufc/{event_id}; a failure is null, never
 *                                  an error page.
 *   renderUfcAnalystRecord(record) the public record, by market family.
 *   mountUfcAnalystRecord(screen)  fetches GET /analyst/ufc/record and appends the section;
 *                                  a failed fetch leaves the page as it was.
 *
 * HOW A PAGE USES IT (two lines; nothing else on the page changes)
 *
 *     import { fetchUfcAnalyst, renderUfcAnalystEvent } from "./analyst_ufc.js";
 *     const data = await fetchUfcAnalyst(eventId);
 *     if (data) screen.appendChild(renderUfcAnalystEvent(data));
 *
 * A page that lays out its own bout cards can fetch once and draw one bout where it belongs:
 * `data.analysis.bouts` is keyed by `bout_id` (the data layer's id) and `boutNode(bout)` renders one.
 *
 * WHAT THIS PAGE MUST NEVER DO (the MLB module's rules, unchanged)
 * -------------------------------------------------------------------
 * - Make a pass look smaller than a take. PASS is the analyst's default and an honest
 *   answer; it gets the same type, the same row and the same reasons as a take.
 * - Print a win rate or a return under 30 graded calls in a family. The server already sends
 *   null for both; this file prints the reason it was given and never computes a rate.
 * - Drop the label. Every render starts with the same sentence, from the server (`label`),
 *   with the same wording as the constant in analyst.js if the server ever omits it.
 * - Show a call the checker could not verify as though it were analysis. Those arrive as a
 *   PASS whose reason says so; they are drawn like any PASS.
 *
 * The API serves what the ledger froze before each bout started. This file reads it. It
 * makes no call to a model, computes no price and re-derives nothing.
 */

import { apiGet } from "./api.js";
import { el, formatAmerican, formatEasternClock } from "./dom.js";
import { ANALYST_LABEL, callNode } from "./analyst.js";

/* Families in the order they are shown; the words a reader sees for each. */
export const UFC_FAMILY_ORDER = ["moneyline", "method", "rounds_total"];
export const UFC_FAMILY_LABEL = {
  moneyline: "Moneyline",
  method: "Method of victory",
  rounds_total: "Rounds total",
};

const SEGMENT_WORDS = { main: "Main card", prelims: "Prelims", early_prelims: "Early prelims" };
const RESULT_WORDS = { WIN: "Won", LOSS: "Lost", PUSH: "Push", VOID: "Void" };

export function segmentWord(segment) {
  if (!segment) return null;
  return SEGMENT_WORDS[segment] || String(segment).replace(/_/g, " ");
}

/** Calls grouped by family, in UFC_FAMILY_ORDER, each group in the order the server sent.
 * A family with no calls is omitted. */
export function groupUfcCalls(calls) {
  const by = new Map();
  for (const call of calls || []) {
    const fam = call.family || call.market || "other";
    if (!by.has(fam)) by.set(fam, []);
    by.get(fam).push(call);
  }
  const order = UFC_FAMILY_ORDER.filter((f) => by.has(f))
    .concat([...by.keys()].filter((f) => !UFC_FAMILY_ORDER.includes(f)));
  return order.map((family) => ({ family, calls: by.get(family) }));
}

function head(label, meta) {
  const h = el("div", { class: "sechead" });
  h.appendChild(el("span", { class: "sechead__label", text: label }));
  h.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) h.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return h;
}

/* =====================================================================
 * One bout
 * ===================================================================*/

export function boutNode(bout) {
  const node = el("section", {
    class: "an-ufc-bout", "data-hook": "analyst-ufc-bout", "data-bout": bout.bout_id || "",
  });
  node.appendChild(el("h3", { class: "an-ufc-bout__head", "data-hook": "analyst-ufc-bout-head",
    text: `${bout.fighter_a || "Fighter A"} vs ${bout.fighter_b || "Fighter B"}` }));
  const bits = [bout.weight_class, segmentWord(bout.card_segment)];
  if (bout.scheduled_rounds) bits.push(`${bout.scheduled_rounds} rounds`);
  const meta = bits.filter(Boolean).join(" · ");
  if (meta) node.appendChild(el("p", { class: "an-ufc-bout__meta", text: meta }));
  if (bout.result_text) {
    node.appendChild(el("p", { class: "an-ufc-bout__result", "data-hook": "analyst-ufc-result",
      text: bout.result_text }));
  }

  if (bout.summary_status === "ok" && bout.summary) {
    for (const para of String(bout.summary).split(/\n{2,}/)) {
      if (para.trim()) {
        node.appendChild(el("p", { class: "an-summary", "data-hook": "analyst-summary", text: para.trim() }));
      }
    }
  } else {
    node.appendChild(el("p", { class: "an-summary an-summary--withheld", "data-hook": "analyst-summary",
      text: "The written summary could not be verified against the data, so it is not shown. The calls below stand on their own." }));
  }

  for (const { family, calls } of groupUfcCalls(bout.calls)) {
    const block = el("div", { class: "an-family", "data-hook": "analyst-family", "data-family": family });
    block.appendChild(el("h4", { class: "an-family__head", text: UFC_FAMILY_LABEL[family] || family }));
    for (const call of calls) block.appendChild(callNode(call));
    node.appendChild(block);
  }
  return node;
}

/* =====================================================================
 * The event section
 * ===================================================================*/

/** @param data  GET /analyst/ufc/{event_id}: {available, label, analysis, reason} */
export function renderUfcAnalystEvent(data) {
  const host = el("section", { class: "an-section an-ufc", "data-hook": "analyst-ufc" });
  const label = (data && data.label) || ANALYST_LABEL;
  const analysis = data && data.analysis;
  host.appendChild(head("AI ANALYST", analysis && analysis.event_name ? analysis.event_name : null));
  host.appendChild(el("p", { class: "an-label", "data-hook": "analyst-label", text: label }));

  if (!data || !data.available || !analysis || !(analysis.bouts || []).length) {
    host.appendChild(el("p", { class: "an-none", "data-hook": "analyst-none",
      text: (data && data.reason) || "No analysis has been published for this event." }));
    return host;
  }

  for (const bout of analysis.bouts) host.appendChild(boutNode(bout));
  host.appendChild(el("p", { class: "an-foot",
    text: "Each bout was published before its scheduled start and is graded afterward, on the record page. Passes are shown as plainly as takes." }));
  return host;
}

/** The fetch the fight-night page needs. A failure is an absent section, never an error page. */
export async function fetchUfcAnalyst(eventId) {
  try {
    return await apiGet(`/analyst/ufc/${encodeURIComponent(eventId)}`);
  } catch (err) {
    return null;
  }
}

/* =====================================================================
 * The record
 * ===================================================================*/

function unitsText(units) {
  if (units === null || units === undefined) return null;
  const n = Number(units);
  if (!Number.isFinite(n)) return null;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}u`;
}

function rateText(family) {
  if (family.win_rate === null || family.win_rate === undefined) return null;
  return `${(Number(family.win_rate) * 100).toFixed(1)}%`;
}

function cell(tag, text, hook) {
  return el(tag, { text, "data-hook": hook });
}

function familyRow(name, f) {
  const tr = el("tr", { "data-hook": "analyst-record-row", "data-family": name });
  tr.appendChild(cell("th", UFC_FAMILY_LABEL[name] || name));
  tr.appendChild(cell("td", String(f.taken), "analyst-record-taken"));
  tr.appendChild(cell("td", String(f.passes), "analyst-record-passes"));
  tr.appendChild(cell("td", String(f.graded), "analyst-record-graded"));
  tr.appendChild(cell("td", `${f.wins}-${f.losses}-${f.pushes}`, "analyst-record-wlp"));
  tr.appendChild(cell("td", String(f.voids), "analyst-record-voids"));
  const rate = rateText(f);
  const units = unitsText(f.units);
  if (rate === null || units === null) {
    tr.appendChild(el("td", { class: "an-rec__withheld", colspan: "2", "data-hook": "analyst-record-withheld",
      text: f.withheld_reason || "Not enough graded calls yet" }));
  } else {
    tr.appendChild(cell("td", rate, "analyst-record-rate"));
    tr.appendChild(cell("td", units, "analyst-record-units"));
  }
  return tr;
}

/** @param record  GET /analyst/ufc/record */
export function renderUfcAnalystRecord(record) {
  const host = el("section", { class: "an-section an-rec", "data-hook": "analyst-ufc-record" });
  host.appendChild(head("UFC AI ANALYST RECORD", "UNPROVEN"));
  host.appendChild(el("p", { class: "an-label", "data-hook": "analyst-label",
    text: (record && record.label) || ANALYST_LABEL }));
  if (!record) return host;
  const min = record.min_graded || 30;
  host.appendChild(el("p", { class: "an-rec__intro", "data-hook": "analyst-record-intro",
    text: `${record.bouts_published} bouts analysed so far, ${record.bouts_settled} fully settled. `
      + `Counts are always shown. A win rate and units appear for a market only after it has ${min} graded calls. `
      + "This record is kept apart from the card record and from the MLB analyst record, and never added to either." }));

  const table = el("table", { class: "an-rec__table", "data-hook": "analyst-record-table" });
  const headRow = el("tr");
  for (const h of ["Market", "Taken", "Passed", "Graded", "W-L-P", "Void", "Win rate", "Units"]) {
    headRow.appendChild(el("th", { text: h }));
  }
  table.appendChild(el("thead", {}, headRow));
  const body = el("tbody");
  const fams = record.families || {};
  for (const name of UFC_FAMILY_ORDER) {
    if (fams[name]) body.appendChild(familyRow(name, fams[name]));
  }
  table.appendChild(body);
  host.appendChild(table);

  const recent = record.recent || [];
  if (recent.length) {
    const list = el("ul", { class: "an-rec__recent", "data-hook": "analyst-record-recent" });
    for (const r of recent) {
      const price = formatAmerican(r.price);
      list.appendChild(el("li", {
        text: `${r.date}: ${r.fighter_a} vs ${r.fighter_b}, ${r.selection}${price ? ` at ${price}` : ""} — ${RESULT_WORDS[r.result] || r.result}`,
      }));
    }
    host.appendChild(el("h3", { class: "an-family__head", text: "Latest graded calls" }));
    host.appendChild(list);
  }
  return host;
}

export async function mountUfcAnalystRecord(screen) {
  let record;
  try {
    record = await apiGet("/analyst/ufc/record");
  } catch (err) {
    return null;
  }
  if (!record) return null;
  const node = renderUfcAnalystRecord(record);
  screen.appendChild(node);
  return node;
}
