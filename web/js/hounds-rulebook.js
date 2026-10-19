/**
 * The rule's dials and the coach panel on a model's page.
 *
 *   THE DIALS (transparent): the tunable numbers in a dog's rule, each in plain words at its current value
 *   ("Steam needed: 3 points"), and when the referee last changed them ("Last changed: never", or "v2 on
 *   Oct 12 by the referee"). The data is GET /hounds/{id}/rulebook (src/hounds/dials.py).
 *
 *   COACH THIS DOG (coachable): one slider per dial, held to the dial's bounds and step grid, the current
 *   value marked, at most TWO dials changed at once (the same cap the AI coach has), an optional nickname,
 *   and "Send my tip" (POST /hounds/{id}/tips). A tip NEVER changes the dog: it is graded later like the AI
 *   coach's proposals, and only the referee changes a dog. The copy says so, in the panel and on the button.
 *
 * `dialText` words a value the same way src/hounds/dials.py does; a test runs both over every grid point
 * of every dial and demands the same strings, so the slider and the rulebook never disagree.
 */

import { h, clearNode, isNum, shortDate } from "./hounds-core.js";
import { apiGet, apiPost } from "./api.js";

export const MAX_CHANGED = 2;
export const NICK_MAX = 20;
export const NICK_RE = /^[A-Za-z0-9 ]+$/;
export const NEVER_CHANGES = "Tips are graded like the AI coach's. Only the referee can change a model.";

export function numberText(v) {
  const r = Math.round(Number(v) * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

/** A dial value in the dog's words: dialText({scale: 100, unit: "points"}, 0.03) -> "3 points". */
export function dialText(dial, value) {
  const num = numberText(value * (isNum(dial.scale) ? dial.scale : 1));
  const unit = String(dial.unit || "");
  if (unit === "%") return `${num}%`;
  if (!unit) return num;
  const word = num === "1" && unit.endsWith("s") ? unit.slice(0, -1) : unit;
  return `${num} ${word}`;
}

/** The nearest point on the dial's grid inside its bounds, with float noise rounded away. */
export function snapToGrid(dial, value) {
  const steps = Math.round((Number(value) - dial.min) / dial.step);
  const clamped = Math.max(0, Math.min(Math.round((dial.max - dial.min) / dial.step), steps));
  return Math.round((dial.min + clamped * dial.step) * 1e6) / 1e6;
}

export function sameValue(a, b) {
  return Math.abs(Number(a) - Number(b)) < 1e-9;
}

/** "Last changed: never" / "Last changed: v2 on Oct 12 by the referee". */
export function lastChangedText(rb) {
  const last = rb && rb.last_changed;
  if (!last) return "Last changed: never. It is still on its starting numbers.";
  const when = shortDate(last.utc);
  return `Last changed: v${last.version}${when ? ` on ${when}` : ""} by ${last.by || "the referee"}.`;
}

// ---- the dials, as the rulebook shows them --------------------------------------------------------------

export function renderDials(box, rb, failed) {
  clearNode(box);
  if (failed || !rb) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "dials-unavailable", text:
      "The dials did not load just now. The rule above is still the whole rule." }));
    return;
  }
  if (rb.trigger) {
    box.appendChild(h("p", { class: "hd-trigger", "data-hook": "rule-trigger", text: `This model bets when ${rb.trigger}.` }));
  }
  if (!rb.tunable || !Array.isArray(rb.dials) || rb.dials.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "no-dials", text:
      "No dials on this model. Its rule is fixed: what you read above is exactly what it does." }));
    return;
  }
  box.appendChild(h("h3", { class: "hd-h3", text: "The dials" }));
  box.appendChild(h("ul", { class: "hd-dials", "data-hook": "dials-list" }, rb.dials.map((d) =>
    h("li", { class: "hd-dial", "data-dial": d.name }, [
      h("span", { class: "hd-dial__label", text: `${d.label}: ` }),
      h("strong", { class: "hd-dial__value", "data-hook": "dial-value", text: d.text || dialText(d, d.current) }),
    ]))));
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "dials-last-changed", text: lastChangedText(rb) }));
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "dials-referee",
    text: "Only the referee turns these. Fans can send tips below; tips never change the model." }));
}

// ---- coach this dog ----------------------------------------------------------------------------------------

/** Pure: how many dials differ from the current values. */
export function changedDials(dials, picked) {
  return (dials || []).filter((d) => picked[d.name] !== undefined && !sameValue(picked[d.name], d.current));
}

export function nicknameProblem(text) {
  const t = String(text || "").trim().replace(/\s+/g, " ");
  if (!t) return "";
  if (t.length > NICK_MAX) return `Keep the nickname to ${NICK_MAX} characters.`;
  if (!NICK_RE.test(t)) return "A nickname is letters, numbers and spaces only.";
  return "";
}

function tipLine(tip, dials) {
  const parts = Object.entries(tip.values || {}).map(([name, v]) => {
    const d = (dials || []).find((x) => x.name === name);
    return d ? `${d.label} ${dialText(d, v)}` : `${name} ${v}`;
  });
  return `${tip.nickname || "A fan"}: ${parts.join(", ")}`;
}

/** The live verdicts of the coach report card (src/hounds/coach_grade.py) as a fan reads them on a tip. */
const GRADE_WORDS = { "HELPED": "HELPED", "HURT": "HURT", "NO DIFFERENCE": "NO DIFFERENCE", "TOO EARLY": "TOO EARLY" };

/** " Live: HELPED ✅ (+1.2u over 24 bets)" for a graded tip, "" for one the report card has not recorded yet. */
export function gradeText(grade) {
  if (!grade || !GRADE_WORDS[grade.label]) return "";
  const n = isNum(grade.n_paired) ? grade.n_paired : 0;
  const bets = `${n} bet${n === 1 ? "" : "s"}`;
  if (grade.label === "TOO EARLY") return ` Live: ${GRADE_WORDS[grade.label]} (${bets})`;
  const u = isNum(grade.units_diff) ? `${grade.units_diff >= 0 ? "+" : "-"}${Math.abs(grade.units_diff).toFixed(1)}u over ` : "";
  return ` Live: ${GRADE_WORDS[grade.label]} (${u}${bets})`;
}

export function renderTips(box, data, dials, failed) {
  clearNode(box);
  if (failed) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "tips-unavailable", text: "Tips did not load just now." }));
    return;
  }
  const count = data && isNum(data.count) ? data.count : 0;
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "tips-count", text:
    `Fan tips: ${count}. Grades coming from the coach report card.` }));
  const tips = (data && data.tips) || [];
  if (tips.length) {
    box.appendChild(h("ul", { class: "hd-tiplist", "data-hook": "tips-list" }, tips.map((t) =>
      h("li", { "data-tip": t.id, text: tipLine(t, dials) + (gradeText(t.grade) ? `.${gradeText(t.grade)}` : "") }))));
  }
}

/**
 * Build the panel in `box`. `ctx`: { houndId, rb }. Returns { picked, send, refreshTips } for tests.
 * Slider values are held in `picked`, snapped to the grid; a third changed dial is refused with a message
 * rather than silently dropped.
 */
export function renderCoach(box, ctx) {
  clearNode(box);
  const rb = ctx.rb;
  const dials = (rb && rb.dials) || [];
  if (!rb || !rb.tunable || dials.length === 0) return null;
  const picked = {};
  for (const d of dials) picked[d.name] = d.current;
  const msg = h("p", { class: "hd-fine", role: "status", "data-hook": "coach-status" });
  const count = h("p", { class: "hd-fine", "data-hook": "coach-count", text: "No dials changed yet." });
  const send = h("button", { type: "button", class: "btn btn--primary", "data-hook": "coach-send",
    text: "Send my tip", disabled: "" });
  const nick = h("input", { type: "text", class: "hd-input", "data-hook": "coach-nick", maxlength: String(NICK_MAX),
    placeholder: "Nickname (optional)", "aria-label": "Nickname, optional, letters and numbers", autocomplete: "off" });
  const tipsBox = h("div", { "data-hook": "coach-tips" });
  const rows = new Map();

  function sync() {
    const changed = changedDials(dials, picked);
    count.textContent = changed.length === 0 ? "No dials changed yet."
      : `${changed.length} of ${MAX_CHANGED} dials changed.`;
    if (changed.length === 0) send.setAttribute("disabled", ""); else send.removeAttribute("disabled");
    for (const d of dials) {
      const row = rows.get(d.name);
      const moved = !sameValue(picked[d.name], d.current);
      row.value.textContent = dialText(d, picked[d.name]);
      row.range.value = String(picked[d.name]);
      row.row.setAttribute("data-changed", moved ? "true" : "false");
      row.note.textContent = moved ? `now ${dialText(d, d.current)}` : "this is where it is now";
    }
  }

  function setValue(d, raw) {
    const v = snapToGrid(d, raw);
    const wasChanged = !sameValue(picked[d.name], d.current);
    const becomesChanged = !sameValue(v, d.current);
    if (becomesChanged && !wasChanged && changedDials(dials, picked).length >= MAX_CHANGED) {
      msg.textContent = `Two dials at most, same as the AI coach. Put one back first.`;
      sync();
      return false;
    }
    picked[d.name] = v;
    msg.textContent = "";
    sync();
    return true;
  }

  const list = h("div", { class: "hd-coach__dials", "data-hook": "coach-dials" });
  for (const d of dials) {
    const value = h("strong", { class: "hd-coach__value", "data-hook": "coach-value" });
    const note = h("span", { class: "hd-fine", "data-hook": "coach-current" });
    const range = h("input", { type: "range", class: "hd-range", "data-hook": "coach-range", min: String(d.min),
      max: String(d.max), step: String(d.step), value: String(d.current), "aria-label": d.label,
      on: { input: () => setValue(d, Number(range.value)) } });
    const minus = h("button", { type: "button", class: "btn btn--ghost hd-step", "data-hook": "coach-dec",
      "aria-label": `Lower ${d.label}`, text: "−", on: { click: () => setValue(d, picked[d.name] - d.step) } });
    const plus = h("button", { type: "button", class: "btn btn--ghost hd-step", "data-hook": "coach-inc",
      "aria-label": `Raise ${d.label}`, text: "+", on: { click: () => setValue(d, picked[d.name] + d.step) } });
    const reset = h("button", { type: "button", class: "btn btn--ghost hd-step", "data-hook": "coach-reset",
      "aria-label": `Put ${d.label} back`, text: "↺", on: { click: () => setValue(d, d.current) } });
    const row = h("div", { class: "hd-coach__dial", "data-dial": d.name, "data-changed": "false" }, [
      h("p", { class: "hd-coach__label" }, [d.label, ": ", value]),
      h("div", { class: "hd-coach__controls" }, [minus, range, plus, reset]),
      h("p", { class: "hd-fine hd-coach__range" }, [
        `${dialText(d, d.min)} to ${dialText(d, d.max)} · `, note]),
    ]);
    rows.set(d.name, { row, value, range, note });
    list.appendChild(row);
  }

  async function refreshTips() {
    try {
      renderTips(tipsBox, await apiGet(`/hounds/${encodeURIComponent(ctx.houndId)}/tips`), dials, false);
    } catch (err) {
      renderTips(tipsBox, null, dials, true);
    }
  }

  async function sendTip() {
    const changed = changedDials(dials, picked);
    if (changed.length === 0) return;
    const problem = nicknameProblem(nick.value);
    if (problem) { msg.textContent = problem; return; }
    const values = {};
    for (const d of changed) values[d.name] = picked[d.name];
    const body = { values };
    const name = nick.value.trim().replace(/\s+/g, " ");
    if (name) body.nickname = name;
    send.setAttribute("disabled", "");
    try {
      await apiPost(`/hounds/${encodeURIComponent(ctx.houndId)}/tips`, body);
      msg.textContent = "Tip sent. The model stays exactly as it was.";
      for (const d of dials) picked[d.name] = d.current;
      sync();
      await refreshTips();
    } catch (err) {
      const detail = err && err.detail && typeof err.detail === "object" ? err.detail : null;
      msg.textContent = (detail && detail.message) || (err && err.status === 429
        ? "That is the daily limit on tips. Come back tomorrow." : "Could not send that tip. Try again in a minute.");
      sync();
    }
  }
  send.addEventListener("click", sendTip);

  box.appendChild(h("h2", { id: "coach-h", text: "Coach this model" }));
  box.appendChild(h("p", { class: "hd-muted", text:
    "Think a dial is off? Turn up to two and send a tip. It is graded against the model's results later." }));
  box.appendChild(h("p", { class: "hd-coach__rule", "data-hook": "coach-promise", text: NEVER_CHANGES }));
  box.appendChild(list);
  box.appendChild(count);
  box.appendChild(h("div", { class: "hd-coach__send" }, [nick, send]));
  box.appendChild(msg);
  box.appendChild(tipsBox);
  sync();
  refreshTips();
  return { picked, setValue, sendTip, refreshTips };
}

/** Load the rulebook; resolves { rb, failed }. */
export async function loadRulebook(houndId) {
  try {
    const rb = await apiGet(`/hounds/${encodeURIComponent(houndId)}/rulebook`);
    return { rb: rb && typeof rb === "object" ? rb : null, failed: !rb };
  } catch (err) {
    return { rb: null, failed: true };
  }
}
