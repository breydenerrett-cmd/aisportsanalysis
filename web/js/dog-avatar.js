/**
 * The dog badge entry points. The drawing itself is the character rig in dog-rig.js (`renderDog`); the look tables and the
 * whitelist live in dog-look.js. This file keeps the names the pages already import (COATS, cleanLook, dogBadge, ...) so
 * every existing caller works, and the two helpers that fetch saved looks for a list of dogs.
 *
 * THE LOOK IS A SET OF CHOICES, NEVER MARKUP. `look` is the whitelisted JSON the server validated
 * (src/hounds/interact/look.py): coat, eyes, bg, head, face, neck, body, number, style, breed. A key the tables do not know falls back to
 * the default, so nothing a server sends can inject a colour string or a node. tests/test_hounds_interact_web.py holds the
 * key lists to the server's.
 *
 * `dogBadge(look, opts)` returns an <svg> element (decorative by default: the dog's name is always written beside it).
 * `hydrateAvatars(root)` swaps the monogram for the badge wherever a page marks an element with
 * `data-dog-avatar="<hound id>"`, fetching the looks for all of them in one request.
 */

import { apiGet } from "./api.js";
import { s as svgNode } from "./hounds-core.js";
import { COATS, EYES, BACKGROUNDS, HEAD, FACE, NECK, BODY, DEFAULT_LOOK, cleanLook, lookFor, randomLook, STYLES, BREED_CHOICES } from "./dog-look.js";
import { dogSvg, renderDog, setPose, flashPose, breedFor, breedLabel, breedOfName, BREED_LABELS, poseOfPick, POSES, BREEDS, STYLE_LABELS, EXPRESSIONS, expressionOf, anchorsFor, versionTier, cleanVersion, tierOf, newParts } from "./dog-rig.js";

export { COATS, EYES, BACKGROUNDS, HEAD, FACE, NECK, BODY, DEFAULT_LOOK, cleanLook, lookFor, randomLook, STYLES, BREED_CHOICES };
export { versionTier, cleanVersion, tierOf, newParts };
export { renderDog, setPose, flashPose, breedFor, breedLabel, breedOfName, BREED_LABELS, poseOfPick, POSES, BREEDS, STYLE_LABELS, EXPRESSIONS, expressionOf, anchorsFor };

/**
 * The badge as an SVG element. `size` is the pixel width and height; `mood` is the pose (idle, happy, sad or the old word
 * slump, thinking, celebrate); `id` / `vibe` / `breed` choose the silhouette (see breedFor in dog-rig.js); `version` is the hound's
 * version number (v2 and later wear their tier: dog-tiers.js).
 */
export function dogBadge(rawLook, { size = 56, label = "", decorative = true, mood = "idle", id, vibe, breed, name, version } = {}) {
  return dogSvg(rawLook, { size, label, decorative, mood, pose: mood, id, vibe, breed, name, version });
}

/**
 * The pose a dog's own recorded results earn: its last pick (a win is happy, a loss is sad), else a streak of two or more
 * in the leaderboard's form block (W is happy, L is sad), else idle. It only restates a result the page already shows.
 */
export function poseOfHound(dog) {
  const d = dog || {};
  if (d.last_pick && d.last_pick.result) return poseOfPick(d.last_pick.result);
  const streak = d.form && d.form.streak;
  if (streak && streak.length >= 2) return streak.kind === "W" ? "happy" : streak.kind === "L" ? "sad" : "idle";
  return "idle";
}

/** The Learner (category / family "learner", id "learner") has its own mascot, web/img/learner-hound.svg: a hound head in a graduation cap.
 * Every other hound is drawn by the rig, unchanged. */
export function isLearner(dog) {
  const d = dog || {};
  const word = (v) => String(v == null ? "" : v).trim().toLowerCase();
  return word(d.category) === "learner" || word(d.family) === "learner" || word(d.id) === "learner" || word(d.root_id) === "learner";
}

/** The Learner's art as the same kind of node dogFace hands back for any hound: an <svg class="dk-badge"> that setPose / flashPose can touch. */
export function learnerFace({ size = 32, pose = "idle", label = "", decorative = true } = {}) {
  let href = "img/learner-hound.svg";
  try { href = new URL("../img/learner-hound.svg", import.meta.url).href; } catch (err) { /* a page one level up from js/ finds it at img/ */ }
  const attrs = { class: "dk-badge dk-badge--learner", viewBox: "0 0 128 128", width: size, height: size, focusable: "false",
    "data-pose": pose, "data-mood": pose, "data-hound": "learner" };
  if (decorative === false) { attrs.role = "img"; attrs["aria-label"] = label || "The Learner"; } else attrs["aria-hidden"] = "true";
  return svgNode("svg", attrs, [svgNode("image", { href, x: 0, y: 0, width: 128, height: 128, preserveAspectRatio: "xMidYMid slice" })]);
}

/** A dog's face for a list row or card: its saved look, else the default look its id picks, and the breed its vibe picks. */
export function dogFace(dog, { size = 32, pose = "idle", label = "", decorative = true } = {}) {
  const d = dog || {};
  if (isLearner(d)) return learnerFace({ size, pose, label, decorative });
  const vibe = d.persona && d.persona.vibe ? d.persona.vibe : d.vibe;
  // a hound's version is real data (version_no on a kennel row, a leaderboard row and the kit): v2 and later wear their tier. The breed is
  // the lineage's, not the version's: a new version has a new id, and a trained hound must stay the breed it was (root_id; a v1's is its id).
  return dogSvg(d.look || lookFor(d.root_id || d.id || d.name), { size, pose, mood: pose, id: d.root_id || d.id, name: d.name, vibe, label, decorative, version: d.version_no });
}

// ---- looks for lists of dogs -----------------------------------------------------------------------

/** {dog id: look} for the builder dogs among `ids` that have saved one. Never throws: no looks is an empty map. */
export async function fetchLooks(ids) {
  const wanted = [...new Set((ids || []).filter(Boolean))].slice(0, 40);
  if (!wanted.length) return {};
  try {
    const data = await apiGet(`/hounds/looks?ids=${wanted.map(encodeURIComponent).join(",")}`);
    return data && typeof data.looks === "object" && data.looks ? data.looks : {};
  } catch (err) {
    return {};
  }
}

/** Swap the monogram for the badge on every element under `root` marked `data-dog-avatar="<id>"`. */
export async function hydrateAvatars(root = document, { size } = {}) {
  const nodes = root.querySelectorAll("[data-dog-avatar]");
  if (!nodes.length) return 0;
  const looks = await fetchLooks(nodes.map((n) => n.getAttribute("data-dog-avatar")));
  let swapped = 0;
  for (const node of nodes) {
    const look = looks[node.getAttribute("data-dog-avatar")];
    const parent = node.parentNode;
    if (!look || !parent) continue;
    const px = size || Number(node.getAttribute("data-dog-size")) || 36;
    const badge = dogBadge(look, { size: px });
    badge.setAttribute("data-dog-avatar", node.getAttribute("data-dog-avatar"));
    parent.insertBefore ? parent.insertBefore(badge, node) : parent.appendChild(badge);
    parent.removeChild(node);
    swapped += 1;
  }
  return swapped;
}
