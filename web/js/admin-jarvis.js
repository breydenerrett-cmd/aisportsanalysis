/**
 * THE JARVIS BRIEFING TAB of web/admin.html -- the owner-only, paper-only pre-game briefing (src/jarvis/), read from
 * GET /admin/jarvis/brief?date=YYYY-MM-DD (api/jarvis.py, behind the same admin token as every other admin route).
 *
 * HONESTY RULES, the same ones the briefing itself keeps:
 *   * every pick says EXPERIMENTAL when its probability comes from a source not yet shown to be calibrated; the page draws the label the
 *     server sent and never upgrades it;
 *   * "EV" here is the briefing's own estimate at the best price, with the probability it used beside the break-even it had to beat. It is
 *     not a result, and a price that is better than the average price is a price difference, not an edge;
 *   * a number the server did not send is an em dash, never a zero; a 404 is "no briefing built yet for that date", which is not an error;
 *   * times arrive as [[w:ISO]] tokens and are shown in the viewer's own zone (web/js/local-time.js).
 */

import { el, clear } from "./dom.js";
import { chip, button } from "./admin-ui.js";
import { localizeTimes } from "./local-time.js";

const DASH = "—";

/** An American price as people write it: +120, -145. */
export function priceText(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  return value > 0 ? `+${Math.round(value)}` : `${Math.round(value)}`;
}

/** A 0-1 chance as a percent with one decimal: 0.5432 -> "54.3%". */
export function percentText(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  return `${(value * 100).toFixed(1)}%`;
}

/** The estimated EV as a signed percent of the stake: 0.0432 -> "+4.3%". */
export function evText(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  const pct = (value * 100).toFixed(1);
  return `${value >= 0 ? "+" : ""}${pct}%`;
}

/** Today's date on the baseball calendar (Eastern), "YYYY-MM-DD": the default date the tab asks for. */
export function defaultBriefDate(nowMs) {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(new Date(nowMs));
    const get = (t) => (parts.find((p) => p.type === t) || {}).value;
    if (get("year") && get("month") && get("day")) return `${get("year")}-${get("month")}-${get("day")}`;
  } catch (err) {
    /* fall through to the UTC day */
  }
  return new Date(nowMs).toISOString().slice(0, 10);
}

/** A [[w:ISO]] token (or text holding some) in the viewer's zone; "" when the stamp is missing. */
function when(text) {
  return localizeTimes(text);
}

function stamp(iso) {
  return iso ? when(`[[w:${iso}]]`) : "";
}

function listBlock(title, items, hook, tone) {
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!list.length) return null;
  const box = el("div", { class: `adm-jv__block${tone ? ` adm-jv__block--${tone}` : ""}`, "data-hook": hook });
  box.appendChild(el("div", { class: "adm-jv__label", text: title }));
  const ul = el("ul", { class: "adm-jv__list" });
  for (const line of list) ul.appendChild(el("li", { text: String(line) }));
  box.appendChild(ul);
  return box;
}

function fact(label, value, hook) {
  return el("div", { class: "adm-jv__fact" }, [
    el("dt", { class: "adm-jv__k", text: label }),
    el("dd", { class: "adm-jv__v", "data-hook": hook, text: value }),
  ]);
}

function confidenceChip(item) {
  const word = item.confidence ? String(item.confidence) : DASH;
  const tone = item.confidence === "high" ? "ok" : (item.confidence === "medium" ? "info" : "mute");
  return chip(`Confidence: ${word}`, tone, "admin-jarvis-confidence");
}

function pickCard(item, kind) {
  const card = el("li", { class: "adm-jv", "data-hook": kind === "parlay" ? "admin-jarvis-parlay" : "admin-jarvis-pick", "data-rank": String(item.rank) });
  const label = item.label ? String(item.label) : "EXPERIMENTAL";
  card.appendChild(el("div", { class: "adm-jv__top" }, [
    el("div", { class: "adm-jv__title", "data-hook": "admin-jarvis-title", text: item.label_text || DASH }),
    el("div", { class: "adm-jv__chips" }, [
      chip(label, label === "EXPERIMENTAL" ? "warn" : "ok", "admin-jarvis-label"),
      confidenceChip(item),
    ]),
  ]));
  if (kind === "parlay") {
    const legs = el("ol", { class: "adm-jv__legs", "data-hook": "admin-jarvis-legs" });
    for (const leg of item.legs || []) {
      const book = leg.best_book ? ` (${leg.best_book})` : "";
      legs.appendChild(el("li", { "data-hook": "admin-jarvis-leg",
        text: `${leg.label_text || DASH}: ${leg.game || DASH}, ${when(leg.first_pitch)}, ${priceText(leg.best_price)}${book}` }));
    }
    card.appendChild(legs);
  } else {
    card.appendChild(el("div", { class: "adm-jv__game", "data-hook": "admin-jarvis-game", text: `${item.game || DASH} · ${when(item.first_pitch)}` }));
  }
  const facts = el("dl", { class: "adm-jv__facts" });
  const bestWhere = item.best_book ? ` (${item.best_book})` : "";
  facts.appendChild(fact("Best price", `${priceText(item.best_price)}${bestWhere}`, "admin-jarvis-best"));
  if (kind !== "parlay") facts.appendChild(fact("Average price", priceText(item.average_price), "admin-jarvis-avg"));
  facts.appendChild(fact("Max acceptable price", priceText(item.max_acceptable_price), "admin-jarvis-max"));
  facts.appendChild(fact("Probability vs break-even", `${percentText(item.probability)} vs ${percentText(item.break_even)}`, "admin-jarvis-prob"));
  facts.appendChild(fact("Estimated EV at the best price", evText(item.expected_value), "admin-jarvis-ev"));
  card.appendChild(facts);
  if (item.captured) card.appendChild(el("div", { class: "adm-jv__fine", "data-hook": "admin-jarvis-captured", text: `Price read ${when(item.captured)}` }));
  if (item.confidence_why) card.appendChild(el("div", { class: "adm-jv__fine", "data-hook": "admin-jarvis-why", text: String(item.confidence_why) }));
  for (const block of [
    listBlock("Why it is here", item.reasons, "admin-jarvis-reasons"),
    listBlock("How it could lose", item.could_lose, "admin-jarvis-lose", "warn"),
    listBlock("Skip it if", item.avoid, "admin-jarvis-avoid"),
  ]) if (block) card.appendChild(block);
  return card;
}

/**
 * Draw the tab. `view` is {date, status, brief, error}: status is idle | loading | ok | none | error.
 * ctx supplies jarvisLoad(date) and jarvisSetDate(date).
 */
export function renderJarvis(host, view, ctx) {
  clear(host);
  const bar = el("div", { class: "adm-toolbar", "data-hook": "admin-jarvis-bar" });
  const input = el("input", { type: "date", class: "adm-input", "aria-label": "Briefing date", "data-hook": "admin-jarvis-date" });
  input.value = view.date || "";
  input.addEventListener("change", () => { ctx.jarvisSetDate(String(input.value || "")); });
  bar.appendChild(input);
  bar.appendChild(button("Load briefing", { variant: "primary", hook: "admin-jarvis-load",
    onClick: () => ctx.jarvisLoad(String(input.value || view.date || "")) }));
  host.appendChild(bar);

  if (view.status === "loading" || view.status === "idle") {
    host.appendChild(el("p", { class: "adm-empty", "data-hook": "admin-jarvis-status", role: "status", text: "Loading the briefing..." }));
    return;
  }
  if (view.status === "none") {
    host.appendChild(el("p", { class: "adm-empty", "data-hook": "admin-jarvis-status", role: "status",
      text: `No briefing has been built for ${view.date} yet. Nothing here is a verdict about that day's games.` }));
    return;
  }
  if (view.status === "error") {
    const code = view.error && view.error.status != null ? ` (${view.error.status})` : "";
    host.appendChild(el("p", { class: "adm-note adm-note--bad", "data-hook": "admin-jarvis-status", role: "status",
      text: `The briefing could not be loaded${code}. Pick a date as YYYY-MM-DD, or use Refresh to try again.` }));
    return;
  }

  const brief = view.brief || {};
  const singles = brief.singles || [];
  const parlays = brief.parlays || [];
  const inputs = brief.inputs || {};
  const count = (n) => (n != null ? String(n) : DASH);

  const head = el("section", { class: "adm-panel", "data-hook": "admin-jarvis-head" });
  head.appendChild(el("div", { class: "adm-panel__head" }, [
    el("h2", { class: "adm-panel__title", text: "Jarvis briefing" }),
    el("span", { class: "adm-panel__meta", "data-hook": "admin-jarvis-meta",
      text: `${brief.date || view.date} · ${String(brief.sport || "mlb").toUpperCase()} · built ${stamp(brief.generated_utc) || DASH}` }),
  ]));
  head.appendChild(el("p", { class: "adm-note", "data-hook": "admin-jarvis-frozen",
    text: `Pregame knowledge frozen as of ${stamp(brief.as_of) || DASH}. Paper only. Nothing here is published to members.` }));
  const small = singles.length + parlays.length < 5
    ? `Small sample: ${singles.length} single${singles.length === 1 ? "" : "s"} and ${parlays.length} parlay${parlays.length === 1 ? "" : "s"} `
      + `from ${count(inputs.selections_evaluated)} priced selections on ${count(inputs.games_on_board)} games. ` : "";
  head.appendChild(el("p", { class: "adm-note", "data-hook": "admin-jarvis-sample",
    text: `${small}An estimate for one slate is not a demonstrated edge; nothing here has a graded record behind it.` }));
  host.appendChild(head);

  const singlesPanel = el("section", { class: "adm-panel", "data-hook": "admin-jarvis-singles" });
  singlesPanel.appendChild(el("div", { class: "adm-panel__head" }, [el("h3", { class: "adm-panel__title", text: "Picks" }),
    el("span", { class: "adm-panel__meta", text: `${singles.length} shown` })]));
  if (!singles.length) {
    const why = brief.status === "no_board" ? "There was no board for this date." : "Nothing cleared the bar on this board.";
    singlesPanel.appendChild(el("p", { class: "adm-empty", "data-hook": "admin-jarvis-no-picks", text: why }));
  } else {
    const list = el("ul", { class: "adm-jv-list" });
    for (const s of singles) list.appendChild(pickCard(s, "single"));
    singlesPanel.appendChild(list);
  }
  host.appendChild(singlesPanel);

  const parlayPanel = el("section", { class: "adm-panel", "data-hook": "admin-jarvis-parlays" });
  parlayPanel.appendChild(el("div", { class: "adm-panel__head" }, [el("h3", { class: "adm-panel__title", text: "Parlays" }),
    el("span", { class: "adm-panel__meta", text: `${parlays.length} shown` })]));
  if (!parlays.length) {
    parlayPanel.appendChild(el("p", { class: "adm-empty", "data-hook": "admin-jarvis-no-parlays", text: brief.parlay_note || "No parlay cleared the bar." }));
  } else {
    const list = el("ul", { class: "adm-jv-list" });
    for (const p of parlays) list.appendChild(pickCard(p, "parlay"));
    parlayPanel.appendChild(list);
  }
  host.appendChild(parlayPanel);

  if (brief.rules && brief.rules.length) {
    const rules = el("section", { class: "adm-panel", "data-hook": "admin-jarvis-rules" });
    rules.appendChild(el("h3", { class: "adm-panel__title", text: "Rules this briefing keeps" }));
    const ul = el("ul", { class: "adm-jv__list" });
    for (const r of brief.rules) ul.appendChild(el("li", { text: String(r) }));
    rules.appendChild(ul);
    host.appendChild(rules);
  }
  host.appendChild(el("p", { class: "adm-note", "data-hook": "admin-jarvis-disclaimer",
    text: brief.disclaimer || "Paper bets only. Not advice. 21+. If gambling stops being fun, call 1-800-GAMBLER (1-800-426-2537)." }));
}
