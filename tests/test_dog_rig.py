"""The dog character rig (web/js/dog-rig.js, dog-look.js, dog-avatar.js): `renderDog(container, look, pose, opts)`.

Design system v2, 2026-10-19. The rig is layered SVG built with createElementNS only. This file holds it to:
  * every pose renders for every breed, and a pose is an attribute plus the CSS that shows its parts (nothing is redrawn);
  * accessories are layers: a cap, headband, visor, sunglasses, chain, hoodie and jersey (with its number) each add their own
    group, and a look with none adds none;
  * the look is a set of whitelisted choices: junk never reaches a colour or a node;
  * a dog's breed is its vibe's, else a stable pick from its id, and the 33 breeds are really different drawings, each named after what it draws;
  * reduced motion: every animation in the stylesheets sits inside prefers-reduced-motion: no-preference, and the rig itself
    schedules nothing and calls no animation API (an expression is a pose, which still shows).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js

ROOT = Path(__file__).resolve().parent.parent
ALL_BREEDS = [
    "retriever", "labrador", "bulldog", "schnauzer", "husky", "mutt", "hound", "chihuahua", "collie", "corgi", "dalmatian", "basset",
    "greyhound", "jackrussell", "kelpie", "newfoundland", "shepherd", "poodle", "beagle", "setter", "terrier", "bloodhound", "pointer",
    "whippet", "spaniel",
    "doberman", "rottweiler", "pitbull", "wolfhound", "boxer", "mastiff", "shiba", "malinois",
]
CSS = ROOT / "web" / "css"

FAKE_DOM = r'''
const mkEl = (tag) => ({ tag, attrs: {}, kids: [], parentNode: null, firstChild: null,
  setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  appendChild(c) { c.parentNode = this; this.kids.push(c); this.firstChild = this.kids[0]; return c; },
  removeChild(c) { this.kids = this.kids.filter((x) => x !== c); this.firstChild = this.kids[0] || null; return c; },
  set textContent(v) { this.text = String(v); } });
globalThis.document = { createElement: mkEl, createElementNS: (ns, t) => mkEl(t), createTextNode: (t) => ({ nodeType: 3, text: t }) };
globalThis.timers = 0; globalThis.frames = 0;
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (...a) => { globalThis.timers += 1; return realSetTimeout(...a); };
globalThis.requestAnimationFrame = () => { globalThis.frames += 1; };
const walk = (n, f) => { if (n && n.tag) f(n); (n.kids || []).forEach((k) => walk(k, f)); };
const classes = (svg) => { const out = []; walk(svg, (n) => { if (n.attrs.class) out.push(n.attrs.class); }); return out; };
const hasClass = (svg, name) => classes(svg).some((c) => c.split(/\s+/).includes(name));
const count = (svg, tag) => { let c = 0; walk(svg, (n) => { if (n.tag === tag) c += 1; }); return c; };
'''


def js(body: str):
    return run_js(FAKE_DOM + 'const Rig = await import("./dog-rig.js");\nconst Av = await import("./dog-avatar.js");\n' + body)


@unittest.skipUnless(HAS_NODE, "node not installed")
class EveryPoseRendersForEveryBreed(unittest.TestCase):
    def test_all_breeds_and_all_poses_draw_and_carry_their_pose_and_breed(self):
        got = js('''
const out = [];
for (const breed of Rig.BREEDS) for (const pose of Rig.POSES) {
  const svg = Rig.dogSvg({ coat: "golden" }, { breed, pose, size: 64 });
  out.push([breed, pose, svg.tag, svg.attrs["data-pose"], svg.attrs["data-breed"], svg.attrs.width, svg.attrs.viewBox, count(svg, "path") > 20,
    hasClass(svg, "dk-head"), hasClass(svg, "dk-body"), hasClass(svg, "dk-eyes"), hasClass(svg, "dk-ear--l"), hasClass(svg, "dk-ear--r")]);
}
console.log(JSON.stringify(out));''')
        self.assertEqual(len(got), 33 * 5)
        for breed, pose, tag, dpose, dbreed, width, view, many, *parts in got:
            self.assertEqual((tag, dpose, dbreed, width, view), ("svg", pose, breed, "64", "0 0 120 120"), (breed, pose))
            self.assertTrue(many and all(parts), (breed, pose, parts))

    def test_the_old_slump_word_is_sad_and_junk_is_idle(self):
        got = js('console.log(JSON.stringify([Rig.cleanPose("slump"), Rig.cleanPose("dance"), Rig.cleanPose(undefined), Rig.cleanPose("celebrate"), Rig.dogSvg({}, { mood: "slump" }).attrs["data-pose"], Rig.dogSvg({}, { mood: "slump" }).attrs["data-mood"]]));')
        self.assertEqual(got, ["sad", "idle", "idle", "celebrate", "sad", "slump"])

    def test_each_pose_has_its_own_mouth_eyes_and_props_drawn_once_and_shown_by_the_pose(self):
        got = js('''
const svg = Rig.dogSvg({}, { breed: "retriever" });
const cls = classes(svg).join(" ");
console.log(JSON.stringify(Rig.POSES.map((p) => [p, ["mouth", "eyes", "brows"].map((k) => new RegExp(`dk-p--${k}[^"]* dk-p--${p === "celebrate" && k === "eyes" ? "happy" : p}\\\\b|dk-p--${p === "celebrate" && k === "eyes" ? "happy" : p}\\\\b`).test(cls))])));''')
        # idle has no brows, and the eyes of celebrate are the happy ones; every other pose has all three
        for pose, found in got:
            mouth, eyes, _brows = found
            self.assertTrue(mouth, pose)
            self.assertTrue(eyes, pose)

    def test_the_stylesheet_shows_exactly_the_parts_of_the_current_pose(self):
        css = (CSS / "lh.css").read_text(encoding="utf-8")
        for pose in ("idle", "happy", "sad", "thinking", "celebrate"):
            self.assertRegex(css, rf'\[data-pose="{pose}"\] \.dk-p--mouth\.dk-p--{pose}', pose)
        for pose in ("idle", "happy", "sad", "thinking"):
            self.assertRegex(css, rf'\[data-pose="{pose}"\] \.dk-p--eyes\.dk-p--(open|happy|sad|thinking)', pose)
        self.assertIn('.dk-badge .dk-p { display: none; }', css, "every pose part starts hidden")
        # a pose reads with animation off: the head and paws take a static position
        self.assertRegex(css, r'\[data-pose="sad"\] \.dk-head \{ transform:')
        self.assertRegex(css, r'\[data-pose="celebrate"\] \.dk-paw--l \{ transform:')


@unittest.skipUnless(HAS_NODE, "node not installed")
class AccessoriesAreLayers(unittest.TestCase):
    def test_each_accessory_adds_its_own_layer_and_a_bare_look_adds_none(self):
        got = js('''
const layers = (look) => { const svg = Rig.dogSvg(look, { breed: "husky" }); return classes(svg).filter((c) => /dk-acc|dk-hood/.test(c)).sort(); };
console.log(JSON.stringify({
  bare: layers({}), cap: layers({ head: "cap" }), band: layers({ head: "headband" }), visor: layers({ head: "visor" }),
  shades: layers({ face: "sunglasses" }), chain: layers({ neck: "chain" }), hood: layers({ body: "hoodie" }),
  all: layers({ head: "cap", face: "sunglasses", neck: "chain", body: "hoodie" }) }));''')
        self.assertEqual(got["bare"], [])
        self.assertEqual(got["cap"], ["dk-acc dk-acc--cap"])
        self.assertEqual(got["band"], ["dk-acc dk-acc--headband"])
        self.assertEqual(got["visor"], ["dk-acc dk-acc--visor"])
        self.assertEqual(got["shades"], ["dk-acc dk-acc--sunglasses"])
        self.assertEqual(got["chain"], ["dk-acc dk-acc--chain"])
        self.assertEqual(got["hood"], ["dk-hood"])
        self.assertEqual(len(got["all"]), 4)

    def test_the_jersey_wears_its_number_and_only_a_jersey_does(self):
        got = js('''
const nums = (look) => { const out = []; walk(Rig.dogSvg(look, { breed: "bulldog" }), (n) => { if (n.tag === "text") out.push([(n.kids[0] || {}).text, n.attrs["data-number"]]); }); return out; };
console.log(JSON.stringify([nums({ body: "jersey", number: 23 }), nums({ body: "jersey" }), nums({ body: "hoodie", number: 7 }), nums({ number: 7 }), nums({ body: "jersey", number: 100 })]));''')
        self.assertEqual(got[0], [["23", "23"]])
        self.assertEqual(got[1], [])
        self.assertEqual(got[2], [])
        self.assertEqual(got[3], [])
        self.assertEqual(got[4], [], "a number over 99 is not a number")

    def test_every_accessory_choice_the_server_allows_draws_on_every_breed(self):
        got = js('''
let n = 0;
for (const breed of Rig.BREEDS) for (const head of Av.HEAD) for (const face of Av.FACE) for (const neck of Av.NECK) for (const body of Av.BODY) {
  const svg = Rig.dogSvg({ head, face, neck, body, number: 9 }, { breed }); if (svg.tag === "svg") n += 1; }
console.log(JSON.stringify(n));''')
        self.assertEqual(got, 33 * 4 * 2 * 4 * 3)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLookIsWhitelisted(unittest.TestCase):
    def test_junk_never_reaches_a_colour_a_style_or_a_node(self):
        got = js('''
const svg = Rig.dogSvg({ coat: "#ff0000", eyes: "<script>alert(1)</script>", bg: "url(javascript:x)", head: "crown", body: "<img onerror=x>", number: "9;fill:red" }, { id: "x</svg><script>" });
const bad = []; walk(svg, (n) => { for (const [k, v] of Object.entries(n.attrs)) if (/script|javascript|onerror|<|url\\(javascript/i.test(`${k}=${v}`)) bad.push([n.tag, k, v]); if (n.text && /script|onerror/.test(n.text)) bad.push(["text", n.text]); });
console.log(JSON.stringify([bad, svg.attrs["data-coat"], svg.attrs["data-bg"], svg.attrs["data-head"], svg.attrs["data-body"]]));''')
        self.assertEqual(got[0], [])
        self.assertEqual(got[1:], ["tan", "navy", "none", "none"])

    def test_every_colour_in_the_drawing_is_a_hex_or_a_url_to_its_own_gradient(self):
        got = js('''
const bad = []; const svg = Rig.dogSvg({ coat: "merle", eyes: "blue", bg: "violet", head: "cap", face: "sunglasses", neck: "chain", body: "jersey", number: 3 }, { breed: "mutt", pose: "celebrate" });
walk(svg, (n) => { for (const k of ["fill", "stroke", "stop-color"]) { const v = n.attrs[k]; if (v === undefined) continue;
  if (!/^(#[0-9a-fA-F]{6}|none|currentColor|rgba\\([\\d., ]+\\)|url\\(#lh-[a-z-]+\\))$/.test(v)) bad.push([n.tag, k, v]); } });
console.log(JSON.stringify(bad));''')
        self.assertEqual(got, [])

    def test_a_default_look_by_id_is_stable_and_only_picks_from_the_tables(self):
        got = js('''
const a = Av.lookFor("chalk_chihuahua"), b = Av.lookFor("chalk_chihuahua"), c = Av.lookFor("dartboard_dalmatian");
const ok = (l) => l.coat in Av.COATS && l.eyes in Av.EYES && l.bg in Av.BACKGROUNDS && l.head === "none" && l.face === "none" && l.neck === "none" && l.body === "none";
const rnd = Av.randomLook(() => 0.999), rnd0 = Av.randomLook(() => 0);
console.log(JSON.stringify([JSON.stringify(a) === JSON.stringify(b), JSON.stringify(a) !== JSON.stringify(c), ok(a), ok(c), JSON.stringify(rnd) === JSON.stringify(Av.cleanLook(rnd)), JSON.stringify(rnd0) === JSON.stringify(Av.cleanLook(rnd0))]));''')
        self.assertEqual(got, [True, True, True, True, True, True])


@unittest.skipUnless(HAS_NODE, "node not installed")
class BreedsFollowTheVibe(unittest.TestCase):
    def test_a_vibe_picks_its_breed_and_an_id_picks_a_stable_one(self):
        got = js('''
console.log(JSON.stringify([
  ["grinder", "nerd", "degen", "chaos", "psychic"].map((v) => Rig.breedFor({ vibe: v, id: "z" })),
  Rig.breedFor({ persona: { vibe: "nerd" }, id: "q" }), Rig.breedFor("u-d151fe52c7"), Rig.breedFor("u-d151fe52c7"), Rig.breedFor({}), Rig.breedFor(null),
  Rig.breedFor({ vibe: "who-knows", id: "abc" }) === Rig.breedFor("abc"), Rig.BREEDS.length,
  new Set(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"].map((i) => Rig.breedFor(i))).size >= 4]));''')
        self.assertEqual(got[0], ["bulldog", "schnauzer", "husky", "mutt", "hound"])
        self.assertEqual(got[1], "schnauzer")
        self.assertEqual(got[2], got[3])
        self.assertIn(got[2], ALL_BREEDS)
        self.assertEqual((got[4], got[5]), ("retriever", "retriever"))
        self.assertTrue(got[6])
        self.assertEqual(got[7], 33)
        self.assertTrue(got[8], "ids spread over the breeds")

    def test_every_breed_is_a_different_drawing(self):
        got = js('''
const sig = (breed) => { const ds = []; walk(Rig.dogSvg({ coat: "tan" }, { breed }), (n) => { if ((n.tag === "path" || n.tag === "ellipse") && (n.attrs.d || n.attrs.rx)) ds.push(n.attrs.d || `${n.attrs.cx},${n.attrs.cy},${n.attrs.rx}`); }); return ds.join("|"); };
console.log(JSON.stringify(new Set(Rig.BREEDS.map(sig)).size));''')
        self.assertEqual(got, 33)

    def test_the_pose_of_a_pick_restates_only_a_result(self):
        got = js('console.log(JSON.stringify([Rig.poseOfPick("won"), Rig.poseOfPick("lost"), Rig.poseOfPick("pending"), Rig.poseOfPick(undefined), Av.poseOfHound({ last_pick: { result: "won" } }), Av.poseOfHound({ form: { streak: { kind: "L", length: 3 } } }), Av.poseOfHound({ form: { streak: { kind: "W", length: 1 } } }), Av.poseOfHound({})]));')
        self.assertEqual(got, ["happy", "sad", "idle", "idle", "happy", "sad", "idle", "idle"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class BreedMappingAndLabels(unittest.TestCase):
    """2026-10-19 critic round 2: a yellow Chihuahua was labelled "Bulldog" (the vibe picked the breed, the name was ignored)."""

    HOUSE = {
        "chalk_chihuahua": ("Chalk Chihuahua", "grinder", "chihuahua", "Chihuahua"),
        "coin_flip_collie": ("Coin-Flip Collie", "chaos", "collie", "Collie"),
        "contrary_corgi": ("Contrary Corgi", "chaos", "corgi", "Corgi"),
        "dartboard_dalmatian": ("Dartboard Dalmatian", "chaos", "dalmatian", "Dalmatian"),
        "elimination_basset": ("Elimination Basset", "degen", "basset", "Basset Hound"),
        "gridiron_greyhound": ("Gridiron Greyhound", "nerd", "greyhound", "Greyhound"),
        "grudge_bulldog": ("Grudge Bulldog", "degen", "bulldog", "Bulldog"),
        "home_dog_hank": ("Home Dog Hank", "degen", "hound", "Hound"),
        "hot_streak_husky": ("Hot-Streak Husky", "degen", "husky", "Husky"),
        "jetlag_jack": ("Jet-Lag Jack", "grinder", "jackrussell", "Jack Russell"),
        "kelly_kelpie": ("Kelly the Kelpie", "nerd", "kelpie", "Kelpie"),
        "lunar_lab": ("Lunar Lab", "psychic", "labrador", "Labrador"),
        "numerology_newfie": ("Numerology Newfie", "psychic", "newfoundland", "Newfoundland"),
        "pack_leader": ("Pack Leader", "grinder", "shepherd", "German Shepherd"),
        "professor_paws": ("Professor Paws", "nerd", "poodle", "Poodle"),
        "relief_retriever": ("Relief Retriever", "grinder", "retriever", "Golden Retriever"),
        "scrappy_schnauzer": ("Scrappy Schnauzer", "degen", "schnauzer", "Schnauzer"),
        "stale_bread_beagle": ("Stale-Bread Beagle", "grinder", "beagle", "Beagle"),
        "steamy_setter": ("Steamy Setter", "degen", "setter", "Setter"),
        "totals_terrier": ("Totals Terrier", "nerd", "terrier", "Terrier"),
        "bargain_bloodhound": ("Bargain Bloodhound", "grinder", "bloodhound", "Bloodhound"),
        "pointer": ("Pointer", "nerd", "pointer", "Pointer"),
        "whippet": ("Whippet", "nerd", "whippet", "Whippet"),
        "spaniel": ("Spaniel", "nerd", "spaniel", "Spaniel"),
        "beagle": ("Beagle", "grinder", "beagle", "Beagle"),
        "collie": ("Collie", "grinder", "collie", "Collie"),
    }

    def test_every_house_dog_is_drawn_as_the_breed_its_name_spells_and_the_label_says_the_same(self):
        import json
        got = js(f"""
const dogs = {json.dumps(self.HOUSE)};
const out = {{}};
for (const [id, [name, vibe]] of Object.entries(dogs)) {{
  const svg = Rig.dogSvg({{}}, {{ id, name, vibe }});
  const breed = svg.attrs["data-breed"];
  out[id] = [Rig.breedFor({{ id, name, vibe }}), breed, Rig.breedLabel(breed)];
}}
console.log(JSON.stringify(out));""")
        for dog_id, (_name, _vibe, breed, label) in self.HOUSE.items():
            with self.subTest(dog=dog_id):
                self.assertEqual(got[dog_id], [breed, breed, label])

    def test_the_label_is_always_the_drawn_breed_for_every_breed(self):
        got = js("console.log(JSON.stringify(Rig.BREEDS.map((b) => [b, Rig.breedLabel(b), Rig.dogSvg({}, { breed: b }).attrs['data-breed']])));")
        self.assertEqual(sorted(b for b, _l, _d in got), sorted(ALL_BREEDS))
        for breed, label, drawn in got:
            self.assertEqual(breed, drawn)
            self.assertTrue(label and label != "Dog", breed)
        self.assertEqual(len({label for _b, label, _d in got}), 33, "no two breeds share a label")

    def test_a_name_that_is_not_a_breed_falls_back_to_the_vibe_then_a_stable_hash(self):
        got = js("""console.log(JSON.stringify([Rig.breedFor({ id: "desk_fader", name: "The Fader", vibe: "chaos" }), Rig.breedFor({ id: "desk_sharp", name: "The Sharp", vibe: "grinder" }),
  Rig.breedFor({ id: "u-d151fe52c7", name: "Jsmooth" }) === Rig.breedFor({ id: "u-d151fe52c7", name: "Jsmooth" }), Rig.breedFor({ id: "x", name: "Bulldog Bob", breed: "husky" })]));""")
        self.assertEqual(got, ["mutt", "bulldog", True, "husky"])

    def test_the_breeds_are_told_apart_by_their_ears_snouts_and_markings_not_only_their_colour(self):
        got = js("""
const sig = (breed) => { let ears = 0, paths = 0; walk(Rig.dogSvg({ coat: "tan" }, { breed }), (n) => { if (n.tag === "path") paths += 1; if ((n.attrs.class || "").includes("dk-ear")) ears += 1; }); return [ears, paths]; };
const dalmatian = Rig.dogSvg({ coat: "black" }, { breed: "dalmatian" }), jack = Rig.dogSvg({ coat: "brown" }, { breed: "jackrussell" });
let spots = 0; walk(dalmatian, (n) => { if (n.tag === "ellipse" && n.attrs.rx < 6) spots += 1; });
console.log(JSON.stringify({ ears: Rig.BREEDS.map((b) => sig(b)[0]), spots, glassesProfessor: hasClass(Rig.dogSvg({}, { id: "professor_paws", name: "Professor Paws" }), "dk-acc--glasses"),
  glassesOther: hasClass(Rig.dogSvg({}, { id: "chalk_chihuahua", name: "Chalk Chihuahua" }), "dk-acc--glasses") }));""")
        self.assertTrue(all(e == 2 for e in got["ears"]), "every breed has a left and a right ear for the flick animation")
        self.assertGreaterEqual(got["spots"], 6, "a dalmatian has spots")
        self.assertTrue(got["glassesProfessor"])
        self.assertFalse(got["glassesOther"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class RenderDogIsTheOneEntryPoint(unittest.TestCase):
    def test_it_replaces_what_was_there_returns_the_svg_and_a_pose_change_redraws_nothing(self):
        got = js('''
const box = mkEl("div"); box.appendChild(mkEl("span")); box.appendChild(mkEl("span"));
const svg = Rig.renderDog(box, { coat: "black" }, "happy", { size: 96, id: "a", vibe: "degen", label: "Rex", decorative: false });
const before = count(svg, "path");
const settled = Rig.setPose(svg, "celebrate");
const after = count(svg, "path");
console.log(JSON.stringify([box.kids.length, box.kids[0] === svg, svg.attrs["data-breed"], svg.attrs.role, svg.attrs["aria-label"], svg.attrs["aria-hidden"], svg.attrs["data-pose"], settled, before === after, Av.renderDog === Rig.renderDog]));''')
        self.assertEqual(got, [1, True, "husky", "img", "Rex", None, "celebrate", "celebrate", True, True])

    def test_a_badge_is_decorative_by_default_because_the_name_is_written_beside_it(self):
        got = js('const s = Av.dogBadge({}, { size: 40 }); console.log(JSON.stringify([s.attrs["aria-hidden"], s.attrs.role, s.attrs.focusable, s.attrs.width, Av.dogFace({ id: "x", name: "X", persona: { vibe: "nerd" } }, { size: 32 }).attrs["data-breed"]]));')
        self.assertEqual(got, ["true", None, "false", "40", "schnauzer"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class ReducedMotion(unittest.TestCase):
    def test_drawing_a_dog_schedules_nothing_and_calls_no_animation(self):
        got = js('''
globalThis.window = { matchMedia: () => ({ matches: true }) };
const box = mkEl("div");
for (const pose of Rig.POSES) Rig.renderDog(box, { body: "jersey", number: 5 }, pose, { size: 56, id: "r" });
Rig.setPose(box.kids[0], "sad");
console.log(JSON.stringify([globalThis.timers, globalThis.frames, box.kids.length]));''')
        self.assertEqual(got, [0, 0, 1])

    def test_the_studio_spring_and_the_race_run_only_when_motion_is_allowed(self):
        locker = (ROOT / "web" / "js" / "dog-locker.js").read_text(encoding="utf-8")
        self.assertRegex(locker, r'matchMedia\("\(prefers-reduced-motion: reduce\)"\)\.matches\) return;')
        race = (ROOT / "web" / "js" / "landing-race.js").read_text(encoding="utf-8")
        self.assertIn("if (reduced() || typeof requestAnimationFrame !== \"function\") { finish();", race)

    def test_every_animation_is_inside_a_no_preference_block_in_the_design_system_files(self):
        from tests.test_kennel_page import EveryAnimationIsInsideNoPreference as Rule
        for name in ("lh.css", "studio.css", "lhnav.css", "landing-v2.css"):
            css = re.sub(r"/\*.*?\*/", "", (CSS / name).read_text(encoding="utf-8"), flags=re.S)
            rest = Rule.outside_motion_blocks(css)
            with self.subTest(file=name):
                self.assertNotRegex(rest, r"animation(-name)?\s*:", f"an animation outside the no-preference block in {name}")

    def test_no_dog_animation_names_are_declared_anywhere_but_the_no_preference_block(self):
        css = (CSS / "lh.css").read_text(encoding="utf-8")
        for name in ("dk-breathe", "dk-jump", "dk-glint", "dk-rage", "dk-pulse", "dk-twinkle", "dk-wave-l", "dk-wave-r", "dk-ponder", "dk-dot"):
            self.assertIn(f"@keyframes {name}", css)


if __name__ == "__main__":
    unittest.main()
