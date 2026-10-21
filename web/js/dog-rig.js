/**
 * THE HOUND CHARACTER RIG. One module draws every dog in the product (kennel cards, the studio, the model page header, small
 * leaderboard rows, the landing hero, the builder, the quiz): `renderDog(container, look, pose, opts)`.
 *
 *   look   the locker-room look JSON (coat, eyes, bg, head, face, neck, body, number, style, breed), cleaned against dog-look.js
 *   pose   idle | happy | sad | thinking | celebrate   ("slump" is the old name for sad; the expression names snarl, grin, focus
 *          and howl are accepted for sad, happy, thinking and celebrate)
 *   opts   { size, breed | vibe | id | name, label, decorative }
 *
 * THE DOGS ARE ILLUSTRATED HOUNDS in inline SVG, nothing raster, nothing fetched: confident, athletic, slightly menacing sports-mascot
 * heads with sharp brows, defined muzzles, ears with character, 2-3 tone shading and a rim light, in three art styles (Mascot,
 * Street, Elite: dog-styles.js). From the back: the tile (background and the style's decoration), a ground shadow, the body
 * (shoulders, hoodie or jersey), the neck pieces (default collar, spiked collar, bandana), the paws (they come up in `celebrate`),
 * the head group (ears, skull, muzzle, markings, nose, mouth, wrinkles, eyes and brow plates, the face and head pieces: sunglasses,
 * cap, headband, visor), the chain, then the pose props (nose crease glow, thought bars, sparkles, sound arcs).
 *
 * SHARED DEFS: the gradients, patterns and symbols live ONCE per page (dog-defs.js), not in every badge. A badge of 44px or less
 * is drawn at the small level of detail (a heavier outline, no overlays, no fine lines) so it reads at 32px; larger is full detail.
 *
 * POSES ARE ATTRIBUTES, NOT REDRAWS. Every pose's mouth, eyes, brows and prop is drawn once with a `dk-p--<pose>` class, and
 * css/lh.css shows the one that matches `data-pose`. `setPose(svg, pose)` flips the attribute. The breathing, the blink, the eye
 * glint, the ear flick, the bounce and the sparkles are CSS animations inside `prefers-reduced-motion: no-preference`; reduced
 * motion keeps the pose (an expression is information) and loses every movement. Nothing in this file schedules an animation.
 *
 * BREEDS: 33, chosen by the look's own `breed` (the owner's override), else a word in the dog's id or name, else its persona vibe,
 * else a stable hash of its id (over the original 25, so no existing dog changes breed). A breed is cosmetic and the server only
 * stores the whitelisted key.
 *
 * Built with createElementNS only (hounds-core's `s`), so the node test harness can run it. Every colour is a constant from
 * dog-look.js's tables or a mix of two of them; no look value ever reaches a style or markup string.
 */

import { clearNode } from "./hounds-core.js";
import { COATS, EYES, cleanLook, hashStr, DEFAULT_LOOK, LEGACY_BREEDS, BREED_CHOICES } from "./dog-look.js";
import { BREEDS, BREED_LABELS, buildBreed } from "./dog-breeds.js";
import { STYLES, STYLE_LABELS, STYLE_BLURBS, styleSpec } from "./dog-styles.js";
import { makeKit, n, path, grp, ell, f } from "./dog-art.js";
import { noseShapes, mouthShapes, eyeShapes, EXPRESSIONS, EXPRESSION_OF } from "./dog-face.js";
import { bodyShapes, neckPieces, headPiece, sunglasses, roundGlasses } from "./dog-accessories.js";
import { defsNode, ensureSharedDefs, SPARKLE } from "./dog-defs.js";
import { tierShapes, tierStyle, versionTier, cleanVersion, tierOf, newParts, TIERS, MAX_TIER } from "./dog-tiers.js";

export const POSES = ["idle", "happy", "sad", "thinking", "celebrate"];
export { versionTier, cleanVersion, tierOf, newParts, TIERS, MAX_TIER };
export { BREEDS, BREED_LABELS, STYLES, STYLE_LABELS, STYLE_BLURBS, EXPRESSIONS, EXPRESSION_OF, BREED_CHOICES };
export const ACCESSORY_LAYERS = ["sunglasses", "cap", "headband", "visor", "chain", "collar", "bandana", "hoodie", "jersey"];
export const VIBE_BREED = { grinder: "bulldog", nerd: "schnauzer", degen: "husky", chaos: "mutt", psychic: "hound" };
/** The expression names, and the pose each stands for. */
export const POSE_ALIAS = { slump: "sad", snarl: "sad", grin: "happy", focus: "thinking", howl: "celebrate", cheer: "celebrate" };
/** The small level of detail: a badge this size or smaller drops the overlays and the fine lines and draws a heavier outline. */
export const SMALL_PX = 44;

const ACCENT = "#2FD07A";

// ---- choosing a pose and a breed -------------------------------------------------------------------------------

/** "slump" (the old word), the expression names and anything unknown become a pose the rig knows. */
export function cleanPose(pose) {
  if (POSE_ALIAS[pose]) return POSE_ALIAS[pose];
  return POSES.includes(pose) ? pose : "idle";
}

/** The expression a pose draws: idle, snarl, grin, focus or howl. */
export function expressionOf(pose) {
  return EXPRESSION_OF[cleanPose(pose)];
}

/**
 * A word in a dog's id or name that names its breed. "Chalk Chihuahua" is a chihuahua and "Jet-Lag Jack" a Jack Russell, whatever
 * its persona vibe; a label can never say "Bulldog" over a drawing of something else, because the label is read from the same
 * mapping. Words that are not breeds fall through to the vibe, then to a hash of the id.
 */
export const NAME_BREED = {
  chihuahua: "chihuahua", collie: "collie", corgi: "corgi", dalmatian: "dalmatian", greyhound: "greyhound", bulldog: "bulldog",
  husky: "husky", schnauzer: "schnauzer", basset: "basset", bloodhound: "bloodhound", beagle: "beagle", setter: "setter",
  spaniel: "spaniel", terrier: "terrier", pointer: "pointer", whippet: "whippet", kelpie: "kelpie", lab: "labrador", labrador: "labrador",
  newfie: "newfoundland", newfoundland: "newfoundland", retriever: "retriever", poodle: "poodle", professor: "poodle",
  shepherd: "shepherd", leader: "shepherd", jack: "jackrussell", hank: "hound", hound: "hound", mutt: "mutt",
  doberman: "doberman", dobie: "doberman", rottweiler: "rottweiler", rottie: "rottweiler", pitbull: "pitbull", staffy: "pitbull",
  wolfhound: "wolfhound", boxer: "boxer", mastiff: "mastiff", shiba: "shiba", malinois: "malinois",
};

/** The breed a dog's id or name spells out, or "". */
export function breedOfName(dog) {
  const d = dog && typeof dog === "object" ? dog : { id: dog };
  const words = `${d.id || ""} ${d.name || ""}`.toLowerCase().split(/[^a-z0-9]+/);
  for (const w of words) if (NAME_BREED[w]) return NAME_BREED[w];
  return "";
}

/**
 * The breed for a dog: the look's own override (the owner picked one in the locker room), else an explicit breed, else the one its
 * name spells, else its persona vibe, else a stable pick from its id (over the original 25 drawings, so it never changes).
 * `dog` may be an id string.
 */
export function breedFor(dog) {
  const d = dog && typeof dog === "object" ? dog : { id: dog };
  const own = d.look && typeof d.look === "object" ? d.look.breed : "";
  if (own && own !== "auto" && BREEDS.includes(own)) return own;
  if (BREEDS.includes(d.breed)) return d.breed;
  const named = breedOfName(d);
  if (named) return named;
  const vibe = d.vibe || (d.persona && d.persona.vibe) || "";
  if (VIBE_BREED[vibe]) return VIBE_BREED[vibe];
  const key = d.id || d.name;
  return key ? LEGACY_BREEDS[hashStr(key) % LEGACY_BREEDS.length] : "retriever";
}

/** The label shown for a breed: always the name of the drawing. */
export function breedLabel(breed) {
  return BREED_LABELS[breed] || BREED_LABELS[breedFor(breed)] || "Dog";
}

/** Traits that belong to one dog, not its breed: the Professor wears glasses. */
export function traitsFor(dog) {
  const d = dog && typeof dog === "object" ? dog : { id: dog };
  const words = `${d.id || ""} ${d.name || ""}`.toLowerCase().split(/[^a-z0-9]+/);
  return { glasses: words.includes("professor") };
}

/** The pose a dog's last pick earns: a win is happy, a loss is sad, anything else (or nothing) is idle. */
export function poseOfPick(result) {
  return result === "won" ? "happy" : result === "lost" ? "sad" : "idle";
}

/** The accessory anchors of a breed (for the tests and for anything that wants to line a piece up with a head). */
export function anchorsFor(breed) {
  const name = BREEDS.includes(breed) ? breed : breedFor(breed);
  const coat = COATS.tan;
  return buildBreed(name, coat, makeKit({ style: styleSpec("mascot"), coat, lod: "l" })).anchors;
}

const use = (href, attrs) => n("use", Object.assign({ href: `#${href}` }, attrs));
/** A four-point sparkle centred on (x, y), `s` wide: a fixed group places it, the path inside is what the CSS twinkles about its own centre. */
const spark = (x, y, s, fill, i) => grp("", [path(SPARKLE, { class: `dk-spark dk-spark--${i}`, fill })], { transform: `translate(${f(x)} ${f(y)}) scale(${f(s / 12)})` });

// ---- the pose props, the tile decoration and the paws ----------------------------------------------------------------

function propShapes(geo) {
  const sparks = [[18, 30, 12, "#E0B24A"], [104, 24, 11, "#EEF1F5"], [108, 64, 11, ACCENT], [12, 70, 11, "#8FB8FF"]];
  const gx = 60 + geo.mw * 0.6, gy = geo.my + 1;
  return [
    n("rect", { class: "dk-p dk-p--rage", x: 0, y: 0, width: 120, height: 120, rx: 26, fill: "url(#lh-vig)" }),
    grp("dk-p dk-p--thought", [
      path("M93 30 l3 3 l-3 3 l-3 -3 Z", { class: "dk-dot dk-dot--1", fill: "#EEF1F5" }),
      path("M100 20 l4 4 l-4 4 l-4 -4 Z", { class: "dk-dot dk-dot--2", fill: "#EEF1F5" }),
      path("M108 8 l5.4 5.4 l-5.4 5.4 l-5.4 -5.4 Z", { class: "dk-dot dk-dot--3", fill: "#EEF1F5" }),
    ]),
    grp("dk-p dk-p--gleam", [spark(gx, gy - 1, 8, "#FFFFFF", 5)]),
    grp("dk-p dk-p--sparkles", sparks.map(([x, y, s, col], i) => spark(x, y, s, col, i + 1))),
    grp("dk-p dk-p--sound", [
      use("lh-sound", { class: "dk-sound dk-sound--l", x: 3, y: 26, width: 14, height: 26, color: "#FFFFFF", transform: "translate(20 0) scale(-1 1)" }),
      use("lh-sound", { class: "dk-sound dk-sound--r", x: 103, y: 26, width: 14, height: 26, color: "#FFFFFF" }),
    ]),
  ];
}

function decorShapes(st, K) {
  const out = [];
  if (st.burst) out.push(use("lh-burst", { class: "dk-burst", x: 0, y: 0, width: 120, height: 120 }));
  if (st.grit) {
    out.push(n("rect", { class: "dk-grit", x: 0, y: 0, width: 120, height: 120, fill: "url(#lh-grit)", opacity: ".8" }));
    if (!K.small) {
      out.push(use("lh-splat", { class: "dk-spray", x: -3, y: -2, width: 32, height: 32, color: "#FF4FA3", opacity: ".9" }));
      out.push(use("lh-splat", { class: "dk-spray", x: 92, y: 80, width: 30, height: 30, color: "#27D3F5", opacity: ".85", transform: "rotate(160 107 95)" }));
      out.push(path("M8 112 Q30 104 52 110", { class: "dk-spray", fill: "none", stroke: "#C6F432", "stroke-width": 3, "stroke-linecap": "round", opacity: ".8" }));
    }
  }
  return out;
}

function pawShapes(coat, K) {
  const paw = (side) => grp(`dk-paw dk-paw--${side < 0 ? "l" : "r"}`, [
    ...K.solid(`M${60 + side * 41 - 10} 112 C${60 + side * 41 - 12} 94 ${60 + side * 41 - 6} 86 ${60 + side * 41} 86 C${60 + side * 41 + 6} 86 ${60 + side * 41 + 12} 94 ${60 + side * 41 + 10} 112 Z`, coat.base, { rim: true }),
    K.fine(path(`M${60 + side * 41 - 4} 90 V97 M${60 + side * 41 + 4} 90 V97`, { stroke: coat.shade, "stroke-width": 1.4, "stroke-linecap": "round", opacity: ".7" })),
  ]);
  return grp("dk-paws", [paw(-1), paw(1)]);
}

// ---- the dog ---------------------------------------------------------------------------------------------------

/** The breed a badge draws: the look's override, else the explicit option, else what the dog's name, vibe and id say. */
function breedOfBadge(look, opts) {
  if (look.breed && look.breed !== "auto" && BREEDS.includes(look.breed)) return look.breed;
  return BREEDS.includes(opts.breed) ? opts.breed : breedFor(opts);
}

/**
 * The dog as an <svg> element. `opts`: size (px, default 56), breed | vibe | id | name (the breed), label + decorative (accessibility),
 * pose (default idle). The svg carries data-pose (the canonical pose), data-mood (the name asked for), data-expr (the expression),
 * data-breed, data-style, data-lod and the data-* keys of the look.
 */
export function dogSvg(rawLook, opts = {}) {
  const look = cleanLook(rawLook);
  const version = cleanVersion(opts.version);
  const pose = cleanPose(opts.pose || opts.mood);
  const breedName = breedOfBadge(look, opts);
  const coat0 = COATS[look.coat];
  const st = styleSpec(look.style);
  const size = opts.size || 56;
  const lod = size <= SMALL_PX ? "s" : "l";
  const K = makeKit({ style: tierStyle(version, st), coat: coat0, lod });
  const built = buildBreed(breedName, coat0, K);
  const coat = built.coat || coat0;
  const geo = built.geo, a = built.anchors;
  const shared = ensureSharedDefs();
  const eyeColor = EYES[look.eyes];

  const tier = tierShapes(version, a, K, st, geo);
  const mouths = mouthShapes(geo, K), eyes = eyeShapes(geo, K, coat, eyeColor);
  const face = [
    ...noseShapes(geo, K, coat),
    ...Object.entries(mouths).map(([name, shapes]) => grp(`dk-p dk-p--mouth dk-p--${name}`, shapes.filter(Boolean))),
    ...built.front,
    eyes.sockets,
    grp("dk-eyes", [...tier.eyes, ...eyes.groups]),
  ];
  if (look.face === "sunglasses") face.push(sunglasses(a, K, st));
  else if (traitsFor(opts).glasses) face.push(roundGlasses(a, K));
  const hat = headPiece(look, a, K, st);
  if (hat) face.push(hat);
  // the star a v3 or later hound wears between the eyes sits under the cap and over the markings
  face.push(...tier.mark, ...tier.brow);

  const bodyBits = bodyShapes(look, coat, a, K, st, geo);
  const neck = neckPieces(look, a, K, st, coat, version);

  const kids = [
    shared ? null : defsNode(),
    n("rect", { class: "dk-tile", x: 0.6, y: 0.6, width: 118.8, height: 118.8, rx: 26, fill: `url(#lh-bg-${look.bg})`, stroke: "#FFFFFF", "stroke-opacity": 0.14 }),
    grp("dk-scene", [
      n("rect", { class: "dk-glow", x: 0, y: 0, width: 120, height: 120, rx: 26, fill: "url(#lh-glow)" }),
      // the tile's clip holds still; the dog inside it (dk-clip) is what bounces in the howl, and the sunburst and the grain stay put
      grp("", [
        ...decorShapes(st, K),
        ...tier.back,
        grp("dk-clip", [
          ell(60, 119, 46, 6, "#000000", { class: "dk-shadow", opacity: ".25" }),
          grp("dk-body", [...tier.cape, ...bodyBits.body, ...neck.behind, ...(built.ruff ? [] : tier.gear)]),
          pawShapes(coat, K),
          // a breed whose ruff is drawn with the head (the Collie) has what it wears drawn over the ruff, under the face
          grp("dk-head", [...built.back, ...(built.ruff ? tier.gear : []), ...built.head, ...face]),
          ...neck.front,
          bodyBits.number,
        ]),
        ...tier.front,
      ], { "clip-path": "url(#lh-tile-clip)" }),
      st.ring ? n("rect", { class: "dk-ring", x: 1.6, y: 1.6, width: 116.8, height: 116.8, rx: 24.6, fill: "none", stroke: "url(#lh-ring)", "stroke-width": 1.8 }) : null,
      ...propShapes(geo),
    ]),
  ];
  const attrs = {
    class: "dk-badge", viewBox: "0 0 120 120", width: size, height: size, focusable: "false", "data-pose": pose,
    "data-mood": opts.mood || pose, "data-expr": EXPRESSION_OF[pose], "data-breed": breedName, "data-style": look.style, "data-lod": lod,
    "data-vno": version, "data-tier": tierOf(version), "data-coat": look.coat, "data-bg": look.bg, "data-head": look.head, "data-face": look.face, "data-neck": look.neck, "data-body": look.body,
  };
  if (opts.decorative === false) { attrs.role = "img"; attrs["aria-label"] = opts.label || "Dog"; } else attrs["aria-hidden"] = "true";
  return n("svg", attrs, kids);
}

/**
 * THE ONE ENTRY POINT. Draws the dog into `container` (replacing what was there) and returns the svg.
 *   renderDog(el, look, "happy", { size: 96, id: dog.id, vibe: dog.persona && dog.persona.vibe })
 */
export function renderDog(container, look, pose = "idle", opts = {}) {
  const svg = dogSvg(look, Object.assign({}, opts, { pose }));
  if (container) { clearNode(container); container.appendChild(svg); }
  return svg;
}

/** Change a drawn dog's pose in place (a CSS state change: nothing is redrawn). Returns the pose it settled on. */
export function setPose(svg, pose) {
  const next = cleanPose(pose);
  if (svg && svg.setAttribute) {
    svg.setAttribute("data-pose", next); svg.setAttribute("data-mood", pose || next); svg.setAttribute("data-expr", EXPRESSION_OF[next]);
  }
  return next;
}

/** A pose for a moment, then back: the new dog and the recorded pick call this. `restore` defaults to the pose it had. */
export function flashPose(svg, pose, ms = 1800, restore) {
  if (!svg || !svg.getAttribute) return null;
  const before = restore || svg.getAttribute("data-pose") || "idle";
  setPose(svg, pose);
  if (typeof setTimeout === "function") setTimeout(() => setPose(svg, before), ms);
  return before;
}

export { DEFAULT_LOOK };
