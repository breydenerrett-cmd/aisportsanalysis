/**
 * Unleash (was "Fire now", then, for a day, "Take them out back"; the route, the module and the data-hooks keep the old
 * word, only what a person reads changed): "What would you bet right now?" (POST /hounds/{id}/fire,
 * src/hounds/interact/fire.py). "Take them out back" is the burial now (dog-rites.js); this is only the preview.
 *
 * The server runs the dog's CURRENT rule over the newest stored boards, read only, and answers with the picks it
 * would make (exact prices, books, the checks each pick passed, how old the board is, when its real ticket would be
 * placed) or "Nothing qualifies right now" with the closest misses (which check failed, and by how much). This file
 * only draws that answer; it works out nothing.
 *
 * A PREVIEW IS NOT A TICKET, and the panel says so. The owner of a builder dog also gets "Record as a manual
 * pick" on each pick the server marks recordable (POST /hounds/{id}/manual: its own ledger, paper only, kept apart
 * from the dog's record). Every other visitor sees the same preview with no button.
 *
 * `renderFireResult` is shared with the Training camp, which fires each of an owner's dogs inline.
 *
 * UNLEASH TODAY (owner request 2026-10-21; the kennel's studio, `mountFire(..., { today: true })`). For the OWNER of a member dog the button
 * no longer previews: it STARTS the hound betting today (POST /hounds/{id}/unleash, src/hounds/interact/unleash.py, paper and forward),
 * then reveals the picks it placed (game, side, price, stake) and, below them, what it would have taken before it was unleashed
 * ("Before you unleashed. Not on its record."), which the server computes point-in-time and never writes anywhere. While the request
 * runs the dog sniffs a board and a three-step list waits; the moment the answer lands the steps are ticked off with the real counts and
 * the cards rise in. There is no timer anywhere in it: the animation is the request's own duration plus under a second of reveal,
 * and under prefers-reduced-motion it is the same list with no movement (all of the motion is in css/dog-kit.css).
 */

import { h, clearNode, fmtPrice, isNum } from "./hounds-core.js";
import { post, errorText, errorCode, whenText, spanText, statusLine, celebrate, PAPER_NOTE } from "./dog-common.js";
import { dogBadge, DEFAULT_LOOK } from "./dog-avatar.js";
import { stakeWords } from "./unitsize.js";

const SLOW = 90000;

/**
 * What the read-only preview is called. "Unleash" is the real thing (the owner's button: it starts the hound betting today), so a
 * visitor's run-the-rule-and-look button must not borrow the word (found on live 2026-10-22: the same word meant "nothing is
 * recorded" on the hound page and "bets today" in the studio).
 */
export const PREVIEW_LABEL = "See what it would pick";

/** The call behind the button, shared with the studio, the camp and the live board. */
export const unleash = (id, eventId) => post(`/hounds/${encodeURIComponent(id)}/fire`, eventId ? { event_id: eventId } : {}, SLOW);

/** The call behind the owner's Unleash: start the hound betting today and answer with the day (picks, and the "before" list). */
export const unleashToday = (id) => post(`/hounds/${encodeURIComponent(id)}/unleash`, {}, SLOW);

function priceLine(p) {
  const bits = [`Average price ${fmtPrice(p.price_average)}`];
  if (isNum(p.price_best) && p.price_best !== p.price_average) bits.push(`best ${fmtPrice(p.price_best)}${p.best_book ? ` at ${p.best_book}` : ""}`);
  if (isNum(p.n_books)) bits.push(`${p.n_books} books quoting`);
  return bits.join(", ");
}

function timingLine(p) {
  const bits = [];
  if (p.start_utc) bits.push(`Starts ${whenText(p.start_utc)}.`);
  if (p.before_lock && isNum(p.placed_in_minutes)) bits.push(`My usual placing time is in ${spanText(p.placed_in_minutes)}.`);
  else if (p.before_lock === false) bits.push("My usual placing time has passed.");
  if (isNum(p.board_age_minutes)) bits.push(`Board is ${spanText(p.board_age_minutes)} old${p.stale ? " (older than 75 minutes)" : ""}.`);
  return bits.join(" ");
}

function pickCard(p, { id, canRecord, onRecord }) {
  const status = statusLine("pick-status");
  const li = h("li", { class: "dk-pick", "data-hook": "fire-pick", "data-event": p.event_id, "data-market": p.market });
  li.appendChild(h("div", { class: "dk-pick__head" }, [
    h("strong", { class: "dk-pick__sel", text: p.selection }),
    h("span", { class: "dk-chip", text: p.market_label || p.market }),
    p.stale ? h("span", { class: "dk-chip dk-chip--warn", text: "Old board" }) : null,
    p.over_daily_limit ? h("span", { class: "dk-chip dk-chip--warn", text: "Over the daily limit" }) : null,
  ]));
  li.appendChild(h("p", { class: "dk-pick__game", text: p.game }));
  li.appendChild(h("p", { class: "dk-pick__price hd-num", text: priceLine(p) }));
  const timing = timingLine(p);
  if (timing) li.appendChild(h("p", { class: "hd-fine", text: timing }));
  if (p.reason) li.appendChild(h("p", { class: "dk-pick__reason", "data-hook": "pick-reason", text: p.reason }));
  if (Array.isArray(p.checks) && p.checks.length) {
    li.appendChild(h("details", { class: "dk-checks" }, [h("summary", { text: "How the rule checked it" }),
      h("ul", {}, p.checks.map((c) => h("li", { class: c.ok ? "dk-check--ok" : "dk-check--no" }, [
        h("strong", { text: `${c.ok ? "Passed" : "Failed"}: ${c.label}. ` }), c.detail])))]));
  }
  const manual = p.manual || {};
  if (canRecord) {
    const actions = h("div", { class: "dk-pick__actions" });
    if (manual.can_record) {
      const btn = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "record-manual", text: "Record as a manual pick",
        "aria-label": `Record ${p.selection} as a manual pick` });
      btn.addEventListener("click", async () => {
        btn.setAttribute("disabled", "");
        status.textContent = "Recording...";
        try {
          const out = await post(`/hounds/${encodeURIComponent(id)}/manual`, p.player ? { event_id: p.event_id, market: p.market, player: p.player } : { event_id: p.event_id, market: p.market });
          celebrate(btn, "manual-pick");
          clearNode(actions);
          actions.appendChild(h("p", { class: "dk-ok", "data-hook": "manual-recorded",
            text: `Recorded as a manual pick at ${fmtPrice(out.ticket.price_average)}. It sits apart from the rule's record. ${out.remaining_today} left today.` }));
          if (onRecord) onRecord(out);
        } catch (err) {
          btn.removeAttribute("disabled");
          status.textContent = errorText(err);
          status.setAttribute("data-code", errorCode(err));
        }
      });
      actions.appendChild(btn);
    } else if (manual.blocked) {
      actions.appendChild(h("p", { class: "hd-fine", "data-hook": "manual-blocked", text: `Cannot record this one: ${manual.blocked}.` }));
    }
    li.appendChild(actions);
    li.appendChild(status);
  }
  return li;
}

/** "5:10 PM EDT" in the visitor's own clock, "" when the stamp is unreadable. */
function localClock(stamp) {
  const d = new Date(stamp);
  if (!stamp || Number.isNaN(d.getTime())) return "";
  try { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZoneName: "short" }); } catch (err) { return ""; }
}

/** The server's slate sentence ("Tonight's games already started: ... Next games I can bet: Thursday."), with each
 *  game's Eastern time swapped for the visitor's local time. Said first, so a list that begins on Thursday is not
 *  read as "not looking at tonight's games". */
function slateLine(slate) {
  if (!slate || !slate.line) return "";
  let line = String(slate.line);
  for (const g of [...(slate.started || []), ...(slate.in_window || [])]) {
    const t = localClock(g.start_utc);
    if (t && g.start_et) line = line.split(`(${g.start_et})`).join(`(${t})`);
  }
  return line;
}

/** A sentence out of a field the server may send as a string or as {line}. */
function sentenceOf(v) {
  if (typeof v === "string") return v.trim();
  return v && typeof v.line === "string" ? v.line.trim() : "";
}

/**
 * When the dog has no pick: the server's own words about the dog's NEXT game (`next_game`) and about what is live in OTHER sports
 * right now (`live_elsewhere`), each a string or {line}, and always a link to the live board (web/live.html). The page writes none
 * of this itself; a server that sends neither still gets the link.
 */
function elsewhereBlock(data) {
  const lines = [sentenceOf(data.next_game), sentenceOf(data.live_elsewhere)].filter(Boolean);
  return h("div", { class: "dk-block dk-elsewhere", "data-hook": "fire-elsewhere" }, [
    ...lines.map((line, i) => h("p", { class: "dk-headline dk-elsewhere__line", "data-hook": i === 0 && sentenceOf(data.next_game) ? "fire-next-game" : "fire-live-elsewhere", text: line })),
    h("p", { class: "hd-fine" }, [lines.length ? "" : "Other sports may have games on right now. ", h("a", { href: "live.html", "data-hook": "fire-live-link", text: "See what's on in every sport" }), "."])]);
}

/** Draw a fire payload into `box`. `canRecord` shows the owner's manual-pick buttons. `name` heads it "<name>'s picks right now". */
export function renderFireResult(box, data, { id, name, canRecord = false, onRecord } = {}) {
  clearNode(box);
  if (name) box.appendChild(h("h3", { class: "hd-h3", "data-hook": "fire-title", text: `${name}'s picks right now` }));
  const slate = slateLine(data.slate);
  if (slate) box.appendChild(h("p", { class: "dk-headline dk-slate", "data-hook": "fire-slate", text: slate }));
  box.appendChild(h("p", { class: "dk-headline", "data-hook": "fire-headline", role: "status", text: data.headline || "" }));
  const asOf = [];
  if (data.as_of) asOf.push(`Run ${whenText(data.as_of)}`);
  if (data.newest_board_utc) asOf.push(`newest board ${whenText(data.newest_board_utc)}`);
  if (isNum(data.games_considered)) asOf.push(`${data.games_considered} ${data.games_considered === 1 ? "game" : "games"} read`);
  if (asOf.length) box.appendChild(h("p", { class: "hd-fine", "data-hook": "fire-asof", text: asOf.join(", ") + "." }));
  const picks = Array.isArray(data.picks) ? data.picks : [];
  if (picks.length) {
    const items = [];
    let day = null;
    for (const p of picks) {
      if (p.day_label && p.day_label !== day) {
        day = p.day_label;
        items.push(h("li", { class: "hd-h3 dk-dayhead", role: "presentation", "data-hook": "fire-day", text: day }));
      }
      items.push(pickCard(p, { id, canRecord, onRecord }));
    }
    box.appendChild(h("ul", { class: "dk-picks", "data-hook": "fire-picks" }, items));
  }
  if (!picks.length) box.appendChild(elsewhereBlock(data));
  const recorded = Array.isArray(data.recorded) ? data.recorded : [];
  if (recorded.length) {
    box.appendChild(h("div", { class: "dk-block" }, [h("h3", { class: "hd-h3", text: "Already on the record" }),
      h("ul", { class: "dk-misses", "data-hook": "fire-recorded" }, recorded.map((t) => h("li", { class: "dk-miss" }, [
        h("strong", { text: t.selection }), ` in ${t.game} at ${fmtPrice(t.price_average)}. The rule's own ticket is already on the record.`])))]));
  }
  const misses = Array.isArray(data.closest_misses) ? data.closest_misses : [];
  if (misses.length) {
    box.appendChild(h("div", { class: "dk-block" }, [
      h("h3", { class: "hd-h3", text: picks.length ? "Games it passed on" : "Closest misses" }),
      h("ul", { class: "dk-misses", "data-hook": "fire-misses" }, misses.map((m) => h("li", { class: "dk-miss", "data-code": m.code }, [
        h("p", {}, [h("strong", { text: `${m.title}. ` }), m.game, m.market_label ? ` (${m.market_label})` : ""]),
        h("p", { class: "hd-fine", text: m.why })])))]));
  }
  for (const note of (data.notes || [])) box.appendChild(h("p", { class: "hd-fine", text: note }));
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "fire-preview-note", text: data.preview_note || PAPER_NOTE }));
}

// ---- Unleash today -------------------------------------------------------------------------------------------

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const stakeText = (p) => `${p.stake_units === 1 ? "1 unit" : `${p.stake_units} units`}${isNum(p.stake_units) ? ` (${stakeWords(p.stake_units)})` : ""}`;

/** The working state: the dog sniffing a board and the three steps, the first one live. The server's counts are not known yet, so the
 *  second and third steps wait with no number; nothing here is timed (see the file header). */
export function unleashWorking({ name, look = null, id = "", vibe } = {}) {
  const steps = [["Reading today's board", "active"], ["Checking today's games", "pending"], ["Locking picks", "pending"]];
  return h("div", { class: "ul-stage", "data-hook": "unleash-working", "data-state": "working", role: "status", "aria-live": "polite" }, [
    h("div", { class: "ul-stage__art", "aria-hidden": "true" }, [
      h("div", { class: "ul-board" }, [0, 1, 2, 3, 4].map((i) => h("span", { class: "ul-board__row", style: `--r:${i}` }))),
      h("div", { class: "ul-dog" }, [dogBadge(look || DEFAULT_LOOK, { size: 84, mood: "thinking", id: id || "unleash", name, vibe })])]),
    h("ol", { class: "ul-steps", "data-hook": "unleash-steps" }, steps.map(([text, state], i) => h("li", { class: "ul-step", "data-state": state, "data-step": String(i), text })))]);
}

function stepsDone(data) {
  const n = isNum(data.games_on_board) ? data.games_on_board : 0;
  const placed = isNum(data.placed_now) ? data.placed_now : 0;
  const open = Array.isArray(data.open_tickets) ? data.open_tickets.length : 0;
  const third = placed ? `Locked ${plural(placed, "pick", "picks")}` : (open ? `${plural(open, "open ticket", "open tickets")}, none new` : "Nothing new fit");
  return h("ol", { class: "ul-steps ul-steps--done", "data-hook": "unleash-steps" }, [
    h("li", { class: "ul-step", "data-state": "done", "data-step": "0", text: "Read today's board" }),
    h("li", { class: "ul-step", "data-state": "done", "data-step": "1", text: `Checked ${plural(n, "game", "games")}` }),
    h("li", { class: "ul-step", "data-state": "done", "data-step": "2", text: third })]);
}

/** "Live bet · price at 20:14 UTC": the label on an in-play ticket. UTC, like the "recorded" time beside it on every ticket
 *  (a viewer-zone time read "price at 00:29" beside "recorded 07:30 UTC", seven hours apart for the same bet). */
export function liveLabel(p) {
  if (!p || !p.live) return "";
  const at = p.live_price_at_utc ? new Date(p.live_price_at_utc) : null;
  if (!at || Number.isNaN(at.getTime())) return "Live bet";
  const pad = (v) => String(v).padStart(2, "0");
  return `Live bet · price at ${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())} UTC`;
}

/** Why each game was or was not taken: "Checked 60 games: 38 not in its sports · 14 price outside ... → placed 2", the game
 *  checked next, and when. Every string goes in as text. */
function whyBlock(data) {
  const why = data.why;
  if (!why || !why.text) return null;
  const kids = [h("p", { class: "dk-why", "data-hook": "unleash-why", text: why.text })];
  if (Array.isArray(why.counts) && why.counts.length) {
    kids.push(h("ul", { class: "dk-misses", "data-hook": "unleash-why-list" }, why.counts.map((c) =>
      h("li", { class: "dk-miss", "data-code": c.code, text: `${c.count} ${c.label}` }))));
  }
  const nx = data.next_check;
  if (nx) kids.push(h("p", { class: "hd-fine", "data-hook": "unleash-next", text: `Next game it checks: ${nx.game}, ${whenText(nx.when_utc)} (${nx.what}).` }));
  else kids.push(h("p", { class: "hd-fine", "data-hook": "unleash-next", text: "No more games left to check today in its sports." }));
  if (data.bets_in_play) kids.push(h("p", { class: "hd-fine", text: "It also bets games in play, on a live price under 5 minutes old. In-play prices move fast." }));
  return h("div", { class: "dk-block ul-why" }, kids);
}

function openTicket(t) {
  const li = h("li", { class: "dk-pick ul-card", "data-hook": "unleash-open-ticket", "data-event": t.event_id, "data-state": t.status });
  li.appendChild(h("div", { class: "dk-pick__head" }, [
    h("strong", { class: "dk-pick__sel", text: t.selection }),
    h("span", { class: "dk-chip", text: t.market_label || t.market }),
    h("span", { class: "dk-chip", "data-hook": "unleash-ticket-status", text: t.status_text || "Open" }),
    t.live ? h("span", { class: "dk-chip dk-chip--warn", "data-hook": "unleash-live-chip", text: liveLabel(t) }) : null]));
  li.appendChild(h("p", { class: "dk-pick__game", text: t.game }));
  li.appendChild(h("p", { class: "dk-pick__price hd-num", text: `${fmtPrice(t.price_average)} · Stake ${stakeText(t)}` }));
  return li;
}

function unleashPick(p) {
  const li = h("li", { class: "dk-pick ul-card", "data-hook": "unleash-pick", "data-event": p.event_id, "data-market": p.market });
  li.appendChild(h("div", { class: "dk-pick__head" }, [
    h("strong", { class: "dk-pick__sel", text: p.selection }),
    h("span", { class: "dk-chip", text: p.market_label || p.market }),
    h("span", { class: `dk-chip ${p.placed_now ? "dk-chip--good" : ""}`, text: p.placed_now ? "Placed now" : "On its record" }),
    p.live ? h("span", { class: "dk-chip dk-chip--warn", "data-hook": "unleash-live-chip", text: liveLabel(p) }) : null]));
  li.appendChild(h("p", { class: "dk-pick__game", text: p.game }));
  li.appendChild(h("p", { class: "dk-pick__price hd-num", "data-hook": "unleash-pick-price", text: `${fmtPrice(p.price_average)} · Stake ${stakeText(p)}` }));
  const when = p.start_utc ? whenText(p.start_utc) : "";
  if (when) li.appendChild(h("p", { class: "hd-fine", text: p.started ? `Started ${when}.` : `Starts ${when}.` }));
  return li;
}

function beforeItem(b) {
  const tone = b.result === "won" ? "dk-chip--good" : b.result === "lost" ? "dk-chip--bad" : "";
  const li = h("li", { class: "dk-miss ul-card ul-card--before", "data-hook": "unleash-before-item", "data-event": b.event_id, "data-state": b.state });
  li.appendChild(h("p", {}, [h("strong", { text: b.selection }), ` ${fmtPrice(b.price_average)} `, h("span", { class: `dk-chip ${tone}`, "data-hook": "unleash-outcome", text: b.outcome })]));
  li.appendChild(h("p", { class: "hd-fine", text: `${b.game} · Stake ${stakeText(b)}` }));
  return li;
}

/**
 * The picks the rule makes that were NOT placed (over the day's limit, a later day, waiting for their lock), with ONE button at the top:
 * "Add the other N as manual picks" (POST /hounds/{id}/manual/batch, src/hounds/interact/manual.py record_batch). The server records each
 * through the same path as a single manual pick and answers what it added and what it skipped and why; the page only shows that. Manual
 * picks sit in their own ledger, apart from the record. A second tap adds nothing new.
 */
function otherPicksBlock(others, id, rise) {
  const eligible = others.filter((o) => o.can_record);
  const result = h("p", { class: "hd-fine dk-status", role: "status", "aria-live": "polite", "data-hook": "unleash-bulk-result" });
  const btn = h("button", { type: "button", class: "btn btn--primary", "data-hook": "unleash-bulk",
    text: `Add the other ${eligible.length} as manual picks` });
  if (!eligible.length) btn.setAttribute("disabled", "");
  const chips = {};
  const items = others.map((o) => {
    const chip = h("span", { class: `dk-chip ${o.can_record ? "" : "dk-chip--warn"}`, "data-hook": "unleash-other-chip", text: o.can_record ? o.why_text : `Cannot add: ${o.blocked}` });
    chips[`${o.event_id}|${o.market}|${o.player || ""}`] = chip;
    const when = o.start_utc ? whenText(o.start_utc) : "";
    return rise(h("li", { class: "dk-pick ul-card", "data-hook": "unleash-other", "data-event": o.event_id, "data-market": o.market }, [
      h("div", { class: "dk-pick__head" }, [h("strong", { class: "dk-pick__sel", text: o.selection }), h("span", { class: "dk-chip", text: o.market_label || o.market }), chip]),
      h("p", { class: "dk-pick__game", text: o.game }),
      h("p", { class: "dk-pick__price hd-num", text: `${fmtPrice(o.price_average)} · Stake ${stakeText(o)}${o.day_label ? ` · ${o.day_label}` : ""}` }),
      when ? h("p", { class: "hd-fine", text: `Starts ${when}.` }) : null]));
  });
  btn.addEventListener("click", async () => {
    btn.setAttribute("disabled", "");
    result.textContent = "Adding...";
    try {
      const out = await post(`/hounds/${encodeURIComponent(id)}/manual/batch`,
        { picks: eligible.map((o) => (o.player ? { event_id: o.event_id, market: o.market, player: o.player } : { event_id: o.event_id, market: o.market })) });
      result.textContent = out.line || "";
      for (const r of (out.results || [])) {
        const chip = chips[`${r.event_id}|${r.market}|${r.player || ""}`];
        if (!chip) continue;
        chip.textContent = r.status === "added" ? "Added as a manual pick" : `Skipped: ${r.reason}`;
        chip.setAttribute("class", `dk-chip ${r.status === "added" ? "dk-chip--good" : "dk-chip--warn"}`);
      }
      if (out.added) celebrate(btn, "manual-pick");
    } catch (err) {
      result.textContent = errorText(err, "Could not add them just now. Try again in a minute.");
    } finally {
      btn.removeAttribute("disabled");
    }
  });
  return h("div", { class: "dk-block ul-others", "data-hook": "unleash-others" }, [
    h("h3", { class: "hd-h3", text: "Other picks on the board" }),
    h("p", { class: "hd-fine", text: "These fit the rule but were not placed. Manual picks stay apart from its record." }),
    h("div", { class: "dk-actions" }, [btn]), result,
    h("ul", { class: "dk-picks", "data-hook": "unleash-others-list" }, items)]);
}

/** The day, drawn into `box`: ticked-off steps, the picks (or why there are none), then the "before you unleashed" block.
 *  Every string goes in as text, never as HTML. */
export function renderUnleashDay(box, data, { name, id } = {}) {
  clearNode(box);
  let i = 0;
  // each node rises in after the one before it: --i is the stagger step, capped so the whole reveal stays under a second
  const rise = (node) => { node.setAttribute("class", `${node.className} ul-in`); node.setAttribute("style", `--i:${Math.min(i++, 7)}`); return node; };
  box.appendChild(rise(stepsDone(data)));
  if (name) box.appendChild(h("h3", { class: "hd-h3", "data-hook": "unleash-title", text: `${name}'s day` }));
  // the same slate sentence the preview opens with ("Tonight's games already started ... Next games I can bet: Thursday."), said first
  const slate = slateLine(data.slate);
  if (slate) box.appendChild(rise(h("p", { class: "dk-headline dk-slate", "data-hook": "fire-slate", text: slate })));
  box.appendChild(rise(h("p", { class: "dk-headline", "data-hook": "unleash-headline", role: "status", text: data.headline || "" })));
  const picks = Array.isArray(data.picks) ? data.picks : [];
  // no pick today: the server's words on the next game and on what is live elsewhere, and the link to the live board (never a dead end)
  if (!picks.length) box.appendChild(rise(elsewhereBlock(data)));
  if (picks.length) {
    box.appendChild(h("ul", { class: "dk-picks", "data-hook": "unleash-picks" }, picks.map((p) => rise(unleashPick(p)))));
  }
  const openTickets = Array.isArray(data.open_tickets) ? data.open_tickets : [];
  if (openTickets.length) {
    box.appendChild(rise(h("div", { class: "dk-block ul-open" }, [
      h("h3", { class: "hd-h3", text: "Open tickets" }),
      h("ul", { class: "dk-picks", "data-hook": "unleash-open-tickets" }, openTickets.map((t) => openTicket(t)))])));
  }
  const why = whyBlock(data);
  if (why) box.appendChild(rise(why));
  const others = Array.isArray(data.other_picks) ? data.other_picks : [];
  if (others.length && id) box.appendChild(rise(otherPicksBlock(others, id, rise)));
  const before = Array.isArray(data.before) ? data.before : [];
  const noBoard = Array.isArray(data.no_board) ? data.no_board : [];
  if (before.length || noBoard.length) {
    const block = h("div", { class: "dk-block ul-before", "data-hook": "unleash-before" }, [
      h("h3", { class: "hd-h3", text: "Before you unleashed" }),
      h("p", {}, [h("span", { class: "dk-chip dk-chip--hind", "data-hook": "unleash-before-label", text: data.before_label || "Before you unleashed. Not on its record." })])]);
    if (before.length) block.appendChild(h("ul", { class: "dk-misses", "data-hook": "unleash-before-list" }, before.map((b) => rise(beforeItem(b)))));
    if (noBoard.length) {
      block.appendChild(h("ul", { class: "dk-misses", "data-hook": "unleash-noboard" }, noBoard.map((g) => rise(h("li", { class: "dk-miss ul-card", "data-event": g.event_id }, [
        h("p", {}, [h("strong", { text: g.game })]), h("p", { class: "hd-fine", text: data.no_board_note || "no board saved for this game" })])))));
    }
    box.appendChild(rise(block));
  }
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "unleash-note", text: PAPER_NOTE }));
}

/** The owner's Unleash panel: one button, the working state while the request runs, then the day. */
function mountUnleashToday(section, body, { id, name, avatar, onDone }) {
  body.appendChild(h("p", { class: "hd-muted" }, `Unleash starts ${name || "this hound"} betting today. It checks every game on today's board that is still open for its placing time, places the bets that fit its rule, and from then on it keeps going on its own. It also shows what it would have taken earlier today, kept apart from its record. Paper only.`));
  const result = h("div", { class: "dk-result", "data-hook": "fire-result", "aria-live": "polite" });
  const btn = h("button", { type: "button", class: "btn btn--primary", "data-hook": "fire-btn", text: "Unleash" });
  const status = statusLine("fire-status");
  btn.addEventListener("click", async () => {
    btn.setAttribute("disabled", "");
    status.textContent = "";
    clearNode(result).appendChild(unleashWorking(Object.assign({ name }, avatar || {})));
    try {
      const data = await unleashToday(id);
      renderUnleashDay(result, data, { name: name || "This hound", id });
      if (onDone) onDone(data);
    } catch (err) {
      clearNode(result);
      status.textContent = errorText(err, "Could not unleash just now. Try again in a minute.");
      status.setAttribute("data-code", errorCode(err));
    } finally {
      btn.removeAttribute("disabled");
    }
  });
  body.appendChild(h("div", { class: "dk-actions" }, [btn, status]));
  body.appendChild(result);
  section.removeAttribute("hidden");
}

/** The "Unleash" panel on a dog's page: a button, a status line and the result. With `today` (the kennel studio, for the owner of a
 *  member dog) the button starts the hound instead of previewing it; `avatar` is {look, id, vibe} for the sniffing dog and `onDone`
 *  hears the server's answer (the kennel redraws its cards when bets were placed). */
export function mountFire(section, { id, name, kit, onRecord, today = false, avatar = null, onDone = null }) {
  const body = section.querySelector("[data-hook='dog-fire']");
  if (!body) return;
  clearNode(body);
  if (today && kit && kit.is_owner) return mountUnleashToday(section, body, { id, name, avatar, onDone });
  const canRecord = !!(kit && kit.can_record_manual);
  body.appendChild(h("p", { class: "hd-muted" }, `Run ${name || "this model"}'s current rule on the latest stored boards and see what it would pick. Nothing is recorded${canRecord ? " unless you choose to" : ""}.`));
  const result = h("div", { class: "dk-result", "data-hook": "fire-result", "aria-live": "polite" });
  const btn = h("button", { type: "button", class: "btn btn--primary", "data-hook": "fire-btn", text: PREVIEW_LABEL });
  const status = statusLine("fire-status");
  btn.addEventListener("click", async () => {
    btn.setAttribute("disabled", "");
    status.textContent = `Looking at the boards for ${name || "this hound"}...`;
    try {
      const data = await unleash(id);
      status.textContent = "";
      renderFireResult(result, data, { id, name: name || "This hound", canRecord: canRecord && data.viewer_is_owner !== false, onRecord });
    } catch (err) {
      clearNode(result);
      status.textContent = errorText(err, "The boards could not be read just now. Try again in a minute.");
    } finally {
      btn.removeAttribute("disabled");
      btn.textContent = `${PREVIEW_LABEL} again`;
    }
  });
  body.appendChild(h("div", { class: "dk-actions" }, [btn, status]));
  body.appendChild(result);
  section.removeAttribute("hidden");
}
