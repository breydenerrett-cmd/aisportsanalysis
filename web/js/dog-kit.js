/**
 * The dog kit on web/hound.html: Fire now, Ask, the manual picks, what fans think and training, and (for a builder
 * dog's owner) the locker room. `bootDogKit(hound)` is called by hounds-detail.js once the model has loaded.
 *
 * ONE REQUEST DECIDES WHAT THIS VISITOR SEES: GET /hounds/{id}/kit says whether they own the dog, whether it can be
 * fired, whether a manual pick can be recorded, and its saved look. The server checks again on every write, so the
 * buttons are a convenience, not the gate. A server without the kit (404) or one that is down leaves the page exactly
 * as it was: every panel here starts hidden and shows itself only with something real to show.
 *
 * The header's monogram is swapped for the dog's badge when its owner has dressed it (builder dogs only); every
 * other model keeps its initials badge.
 */

import { get } from "./dog-common.js";
import { dogBadge, DEFAULT_LOOK } from "./dog-avatar.js";
import { poseOfHound } from "./dog-avatar.js";
import { mountFire } from "./dog-fire.js";
import { bootAsk } from "./dog-ask.js";
import { mountFans } from "./dog-feedback.js";
import { mountManual } from "./dog-manual.js";
import { mountLocker } from "./dog-locker.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

/** Put the dog's badge in the header where the monogram is. Returns true when it swapped. */
export function applyHeaderBadge(look, name, muted = false, dog = {}) {
  const old = document.querySelector(".hd-modelhead .hd-mono") || document.querySelector(".hd-modelhead .dk-badge");
  if (!old || !look) return false;
  const badge = dogBadge(look, { size: 84, id: dog.id, vibe: dog.vibe, mood: muted ? "sad" : (dog.pose || "idle") });
  badge.setAttribute("data-hook", "header-badge");
  if (muted) badge.setAttribute("style", "opacity:.55");
  const parent = old.parentNode;
  if (parent.insertBefore) parent.insertBefore(badge, old); else parent.appendChild(badge);
  parent.removeChild(old);
  return true;
}

export async function bootDogKit(hound) {
  const id = hound && hound.id;
  if (!id) return null;
  const sections = {
    fire: q("dog-fire-section"), ask: q("dog-ask-section"), manual: q("dog-manual-section"),
    fans: q("dog-fans-section"), locker: q("dog-locker-section"),
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
  if (kit.look || hound.kind === "user") applyHeaderBadge(kit.look || DEFAULT_LOOK, name, hound.status === "retired", { id, vibe, pose: poseOfHound(hound) });
  let manual = null;
  const jobs = [];
  if (hound.kind === "user" && sections.manual) {
    jobs.push(mountManual(sections.manual, { id, kit }).then((m) => { manual = m; }));
  }
  if (kit.can_fire) {
    mountFire(sections.fire, { id, name, kit, onRecord: () => { if (manual) manual.refresh(); } });
  }
  jobs.push(bootAsk(sections.ask, { id, name }));
  jobs.push(mountFans(sections.fans, { id, name, kit, hound }));
  if (kit.can_customize && sections.locker) {
    mountLocker(sections.locker, { id, name, kit, vibe, onSaved: (look) => applyHeaderBadge(look, name, false, { id, vibe, pose: poseOfHound(hound) }) });
  }
  await Promise.all(jobs.map((p) => Promise.resolve(p).catch(() => null)));
  return kit;
}
