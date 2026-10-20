/**
 * Ask your dog: a chat-style panel (GET/POST /hounds/{id}/ask, src/hounds/interact/ask.py).
 *
 * The answers are COMPUTED from the dog's own tickets, rule, record and the stored boards; no model writes them
 * and the page says so. Suggested questions sit above a text box. Each answer lists what it is built from only in
 * the sense that every number in it is one the page already shows, and carries "Good call / Bad call" (signed-in)
 * so a visitor can say whether it helped.
 *
 * `mountAsk` is shared with the Training camp, which opens a small chat per dog.
 */

import { h, clearNode } from "./hounds-core.js";
import { get, post, errorText, statusLine } from "./dog-common.js";
import { voteRow } from "./dog-feedback.js";

export const NOTE = "Answers are worked out from this dog's own data, not written by an AI model.";

/** The pick cards an answer carries (what the dog would take), drawn with the Fire now panel's own card classes. */
function pickCards(cards) {
  const list = h("ul", { class: "dk-picks", "data-hook": "ask-cards" });
  for (const c of cards) {
    const li = h("li", { class: "dk-pick", "data-hook": "ask-card", "data-state": c.state || "" });
    li.appendChild(h("div", { class: "dk-pick__head" }, [
      h("strong", { class: "dk-pick__sel", text: c.selection }),
      h("span", { class: "dk-chip", text: c.price_text }),
      c.market ? h("span", { class: "dk-chip", text: c.market }) : null,
      c.over_limit ? h("span", { class: "dk-chip dk-chip--warn", text: "Past the daily limit" }) : null,
    ]));
    li.appendChild(h("p", { class: "dk-pick__game", text: `${c.game}${c.when ? `, ${c.when}` : ""}` }));
    if (c.best) li.appendChild(h("p", { class: "hd-fine", text: c.best }));
    if (c.reason) li.appendChild(h("p", { class: "dk-pick__reason", text: c.reason }));
    list.appendChild(li);
  }
  return list;
}

/** `lines` are drawn as paragraphs; `cards` (optional) go in at index `cardsAt` (default: the end). */
function dogMessage(lines, intent, cards, cardsAt) {
  const msg = h("div", { class: "dk-msg dk-msg--dog", "data-hook": "ask-answer", "data-intent": intent || "" });
  const rows = lines || [];
  const withCards = Array.isArray(cards) && cards.length > 0;
  const at = withCards ? (Number.isInteger(cardsAt) ? Math.min(cardsAt, rows.length) : rows.length) : -1;
  rows.forEach((line, i) => {
    if (i === at) msg.appendChild(pickCards(cards));
    msg.appendChild(h("p", { text: line }));
  });
  if (at === rows.length) msg.appendChild(pickCards(cards));
  return msg;
}

/**
 * Mount a chat into `box`. `id` and `name` name the dog; `compact` trims the intro. Returns { ask(question) }.
 */
export function mountAsk(box, { id, name, compact = false }) {
  clearNode(box);
  const thread = h("div", { class: "dk-thread", role: "log", "aria-live": "polite", "aria-label": `Conversation with ${name || "this model"}`, "data-hook": "ask-thread" });
  const chips = h("div", { class: "dk-chips", "data-hook": "ask-suggestions" });
  const status = statusLine("ask-status");
  const inputId = `dk-q-${id}`;
  const input = h("input", { type: "text", id: inputId, maxlength: "300", autocomplete: "off", "data-hook": "ask-input",
    placeholder: `Ask ${name || "it"} anything about its bets`, "aria-label": `Your question for ${name || "this model"}` });
  const send = h("button", { type: "button", class: "btn btn--primary", "data-hook": "ask-send", text: "Ask" });
  const paint = (list) => {
    clearNode(chips);
    for (const q of (list || []).slice(0, 6)) {
      const b = h("button", { type: "button", class: "dk-chipbtn", "data-hook": "ask-chip", text: q });
      b.addEventListener("click", () => { ask(q); });
      chips.appendChild(b);
    }
  };
  async function ask(question) {
    const text = String(question || "").trim();
    if (!text) { status.textContent = "Type a question first."; return; }
    status.textContent = "";
    thread.appendChild(h("div", { class: "dk-msg dk-msg--you", "data-hook": "ask-question" }, [h("p", { text })]));
    input.value = "";
    thread.scrollTop = thread.scrollHeight;
    send.setAttribute("disabled", "");
    try {
      const out = await post(`/hounds/${encodeURIComponent(id)}/ask`, { question: text });
      const hasCards = Array.isArray(out.cards) && out.cards.length > 0;
      const rows = hasCards && Array.isArray(out.ui_lines) && out.ui_lines.length ? out.ui_lines
        : (out.lines && out.lines.length ? out.lines : [out.answer]);
      const msg = dogMessage(rows, out.intent, hasCards ? out.cards : null, out.cards_at);
      msg.appendChild(voteRow({ id, kind: "answer", targetId: out.intent || "fallback", label: "this answer" }));
      thread.appendChild(msg);
      thread.scrollTop = msg.offsetTop ? Math.max(0, msg.offsetTop - 8) : thread.scrollHeight;     // the top of the new answer
      paint(out.followups);
    } catch (err) {
      thread.appendChild(dogMessage([errorText(err, "I could not answer just now. Try again in a minute.")], "error"));
      thread.scrollTop = thread.scrollHeight;
    } finally {
      send.removeAttribute("disabled");
    }
  }
  send.addEventListener("click", () => { ask(input.value); });
  input.addEventListener("keydown", (evt) => { if (evt.key === "Enter") { if (evt.preventDefault) evt.preventDefault(); ask(input.value); } });
  box.appendChild(thread);
  box.appendChild(chips);
  box.appendChild(h("div", { class: "dk-askrow" }, [input, send]));
  box.appendChild(status);
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "ask-note", text: NOTE }));
  return { ask };
}

/** The Ask panel on a dog's page: loads the dog's greeting and the questions worth asking, or hides itself. */
export async function bootAsk(section, { id, name }) {
  const body = section.querySelector("[data-hook='dog-ask']");
  if (!body) return;
  let hello = null;
  try {
    hello = await get(`/hounds/${encodeURIComponent(id)}/ask`);
  } catch (err) {
    return;                                  // a server without the route: the panel stays hidden
  }
  const chat = mountAsk(body, { id, name });
  const thread = body.querySelector("[data-hook='ask-thread']");
  thread.appendChild(dogMessage(hello.greeting, "hello"));
  const chips = body.querySelector("[data-hook='ask-suggestions']");
  for (const q of (hello.suggestions || []).slice(0, 6)) {
    const b = h("button", { type: "button", class: "dk-chipbtn", "data-hook": "ask-chip", text: q });
    b.addEventListener("click", () => { chat.ask(q); });
    chips.appendChild(b);
  }
  section.removeAttribute("hidden");
}
