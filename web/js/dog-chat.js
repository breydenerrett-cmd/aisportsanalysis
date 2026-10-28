/**
 * Talk to your hound: the studio's Ask tab as a real conversation (GET / POST / DELETE /hounds/{id}/chat, api/hounds_chat.py).
 *
 * Owner request 2026-10-28: "a way for users to talk to their hounds ... and be able to interact, edit rules, change, directly from
 * within their own chat bubble and conversation, with conversation history that shows."
 *
 * The member's lines sit on the right, the hound's on the left with its own face. The history is the server's (saved per member and
 * hound lineage), loaded on open and scrolled to the newest line; "Clear chat" wipes it after a second tap. The answers come from Claude
 * Haiku, as the hound, from the hound's own rule and record; the page draws what it is given and decides nothing.
 *
 * A CHANGE IS A CARD, NEVER A SURPRISE. When the member asks for a change the hound stages a proposal and the line carries a card:
 * each change as Before and After in plain words, then Apply and Cancel. Nothing about the hound changes until Apply (the server makes
 * the next version and says so). Cancel changes nothing. An applied card hands the new version to `onApplied` so the kennel can point
 * the studio at it; this module keeps talking to the same hound.
 *
 * `bootChat` resolves false when the server has no chat for this hound (an older server, not the owner): the caller then mounts the
 * computed Ask (dog-ask.js) instead, so the tab is never empty. When the server says chat cannot answer right now (no key, the shared
 * spending limit) the saved conversation still shows and the box says so in words.
 */

import { dogBadge, lookFor } from "./dog-avatar.js";
import { h, clearNode } from "./hounds-core.js";
import { get, post, errorText, errorCode } from "./dog-common.js";
import { apiDelete } from "./api.js";

const SEND_TIMEOUT_MS = 70000;           // the model may think a while, then answer
const SUGGESTIONS = ["How am I doing?", "Why did you take your last bet?", "Explain my rule", "Bet fewer games a day"];
const END_STATES = {
  applied: "Applied.",
  cancelled: "Cancelled. No change was made.",
  replaced: "Replaced by a later change.",
  stale: "Out of date: ask me again.",
  failed: "That change could not be applied.",
};

const lines = (text) => String(text == null ? "" : text).split("\n").filter((t) => t.trim() !== "");

function allowanceText(limits) {
  if (!limits || !Number.isFinite(limits.left_today)) return "";
  const left = limits.left_today;
  return `${left} of ${limits.limit_per_day} message${limits.limit_per_day === 1 ? "" : "s"} left today`;
}

/**
 * Mount the conversation into `section`. `hound` = { id, name, look, version, root_id }. Resolves true when it mounted.
 */
export async function bootChat(section, hound, { onApplied } = {}) {
  let state;
  try {
    state = await get(`/hounds/${encodeURIComponent(hound.id)}/chat`);
  } catch (err) {
    return false;                              // no chat here: the computed Ask takes the tab
  }
  if (!state || !Array.isArray(state.messages)) return false;
  const body = section.querySelector("[data-hook='dog-ask']") || section;
  clearNode(body);
  const name = (state.hound && state.hound.name) || hound.name || "your hound";
  const ctx = { id: (state.hound && state.hound.id) || hound.id, name, look: hound.look, root: (state.hound && state.hound.root_id) || hound.root_id || hound.id,
    version: (state.hound && state.hound.version_no) || hound.version, limits: state.limits, available: state.available !== false,
    reason: state.reason, canEdit: !state.hound || state.hound.can_edit !== false };

  const thread = h("div", { class: "dc-thread", role: "log", "aria-live": "polite", "aria-label": `Conversation with ${name}`, "data-hook": "chat-thread" });
  const status = h("p", { class: "hd-fine dk-status dc-status", role: "status", "aria-live": "polite", "data-hook": "chat-status" });
  const allowance = h("p", { class: "hd-fine dc-allowance", "data-hook": "chat-allowance" });
  const notice = h("p", { class: "dc-unavailable", role: "status", "data-hook": "chat-unavailable", hidden: true });
  const chips = h("div", { class: "dk-chips dc-chips", "data-hook": "chat-suggestions" });
  const input = h("input", { type: "text", id: `dc-q-${ctx.id}`, maxlength: String((ctx.limits && ctx.limits.message_max_chars) || 500), autocomplete: "off",
    "data-hook": "chat-input", placeholder: `Say something to ${name}`, "aria-label": `Your message to ${name}` });
  const send = h("button", { type: "button", class: "btn btn--primary", "data-hook": "chat-send", text: "Send" });
  const clear = h("button", { type: "button", class: "btn btn--soft dc-clear", "data-hook": "chat-clear", text: "Clear chat" });
  const sure = h("span", { class: "dc-sure", "data-hook": "chat-clear-sure", hidden: true }, [
    h("span", { text: "Clear this chat?" }),
    h("button", { type: "button", class: "btn btn--danger", "data-hook": "chat-clear-yes", text: "Yes, clear it" }),
    h("button", { type: "button", class: "btn btn--soft", "data-hook": "chat-clear-no", text: "Keep it" })]);

  const face = () => dogBadge(ctx.look || lookFor(ctx.root || ctx.id), { size: 34, mood: "idle", id: ctx.root || ctx.id, name: ctx.name, version: ctx.version });
  const toEnd = () => { thread.scrollTop = thread.scrollHeight; };

  function setComposer() {
    const left = ctx.limits && Number.isFinite(ctx.limits.left_today) ? ctx.limits.left_today : 1;
    const open = ctx.available && left > 0;
    if (open) { input.removeAttribute("disabled"); send.removeAttribute("disabled"); } else { input.setAttribute("disabled", ""); send.setAttribute("disabled", ""); }
    allowance.textContent = allowanceText(ctx.limits);
    chips.hidden = !open;
    if (!ctx.available) {
      notice.hidden = false;
      clearNode(notice);
      notice.appendChild(document.createTextNode(`${ctx.reason || "Chat is unavailable right now."} `));
      notice.appendChild(h("a", { href: `hound.html?id=${encodeURIComponent(ctx.id)}&tab=ask`, "data-hook": "chat-quick-link", text: "Quick answers from my record" }));
    } else if (left <= 0) {
      notice.hidden = false;
      notice.textContent = "That is all your messages for today. They come back tomorrow.";
    } else notice.hidden = true;
  }

  /** The card a proposal carries: each change as Before and After, then Apply and Cancel while it waits on a tap. */
  function card(msg) {
    const box = h("div", { class: "dc-card", "data-hook": "chat-proposal", "data-id": String(msg.id) });
    return fillCard(box, msg);
  }

  function fillCard(box, msg) {
    const p = msg.proposal;
    box.setAttribute("data-status", p.status);
    box.appendChild(h("p", { class: "dc-card__title", text: "Proposed change" }));
    const list = h("ul", { class: "dc-card__list", "data-hook": "chat-changes" });
    for (const c of (p.changes || [])) {
      list.appendChild(h("li", { class: "dc-change", "data-hook": "chat-change" }, [
        h("strong", { class: "dc-change__what", text: c.what }),
        h("p", { class: "dc-change__before", "data-hook": "chat-before" }, [h("span", { class: "dc-tag", text: "Before" }), ` ${c.before == null ? "nothing" : c.before}`]),
        h("p", { class: "dc-change__after", "data-hook": "chat-after" }, [h("span", { class: "dc-tag dc-tag--after", text: "After" }), ` ${c.after == null ? "nothing" : c.after}`])]));
    }
    box.appendChild(list);
    if (p.rule_after) {
      box.appendChild(h("details", { class: "dk-checked dc-card__rule" }, [h("summary", { text: "How the rules will read" }), h("p", { text: p.rule_after })]));
    }
    const result = h("p", { class: "hd-fine dc-card__result", role: "status", "data-hook": "chat-proposal-status" });
    box.appendChild(result);
    if (p.status === "pending") {
      const apply = h("button", { type: "button", class: "btn btn--primary", "data-hook": "chat-apply", text: "Apply" });
      const cancel = h("button", { type: "button", class: "btn btn--soft", "data-hook": "chat-cancel", text: "Cancel" });
      const settle = async (verb) => {
        apply.setAttribute("disabled", ""); cancel.setAttribute("disabled", "");
        result.textContent = verb === "apply" ? "Applying..." : "Cancelling...";
        try {
          const out = await post(`/hounds/${encodeURIComponent(ctx.id)}/chat/proposals/${msg.id}/${verb}`, {});
          const updated = (out.messages || [])[0];
          if (updated && updated.proposal) fillCard(clearNode(box), updated);
          for (const m of (out.messages || []).slice(1)) { thread.appendChild(bubble(m)); }
          if (verb === "apply" && out.hound) {
            ctx.id = out.hound.id; ctx.version = out.hound.version_no;
            if (typeof onApplied === "function") { try { await onApplied(out); } catch (err) { /* the kennel redraws on its next load */ } }
          }
          toEnd();
        } catch (err) {
          apply.removeAttribute("disabled"); cancel.removeAttribute("disabled");
          result.textContent = errorText(err, "That did not work. Try again in a minute.");
          if (/^proposal_/.test(errorCode(err))) { apply.setAttribute("disabled", ""); cancel.setAttribute("disabled", ""); }
        }
      };
      apply.addEventListener("click", () => settle("apply"));
      cancel.addEventListener("click", () => settle("cancel"));
      box.appendChild(h("div", { class: "dc-card__actions" }, [apply, cancel]));
      box.appendChild(h("p", { class: "hd-fine", text: "Nothing changes until you tap Apply. Paper only." }));
    } else if (p.status === "applied") {
      const v = p.applied && p.applied.version_no;
      result.textContent = v ? `Applied. Version ${v} is running.` : END_STATES.applied;
    } else result.textContent = END_STATES[p.status] || "";
    return box;
  }

  function bubble(msg) {
    if (msg.role === "notice") return h("p", { class: "dc-notice", "data-hook": "chat-notice", text: msg.text });
    const mine = msg.role === "member";
    const bub = h("div", { class: `dc-bubble dc-bubble--${mine ? "you" : "hound"}`, "data-hook": mine ? "chat-you-text" : "chat-hound-text" },
      lines(msg.text).map((t) => h("p", { class: "dc-line", text: t })));
    if (!mine && msg.proposal) bub.appendChild(card(msg));
    const row = h("div", { class: `dc-row dc-row--${mine ? "you" : "hound"}`, "data-hook": mine ? "chat-you" : "chat-hound", "data-id": String(msg.id == null ? "" : msg.id) });
    if (!mine) row.appendChild(h("span", { class: "dc-face", "data-hook": "chat-face" }, [face()]));
    row.appendChild(bub);
    return row;
  }

  function draw(messages) {
    clearNode(thread);
    if (!messages.length) {
      thread.appendChild(bubble({ id: "", role: "hound", text: `Hi, I'm ${name}. Ask me about my bets, or tell me what to change about how I bet. I only know my own rule and record, and nothing changes until you tap Apply.` }));
    } else for (const m of messages) thread.appendChild(bubble(m));
    toEnd();
  }

  function paintChips() {
    clearNode(chips);
    for (const q of SUGGESTIONS) {
      const b = h("button", { type: "button", class: "dk-chipbtn", "data-hook": "chat-chip", text: q });
      b.addEventListener("click", () => { say(q); });
      chips.appendChild(b);
    }
  }

  let busy = false;
  async function say(raw) {
    const text = String(raw == null ? "" : raw).trim();
    if (!text) { status.textContent = "Type a message first."; return; }
    if (busy || !ctx.available) return;
    busy = true;
    status.textContent = "";
    input.value = "";
    send.setAttribute("disabled", "");
    const mineNow = bubble({ id: "", role: "member", text });
    const typing = h("div", { class: "dc-row dc-row--hound dc-row--typing", "data-hook": "chat-typing" }, [
      h("span", { class: "dc-face" }, [face()]), h("div", { class: "dc-bubble dc-bubble--hound", text: "..." })]);
    thread.appendChild(mineNow);
    thread.appendChild(typing);
    toEnd();
    try {
      const out = await post(`/hounds/${encodeURIComponent(ctx.id)}/chat`, { message: text }, SEND_TIMEOUT_MS);
      thread.removeChild(mineNow); thread.removeChild(typing);
      for (const m of (out.messages || [])) thread.appendChild(bubble(m));
      if (out.hound) { ctx.id = out.hound.id; ctx.version = out.hound.version_no; }
      ctx.limits = out.limits || ctx.limits;
      toEnd();
    } catch (err) {
      thread.removeChild(mineNow); thread.removeChild(typing);
      input.value = text;                                // nothing was sent: the words are still the member's
      const code = errorCode(err);
      status.textContent = errorText(err, "I couldn't answer just now. Try again in a minute.");
      if (code === "daily_limit" && ctx.limits) ctx.limits = Object.assign({}, ctx.limits, { left_today: 0, used_today: ctx.limits.limit_per_day });
      if (code === "unavailable" || code === "resting") { ctx.available = false; ctx.reason = errorText(err); }
    } finally {
      busy = false;
      setComposer();
    }
  }

  send.addEventListener("click", () => { say(input.value); });
  input.addEventListener("keydown", (evt) => { if (evt.key === "Enter") { if (evt.preventDefault) evt.preventDefault(); say(input.value); } });
  clear.addEventListener("click", () => { sure.hidden = false; clear.setAttribute("hidden", ""); });
  sure.querySelector("[data-hook='chat-clear-no']").addEventListener("click", () => { sure.hidden = true; clear.removeAttribute("hidden"); });
  sure.querySelector("[data-hook='chat-clear-yes']").addEventListener("click", async () => {
    try {
      await apiDelete(`/hounds/${encodeURIComponent(ctx.id)}/chat`);
      state.messages = [];
      draw([]);
      status.textContent = "Chat cleared.";
    } catch (err) {
      status.textContent = errorText(err, "That did not work. Try again in a minute.");
    }
    sure.hidden = true;
    clear.removeAttribute("hidden");
  });

  body.appendChild(thread);
  body.appendChild(notice);
  paintChips();
  body.appendChild(chips);
  body.appendChild(h("div", { class: "dk-askrow dc-askrow" }, [input, send]));
  body.appendChild(status);
  body.appendChild(h("div", { class: "dc-foot" }, [allowance, clear, sure]));
  body.appendChild(h("p", { class: "hd-fine dc-fine", text: "Paper only. Not advice. I answer from my own rule and record, and I will tell you when I don't have something." }));
  draw(state.messages);
  setComposer();
  return true;
}
