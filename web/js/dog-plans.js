/**
 * THE TRAINING SCREEN'S TWO CHOICES (owner request 2026-10-27): FINE-TUNE and FULL REBUILD.
 *
 *   Fine-tune     a small change that the server rehearsed against today's rules and only offers when it did better.
 *   Full rebuild  Claude rebuilt the rules from the hound's whole record; the server checked every limit and rehearsed the result.
 *
 * Both are SLOW (a rebuild takes a minute or two), so the server runs them as a job: POST .../fine-tune or .../rebuild starts it,
 * GET .../job/{id} is polled until it is done, and the answer is a PLAN card. This file draws what the server answered and works
 * out nothing: every number, every sentence and every rule comes from the server, text is always textContent, and the page never
 * sends a rule set back: Apply sends the plan id (and which option), and the server applies its own saved, re-checked plan.
 *
 * THE REHEARSAL IS ALWAYS LABELLED. Before and after sit side by side under "Rehearsal (hindsight, not counted in the record)", with
 * the number of graded bets said in words; a small sample says so. The card never says the next version will do better.
 *
 * A REBUILD THAT CAME BACK WITH NOTHING (owner, 2026-10-29: "this doesn't feel very helpful") is a card of its own: the server's `why`
 * (how many versions it tried and what became of them, as 2 to 4 short lines it wrote), the rehearsal of the rules the hound has now
 * WITHOUT an "Updated rules" side that was never rehearsed, and the next steps: Try fine-tune, Ask the coach, Close.
 */

import { h, clearNode } from "./hounds-core.js";
import { errorText, errorCode } from "./dog-common.js";

export const POLL_MS = 2000;
export const POLL_MAX = 240;           // eight minutes at two seconds a poll, then it stops asking

const button = (text, hook, kind, onClick, extra = {}) => h("button", Object.assign(
  { type: "button", class: `btn ${kind === "quiet" ? "btn--ghost" : "btn--primary"}`, "data-hook": hook, text, on: { click: onClick } }, extra));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** "12 graded bets, 7-5, +3.4 units" for one side of the rehearsal; a dash when it was not rehearsed. */
export function sideText(s) {
  if (!s || !Number.isInteger(s.graded)) return "Not rehearsed";
  const units = typeof s.units === "number" ? `${s.units > 0 ? "+" : ""}${s.units} units` : "";
  return `${s.graded} graded bet${s.graded === 1 ? "" : "s"}, ${s.wins}-${s.losses}${s.pushes ? `-${s.pushes}` : ""}, ${units}`.trim();
}

/** The before and after of the rehearsal, labelled. */
export function rehearsalBlock(r) {
  if (!r) return null;
  return h("div", { class: "rt-rehearsal", "data-hook": "plan-rehearsal", "data-counted": r.counted ? "1" : "0" }, [
    h("p", { class: "rt-coach__label", "data-hook": "plan-rehearsal-label", text: r.label || "Rehearsal (hindsight, not counted in the record)" }),
    h("dl", { class: "rt-record", "data-hook": "plan-rehearsal-sides" }, [
      h("div", {}, [h("dt", { text: `Rules it has now, last ${r.days} days` }), h("dd", { "data-hook": "plan-before", text: sideText(r.before) })]),
      // no candidate was rehearsed: say nothing about "updated rules" rather than a row of "Not rehearsed"
      r.after ? h("div", {}, [h("dt", { text: "Updated rules, same days" }), h("dd", { "data-hook": "plan-after", text: sideText(r.after) })]) : null]),
    h("p", { class: "hd-fine", "data-hook": "plan-sample", text: r.sample_text || "" }),
    h("p", { class: "hd-fine", "data-hook": "plan-rehearsal-note", text: r.note || "" })]);
}

/** Ask the coach: the studio's Ask tab. Inside the kennel studio the page hears "linehound:studio-tab" (the same event the builder's next steps send);
 * anywhere else (the hound's own page) it is a plain link to the kennel's Ask tab. Returns true when it asked. */
export function askCoach(dog) {
  const id = dog && dog.id;
  if (!id) return false;
  try {
    if (document.querySelector("[data-hook='studio']")) {
      const evt = new Event("linehound:studio-tab");
      evt.detail = { id, tab: "ask" };
      window.dispatchEvent(evt);
    } else {
      window.location.href = `kennel.html?dog=${encodeURIComponent(id)}&tab=ask`;
    }
    return true;
  } catch (err) { return false; }
}

/** The server's plain lines about why a rebuild came back with nothing (2 to 4 of them; the page works out nothing). */
export function whyBlock(why) {
  const lines = why && Array.isArray(why.lines) ? why.lines.filter((t) => typeof t === "string" && t.trim()).slice(0, 4) : [];
  if (!lines.length) return null;
  return h("ul", { class: "rt-why", "data-hook": "plan-why" }, lines.map((t) => h("li", { class: "plan-line", text: t })));
}

function list(hook, items) {
  return h("ul", { class: "rt-changes", "data-hook": hook }, (items || []).map((t) => h("li", { class: "rt-change", text: String(t) })));
}

/**
 * Draw a plan card in `body` and resolve with the owner's decision:
 *   { action: "apply", plan_id, choice, basis }   Apply was tapped (choice is the option picked; the main one by default)
 *   { action: "rebuild" }                          fine-tune found nothing and the owner chose the full rebuild
 *   { action: "fine-tune" }                        the rebuild found nothing and the owner chose to try the fine-tune
 *   { action: "ask" }                              the rebuild found nothing and the owner chose to ask the coach (the caller opens the Ask tab)
 *   { action: "close" }                            Not now
 */
export function showPlan({ body, card }) {
  return new Promise((resolve) => {
    clearNode(body);
    const root = h("div", { class: "rt-review rt-plan", "data-hook": "plan-card", "data-kind": card.kind || "", "data-found": card.found ? "1" : "0" });
    body.appendChild(root);
    if (!card.found) {
      root.appendChild(h("p", { class: "rt-note", role: "status", "data-hook": "plan-none", text: card.message || "Nothing to offer this time." }));
      const why = whyBlock(card.why);
      if (why) root.appendChild(why);
      if (card.rehearsal) root.appendChild(rehearsalBlock(card.rehearsal));
      if (card.chalk && card.chalk.text) root.appendChild(h("p", { class: "hd-fine", "data-hook": "plan-chalk", text: card.chalk.text }));
      const actions = [button("Close", "plan-close", "quiet", () => resolve({ action: "close" }))];
      if (card.kind === "minor" && card.rebuild_offer) actions.push(button("Full rebuild", "plan-to-rebuild", "primary", () => resolve({ action: "rebuild" })));
      // a rebuild that found nothing is not a dead end: the fine-tune is still open, and the coach can be asked (owner, 2026-10-29)
      if (card.kind === "rebuild") {
        actions.push(button("Ask the coach", "plan-ask-coach", "quiet", () => resolve({ action: "ask" })));
        actions.push(button("Try fine-tune", "plan-try-fine-tune", "primary", () => resolve({ action: "fine-tune" })));
      }
      root.appendChild(h("div", { class: "rt-actions", "data-hook": "rites-actions" }, actions));
      return;
    }
    const ex = card.explanation || {};
    root.appendChild(h("h3", { class: "hd-h3", text: card.kind === "rebuild" ? "The rebuild" : "The fine-tune" }));
    root.appendChild(h("div", { class: "rt-note", "data-hook": "plan-explanation", "data-source": ex.source || "" },
      (ex.lines || []).map((t) => h("p", { class: "plan-line", text: String(t) }))));
    if (ex.changed && ex.changed.length) {
      root.appendChild(h("p", { class: "hd-fine", text: "What changed" }));
      root.appendChild(list("plan-changed", ex.changed));
    }
    root.appendChild(rehearsalBlock(card.rehearsal));
    // a Gematria hound's own lean (how often it backed favourites): a fact about its bets, said in numbers by the server
    if (card.chalk && card.chalk.text) root.appendChild(h("p", { class: "hd-fine", "data-hook": "plan-chalk", text: card.chalk.text }));
    if (card.kind === "rebuild" && card.beats_current === false) {
      root.appendChild(h("p", { class: "rt-note", "data-hook": "plan-not-better",
        text: "In the rehearsal this rebuild did not do better than the rules it has now. It is a different approach, so the choice is yours." }));
    }
    if (card.analyst && card.analyst.weak_spots && card.analyst.weak_spots.length) {
      root.appendChild(h("p", { class: "hd-fine", text: "Things to keep in mind" }));
      root.appendChild(list("plan-weak", card.analyst.weak_spots));
    }
    let choice = card.choice || null;
    const ups = Array.isArray(card.runners_up) ? card.runners_up : [];
    if (ups.length) {
      const group = h("div", { class: "rt-plan__others", "data-hook": "plan-others" }, [h("p", { class: "hd-fine", text: "Other rebuilds it tried" })]);
      const radios = [];
      const add = (value, text, after, checked) => {
        const input = h("input", { type: "radio", name: "plan-choice", value, "data-hook": "plan-choice", "aria-label": text });
        input.checked = checked;
        input.addEventListener("change", () => { choice = value; });
        radios.push(input);
        group.appendChild(h("label", { class: "hd-fine" }, [input, " ", text, ` (${sideText(after)})`]));
      };
      add(card.choice, "Best of the rebuilds", card.rehearsal && card.rehearsal.after, true);
      ups.forEach((u) => add(u.choice, `${u.label}`, u.after, false));
      root.appendChild(group);
    }
    root.appendChild(h("p", { class: "hd-fine", "data-hook": "plan-honesty", text: card.honesty || "" }));
    if (card.usage) root.appendChild(h("p", { class: "hd-fine", "data-hook": "plan-usage", text: `Full rebuilds left today: ${card.usage.left_today} of ${card.usage.limit_per_day}.` }));
    root.appendChild(h("div", { class: "rt-actions", "data-hook": "rites-actions" }, [
      button("Not now", "plan-close", "quiet", () => resolve({ action: "close" })),
      button("Apply", "plan-apply", "primary", () => resolve({ action: "apply", plan_id: card.plan_id, choice, basis: card.basis }))]));
  });
}

/**
 * Start a job and poll it. `start()` returns the job view; `poll(id)` returns it again. Resolves with the finished card, or throws the
 * server's error (a refused start, a failed job). `onStage(text)` shows what the server says it is doing.
 */
export async function runJob({ start, poll, onStage = () => {}, wait = sleep, interval = POLL_MS, max = POLL_MAX }) {
  let job = await start();
  for (let i = 0; i < max; i += 1) {
    if (job.state === "done") return job.result;
    if (job.state === "failed") {
      const e = job.error || {};
      const err = new Error(e.message || "That step could not finish just now. Nothing was changed.");
      err.detail = { error: e.code || "job_failed", message: err.message };
      throw err;
    }
    onStage(job.stage || "Working");
    await wait(interval);
    job = await poll(job.job_id);
  }
  const err = new Error("That is taking longer than expected. Nothing was changed; try again in a few minutes.");
  err.detail = { error: "job_slow", message: err.message };
  throw err;
}

export { errorText, errorCode };
