/**
 * web/kennels.html: every member with a public hound, as a card with a small stack of their hounds' avatars, how many
 * hounds, and their best record. The way in (Create your own hound) is the page's one primary button, not a card here. Each card opens that member's kennel
 * (web/kennel.html?u=<handle>). Reads GET /hounds/kennels. A dog with no bet yet counts as a dog (it says "new").
 *
 * Its own script, so the leaderboard works the same without it.
 */

import { apiGet } from "./api.js";
import { h, clearNode, describeError, kennelName } from "./hounds-core.js";
import { dogFace, dogBadge, DEFAULT_LOOK } from "./dog-avatar.js";
import { featuredDog, featuredCard, activityStrip, fetchStream } from "./kennel-extras.js";
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
    (kennel.dogs || []).slice(0, 4).map((d, i) => h("span", { class: "kn-stack__dog", style: `--n:${i}` }, [dogFace(d, { size: 48 })])));
  return h("a", { class: "kn-kcard", href: kennel.href || `kennel.html?u=${encodeURIComponent(kennel.handle)}`, "data-hook": "kennel-card",
    "data-handle": kennel.handle, style: `--i:${Math.min(index, 12)}` }, [
    stack,
    h("span", { class: "kn-kcard__text" }, [
      h("strong", { class: "kn-kcard__name", text: kennelName(kennel.display) }),
      h("span", { class: "kn-kcard__meta", text: `${kennel.dog_count} ${kennel.dog_count === 1 ? "hound" : "hounds"} · ${bestLine(kennel)}` })]),
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
      // a thinking hound and one sentence; the way in is the page's one primary button above, so no second button here
      h("div", { class: "kn-quiet", "data-hook": "kennel-quiet" }, [
        h("span", { class: "kn-quiet__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 96, mood: "thinking", id: "quiet-kennel" })]),
        h("p", { class: "kn-quiet__text", text: "The first member to create a hound starts one. Say a strategy in plain English and it becomes a hound with a paper bankroll." })])]));
    return list;
  }
  // ROUND 2 (2026-10-19): a quiet list is filled with a featured dog and the latest tickets from member dogs, not a legend of breeds.
  const allDogs = list.flatMap((k) => (k.dogs || []).map((d) => Object.assign({ _kennel: kennelName(k.display) }, d)));
  const pick = featuredDog(allDogs);
  if (pick) host.appendChild(featuredCard(pick, pick.dog._kennel));
  const grid = h("div", { class: "kn-kgrid", "data-hook": "kennels-grid" }, list.map((k, i) => kennelCard(k, i)));
  host.appendChild(grid);
  const strip = activityStrip(await fetchStream(), allDogs);
  if (strip) host.appendChild(strip);
  return list;
}

export const booted = renderKennels();
