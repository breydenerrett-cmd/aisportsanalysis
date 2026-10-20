"""The illustrated hounds (web/js/dog-rig.js and its parts), run for real under node.

Design round 3, 2026-10-19: the dog rig became a premium illustrated hound system. This file holds it to:
  * every breed x every style x every pose renders (33 x 3 x 5 drawings) with no NaN or undefined anywhere in a drawing;
  * look validation: the style is a whitelist (default Mascot), the breed override is a whitelist ("auto" is the name's breed),
    a look saved before either existed keeps working, and the page and the server hold the same lists;
  * every breed has the anchors the accessories are placed from, in the right order, inside the badge;
  * the new accessory layers (spiked collar, bandana) draw on every breed in every style;
  * the small level of detail (a badge of 44px or less) is lighter and heavier-lined than the full one;
  * every house dog is still drawn as the breed its name spells, and a dog with no breed word keeps its hashed breed;
  * the defs are shared once per page when the page has a body, and inline when it has not;
  * the expression names (snarl, grin, focus, howl) are accepted and the drawing says which expression it shows;
  * the whole illustration code stays under the 120 KB gzipped budget and animates nothing outside the reduced-motion block;
  * the locker room: the style cards, the breed grid, the preview and what is saved.
"""

from __future__ import annotations

import gzip
import json
import re
import unittest
from pathlib import Path

from src.hounds.interact import look
from tests.hounds_web_runner import HAS_NODE, run_js
from tests.test_dog_rig import FAKE_DOM, BreedMappingAndLabels
from tests.test_hounds_interact_web import HID, dog_routes, hook, page, q

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"

BREEDS = [
    "retriever", "labrador", "bulldog", "newfoundland", "chihuahua", "corgi", "collie", "shepherd", "kelpie", "husky",
    "jackrussell", "dalmatian", "pointer", "beagle", "basset", "bloodhound", "hound", "greyhound", "whippet", "setter",
    "spaniel", "poodle", "terrier", "schnauzer", "mutt",
    "doberman", "rottweiler", "pitbull", "wolfhound", "boxer", "mastiff", "shiba", "malinois",
]
OWNER_ASKED_FOR = ["doberman", "rottweiler", "pitbull", "shepherd", "greyhound", "bloodhound", "husky", "wolfhound", "boxer", "bulldog",
                   "dalmatian", "basset", "beagle", "mastiff", "shiba", "malinois"]
STYLES = ["mascot", "street", "elite"]
POSES = ["idle", "happy", "sad", "thinking", "celebrate"]
ORIGINAL_25 = BREEDS[:25]


def js(body: str):
    return run_js(FAKE_DOM + 'const Rig = await import("./dog-rig.js");\nconst Av = await import("./dog-avatar.js");\n' + body)


def fnv(text: str) -> int:
    x = 2166136261
    for ch in text:
        x = ((x ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return x


@unittest.skipUnless(HAS_NODE, "node not installed")
class EveryBreedEveryStyleEveryPose(unittest.TestCase):
    def test_the_owner_asked_for_these_sixteen_and_the_rig_draws_all_of_them(self):
        got = js("console.log(JSON.stringify(Rig.BREEDS));")
        self.assertEqual(got, BREEDS)
        self.assertLessEqual(set(OWNER_ASKED_FOR), set(got))
        self.assertGreaterEqual(len(got), 16)

    def test_all_breeds_all_styles_all_poses_render_clean(self):
        got = js('''
const bad = []; let n = 0; const sigs = new Set();
for (const breed of Rig.BREEDS) for (const style of Rig.STYLES) for (const pose of Rig.POSES) {
  const svg = Rig.dogSvg({ style, coat: "golden", eyes: "blue", bg: "teal" }, { breed, pose, size: 120 });
  n += 1;
  if (svg.tag !== "svg" || svg.attrs["data-style"] !== style || svg.attrs["data-breed"] !== breed || svg.attrs["data-pose"] !== pose) bad.push([breed, style, pose, "attrs"]);
  let paths = 0;
  walk(svg, (node) => {
    if (node.tag === "path") paths += 1;
    for (const [k, v] of Object.entries(node.attrs)) if (/NaN|undefined|Infinity|null/.test(String(v))) bad.push([breed, style, pose, node.tag, k, String(v).slice(0, 60)]);
  });
  if (paths < 30) bad.push([breed, style, pose, "few paths", paths]);
  if (pose === "idle") sigs.add(`${breed}|${style}`);
}
console.log(JSON.stringify({ n, bad: bad.slice(0, 8), sigs: sigs.size }));''')
        self.assertEqual(got["n"], 33 * 3 * 5)
        self.assertEqual(got["bad"], [])

    def test_a_pose_shows_the_expression_it_draws_and_the_expression_words_are_accepted(self):
        got = js('''
const exp = Rig.POSES.map((p) => Rig.dogSvg({}, { breed: "husky", pose: p }).attrs["data-expr"]);
const words = ["snarl", "grin", "focus", "howl", "cheer", "slump"].map((w) => [w, Rig.cleanPose(w), Rig.dogSvg({}, { pose: w }).attrs["data-pose"]]);
const svg = Rig.dogSvg({}, { pose: "idle" }); Rig.setPose(svg, "howl");
console.log(JSON.stringify({ exp, words, after: [svg.attrs["data-pose"], svg.attrs["data-expr"]], list: Rig.EXPRESSIONS, junk: Rig.cleanPose("dance") }));''')
        self.assertEqual(got["exp"], ["idle", "grin", "snarl", "focus", "howl"])
        self.assertEqual(got["words"], [["snarl", "sad", "sad"], ["grin", "happy", "happy"], ["focus", "thinking", "thinking"],
                                        ["howl", "celebrate", "celebrate"], ["cheer", "celebrate", "celebrate"], ["slump", "sad", "sad"]])
        self.assertEqual(got["after"], ["celebrate", "howl"])
        self.assertEqual(got["list"], ["idle", "snarl", "grin", "focus", "howl"])
        self.assertEqual(got["junk"], "idle")

    def test_every_expression_has_its_own_eyes_mouth_and_prop_drawn_once(self):
        got = js('''
const cls = classes(Rig.dogSvg({}, { breed: "doberman" })).join(" ");
const has = (re) => re.test(cls);
console.log(JSON.stringify({
  mouths: ["idle", "happy", "sad", "thinking", "celebrate"].map((p) => has(new RegExp(`dk-p--mouth dk-p--${p}\\\\b`))),
  eyes: ["open", "happy", "sad", "thinking", "celebrate"].map((p) => has(new RegExp(`dk-p--eyes dk-p--${p}\\\\b`))),
  props: ["rage", "thought", "gleam", "sparkles", "sound"].map((p) => has(new RegExp(`dk-p--${p}\\\\b`))) }));''')
        self.assertTrue(all(got["mouths"]), got)
        self.assertTrue(all(got["eyes"]), got)
        self.assertTrue(all(got["props"]), got)

    def test_the_stylesheet_shows_the_new_parts_for_their_poses(self):
        css = (ROOT / "web" / "css" / "lh.css").read_text(encoding="utf-8")
        self.assertRegex(css, r'\[data-pose="celebrate"\] \.dk-p--eyes\.dk-p--celebrate')
        self.assertRegex(css, r'\[data-pose="sad"\] \.dk-p--rage')
        self.assertRegex(css, r'\[data-pose="happy"\] \.dk-p--gleam')
        self.assertRegex(css, r'\[data-pose="celebrate"\] \.dk-p--sound')
        self.assertRegex(css, r'\[data-pose="celebrate"\] \.dk-head \{ transform:', "the howl throws the head back with every animation off")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStyleAndTheBreedAreWhitelisted(unittest.TestCase):
    def test_the_style_is_a_whitelist_and_the_default_is_mascot(self):
        got = js('''
const c = (look) => Av.cleanLook(look).style;
console.log(JSON.stringify({ ok: ["mascot", "street", "elite"].map((s) => c({ style: s })), junk: [c({ style: "neon" }), c({ style: "<script>" }), c({ style: 4 }), c({ style: null }), c({}), c(undefined)],
  drawn: Rig.dogSvg({ style: "x</svg>" }, {}).attrs["data-style"], list: Av.STYLES, d: Av.DEFAULT_LOOK.style }));''')
        self.assertEqual(got["ok"], STYLES)
        self.assertEqual(got["junk"], ["mascot"] * 6)
        self.assertEqual(got["drawn"], "mascot")
        self.assertEqual(got["list"], STYLES)
        self.assertEqual(got["d"], "mascot")

    def test_the_breed_override_is_a_whitelist_and_auto_means_the_names_breed(self):
        got = js('''
const named = (breed) => Rig.dogSvg({ breed }, { id: "chalk_chihuahua", name: "Chalk Chihuahua", vibe: "grinder" }).attrs["data-breed"];
console.log(JSON.stringify({
  auto: named("auto"), none: named(undefined), junk: [named("unicorn"), named("<img>"), named(7)], doberman: named("doberman"), every: Rig.BREEDS.every((b) => named(b) === b),
  breedFor: [Rig.breedFor({ id: "x", name: "Bulldog Bob", look: { breed: "boxer" } }), Rig.breedFor({ id: "x", name: "Bulldog Bob", look: { breed: "auto" } }), Rig.breedFor({ id: "x", look: {} })],
  label: Rig.breedLabel(Rig.breedFor({ look: { breed: "pitbull" } })),
  explicit: Rig.dogSvg({ breed: "mastiff" }, { breed: "husky" }).attrs["data-breed"], optBreed: Rig.dogSvg({}, { breed: "husky" }).attrs["data-breed"],
  choices: Av.BREED_CHOICES, cleaned: Av.cleanLook({ breed: "malinois" }).breed, junkClean: Av.cleanLook({ breed: "x" }).breed }));''')
        self.assertEqual(got["auto"], "chihuahua")
        self.assertEqual(got["none"], "chihuahua")
        self.assertEqual(got["junk"], ["chihuahua"] * 3)
        self.assertEqual(got["doberman"], "doberman")
        self.assertTrue(got["every"], "the owner may pick any breed")
        self.assertEqual(got["breedFor"], ["boxer", "bulldog", got["breedFor"][2]])
        self.assertEqual(got["label"], "Pit Bull")
        self.assertEqual(got["explicit"], "mastiff", "the owner's own pick beats a breed a page passes in")
        self.assertEqual(got["optBreed"], "husky")
        self.assertEqual(got["choices"], ["auto"] + BREEDS)
        self.assertEqual((got["cleaned"], got["junkClean"]), ("malinois", "auto"))

    def test_the_server_and_the_page_hold_the_same_lists(self):
        got = js("console.log(JSON.stringify({ styles: Av.STYLES, breeds: Av.BREED_CHOICES, neck: Av.NECK, d: Av.DEFAULT_LOOK }));")
        self.assertEqual(got["styles"], list(look.STYLES))
        self.assertEqual(got["breeds"], list(look.BREED_CHOICES))
        self.assertEqual(got["neck"], list(look.NECK))
        self.assertEqual({k: v for k, v in got["d"].items()}, {k: v for k, v in look.DEFAULT_LOOK.items() if k != "v"})

    def test_the_server_validates_style_and_breed_and_an_old_look_keeps_working(self):
        for style in look.STYLES:
            self.assertEqual(look.validate_look({"style": style})["style"], style)
        for breed in look.BREED_CHOICES:
            self.assertEqual(look.validate_look({"breed": breed})["breed"], breed)
        for neck in ("collar", "bandana"):
            self.assertEqual(look.validate_look({"neck": neck})["neck"], neck)
        old = look.validate_look({"coat": "red", "eyes": "blue", "bg": "forest", "head": "cap", "face": "sunglasses", "neck": "chain",
                                  "body": "jersey", "number": 9, "v": 1})
        self.assertEqual((old["style"], old["breed"], old["coat"], old["number"]), ("mascot", "auto", "red", 9))
        for bad in ({"style": "neon"}, {"style": ""}, {"style": 3}, {"breed": "unicorn"}, {"breed": "<img>"}, {"breed": None}, {"neck": "scarf"}):
            with self.subTest(bad=bad):
                with self.assertRaises(look.LookError):
                    look.validate_look(bad)
        self.assertIn("style", look.menu())
        self.assertEqual(look.menu()["breed"], ["auto"] + BREEDS)

    def test_a_look_from_the_server_with_no_style_or_breed_draws_in_mascot(self):
        got = js('''
const old = { coat: "red", eyes: "blue", bg: "forest", head: "cap", face: "none", neck: "chain", body: "jersey", number: 9, v: 1 };
const svg = Rig.dogSvg(old, { id: "pack_leader", name: "Pack Leader" });
console.log(JSON.stringify([svg.attrs["data-style"], svg.attrs["data-breed"], Av.cleanLook(old).style, Av.cleanLook(old).breed]));''')
        self.assertEqual(got, ["mascot", "shepherd", "mascot", "auto"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class AnchorsAndAccessories(unittest.TestCase):
    def test_every_breed_has_the_anchors_the_accessories_hang_from_in_order_and_inside_the_badge(self):
        got = js("console.log(JSON.stringify(Object.fromEntries(Rig.BREEDS.map((b) => [b, Av.anchorsFor(b)]))));")
        self.assertEqual(sorted(got), sorted(BREEDS))
        for breed, a in got.items():
            with self.subTest(breed=breed):
                for key in ("crown", "brow", "eyes", "nose", "mouth", "chin", "neck", "chest", "hood"):
                    self.assertIn(key, a)
                nums = []

                def collect(o):
                    if isinstance(o, dict):
                        for v in o.values():
                            collect(v)
                    else:
                        nums.append(o)
                collect(a)
                self.assertTrue(all(isinstance(v, (int, float)) and v == v for v in nums), a)
                self.assertTrue(all(-20 <= v <= 140 for v in nums), a)
                self.assertLess(a["crown"]["y"], a["brow"]["y"])
                self.assertLess(a["brow"]["y"], a["eyes"]["y"])
                self.assertLess(a["eyes"]["y"], a["nose"]["y"])
                self.assertLess(a["nose"]["y"], a["mouth"]["y"])
                self.assertLess(a["mouth"]["y"], a["chin"]["y"])
                self.assertLess(a["chin"]["y"], 108, "the chin and the pieces that hang from it stay inside the badge")
                self.assertLess(a["eyes"]["left"], 60)
                self.assertGreater(a["eyes"]["right"], 60)
                self.assertGreater(a["neck"]["half"], 12)
                self.assertLess(a["brow"]["left"], a["eyes"]["left"] - a["eyes"]["ew"] + 1, "the head is wider than the eyes")

    def test_each_new_neck_piece_draws_on_every_breed_in_every_style(self):
        got = js('''
const out = [];
for (const breed of Rig.BREEDS) for (const style of Rig.STYLES) {
  const has = (look) => classes(Rig.dogSvg(Object.assign({ style }, look), { breed })).filter((c) => /dk-acc--(collar|bandana|chain)/.test(c));
  out.push([breed, style, has({ neck: "collar" }), has({ neck: "bandana" }), has({ neck: "chain" }), has({})]);
}
console.log(JSON.stringify(out));''')
        self.assertEqual(len(got), 33 * 3)
        for breed, style, collar, bandana, chain, bare in got:
            self.assertEqual(collar, ["dk-acc dk-acc--collar"], (breed, style))
            self.assertEqual(bandana, ["dk-acc dk-acc--bandana"], (breed, style))
            self.assertEqual(chain, ["dk-acc dk-acc--chain"], (breed, style))
            self.assertEqual(bare, [], (breed, style))

    def test_every_accessory_the_server_allows_draws_in_every_style_on_every_breed(self):
        got = js('''
let n = 0, bad = 0;
for (const breed of Rig.BREEDS) for (const style of Rig.STYLES) for (const head of Av.HEAD) for (const face of Av.FACE) for (const neck of Av.NECK) for (const body of Av.BODY) {
  const svg = Rig.dogSvg({ style, head, face, neck, body, number: 12 }, { breed, size: n % 3 ? 40 : 150, pose: Rig.POSES[n % 5] }); n += 1;
  walk(svg, (node) => { for (const v of Object.values(node.attrs)) if (/NaN|undefined/.test(String(v))) bad += 1; });
}
console.log(JSON.stringify({ n, bad }));''')
        self.assertEqual(got["n"], 33 * 3 * 4 * 2 * 4 * 3)
        self.assertEqual(got["bad"], 0)

    def test_the_head_pieces_sit_on_the_brow_anchor_of_each_breed(self):
        got = js('''
const out = [];
for (const breed of Rig.BREEDS) {
  const a = Av.anchorsFor(breed), svg = Rig.dogSvg({ head: "cap", face: "sunglasses" }, { breed });
  const ys = []; walk(svg, (n) => { if (/dk-acc--cap/.test(n.attrs.class || "")) walk(n, (m) => { if (m.tag === "path" && m.attrs.d) for (const mm of m.attrs.d.matchAll(/(-?\\d+\\.?\\d*) (-?\\d+\\.?\\d*)/g)) ys.push(Number(mm[2])); }); });
  out.push([breed, a.brow.y, Math.min(...ys), Math.max(...ys), a.eyes.y]);
}
console.log(JSON.stringify(out));''')
        a_nose = {b: v["nose"]["y"] for b, v in js("console.log(JSON.stringify(Object.fromEntries(Rig.BREEDS.map((b) => [b, Av.anchorsFor(b)]))));").items()}
        for breed, brow, lo, hi, eyes in got:
            with self.subTest(breed=breed):
                self.assertLess(lo, brow, "the cap rises above the brow")
                self.assertLess(hi, a_nose[breed], "the cap never comes down to the nose")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSmallLevelOfDetail(unittest.TestCase):
    def test_a_badge_of_44px_or_less_is_the_small_level_and_is_lighter_with_a_heavier_outline(self):
        got = js('''
const nodes = (svg) => { let c = 0; walk(svg, () => { c += 1; }); return c; };
const overlays = (svg) => { let c = 0; walk(svg, (n) => { if (/^url\\(#lh-(sh|rim|key)/.test(n.attrs.fill || "")) c += 1; }); return c; };
const widths = (svg) => { const w = []; walk(svg, (n) => { if (n.tag === "path" && n.attrs.stroke && n.attrs["stroke-width"] && /^#0B0D12$/i.test(n.attrs.stroke)) w.push(Number(n.attrs["stroke-width"])); }); return Math.max(...w); };
const out = {};
for (const style of Rig.STYLES) {
  const big = Rig.dogSvg({ style }, { breed: "doberman", size: 200 }), small = Rig.dogSvg({ style }, { breed: "doberman", size: 32 });
  out[style] = [big.attrs["data-lod"], small.attrs["data-lod"], nodes(big), nodes(small), widths(big), widths(small), hasClass(small, "dk-sockets"), hasClass(big, "dk-sockets"), overlays(small), overlays(big)];
}
const edge = [Rig.dogSvg({}, { size: 44 }).attrs["data-lod"], Rig.dogSvg({}, { size: 45 }).attrs["data-lod"], Rig.dogSvg({}, {}).attrs["data-lod"], Rig.dogSvg({}, { size: 24 }).attrs["data-lod"]];
console.log(JSON.stringify({ out, edge, small: Rig.SMALL_PX }));''')
        self.assertEqual(got["small"], 44)
        self.assertEqual(got["edge"], ["s", "l", "l", "s"])
        for style in ("mascot", "street"):
            big_lod, small_lod, big_n, small_n, big_w, small_w, small_sock, big_sock, small_ov, big_ov = got["out"][style]
            self.assertEqual((big_lod, small_lod), ("l", "s"))
            self.assertLess(small_n, big_n, f"{style}: the small badge draws fewer parts")
            self.assertEqual(small_ov, 0, f"{style}: no shading overlays at the small level")
            self.assertGreater(big_ov, 6, f"{style}: the full badge shades its shapes")
            self.assertGreater(small_w, big_w, f"{style}: the small badge has the heavier outline")
            self.assertFalse(small_sock)
            self.assertTrue(big_sock)
        elite = got["out"]["elite"]
        self.assertLess(elite[3], elite[2])

    def test_every_breed_reads_at_32px_with_eyes_nose_mouth_and_ears(self):
        got = js('''
const out = [];
for (const breed of Rig.BREEDS) for (const style of Rig.STYLES) {
  const svg = Rig.dogSvg({ style }, { breed, size: 32 });
  out.push([breed, style, svg.attrs.width, hasClass(svg, "dk-eyes"), hasClass(svg, "dk-ear--l"), hasClass(svg, "dk-ear--r"), count(svg, "path") > 25 && count(svg, "path") < 140]);
}
console.log(JSON.stringify(out));''')
        for breed, style, width, eyes, ear_l, ear_r, sane in got:
            self.assertEqual(width, "32")
            self.assertTrue(eyes and ear_l and ear_r and sane, (breed, style))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHouseDogsAreUnchanged(unittest.TestCase):
    def test_every_house_dog_is_still_the_breed_its_name_spells_with_the_same_label(self):
        dogs = BreedMappingAndLabels.HOUSE
        got = js(f"""
const dogs = {json.dumps(dogs)};
const out = {{}};
for (const [id, [name, vibe]] of Object.entries(dogs)) {{
  const svg = Rig.dogSvg(Av.lookFor(id), {{ id, name, vibe }});
  out[id] = [svg.attrs["data-breed"], Rig.breedLabel(svg.attrs["data-breed"]), svg.attrs["data-style"]];
}}
console.log(JSON.stringify(out));""")
        for dog_id, (_name, _vibe, breed, label) in dogs.items():
            self.assertEqual(got[dog_id], [breed, label, "mascot"], dog_id)

    def test_a_dog_with_no_breed_word_and_no_vibe_keeps_the_breed_its_id_hashed_to_before(self):
        ids = ["u-d151fe52c7", "u-0000000001", "desk_fader_x", "member dog 7", "qq", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
        got = js(f"console.log(JSON.stringify({json.dumps(ids)}.map((id) => Rig.breedFor(id))));")
        self.assertEqual(got, [ORIGINAL_25[fnv(i) % 25] for i in ids])
        self.assertTrue(all(b in ORIGINAL_25 for b in got), "the new breeds are never assigned by hash")

    def test_the_vibes_keep_their_breeds_and_the_new_breeds_have_name_words(self):
        got = js('''console.log(JSON.stringify([["grinder", "nerd", "degen", "chaos", "psychic"].map((v) => Rig.breedFor({ vibe: v, id: "z" })),
  ["Rex the Doberman", "Rottie Rick", "Pitbull Pete", "Wolfhound Will", "Boxer Bo", "Mastiff Mo", "Shiba Sue", "Malinois Max", "Kane Corso"].map((name) => Rig.breedFor({ id: "n", name }))]));''')
        self.assertEqual(got[0], ["bulldog", "schnauzer", "husky", "mutt", "hound"])
        self.assertEqual(got[1][:8], ["doberman", "rottweiler", "pitbull", "wolfhound", "boxer", "mastiff", "shiba", "malinois"])
        self.assertIn(got[1][8], ORIGINAL_25, "a name with no breed word still hashes over the original drawings")


@unittest.skipUnless(HAS_NODE, "node not installed")
class SharedDefs(unittest.TestCase):
    def test_a_page_with_a_body_gets_one_copy_of_the_defs_and_the_badges_carry_none(self):
        got = js('''
const body = mkEl("body"); const ids = new Map();
const reg = (el) => { if (el.attrs && el.attrs.id) ids.set(el.attrs.id, el); (el.kids || []).forEach(reg); };
globalThis.document.body = body;
globalThis.document.getElementById = (id) => { ids.clear(); reg(body); return ids.get(id) || null; };
const a = Rig.dogSvg({ style: "street" }, { breed: "boxer" }), b = Rig.dogSvg({ style: "elite" }, { breed: "husky" }), c = Rig.dogSvg({}, { breed: "mutt", size: 32 });
const hosts = body.kids.filter((k) => k.attrs.id === "lh-dog-defs");
const defsIn = (svg) => { let n = 0; walk(svg, (x) => { if (x.tag === "defs") n += 1; }); return n; };
const grads = []; walk(hosts[0], (x) => { if (x.attrs.id) grads.push(x.attrs.id); });
console.log(JSON.stringify({ hosts: hosts.length, bodyKids: body.kids.length, inBadges: [defsIn(a), defsIn(b), defsIn(c)], grads, aria: hosts[0].attrs["aria-hidden"], size: [hosts[0].attrs.width, hosts[0].attrs.height] }));''')
        self.assertEqual(got["hosts"], 1)
        self.assertEqual(got["bodyKids"], 1, "three badges, one set of defs")
        self.assertEqual(got["inBadges"], [0, 0, 0])
        for needed in ("lh-sh-cel", "lh-sh-soft", "lh-rim-hard", "lh-rim-soft", "lh-gold", "lh-silver", "lh-burst", "lh-splat", "lh-sound", "lh-tile-clip", "lh-bg-navy", "lh-bg-sand"):
            self.assertIn(needed, got["grads"])
        self.assertEqual(got["aria"], "true")
        self.assertEqual(got["size"], ["0", "0"])

    def test_a_page_with_no_body_gets_the_defs_inline_so_the_badge_still_draws(self):
        got = js('''
const svg = Rig.dogSvg({ style: "mascot" }, { breed: "boxer" });
let defs = 0, ids = []; walk(svg, (x) => { if (x.tag === "defs") defs += 1; if (x.attrs.id) ids.push(x.attrs.id); });
console.log(JSON.stringify({ defs, ids, usesShade: ids.includes("lh-sh-cel") }));''')
        self.assertEqual(got["defs"], 1)
        self.assertTrue(got["usesShade"])

    def test_every_url_a_badge_draws_with_is_defined_in_the_shared_defs(self):
        got = js('''
const defsSvg = Rig.dogSvg({}, {}); const defined = new Set(); walk(defsSvg, (x) => { if (x.attrs.id) defined.add(x.attrs.id); });
const missing = new Set();
for (const style of Rig.STYLES) for (const bg of Object.keys(Av.BACKGROUNDS)) for (const pose of Rig.POSES) {
  const svg = Rig.dogSvg({ style, bg, head: "visor", neck: "collar", body: "hoodie", face: "sunglasses" }, { breed: "mastiff", pose });
  walk(svg, (x) => { for (const v of Object.values(x.attrs)) { const m = /url\\(#([\\w-]+)\\)/.exec(String(v)); if (m && !defined.has(m[1])) missing.add(m[1]); if (x.tag === "use" && x.attrs.href && !defined.has(x.attrs.href.slice(1))) missing.add(x.attrs.href); } });
}
console.log(JSON.stringify([...missing]));''')
        self.assertEqual(got, [])


class TheBudgetAndTheMotion(unittest.TestCase):
    FILES = ("dog-art.js", "dog-breeds.js", "dog-defs.js", "dog-face.js", "dog-accessories.js", "dog-styles.js", "dog-rig.js", "dog-look.js",
             "dog-locker.js", "dog-avatar.js")

    def test_the_whole_illustration_code_is_far_under_120kb_gzipped(self):
        blob = b"".join((JS / name).read_bytes() for name in self.FILES)
        gz = len(gzip.compress(blob, 9))
        self.assertLess(gz, 120 * 1024, f"{gz} bytes gzipped")

    def test_no_external_assets_no_script_tags_in_the_rig(self):
        for name in self.FILES:
            src = (JS / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertNotRegex(src, r"https?://(?!www\.w3\.org)", "no fetched asset")
                self.assertNotRegex(src, r"<script|\bfetch\(|\bnew Image\(|<image\b|<foreignObject", "nothing raster, nothing fetched")

    def test_the_rig_schedules_nothing_and_every_dog_animation_is_in_the_reduced_motion_block(self):
        for name in ("dog-art.js", "dog-breeds.js", "dog-defs.js", "dog-face.js", "dog-accessories.js", "dog-styles.js"):
            src = (JS / name).read_text(encoding="utf-8")
            self.assertNotRegex(src, r"setTimeout|setInterval|requestAnimationFrame|\.animate\(", name)
        css = re.sub(r"/\*.*?\*/", "", (ROOT / "web" / "css" / "lh.css").read_text(encoding="utf-8"), flags=re.S)
        motion = css.index("@media (prefers-reduced-motion: no-preference)")
        head = css[:motion]
        for name in ("dk-glint", "dk-rage", "dk-pulse", "dk-breathe", "dk-twinkle"):
            self.assertNotRegex(head, rf"animation[^;]*{name}", f"{name} is used outside the reduced-motion block")
            self.assertRegex(css[motion:], rf"animation: {name}")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLockerRoomPicksStyleAndBreed(unittest.TestCase):
    def test_the_locker_shows_three_style_cards_and_a_breed_grid_that_starts_on_the_name(self):
        out = page(dog_routes(), queries=[
            q("styles", "[data-group='style'] " + hook("locker-opt"), "count"),
            q("breeds", "[data-group='breed'] " + hook("locker-opt"), "count"),
            q("style", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-style"),
            q("note", hook("locker-breed"))])
        f = out["final"]
        self.assertEqual(f["styles"], 3)
        self.assertEqual(f["breeds"], 34, "the name's own plus the 33 breeds")
        self.assertEqual(f["style"], "mascot")
        self.assertIn("from the name", f["note"])

    def test_picking_a_style_and_a_breed_redraws_the_stage_and_saving_sends_both(self):
        out = page(dog_routes(), actions=[
            dict(do="click", sel="[data-group='style'] " + hook("locker-opt") + "[data-value='elite']", wait=20, capture=[
                q("style", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-style"),
                q("pressed", "[data-group='style'] " + hook("locker-opt") + "[data-value='elite']", "attr", attr="aria-pressed")]),
            dict(do="click", sel="[data-group='breed'] " + hook("locker-opt") + "[data-value='doberman']", wait=20, capture=[
                q("breed", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-breed"),
                q("note", hook("locker-breed")), q("dirty", hook("locker-dirty"), "hidden")]),
            dict(do="click", sel=hook("locker-save"), wait=80)])
        self.assertEqual(out["captures"]["0"]["style"], "elite")
        self.assertEqual(out["captures"]["0"]["pressed"], "true")
        c = out["captures"]["1"]
        self.assertEqual(c["breed"], "doberman")
        self.assertIn("Doberman", c["note"])
        self.assertIn("your pick", c["note"])
        self.assertFalse(c["dirty"], "the unsaved-changes note shows")
        put = [p for p in out["posts"] if p["method"] == "PUT"][0]
        self.assertEqual(put["url"], f"/hounds/{HID}/look")
        self.assertEqual((put["body"]["look"]["style"], put["body"]["look"]["breed"]), ("elite", "doberman"))

    def test_choosing_from_the_name_again_puts_the_dogs_own_breed_back(self):
        out = page(dog_routes(), actions=[
            dict(do="click", sel="[data-group='breed'] " + hook("locker-opt") + "[data-value='mastiff']", wait=20),
            dict(do="click", sel="[data-group='breed'] " + hook("locker-opt") + "[data-value='auto']", wait=20, capture=[
                q("breed", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-breed"), q("note", hook("locker-breed"))])])
        c = out["captures"]["1"]
        self.assertNotEqual(c["breed"], "mastiff")
        self.assertIn("from the name", c["note"])

    def test_randomize_keeps_the_dogs_breed_and_rolls_a_whitelisted_style(self):
        out = page(dog_routes(), actions=[
            dict(do="click", sel="[data-group='breed'] " + hook("locker-opt") + "[data-value='pitbull']", wait=20),
            dict(do="click", sel=hook("locker-random"), wait=30, capture=[
                q("breed", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-breed"),
                q("style", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-style")])])
        c = out["captures"]["1"]
        self.assertEqual(c["breed"], "pitbull")
        self.assertIn(c["style"], STYLES)

    def test_the_new_neck_pieces_are_options_with_a_small_dog_each(self):
        out = page(dog_routes(), queries=[q("neck", "[data-group='neck'] " + hook("locker-opt"), "count"),
                                          q("dogs", "[data-group='neck'] " + hook("locker-opt") + " svg.dk-badge", "count")],
                   actions=[dict(do="click", sel="[data-group='neck'] " + hook("locker-opt") + "[data-value='bandana']", wait=20, capture=[
                       q("neck", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-neck")])])
        self.assertEqual(out["final"]["neck"], 4)
        self.assertEqual(out["final"]["dogs"], 4)
        self.assertEqual(out["captures"]["0"]["neck"], "bandana")


if __name__ == "__main__":
    unittest.main()
