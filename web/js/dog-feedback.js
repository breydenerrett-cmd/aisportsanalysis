/**
 * Feedback and training from the page: "Good call / Bad call" on a ticket or an answer, what other people think,
 * and "Train it".
 *
 *   voteRow      two buttons (aria-pressed) plus an optional note, POST /hounds/{id}/feedback. Signed-in only: a
 *                signed-out visitor is asked to sign in, once, in words. A second vote on the same thing replaces
 *                the first. FEEDBACK NEVER CHANGES A DOG: the copy says so, because it is the rule.
 *   mountFans    the "What fans think" panel: counts only (a stranger sees no notes), a short list of recent tickets
 *                to rate, and the training block.
 *   training     a house model: its Coach panel's tip box (graded tips, only the referee changes a model). A builder
 *                dog's owner: "Suggest a change", which opens their builder with the change pre-filled (and lists what
 *                other people suggested, each with its own pre-filled link). Anyone else on a builder dog: "Suggest a
 *                change" sends the owner a suggestion (POST /hounds/{id}/suggest); it changes nothing by itself.
 */

import { h, clearNode, fmtPrice, isNum } from "./hounds-core.js";
import {
  get, post, errorText, signedIn, signInPrompt, builderHref, changeText, FIELD_WORDS, ticketKey, statusLine, nextId, SIGNIN_HREF,
} from "./dog-common.js";

export const NEVER_CHANGES = "Feedback is counted and the owner reads it. It never changes a dog by itself.";
const SMALL = 10;

/**
 * "Good call / Bad call" for one thing. `kind` is ticket | manual | answer | dog, `targetId` what it is about.
 * `my` is "good" | "bad" | undefined (what this person chose before); `counts` {good, bad} shows the tally.
 */
export function voteRow({ id, kind, targetId, my, counts, label = "", onVoted }) {
  const wrap = h("div", { class: "dk-vote", "data-hook": "vote-row", "data-kind": kind });
  const status = statusLine("vote-status");
  const noteBox = h("div", { class: "dk-note", hidden: "" });
  let chosen = my || "";
  let tally = counts ? { good: counts.good || 0, bad: counts.bad || 0 } : null;
  const buttons = {};
  const paint = () => {
    for (const verdict of ["good", "bad"]) {
      const b = buttons[verdict];
      b.setAttribute("aria-pressed", chosen === verdict ? "true" : "false");
      b.textContent = (verdict === "good" ? "Good call" : "Bad call") + (tally && tally[verdict] ? ` (${tally[verdict]})` : "");
    }
  };
  const send = async (verdict, note) => {
    if (!signedIn()) {
      clearNode(status);
      status.appendChild(h("span", {}, ["Sign in to rate. ", h("a", { href: SIGNIN_HREF, text: "Sign in" })]));
      return;
    }
    status.textContent = "Saving...";
    try {
      const body = { target_kind: kind, target_id: targetId || "", verdict };
      if (note) body.note = note;
      const out = await post(`/hounds/${encodeURIComponent(id)}/feedback`, body);
      const cell = (out.counts && out.counts.by_target && out.counts.by_target[`${kind}:${targetId || ""}`]) || null;
      if (counts && cell) tally = { good: cell.good, bad: cell.bad };
      chosen = verdict;
      paint();
      status.textContent = note ? "Saved with your note." : "Saved.";
      noteBox.removeAttribute("hidden");
      if (onVoted) onVoted(out);
    } catch (err) {
      status.textContent = errorText(err);
    }
  };
  for (const verdict of ["good", "bad"]) {
    const b = h("button", { type: "button", class: "dk-vote__btn", "data-verdict": verdict, "aria-pressed": "false",
      "aria-label": `${verdict === "good" ? "Good call" : "Bad call"}${label ? `: ${label}` : ""}` });
    b.addEventListener("click", () => { send(verdict, ""); });
    buttons[verdict] = b;
    wrap.appendChild(b);
  }
  const noteId = nextId("dk-note");
  const input = h("input", { type: "text", maxlength: "200", id: noteId, "data-hook": "vote-note", autocomplete: "off",
    placeholder: "Add a note (optional)", "aria-label": "Add a note to your rating" });
  const save = h("button", { type: "button", class: "dk-vote__btn", "data-hook": "vote-note-save", text: "Save note" });
  save.addEventListener("click", () => { if (chosen) send(chosen, input.value.trim()); });
  noteBox.appendChild(input);
  noteBox.appendChild(save);
  wrap.appendChild(noteBox);
  wrap.appendChild(status);
  paint();
  return wrap;
}

// ---- the menu, for the suggestion form -------------------------------------------------------------

let menuPromise = null;
function menu() {
  if (!menuPromise) menuPromise = get("/hounds/menu").catch(() => null);
  return menuPromise;
}

const FIELDS = ["price_min", "price_max", "min_books", "max_bets_per_day", "lock_minutes", "side_rule"];

function range(lo, hi) {
  const out = [];
  for (let i = lo; i <= hi; i++) out.push(i);
  return out;
}

/** The choices the menu offers for one rule field: [[value, label]]. */
export function choicesFor(m, field) {
  if (!m) return [];
  if (field === "price_min") return (m.price_min.presets || []).map((p) => [p, fmtPrice(p)]);
  if (field === "price_max") return (m.price_max.presets || []).map((p) => [p, fmtPrice(p)]);
  if (field === "min_books") return range(m.min_books.min, m.min_books.max).map((n) => [n, String(n)]);
  if (field === "max_bets_per_day") return range(m.max_bets_per_day.min, m.max_bets_per_day.max).map((n) => [n, String(n)]);
  if (field === "lock_minutes") return (m.lock_minutes.choices || []).map((n) => [n, `${n} minutes`]);
  if (field === "side_rule") return (m.side_rules || []).map((o) => [o.value, o.label]);
  return [];
}

/** A change from the form's two controls: numbers stay numbers, the side rule stays text. */
export function changeFrom(field, raw) {
  return { [field]: field === "side_rule" ? String(raw) : Number(raw) };
}

function suggestForm({ id, owner, onSent }) {
  const box = h("div", { class: "dk-suggest", "data-hook": "suggest-form" });
  const fieldSel = h("select", { "data-hook": "suggest-field", "aria-label": "Which part of the rule" },
    FIELDS.map((f) => h("option", { value: f, text: FIELD_WORDS[f] })));
  const valueSel = h("select", { "data-hook": "suggest-value", "aria-label": "New value" });
  const note = h("input", { type: "text", maxlength: "200", "data-hook": "suggest-note", autocomplete: "off",
    placeholder: "Why? (optional)", "aria-label": "Why you would change it" });
  const status = statusLine("suggest-status");
  let m = null;
  const fill = () => {
    clearNode(valueSel);
    for (const [value, label] of choicesFor(m, fieldSel.value)) valueSel.appendChild(h("option", { value: String(value), text: label }));
  };
  fieldSel.addEventListener("change", fill);
  menu().then((got) => { m = got; fill(); });
  const send = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "suggest-send",
    text: owner ? "Open in the builder" : "Send my suggestion" });
  send.addEventListener("click", async () => {
    const change = changeFrom(fieldSel.value, valueSel.value);
    if (owner) {
      window.location.href = builderHref(id, change);
      return;
    }
    if (!signedIn()) { clearNode(status); status.appendChild(signInPrompt("Sign in to send a suggestion.")); return; }
    status.textContent = "Sending...";
    try {
      const out = await post(`/hounds/${encodeURIComponent(id)}/suggest`, { change, note: note.value.trim() || undefined });
      status.textContent = out.note || "Sent to the owner.";
      if (onSent) onSent(out);
    } catch (err) {
      status.textContent = errorText(err);
    }
  });
  box.appendChild(h("div", { class: "dk-suggest__row" }, [fieldSel, valueSel]));
  if (!owner) box.appendChild(note);
  box.appendChild(h("div", { class: "dk-actions" }, [send, status]));
  return box;
}

function suggestionsList(id, items) {
  if (!items || !items.length) return null;
  return h("div", { class: "dk-block", "data-hook": "owner-suggestions" }, [
    h("h3", { class: "hd-h3", text: "Suggestions from visitors" }),
    h("ul", { class: "dk-misses" }, items.map((s) => h("li", { class: "dk-miss", "data-suggestion": String(s.id) }, [
      h("p", {}, [h("strong", { text: changeText(s.change) }), s.note ? ` — ${s.note}` : ""]),
      h("a", { class: "btn btn--ghost", href: builderHref(id, s.change), "data-hook": "suggestion-open", text: "Open in the builder" })])))]);
}

// ---- the panel -------------------------------------------------------------------------------------

function countsLine(c) {
  const total = (c.good || 0) + (c.bad || 0);
  if (!total) return "Nobody has rated this dog yet. A Good call or Bad call under any ticket counts.";
  return `${total} ${total === 1 ? "rating" : "ratings"}: ${c.good || 0} Good call, ${c.bad || 0} Bad call.${total < SMALL ? " That is a small sample, so read it lightly." : ""}`;
}

async function recentTickets(id) {
  try {
    const data = await get(`/hounds/${encodeURIComponent(id)}/bets?segment=forward&page=1&page_size=8`);
    return Array.isArray(data && data.items) ? data.items : [];
  } catch (err) {
    return [];
  }
}

export async function mountFans(section, { id, name, kit, hound }) {
  const body = section.querySelector("[data-hook='dog-fans']");
  if (!body) return;
  clearNode(body);
  let fb = { counts: kit.feedback || {}, my_votes: kit.my_votes || {} };
  try {
    fb = await get(`/hounds/${encodeURIComponent(id)}/feedback`);
  } catch (err) { /* the kit's own counts stand */ }
  const counts = fb.counts || {};
  const mine = kit.my_votes || fb.my_votes || {};
  body.appendChild(h("p", { "data-hook": "fans-counts", text: countsLine(counts) }));
  if (counts.suggestions && kit.is_owner) body.appendChild(h("p", { class: "hd-fine", text: `${counts.suggestions} ${counts.suggestions === 1 ? "suggestion" : "suggestions"} waiting below.` }));
  body.appendChild(h("p", { class: "hd-fine", text: NEVER_CHANGES }));
  body.appendChild(h("div", { class: "dk-block" }, [h("h3", { class: "hd-h3", text: `Rate ${name || "this model"}` }),
    voteRow({ id, kind: "dog", targetId: "", my: mine["dog:"], counts: (counts.by_kind || {}).dog || { good: 0, bad: 0 }, label: "the dog overall" })]));
  const tickets = await recentTickets(id);
  if (tickets.length) {
    body.appendChild(h("div", { class: "dk-block" }, [h("h3", { class: "hd-h3", text: "Rate its tickets" }),
      h("ul", { class: "dk-tickets", "data-hook": "fans-tickets" }, tickets.map((t) => {
        const key = ticketKey(t);
        return h("li", { class: "dk-ticket", "data-ticket": key }, [
          h("p", { class: "dk-ticket__text" }, [h("strong", { text: t.selection || "" }),
            h("span", { class: "hd-fine", text: ` ${[t.game, fmtPrice(isNum(t.price_average) ? t.price_average : t.price), String(t.date || "").slice(0, 10), t.result || "open"].filter(Boolean).join(" · ")}` })]),
          voteRow({ id, kind: "ticket", targetId: key, my: mine[`ticket:${key}`], counts: (counts.by_target || {})[`ticket:${key}`] || { good: 0, bad: 0 }, label: t.selection })]);
      }))]));
  }
  // train it
  const train = h("div", { class: "dk-block", "data-hook": "dog-train" }, [h("h3", { class: "hd-h3", text: "Train it" })]);
  if (hound && hound.kind === "user") {
    train.appendChild(h("p", { class: "hd-muted", text: kit.is_owner
      ? "Pick one change and your builder opens with it filled in. A change is a new version with its own record; the old one stays as it was."
      : "Think a number should be different? Send the owner a suggestion. It changes nothing by itself." }));
    train.appendChild(suggestForm({ id, owner: !!kit.is_owner }));
    if (kit.is_owner) {
      let extra = null;
      try { extra = (await get(`/hounds/${encodeURIComponent(id)}/feedback`)); } catch (err) { extra = null; }
      const list = suggestionsList(id, extra && extra.suggestions);
      if (list) train.appendChild(list);
      if (extra && Array.isArray(extra.notes) && extra.notes.length) {
        train.appendChild(h("div", { class: "dk-block", "data-hook": "owner-notes" }, [h("h3", { class: "hd-h3", text: "Notes people left" }),
          h("ul", { class: "dk-misses" }, extra.notes.map((n) => h("li", { class: "dk-miss" }, [h("strong", { text: n.verdict === "good" ? "Good call: " : "Bad call: " }), n.note])))]));
      }
    }
  } else {
    train.appendChild(h("p", { class: "hd-muted", text: "If this model has dials, Coach this model, further down, lets you send a tip. Every tip is graded by code against the same games, and only the referee can change a model." }));
  }
  body.appendChild(train);
  section.removeAttribute("hidden");
}
