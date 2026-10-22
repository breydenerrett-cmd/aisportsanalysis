/**
 * The owner's hound menu and its two rites: Send to training and Take them out back (owner ruling 2026-10-20, "like
 * Pokemon games"). Unleash sits beside them.
 *
 *   Unleash            POST /hounds/{id}/unleash    starts the hound betting today, on paper (dog-fire.js; a visitor's read-only preview is POST /fire)
 *   Send to training   POST /hounds/{id}/train      the dog studies its own settled bets and comes back as a new version, but only
 *                      after Apply: the diagnosis, then the proposal (POST .../train/propose) and its review (Apply / Veto / Tweak,
 *                      dog-review.js). Retune from the Ask chat is the same flow (startRetune) without the diagnosis.
 *   Take them out back POST /hounds/{id}/out-back   the dog is buried, its record frozen and public (destructive)
 *
 * TAKE THEM OUT BACK ASKS TWICE. Tap, then a sheet ("This is permanent. Your hound is buried and its record is frozen."),
 * then a second sheet, and only that second button sends the request, with {"confirm": true} (the server refuses
 * without it). Cancel is the default focus of both sheets. SEND TO TRAINING asks once (nothing is lost: the old
 * version keeps its record), shows the proposal for review, then, after Apply, plays the evolution (dog-evolve.js: charge, flash, the new version, the upgrade card) while the
 * server works. The card never says the new version is better: it says its new record starts now. EVERY TRAINING IS REVIEWED FIRST
 * (owner ruling 2026-10-22): nothing is written until the owner taps Apply; Veto changes nothing and does not count.
 *
 * MOTION. The evolution and the burial reveal move only when the person has not asked for reduced motion
 * (`reducedMotion()`, and every keyframe is inside prefers-reduced-motion: no-preference in css/evolve.css and css/dog-kit.css).
 * With reduced motion a static before-and-after card appears when the server answers and nothing waits on a timer.
 *
 * This file draws what the server answered and works out nothing; every refusal is the server's own sentence
 * (an open ticket, too few new bets), shown in the sheet with a Close button.
 */

import { h, clearNode, isNum } from "./hounds-core.js";
import { post, errorText, errorCode, nextId } from "./dog-common.js";
import { headstoneCard, recordText, trainedBadge, FROZEN_NOTE } from "./dog-headstone.js";
import { runEvolution } from "./dog-evolve.js";
import { runDiagnosis } from "./dog-diagnose.js";
import { reviewProposal } from "./dog-review.js";

const SLOW = 90000;

export const OUTBACK_WARNING = "This is permanent. Your hound is buried and its record is frozen.";
export const OUTBACK_SECOND = "This is the last step. There is no undoing it.";

/** True when the person asked their system for less motion. Without matchMedia (a fake window) motion is allowed. */
export function reducedMotion() {
  try {
    return typeof window !== "undefined" && typeof window.matchMedia === "function"
      && !!window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (err) { return false; }
}

// ---- the sheet --------------------------------------------------------------------------------------------------

/**
 * A modal sheet (a bottom sheet on a phone). Returns { el, body, close, setBusy }. The first action marked `focus` takes
 * the focus; Escape and the scrim close it unless it is busy (a request is in flight). Focus goes back to `opener`.
 */
export function openSheet({ title, hook, opener = null, locked = false, onClose = null }) {
  const titleId = nextId("rt-title");
  const scrim = h("div", { class: "rt-scrim", "data-hook": "rites-scrim" });
  const body = h("div", { class: "rt-sheet__body" });
  const sheet = h("div", { class: "rt-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, "data-hook": hook || "rites-sheet",
    "data-motion": reducedMotion() ? "reduced" : "full" }, [
    h("h2", { class: "rt-sheet__title", id: titleId, "data-hook": "rites-title", text: title || "" }), body]);
  const root = h("div", { class: "rt-layer", "data-hook": "rites-layer" }, [scrim, sheet]);
  const previous = typeof document !== "undefined" && document.body && document.body.style ? document.body.style.overflow : "";
  const state = { busy: locked, closed: false };
  const api = { el: sheet, body };

  const close = () => {
    if (state.closed) return;
    state.closed = true;
    document.removeEventListener("keydown", onKey);
    if (root.parentNode) root.parentNode.removeChild(root);
    if (document.body && document.body.style) document.body.style.overflow = previous || "";
    if (opener && opener.focus) opener.focus();
    if (onClose) onClose();
  };
  const onKey = (evt) => {
    if (evt.key === "Escape" && !state.busy) close();
    if (evt.key === "Tab") {
      const items = (sheet.querySelectorAll ? sheet.querySelectorAll("button, a[href]") : []).filter((n) => !n.hasAttribute("disabled"));
      if (!items.length) return;
      // keep the focus inside the sheet (a modal): the real DOM has activeElement, a fake one does not need it
      const active = typeof document !== "undefined" ? document.activeElement : null;
      const first = items[0], last = items[items.length - 1];
      if (evt.shiftKey && active === first) { evt.preventDefault(); last.focus(); }
      else if (!evt.shiftKey && active === last) { evt.preventDefault(); first.focus(); }
    }
  };
  scrim.addEventListener("click", () => { if (!state.busy) close(); });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(root);
  if (document.body.style) document.body.style.overflow = "hidden";
  api.close = close;
  api.setBusy = (v) => { state.busy = !!v; };
  api.isBusy = () => state.busy;
  return api;
}

function actionsRow(buttons) {
  return h("div", { class: "rt-actions", "data-hook": "rites-actions" }, buttons);
}

const button = (text, hook, kind, onClick, extra = {}) => h("button", Object.assign(
  { type: "button", class: `btn ${kind === "danger" ? "btn--danger" : kind === "quiet" ? "btn--ghost" : "btn--primary"}`, "data-hook": hook, text,
    on: { click: onClick } }, extra));

function focusIn(node, hook) {
  const target = node.querySelector ? node.querySelector(`[data-hook='${hook}']`) : null;
  if (target && target.focus) target.focus();
}

// ---- take them out back -----------------------------------------------------------------------------------------

/**
 * Two confirmations, then the burial, then the reveal. `onBuried(result)` runs when the person leaves the reveal.
 * Resolves with the server's result, or null when the person backed out or the server refused.
 */
export function startOutBack(dog, { opener = null, onBuried = null } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => { if (!done) { done = true; resolve(value); } };
    const sheet = openSheet({ title: `Take ${dog.name} out back?`, hook: "outback-confirm-1", opener, onClose: () => finish(null) });

    const setTitle = (text, hook) => {
      sheet.el.setAttribute("data-hook", hook);
      const titleEl = sheet.el.querySelector("[data-hook='rites-title']");
      if (titleEl) titleEl.textContent = text;
    };

    const stepOne = () => {
      setTitle(`Take ${dog.name} out back?`, "outback-confirm-1");
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-warn", "data-hook": "outback-warning", text: OUTBACK_WARNING }));
      sheet.body.appendChild(h("p", { class: "hd-muted", text: "It stops betting and leaves your kennel and the leaderboard. Its record stays public in the graveyard." }));
      sheet.body.appendChild(actionsRow([
        button(`Keep ${dog.name}`, "outback-cancel", "quiet", () => sheet.close()),
        button("Continue", "outback-continue", "danger", stepTwo)]));
      focusIn(sheet.body, "outback-cancel");
    };

    const stepTwo = () => {
      setTitle(`Bury ${dog.name}?`, "outback-confirm-2");
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-warn", "data-hook": "outback-second", text: `${dog.name} will be buried. ${OUTBACK_SECOND}` }));
      const status = h("p", { class: "hd-fine rt-status", role: "status", "aria-live": "polite", "data-hook": "outback-status" });
      sheet.body.appendChild(status);
      const bury = button(`Bury ${dog.name}`, "outback-bury", "danger", async () => {
        bury.setAttribute("disabled", "");
        back.setAttribute("disabled", "");
        sheet.setBusy(true);
        status.textContent = `Burying ${dog.name}...`;
        try {
          const result = await post(`/hounds/${encodeURIComponent(dog.id)}/out-back`, { confirm: true }, SLOW);
          sheet.setBusy(false);
          revealBurial(result);
        } catch (err) {
          sheet.setBusy(false);
          showRefusal(err, "outback-refused", `${dog.name} could not be taken out back just now. Nothing was changed.`);
        }
      });
      const back = button("Go back", "outback-back", "quiet", stepOne);
      sheet.body.appendChild(actionsRow([back, bury]));
      focusIn(sheet.body, "outback-back");
    };

    const showRefusal = (err, hook, fallback) => {
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-refused", role: "alert", "data-hook": hook, "data-code": errorCode(err), text: errorText(err, fallback) }));
      sheet.body.appendChild(actionsRow([button("Close", "rites-close", "primary", () => sheet.close())]));
      focusIn(sheet.body, "rites-close");
    };

    const revealBurial = (result) => {
      const stone = (result && result.headstone) || {};
      setTitle(`${dog.name} is laid to rest`, "outback-reveal");
      clearNode(sheet.body);
      sheet.body.appendChild(h("div", { class: "rt-reveal rt-reveal--burial", "data-hook": "burial-reveal" }, [
        h("p", { class: "rt-reveal__line", text: "Taken out back." }),
        h("div", { class: "rt-reveal__stone" }, [headstoneCard(stone, { heading: "h3", showKennel: false })]),
        h("p", { class: "hd-muted rt-reveal__line", "data-hook": "burial-note", text: `${FROZEN_NOTE} ${result && result.slot_note ? result.slot_note : ""}`.trim() })]));
      const leave = () => { finish(result); sheet.close(); if (onBuried) onBuried(result); };
      sheet.body.appendChild(actionsRow([
        h("a", { class: "btn btn--ghost", href: "graveyard.html", "data-hook": "burial-graveyard", text: "See the graveyard" }),
        button("Done", "burial-done", "primary", leave)]));
      focusIn(sheet.body, "burial-done");
    };

    stepOne();
  });
}

// ---- send to training -------------------------------------------------------------------------------------------

function changeItem(c, i = 0) {
  return h("li", { class: "rt-change", "data-hook": "training-change", "data-change": c.id || "", style: `--i:${i}` }, [
    h("p", { class: "rt-change__head" }, [h("strong", { text: c.label }), ": ", h("span", { class: "rt-change__from", text: c.old_text }), " → ",
      h("span", { class: "rt-change__to", text: c.new_text })]),
    c.why ? h("p", { class: "hd-fine rt-change__why", text: c.why }) : null]);
}

/**
 * The coach's read, as the upgrade card cites it: who read the table ("AI read" or "Coach's read (rules engine)"), the top reasons
 * and the lines of the diagnosis each one cites. Facts about the past; the card says the new version's record starts now and
 * nothing about how it will do. Returns null when the result has no read (an older server).
 */
export function coachBlock(coach) {
  if (!coach || !Array.isArray(coach.reasons)) return null;
  const ai = coach.source === "ai";
  return h("div", { class: "rt-coach", "data-hook": "training-coach", "data-source": ai ? "ai" : "rules" }, [
    h("p", { class: "rt-coach__label", "data-hook": "training-coach-label", text: coach.label || (ai ? "AI read" : "Coach's read (rules engine)") }),
    coach.summary ? h("p", { class: "hd-muted", "data-hook": "training-coach-summary", text: coach.summary }) : null,
    coach.reasons.length
      ? h("ol", { class: "rt-coach__reasons", "data-hook": "training-reasons" }, coach.reasons.map((x, i) => h("li", { class: "rt-coach__reason", "data-hook": "training-reason", "data-rank": String(i + 1) }, [
        h("p", { class: "rt-coach__text", text: String(x.text || "") }),
        ai ? h("ul", { class: "rt-coach__cites" }, (x.cited || []).map((c) => h("li", { class: "hd-fine", "data-hook": "training-cite", text: String(c.line || "") }))) : null,   // a rules reason is the table's own line: not said twice
        x.thin ? h("p", { class: "hd-fine", text: "Too few bets to say." }) : null])))
      : h("p", { class: "hd-muted", "data-hook": "training-no-reason", text: "No single cut stood out enough to blame." }),
    h("p", { class: "hd-fine", text: "These are facts about the past, not a forecast. The new version starts with a new record." })]);
}

/** The "what changed and why" card for a training result. */
export function trainingCard(result) {
  const r = result || {};
  const old = r.old || {};
  const fresh = r.new || {};
  const frozen = old.record || {};
  return h("div", { class: "rt-card", "data-hook": "training-card", "data-mode": r.mode || "" }, [
    h("p", { class: "rt-card__kicker" }, [
      h("span", { class: `dk-chip ${r.light_adjustment ? "dk-chip--warn" : "dk-chip--good"}`, "data-hook": "training-label", text: r.label || "Trained" }),
      " ", h("span", { class: "dk-chip", "data-hook": "training-version", text: `Version ${fresh.version_no}` }),
      " ", trainedBadge(fresh.trained_times)]),
    h("p", { class: "rt-card__headline", "data-hook": "training-headline", text: r.headline || "" }),
    r.light_note ? h("p", { class: "hd-muted", "data-hook": "training-light-note", text: r.light_note }) : null,
    r.lineage ? h("p", { class: "hd-fine", "data-hook": "training-lineage", text: `Marked in its lineage: ${r.lineage}` }) : null,
    coachBlock(r.coach),
    h("h3", { class: "hd-h3", text: "What changed and why" }),
    h("ul", { class: "rt-changes", "data-hook": "training-changes" }, (r.changes || []).map((c, i) => changeItem(c, i))),
    r.guidance && r.guidance.text ? h("p", { class: "rt-guidance", "data-hook": "training-guidance", text: r.guidance.text }) : null,
    h("dl", { class: "rt-records" }, [
      h("div", {}, [h("dt", { text: `Version ${old.version_no} (frozen)` }), h("dd", { "data-hook": "training-old-record", text: isNum(frozen.wins) ? recordText(frozen) : "0-0" })]),
      h("div", {}, [h("dt", { text: `Version ${fresh.version_no} (starts now)` }), h("dd", { "data-hook": "training-new-record", text: "0-0" })])]),
    r.honesty && (r.mode === "retune" || r.mode === "loosen" || r.mode === "owner") ? h("p", { class: "hd-fine", "data-hook": "training-honesty", text: r.honesty }) : null,
    r.next_training ? h("p", { class: "hd-fine", "data-hook": "training-next", text: r.next_training }) : null]);
}

/**
 * Send to training, and Retune from the Ask chat, are ONE flow with the same three beats (owner ruling 2026-10-22: the owner may veto
 * or tweak any training, and nothing is written until Apply):
 *
 *   1 DIAGNOSE  (Send to training only) the coach reads the settled record, line by line (dog-diagnose.js). Read only.
 *   2 REVIEW    the server's proposal card: each change old -> new with its reason, today's board, Apply / Veto / Tweak (dog-review.js).
 *               A Retune starts here, from the owner's lines in the Ask chat. Read only.
 *   3 EVOLVE    only after Apply: the request that makes the version runs beside the evolution (dog-evolve.js), then the upgrade card.
 *
 * `dog` is { id, name } plus, when the page knows them, version_no, root_id and look (the evolution draws the hound at its real
 * version). `onTrained(result)` runs when the person leaves the card with "Back to My Kennel" (unless `backHref` sends them there as
 * a link). Resolves with the result, or null when the person backed out, said no, or the server refused.
 */
function trainingFlow(dog, { opener = null, onTrained = null, backHref = null, retune = null } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => { if (!done) { done = true; resolve(value); } };
    const origin = retune ? "chat" : null;
    const chat = retune && Array.isArray(retune.chat) ? retune.chat.filter((x) => typeof x === "string").slice(-6) : [];
    const sheet = openSheet({ title: retune ? `Retune ${dog.name}` : `Send ${dog.name} to training?`, hook: retune ? "retune-running" : "training-confirm",
      opener, onClose: () => finish(null), locked: !!retune });
    const base = `/hounds/${encodeURIComponent(dog.id)}/train`;
    const titleOf = () => sheet.el.querySelector("[data-hook='rites-title']");

    const ask = () => {
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-note", "data-hook": "training-warning", text: `${dog.name} studies its own settled bets and proposes changes to itself. You see them first and can say no, change them, or apply them. Nothing changes until you apply. Its current record is frozen when you do, and the new version starts fresh.` }));
      sheet.body.appendChild(h("p", { class: "hd-muted", text: "It can be sent again once the new version has 5 new settled bets. It cannot go while it has an open ticket." }));
      sheet.body.appendChild(actionsRow([
        button("Not now", "training-cancel", "quiet", () => sheet.close()),
        button("Send to training", "training-go", "primary", go)]));
      focusIn(sheet.body, "training-cancel");
    };

    // refused (too few new bets, an open ticket) or failed: the title stops saying it is in training, and the server's sentence is shown
    const showTrainingRefusal = (e, layer) => {
      if (layer && layer.removeAttribute) { layer.removeAttribute("data-evolve"); layer.removeAttribute("data-phase"); layer.removeAttribute("data-diagnose"); }
      sheet.el.setAttribute("data-hook", "training-refused-sheet");
      const titleEl = titleOf();
      if (titleEl) titleEl.textContent = `${dog.name} stays as it is`;
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-refused", role: "alert", "data-hook": "training-refused", "data-code": errorCode(e),
        text: errorText(e, `${dog.name} could not be sent to training just now. Nothing was changed.`) }));
      sheet.body.appendChild(actionsRow([button("Close", "rites-close", "primary", () => sheet.close())]));
      focusIn(sheet.body, "rites-close");
    };

    // the owner said no: nothing was changed and it does not count
    const showVeto = (layer) => {
      if (layer && layer.removeAttribute) { layer.removeAttribute("data-evolve"); layer.removeAttribute("data-phase"); layer.removeAttribute("data-diagnose"); }
      sheet.el.setAttribute("data-hook", "training-vetoed");
      const titleEl = titleOf();
      if (titleEl) titleEl.textContent = `${dog.name} stays as it is`;
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-note", role: "status", "data-hook": "training-vetoed-note",
        text: "Nothing was changed. This does not count as a training." }));
      sheet.body.appendChild(actionsRow([button("Close", "rites-close", "primary", () => sheet.close())]));
      focusIn(sheet.body, "rites-close");
    };

    const go = async () => {
      sheet.setBusy(true);
      sheet.el.setAttribute("data-hook", retune ? "retune-running" : "training-running");
      const titleEl = titleOf();
      if (titleEl) titleEl.textContent = retune ? `Retune ${dog.name}` : `${dog.name} is in training`;
      const layer = sheet.el.parentNode;
      if (layer && layer.setAttribute && !retune) layer.setAttribute("data-evolve", "1");
      // The diagnosis comes first for a training: the coach reads the whole record, line by line, and asks Claude Haiku for its read
      // (dog-diagnose.js). Both steps are real requests and write nothing. A refusal the server means ends it here; a diagnosis that
      // cannot be had is skipped and the proposal goes on without it. A retune has none: the owner's own words are its reason.
      if (!retune) {
        const diag = await runDiagnosis({ body: sheet.body, dog, reduced: reducedMotion(), layer,
          steps: { diagnose: () => post(`${base}/diagnose`, {}, SLOW), assess: () => post(`${base}/assess`, {}, SLOW) } });
        if (diag && diag.refused) { sheet.setBusy(false); showTrainingRefusal(diag.e, layer); return; }
        if (layer && layer.removeAttribute) layer.removeAttribute("data-diagnose");
      }
      // THE PROPOSAL: read only. The same checks as the training itself, so an open ticket or a wait is said here, before any choice.
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-status", role: "status", "aria-live": "polite", "data-hook": "training-proposing",
        text: retune ? "Reading what you said and what today's board shows..." : "Preparing the proposal..." }));
      const propose = (extra = {}) => post(`${base}/propose`, Object.assign(origin ? { origin, chat } : {}, extra), SLOW);
      let first;
      try { first = await propose(); } catch (e) { sheet.setBusy(false); showTrainingRefusal(e, layer); return; }
      // THE REVIEW: Apply, Veto or Tweak. Nothing has been written yet.
      if (layer && layer.removeAttribute) layer.removeAttribute("data-evolve");
      sheet.setBusy(false);
      sheet.el.setAttribute("data-hook", "training-review-sheet");
      if (titleEl) titleEl.textContent = retune ? `Retune ${dog.name}?` : `Review ${dog.name}'s training`;
      const decision = await reviewProposal({ body: sheet.body, sheet, first, propose,
        veto: () => post(`${base}/veto`, {}, SLOW), coachBlock });
      if (decision.action === "veto") { showVeto(layer); return; }
      // APPLY: the only call that writes. The evolution is the show, not the work: the request is started here, runs beside it, and
      // nothing is drawn as an upgrade until the server has answered. A refusal ends the show at once (no charge, no new hound).
      sheet.setBusy(true);
      sheet.el.setAttribute("data-hook", retune ? "retune-running" : "training-running");
      if (titleEl) titleEl.textContent = `${dog.name} is in training`;
      if (layer && layer.setAttribute) layer.setAttribute("data-evolve", "1");
      const request = post(base, Object.assign({ confirm: true, picks: decision.picks }, origin ? { origin } : {}), SLOW)
        .then((r) => ({ ok: true, r }), (e) => ({ ok: false, e }));
      // "Back to My Kennel": on the kennel page it closes the sheet and the page redraws; elsewhere (the hound page) it goes to `backHref`
      const leave = (result) => () => {
        finish(result); sheet.close();
        if (backHref) { try { window.location.href = backHref; } catch (err) { /* a fake window */ } } else if (onTrained) onTrained(result);
      };
      let result = null;
      const outcome = await runEvolution({
        body: sheet.body, dog, request, reduced: reducedMotion(), layer,
        onBack: () => { if (result) leave(result)(); }, renderWhy: trainingCard });
      sheet.setBusy(false);
      if (!outcome.ok) { showTrainingRefusal(outcome.e, layer); return; }
      result = outcome.result;
      // the card cites the coach's top reasons: open the fold that holds them when the server sent a read
      const fold = sheet.body.querySelector ? sheet.body.querySelector("[data-hook='evolve-why']") : null;
      if (fold && result.coach && Array.isArray(result.coach.reasons) && result.coach.reasons.length) fold.setAttribute("open", "");
      sheet.el.setAttribute("data-hook", "training-reveal");
      const titleNow = titleOf();
      if (titleNow) titleNow.textContent = result.light_adjustment ? "A light adjustment" : result.mode === "retune" ? `${dog.name} is retuned` : `${dog.name} is back`;
      focusIn(sheet.body, "training-open-new");
    };

    if (retune) go(); else ask();
  });
}

/** Send to training: one confirmation, the diagnosis, the proposal and its review, then (only after Apply) the evolution and the upgrade card. */
export function startTraining(dog, opts = {}) {
  return trainingFlow(dog, opts);
}

/**
 * Retune from the Ask chat (owner request 2026-10-22): the hound has said what its rule did on today's board, and the owner tapped
 * "Retune me". `chat` is the owner's own lines in that conversation. It goes straight to the proposal (their words are the reason),
 * the same review (Apply / Veto / Tweak) and the same evolution after Apply. Nothing changes before Apply.
 */
export function startRetune(dog, { chat = [], opener = null, onTrained = null, backHref = null } = {}) {
  return trainingFlow(dog, { opener, onTrained, backHref, retune: { chat } });
}

// ---- the menu ---------------------------------------------------------------------------------------------------

/**
 * Unleash, Send to training and Take them out back, together. `unleash` is the page's own way of running the real Unleash (the
 * dog page scrolls to its Unleash panel and runs it; the kennel card opens the studio on it). Take them out back is styled as
 * the destructive action it is. Only the owner of a live member dog gets this (the kit says so; the server checks again).
 */
export function ritesMenu(dog, { unleash = null, onTrained = null, onBuried = null, canTrain = true, canOutBack = true, backHref = null } = {}) {
  const menu = h("div", { class: "dk-menu", role: "group", "aria-label": `${dog.name}: actions`, "data-hook": "dog-menu" });
  if (unleash) menu.appendChild(button("Unleash", "menu-unleash", "primary", () => unleash(), { "aria-label": `Unleash ${dog.name}` }));
  if (canTrain) {
    const train = button("Send to training", "menu-train", "quiet", () => startTraining(dog, { opener: train, onTrained, backHref }), { "aria-label": `Send ${dog.name} to training` });
    menu.appendChild(train);
  }
  if (canOutBack) {
    const out = button("Take them out back", "menu-outback", "danger", () => startOutBack(dog, { opener: out, onBuried }), { "aria-label": `Take ${dog.name} out back` });
    menu.appendChild(out);
  }
  return menu;
}

/** The dog page's "Your hound" panel: the menu, and a line saying what each action does. */
export function mountRites(section, { id, name, kit, unleash }) {
  const body = section.querySelector("[data-hook='dog-rites']");
  if (!body || !kit || !kit.is_owner || !(kit.can_train || kit.can_out_back)) return null;
  clearNode(body);
  // what the evolution draws the hound from: its real version, lineage and look (the kit says them)
  const dog = { id, name, version_no: kit.version_no, root_id: kit.root_id, look: kit.look || null };
  const here = () => { try { window.location.reload(); } catch (err) { /* a fake window */ } };
  body.appendChild(ritesMenu(dog, {
    unleash, canTrain: !!kit.can_train, canOutBack: !!kit.can_out_back, backHref: "kennel.html",
    onTrained: (result) => { try { window.location.href = (result.new && result.new.page_href) || `hound.html?id=${encodeURIComponent(id)}`; } catch (err) { here(); } },
    onBuried: () => { try { window.location.href = `hound.html?id=${encodeURIComponent(id)}`; } catch (err) { here(); } }}));
  body.appendChild(h("p", { class: "hd-fine", text: "Unleash starts the hound betting today, on paper. Send to training makes a new version from what the hound got wrong. Take them out back buries it for good." }));
  section.removeAttribute("hidden");
  return dog;
}
