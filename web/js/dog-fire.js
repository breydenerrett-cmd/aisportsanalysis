/**
 * Fire now: "What would you bet right now?" (POST /hounds/{id}/fire, src/hounds/interact/fire.py).
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
 */

import { h, clearNode, fmtPrice, isNum } from "./hounds-core.js";
import { post, errorText, errorCode, whenText, spanText, statusLine, celebrate, PAPER_NOTE } from "./dog-common.js";

const SLOW = 90000;

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
          const out = await post(`/hounds/${encodeURIComponent(id)}/manual`, { event_id: p.event_id, market: p.market });
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

/** Draw a fire payload into `box`. `canRecord` shows the owner's manual-pick buttons. */
export function renderFireResult(box, data, { id, canRecord = false, onRecord } = {}) {
  clearNode(box);
  box.appendChild(h("p", { class: "dk-headline", "data-hook": "fire-headline", role: "status", text: data.headline || "" }));
  const asOf = [];
  if (data.as_of) asOf.push(`Run ${whenText(data.as_of)}`);
  if (data.newest_board_utc) asOf.push(`newest board ${whenText(data.newest_board_utc)}`);
  if (isNum(data.games_considered)) asOf.push(`${data.games_considered} ${data.games_considered === 1 ? "game" : "games"} read`);
  if (asOf.length) box.appendChild(h("p", { class: "hd-fine", "data-hook": "fire-asof", text: asOf.join(", ") + "." }));
  const picks = Array.isArray(data.picks) ? data.picks : [];
  if (picks.length) {
    box.appendChild(h("ul", { class: "dk-picks", "data-hook": "fire-picks" }, picks.map((p) => pickCard(p, { id, canRecord, onRecord }))));
  }
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

/** The Fire now panel on a dog's page: a button, a status line and the result. */
export function mountFire(section, { id, name, kit, onRecord }) {
  const body = section.querySelector("[data-hook='dog-fire']");
  if (!body) return;
  clearNode(body);
  const canRecord = !!(kit && kit.can_record_manual);
  body.appendChild(h("p", { class: "hd-muted" }, `Run ${name || "this model"}'s current rule on the latest stored boards and see what it would pick. Nothing is recorded${canRecord ? " unless you choose to" : ""}.`));
  const result = h("div", { class: "dk-result", "data-hook": "fire-result", "aria-live": "polite" });
  const btn = h("button", { type: "button", class: "btn btn--primary", "data-hook": "fire-btn", text: "What would you bet right now?" });
  const status = statusLine("fire-status");
  btn.addEventListener("click", async () => {
    btn.setAttribute("disabled", "");
    status.textContent = "Reading the latest boards...";
    try {
      const data = await post(`/hounds/${encodeURIComponent(id)}/fire`, {}, SLOW);
      status.textContent = "";
      renderFireResult(result, data, { id, canRecord: canRecord && data.viewer_is_owner !== false, onRecord });
    } catch (err) {
      clearNode(result);
      status.textContent = errorText(err, "The boards could not be read just now. Try again in a minute.");
    } finally {
      btn.removeAttribute("disabled");
      btn.textContent = "Fire again";
    }
  });
  body.appendChild(h("div", { class: "dk-actions" }, [btn, status]));
  body.appendChild(result);
  section.removeAttribute("hidden");
}
