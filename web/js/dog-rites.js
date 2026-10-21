/**
 * The owner's hound menu and its two rites: Send to training and Take them out back (owner ruling 2026-10-20, "like
 * Pokemon games"). Unleash, the run-it-now preview that used to be called Take them out back, sits beside them.
 *
 *   Unleash            POST /hounds/{id}/fire       what the rule would pick on the newest boards, read only (dog-fire.js)
 *   Send to training   POST /hounds/{id}/train      the dog studies its own settled bets and comes back as a new version
 *   Take them out back POST /hounds/{id}/out-back   the dog is buried, its record frozen and public (destructive)
 *
 * TAKE THEM OUT BACK ASKS TWICE. Tap, then a sheet ("This is permanent. Your hound is buried and its record is frozen."),
 * then a second sheet, and only that second button sends the request, with {"confirm": true} (the server refuses
 * without it). Cancel is the default focus of both sheets. SEND TO TRAINING asks once (nothing is lost: the old
 * version keeps its record), then plays a short montage while the server works and shows the "what changed and why" card.
 * The card never says the new version is better: it says its new record starts now.
 *
 * MOTION. The montage and the burial reveal move only when the person has not asked for reduced motion
 * (`reducedMotion()`, and every keyframe is inside prefers-reduced-motion: no-preference in css/dog-kit.css). With reduced
 * motion the finished card appears at once and nothing waits on a timer.
 *
 * This file draws what the server answered and works out nothing; every refusal is the server's own sentence
 * (an open ticket, too few new bets), shown in the sheet with a Close button.
 */

import { h, clearNode, isNum } from "./hounds-core.js";
import { post, errorText, errorCode, nextId } from "./dog-common.js";
import { headstoneCard, recordText, trainedBadge, FROZEN_NOTE } from "./dog-headstone.js";

const SLOW = 90000;
export const MONTAGE_STEP_MS = 650;
export const MONTAGE_STEPS = ["Reading its settled tickets", "Finding where it loses", "Drawing up the changes"];

export const OUTBACK_WARNING = "This is permanent. Your hound is buried and its record is frozen.";
export const OUTBACK_SECOND = "This is the last step. There is no undoing it.";

/** True when the person asked their system for less motion. Without matchMedia (a fake window) motion is allowed. */
export function reducedMotion() {
  try {
    return typeof window !== "undefined" && typeof window.matchMedia === "function"
      && !!window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (err) { return false; }
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
    h("h3", { class: "hd-h3", text: "What changed and why" }),
    h("ul", { class: "rt-changes", "data-hook": "training-changes" }, (r.changes || []).map((c, i) => changeItem(c, i))),
    r.guidance && r.guidance.text ? h("p", { class: "rt-guidance", "data-hook": "training-guidance", text: r.guidance.text }) : null,
    h("dl", { class: "rt-records" }, [
      h("div", {}, [h("dt", { text: `Version ${old.version_no} (frozen)` }), h("dd", { "data-hook": "training-old-record", text: isNum(frozen.wins) ? recordText(frozen) : "0-0" })]),
      h("div", {}, [h("dt", { text: `Version ${fresh.version_no} (starts now)` }), h("dd", { "data-hook": "training-new-record", text: "0-0" })])]),
    r.next_training ? h("p", { class: "hd-fine", "data-hook": "training-next", text: r.next_training }) : null]);
}

function montage() {
  return h("ol", { class: "rt-montage", "data-hook": "training-montage", "aria-label": "Training" }, MONTAGE_STEPS.map((text, i) => h("li", {
    class: "rt-montage__step", "data-step": String(i), style: `--i:${i}`, text })));
}

/**
 * One confirmation, then the montage while the server works, then the "what changed and why" card. `onTrained(result)` runs
 * when the person leaves the card. Resolves with the result, or null when the person backed out or the server refused.
 */
export function startTraining(dog, { opener = null, onTrained = null } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => { if (!done) { done = true; resolve(value); } };
    const sheet = openSheet({ title: `Send ${dog.name} to training?`, hook: "training-confirm", opener, onClose: () => finish(null) });

    const ask = () => {
      clearNode(sheet.body);
      sheet.body.appendChild(h("p", { class: "rt-note", "data-hook": "training-warning", text: `${dog.name} studies its own settled bets, then comes back as the next version with the changes the coach made. Its current record is frozen and the new version starts fresh.` }));
      sheet.body.appendChild(h("p", { class: "hd-muted", text: "It can be sent again once the new version has 5 new settled bets. It cannot go while it has an open ticket." }));
      sheet.body.appendChild(actionsRow([
        button("Not now", "training-cancel", "quiet", () => sheet.close()),
        button("Send to training", "training-go", "primary", go)]));
      focusIn(sheet.body, "training-cancel");
    };

    const go = async () => {
      sheet.setBusy(true);
      sheet.el.setAttribute("data-hook", "training-running");
      const titleEl = sheet.el.querySelector("[data-hook='rites-title']");
      if (titleEl) titleEl.textContent = `${dog.name} is in training`;
      clearNode(sheet.body);
      const reduced = reducedMotion();
      const stage = montage();
      sheet.body.appendChild(stage);
      sheet.body.appendChild(h("p", { class: "hd-fine rt-status", role: "status", "aria-live": "polite", "data-hook": "training-status", text: "Training..." }));
      const request = post(`/hounds/${encodeURIComponent(dog.id)}/train`, { confirm: true }, SLOW).then((r) => ({ ok: true, r }), (e) => ({ ok: false, e }));
      // The montage is the show, not the work: the request runs beside it, and the card waits for both. With reduced
      // motion nothing waits on a timer.
      const minimum = reduced ? 0 : MONTAGE_STEP_MS * MONTAGE_STEPS.length;
      const [outcome] = await Promise.all([request, wait(minimum)]);
      sheet.setBusy(false);
      if (!outcome.ok) {
        // refused (too few new bets, an open ticket): the title stops saying it is in training
        sheet.el.setAttribute("data-hook", "training-refused-sheet");
        if (titleEl) titleEl.textContent = `${dog.name} stays as it is`;
        clearNode(sheet.body);
        sheet.body.appendChild(h("p", { class: "rt-refused", role: "alert", "data-hook": "training-refused", "data-code": errorCode(outcome.e),
          text: errorText(outcome.e, `${dog.name} could not be sent to training just now. Nothing was changed.`) }));
        sheet.body.appendChild(actionsRow([button("Close", "rites-close", "primary", () => sheet.close())]));
        focusIn(sheet.body, "rites-close");
        return;
      }
      const result = outcome.r;
      sheet.el.setAttribute("data-hook", "training-reveal");
      if (titleEl) titleEl.textContent = result.light_adjustment ? "A light adjustment" : `${dog.name} is back`;
      clearNode(sheet.body);
      sheet.body.appendChild(trainingCard(result));
      const leave = () => { finish(result); sheet.close(); if (onTrained) onTrained(result); };
      sheet.body.appendChild(actionsRow([
        h("a", { class: "btn btn--ghost", href: (result.new && result.new.page_href) || "#", "data-hook": "training-open-new", text: `Open version ${result.new && result.new.version_no}` }),
        button("Done", "training-done", "primary", leave)]));
      focusIn(sheet.body, "training-done");
    };

    ask();
  });
}

// ---- the menu ---------------------------------------------------------------------------------------------------

/**
 * Unleash, Send to training and Take them out back, together. `unleash` is the page's own way of running the preview (the
 * dog page scrolls to its Unleash panel and runs it; the kennel card opens the studio on it). Take them out back is styled as
 * the destructive action it is. Only the owner of a live member dog gets this (the kit says so; the server checks again).
 */
export function ritesMenu(dog, { unleash = null, onTrained = null, onBuried = null, canTrain = true, canOutBack = true } = {}) {
  const menu = h("div", { class: "dk-menu", role: "group", "aria-label": `${dog.name}: actions`, "data-hook": "dog-menu" });
  if (unleash) menu.appendChild(button("Unleash", "menu-unleash", "primary", () => unleash(), { "aria-label": `Unleash ${dog.name}` }));
  if (canTrain) {
    const train = button("Send to training", "menu-train", "quiet", () => startTraining(dog, { opener: train, onTrained }), { "aria-label": `Send ${dog.name} to training` });
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
  const dog = { id, name };
  const here = () => { try { window.location.reload(); } catch (err) { /* a fake window */ } };
  body.appendChild(ritesMenu(dog, {
    unleash, canTrain: !!kit.can_train, canOutBack: !!kit.can_out_back,
    onTrained: (result) => { try { window.location.href = (result.new && result.new.page_href) || `hound.html?id=${encodeURIComponent(id)}`; } catch (err) { here(); } },
    onBuried: () => { try { window.location.href = `hound.html?id=${encodeURIComponent(id)}`; } catch (err) { here(); } }}));
  body.appendChild(h("p", { class: "hd-fine", text: "Unleash shows what the rule would pick right now. Send to training makes a new version from what the dog got wrong. Take them out back buries it for good." }));
  section.removeAttribute("hidden");
  return dog;
}
