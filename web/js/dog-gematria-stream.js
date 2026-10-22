/**
 * THE GEMATRIA ANALYSIS: what the Gematria hound is really doing while Unleash (or Ask) runs, shown line by line.
 *
 * Owner, 2026-10-22: "a gematria hound should take longer to think and analyze games ... it should feel deep and real." It was real
 * already: the engine computes four cipher values for every name, the numbers of the date, thousands of coincidences per game and a
 * score for each side. The page just never showed it. This screen plays that work the way the training diagnosis plays its checks
 * (web/js/dog-diagnose.js), one line at a time:
 *
 *   per game   the ciphers computed ("Lakers: EO 33 · FR 36 ..."), the basis it read, the matches found for each side
 *              ("33: Lakers (name) = 33 EO · ... (+1)"), the score of each side with its noise and search size, and the pick or the
 *              pass with its reason.
 *
 * NOTHING HERE IS INVENTED. The lines are the server's own (GET /hounds/{id}/analysis, src/hounds/interact/gematria_analysis.py: each
 * one formatted from a value the engine computed in that call). The page adds only FRAME lines, each a label for what follows
 * ("Game 3 of 12: A @ B", "Weighed 113 games"), and every number in a frame is a count of the payload. PACING is staging: the real lines
 * are spread over about 15 to 30 seconds so a person can read them; no line, no number and no delay stands in for work that was not
 * done. When the day has fewer lines than that the stream is simply shorter.
 *
 * SKIP. After two seconds a Skip button shows; it fast-forwards the remaining lines at once. REDUCED MOTION: no timers and no
 * animation; the lines are drawn all at once, folded away, and the caller carries on.
 *
 * The stream never blocks the real request. The caller starts Unleash first and passes it as `waitFor`; the stream finishes its lines
 * and then waits on it (a last line says so), never the other way round. A payload that cannot be fetched (not a Gematria hound, the
 * server failed) ends the stream quietly: the caller shows the day as before.
 *
 * Pure DOM built with h() (text is always textContent), CSS in css/diagnose.css (the .dx classes) and css/gematria-stream.css.
 */

import { h, clearNode, isNum } from "./hounds-core.js";
import { get } from "./dog-common.js";

export const TIMING = {
  skipAfter: 2000,       // a Skip button appears after this
  target: 22000,         // all the lines together aim for about this
  lineMin: 90,           // never faster than this per line
  lineMax: 650,          // never slower than this per line
  gamePause: 350,        // a breath after each game's decision
  start: 400,            // before the first line
};

/** The call behind the stream, shared by Unleash and Ask. */
export const gematriaAnalysis = (id) => get(`/hounds/${encodeURIComponent(id)}/analysis`);

const clean = (v) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export function reducedMotion() {
  return typeof window !== "undefined" && !!window.matchMedia && !!window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The steps of a payload, in order: each is `{kind, text, tone, game}`. A "frame" step is a label made only of the payload's own counts and
 * names; every other kind is one of the server's lines, text unchanged. Pure, so a test compares the steps with the payload.
 */
export function streamSteps(payload) {
  const games = Array.isArray(payload && payload.games) ? payload.games : [];
  const steps = [];
  if (!games.length) return steps;
  const dn = payload.date_numbers && clean(payload.date_numbers.text);
  steps.push({ kind: "frame", text: `Weighing ${plural(isNum(payload.weighed) ? payload.weighed : games.length, "game", "games")} on today's board`, tone: "frame", game: -1 });
  if (dn) steps.push({ kind: "date", text: dn, tone: "none", game: -1 });
  games.forEach((g, i) => {
    steps.push({ kind: "frame", text: `Game ${i + 1} of ${games.length}: ${clean(g.game)}${g.start_et ? ` (${clean(g.start_et)})` : ""}`, tone: "frame", game: i });
    for (const line of Array.isArray(g.lines) ? g.lines : []) {
      const tone = line.kind === "decision" ? (line.status === "bet" ? "good" : "pass") : line.kind === "match" && line.none ? "thin" : "none";
      steps.push({ kind: line.kind, text: clean(line.text), tone, game: i, side: line.side || "" });
    }
  });
  const picks = isNum(payload.picks_total) ? payload.picks_total : games.filter((g) => g.status === "bet").length;
  steps.push({ kind: "frame", text: `Done: ${plural(isNum(payload.weighed) ? payload.weighed : games.length, "game", "games")} weighed, ${plural(picks, "pick", "picks")}`,
    tone: "frame", game: games.length });
  return steps;
}

const MARK = { frame: ">", date: "#", cipher: "~", basis: "·", match: "=", score: "Σ", decision: "→" };

function lineNode(step, state = "done") {
  return h("li", { class: "dx-line gs-line", "data-hook": "gematria-line", "data-kind": step.kind, "data-state": state, "data-tone": step.tone, "data-game": String(step.game) }, [
    h("span", { class: "dx-line__mark", "aria-hidden": "true", text: MARK[step.kind] || "·" }),
    h("span", { class: "dx-line__text", text: step.text })]);
}

/**
 * The finished analysis, folded away: "How it analysed today's games", the same lines. Drawn after the day (and for reduced motion),
 * so a person can read it again.
 */
export function analysisLog(payload) {
  const steps = streamSteps(payload);
  if (!steps.length) return null;
  const list = h("ol", { class: "dx-log dx-log--static gs-log", "data-hook": "gematria-log" }, steps.map((s) => lineNode(s)));
  return h("details", { class: "dk-block gs-fold dx", "data-hook": "gematria-fold", "data-motion": "reduced" }, [
    h("summary", { class: "gs-fold__sum", text: `How it analysed today's games (${steps.length} lines)` }), list,
    h("p", { class: "hd-fine", text: payload.copy || "Experimental numerology. Paper only." })]);
}

/**
 * Play the analysis inside `body`.
 *   load      () => Promise<payload>   the real request (`gematriaAnalysis(id)`)
 *   waitFor   a promise of the caller's own real request (Unleash); the stream does not resolve before it settles
 *   onStart   called once, just before the first line is drawn (the caller removes its "working" art)
 *   reduced   true for prefers-reduced-motion: nothing is drawn here; the caller shows `analysisLog(payload)` after its answer
 *   speed     1 normally; 0 runs without waiting (tests); in between scales every wait
 * Resolves `{ ok: true, payload, steps, skipped }` when it is done, or `{ ok: false }` when there was nothing to play.
 */
export function runGematriaStream({ body, load, waitFor = null, onStart = null, reduced = false, speed = 1, timing = TIMING }) {
  return new Promise((resolve) => {
    const timers = [];
    const sleepers = [];
    let skipped = false;
    let finished = false;

    const wait = (ms) => new Promise((go) => {
      if (skipped || speed === 0 || reduced) { go(); return; }
      const id = setTimeout(go, ms * speed);
      timers.push(id);
      sleepers.push(go);
    });
    const stopAll = () => { timers.forEach((id) => clearTimeout(id)); timers.length = 0; };
    const done = (value) => { if (finished) return; finished = true; stopAll(); resolve(value); };

    (async () => {
      let payload = null;
      try { payload = await load(); } catch (err) { payload = null; }
      if (finished) return;
      const steps = streamSteps(payload);
      if (!steps.length) { if (waitFor) { try { await waitFor; } catch (err) { /* the caller reports its own failure */ } } done({ ok: false }); return; }
      if (reduced) { if (waitFor) { try { await waitFor; } catch (err) { /* ditto */ } } done({ ok: true, payload, steps, skipped: false, static: true }); return; }

      if (onStart) onStart();
      const count = h("span", { class: "dx-count", "data-hook": "gematria-count", text: "Reading the board" });
      const head = h("div", { class: "dx-head" }, [h("span", { class: "dx-brand", text: "GEMATRIA" }), h("span", { class: "dx-title", text: "Analysis" }), count]);
      const picksEl = h("dd", { class: "dx-meter__v", "data-hook": "gematria-picks", text: "0" });
      const meters = h("dl", { class: "dx-meters gs-meters", "data-hook": "gematria-meters" }, [
        h("div", { class: "dx-meter" }, [h("dt", { class: "dx-meter__k", text: "Weighed" }), h("dd", { class: "dx-meter__v", "data-hook": "gematria-weighed", text: String(isNum(payload.weighed) ? payload.weighed : payload.games.length) })]),
        h("div", { class: "dx-meter" }, [h("dt", { class: "dx-meter__k", text: "Picks so far" }), picksEl])]);
      const log = h("ol", { class: "dx-log gs-log", "data-hook": "gematria-log" });
      const sr = h("p", { class: "dx-sr", role: "status", "aria-live": "polite", "data-hook": "gematria-status" });
      const skip = h("button", { type: "button", class: "dx-skip", "data-hook": "gematria-skip", hidden: "", text: "Skip" });
      const root = h("div", { class: "dx gs", "data-hook": "gematria-stream", "data-phase": "play", "data-motion": "full" },
        [head, meters, log, sr, h("div", { class: "dx-foot" }, [skip])]);
      clearNode(body);
      body.appendChild(root);

      skip.addEventListener("click", (evt) => {
        if (evt && evt.stopPropagation) evt.stopPropagation();
        if (finished || skipped) return;
        skipped = true;
        skip.setAttribute("hidden", "");
        stopAll();
        sleepers.splice(0).forEach((go) => go());
      });
      const skipId = setTimeout(() => { if (!finished && !skipped) skip.removeAttribute("hidden"); }, timing.skipAfter * (speed === 0 ? 0 : speed));
      timers.push(skipId);

      const per = Math.max(timing.lineMin, Math.min(timing.lineMax, timing.target / steps.length));
      let picks = 0;
      let games = 0;
      await wait(timing.start);
      for (const step of steps) {
        if (finished) return;
        log.appendChild(lineNode(step));
        try { log.scrollTop = log.scrollHeight; } catch (err) { /* a fake DOM */ }
        if (step.kind === "decision") {
          games += 1;
          if (step.tone === "good") picks += 1;
          count.textContent = `game ${games}/${payload.games.length}`;
          picksEl.textContent = String(picks);
          sr.textContent = `Game ${games} of ${payload.games.length}: ${step.text}`;
          await wait(per + timing.gamePause);
        } else {
          await wait(per);
        }
      }
      count.textContent = "done";
      if (waitFor) {
        const last = lineNode({ kind: "frame", text: "Placing what fit on its record...", tone: "frame", game: payload.games.length }, "pending");
        log.appendChild(last);
        try { await waitFor; } catch (err) { /* the caller reports its own failure */ }
        last.setAttribute("data-state", "done");
      }
      done({ ok: true, payload, steps, skipped });
    })();
  });
}
