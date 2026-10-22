/**
 * THE REVIEW: every training is proposal -> review -> apply (owner ruling 2026-10-22: "players should have a choice to veto the
 * upgrade or tell it to tweak the changes and why").
 *
 * Send to training and Retune from the Ask chat both end here before anything is written. The server's proposal card
 * (POST /hounds/{id}/train/propose, src/hounds/interact/training.review) is drawn as a list of changes, each one:
 *
 *     [x] Price range: +100 to +110 -> +100 to +120
 *         why (one line, written by code)         You said: "<the owner's line it answers>"          On today's board: 0 -> 1 candidates
 *
 * and three buttons:
 *
 *     Apply   makes the new version with exactly the changes still ticked (the caller sends their ids; the server rebuilds each one
 *             from its closed menu, so a tick can only ever name a change the menu offers). Only Apply writes anything.
 *     Veto    says no: nothing changes, no version is made, and it does not count as a training (POST .../train/veto).
 *     Tweak   opens a short box ("why, or what instead"); the hound looks again through the same menu, within the same caps, and a
 *             revised card replaces the list. Up to three rounds; the card says how many are left.
 *
 * NOTHING HERE IS INVENTED OR EVALUATED. Every word of a change, its reason, its count of candidates on today's board and the
 * honesty line is the server's. The owner's own line is drawn as text (never as markup), so what they typed cannot do anything
 * but read. The page never says the new version will win more: the card says it changes how many and which games the hound looks at.
 *
 * Pure DOM built with h() (text is always textContent), the classes of css/dog-kit.css (rt-*), no library, no script tag.
 */

import { h, clearNode } from "./hounds-core.js";
import { errorText, errorCode } from "./dog-common.js";

export const TWEAK_PLACEHOLDER = "Why, or what instead? For example: look at more sports.";

const button = (text, hook, kind, onClick, extra = {}) => h("button", Object.assign(
  { type: "button", class: `btn ${kind === "quiet" ? "btn--ghost" : "btn--primary"}`, "data-hook": hook, text, on: { click: onClick } }, extra));

/** The candidates figure for one change: "On today's board: 0 -> 1 candidate". Counts of candidates, never results. */
export function todayWords(t) {
  if (!t || !Number.isInteger(t.before) || !Number.isInteger(t.after)) return "";
  const word = (n) => (n === 1 ? "candidate" : "candidates");
  return t.before === t.after ? `On today's board: ${t.after} ${word(t.after)} either way`
    : `On today's board: ${t.before} -> ${t.after} ${word(t.after)}`;
}

/** One proposed change as a list item with a tick the owner can clear. `onTick` runs when it changes. */
export function reviewChange(c, i, onTick) {
  const tick = h("input", { type: "checkbox", "data-hook": "review-tick", "aria-label": `Apply this change: ${c.label}` });
  tick.checked = true;
  tick.addEventListener("change", () => { if (onTick) onTick(); });
  const li = h("li", { class: "rt-change rt-change--pick", "data-hook": "review-change", "data-cid": c.cid || "", "data-direction": c.direction || "",
    style: `--i:${i}` }, [
    h("label", { class: "rt-change__head" }, [tick, " ", h("strong", { text: c.label }), ": ",
      h("span", { class: "rt-change__from", text: c.old_text }), " → ", h("span", { class: "rt-change__to", text: c.new_text })]),
    c.why ? h("p", { class: "hd-fine rt-change__why", "data-hook": "review-why", text: c.why }) : null,
    c.cite && c.cite.text ? h("p", { class: "hd-fine rt-change__cite", "data-hook": "review-cite", text: `You said: “${c.cite.text}”` }) : null,
    c.today ? h("p", { class: "hd-fine", "data-hook": "review-change-today", text: todayWords(c.today) }) : null]);
  li.tick = tick;
  return li;
}

/**
 * Draw the proposal in `body` and resolve with what the owner decided:
 *   { action: "apply", picks: [cid...] }   the ids still ticked (at least one)
 *   { action: "veto" }                     the owner said no (the server was told; if it could not be reached nothing had changed anyway)
 *
 * `first` is the server's proposal card. `propose(extra)` asks for a revised one (`extra` is { tweak, round }); `veto()` tells the
 * server no. `coachBlock` (optional) draws the coach's read above the changes. Every request is the caller's, so tests can fake it.
 */
export function reviewProposal({ body, sheet, first, propose, veto, coachBlock = null }) {
  return new Promise((resolve) => {
    let card = first;
    let tweakOpen = false;
    let busy = false;
    let note = "";

    const setBusy = (v) => { busy = v; if (sheet && sheet.setBusy) sheet.setBusy(v); };

    const render = () => {
      clearNode(body);
      const changes = Array.isArray(card.changes) ? card.changes : [];
      const left = card.tweak && Number.isInteger(card.tweak.left) ? card.tweak.left : 0;
      const root = h("div", { class: "rt-review", "data-hook": "training-review", "data-origin": card.origin || "", "data-mode": card.mode || "" });
      if (card.framing) root.appendChild(h("p", { class: "rt-note", "data-hook": "review-framing", text: card.framing }));
      if (coachBlock && card.coach && Array.isArray(card.coach.reasons) && card.coach.reasons.length) {
        const block = coachBlock(card.coach);
        if (block) root.appendChild(block);
      }
      root.appendChild(h("h3", { class: "hd-h3", text: changes.length ? "What it would change" : "Nothing to change" }));
      const list = h("ul", { class: "rt-changes", "data-hook": "review-changes" });
      const items = changes.map((c, i) => reviewChange(c, i, refresh));
      items.forEach((li) => list.appendChild(li));
      if (items.length) root.appendChild(list);
      if (card.message) root.appendChild(h("p", { class: "rt-note", "data-hook": "review-message", text: card.message }));
      const todayLine = h("p", { class: "hd-muted", "data-hook": "review-today" });
      root.appendChild(todayLine);
      if (card.mapper && card.mapper.label) root.appendChild(h("p", { class: "hd-fine", "data-hook": "review-mapper", text: `Read by: ${card.mapper.label}` }));
      root.appendChild(h("p", { class: "hd-fine", "data-hook": "review-honesty", text: card.honesty || "" }));
      root.appendChild(h("p", { class: "hd-fine", "data-hook": "review-limit", text: card.limit_note || "" }));
      root.appendChild(h("p", { class: "rt-refused", role: "alert", "data-hook": "review-error", text: note, hidden: note ? null : "" }));

      const input = h("textarea", { class: "rt-tweak__input", rows: "3", maxlength: "300", "data-hook": "review-tweak-input", placeholder: TWEAK_PLACEHOLDER,
        "aria-label": "Why, or what instead" });
      const send = button("Look again", "review-tweak-send", "primary", onLookAgain);
      const box = h("div", { class: "rt-tweak", "data-hook": "review-tweak-box", hidden: tweakOpen ? null : "" }, [
        h("label", { class: "hd-fine" }, ["Tell it why, or what you want instead. It maps your words to the changes it is allowed to make.", input]), send]);
      root.appendChild(box);
      root.appendChild(h("p", { class: "hd-fine", "data-hook": "review-tweaks-left", text: left > 0 ? `Tweaks left: ${left}` : "No tweaks left." }));

      const apply = button("Apply", "review-apply", "primary", onApply);
      const noButton = button("Veto", "review-veto", "quiet", onVeto);
      const tweak = button("Tweak", "review-tweak", "quiet", () => { tweakOpen = !tweakOpen; render(); });
      if (left <= 0) tweak.setAttribute("disabled", "");
      root.appendChild(h("div", { class: "rt-actions", "data-hook": "rites-actions" }, [noButton, tweak, apply]));
      body.appendChild(root);

      function refresh() {
        const ticked = items.filter((li) => li.tick.checked).length;
        if (!ticked) apply.setAttribute("disabled", ""); else apply.removeAttribute("disabled");
        // the total for today's board is for the whole set; once a change is cleared only each change's own figure is true
        todayLine.textContent = !items.length || !card.today ? ""
          : ticked === items.length ? `${card.today.text} ${card.today.note || ""}`.trim() : (card.today.note || "");
      }
      refresh();

      function onApply() {
        if (busy) return;
        const picks = items.filter((li) => li.tick.checked).map((li) => li.getAttribute("data-cid")).filter(Boolean);
        if (!picks.length) return;
        resolve({ action: "apply", picks });
      }

      async function onVeto() {
        if (busy) return;
        setBusy(true);
        try { await veto(); } catch (err) { /* nothing had changed, so the answer to the owner is the same */ }
        setBusy(false);
        resolve({ action: "veto" });
      }

      async function onLookAgain() {
        if (busy) return;
        const text = String(input.value || "").trim();
        if (!text) { note = "Say what you want changed, or why."; render(); return; }
        setBusy(true);
        send.setAttribute("disabled", "");
        try {
          const fresh = await propose({ tweak: text, round: card.tweak ? card.tweak.used : 0 });
          if (fresh && fresh.nothing && changes.length) {
            note = fresh.message || "That did not map to a change it is allowed to make.";
            card = Object.assign({}, card, { tweak: fresh.tweak || card.tweak });
          } else {
            card = fresh;
            note = "";
            tweakOpen = false;
          }
        } catch (err) {
          note = errorText(err, "It could not look again just now. Nothing was changed.");
          if (errorCode(err) === "tweak_limit") card = Object.assign({}, card, { tweak: { used: 3, left: 0, max: 3 } });
        }
        setBusy(false);
        render();
      }
    };

    render();
  });
}
