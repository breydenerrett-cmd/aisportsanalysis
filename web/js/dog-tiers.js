/**
 * THE VERSION TIERS: what a hound's version number looks like, everywhere the hound is drawn.
 *
 * A hound's version (v1, v2, v3 ...) is real data: Send to training and the builder's "save as a new version" each make the next
 * one. The art shows it so a v3 looks like a v3 on the kennel card, the hound page, the Kennel Room, the leaderboard and in the
 * training evolution (dog-evolve.js). The look is a pure function of the version number: no clock, no random, no look key, no
 * network. The same number always draws the same pieces, in every art style and at every size.
 *
 *   v1   the hound as it always was; nothing is added.
 *   v2   BRONZE    the HOUND wears a bandana in the metal's colour; the tile gets a bronze frame, a "v2" rank plate (top left) and one chevron.
 *   v3   SILVER    the hound also wears a vest with a chest strap, a bolder outline and a confident brow; a double silver frame, a plate,
 *                  two chevrons, a star mark between the eyes, a soft halo.
 *   v4   GOLD      shoulder plates and softly glowing eyes on top of that; a double gold frame with corner studs, three chevrons, a halo.
 *   v5+  PLATINUM  a mantle (a cape over the shoulders) and an aura round the hound; a bright frame, four chevrons, a twinkle either side.
 *
 * It is the same hound grown up: the breed, coat and eyes never change, only what it wears and how it is drawn. Every piece is placed from
 * the breed's anchors (dog-breeds.js), so it lines up on a Greyhound's blade and a Mastiff's block alike. The gear is built so each tier
 * also changes the hound's OUTLINE (the bandana's tails, the shoulder plates, the mantle's wings), because the training evolution
 * shows the old and new hound as white silhouettes and the morph has to read there.
 *
 * Versions past 5 keep the platinum look and the plate keeps counting ("v12"). A version that is not a whole number of at least
 * 1 (nothing was sent, a house hound) is v1: nothing is added and nothing is guessed.
 *
 * Everything here is built from the toolkit's own pieces (dog-art.js) with createElementNS only. Colours are the constants in
 * TIERS or `url(#lh-...)` gradients from dog-defs.js, never a value from the server. A small badge (44px or less) keeps the
 * frame, the plate block and the chevrons, and drops the numeral and the fine pieces.
 */

import { INK, n, path, grp, ell, f, mix } from "./dog-art.js";
import { SPARKLE } from "./dog-defs.js";
import { gearShapes, auraShapes } from "./dog-gear.js";

export const MAX_TIER = 5;

/**
 * The metals. `flat` is used by the Mascot and Street styles (flat colour, thick outline), `grad` by Elite (the gradients in
 * dog-defs.js). `name` is what the upgrade card calls the tier.
 */
export const TIERS = {
  1: { tier: 1, name: "Base" },
  2: { tier: 2, name: "Bronze", flat: "#C98448", lit: "#EDB67F", dark: "#6E3F18", grad: "url(#lh-bronze)", chevrons: 1, rings: 1, studs: false, mark: false, halo: 0, twinkle: false,
    vest: false, bold: false, pads: false, glow: false, mantle: false, aura: false },
  3: { tier: 3, name: "Silver", flat: "#C9D0DA", lit: "#F4F7FB", dark: "#6B7685", grad: "url(#lh-silver)", chevrons: 2, rings: 2, studs: false, mark: true, halo: 1, twinkle: false,
    vest: true, bold: true, pads: false, glow: false, mantle: false, aura: false },
  4: { tier: 4, name: "Gold", flat: "#E0B24A", lit: "#FFF0B8", dark: "#8A6A1F", grad: "url(#lh-gold)", chevrons: 3, rings: 2, studs: true, mark: true, halo: 2, twinkle: false,
    vest: true, bold: true, pads: true, glow: true, mantle: false, aura: false },
  5: { tier: 5, name: "Platinum", flat: "#BFE7F2", lit: "#FFFFFF", dark: "#4C8CA0", grad: "url(#lh-platinum)", chevrons: 4, rings: 2, studs: true, mark: true, halo: 2, twinkle: true,
    vest: true, bold: true, pads: true, glow: true, mantle: true, aura: true },
};

/** The whole-number version a value stands for, or 1. */
export function cleanVersion(version) {
  const v = typeof version === "string" && /^\d{1,3}$/.test(version.trim()) ? Number(version) : version;
  return Number.isInteger(v) && v >= 1 && v <= 999 ? v : 1;
}

/** The tier (1 to 5) of a version. */
export function tierOf(version) {
  return Math.min(MAX_TIER, cleanVersion(version));
}

/**
 * What a version looks like, as plain data: { version, tier, name, plate, chevrons, rings, studs, mark, halo, twinkle, bandana, vest, bold,
 * pads, glow, mantle, aura, parts }. `parts` is the list of words the upgrade card shows ("Bronze bandana", "Vest", ...), in the order
 * they appear: what the hound wears first, then the tile.
 */
export function versionTier(version) {
  const v = cleanVersion(version);
  const t = TIERS[tierOf(v)];
  const none = { plate: false, chevrons: 0, rings: 0, studs: false, mark: false, halo: 0, twinkle: false, bandana: false, vest: false, bold: false, pads: false, glow: false, mantle: false, aura: false };
  if (t.tier === 1) return Object.assign({ version: v, tier: 1, name: t.name, parts: [] }, none);
  const parts = [`${t.name} bandana`];
  if (t.vest) parts.push("Vest");
  if (t.bold) parts.push("Bold brow");
  if (t.pads) parts.push("Shoulder plates");
  if (t.glow) parts.push("Glowing eyes");
  if (t.mantle) parts.push("Mantle");
  if (t.aura) parts.push("Aura");
  parts.push(`${t.name} frame`, `Rank plate v${v}`, t.chevrons === 1 ? "1 chevron" : `${t.chevrons} chevrons`);
  if (t.mark) parts.push("Star mark");
  if (t.halo) parts.push("Halo");
  if (t.twinkle) parts.push("Twinkle");
  return {
    version: v, tier: t.tier, name: t.name, plate: true, chevrons: t.chevrons, rings: t.rings, studs: t.studs, mark: t.mark, halo: t.halo, twinkle: t.twinkle,
    bandana: true, vest: t.vest, bold: t.bold, pads: t.pads, glow: t.glow, mantle: t.mantle, aura: t.aura, parts,
  };
}

/** What changed between two versions' looks, in the same words: the parts the newer one has that the older did not. */
export function newParts(from, to) {
  const a = new Set(versionTier(from).parts);
  return versionTier(to).parts.filter((p) => !a.has(p));
}

const metal = (t, st) => (st && st.metal ? t.grad : t.flat);

/** The collar band colour for a tier (the default collar reads it); null at v1 so the green band stays. */
export function collarFor(version, st) {
  const v = versionTier(version);
  return v.tier > 1 ? { band: metal(TIERS[v.tier], st), tag: TIERS[v.tier].lit, tagLine: TIERS[v.tier].dark } : null;
}

/** The art style a version is drawn in: from v3 the outline is a little bolder (the same hound, drawn with more confidence). */
export function tierStyle(version, st) {
  return versionTier(version).bold ? Object.assign({}, st, { ow: st.ow + 0.35, owSmall: st.owSmall + 0.25 }) : st;
}

/**
 * The pieces a version adds, as { back, mark, front, cape, gear, brow, eyes }:
 *   back   drawn behind the hound inside the tile (the halo, the aura)
 *   mark   drawn on the head (the star between the eyes)
 *   front  drawn over everything inside the tile (the plate, the chevrons, the studs) and the frame
 *   cape, gear, brow, eyes   what the hound wears (dog-gear.js): behind the torso, over it, on the head, inside the eyes group
 * `a` is the breed's anchors (dog-breeds.js), `K` the kit (dog-art.js `makeKit`), `st` the art style, `geo` the breed's landmarks (its bulk).
 */
export function tierShapes(version, a, K, st, geo) {
  const v = versionTier(version);
  if (v.tier === 1) return { back: [], mark: [], front: [], cape: [], gear: [], brow: [], eyes: [], tier: v };
  const T = TIERS[v.tier];
  const fill = metal(T, st);
  const small = K.small;
  const out = Object.assign({ back: [], mark: [], front: [], tier: v }, gearShapes(v, T, fill, a, K, geo));
  if (v.aura) out.back.push(auraShapes(T, K));

  // the halo behind the hound: a wide soft ring of the metal, so the tile glows from the middle
  if (v.halo) {
    out.back.push(grp("dk-tier dk-tier--halo", [
      ell(60, 64, 54, 56, T.flat, { opacity: v.halo === 2 ? ".2" : ".13" }),
      ell(60, 64, 40, 42, T.lit, { opacity: v.halo === 2 ? ".1" : ".06" }),
    ]));
  }

  // the star between the eyes
  if (v.mark && !small && a && a.eyes) {
    const my = a.eyes.y - 1.5 * (a.eyes.eh || 3) - 3;
    out.mark.push(grp("dk-tier dk-tier--mark", [
      grp("", [path(SPARKLE, { fill: T.lit, stroke: T.dark, "stroke-width": 0.9, "stroke-linejoin": "round" })], { transform: `translate(60 ${f(my)}) scale(.62)` }),
    ]));
  }

  // the frame: one ring, or two, inside the tile border
  const ringW = small ? 3.6 : v.tier >= 4 ? 3 : 2.6;
  const ring = (inset, w, extra) => n("rect", Object.assign({
    class: "dk-tier__ring", x: f(inset), y: f(inset), width: f(120 - 2 * inset), height: f(120 - 2 * inset), rx: f(26 - inset), fill: "none",
    stroke: fill, "stroke-width": f(w), pathLength: 1,
  }, extra || {}));
  const pieces = [ring(3.4, ringW)];
  if (v.rings === 2 && !small) pieces.push(ring(7.2, 1.2, { stroke: T.lit, "stroke-opacity": 0.7, class: "dk-tier__ring dk-tier__ring--inner" }));
  // the outline of the frame, so it reads on a pale tile (drawn under the metal)
  pieces.unshift(n("rect", { class: "dk-tier__edge", x: f(3.4), y: f(3.4), width: f(113.2), height: f(113.2), rx: f(22.6), fill: "none", stroke: INK, "stroke-opacity": 0.55, "stroke-width": f(ringW + 1.6) }));
  if (v.studs && !small) {
    for (const [x, y] of [[14, 14], [106, 14], [14, 106], [106, 106]]) {
      pieces.push(n("circle", { class: "dk-tier__stud", cx: x, cy: y, r: 2.5, fill: T.lit, stroke: T.dark, "stroke-width": 0.9 }));
    }
  }
  out.front.push(grp("dk-tier dk-tier--frame", pieces));

  // the rank plate, top left: a chamfered tab with the version in it ("v2")
  const px = 8, py = 8, pw = small ? 21 : 27, ph = small ? 15 : 15;
  const plateD = `M${px + 3} ${py} H${px + pw} V${py + ph - 3} L${px + pw - 3} ${py + ph} H${px} V${py + 3} Z`;
  const plate = [
    path(plateD, { fill, stroke: INK, "stroke-width": f(Math.max(1, K.ow * 0.55)), "stroke-linejoin": "round" }),
    path(`M${px + 3} ${py + 1.6} H${px + pw - 1.6}`, { stroke: T.lit, "stroke-width": 1.1, "stroke-linecap": "round", opacity: 0.75 }),
  ];
  if (!small) {
    plate.push(n("text", {
      x: f(px + pw / 2), y: f(py + ph - 4), "text-anchor": "middle", "font-size": v.version >= 10 ? 8.4 : 9.6, "font-weight": 800,
      "font-family": "Instrument Sans, Arial, Helvetica, sans-serif", fill: INK, "data-vno": String(v.version),
    }, `v${v.version}`));
  }
  out.front.push(grp("dk-tier dk-tier--plate", plate));

  // the chevrons, top right: one per rank above the base, pointing up
  const chev = [];
  const cw = small ? 6.5 : 7.5;
  for (let i = 0; i < v.chevrons; i++) {
    const cy = 22 - i * (small ? 5.4 : 4.6);
    const d = `M${f(106 - cw)} ${f(cy)} L106 ${f(cy - cw * 0.62)} L${f(106 + cw)} ${f(cy)}`;
    chev.push(grp("dk-tier__chev", [
      path(d, { fill: "none", stroke: INK, "stroke-width": f(small ? 5.2 : 4.4), "stroke-linecap": "round", "stroke-linejoin": "round", opacity: 0.85 }),
      path(d, { fill: "none", stroke: fill, "stroke-width": f(small ? 3.2 : 2.6), "stroke-linecap": "round", "stroke-linejoin": "round" }),
    ], { style: `--c:${i}` }));
  }
  out.front.push(grp("dk-tier dk-tier--chevrons", chev));

  // a twinkle on either side of the head (platinum)
  if (v.twinkle && !small) {
    const spark = (x, y, s, i) => grp("", [path(SPARKLE, { class: `dk-spark dk-spark--${i}`, fill: "#FFFFFF" })], { transform: `translate(${x} ${y}) scale(${f(s / 12)})` });
    out.front.push(grp("dk-tier dk-tier--twinkle", [spark(24, 44, 9, 1), spark(97, 54, 8, 3)]));
  }
  return out;
}
