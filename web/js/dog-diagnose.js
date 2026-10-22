/**
 * THE DIAGNOSIS: the analysis phase of Send to training (owner request 2026-10-21, "MATRIX-LEVEL complicated, AI assessing and
 * analyzing. It should feel expensive and well thought out").
 *
 * Before the hound evolves, the coach reads its whole settled record, and the person watches it do it:
 *
 *   1 SCAN     "Scanning 47 settled tickets": the server's diagnosis table (POST /hounds/{id}/train/diagnose), one line per cut that
 *              was really checked (price band, side, sport, day, slate time, rest, line movement, books, rules, streaks...), each
 *              resolving with its own record and units. A tile per cut lights in a small heatmap; the weak spots go red.
 *   2 ASK      "Asking the coach (Claude Haiku)": the real request (POST /hounds/{id}/train/assess). The line waits for the answer.
 *   3 READ     the ranked reasons, each citing the lines above, labelled "AI read" or "Coach's read (rules engine)".
 *   4 HAND OFF the caller runs the evolution (dog-evolve.js) and the real training.
 *
 * NOTHING HERE IS INVENTED. Every log line is a row of the server's diagnosis (its own text, its own tone), plus four framing lines
 * the page needs to say what it is doing (scanning, asking, the answer, the cause). The number of row lines equals the number of
 * rows of the diagnosis: a test counts them. Pacing is staged so a person can read, but it stages real results; it adds none. The
 * words never say the new version will win or improve: the lines are facts about the past, and the read says so.
 *
 * SKIP. After three seconds a Skip button appears. It fast-forwards the lines, still waits for the coach's answer (the request is
 * already paid for), and hands off. REDUCED MOTION: no timers and no animation; one static summary (the weakest parts, the read, the
 * full list folded away) and a Continue button.
 *
 * A diagnosis that cannot be fetched (the server does not have the step, or the network failed) is not an error here: the phase is
 * skipped and the training goes on as before, so the person is never stuck behind the show. A refusal the server means (an open
 * ticket, too few new bets) ends the phase and is shown by the caller.
 *
 * Pure DOM built with h() (text is always textContent), CSS in css/diagnose.css, no image, no library, no script tag.
 */

import { h, clearNode, isNum } from "./hounds-core.js";
import { dogBadge, fetchLooks, lookFor, cleanLook } from "./dog-avatar.js";

/** Pacing in milliseconds. The lines share `rowTarget` between them (clamped per line), then the ask and the read add their own. */
export const TIMING = {
  skipAfter: 3000,        // a Skip button appears after this
  rowTarget: 17000,       // all the check lines together aim for about this
  rowMin: 220,            // ...but never faster than this per line
  rowMax: 700,            // ...nor slower than this
  pending: 150,           // a line shows as pending (a spinner glyph) for this long before it resolves
  askMin: 1500,           // the ask line holds at least this long, even when the answer is already there
  reasonGap: 1200,        // between one reason and the next
  hold: 3800,             // the finished read stays this long before the hand off
  look: 600,              // how long to wait for the hound's saved look
};

/** Codes the server uses for a refusal it means (the caller shows the server's sentence); anything else skips the phase. */
export const REFUSAL_CODES = ["open_tickets", "training_too_soon", "not_found", "not_a_member_dog", "already_buried", "not_active",
  "retired", "buried", "confirm_required", "nothing_to_change"];

/** The short caption over each group of tiles in the heatmap (a label for the eye; the group itself is the server's). */
export const GROUP_TAG = { band: "PRICE", role: "ROLE", venue: "SIDE", sport: "SPORT", market: "MKT", dow: "DAY", slate: "TIME", rest: "REST", move: "MOVE",
  books: "BOOKS", activity: "DAYS", cap: "LIMIT", rule: "RULES", streak: "RUNS", combo: "PAIRS" };

const clean = (v) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "");
const GLYPH = { weak: "▼", soft: "▼", ok: "", thin: "·", none: "" };

// ---- pure helpers (the words and the steps) -------------------------------------------------------------------

export const recordText = (o) => `${o.wins}-${o.losses}${o.pushes ? `-${o.pushes}` : ""}`;
export const unitsText = (u) => (isNum(u) ? `${u >= 0 ? "+" : "-"}${Math.abs(u).toFixed(1)}u` : "");

/** The text of one row's line, resolved, from the server's own row. The overall row reads as the scan. */
export function rowText(row, diagnosis) {
  if (row.id === "overall") {
    const o = diagnosis.overall || {};
    return `Scanning ${diagnosis.settled} settled ${diagnosis.settled === 1 ? "ticket" : "tickets"}: ${recordText(o)}, ${unitsText(o.units)}`;
  }
  let text = clean(row.line);
  if (row.kind !== "unavailable" && row.kind !== "context" && row.level === "too_few" && row.level_text) text += ` - ${row.level_text}`;
  return text;
}

/** The text of a row's line while it is pending (what is being checked). */
export function pendingText(row, diagnosis) {
  if (row.id === "overall") return `Scanning ${diagnosis.settled} settled ${diagnosis.settled === 1 ? "ticket" : "tickets"}...`;
  return `${clean(row.label)}...`;
}

/** One step per row of the diagnosis, in order: the screen's checks ARE the table's rows. */
export function rowSteps(diagnosis) {
  const rows = Array.isArray(diagnosis && diagnosis.rows) ? diagnosis.rows : [];
  return rows.map((row) => ({ kind: "row", id: row.id, group: row.group, tone: row.tone || "none", direction: row.direction || "",
    pending: pendingText(row, diagnosis), text: rowText(row, diagnosis), glyph: GLYPH[row.tone] || "" }));
}

/** The reasons to show: the coach's own when it answered, else the top of the diagnosis's ranking in the table's own words. */
export function reasonsOf(coach, diagnosis) {
  if (coach && Array.isArray(coach.reasons) && coach.reasons.length) return coach.reasons;
  const byId = {};
  for (const r of diagnosis.rows || []) byId[r.id] = r;
  const out = [];
  for (const id of diagnosis.ranked || []) {
    const r = byId[id];
    if (!r) continue;
    if (r.level === "too_few" && out.length) continue;
    out.push({ rank: out.length + 1, factors: [id], text: `${clean(r.line)}${r.level === "too_few" ? ` (${r.level_text})` : ""}.`,
      confidence: r.level === "too_few" ? "low" : r.level, thin: r.level === "too_few",
      cited: [{ id, line: r.line, level: r.level, level_text: r.level_text, tone: r.tone }] });
    if (out.length >= 3) break;
  }
  return out;
}

export const readLabel = (coach) => (coach && coach.label) || "Coach's read (rules engine)";

// ---- the screen ------------------------------------------------------------------------------------------------

function meter(label, value, hook) {
  return h("div", { class: "dx-meter" }, [h("dt", { class: "dx-meter__k", text: label }), h("dd", { class: "dx-meter__v", "data-hook": hook, text: value })]);
}

function readBlock(coach, diagnosis, reasons) {
  const ai = !!coach && coach.source === "ai";
  const head = ai ? `${readLabel(coach)} - ${coach.model_label || "Claude Haiku"}` : readLabel(coach);
  const block = h("div", { class: "dx-read", "data-hook": "diagnose-read", "data-source": ai ? "ai" : "rules" }, [
    h("p", { class: "dx-read__label", "data-hook": "diagnose-label", text: head })]);
  if (coach && coach.summary) block.appendChild(h("p", { class: "dx-read__summary", "data-hook": "diagnose-summary", text: coach.summary }));
  if (!reasons.length) block.appendChild(h("p", { class: "dx-read__none", "data-hook": "diagnose-no-reason", text: "No single cut stood out enough to blame." }));
  block.appendChild(h("ol", { class: "dx-reasons", "data-hook": "diagnose-reasons" }, reasons.map((r, i) => reasonItem(r, i))));
  const cuts = diagnosis && diagnosis.meta && isNum(diagnosis.meta.cuts_examined) ? diagnosis.meta.cuts_examined : null;
  block.appendChild(h("p", { class: "dx-read__note", "data-hook": "diagnose-note", text: `Facts about the past, not a forecast.${cuts ? ` ${cuts} cuts were examined, so one of them can look bad by chance.` : ""}` }));
  return block;
}

function reasonItem(r, i) {
  return h("li", { class: "dx-reason", "data-hook": "diagnose-reason", "data-rank": String(i + 1), "data-thin": r.thin ? "1" : "0", style: `--i:${i}` }, [
    h("p", { class: "dx-reason__text" }, [h("b", { class: "dx-reason__n", text: `${i + 1}` }), " ", h("span", { text: clean(r.text) })]),
    h("ul", { class: "dx-cites" }, (r.cited || []).map((c) => h("li", { class: "dx-cite", "data-tone": c.tone || "none", "data-hook": "diagnose-cite", text: clean(c.line) }))),
    h("p", { class: "dx-reason__conf", text: r.thin ? "Too few bets to say" : `Confidence: ${clean(r.confidence)}` })]);
}

/**
 * Play the diagnosis inside `body` (the sheet's body).
 *   dog      { id, name, version_no?, root_id?, look? }
 *   steps    { diagnose: () => Promise<{diagnosis}>, assess: () => Promise<{coach}> }  the two real requests (the caller's)
 *   reduced  true for prefers-reduced-motion: no timers, one static summary and a Continue button
 *   layer    the modal layer (gets data-phase)
 *   speed    1 normally; 0 runs without waiting (tests); anything between scales every wait
 * Resolves with { ok: true, diagnosis, coach, skipped } when the person (or the clock) hands off, { ok: false, refused: true, e }
 * for a refusal the server means, or { ok: false, skipped: true } when the diagnosis could not be had (carry on without it).
 */
export function runDiagnosis({ body, dog, steps, reduced = false, layer = null, speed = 1, timing = TIMING }) {
  return new Promise((resolve) => {
    const timers = [];
    const sleepers = [];
    let skipped = false;
    let finished = false;
    let phase = "load";

    const setPhase = (name) => { phase = name; root.setAttribute("data-phase", name); if (layer) layer.setAttribute("data-diagnose", name); };
    const wait = (ms) => new Promise((go) => {
      if (skipped || speed === 0 || reduced) { go(); return; }
      const id = setTimeout(go, ms * speed);
      timers.push(id);
      sleepers.push(go);
    });
    const stopAll = () => { timers.forEach((id) => clearTimeout(id)); timers.length = 0; };
    const done = (value) => { if (finished) return; finished = true; stopAll(); resolve(value); };

    // ---- the page
    const count = h("span", { class: "dx-count", "data-hook": "diagnose-count", text: "Reading the ledger" });
    const head = h("div", { class: "dx-head" }, [h("span", { class: "dx-brand", text: "COACH" }), h("span", { class: "dx-title", text: "Diagnosis" }), count]);
    const portrait = h("div", { class: "dx-portrait", "data-hook": "diagnose-portrait", "aria-hidden": "true" }, [h("i", { class: "dx-beam" })]);
    const meters = h("dl", { class: "dx-meters", "data-hook": "diagnose-meters" });
    const heat = h("div", { class: "dx-heat", "data-hook": "diagnose-heat", role: "img", "aria-label": "Every cut that was checked, one tile each" });
    const log = h("ol", { class: "dx-log", "data-hook": "diagnose-log" });
    const readSlot = h("div", { class: "dx-readslot" });
    const sr = h("p", { class: "dx-sr", role: "status", "aria-live": "polite", "data-hook": "diagnose-status" });
    const skip = h("button", { type: "button", class: "dx-skip", "data-hook": "diagnose-skip", hidden: "", text: "Skip" });
    const foot = h("div", { class: "dx-foot" }, [skip]);
    const root = h("div", { class: "dx", "data-hook": "diagnose", "data-phase": "load", "data-motion": reduced ? "reduced" : "full" },
      [head, h("div", { class: "dx-top" }, [portrait, meters]), heat, log, readSlot, sr, foot]);
    clearNode(body);
    body.appendChild(root);
    if (layer) layer.setAttribute("data-diagnose", "load");

    // the hound's portrait: its saved look, else the default look for its lineage (same as the evolution)
    const lookReady = (async () => {
      if (dog.look) return cleanLook(dog.look);
      let found = null;
      try {
        found = await Promise.race([fetchLooks([dog.root_id || dog.id]).then((m) => m[dog.root_id || dog.id] || m[dog.id] || null),
          new Promise((r) => setTimeout(() => r(null), timing.look))]);
      } catch (err) { found = null; }
      return found ? cleanLook(found) : lookFor(dog.root_id || dog.id);
    })();
    lookReady.then((look) => {
      try {
        portrait.insertBefore ? portrait.insertBefore(dogBadge(look, { size: 84, mood: "thinking", id: dog.root_id || dog.id, name: dog.name,
          vibe: dog.vibe, version: isNum(dog.version_no) ? dog.version_no : 1 }), portrait.firstChild) : null;
      } catch (err) { /* a portrait never takes the diagnosis down */ }
    });

    const onSkip = (evt) => {
      if (evt && evt.stopPropagation) evt.stopPropagation();
      if (finished || skipped) return;
      skipped = true;
      skip.setAttribute("hidden", "");
      stopAll();
      sleepers.splice(0).forEach((go) => go());
    };
    skip.addEventListener("click", onSkip);
    if (!reduced) {
      const id = setTimeout(() => { if (!finished && !skipped) skip.removeAttribute("hidden"); }, timing.skipAfter * (speed === 0 ? 0 : speed));
      timers.push(id);
    }

    // ---- lines
    const addLine = (kind, text, extra = {}) => {
      const line = h("li", { class: "dx-line", "data-hook": "diagnose-line", "data-kind": kind, "data-state": extra.state || "done",
        "data-tone": extra.tone || "none", "data-id": extra.id || "" }, [
        h("span", { class: "dx-line__mark", "aria-hidden": "true", text: extra.mark || "" }),
        h("span", { class: "dx-line__text", text })]);
      log.appendChild(line);
      try { log.scrollTop = log.scrollHeight; } catch (err) { /* a fake DOM */ }
      return line;
    };
    const resolveLine = (line, text, tone, mark) => {
      line.setAttribute("data-state", "done");
      line.setAttribute("data-tone", tone || "none");
      const kids = line.childNodes || line.kids || [];
      if (kids[0]) kids[0].textContent = mark || "";
      if (kids[1]) kids[1].textContent = text;
      try { log.scrollTop = log.scrollHeight; } catch (err) { /* a fake DOM */ }
    };
    const tiles = {};
    const heatGroups = {};
    const addTile = (step) => {
      if (step.id === "overall") return;
      const tile = h("i", { class: "dx-tile", "data-hook": "diagnose-tile", "data-id": step.id, "data-group": step.group, "data-tone": step.tone, "data-state": reduced ? "on" : "off", title: step.text });
      tiles[step.id] = tile;
      if (!heatGroups[step.group]) {
        const cells = h("span", { class: "dx-heatgroup__cells" });
        heatGroups[step.group] = cells;
        heat.appendChild(h("span", { class: "dx-heatgroup", "data-group": step.group }, [h("span", { class: "dx-heatgroup__k", "aria-hidden": "true", text: GROUP_TAG[step.group] || String(step.group || "").toUpperCase().slice(0, 5) }), cells]));
      }
      heatGroups[step.group].appendChild(tile);
    };

    // ---- the run
    (async () => {
      let first;
      try { first = await steps.diagnose(); } catch (err) { first = { error: err }; }
      if (finished) return;
      const diagnosis = first && first.diagnosis;
      if (!diagnosis || !Array.isArray(diagnosis.rows)) {
        const code = first && first.error && first.error.detail && typeof first.error.detail === "object" ? first.error.detail.error : "";
        if (code && REFUSAL_CODES.includes(code)) { done({ ok: false, refused: true, e: first.error }); return; }
        done({ ok: false, skipped: true });
        return;
      }
      const list = rowSteps(diagnosis);
      const o = diagnosis.overall || {};
      meters.appendChild(meter("Settled", String(diagnosis.settled), "diagnose-settled"));
      meters.appendChild(meter("Record", isNum(o.wins) ? recordText(o) : "0-0", "diagnose-record"));
      meters.appendChild(meter("Units", isNum(o.units) ? unitsText(o.units) : "0.0u", "diagnose-units"));
      list.forEach(addTile);
      count.textContent = `0/${list.length} checks`;
      setPhase(reduced ? "static" : "scan");

      // with nothing settled there is nothing to read: say so and hand off
      if (!list.length) {
        addLine("frame", "No settled tickets to read yet.");
        const coach = null;
        readSlot.appendChild(readBlock(coach, diagnosis, []));
        setPhase(reduced ? "static" : "done");
        if (reduced) { finishStatic(diagnosis, coach); return; }
        await wait(timing.hold / 2);
        done({ ok: true, diagnosis, coach, skipped });
        return;
      }

      // the check lines: each is pending for a moment, then resolves to the server's own text
      const per = Math.max(timing.rowMin, Math.min(timing.rowMax, timing.rowTarget / Math.max(1, list.length)));
      let resolved = 0;
      for (const step of list) {
        if (reduced) {
          addLine("row", step.text, { id: step.id, tone: step.tone, mark: step.glyph });
        } else {
          const line = addLine("row", step.pending, { id: step.id, tone: "none", state: "pending", mark: "…" });
          await wait(timing.pending);
          resolveLine(line, step.text, step.tone, step.glyph);
          if (tiles[step.id]) tiles[step.id].setAttribute("data-state", "on");
          await wait(Math.max(0, per - timing.pending));
        }
        if (finished) return;
        resolved += 1;
        count.textContent = `${resolved}/${list.length} checks`;
        if (resolved % 8 === 0 || resolved === list.length) sr.textContent = `${resolved} of ${list.length} checks done`;
      }
      if (reduced) Object.values(tiles).forEach((t) => t.setAttribute("data-state", "on"));

      // the ask: the real request; the line holds until the coach has answered
      setPhase(reduced ? "static" : "ask");
      const asked = Date.now();
      const askLine = reduced ? null : addLine("frame", "Asking the coach (Claude Haiku)...", { state: "pending", mark: "…" });
      let coach = null;
      let askError = null;
      try { const second = await steps.assess(); coach = second && second.coach ? second.coach : null; } catch (err) { askError = err; }
      if (finished) return;
      if (!reduced) await wait(Math.max(0, timing.askMin - (Date.now() - asked)));
      const resting = !coach || coach.source !== "ai";
      const answered = !coach ? "The coach could not be reached. Reading the table with the rules engine."
        : coach.why === "too_few" ? "Too few settled bets for an AI read. Reading the table with the rules engine."
          : coach.why === "dropped" ? "None of the AI's reasons held up against the table. Reading it with the rules engine."
            : resting ? "The AI coach is resting. Reading the table with the rules engine."
              : `Coach answered: ${coach.reasons.length} ${coach.reasons.length === 1 ? "reason" : "reasons"} ranked.`;
      if (askLine) resolveLine(askLine, answered, "none", resting ? "·" : "✓");
      else addLine("frame", answered, { mark: resting ? "·" : "✓" });

      const reasons = reasonsOf(coach, diagnosis);
      if (reduced) { readSlot.appendChild(readBlock(coach, diagnosis, reasons)); finishStatic(diagnosis, coach); return; }

      // the read: the cause, then the rest, each lighting the lines it cites
      setPhase("read");
      readSlot.appendChild(h("p", { class: "dx-read__label", "data-hook": "diagnose-label", "data-source": coach && coach.source === "ai" ? "ai" : "rules",
        text: coach && coach.source === "ai" ? `${readLabel(coach)} - ${coach.model_label || "Claude Haiku"}` : readLabel(coach) }));
      if (!reasons.length) {
        addLine("frame", "No single cut stood out enough to blame.", { mark: "·" });
      }
      for (let i = 0; i < reasons.length; i++) {
        const r = reasons[i];
        addLine("frame", `${i === 0 ? "Most likely cause" : "Next"}: ${clean(r.text)}`, { tone: r.thin ? "thin" : "weak", mark: i === 0 ? "▶" : "·" });
        for (const id of r.factors || []) if (tiles[id]) tiles[id].setAttribute("data-cited", "1");
        await wait(timing.reasonGap);
        if (finished) return;
      }
      clearNode(readSlot);
      readSlot.appendChild(readBlock(coach, diagnosis, reasons));
      sr.textContent = `${readLabel(coach)}. ${reasons.length ? clean(reasons[0].text) : "No single cut stood out."}`;
      skip.textContent = "Continue";
      skip.removeAttribute("hidden");
      setPhase("done");
      await wait(timing.hold);
      done({ ok: true, diagnosis, coach, skipped });
    })();

    // ---- reduced motion: one static summary with the weakest parts first and the full list folded away
    function finishStatic(diagnosis, coach) {
      const byId = {};
      for (const r of diagnosis.rows) byId[r.id] = r;
      const weak = (diagnosis.ranked || []).slice(0, 5).map((id) => byId[id]).filter(Boolean);
      const all = Array.from(log.childNodes || log.kids || []);
      const folded = h("details", { class: "dx-all", "data-hook": "diagnose-all" }, [
        h("summary", { text: `All ${diagnosis.rows.length} checks` })]);
      all.forEach((n) => { log.removeChild(n); });
      const list = h("ol", { class: "dx-log dx-log--static" });
      all.forEach((n) => list.appendChild(n));
      folded.appendChild(list);
      clearNode(log);
      log.setAttribute("hidden", "");
      const summary = h("div", { class: "dx-static", "data-hook": "diagnose-static" }, [
        h("p", { class: "dx-static__h", text: weak.length ? "Where it lost the most" : "No cut lost units" }),
        h("ul", { class: "dx-weak", "data-hook": "diagnose-weak" }, weak.map((r) => h("li", { class: "dx-weak__li", "data-tone": r.tone, text: rowText(r, diagnosis) }))),
        folded]);
      root.insertBefore ? root.insertBefore(summary, readSlot) : root.appendChild(summary);
      count.textContent = `${diagnosis.rows.length}/${diagnosis.rows.length} checks`;
      sr.textContent = `${readLabel(coach)}. ${weak.length ? rowText(weak[0], diagnosis) : "No cut lost units."}`;
      const go = h("button", { type: "button", class: "dx-skip dx-continue", "data-hook": "diagnose-continue", text: "Continue" });
      go.addEventListener("click", () => done({ ok: true, diagnosis, coach, skipped: false }));
      clearNode(foot);
      foot.appendChild(go);
      setPhase("static");
    }
  });
}
