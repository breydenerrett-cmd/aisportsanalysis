/**
 * The AI desk's part of web/hound.html: "How the desk argued" and "Where they disagree".
 *
 * WHAT THE DESK IS. The hounds in the categories `ai-desk` and `persona` (config/desk_hounds.json,
 * docs/PREREG_DESK_HOUNDS.md) are one model reading the same frozen data under different instructions. The
 * Desk argues a game in the open: four analysts each write a checked report, a bull and a bear argue from
 * them, and a head reads everything and takes at most two bets or passes. A persona is one instruction and one
 * decision. Each published game leaves two files: `transcript.json` (every stage, every attempt, the checker's
 * verdict, the code's strikes, the final decisions) and `disagreement.json` (where the seven hounds split).
 *
 * THE SHAPES READ HERE are src/hounds/desk/publish.py's: a transcript is `{game_id, away, home, date,
 * model, prompt_version, label, stages: [{stage, title, kind, state, final_attempt, attempts: [{attempt,
 * response, kept, struck, rejected}]}], hounds: {hound_id: {takes, struck} | null}}`; a report response is
 * `{text, findings: [{claim, evidence, derived}], focus}`; a decision response is `{summary, decisions:
 * [{slot_id, selection, price, book, probability, reasons, case_against, what_would_change_it}]}`; a
 * disagreement table is `{slots: [{slot_id, label, market, status, takers, hounds: {id: {decision, ...}}}],
 * counts, note}`. They reach the page through GET /hounds/{id}/desk and /hounds/{id}/desk/{game_id}
 * (api/hounds.py, src/hounds/desk_view.py).
 *
 * HONEST EMPTY STATES. Before the first publish there is nothing to show, and the page says so. A stage that
 * is not in a transcript, an answer that could not be read, a game with no disagreement file: each is said in
 * words, never filled in. Everything a model wrote is shown as plain text (never as markup), labelled as
 * written by a model and unproven. Paper only. Not advice.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, categoryOf, describeError, fmtPrice, fmtWhen, shortDate, isNum, NOT_REPORTED,
} from "./hounds-core.js";

export const DESK_CATEGORIES = ["ai-desk", "persona"];
export const MODEL_LABEL = "Written by AI models from the data on this page. Unproven. Paper only, not advice.";
export const NO_GAMES_TEXT =
  "The desk has not published a game yet. When it does, every analyst's report, the bull and bear cases and the "
  + "decision will be here, with what the checker and the code struck.";
export const NOT_IN_TRANSCRIPT = "This stage is not in this game's transcript.";
export const UNREADABLE = "The answer for this stage could not be read, so nothing is shown for it.";

const ANALYST_PREFIX = "analyst_";

export function isDeskHound(hound) {
  return DESK_CATEGORIES.includes(categoryOf(hound));
}

export function isPersona(hound) {
  return categoryOf(hound) === "persona";
}

/** The decision stage of a persona: `desk_sharp` decides in `persona_sharp`. The Desk's is `head`. */
export function decisionStageOf(hound) {
  if (isPersona(hound)) return `persona_${String(hound.id).replace(/^desk_/, "")}`;
  return "head";
}

/** A short name for a hound id in a table header: "desk_ai" is "Desk", "desk_sharp" is "Sharp". */
export function deskName(id) {
  const raw = String(id).replace(/^desk_/, "");
  if (raw === "ai") return "Desk";
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

/** The attempt that counts: the stage's `final_attempt`, else the last one it made. */
export function finalAttempt(stage) {
  const attempts = stage && Array.isArray(stage.attempts) ? stage.attempts : [];
  if (!attempts.length) return null;
  const wanted = stage.final_attempt;
  return attempts.find((a) => a && a.attempt === wanted) || attempts[attempts.length - 1];
}

function cap(text) {
  const t = String(text || "");
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

// ---- one stage -------------------------------------------------------------------------------------------

function claimList(items, hook) {
  const list = Array.isArray(items) ? items.filter((x) => x && typeof x === "object") : [];
  if (!list.length) return null;
  return h("ul", { class: "hd-desk__claims", "data-hook": hook }, list.map((r) => {
    const evidence = Array.isArray(r.evidence) ? r.evidence.length : 0;
    return h("li", {}, [String(r.claim || NOT_REPORTED),
      h("span", { class: "hd-fine", text: ` (${plural(evidence, "piece", "pieces")} of evidence)` })]);
  }));
}

function checkNote(attempt) {
  const bits = [];
  if (isNum(attempt.kept)) bits.push(`${attempt.kept} kept`);
  if (isNum(attempt.struck) && attempt.struck > 0) bits.push(`${attempt.struck} struck`);
  if (isNum(attempt.rejected) && attempt.rejected > 0) bits.push(`${attempt.rejected} rejected`);
  return bits.length ? `Checker: ${bits.join(", ")}.` : "";
}

/** A report stage (an analyst, the bull, the bear): its text and the claims it rests on. */
export function renderReport(stage, hook) {
  const box = h("details", { class: "hd-desk__stage", open: "", "data-hook": hook, "data-stage": stage ? stage.stage : "" });
  if (!stage) {
    box.appendChild(h("summary", { text: "Missing stage" }));
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "stage-empty", text: NOT_IN_TRANSCRIPT }));
    return box;
  }
  box.appendChild(h("summary", { text: cap(stage.title || stage.stage) }));
  const attempt = finalAttempt(stage);
  const response = attempt && attempt.response && typeof attempt.response === "object" ? attempt.response : null;
  if (!response) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "stage-empty",
      text: attempt ? UNREADABLE : "This stage made no attempt that is saved." }));
    return box;
  }
  box.appendChild(h("p", { class: "hd-desk__text", "data-hook": "stage-text", text: String(response.text || NOT_REPORTED) }));
  const claims = claimList(response.findings, "stage-claims");
  box.appendChild(claims || h("p", { class: "hd-muted", text: "No findings were listed." }));
  const note = checkNote(attempt);
  box.appendChild(h("p", { class: "hd-fine", text: `${plural(stage.attempts.length, "attempt", "attempts")}. ${note}`.trim() }));
  return box;
}

function takesTable(decisions) {
  const head = ["Slot", "Selection", "Price (book)", "Stated probability", "What would change it"];
  return h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": "The takes, scrolls sideways on a phone" }, [
    h("table", { class: "hd-table", "data-hook": "desk-takes" }, [
      h("thead", {}, [h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))]),
      h("tbody", {}, decisions.map((d) => h("tr", { "data-slot": String(d.slot_id || "") }, [
        h("td", { text: String(d.slot_id || NOT_REPORTED) }),
        h("td", { text: String(d.selection || NOT_REPORTED) }),
        h("td", { text: `${fmtPrice(d.price)}${d.book ? ` (${d.book})` : ""}` }),
        h("td", { text: isNum(d.probability) ? `${(d.probability * 100).toFixed(1)}%` : NOT_REPORTED }),
        h("td", { text: String(d.what_would_change_it || "") }),
      ])))])]);
}

/** A decision stage (the head, or a persona): the summary, the takes, and what code or the checker struck. */
export function renderDecision(stage, hook, verdictFor) {
  const box = h("details", { class: "hd-desk__stage", open: "", "data-hook": hook, "data-stage": stage ? stage.stage : "" });
  if (!stage) {
    box.appendChild(h("summary", { text: "Decision" }));
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "stage-empty", text: NOT_IN_TRANSCRIPT }));
    return box;
  }
  box.appendChild(h("summary", { text: cap(stage.title || stage.stage) }));
  const attempt = finalAttempt(stage);
  const response = attempt && attempt.response && typeof attempt.response === "object" ? attempt.response : null;
  if (!response) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "stage-empty",
      text: attempt ? `${UNREADABLE} The hound passed the game.` : "This stage made no attempt that is saved." }));
    return box;
  }
  box.appendChild(h("p", { class: "hd-desk__text", "data-hook": "stage-text", text: String(response.summary || NOT_REPORTED) }));
  const decisions = Array.isArray(response.decisions) ? response.decisions.filter((d) => d && typeof d === "object") : [];
  const kept = (verdictFor && Array.isArray(verdictFor.takes)) ? verdictFor.takes : null;
  const struck = (verdictFor && Array.isArray(verdictFor.struck)) ? verdictFor.struck : [];
  if (!decisions.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "desk-passed", text: "It took nothing: a pass is a decision." }));
  } else {
    box.appendChild(takesTable(decisions));
    const first = decisions.map((d) => (Array.isArray(d.reasons) && d.reasons[0] && d.reasons[0].claim) || "").filter(Boolean);
    if (first.length) {
      box.appendChild(h("ul", { class: "hd-desk__claims", "data-hook": "desk-reasons" }, first.map((c) => h("li", { text: c }))));
    }
  }
  if (kept !== null) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "desk-kept",
      text: `After code and the checker: ${plural(kept.length, "take stands", "takes stand")}.` }));
  }
  if (struck.length) {
    box.appendChild(h("ul", { class: "hd-desk__struck", "data-hook": "desk-struck" }, struck.map((s) =>
      h("li", { text: `Struck${s.selection ? ` (${s.selection})` : ""} by ${s.rule || "a rule"}: ${s.reason || "no reason given"}` }))));
  }
  box.appendChild(h("p", { class: "hd-fine", text: `${plural(stage.attempts.length, "attempt", "attempts")}. ${checkNote(attempt)}`.trim() }));
  return box;
}

// ---- a whole game ----------------------------------------------------------------------------------------

/** "How the desk argued" for one game. The Desk shows analysts, bull, bear and head; a persona shows its call. */
export function renderTranscript(box, payload, hound) {
  clearNode(box);
  const t = payload && payload.transcript && typeof payload.transcript === "object" ? payload.transcript : null;
  if (!t) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "transcript-missing",
      text: `This game's transcript is not available: ${payload && payload.transcript_problem ? payload.transcript_problem : "the server sent none"}.` }));
    return;
  }
  const stages = new Map((Array.isArray(t.stages) ? t.stages : []).map((s) => [s.stage, s]));
  const intro = [`${t.away || payload.away || "?"} at ${t.home || payload.home || "?"}, ${shortDate(t.date || payload.date) || NOT_REPORTED}.`];
  if (t.model) intro.push(`Model: ${t.model}.`);
  if (t.prompt_version) intro.push(`Prompt ${t.prompt_version}.`);
  if (t.published_utc) intro.push(`Published ${fmtWhen(t.published_utc)}.`);
  box.appendChild(h("p", { class: "hd-desk__game", "data-hook": "desk-game-line", text: intro.join(" ") }));
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "desk-label", text: t.label || MODEL_LABEL }));
  if (payload.transcript_sha256_ok === false) {
    box.appendChild(h("p", { class: "hd-state hd-state--down", role: "alert", "data-hook": "desk-hash-bad",
      text: "This transcript does not match the checksum the ledger recorded when it was published. Treat it as altered." }));
  } else if (payload.transcript_sha256_ok === true) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "desk-hash-ok", text: "The transcript matches the checksum in the ledger." }));
  }
  const mine = t.hounds && typeof t.hounds === "object" ? t.hounds[hound.id] : null;
  if (isPersona(hound)) {
    box.appendChild(h("h3", { class: "hd-h3", text: "The persona's call" }));
    box.appendChild(renderDecision(stages.get(decisionStageOf(hound)), "desk-persona", mine));
    return;
  }
  const analysts = [...stages.values()].filter((s) => String(s.stage).startsWith(ANALYST_PREFIX));
  box.appendChild(h("h3", { class: "hd-h3", text: "The analysts" }));
  if (!analysts.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "analysts-empty", text: "No analyst report is in this transcript." }));
  } else {
    const wrap = h("div", { "data-hook": "desk-analysts" });
    for (const s of analysts) wrap.appendChild(renderReport(s, "desk-analyst"));
    box.appendChild(wrap);
  }
  box.appendChild(h("h3", { class: "hd-h3", text: "The bull and the bear" }));
  box.appendChild(renderReport(stages.get("bull") || null, "desk-bull"));
  box.appendChild(renderReport(stages.get("bear") || null, "desk-bear"));
  box.appendChild(h("h3", { class: "hd-h3", text: "The head's decision" }));
  box.appendChild(renderDecision(stages.get("head") || null, "desk-head", mine));
}

function cellText(cell) {
  if (!cell || typeof cell !== "object") return { text: NOT_REPORTED, tone: "unknown" };
  if (cell.decision === "TAKE") {
    return { text: `${cell.selection || "TAKE"}${isNum(cell.price) ? ` ${fmtPrice(cell.price)}` : ""}`, tone: "take" };
  }
  if (cell.decision === "PASS") return { text: "pass", tone: "pass" };
  if (cell.decision === "unanswered") return { text: "not answered", tone: "unanswered" };
  return { text: String(cell.decision || NOT_REPORTED), tone: "unknown" };
}

const STATUS_WORDS = {
  split: "Split: opposite sides taken", agree: "Agree: same side taken", lone: "Lone: one hound took it",
  none: "None: nobody took it",
};

/** "Where they disagree": a market per row, a hound per column, one status word per row. */
export function renderDisagreement(box, payload, hound) {
  clearNode(box);
  const table = payload && payload.disagreement && typeof payload.disagreement === "object" ? payload.disagreement : null;
  if (!table) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "disagree-missing",
      text: `There is no disagreement table for this game: ${payload && payload.disagreement_problem ? payload.disagreement_problem : "the server sent none"}.` }));
    return;
  }
  const slots = Array.isArray(table.slots) ? table.slots : [];
  if (!slots.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "disagree-empty", text: "This game's table lists no market slots." }));
    return;
  }
  const ids = [];
  for (const slot of slots) for (const id of Object.keys(slot.hounds || {})) if (!ids.includes(id)) ids.push(id);
  const counts = table.counts && typeof table.counts === "object" ? table.counts : null;
  if (counts) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "disagree-counts",
      text: `Markets: ${["split", "agree", "lone", "none"].filter((k) => isNum(counts[k])).map((k) => `${counts[k]} ${k}`).join(", ")}.` }));
  }
  const head = ["Market", "Status"].concat(ids.map(deskName));
  const rows = slots.map((slot) => h("tr", { "data-slot": String(slot.slot_id || ""), "data-status": String(slot.status || "") }, [
    h("td", { text: String(slot.label || slot.slot_id || NOT_REPORTED) }),
    h("td", { "data-hook": "disagree-status", text: STATUS_WORDS[slot.status] || String(slot.status || NOT_REPORTED) }),
    ...ids.map((id) => {
      const cell = (slot.hounds || {})[id];
      const c = cellText(cell);
      const struck = cell && Array.isArray(cell.struck) ? cell.struck : [];
      return h("td", { "data-cell": c.tone, "data-hound": id, class: id === hound.id ? "hd-desk__me" : "" }, [
        c.text,
        ...struck.map((s) => h("span", { class: "hd-fine hd-desk__strike",
          text: ` struck by ${s.rule || "a rule"}${s.reason ? `: ${s.reason}` : ""}` })),
      ]);
    }),
  ]));
  box.appendChild(h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": "Where the hounds disagree, scrolls sideways on a phone" }, [
    h("table", { class: "hd-table", "data-hook": "disagree-table" }, [
      h("caption", { class: "hd-sr-only", text: "For each market of this game, what each desk hound decided" }),
      h("thead", {}, [h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))]),
      h("tbody", {}, rows)])]));
  if (table.note) box.appendChild(h("p", { class: "hd-fine", "data-hook": "disagree-note", text: table.note }));
}

// ---- loading ---------------------------------------------------------------------------------------------

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function show(section, on) {
  if (!section) return;
  if (on) { section.hidden = false; section.removeAttribute("hidden"); } else { section.hidden = true; section.setAttribute("hidden", ""); }
}

function gameLabel(g) {
  const where = `${g.away || "?"} at ${g.home || "?"}`;
  const took = isNum(g.takes) ? `, ${plural(g.takes, "take", "takes")}` : "";
  return `${shortDate(g.date) || NOT_REPORTED}: ${where}${took}`;
}

async function loadGame(hound, id) {
  const box = q("hound-desk");
  const dis = q("hound-disagree");
  clearNode(box);
  box.appendChild(h("p", { class: "hd-muted", text: "Loading how the desk argued..." }));
  try {
    const payload = await apiGet(`/hounds/${encodeURIComponent(hound.id)}/desk/${encodeURIComponent(id)}`);
    renderTranscript(box, payload, hound);
    if (isPersona(hound) && dis) renderDisagreement(dis, payload, hound);
  } catch (err) {
    clearNode(box);
    const e = describeError(err, "this game's transcript");
    box.appendChild(h("div", { class: `hd-state hd-state--${e.kind}`, role: "status", "data-hook": "section-state", "data-kind": e.kind },
      [h("p", { text: e.text })]));
  }
}

/** Show the desk sections for a desk hound and load its newest game. Other hounds never see them. */
export async function bootDesk(hound) {
  const section = q("hound-desk-section");
  const disSection = q("hound-disagree-section");
  const on = isDeskHound(hound);
  show(section, on);
  show(disSection, on && isPersona(hound));
  if (!on) return;
  const picker = q("desk-games");
  const box = q("hound-desk");
  const dis = q("hound-disagree");
  clearNode(picker);
  let listing;
  try {
    listing = await apiGet(`/hounds/${encodeURIComponent(hound.id)}/desk`);
  } catch (err) {
    clearNode(box);
    const e = describeError(err, "the desk's games");
    box.appendChild(h("div", { class: `hd-state hd-state--${e.kind}`, role: "status", "data-hook": "section-state", "data-kind": e.kind },
      [h("p", { text: e.text })]));
    if (dis) { clearNode(dis); dis.appendChild(h("p", { class: "hd-muted", text: "The table needs the desk's games, which are not available right now." })); }
    return;
  }
  const games = Array.isArray(listing && listing.games) ? listing.games : [];
  if (!games.length) {
    clearNode(box);
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "desk-none", text: NO_GAMES_TEXT }));
    if (dis) { clearNode(dis); dis.appendChild(h("p", { class: "hd-muted", "data-hook": "disagree-none", text: "No game has been published yet, so there is nothing to compare." })); }
    return;
  }
  const select = h("select", { "data-hook": "desk-game", "aria-label": "Which game to show" },
    games.map((g) => h("option", { value: String(g.game_id), text: gameLabel(g) })));
  select.value = String(games[0].game_id);
  select.addEventListener("change", () => { loadGame(hound, select.value); });
  picker.appendChild(h("label", { for: "desk-game-select", text: "Game " }));
  select.setAttribute("id", "desk-game-select");
  picker.appendChild(select);
  await loadGame(hound, String(games[0].game_id));
}
