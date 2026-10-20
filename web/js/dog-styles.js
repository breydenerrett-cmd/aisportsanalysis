/**
 * THE THREE ART STYLES of the hound illustrations, picked in the locker room (look.style).
 *
 *   mascot  bold sports-logo craft: a thick near-black outline, hard cel shadows, a crisp rim light, a sunburst behind the dog.
 *   street  gritty: a slimmer outline, the same hard shadows plus a grain over the tile, spray-paint splats and drips in the
 *           corners, a heavier chain and a hoodie that wants to be worn.
 *   elite   clean and premium: a hairline outline in a dark tone of the coat, smooth gradient shading and a soft rim, metallic
 *           gold and silver on every accessory, a metal ring around the tile.
 *
 * A style is a spec the toolkit (dog-art.js) and the accessories (dog-accessories.js) read; the drawing of a breed is written
 * once and comes out in all three. The whitelist is `STYLES`: dog-look.js cleans `look.style` against it and the server
 * (src/hounds/interact/look.py) holds the same list; tests/test_hounds_interact_web.py keeps the two together.
 */

import { INK, mix } from "./dog-art.js";
import { STYLES, DEFAULT_STYLE } from "./dog-look.js";

export { STYLES, DEFAULT_STYLE };
export const STYLE_LABELS = { mascot: "Mascot", street: "Street", elite: "Elite" };
export const STYLE_BLURBS = {
  mascot: "Bold logo, thick outline",
  street: "Gritty, spray-paint accents",
  elite: "Clean, premium, metallic",
};

const SPEC = {
  mascot: {
    id: "mascot", ow: 3.2, owSmall: 4.2, shadeId: "lh-sh-cel", rimId: "lh-rim-hard", outline: () => INK,
    burst: true, grit: false, spray: false, metal: false, ring: false, chainW: 3.4, hood: "#2C3442", hoodLight: "#3B4455", jersey: "#F2F4F8",
  },
  street: {
    id: "street", ow: 2.5, owSmall: 3.6, shadeId: "lh-sh-cel", rimId: "lh-rim-hard", outline: () => INK,
    burst: false, grit: true, spray: true, metal: false, ring: false, chainW: 4.6, hood: "#15181E", hoodLight: "#23272F", jersey: "#E7E9EE",
  },
  elite: {
    id: "elite", ow: 1.2, owSmall: 2.6, shadeId: "lh-sh-soft", rimId: "lh-rim-soft", outline: (c) => mix(c.shade, INK, 0.62),
    burst: false, grit: false, spray: false, metal: true, ring: true, chainW: 2.8, hood: "#252B36", hoodLight: "#323A48", jersey: "#F7F8FB",
  },
};

/** The whitelisted style name, else the default. */
export function cleanStyle(name) {
  return typeof name === "string" && STYLES.includes(name) ? name : DEFAULT_STYLE;
}

export function styleSpec(name) {
  return SPEC[cleanStyle(name)];
}
