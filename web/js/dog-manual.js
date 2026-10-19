/**
 * Manual picks: the owner's own tickets on a builder dog (GET /hounds/{id}/manual, src/hounds/interact/manual.py).
 *
 * A manual pick is a paper ticket the owner chose to record from a Fire now preview. It lives in its own ledger and
 * is graded by the same grader as the rule's tickets, but it is NEVER counted in the dog's rule record, its status
 * or the leaderboard: this panel shows it apart, with its own small record, and says so in words.
 */

import { h, clearNode, fmtPrice, isNum } from "./hounds-core.js";
import { get, whenText } from "./dog-common.js";

const STATUS_WORDS = { WON: "Won", LOST: "Lost", PUSH: "Push", VOID: "Void", PENDING: "Pending", UNGRADED: "Ungraded" };

function unitsText(u) {
  return isNum(u) ? `${u > 0 ? "+" : ""}${u.toFixed(2)}u` : "";
}

export async function mountManual(section, { id, kit }) {
  const body = section.querySelector("[data-hook='dog-manual']");
  if (!body) return null;
  async function refresh() {
    let data = null;
    try { data = await get(`/hounds/${encodeURIComponent(id)}/manual`); } catch (err) { data = null; }
    if (!data) { section.setAttribute("hidden", ""); return; }
    const items = Array.isArray(data.tickets) ? data.tickets : [];
    if (!items.length && !(kit && kit.is_owner)) { section.setAttribute("hidden", ""); return; }
    clearNode(body);
    const rec = data.record || {};
    body.appendChild(h("p", { class: "hd-muted", "data-hook": "manual-note",
      text: "Tickets the owner chose to record by hand, kept apart. They are never counted in this dog's rule record, its status or the leaderboard." }));
    if (!items.length) {
      body.appendChild(h("p", { class: "hd-muted", "data-hook": "manual-empty",
        text: `None yet. Run Fire now and use Record as a manual pick on a pick you like. Up to ${data.limit_per_day || 5} a day.` }));
    } else {
      body.appendChild(h("p", { "data-hook": "manual-record", class: "hd-num",
        text: `${rec.graded || 0} graded (${rec.wins || 0}-${rec.losses || 0}${rec.pushes ? `-${rec.pushes}` : ""}), ${unitsText(rec.units_average_price) || "0.00u"} at the average price, ${rec.open || 0} open.${(rec.graded || 0) < 30 ? " A small sample." : ""}` }));
      body.appendChild(h("ul", { class: "dk-tickets", "data-hook": "manual-list" }, items.map((t) => h("li", { class: "dk-ticket", "data-status": t.status }, [
        h("p", {}, [h("strong", { text: t.selection }), ` in ${t.game} at ${fmtPrice(t.price_average)}`,
          isNum(t.price_best) && t.price_best !== t.price_average ? `, best ${fmtPrice(t.price_best)}${t.book ? ` at ${t.book}` : ""}` : ""]),
        h("p", { class: "hd-fine", text: `Recorded ${whenText(t.recorded_utc)}. ${STATUS_WORDS[t.status] || t.status}${unitsText(t.units_average_price) ? `, ${unitsText(t.units_average_price)}` : ""}. Manual pick, not counted in the record.` })]))));
    }
    section.removeAttribute("hidden");
  }
  await refresh();
  return { refresh };
}
