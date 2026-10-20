/**
 * THE DOG CHARACTER RIG. One module draws every dog in the product (kennel cards, the studio, the model page header, small
 * leaderboard rows, the landing hero, the builder): `renderDog(container, look, pose, opts)`.
 *
 *   look   the locker-room look JSON (coat, eyes, bg, head, face, neck, body, number), cleaned against dog-look.js's tables
 *   pose   idle | happy | sad | thinking | celebrate   ("slump" is the old name for sad)
 *   opts   { size, breed | vibe | id, label, decorative }
 *
 * THE RIG IS LAYERED SVG, nothing raster, nothing fetched. From the back: the tile (background colour from the look), a
 * ground shadow, the body (shoulders, collar, hoodie or jersey), the paws (they come up in `celebrate`), the head group
 * (back ears, head, muzzle, markings, nose, mouth, eyes, brows, cheeks, front-of-face pieces), the accessory layers (sunglasses,
 * cap, headband, visor, chain; the jersey number sits on the jersey), then the pose props (tear, thought dots, sparkles).
 *
 * POSES ARE ATTRIBUTES, NOT REDRAWS. Every pose's mouth, eyes, brows and prop is drawn once into the SVG with a `dk-p--<pose>`
 * class, and css/lh.css shows the one that matches `data-pose`. `setPose(svg, pose)` flips the attribute, so a card can go
 * from idle to happy to celebrate without rebuilding the drawing. The breathing, the blink, the ear flick, the bounce and the
 * sparkles are CSS animations inside `prefers-reduced-motion: no-preference`; reduced motion keeps the pose (an expression is
 * information) and loses every movement. Nothing in this file schedules an animation.
 *
 * BREEDS are silhouettes chosen by a dog's VIBE (the persona vibe the leaderboard already carries): grinder is a bulldog, nerd a
 * schnauzer, degen a husky, chaos a mutt, psychic a hound; a dog with no vibe (a member's dog) gets one of the six by hashing
 * its id, so it keeps the same breed on every page. A breed is not part of the saved look and the server never sees it.
 *
 * Built with createElementNS only (hounds-core's `s`), so the node test harness can run it. Every colour is a constant from
 * dog-look.js's tables or a mix of two of them; no look value ever reaches a style or markup string.
 */

import { s, clearNode } from "./hounds-core.js";
import { COATS, EYES, BACKGROUNDS, cleanLook, hashStr, DEFAULT_LOOK } from "./dog-look.js";
import { BREEDS, BREED_LABELS, buildBreed, mix } from "./dog-breeds.js";

export const POSES = ["idle", "happy", "sad", "thinking", "celebrate"];
export { BREEDS, BREED_LABELS };
export const ACCESSORY_LAYERS = ["sunglasses", "cap", "headband", "visor", "chain", "hoodie", "jersey"];
export const VIBE_BREED = { grinder: "bulldog", nerd: "schnauzer", degen: "husky", chaos: "mutt", psychic: "hound" };

const ACCENT = "#2FD07A";
const GOLD = "#E0B24A";
const INK = "#12151A";
let uid = 0;

// ---- choosing a pose and a breed -------------------------------------------------------------------------------

/** "slump" (the old word) and anything unknown become a pose the rig knows. */
export function cleanPose(pose) {
  if (pose === "slump") return "sad";
  return POSES.includes(pose) ? pose : "idle";
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
};

/** The breed a dog's id or name spells out, or "". */
export function breedOfName(dog) {
  const d = dog && typeof dog === "object" ? dog : { id: dog };
  const words = `${d.id || ""} ${d.name || ""}`.toLowerCase().split(/[^a-z0-9]+/);
  for (const w of words) if (NAME_BREED[w]) return NAME_BREED[w];
  return "";
}

/** The breed for a dog: an explicit breed, else the one its name spells, else its persona vibe, else a stable pick from its id. `dog` may be an id string. */
export function breedFor(dog) {
  const d = dog && typeof dog === "object" ? dog : { id: dog };
  if (BREEDS.includes(d.breed)) return d.breed;
  const named = breedOfName(d);
  if (named) return named;
  const vibe = d.vibe || (d.persona && d.persona.vibe) || "";
  if (VIBE_BREED[vibe]) return VIBE_BREED[vibe];
  const key = d.id || d.name;
  return key ? BREEDS[hashStr(key) % BREEDS.length] : "retriever";
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

const n = (tag, attrs, kids) => s(tag, attrs || {}, kids || []);
const g = (cls, kids, attrs) => n("g", Object.assign({ class: cls }, attrs || {}), kids);
const path = (d, attrs) => n("path", Object.assign({ d }, attrs || {}));

// ---- the face: nose, mouth, eyes, brows, cheeks (one drawing per pose) ------------------------------------------

function noseShapes(geo, coat) {
  const { ny, nrx, nry } = geo;
  return [
    n("ellipse", { cx: 60, cy: ny, rx: nrx, ry: nry, fill: INK }),
    n("ellipse", { cx: 58, cy: ny - nry * 0.45, rx: nrx * 0.35, ry: nry * 0.28, fill: "#FFFFFF", opacity: ".38" }),
    path(`M60 ${ny + nry} V${geo.my - 4}`, { stroke: INK, "stroke-width": 1.6, "stroke-linecap": "round", fill: "none", opacity: ".8" }),
  ].map((el) => { void coat; return el; });
}

function mouthShapes(geo) {
  const { my } = geo, tongue = "#FF7B8E", deep = "#2A1216";
  const stroke = { stroke: INK, "stroke-width": 1.9, "stroke-linecap": "round", "stroke-linejoin": "round", fill: "none" };
  const open = (w, h) => [
    path(`M${60 - w} ${my - 3} Q60 ${my + h} ${60 + w} ${my - 3} Q60 ${my - 1} ${60 - w} ${my - 3} Z`, { fill: deep }),
    path(`M${60 - w * 0.55} ${my + h * 0.55} Q60 ${my + h * 0.1} ${60 + w * 0.55} ${my + h * 0.55} Q60 ${my + h * 1.05} ${60 - w * 0.55} ${my + h * 0.55} Z`, { fill: tongue }),
  ];
  return {
    idle: [path(`M${53} ${my - 1} Q${56.5} ${my + 3.5} 60 ${my - 3} Q${63.5} ${my + 3.5} ${67} ${my - 1}`, stroke)],
    happy: open(8.5, 11),
    sad: [path(`M${53.5} ${my + 3} Q60 ${my - 3.5} ${66.5} ${my + 3}`, stroke)],
    thinking: [path(`M${54} ${my + 0.5} Q${60} ${my + 2.5} ${66} ${my - 1.5}`, stroke), n("circle", { cx: 66.5, cy: my - 2, r: 0.6, fill: INK })],
    celebrate: open(10.5, 14),
  };
}

function eyeShapes(geo, eyeColor) {
  const { ey, edx, er } = geo;
  const xs = [60 - edx, 60 + edx];
  const open = (name, dx, dy, lid) => g(`dk-p dk-p--eyes dk-p--${name}`, xs.map((x, i) => g("dk-eye", [
    n("circle", { cx: x, cy: ey, r: er, fill: "#F7F8FA" }),
    n("circle", { cx: x + dx, cy: ey + dy, r: er * 0.68, fill: eyeColor }),
    n("circle", { cx: x + dx + 0.3, cy: ey + dy + 0.3, r: er * 0.34, fill: "#0B0C0E" }),
    n("circle", { cx: x + dx + er * 0.28, cy: ey + dy - er * 0.3, r: er * 0.2, fill: "#FFFFFF" }),
    lid ? path(lid(x, i), { fill: geo.lid[i] }) : null,
  ])));
  const arc = g("dk-p dk-p--eyes dk-p--happy", xs.map((x) => path(`M${x - er} ${ey + 1} Q${x} ${ey - er * 1.5} ${x + er} ${ey + 1}`,
    { stroke: INK, "stroke-width": 2.4, "stroke-linecap": "round", fill: "none" })));
  return [
    open("open", 0, 0.3),
    arc,
    open("sad", 0, 1.3, (x, i) => `M${x - er - 0.8} ${ey - er - 1} L${x + er + 0.8} ${ey - er - 1} L${x + er + 0.8} ${ey - er * 0.2 + (i ? -2.2 : 2.2)} L${x - er - 0.8} ${ey - er * 0.2 + (i ? 2.2 : -2.2)} Z`),
    open("thinking", 1.6, -1.6, (x) => `M${x - er - 0.8} ${ey - er - 1} L${x + er + 0.8} ${ey - er - 1} L${x + er + 0.8} ${ey - er * 0.35} L${x - er - 0.8} ${ey - er * 0.35} Z`),
  ];
}

function browShapes(geo, coat) {
  const { ey, edx, er } = geo;
  const col = mix(coat.shade, "#0B0C0E", 0.45);
  const st = { stroke: col, "stroke-width": 2.2, "stroke-linecap": "round", fill: "none" };
  const y = ey - er - 5;
  const L = 60 - edx, R = 60 + edx;
  return {
    happy: [path(`M${L - 5} ${y + 1} Q${L} ${y - 3} ${L + 5} ${y + 1}`, st), path(`M${R - 5} ${y + 1} Q${R} ${y - 3} ${R + 5} ${y + 1}`, st)],
    sad: [path(`M${L - 5} ${y + 3} L${L + 5} ${y - 2}`, st), path(`M${R + 5} ${y + 3} L${R - 5} ${y - 2}`, st)],
    thinking: [path(`M${L - 5} ${y + 1} L${L + 5} ${y + 1}`, st), path(`M${R - 5} ${y + 1} Q${R} ${y - 5} ${R + 5} ${y - 2}`, st)],
    celebrate: [path(`M${L - 5} ${y + 1} Q${L} ${y - 4} ${L + 5} ${y + 1}`, st), path(`M${R - 5} ${y + 1} Q${R} ${y - 4} ${R + 5} ${y + 1}`, st)],
  };
}

// ---- the body, the accessories, the props ----------------------------------------------------------------------

function bodyShapes(look, coat) {
  const torso = "M10 120 C10 100 30 90 60 90 C90 90 110 100 110 120 Z";
  if (look.body === "hoodie") {
    return [
      n("ellipse", { class: "dk-hood", cx: 60, cy: 80, rx: 42, ry: 28, fill: "#2C3442" }),
      path(torso, { fill: "#3B4455" }),
      path("M38 92 C46 100 74 100 82 92 C74 94 46 94 38 92 Z", { fill: "#2C3442" }),
      path("M52 97 L51 112 M68 97 L69 112", { stroke: "#E9ECF1", "stroke-width": 2, "stroke-linecap": "round", fill: "none" }),
      path("M44 112 C52 118 68 118 76 112 L76 120 L44 120 Z", { fill: "#2C3442", opacity: ".7" }),
    ];
  }
  if (look.body === "jersey") {
    const shapes = [
      path(torso, { fill: "#F2F4F8" }),
      path("M44 91 L60 106 L76 91", { fill: mix(coat.shade, coat.base, 0.2), stroke: ACCENT, "stroke-width": 3, "stroke-linejoin": "round" }),
      path("M14 106 H106", { stroke: ACCENT, "stroke-width": 2, opacity: ".85", fill: "none" }),
    ];
    if (look.number !== null) {
      shapes.push(n("text", { x: 60, y: 118.5, "text-anchor": "middle", "font-size": 13, "font-weight": 800,
        "font-family": "Instrument Sans, Arial, Helvetica, sans-serif", fill: "#0E1116", "data-number": String(look.number) }, String(look.number)));
    }
    return shapes;
  }
  return [
    path(torso, { fill: coat.base }),
    path("M42 92 C46 108 74 108 78 92 C72 100 48 100 42 92 Z", { fill: coat.light, opacity: ".55" }),
    path("M42 90 Q60 100 78 90 L78 95 Q60 106 42 95 Z", { fill: ACCENT }),
    n("circle", { cx: 60, cy: 103, r: 3.6, fill: GOLD, stroke: "#8A6A1F", "stroke-width": 0.8 }),
  ];
}

function headAccessory(look, geo) {
  const { browY, topY, hw } = geo;
  const L = 60 - hw - 1, R = 60 + hw + 1;
  if (look.head === "cap") {
    return g("dk-acc dk-acc--cap", [
      path(`M${L} ${browY - 2} C${L} ${topY - 14} ${R} ${topY - 14} ${R} ${browY - 2} C${R - 10} ${browY - 9} ${L + 10} ${browY - 9} ${L} ${browY - 2} Z`, { fill: "#1F2937" }),
      path(`M${L + 3} ${browY - 8} C${L + 14} ${browY - 14} ${R - 14} ${browY - 14} ${R - 3} ${browY - 8}`, { stroke: ACCENT, "stroke-width": 2.4, fill: "none", "stroke-linecap": "round" }),
      path(`M62 ${browY - 5} C${74} ${browY - 8} ${R + 8} ${browY - 5} ${R + 12} ${browY + 2} C${R + 2} ${browY + 3} 74 ${browY + 1} 62 ${browY - 1} Z`, { fill: "#111827" }),
      n("circle", { cx: 60, cy: topY - 9, r: 2.8, fill: ACCENT }),
    ]);
  }
  if (look.head === "headband") {
    return g("dk-acc dk-acc--headband", [
      path(`M${L} ${browY - 1} Q60 ${browY - 15} ${R} ${browY - 1} L${R + 0.5} ${browY + 6} Q60 ${browY - 8} ${L - 0.5} ${browY + 6} Z`, { fill: ACCENT }),
      path(`M${L} ${browY - 1} Q60 ${browY - 15} ${R} ${browY - 1}`, { stroke: "#1E9E5C", "stroke-width": 1.2, fill: "none" }),
    ]);
  }
  if (look.head === "visor") {
    return g("dk-acc dk-acc--visor", [
      path(`M${L} ${browY - 2} Q60 ${browY - 14} ${R} ${browY - 2}`, { stroke: "#E9ECF1", "stroke-width": 4, fill: "none", "stroke-linecap": "round" }),
      path(`M${L + 7} ${browY - 2} C${L + 18} ${browY - 8} ${R - 18} ${browY - 8} ${R - 7} ${browY - 2} C${R - 9} ${browY + 9} ${L + 9} ${browY + 9} ${L + 7} ${browY - 2} Z`, { fill: "#E9ECF1", opacity: ".95" }),
      path(`M${L + 11} ${browY + 2} C${L + 22} ${browY - 1} ${R - 22} ${browY - 1} ${R - 11} ${browY + 2}`, { stroke: "#B6BDC9", "stroke-width": 1.2, fill: "none" }),
    ]);
  }
  return null;
}

function sunglasses(geo) {
  const { ey, edx, er } = geo;
  const w = er * 2 + 8, h = er * 2 + 4;
  return g("dk-acc dk-acc--sunglasses", [
    path(`M${60 - edx - w / 2 - 3} ${ey - 1} H${60 + edx + w / 2 + 3}`, { stroke: "#0B0C0E", "stroke-width": 2.2, "stroke-linecap": "round" }),
    n("rect", { x: 60 - edx - w / 2, y: ey - h / 2 - 1, width: w, height: h, rx: h / 2.6, fill: "#0B0C0E" }),
    n("rect", { x: 60 + edx - w / 2, y: ey - h / 2 - 1, width: w, height: h, rx: h / 2.6, fill: "#0B0C0E" }),
    path(`M${60 - edx - w / 2 + 3} ${ey - 3} l4 0 M${60 + edx - w / 2 + 3} ${ey - 3} l4 0`, { stroke: "rgba(255,255,255,.6)", "stroke-width": 1.6, "stroke-linecap": "round" }),
  ]);
}

function roundGlasses(geo) {
  const { ey, edx, er } = geo, r = er + 4.6, gold = GOLD;
  const rim = (x) => n("circle", { cx: x, cy: ey, r, fill: "rgba(255,255,255,0.14)", stroke: gold, "stroke-width": 1.9 });
  return g("dk-acc dk-acc--glasses", [
    rim(60 - edx), rim(60 + edx),
    path(`M${60 - edx + r} ${ey - 1} Q60 ${ey - 4.5} ${60 + edx - r} ${ey - 1}`, { stroke: gold, "stroke-width": 1.9, fill: "none", "stroke-linecap": "round" }),
    path(`M${60 - edx - r} ${ey} L${60 - edx - r - 5} ${ey - 2} M${60 + edx + r} ${ey} L${60 + edx + r + 5} ${ey - 2}`, { stroke: gold, "stroke-width": 1.6, fill: "none", "stroke-linecap": "round" }),
  ]);
}

function chain() {
  return g("dk-acc dk-acc--chain", [
    path("M36 92 Q60 118 84 92", { stroke: GOLD, "stroke-width": 3, fill: "none", "stroke-dasharray": "4.2 1.8", "stroke-linecap": "round" }),
    n("circle", { cx: 60, cy: 108, r: 4.6, fill: GOLD, stroke: "#8A6A1F", "stroke-width": 1 }),
    n("circle", { cx: 58.6, cy: 106.6, r: 1.4, fill: "#FFFFFF", opacity: ".55" }),
  ]);
}

const SPARKLE = "M0 -6 L1.7 -1.7 L6 0 L1.7 1.7 L0 6 L-1.7 1.7 L-6 0 L-1.7 -1.7 Z";

function pawShapes(coat) {
  const paw = (side) => g(`dk-paw dk-paw--${side < 0 ? "l" : "r"}`, [
    n("ellipse", { cx: 60 + side * 40, cy: 98, rx: 10, ry: 12.5, fill: coat.base, stroke: coat.shade, "stroke-width": 1.2 }),
    path(`M${60 + side * 40 - 3.4} 89 V94 M${60 + side * 40 + 3.4} 89 V94`, { stroke: coat.shade, "stroke-width": 1.3, "stroke-linecap": "round", opacity: ".7" }),
  ]);
  return g("dk-paws", [paw(-1), paw(1)]);
}

function propShapes() {
  return [
    g("dk-p dk-p--tear", [path("M0 0 C-3.6 5 -3.6 9 0 9 C3.6 9 3.6 5 0 0 Z", { fill: "#8FD0FF", opacity: ".95", transform: "translate(80 66)" })]),
    g("dk-p dk-p--thought", [
      n("circle", { class: "dk-dot dk-dot--1", cx: 93, cy: 26, r: 2.2, fill: "#EEF1F5" }),
      n("circle", { class: "dk-dot dk-dot--2", cx: 100, cy: 18, r: 3.2, fill: "#EEF1F5" }),
      n("circle", { class: "dk-dot dk-dot--3", cx: 108, cy: 9, r: 4.4, fill: "#EEF1F5" }),
    ]),
    g("dk-p dk-p--sparkles", [
      path(SPARKLE, { class: "dk-spark dk-spark--1", fill: GOLD, transform: "translate(18 30)" }),
      path(SPARKLE, { class: "dk-spark dk-spark--2", fill: "#EEF1F5", transform: "translate(104 24)" }),
      path(SPARKLE, { class: "dk-spark dk-spark--3", fill: ACCENT, transform: "translate(108 64)" }),
      path(SPARKLE, { class: "dk-spark dk-spark--4", fill: "#8FB8FF", transform: "translate(12 70)" }),
    ]),
  ];
}

// ---- the dog ---------------------------------------------------------------------------------------------------

/**
 * The dog as an <svg> element. `opts`: size (px, default 56), breed | vibe | id (the breed), label + decorative (accessibility),
 * pose (default idle). The svg carries data-pose, data-mood (the name asked for), data-breed and the data-* keys of the look.
 */
export function dogSvg(rawLook, opts = {}) {
  const look = cleanLook(rawLook);
  const pose = cleanPose(opts.pose || opts.mood);
  const breedName = BREEDS.includes(opts.breed) ? opts.breed : breedFor(opts);
  const coat0 = COATS[look.coat];
  const [bgA, bgB] = BACKGROUNDS[look.bg];
  const size = opts.size || 56;
  const gid = `dk-bg-${++uid}`;
  const built = buildBreed(breedName, coat0);
  const coat = built.coat || coat0;
  const geo = built.geo;
  if (!geo.lid) geo.lid = [coat.base, coat.base];
  const mouths = mouthShapes(geo), eyes = eyeShapes(geo, EYES[look.eyes]), brows = browShapes(geo, coat);

  const face = [
    ...noseShapes(geo, coat),
    ...Object.entries(mouths).map(([name, shapes]) => g(`dk-p dk-p--mouth dk-p--${name}`, shapes)),
    ...built.front,
    g("dk-p dk-p--cheeks", [
      n("ellipse", { cx: 60 - geo.edx - 6, cy: geo.ey + 9, rx: 5.5, ry: 3.4, fill: "#FF8FA3", opacity: ".42" }),
      n("ellipse", { cx: 60 + geo.edx + 6, cy: geo.ey + 9, rx: 5.5, ry: 3.4, fill: "#FF8FA3", opacity: ".42" }),
    ]),
    g("dk-eyes", eyes),
    ...Object.entries(brows).map(([name, shapes]) => g(`dk-p dk-p--brows dk-p--${name}`, shapes)),
  ];
  if (look.face === "sunglasses") face.push(sunglasses(geo));
  else if (traitsFor(opts).glasses) face.push(roundGlasses(geo));
  const acc = headAccessory(look, geo);
  if (acc) face.push(acc);

  const kids = [
    n("defs", {}, [
      n("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [n("stop", { offset: "0", "stop-color": bgA }), n("stop", { offset: "1", "stop-color": bgB })]),
      n("radialGradient", { id: `${gid}-glow`, cx: 0.5, cy: 0.38, r: 0.62 }, [
        n("stop", { offset: "0", "stop-color": "#FFFFFF", "stop-opacity": ".2" }), n("stop", { offset: "1", "stop-color": "#FFFFFF", "stop-opacity": "0" })]),
      n("clipPath", { id: `${gid}-clip` }, [n("rect", { x: 0, y: 0, width: 120, height: 120, rx: 26 })]),
    ]),
    n("rect", { class: "dk-tile", x: 0.6, y: 0.6, width: 118.8, height: 118.8, rx: 26, fill: `url(#${gid})`, stroke: "rgba(255,255,255,.14)" }),
    g("dk-scene", [
      n("rect", { x: 0, y: 0, width: 120, height: 120, rx: 26, fill: `url(#${gid}-glow)` }),
      g("dk-clip", [
        n("ellipse", { class: "dk-shadow", cx: 60, cy: 118, rx: 46, ry: 6, fill: "#000000", opacity: ".22" }),
        g("dk-body", bodyShapes(look, coat)),
        pawShapes(coat),
        g("dk-head", [...built.back, ...built.head, ...face]),
        look.neck === "chain" && look.body !== "hoodie" ? chain() : null,
        look.neck === "chain" && look.body === "hoodie" ? chain() : null,
      ], { "clip-path": `url(#${gid}-clip)` }),
      ...propShapes(),
    ]),
  ];
  const attrs = {
    class: "dk-badge", viewBox: "0 0 120 120", width: size, height: size, focusable: "false", "data-pose": pose,
    "data-mood": opts.mood || pose, "data-breed": breedName, "data-coat": look.coat, "data-bg": look.bg, "data-head": look.head,
    "data-face": look.face, "data-neck": look.neck, "data-body": look.body,
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
  if (svg && svg.setAttribute) { svg.setAttribute("data-pose", next); svg.setAttribute("data-mood", pose || next); }
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
