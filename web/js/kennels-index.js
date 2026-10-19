/**
 * The "Kennels" view of the leaderboard page (web/hounds.html?tab=kennels): every member with a public dog, as a card
 * with a small stack of their dogs' avatars, how many dogs, and their best record. Each card opens that member's kennel
 * (web/kennel.html?u=<handle>). Reads GET /hounds/kennels. A dog with no bet yet counts as a dog (it says "new").
 *
 * Its own script, so the leaderboard works the same without it.
 */

import { apiGet } from "./api.js";
import { h, clearNode, describeError, kennelName } from "./hounds-core.js";
import { dogBadge, DEFAULT_LOOK } from "./dog-avatar.js";
import { bankrollNow, returnPctOf, fmtUsd, fmtPct } from "./hounds-board.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

export function bestLine(kennel) {
  const best = kennel.best;
  if (!best) return kennel.new_dogs >= kennel.dog_count ? "New: no bets yet" : "No settled bets yet";
  const r = best.record || {};
  const money = bankrollNow(best) === null ? "" : `, ${fmtUsd(bankrollNow(best))} (${fmtPct(returnPctOf(best))})`;
  return `Best: ${best.name}, ${r.wins || 0}-${r.losses || 0}${r.pushes ? `-${r.pushes}` : ""}${money}`;
}

export function kennelCard(kennel, index = 0) {
  const stack = h("span", { class: "kn-stack", "aria-hidden": "true" },
    (kennel.dogs || []).slice(0, 4).map((d, i) => h("span", { class: "kn-stack__dog", style: `--n:${i}` }, [dogBadge(d.look || DEFAULT_LOOK, { size: 44 })])));
  return h("a", { class: "kn-kcard", href: kennel.href || `kennel.html?u=${encodeURIComponent(kennel.handle)}`, "data-hook": "kennel-card",
    "data-handle": kennel.handle, style: `--i:${Math.min(index, 12)}` }, [
    stack,
    h("span", { class: "kn-kcard__text" }, [
      h("strong", { class: "kn-kcard__name", text: kennelName(kennel.display) }),
      h("span", { class: "kn-kcard__meta", text: `${kennel.dog_count} ${kennel.dog_count === 1 ? "dog" : "dogs"} · ${bestLine(kennel)}` })]),
    h("span", { class: "kn-kcard__go", "aria-hidden": "true", text: "→" })]);
}

export async function renderKennels() {
  const host = q("kennels-index");
  if (!host) return null;
  let data = null;
  try {
    data = await apiGet("/hounds/kennels");
  } catch (err) {
    clearNode(host).appendChild(h("div", { class: `hd-state hd-state--${err && err.status === 404 ? "missing" : "down"}`, role: "status",
      "data-hook": "section-state" }, [h("p", { text: describeError(err, "the kennels").text })]));
    return null;
  }
  const list = Array.isArray(data && data.kennels) ? data.kennels : [];
  const count = q("kennels-count");
  if (count) count.textContent = `${list.length} ${list.length === 1 ? "kennel" : "kennels"}`;
  clearNode(host);
  if (!list.length) {
    host.appendChild(h("div", { class: "kn-empty", "data-hook": "kennels-empty" }, [
      h("h3", { text: "No kennels yet" }),
      h("p", { class: "hd-muted", text: "The first member to build a dog starts one." }),
      h("a", { class: "lh-btn lh-btn--solid", href: "build-a-hound.html", text: "Build a dog" })]));
    return list;
  }
  host.appendChild(h("div", { class: "kn-kgrid", "data-hook": "kennels-grid" }, list.map((k, i) => kennelCard(k, i))));
  return list;
}

export const booted = renderKennels();
