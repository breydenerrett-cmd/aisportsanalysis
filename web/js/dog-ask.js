/**
 * Ask your dog: a chat-style panel (GET/POST /hounds/{id}/ask, src/hounds/interact/ask.py).
 *
 * The answers are COMPUTED from the dog's own tickets, rule, record and the stored boards; no model writes them.
 * The page no longer SAYS so (owner, 2026-10-22): a glossary or help answer is not "this hound's own data", so the line was
 * not true of every answer. Suggested questions sit above a text box. An answer is short: one or two lines in the hound's
 * voice, then the pick card (game, side, price, start, the stake in the viewer's sizing). The rule text and the numbers behind a
 * pick sit in a collapsed "How I checked it", never inline. Every answer carries "Good call / Bad call" (signed-in)
 * so a visitor can say whether it helped.
 *
 * RETUNE ME (owner request 2026-10-22). When the owner tells a hound its rule is too tight or too loose, the answer carries
 * `retune: { offer, label, enabled, note }` and ONLY the owner's answer ever does (the server decides; the page just draws what it
 * is given). The button starts the review (dog-rites.js `startRetune`): the proposal, then Apply / Veto / Tweak. It sends the
 * owner's own lines from this conversation, so the hound can cite the one it is answering. Nothing changes until Apply.
 *
 * `mountAsk` is shared with the Training camp, which opens a small chat per dog.
 */

import { getSizing } from "./unitsize.js";
import { h, clearNode } from "./hounds-core.js";
import { get, post, errorText, statusLine } from "./dog-common.js";
import { voteRow } from "./dog-feedback.js";
import { isUpgradeRefusal, upgradePrompt } from "./upgrade.js";
import { startRetune } from "./dog-rites.js";
import { runGematriaStream, gematriaAnalysis, analysisLog, reducedMotion } from "./dog-gematria-stream.js";

/** Questions worth fetching the Gematria hound's analysis for as soon as they are asked (it is played when the answer is a pick answer). */
const PICK_QUESTION = /\b(bet|pick|picks|play|take|taking|tonight|today|right now|games?|fire|unleash)\b/i;

/** A collapsed "How I checked it": a title and lines the answer would otherwise print inline. */
function checkedFold(details) {
  const rows = details && Array.isArray(details.lines) ? details.lines.filter((x) => typeof x === "string" && x) : [];
  if (!rows.length) return null;
  return h("details", { class: "dk-checked", "data-hook": "ask-checked" }, [
    h("summary", { text: (details && details.title) || "How I checked it" }),
    ...rows.map((line) => h("p", { text: line })),
  ]);
}

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
    if (c.stake) li.appendChild(h("p", { class: "dk-pick__stake", "data-hook": "ask-stake", text: `Stake ${c.stake}` }));
    if (c.best) li.appendChild(h("p", { class: "hd-fine", text: c.best }));
    if (c.reason) li.appendChild(checkedFold({ title: "How I checked it", lines: [c.reason] }));
    list.appendChild(li);
  }
  return list;
}

/** The Retune me button under a hound's self-diagnosis (the owner only: the server sends `retune` to nobody else). */
function retuneOffer(offer, onRetune) {
  const wrap = h("div", { class: "dk-retune", "data-hook": "ask-retune-offer" });
  const btn = h("button", { type: "button", class: "btn btn--primary", "data-hook": "ask-retune", text: offer.label || "Retune me" });
  if (offer.enabled === false) btn.setAttribute("disabled", "");
  else btn.addEventListener("click", () => onRetune(btn));
  wrap.appendChild(btn);
  if (offer.enabled === false && offer.note) wrap.appendChild(h("p", { class: "hd-fine", "data-hook": "ask-retune-note", text: offer.note }));
  return wrap;
}

/** `lines` are drawn as paragraphs; `cards` (optional) go in at index `cardsAt` (default: the end). */
function dogMessage(lines, intent, cards, cardsAt, details, fine) {
  const msg = h("div", { class: "dk-msg dk-msg--dog", "data-hook": "ask-answer", "data-intent": intent || "" });
  const rows = lines || [];
  const withCards = Array.isArray(cards) && cards.length > 0;
  const at = withCards ? (Number.isInteger(cardsAt) ? Math.min(cardsAt, rows.length) : rows.length) : -1;
  rows.forEach((line, i) => {
    if (i === at) msg.appendChild(pickCards(cards));
    msg.appendChild(h("p", { text: line }));
  });
  if (at === rows.length) msg.appendChild(pickCards(cards));
  const fold = checkedFold(details);
  if (fold) msg.appendChild(fold);
  if (typeof fine === "string" && fine) msg.appendChild(h("p", { class: "hd-fine", "data-hook": "ask-fine", text: fine }));
  return msg;
}

/**
 * Mount a chat into `box`. `id` and `name` name the dog; `compact` trims the intro. Returns { ask(question) }.
 */
export function mountAsk(box, { id, name, compact = false, gematria = false }) {
  clearNode(box);
  const thread = h("div", { class: "dk-thread", role: "log", "aria-live": "polite", "aria-label": `Conversation with ${name || "this model"}`, "data-hook": "ask-thread" });
  const chips = h("div", { class: "dk-chips", "data-hook": "ask-suggestions" });
  const status = statusLine("ask-status");
  const said = [];                                  // the owner's own lines in this conversation, newest last (what a retune may cite)
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
    said.push(text.slice(0, 300));
    if (said.length > 6) said.shift();
    thread.appendChild(h("div", { class: "dk-msg dk-msg--you", "data-hook": "ask-question" }, [h("p", { text })]));
    input.value = "";
    thread.scrollTop = thread.scrollHeight;
    send.setAttribute("disabled", "");
    try {
      // a Gematria hound's analysis is fetched beside a question that sounds like a pick request, and played before a pick answer
      let analysis = null;
      if (gematria && PICK_QUESTION.test(text)) { analysis = gematriaAnalysis(id); analysis.catch(() => null); }
      const out = await post(`/hounds/${encodeURIComponent(id)}/ask`, { question: text, sizing: getSizing() });
      if (gematria && out.fire) {
        const host = h("div", { class: "dk-msg dk-msg--dog gs-host", "data-hook": "ask-gematria" });
        const played = await runGematriaStream({ body: host, load: () => analysis || gematriaAnalysis(id), reduced: reducedMotion(),
          onStart: () => { thread.appendChild(host); thread.scrollTop = thread.scrollHeight; } });
        if (played.ok) { clearNode(host); const fold = analysisLog(played.payload); if (fold) host.appendChild(fold); }
      }
      const hasCards = Array.isArray(out.cards) && out.cards.length > 0;
      const rows = hasCards && Array.isArray(out.ui_lines) && out.ui_lines.length ? out.ui_lines
        : (out.lines && out.lines.length ? out.lines : [out.answer]);
      const msg = dogMessage(rows, out.intent, hasCards ? out.cards : null, out.cards_at, out.details, out.fine);
      if (out.retune && out.retune.offer) {
        msg.appendChild(retuneOffer(out.retune, (opener) => startRetune({ id, name }, { chat: said.slice(), opener, onTrained: (result) => {
          const href = (result && result.new && result.new.page_href) || `hound.html?id=${encodeURIComponent(id)}`;
          try { window.location.href = href; } catch (err) { /* a fake window */ }
        } })));
      }
      // an introduction is not a call the hound made, so it has no Good call / Bad call row (intent "hello")
      if (out.intent !== "hello") msg.appendChild(voteRow({ id, kind: "answer", targetId: out.intent || "fallback", label: "this answer" }));
      thread.appendChild(msg);
      thread.scrollTop = msg.offsetTop ? Math.max(0, msg.offsetTop - 8) : thread.scrollHeight;     // the top of the new answer
      paint(out.followups);
    } catch (err) {
      if (isUpgradeRefusal(err)) { thread.appendChild(upgradePrompt(err)); thread.scrollTop = thread.scrollHeight; return; }
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
  return { ask };
}

/** The Ask panel on a dog's page: loads the dog's greeting and the questions worth asking, or hides itself. */
export async function bootAsk(section, { id, name, gematria = false }) {
  const body = section.querySelector("[data-hook='dog-ask']");
  if (!body) return;
  let hello = null;
  try {
    hello = await get(`/hounds/${encodeURIComponent(id)}/ask`);
  } catch (err) {
    return;                                  // a server without the route: the panel stays hidden
  }
  const chat = mountAsk(body, { id, name, gematria });
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
