/**
 * The dog kit on web/hound.html: Unleash, the owner's hound menu (Send to training, Take them out back), Backtest, Ask, the manual picks, what fans think and training, and (for a builder
 * dog's owner) the locker room. `bootDogKit(hound)` is called by hounds-detail.js once the model has loaded.
 *
 * ONE REQUEST DECIDES WHAT THIS VISITOR SEES: GET /hounds/{id}/kit says whether they own the dog, whether it can be
 * fired, whether a manual pick can be recorded, and its saved look. The server checks again on every write, so the
 * buttons are a convenience, not the gate. A server without the kit (404) or one that is down leaves the page exactly
 * as it was: every panel here starts hidden and shows itself only with something real to show.
 *
 * The header's monogram is swapped for the dog's badge when its owner has dressed it (builder dogs only); every
 * other model keeps its initials badge.
 *
 * THE OWNER'S HOUND MENU (dog-rites.js): for the owner of a live member dog, a "Your hound" panel with Unleash (the real one, the studio's: it starts the hound betting today;
 * the panel below it), Send to training and Take them out back. A dog that has been sent to training wears "Trained xN" in its
 * header; a dog its owner buried shows its headstone (GET /hounds/{id}/headstone) instead of any of the above.
 */

import { get } from "./dog-common.js";
import { dogBadge, DEFAULT_LOOK, lookFor } from "./dog-avatar.js";
import { poseOfHound } from "./dog-avatar.js";
import { mountFire, PREVIEW_LABEL } from "./dog-fire.js";
import { mountBacktest } from "./dog-backtest.js";
import { bootAsk } from "./dog-ask.js";
import { mountFans } from "./dog-feedback.js";
import { mountManual } from "./dog-manual.js";
import { mountLocker } from "./dog-locker.js";
import { mountRites } from "./dog-rites.js";
import { headstoneCard, trainedBadge } from "./dog-headstone.js";
import { clearNode } from "./hounds-core.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

/** Put the dog's badge in the header where the monogram is. Returns true when it swapped. */
export function applyHeaderBadge(look, name, muted = false, dog = {}) {
  const old = document.querySelector(".hd-modelhead .hd-mono") || document.querySelector(".hd-modelhead .dk-badge");
  if (!old || !look) return false;
  // keep the size the header drew the first face at (the hero's big art), 84 when it did not say
  const drawn = Number(old.getAttribute ? old.getAttribute("width") : 0);
  const badge = dogBadge(look, { size: drawn > 0 ? drawn : 84, id: dog.root_id || dog.id, name: name || dog.name, vibe: dog.vibe, version: dog.version_no, mood: muted ? "sad" : (dog.pose || "idle") });
  badge.setAttribute("data-hook", "header-badge");
  if (muted) badge.setAttribute("style", "opacity:.55");
  const parent = old.parentNode;
  if (parent.insertBefore) parent.insertBefore(badge, old); else parent.appendChild(badge);
  parent.removeChild(old);
  return true;
}

/** "Trained xN" in the header's chip row, once. */
export function applyTrainedBadge(times) {
  const chips = document.querySelector(".hd-modelhead .hd-chips");
  const badge = trainedBadge(times);
  if (!chips || !badge || document.querySelector("[data-hook='trained-badge']")) return false;
  chips.appendChild(badge);
  return true;
}

/** A buried dog's headstone, in its own panel. Resolves false when the server has none (the page is what it was). */
async function mountHeadstone(section, id) {
  if (!section) return false;
  let data = null;
  try { data = await get(`/hounds/${encodeURIComponent(id)}/headstone`); } catch (err) { return false; }
  const body = section.querySelector("[data-hook='dog-headstone']");
  if (!data || !data.headstone || !body) return false;
  clearNode(body).appendChild(headstoneCard(data.headstone, { heading: "h3", showKennel: true }));
  section.removeAttribute("hidden");
  return true;
}

export async function bootDogKit(hound, { onUnleashed = null } = {}) {
  const id = hound && hound.id;
  if (!id) return null;
  const sections = {
    fire: q("dog-fire-section"), ask: q("dog-ask-section"), manual: q("dog-manual-section"),
    fans: q("dog-fans-section"), locker: q("dog-locker-section"), backtest: q("dog-backtest-section"),
    rites: q("dog-rites-section"), headstone: q("dog-headstone-section"),
  };
  if (!sections.fire) return null;
  let kit = null;
  try {
    kit = await get(`/hounds/${encodeURIComponent(id)}/kit`);
  } catch (err) {
    return null;                                  // no kit on this server: the page is what it was
  }
  if (!kit || typeof kit !== "object") return null;
  const name = hound.name || kit.name || "this model";
  // a builder dog always wears a dog (its saved look, else the default one); the house models keep their initials
  const vibe = hound.persona && hound.persona.vibe;
  if (kit.look || hound.kind === "user") applyHeaderBadge(kit.look || lookFor(kit.root_id || id), name, hound.status === "retired", { id, root_id: kit.root_id, vibe, version_no: kit.version_no, pose: poseOfHound(hound) });
  if (kit.trained_times) applyTrainedBadge(kit.trained_times);
  let manual = null;
  const jobs = [];
  if (kit.buried) jobs.push(mountHeadstone(sections.headstone, id));
  if (hound.kind === "user" && sections.manual) {
    jobs.push(mountManual(sections.manual, { id, kit }).then((m) => {
      manual = m;
      // the right-now card (hound-rightnow.js) records through the same route; keep this panel current
      if (m && typeof document !== "undefined" && document.addEventListener) document.addEventListener("hound:manual-recorded", () => m.refresh());
    }));
  }
  if (kit.can_fire) {
    // THE OWNER'S UNLEASH IS THE STUDIO'S (dog-fire.js `today`, POST /hounds/{id}/unleash): it starts the hound betting today and
    // shows the day and the before-list. A visitor gets the read-only preview under its own name ("See what it would pick").
    const owner = !!kit.is_owner;
    const heading = sections.fire.querySelector("h2");
    if (heading) heading.textContent = owner ? "Unleash" : PREVIEW_LABEL;
    mountFire(sections.fire, { id, name, kit, onRecord: () => { if (manual) manual.refresh(); }, today: owner,
      avatar: owner ? { look: kit.look || lookFor(kit.root_id || id), id, vibe } : null,
      onDone: (out) => { if (onUnleashed && out && out.placed_now) onUnleashed(out); } });
    // the owner's hound menu: Unleash runs the preview panel just below it; the two rites are dog-rites.js
    if (sections.rites) {
      mountRites(sections.rites, { id, name, kit, unleash: () => {
        const btn = q("fire-btn");
        if (sections.fire.scrollIntoView) sections.fire.scrollIntoView({ behavior: "smooth", block: "start" });
        if (btn && !btn.hasAttribute("disabled")) btn.click();
      } });
    }
    // the same dogs that can be unleashed can be backtested (house dogs and builder dogs: the rule runs on demand)
    if (sections.backtest) mountBacktest(sections.backtest, { id, name });
  }
  jobs.push(bootAsk(sections.ask, { id, name, gematria: !!kit.gematria }));
  jobs.push(mountFans(sections.fans, { id, name, kit, hound }));
  if (kit.can_customize && sections.locker) {
    mountLocker(sections.locker, { id, name, kit, vibe, onSaved: (look) => applyHeaderBadge(look, name, false, { id, root_id: kit.root_id, vibe, version_no: kit.version_no, pose: poseOfHound(hound) }) });
  }
  await Promise.all(jobs.map((p) => Promise.resolve(p).catch(() => null)));
  return kit;
}
