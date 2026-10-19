/**
 * The "Versions" section of web/hound.html.
 *
 * Reads GET /hounds/{id}/lineage (src/hounds/learning/views.py: lineage_view):
 *   {versions: [{id, name, version_no, current, status, retired, record, clv, verdict, rule_text}],
 *    live_challengers: [C], tried_and_failed: [C], closed_undecided: [C], promoted: [C], lessons: [...],
 *    paused, rules}
 *   C = {id, status, outcome_reason, hypothesis, spec_diff, created_utc, ended_utc, looks,
 *        latest_look: {look_no, n, dates, mean, lower, upper, p_better, eligible, harm, volume_ok}}
 *
 * WHAT IT SAYS. Every version keeps its own record (a promotion starts a new one; the old one stays,
 * retired, and is linked). A live challenger runs in shadow on the same games at the same prices; the
 * page shows what it changed, the reason the coach gave (quoted, never acted on), and how its paired
 * difference against the champion stands so far. Nothing here can promote anything: the referee does,
 * by a rule fixed in advance, and the page says so. A hound with one version and no challengers says
 * exactly that. The section loads on its own and never takes the model page down.
 */

import { apiGet } from "./api.js";
import { h, clearNode, signed, isNum, fmtRecord, fmtWhen, houndHref,
  describeError, isWarming, NOT_REPORTED } from "./hounds-core.js";
import { statusOf } from "./hounds-board.js";
import { friendlyLesson } from "./hounds-voice.js";

export const NO_LINEAGE_TEXT = "This model has one version and no challengers testing.";
export const REFEREE_NOTE = "A challenger is only a suggestion. It replaces the current version only if its prices beat the current version's against the closing line by a margin fixed in advance, after at least 100 paired games, and never because of what anyone wrote about it.";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

export function diffText(spec_diff) {
  const entries = Object.entries(spec_diff || {});
  if (!entries.length) return "no change recorded";
  const fmt = (v) => (Array.isArray(v) ? `[${v.join(", ")}]` : String(v));
  return entries.map(([k, v]) => `${k}: ${fmt(v[0])} -> ${fmt(v[1])}`).join("; ");
}

export function lookText(c) {
  const lk = c && c.latest_look;
  if (!lk || !isNum(lk.n)) {
    return "Waiting for its first look, at 100 paired games. Nothing can be said about it before then.";
  }
  const bounds = isNum(lk.lower) && isNum(lk.upper) ? ` (somewhere between ${signed(lk.lower, 2)} and ${signed(lk.upper, 2)})` : "";
  const mean = isNum(lk.mean) ? `${signed(lk.mean, 2)} points` : NOT_REPORTED;
  const flag = lk.harm ? " It is doing worse than the current version." : lk.eligible ? " It has cleared the first bar; the monthly fluke check comes next." : "";
  return `Look ${lk.look_no}, after ${lk.n} paired games: its prices beat the current version's by ${mean} on average${bounds}.${flag}`;
}

/** The code-written lesson, in plain words and this page's vocabulary (current version, challenger, promoted). */
export function proLesson(text) {
  return friendlyLesson(text)
    .replace(/made the team/g, "was promoted").replace(/was cut:/g, "was retired:")
    .replace(/the starter's/g, "the current version's").replace(/the starter\b/g, "the current version")
    .replace(/its tryout/g, "its test").replace(/camp's fluke check/g, "the false-positive check");
}

function versionItem(v, currentId) {
  const st = statusOf(v);
  const status = v.current ? "Current version" : (v.retired && v.retired.cause) ? `Retired: ${v.retired.cause}` : (v.status || "");
  const rec = v.record && isNum(v.record.bets) && v.record.bets > 0 ? fmtRecord(v.record) : "no live bets yet";
  return h("li", { class: "hd-version", "data-version": String(v.version_no), "data-current": v.current ? "true" : "false" }, [
    h("p", { class: "hd-version__head" }, [
      h("strong", { text: `Version ${v.version_no}` }), " ",
      h("span", { class: "hd-fine", text: status }), " ",
      v.verdict ? h("span", { class: `hd-st hd-st--${st.tone}`, "data-status": st.key, title: st.title, text: st.text }) : null,
    ]),
    h("p", { class: "hd-fine", text: `Its own record: ${rec}.` }),
    v.id && v.id !== currentId ? h("a", { href: houndHref(v.id), "data-hook": "version-link", text: "Open this version" }) : null,
  ]);
}

function challengerItem(c) {
  return h("li", { class: "hd-challenger", "data-challenger": c.id, "data-status": c.status || "" }, [
    h("p", { class: "hd-challenger__head" }, [h("strong", { text: `Challenger ${c.id}` }), " ",
      h("span", { class: "hd-fine", text: `started ${fmtWhen(c.created_utc) || ""}` })]),
    h("p", { class: "hd-challenger__diff", text: `What it changes: ${diffText(c.spec_diff)}` }),
    c.rule_text ? h("p", { class: "hd-fine", text: `Its rule: ${c.rule_text}` }) : null,
    h("p", { class: "hd-fine", text: `The coach's pitch (quoted): "${c.hypothesis || NOT_REPORTED}"` }),
    h("p", { class: "hd-challenger__look", text: lookText(c) }),
  ]);
}

function failedItem(c, lessons) {
  const lesson = (lessons || []).find((l) => l.lesson_id === `l-${c.id}`);
  return h("li", { class: "hd-challenger hd-challenger--failed", "data-challenger": c.id, "data-status": c.status || "" }, [
    h("p", { class: "hd-challenger__head" }, [h("strong", { text: `Challenger ${c.id}` }), " ",
      h("span", { class: "hd-fine", text: `${c.status || ""}${c.outcome_reason ? `: ${c.outcome_reason}` : ""}` })]),
    h("p", { class: "hd-challenger__diff", text: `It changed: ${diffText(c.spec_diff)}` }),
    h("p", { class: "hd-challenger__look", text: lesson ? proLesson(lesson.lesson) : lookText(c) }),
  ]);
}

export function renderLineage(payload, currentId) {
  const box = q("hound-lineage");
  clearNode(box);
  const versions = Array.isArray(payload.versions) ? payload.versions : [];
  const live = payload.live_challengers || [];
  const failed = payload.tried_and_failed || [];
  const undecided = payload.closed_undecided || [];
  const promoted = payload.promoted || [];
  if (payload.paused) {
    box.appendChild(h("p", { class: "hd-state hd-state--down", "data-hook": "lineage-paused",
      text: "The learning loop has shut itself down, so no challenger is being accepted or promoted. See Learning." }));
  }
  if (versions.length <= 1 && !live.length && !failed.length && !undecided.length && !promoted.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "lineage-empty", text: NO_LINEAGE_TEXT }));
  } else {
    if (versions.length > 1) {
      box.appendChild(h("h3", { class: "hd-h3", text: "Versions, each with its own record" }));
      box.appendChild(h("ol", { class: "hd-versions", "data-hook": "versions-list" }, versions.map((v) => versionItem(v, currentId))));
    }
    if (live.length) {
      box.appendChild(h("h3", { class: "hd-h3", text: "Testing now" }));
      box.appendChild(h("ul", { class: "hd-challengers", "data-hook": "live-challengers" }, live.map(challengerItem)));
    }
    if (failed.length || undecided.length) {
      box.appendChild(h("h3", { class: "hd-h3", text: "Tested and not promoted" }));
      box.appendChild(h("ul", { class: "hd-challengers", "data-hook": "failed-challengers" },
        [...failed, ...undecided].map((c) => failedItem(c, payload.lessons))));
    }
  }
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "referee-note", text: REFEREE_NOTE }));
  box.appendChild(h("p", { class: "hd-fine" }, [h("a", { href: "learning.html", text: "Learning: do challengers actually help?" })]));
}

export async function bootLineage(hound) {
  const section = q("hound-lineage-section");
  if (!section) return;
  const box = q("hound-lineage");
  const id = hound && hound.id;
  if (!id) return;
  section.hidden = false;
  section.removeAttribute("hidden");
  clearNode(box);
  box.appendChild(h("p", { class: "hd-muted", text: "Loading the versions..." }));
  try {
    const payload = await apiGet(`/hounds/${encodeURIComponent(id)}/lineage`);
    if (!payload || typeof payload !== "object") throw Object.assign(new Error("empty"), { status: 502 });
    if (isWarming(payload)) {
      clearNode(box);
      box.appendChild(h("p", { class: "hd-muted", text: payload.message || "The numbers are still being worked out." }));
      return;
    }
    renderLineage(payload, id);
  } catch (err) {
    clearNode(box);
    const e = describeError(err, "the versions and challengers");
    box.appendChild(h("div", { class: `hd-state hd-state--${e.kind}`, role: "status", "data-hook": "section-state",
      "data-kind": e.kind }, [h("p", { text: e.text }),
      h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again", on: { click: () => { bootLineage(hound); } } })]));
  }
}
