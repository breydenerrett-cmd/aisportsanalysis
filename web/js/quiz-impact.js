/**
 * The quiz's impact meter: under each question, what the answers so far would have done over the last 1, 3 and 7 days of stored
 * boards ("Last 7 days: 14 bets, 8-6, +2.1u", or "would not have bet"), and what the answer just given changed ("this choice: +3 bets,
 * +0.8u over 7 days"). The numbers and the sentences come from POST /hounds/quiz/impact (src/hounds/quiz/impact.py); this file only
 * asks and draws.
 *
 * It asks 600 ms after the last answer (so a person tapping through sports asks once), drops any answer that arrives after a newer
 * question was sent, remembers every answer by its payload (going back and forth costs nothing), and says nothing at all when the
 * server cannot answer: the quiz never waits on it and never fails because of it. It is hindsight on paper, so the note says so.
 * Open to a signed-out visitor: it is read-only on the server.
 *
 * Written against attributes only (no classList, no dataset, no innerHTML): it runs in the node test harness's small DOM.
 */

import { h, clearNode } from "./hounds-core.js";

export const DEBOUNCE_MS = 600;
export const CHECKING_TEXT = "Checking the last 7 days...";

/** Whether a payload has anything to measure: at least a sport or a style. */
export function hasSomething(payload) {
  return !!payload && ((Array.isArray(payload.sports) && payload.sports.length > 0) || !!payload.personality);
}

const keyOf = (payload) => (payload ? JSON.stringify(payload) : "");

/** One meter. `post(path, body)` is the page's JSON poster; `getHost()` returns the element to draw into (or null). */
export function createMeter({ post, getHost, delay = DEBOUNCE_MS }) {
  const cache = new Map();
  let current = null, previous = null, timer = null, seq = 0;
  let settled = null, beforeSettled = null;        // the last two DIFFERENT payloads whose answer was drawn: the baseline for "this choice"

  function draw(data, loading) {
    const host = getHost();
    if (!host) return;
    clearNode(host);
    host.setAttribute("data-state", loading ? "loading" : data ? "ready" : "empty");
    if (loading && !data) {
      host.hidden = false;
      host.appendChild(h("p", { class: "qz-impact__line qz-impact__line--wait", text: CHECKING_TEXT }));
      return;
    }
    if (!data || (!data.available && !data.note)) { host.hidden = true; return; }
    host.hidden = false;
    if (!data.available) {
      host.appendChild(h("p", { class: "qz-fine", "data-hook": "quiz-impact-note", text: data.note }));
      return;
    }
    const list = h("ul", { class: "qz-impact__list", "data-hook": "quiz-impact-list" }, (data.windows || []).map((w) =>
      h("li", { class: "qz-impact__line", "data-hook": "quiz-impact-line", "data-days": String(w.days), "data-bets": String(w.bets), text: w.line })));
    host.appendChild(list);
    if (data.delta) host.appendChild(h("p", { class: "qz-impact__delta", "data-hook": "quiz-impact-delta", text: data.delta.line }));
    if (data.note) host.appendChild(h("p", { class: "qz-fine", "data-hook": "quiz-impact-note", text: data.note }));
  }

  async function ask(payload, prev, draft, key) {
    const mine = ++seq;
    const body = { answers: payload };
    if (prev) body.previous_answers = prev;
    if (draft) body.english_draft = draft;
    let data = null;
    try {
      data = await post("/hounds/quiz/impact", body);
    } catch (err) {
      data = null;                                        // busy, rate limited, no boards: say nothing
    }
    if (mine !== seq) return;                             // a newer question went out while this one was in the air
    if (data) {
      cache.set(key, data);
      if (keyOf(payload) !== keyOf(settled)) { beforeSettled = settled; settled = payload; }
    }
    draw(data, false);
  }

  return {
    /** Show the meter for `payload`. A payload that differs from the last one makes the last one "the answer before". */
    update(payload, draft) {
      if (timer) { clearTimeout(timer); timer = null; }
      seq += 1;                                           // anything still in the air is stale now
      if (!hasSomething(payload)) { current = null; draw(null, false); return; }
      current = payload;
      // the answer before this one is the last settled payload that is not this one: quick taps are measured against what was last SHOWN
      previous = keyOf(settled) !== keyOf(current) ? settled : beforeSettled;
      const prev = hasSomething(previous) ? previous : null;
      const key = keyOf(current) + "|" + keyOf(prev) + "|" + keyOf(draft);
      if (cache.has(key)) { draw(cache.get(key), false); return; }
      draw(null, true);
      timer = setTimeout(() => { timer = null; ask(current, prev, draft || null, key); }, delay);
    },
    /** Forget the baseline (the quiz was reset). */
    reset() {
      if (timer) { clearTimeout(timer); timer = null; }
      seq += 1; current = null; previous = null; settled = null; beforeSettled = null; draw(null, false);
    },
    cancel() { if (timer) { clearTimeout(timer); timer = null; } seq += 1; },
  };
}
