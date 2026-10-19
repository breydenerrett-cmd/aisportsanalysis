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

function dogMessage(lines, intent) {
  const msg = h("div", { class: "dk-msg dk-msg--dog", "data-hook": "ask-answer", "data-intent": intent || "" });
  for (const line of (lines || [])) msg.appendChild(h("p", { text: line }));
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
      const msg = dogMessage(out.lines && out.lines.length ? out.lines : [out.answer], out.intent);
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
