/**
 * THE EVOLUTION: what Send to training looks like (owner request 2026-10-21, "like a Pokemon evolution").
 *
 * The hound is sent, the real training request runs, and while it runs the person watches the hound evolve:
 *
 *   1 BEFORE   the hound as it is, with its version badge ("v1"); one line says what training changed
 *   2 CHARGE   the screen dims, the hound goes white, light streaks pull in, and the old and new silhouettes alternate,
 *              faster and faster. Both are the real hound at its real version, drawn white with its ink lines, so the new one
 *              carries the new tier's own outline (bandana, vest, shoulder plates, mantle: dog-gear.js) and the morph reads
 *   3 BURST    a white flash, then the NEW hound: what it wears, and its version's frame, rank plate and chevrons (dog-tiers.js)
 *   4 CARD     "{Name} became {Name} v2!" and the changes, each old value struck through and replaced by the new one
 *   5 CTA      See v2 / Back to My Kennel
 *
 * IT NEVER FAKES THE SERVER. The request is made by the caller and handed in as a promise. Nothing is drawn as an upgrade until
 * the server has answered, and the upgrade is drawn from that answer: the new version number is `result.new.version_no`, and every
 * line on the card is a change the server made (`result.changes`, else `result.diff`). If the request fails the sequence ends at
 * once with the error and no charge, no flash and no new hound. The animation is a minimum, never a wait: when the answer is slow
 * the Before beat holds ("Training...") until it arrives.
 *
 * SKIP. A tap on the stage (or the Skip button, or Enter or Space on it) after the first second jumps to the card. Before the
 * answer arrives, a skip waits for it and then goes straight to the card.
 *
 * REDUCED MOTION. Nothing is timed and nothing moves: when the answer arrives the person gets one static card, the old hound and
 * the new hound side by side, and the same lines (old value struck through, then the new one).
 *
 * SOUND is off until the person turns it on (a toggle in the corner); it is a few synthesized tones, no files.
 *
 * Pure SVG, CSS (css/evolve.css) and JS. No image, no library. The drawing of the hounds is dogBadge (dog-rig.js); the look of a
 * version is dog-tiers.js, so a v3 here is the v3 the kennel card, the hound page and the Kennel Room draw.
 */

import { h, clearNode, isNum, s as svg } from "./hounds-core.js";
import { dogBadge, fetchLooks, lookFor, cleanLook, versionTier, newParts } from "./dog-avatar.js";
import { trainedBadge } from "./dog-headstone.js";

/** The beats of the sequence, in milliseconds. The whole thing runs about 7 seconds before the card, and the card builds for 2 more. */
export const TIMING = {
  beforeMin: 1900,        // the Before beat holds at least this long (longer when the answer is slow)
  skipAfter: 1000,        // a tap skips only after this
  flip: [520, 440, 372, 314, 264, 220, 182, 150, 124, 102],      // the silhouettes alternate, each beat shorter than the last
  flashPeak: 150,         // from the flash starting to the new hound showing
  burst: 900,             // the flash and the shock ring
  hold: 1500,             // the new hound alone, before the card
  look: 600,              // how long to wait for the hound's saved look before drawing the default
};
export const CHARGE_MS = TIMING.flip.reduce((a, b) => a + b, 0);

// ---- the words: only what the server changed ------------------------------------------------------------------------

const clean = (v) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "");

/** The phrase for one change the server made, from its own fields and nothing else: "Price range tightened to +100 to +180". */
export function changePhrase(change) {
  const c = change || {};
  const to = clean(c.to), label = clean(c.label);
  if (!to) return "";
  switch (c.id) {
    case "tighten_band": return `Price range tightened to ${to}`;
    case "drop_sport": return `Sports narrowed to ${to}`;
    case "drop_market": return `Markets narrowed to ${to}`;
    case "drop_venue": return `Side now ${to}`;
    case "require_role": return `Takes ${to}`;
    case "more_books": return `Needs ${to} quoting`;
    case "fewer_bets": return `Max ${to} a day`;
    case "widen_band": return `Price range widened to ${to}`;
    case "lower_books": return `Needs ${to} quoting`;
    case "add_sport": return `Sports widened to ${to}`;
    case "add_market": return `Markets widened to ${to}`;
    case "more_bets": return `Max ${to} a day`;
    default: return label ? `${label}: ${to}` : to;
  }
}

/**
 * The lines of the card, from the server's training result and nothing else: [{ id, label, from, to, phrase }]. A change whose old and
 * new text are the same, or that has no new text, is not a line. `result.changes` is the coach's list; when it is empty the
 * spec diff (`result.diff`: what, before, after) is used instead. No line is ever made up: a result with neither gives [].
 */
export function evolveLines(result) {
  const r = result || {};
  const lines = [];
  const seen = new Set();
  const push = (line) => {
    const key = `${line.label}|${line.from}|${line.to}`;
    if (!line.to || line.from === line.to || seen.has(key)) return;
    seen.add(key);
    line.phrase = changePhrase(line);
    lines.push(line);
  };
  for (const c of Array.isArray(r.changes) ? r.changes : []) {
    if (c && typeof c === "object") push({ id: clean(c.id), label: clean(c.label), from: clean(c.old_text), to: clean(c.new_text), why: clean(c.why) });
  }
  if (!lines.length) {
    for (const d of Array.isArray(r.diff) ? r.diff : []) {
      if (d && typeof d === "object") push({ id: "", label: clean(d.what), from: clean(d.before), to: clean(d.after), why: "" });
    }
  }
  return lines;
}

/** The one line under the hound once the server has answered: "Training changed: Price range tightened to ... · Max 2 a day". */
export function summaryLine(lines) {
  const phrases = (lines || []).map((l) => l.phrase).filter(Boolean);
  return phrases.length ? `Training changed: ${phrases.join(" · ")}` : "";
}

/** "Gus became Gus v2!" */
export const becameText = (name, version) => `${name} became ${name} v${version}!`;

// ---- sound: off until asked, a few synthesized tones ---------------------------------------------------------------

/** The sound of the sequence. `supported` is false where there is no Web Audio, and then the toggle is not drawn. */
export function makeSound() {
  let ctx = null;
  let on = false;
  const Ctor = typeof window !== "undefined" ? (window.AudioContext || window.webkitAudioContext) : null;
  const tone = (freq, at, len, gain, type = "sine", to = null) => {
    try {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type;
      o.frequency.setValueAtTime(freq, ctx.currentTime + at);
      if (to) o.frequency.exponentialRampToValueAtTime(to, ctx.currentTime + at + len);
      g.gain.setValueAtTime(0.0001, ctx.currentTime + at);
      g.gain.exponentialRampToValueAtTime(gain, ctx.currentTime + at + Math.min(0.04, len / 3));
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + len);
      o.connect(g); g.connect(ctx.destination);
      o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + len + 0.05);
    } catch (err) { /* a sound never takes the sequence down */ }
  };
  return {
    supported: !!Ctor,
    get on() { return on; },
    set(value) {
      on = !!value && !!Ctor;
      if (on && !ctx) { try { ctx = new Ctor(); } catch (err) { ctx = null; on = false; } }
      if (on && ctx && ctx.state === "suspended" && ctx.resume) { try { ctx.resume(); } catch (err) { /* ignore */ } }
      return on;
    },
    /** One beat of the charge: a blip that climbs with the beat. */
    beat(i, n) { if (on && ctx) tone(260 * Math.pow(2, (i / Math.max(1, n - 1)) * 2.2), 0, 0.09, 0.05, "triangle"); },
    burst() { if (on && ctx) { tone(95, 0, 0.5, 0.16, "sine", 38); tone(1046, 0.02, 0.9, 0.06); tone(1568, 0.02, 1.1, 0.04); } },
    chime() { if (on && ctx) { tone(784, 0, 0.5, 0.05); tone(988, 0.12, 0.5, 0.05); tone(1318, 0.24, 0.8, 0.05); } },
    close() { if (ctx && ctx.close) { try { ctx.close(); } catch (err) { /* ignore */ } } ctx = null; on = false; },
  };
}

// ---- pieces ----------------------------------------------------------------------------------------------------

const RAYS = 18;
/** The light streaks that pull in on the charge: lines from the rim of the screen towards the middle, each one a dash that travels inward. */
function streaks() {
  const lines = [];
  for (let i = 0; i < RAYS; i++) {
    const a = (i / RAYS) * Math.PI * 2 + (i % 2 ? 0.08 : -0.05);
    const r0 = 98 + (i % 3) * 8, r1 = 34 + (i % 4) * 5;
    lines.push(svg("line", {
      x1: (100 + r0 * Math.cos(a)).toFixed(1), y1: (100 + r0 * Math.sin(a)).toFixed(1),
      x2: (100 + r1 * Math.cos(a)).toFixed(1), y2: (100 + r1 * Math.sin(a)).toFixed(1),
      pathLength: 1, style: `--k:${i}`, "stroke-width": i % 3 === 0 ? 1.6 : 0.9,
    }));
  }
  return svg("svg", { class: "ev-rays", viewBox: "0 0 200 200", "aria-hidden": "true", focusable: "false", preserveAspectRatio: "xMidYMid slice" }, lines);
}

const tierWord = (version) => versionTier(version).name;

/** A hound at a version, in a box: the old and the new one are the same hound with a different `version`. */
function houndBox(cls, look, dog, version, size) {
  const box = h("div", { class: `ev-hound ${cls}`, "data-vno": String(version) });
  box.appendChild(dogBadge(look, { size, mood: "idle", id: dog.root_id || dog.id, name: dog.name, vibe: dog.vibe, version }));
  return box;
}

function statRow(line, i, animate) {
  const row = h("li", { class: "ev-stat", "data-hook": "evolve-stat", "data-change": line.id || "", style: `--i:${i}` }, [
    h("span", { class: "ev-stat__label", text: line.label }),
    h("span", { class: "ev-stat__vals" }, [
      h("s", { class: "ev-stat__from", "data-hook": "evolve-from", text: line.from }),
      h("span", { class: "ev-stat__arrow", "aria-hidden": "true", text: "→" }),
      h("b", { class: "ev-stat__to", "data-hook": "evolve-to", text: line.to })])]);
  // a plain whole number counts down or up to its new value (3 -> 2); everything else slides in
  if (animate && /^\d{1,3}$/.test(line.from) && /^\d{1,3}$/.test(line.to)) row.setAttribute("data-tween", `${line.from}:${line.to}`);
  return row;
}

// ---- the sequence --------------------------------------------------------------------------------------------------

/**
 * Play the evolution inside `body` (the sheet's body) while `request` runs.
 *   dog       { id, name, version_no?, root_id?, look?, vibe? }   the hound being trained, as the page knows it
 *   request   a promise of { ok: true, r: <result> } or { ok: false, e: <error> }   the real POST /hounds/{id}/train
 *   reduced   true for prefers-reduced-motion: no timers, one static card
 *   layer     the modal layer (gets data-evolve and data-phase so the page dims)
 *   onBack    runs when "Back to My Kennel" is tapped
 *   renderWhy (result) => node   the "what changed and why" card (reasons, the coach's note, the two records), folded under the new card
 * Resolves with { ok: false, e } the moment the request fails (nothing evolved was drawn), or { ok: true, result } once the card is up.
 */
export function runEvolution({ body, dog, request, reduced = false, layer = null, onBack = null, renderWhy = null, sound = makeSound() }) {
  return new Promise((resolve) => {
    const timers = [];
    let stopped = false;
    let phase = "before";
    let outcome = null;
    let skipAsked = false;
    let started = Date.now();
    let look = null;
    let oldV = isNum(dog.version_no) ? dog.version_no : null;
    let newV = null;
    let lines = [];

    const later = (ms, fn) => { const id = setTimeout(() => { if (!stopped) fn(); }, ms); timers.push(id); return id; };
    const stopAll = () => { stopped = true; timers.forEach((id) => clearTimeout(id)); timers.length = 0; };
    const setPhase = (name) => {
      phase = name;
      root.setAttribute("data-phase", name);
      if (layer) layer.setAttribute("data-phase", name);
    };

    // ---- the page of the sequence
    const stage = h("div", { class: "ev-stage", "data-hook": "evolve-stage", "data-flip": "old" });
    const ripple = h("div", { class: "ev-ripple", "aria-hidden": "true", "data-beat": "a" });
    const shock = h("div", { class: "ev-shock", "aria-hidden": "true" });
    const flash = h("div", { class: "ev-flash", "aria-hidden": "true", "data-hook": "evolve-flash" });
    const rays = streaks();
    const badge = h("span", { class: "ev-badge", "data-hook": "evolve-version", text: oldV === null ? "" : `v${oldV}` });
    const line = h("p", { class: "ev-line", role: "status", "aria-live": "polite", "data-hook": "training-status", text: "Training..." });
    const parts = h("ul", { class: "ev-parts", "data-hook": "evolve-parts", "aria-label": "What the new version wears" });
    const caption = h("div", { class: "ev-caption" }, [badge, line, parts]);
    const skip = h("button", { type: "button", class: "ev-skip", "data-hook": "evolve-skip", hidden: "", text: "Skip" });
    // the sound toggle is an icon button in the sheet's corner (never over the title): a speaker with a cross when off, with waves when on
    const soundIcon = () => svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false", fill: "none", stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round" }, [
      svg("path", { d: "M4 9.5v5h3.5L12 18.5v-13L7.5 9.5H4z" }),
      svg("path", { class: "ev-sound__mute", d: "M15.5 9.5l5 5M20.5 9.5l-5 5" }),
      svg("path", { class: "ev-sound__wave", d: "M15.5 9a4 4 0 0 1 0 6M18.2 6.5a8 8 0 0 1 0 11" })]);
    const soundBtn = sound.supported
      ? h("button", { type: "button", class: "ev-sound", "data-hook": "evolve-sound", "aria-pressed": "false", "aria-label": "Sound off", title: "Sound off" }, [soundIcon()]) : null;
    const top = h("div", { class: "ev-top" }, [soundBtn]);
    const root = h("div", { class: "ev", "data-hook": "evolve", "data-phase": "before", "data-motion": reduced ? "reduced" : "full" },
      [top, stage, caption, skip, flash]);
    stage.appendChild(rays);
    stage.appendChild(ripple);
    stage.appendChild(shock);
    clearNode(body);
    body.appendChild(root);
    if (layer) layer.setAttribute("data-phase", "before");

    if (soundBtn) {
      soundBtn.addEventListener("click", (evt) => {
        if (evt && evt.stopPropagation) evt.stopPropagation();
        const next = sound.set(!sound.on);
        soundBtn.setAttribute("aria-pressed", next ? "true" : "false");
        soundBtn.setAttribute("aria-label", next ? "Sound on" : "Sound off");
        soundBtn.setAttribute("title", next ? "Sound on" : "Sound off");
      });
    }

    // ---- the hounds
    let oldBox = null, newBox = null;
    const SIZE = 260;
    const drawOld = () => {
      if (oldBox || oldV === null || !look) return;
      oldBox = houndBox("ev-hound--old", look, dog, oldV, SIZE);
      stage.insertBefore ? stage.insertBefore(oldBox, rays) : stage.appendChild(oldBox);
      badge.textContent = `v${oldV}`;
    };
    const drawNew = () => {
      if (newBox) return;
      newBox = houndBox("ev-hound--new", look, dog, newV, SIZE);
      stage.appendChild(newBox);
    };

    const lookDone = (async () => {
      if (dog.look) return cleanLook(dog.look);
      let found = null;
      try {
        found = await Promise.race([fetchLooks([dog.root_id || dog.id]).then((m) => m[dog.root_id || dog.id] || m[dog.id] || null), new Promise((r) => setTimeout(() => r(null), TIMING.look))]);
      } catch (err) { found = null; }
      return found ? cleanLook(found) : lookFor(dog.root_id || dog.id);
    })();
    lookDone.then((l) => { look = l; drawOld(); });

    // ---- skip
    const canSkip = () => !reduced && phase !== "card" && phase !== "static" && Date.now() - started >= TIMING.skipAfter;
    const doSkip = () => {
      if (!canSkip()) return;
      if (!outcome || !outcome.ok) { skipAsked = true; skip.setAttribute("hidden", ""); line.textContent = "Training..."; return; }
      stopAll();
      stopped = false;
      sound.close();
      showCard(true);
    };
    skip.addEventListener("click", (evt) => { if (evt && evt.stopPropagation) evt.stopPropagation(); doSkip(); });
    stage.addEventListener("click", doSkip);
    if (!reduced) later(TIMING.skipAfter, () => { if (phase !== "card") skip.removeAttribute("hidden"); });

    // ---- the answer
    const onAnswer = async (o) => {
      outcome = o;
      if (!o.ok) {                                  // refused or failed: no charge, no flash, no new hound
        stopAll();
        sound.close();
        resolve({ ok: false, e: o.e });
        return;
      }
      const r = o.r || {};
      newV = r.new && isNum(r.new.version_no) ? r.new.version_no : null;
      if (oldV === null && r.old && isNum(r.old.version_no)) oldV = r.old.version_no;
      if (newV === null) newV = oldV === null ? null : oldV + 1;
      lines = evolveLines(r);
      await lookDone;
      if (stopped) return;
      if (oldV === null) oldV = newV === null ? 1 : Math.max(1, newV - 1);
      if (newV === null) newV = oldV + 1;
      drawOld();
      line.textContent = summaryLine(lines) || "Training made its next version.";
      line.setAttribute("data-ready", "1");
      if (reduced) { showCard(false); return; }
      if (skipAsked) { showCard(true); return; }
      later(Math.max(0, TIMING.beforeMin - (Date.now() - started)), charge);
    };
    request.then(onAnswer, (e) => onAnswer({ ok: false, e }));

    // ---- charge: dim, white-out, streaks, the silhouettes alternating faster and faster
    function charge() {
      setPhase("charge");
      drawNew();
      oldBox.setAttribute("data-sil", "1");
      newBox.setAttribute("data-sil", "1");
      badge.setAttribute("data-charging", "1");
      line.textContent = "";
      let i = 0, showNew = false;
      const n = TIMING.flip.length;
      const beat = () => {
        if (i >= n) { burst(); return; }
        showNew = !showNew;
        stage.setAttribute("data-flip", showNew ? "new" : "old");
        ripple.setAttribute("data-beat", i % 2 ? "a" : "b");
        stage.setAttribute("style", `--ev-charge:${((i + 1) / n).toFixed(2)}`);
        sound.beat(i, n);
        later(TIMING.flip[i++], beat);
      };
      beat();
    }

    // ---- burst: the flash, then the new hound
    function burst() {
      setPhase("burst");
      sound.burst();
      later(TIMING.flashPeak, () => {
        stage.setAttribute("data-flip", "reveal");
        oldBox.removeAttribute("data-sil");
        newBox.removeAttribute("data-sil");
        stage.setAttribute("style", "--ev-charge:0");
        badge.removeAttribute("data-charging");   // from here the version is read off the art's own tab and the card's one chip
      });
      later(TIMING.burst, reveal);
    }

    // ---- reveal: the new hound alone, with what it earned
    function reveal() {
      setPhase("reveal");
      sound.chime();
      clearNode(parts);
      // what the new version wears, hound first; the rank plate is the art's own tab, so it is only listed when it is the one thing that is new
      const gained = newParts(oldV, newV);
      const shown = gained.filter((p) => !/^Rank plate/.test(p));
      for (const [i, p] of (shown.length ? shown : gained).entries()) parts.appendChild(h("li", { class: "ev-part", "data-hook": "evolve-part", style: `--i:${i}`, text: p }));
      line.textContent = `${dog.name} · ${tierWord(newV)} tier`;
      later(TIMING.hold, () => showCard(false));
    }

    // ---- the card
    function showCard(skipped) {
      if (phase === "card" || phase === "static") return;
      const r = outcome.r || {};
      const fresh = r.new || {};
      const animate = !reduced && !skipped;
      if (skipped) root.setAttribute("data-skipped", "1");
      setPhase(reduced ? "static" : "card");
      stage.setAttribute("data-flip", "reveal");
      skip.setAttribute("hidden", "");
      if (!reduced) { drawNew(); oldBox.removeAttribute("data-sil"); newBox.removeAttribute("data-sil"); }
      const tier = versionTier(newV);

      // reduced motion: the old hound, an arrow and the new hound, side by side, in place of the stage
      if (reduced) {
        clearNode(stage);
        const pair = h("div", { class: "ev-pair", "data-hook": "evolve-pair" }, [
          h("figure", { class: "ev-pair__one" }, [houndBox("ev-hound--static", look, dog, oldV, 120), h("figcaption", { text: `v${oldV}` })]),
          h("span", { class: "ev-pair__arrow", "aria-hidden": "true", text: "→" }),
          h("figure", { class: "ev-pair__one" }, [houndBox("ev-hound--static", look, dog, newV, 120), h("figcaption", { text: `v${newV}` })])]);
        stage.appendChild(pair);
        clearNode(parts);
        badge.textContent = `v${newV}`;
      }
      line.textContent = "";
      line.removeAttribute("role");

      const stats = h("ul", { class: "ev-stats", "data-hook": "evolve-stats" }, lines.map((l, i) => statRow(l, i, animate)));
      const card = h("div", { class: "ev-card", "data-hook": "evolve-card", "data-tier": String(tier.tier), style: `--n:${lines.length}` }, [
        h("p", { class: "ev-card__kicker" }, [
          h("span", { class: `dk-chip ${r.light_adjustment ? "dk-chip--warn" : "dk-chip--good"}`, "data-hook": "training-label", text: r.label || "Trained" }),
          " ", h("span", { class: "dk-chip ev-chip--tier", "data-hook": "evolve-tier", "data-tier": String(tier.tier), text: `v${newV} · ${tier.name}` }),
          " ", trainedBadge(fresh.trained_times)]),
        h("h3", { class: "ev-card__title", "data-hook": "evolve-title", text: becameText(dog.name, newV) }),
        r.light_note ? h("p", { class: "ev-card__note", "data-hook": "training-light-note", text: r.light_note }) : null,
        lines.length ? stats : h("p", { class: "ev-card__note", "data-hook": "evolve-no-lines", text: "The coach changed nothing the rule shows. The new version starts fresh." }),
        h("p", { class: "ev-card__fresh", "data-hook": "evolve-fresh", text: `Its new record starts now. v${oldV} keeps its record.` }),
        renderWhy ? why(renderWhy(r)) : null,
        h("div", { class: "ev-actions", "data-hook": "rites-actions" }, [
          h("a", { class: "btn btn--primary", href: fresh.page_href || "#", "data-hook": "training-open-new", text: `See v${newV}` }),
          h("button", { type: "button", class: "btn btn--ghost", "data-hook": "training-done", on: { click: () => { if (onBack) onBack(); } }, text: "Back to My Kennel" })]),
      ]);
      root.appendChild(card);
      if (animate) runCounts(stats);
      later(2400, () => sound.close());
      resolve({ ok: true, result: r, skipped: !!skipped });
    }

    function runCounts(stats) {
      for (const row of stats.querySelectorAll ? stats.querySelectorAll("[data-tween]") : []) {
        const [a, b] = row.getAttribute("data-tween").split(":").map(Number);
        const to = row.querySelector("[data-hook='evolve-to']");
        if (!to || !Number.isFinite(a) || !Number.isFinite(b) || a === b) continue;
        const i = Number(((row.getAttribute("style") || "").match(/--i:(\d+)/) || [0, 0])[1]);
        const dir = b > a ? 1 : -1, steps = Math.abs(b - a);
        to.textContent = String(a);
        for (let k = 1; k <= steps; k++) later(900 + i * 420 + k * 110, () => { to.textContent = String(a + dir * k); });
      }
    }
  });
}

/** The fold under the card: the reasons, the coach's note and the two records (the card dog-rites.js has always drawn). */
function why(node) {
  return h("details", { class: "ev-why", "data-hook": "evolve-why" }, [h("summary", { text: "Why these changes" }), node]);
}
