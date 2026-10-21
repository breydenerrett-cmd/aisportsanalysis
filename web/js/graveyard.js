/**
 * web/graveyard.html: every dog a member took out back, newest burial first, across all kennels.
 *
 * Reads GET /hounds/graveyard and draws its `headstones` (the server's list; the page keeps the order it was sent in).
 * Each headstone was frozen by the server on the day of the burial (src/hounds/interact/outback.py), so nothing here
 * recomputes a record. The same response also carries `hounds`, the older retired models; they are not this page's.
 *
 * A server that answers without `headstones` (an older build) shows the empty graveyard, not an error: there is
 * nothing buried that it knows about.
 */

import { apiGet } from "./api.js";
import { h, clearNode, describeError } from "./hounds-core.js";
import { headstoneCard } from "./dog-headstone.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

export async function renderGraveyard() {
  const host = q("graveyard-list");
  if (!host) return null;
  let data = null;
  try {
    data = await apiGet("/hounds/graveyard");
  } catch (err) {
    clearNode(host).appendChild(h("div", { class: `hd-state hd-state--${err && err.status === 404 ? "missing" : "down"}`, role: "status",
      "data-hook": "section-state" }, [h("p", { text: describeError(err, "the graveyard").text })]));
    return null;
  }
  const stones = Array.isArray(data && data.headstones) ? data.headstones : [];
  const count = q("graveyard-count");
  if (count) count.textContent = `${stones.length} ${stones.length === 1 ? "headstone" : "headstones"}`;
  clearNode(host);
  if (!stones.length) {
    host.appendChild(h("div", { class: "kn-empty", "data-hook": "graveyard-empty" }, [
      h("h2", { text: "Nothing buried yet" }),
      h("p", { class: "hd-lede", text: "A hound its owner takes out back lands here with a headstone and its final record." })]));
    return stones;
  }
  host.appendChild(h("div", { class: "hs-list", "data-hook": "graveyard-stones" }, stones.map((s) => headstoneCard(s, { heading: "h2" }))));
  return stones;
}

export const booted = renderGraveyard();
