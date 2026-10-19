/**
 * The "Kennels" view of the leaderboard page (web/hounds.html?tab=kennels): every member with a public dog, as a card
 * with a small stack of their dogs' avatars, how many dogs, and their best record. Each card opens that member's kennel
 * (web/kennel.html?u=<handle>). Reads GET /hounds/kennels. A dog with no bet yet counts as a dog (it says "new").
 *
 * Its own script, so the leaderboard works the same without it.
 */

import { apiGet } from "./api.js";
import { h, clearNode, describeError, kennelName } from "./hounds-core.js";
import { dogFace, dogBadge, DEFAULT_LOOK, lookFor } from "./dog-avatar.js";
import { VIBE_BREED } from "./dog-rig.js";
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
      h("span", { class: "kn-kcard__meta", text: `${kennel.dog_count} ${kennel.dog_count === 1 ? "dog" : "dogs"} · ${bestLine(kennel)}` })]),
    h("span", { class: "kn-kcard__go", "aria-hidden": "true", text: "→" })]);
}

/** The five breeds and the vibe each one stands for: a legend for the dogs on every page, and something to look at in a quiet kennel list. */
export function breedStrip() {
  const word = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  return h("section", { class: "kn-breeds", "data-hook": "kennels-breeds", "aria-label": "The breeds" }, [
    h("h3", { class: "kn-breeds__title", text: "The breeds" }),
    h("p", { class: "hd-fine", text: "A dog's breed follows its vibe. A look (coat, eyes, gear) is the owner's to choose." }),
    h("ul", { class: "kn-breeds__row" }, Object.entries(VIBE_BREED).map(([vibe, breed]) => h("li", { class: "kn-breeds__item", "data-breed": breed }, [
      h("span", { class: "kn-breeds__dog", "aria-hidden": "true" }, [dogBadge(lookFor(breed), { size: 64, breed, mood: "idle" })]),
      h("strong", { class: "kn-breeds__name", text: word(breed) }), h("span", { class: "hd-fine", text: `${word(vibe)} vibe` })])))]);
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
    host.appendChild(breedStrip());
    return list;
  }
  const grid = h("div", { class: "kn-kgrid", "data-hook": "kennels-grid" }, list.map((k, i) => kennelCard(k, i)));
  // the way in: a kennel is a member's dogs, so the last card starts yours
  grid.appendChild(h("a", { class: "kn-newkennel", href: "build-a-hound.html", "data-hook": "kennels-new" }, [
    h("span", { class: "kn-newkennel__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 52, mood: "thinking", id: "new-kennel" })]),
    h("span", { class: "kn-newkennel__text" }, [h("strong", { class: "kn-newkennel__title", text: "Start your own kennel" }),
      h("span", { class: "kn-newkennel__sub", text: "Say a strategy in plain English." })]),
    h("span", { class: "kn-newkennel__go", "aria-hidden": "true", text: "→" })]));
  host.appendChild(grid);
  host.appendChild(breedStrip());
  return list;
}

export const booted = renderKennels();
