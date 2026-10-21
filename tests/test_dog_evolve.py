"""Send to training as an evolution (web/js/dog-evolve.js) and the version tiers it reveals (web/js/dog-tiers.js).

Owner request 2026-10-21: the training flow was "too quick, not impactful"; it should take longer and land like a Pokemon evolution,
with a visible upgrade. This file holds what must stay true while it does:

  * THE WORDS ARE THE SERVER'S. The one line under the hound and every row of the upgrade card come from the training result's own
    change list (else its spec diff); a result with neither gives no line. Nothing is invented and no "better" is claimed.
  * A VERSION LOOKS LIKE ITS VERSION. The tier art is a pure function of the version number: the same number draws the same
    markup, v1 draws nothing extra, v2 / v3 / v4 / v5 differ, and a version past 5 keeps the platinum look. The breed and the default
    look follow the lineage (root_id), so a trained hound stays the hound it was.
  * THE SEQUENCE NEVER FAKES THE SERVER (the failure, slow-server, skip and reduced-motion paths run in tests/test_hounds_rites_web.py,
    against the pages' own HTML). Here a real Chrome plays the whole thing at 390 px and nothing scrolls sideways at any beat.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
import unittest
from pathlib import Path

from tests import test_hounds_rites_web as rites
from tests.hounds_web_runner import HAS_NODE, run_js
from tests.test_dog_rig import FAKE_DOM
from tests.test_no_horizontal_overflow import CHROME, HERE

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

SERIALIZE = r'''
const ser = (n) => (n && n.tag ? `<${n.tag} ${Object.keys(n.attrs).sort().map((k) => `${k}=${n.attrs[k]}`).join(" ")}>${(n.kids || []).map(ser).join("")}</${n.tag}>` : (n && n.text) || "");
'''


def js(body: str):
    return run_js(FAKE_DOM + SERIALIZE + 'const Ev = await import("./dog-evolve.js");\nconst Av = await import("./dog-avatar.js");\n' + body)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheWordsAreOnlyWhatTheServerChanged(unittest.TestCase):
    def test_every_line_is_one_of_the_servers_changes_and_none_is_added(self):
        for key in ("trained", "light"):
            result = rites.payloads()[key]
            got = js(f"const r = {json.dumps(result)};\nconst lines = Ev.evolveLines(r);\n"
                     "console.log(JSON.stringify({ lines, summary: Ev.summaryLine(lines) }));")
            with self.subTest(result=key):
                self.assertEqual(len(got["lines"]), len([c for c in result["changes"] if c["old_text"] != c["new_text"]]))
                for line, change in zip(got["lines"], result["changes"]):
                    self.assertEqual((line["label"], line["from"], line["to"]), (change["label"], change["old_text"], change["new_text"]))
                    # a phrase is built from the change's own new value and label, and is not a sentence about anything else
                    self.assertIn(change["new_text"], line["phrase"])
                    self.assertNotRegex(line["phrase"], r"\b(better|improv\w*|stronger|profit\w*|edge|win more)\b")
                self.assertTrue(got["summary"].startswith("Training changed: "))
                for line in got["lines"]:
                    self.assertIn(line["phrase"], got["summary"])

    def test_the_known_changes_read_in_the_words_a_bettor_uses(self):
        got = js('''
const mk = (id, label, from, to) => ({ id, label, old_text: from, new_text: to });
const r = { changes: [mk("tighten_band", "Price range", "+100 to +200", "+100 to +180"), mk("fewer_bets", "Most bets a day", "3", "2"),
  mk("drop_sport", "Sports", "MLB and NFL", "MLB"), mk("more_books", "Books quoting at least", "3 books", "4 books"), mk("odd", "Something new", "a", "b")] };
console.log(JSON.stringify(Ev.evolveLines(r).map((l) => l.phrase)));''')
        self.assertEqual(got, ["Price range tightened to +100 to +180", "Max 2 a day", "Sports narrowed to MLB", "Needs 4 books quoting", "Something new: b"])

    def test_nothing_is_invented_when_the_server_changed_nothing_we_can_say(self):
        got = js('''
const out = {
  none: Ev.evolveLines({}), nullish: Ev.evolveLines(null), empty: Ev.evolveLines({ changes: [], diff: [] }),
  same: Ev.evolveLines({ changes: [{ id: "x", label: "Same", old_text: "1", new_text: "1" }] }),
  noNew: Ev.evolveLines({ changes: [{ id: "x", label: "Gone", old_text: "1", new_text: "" }] }),
  junk: Ev.evolveLines({ changes: ["a", 3, null, { label: 7 }] }),
  dup: Ev.evolveLines({ changes: [{ id: "a", label: "L", old_text: "1", new_text: "2" }, { id: "a", label: "L", old_text: "1", new_text: "2" }] }).length,
  diff: Ev.evolveLines({ changes: [], diff: [{ what: "Most bets a day", before: "3", after: "2" }, { what: "Rule 2 removed", before: "x", after: null }] }),
  summaryOfNothing: Ev.summaryLine([]),
};
console.log(JSON.stringify(out));''')
        for key in ("none", "nullish", "empty", "same", "noNew", "junk"):
            self.assertEqual(got[key], [], key)
        self.assertEqual(got["dup"], 1)
        self.assertEqual([(d["label"], d["from"], d["to"]) for d in got["diff"]], [("Most bets a day", "3", "2")], "the spec diff stands in only when the coach's list is empty")
        self.assertEqual(got["summaryOfNothing"], "")

    def test_the_headline_names_the_hound_twice_and_the_version(self):
        self.assertEqual(js('console.log(JSON.stringify(Ev.becameText("Gus", 2)));'), "Gus became Gus v2!")


@unittest.skipUnless(HAS_NODE, "node not installed")
class AVersionLooksLikeItsVersion(unittest.TestCase):
    def test_the_tier_is_a_pure_function_of_the_version_number(self):
        got = js('''
const a = JSON.stringify(Av.versionTier(3)), b = JSON.stringify(Av.versionTier(3));
const bare = ["x", 0, -4, 1.5, null, undefined, NaN, 1000, {}].map((v) => Av.versionTier(v).tier);
console.log(JSON.stringify({ same: a === b, bare, v1: Av.versionTier(1), tiers: [1, 2, 3, 4, 5, 6, 12, 99].map((v) => Av.versionTier(v).tier),
  names: [1, 2, 3, 4, 5].map((v) => Av.versionTier(v).name), chevrons: [1, 2, 3, 4, 5, 6].map((v) => Av.versionTier(v).chevrons),
  parts2: Av.versionTier(2).parts, parts3: Av.versionTier(3).parts, gain: Av.newParts(2, 3), gain12: Av.newParts(5, 6) }));''')
        self.assertTrue(got["same"])
        self.assertEqual(got["bare"], [1] * 9, "a version that is not a whole number of 1 or more is v1: nothing is guessed")
        self.assertEqual(got["v1"]["parts"], [])
        self.assertEqual(got["tiers"], [1, 2, 3, 4, 5, 5, 5, 5])
        self.assertEqual(got["names"], ["Base", "Bronze", "Silver", "Gold", "Platinum"])
        self.assertEqual(got["chevrons"], [0, 1, 2, 3, 4, 4])
        self.assertEqual(got["parts2"], ["Bronze frame", "Rank plate v2", "1 chevron", "Bronze collar"])
        self.assertIn("Star mark", got["parts3"])
        self.assertEqual(got["gain"], got["parts3"], "v3 shares none of v2's pieces")
        self.assertEqual(got["gain12"], ["Rank plate v6"], "past v5 only the plate's number is new")

    def test_the_same_version_draws_the_same_markup_and_v1_adds_nothing(self):
        got = js('''
const look = { coat: "golden", style: "mascot", breed: "retriever" };
const draw = (v, style, size) => ser(Av.dogBadge({ ...look, style: style || look.style }, { size: size || 96, version: v, id: "x" }));
const tierGroups = (v) => { const out = []; walk(Av.dogBadge(look, { size: 96, version: v, id: "x" }), (n) => { if (/dk-tier/.test(n.attrs.class || "")) out.push(n.attrs.class); }); return out; };
const out = {
  stable: [1, 2, 3, 4, 5, 9].map((v) => draw(v) === draw(v)),
  v1IsBare: draw(1) === draw(undefined) && draw(1) === draw("nope"),
  distinct: new Set([1, 2, 3, 4, 5].map((v) => draw(v))).size,
  fiveVsNine: draw(5).replace(/v5/g, "vN").replace(/data-vno=5/g, "x") === draw(9).replace(/v9/g, "vN").replace(/data-vno=9/g, "x"),
  groups1: tierGroups(1), groups2: tierGroups(2), groups3: tierGroups(3).length, groups5: tierGroups(5).length,
  everyStyle: ["mascot", "street", "elite"].map((st) => [draw(1, st) !== draw(2, st), draw(2, st) !== draw(3, st), draw(2, st) === draw(2, st)]),
  small: [draw(1, "mascot", 32) !== draw(2, "mascot", 32), draw(2, "mascot", 32) !== draw(3, "mascot", 32)],
  attrs: [1, 2, 7].map((v) => { const s = Av.dogBadge(look, { size: 96, version: v }); return [s.attrs["data-vno"], s.attrs["data-tier"]]; }),
};
console.log(JSON.stringify(out));''')
        self.assertTrue(all(got["stable"]))
        self.assertTrue(got["v1IsBare"])
        self.assertEqual(got["distinct"], 5, "v1 to v5 each look different")
        self.assertTrue(got["fiveVsNine"], "past v5 only the number on the plate changes")
        self.assertEqual(got["groups1"], [])
        self.assertGreaterEqual(len(got["groups2"]), 3)
        self.assertGreater(got["groups3"], len(got["groups2"]) - 1)
        self.assertGreater(got["groups5"], got["groups3"] - 1)
        for row in got["everyStyle"]:
            self.assertEqual(row, [True, True, True])
        self.assertEqual(got["small"], [True, True], "a 32px badge still shows the tier")
        self.assertEqual(got["attrs"], [["1", "1"], ["2", "2"], ["7", "5"]])

    def test_every_colour_in_a_tier_is_a_hex_or_one_of_the_shared_gradients(self):
        got = js('''
const bad = [];
for (const v of [2, 3, 4, 5, 12]) for (const style of ["mascot", "street", "elite"]) {
  walk(Av.dogBadge({ coat: "merle", style, neck: "none" }, { size: 120, version: v, id: "z" }), (n) => { for (const k of ["fill", "stroke", "stop-color"]) { const x = n.attrs[k]; if (x === undefined) continue;
    if (!/^(#[0-9a-fA-F]{6}|none|currentColor|rgba\\([\\d., ]+\\)|url\\(#lh-[a-z-]+\\))$/.test(x)) bad.push([v, style, n.tag, k, x]); } });
}
console.log(JSON.stringify(bad));''')
        self.assertEqual(got, [])
        defs = (WEB / "js" / "dog-defs.js").read_text(encoding="utf-8")
        for gradient in ("lh-bronze", "lh-platinum"):
            self.assertIn(f'"{gradient}"', defs)

    def test_a_trained_hound_stays_the_breed_and_look_it_was(self):
        got = js('''
const face = (d) => { const s = Av.dogFace(d, { size: 96 }); return [s.attrs["data-breed"], s.attrs["data-coat"], s.attrs["data-eyes"], s.attrs["data-tier"], s.attrs["data-vno"]]; };
const v1 = face({ id: "u-root1", name: "Gus" }), v2 = face({ id: "u-new-id-9", root_id: "u-root1", name: "Gus", version_no: 2 }), v3 = face({ id: "u-newer-id", root_id: "u-root1", name: "Gus", version_no: 3 });
console.log(JSON.stringify({ v1, v2, v3 }));''')
        self.assertEqual(got["v1"][:2], got["v2"][:2])
        self.assertEqual(got["v1"][:2], got["v3"][:2])
        self.assertEqual((got["v1"][3], got["v2"][3], got["v3"][3]), ("1", "2", "3"))

    def test_the_server_sends_the_version_and_the_lineage_the_art_reads(self):
        camp = (ROOT / "src" / "hounds" / "interact" / "camp.py").read_text(encoding="utf-8")
        kennels = (ROOT / "src" / "hounds" / "kennels.py").read_text(encoding="utf-8")
        self.assertIn('"version_no": (dog.hound or {}).get("version_no")', camp)
        self.assertRegex(camp, r'"root_id": dog\.root_id')
        self.assertIn('"root_id": row.get("root_id") or row["id"]', kennels)


class NoWordOfTheSequenceSaysDog(unittest.TestCase):
    def test_what_a_person_reads_says_hound(self):
        for name in ("dog-evolve.js", "dog-tiers.js"):
            src = (WEB / "js" / name).read_text(encoding="utf-8")
            src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
            src = re.sub(r"//.*", "", src)
            for literal in re.findall(r'"([^"\n]*)"|`([^`\n]*)`', src):
                text = re.sub(r"\$\{[^}]*\}", "", "".join(literal))
                if text.startswith("./"):          # an import path, not copy
                    continue
                with self.subTest(file=name, text=text[:40]):
                    self.assertNotRegex(text, r"\bdogs?\b", "user-visible copy says hound")

    def test_the_copy_never_claims_the_new_version_is_better_or_profitable(self):
        src = (WEB / "js" / "dog-evolve.js").read_text(encoding="utf-8")
        shown = " ".join(re.findall(r'text: "([^"]*)"|text: `([^`]*)`', src) and [a or b for a, b in re.findall(r'text: "([^"]*)"|text: `([^`]*)`', src)])
        self.assertIsNone(re.search(r"\b(better|improve\w*|stronger|smarter|profit\w*|edge|ROI|will win|guarantee\w*)\b", shown, re.I), shown)
        self.assertIn("Its new record starts now.", src)
        self.assertNotRegex(src, r"https?://(?!www\.w3\.org)")
        self.assertNotRegex(src, r"<script|import\(\s*[\"']http")

    def test_no_image_file_no_library_and_sound_is_off_until_asked(self):
        src = (WEB / "js" / "dog-evolve.js").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"\.(png|jpe?g|gif|webp|mp3|wav|ogg)\b")
        self.assertIn('"aria-pressed": "false"', src)
        self.assertRegex(src, r"let on = false;")


class ServesTheNewFilesWhereTheyAreRead(unittest.TestCase):
    def test_dog_kit_css_imports_the_evolution_stylesheet_and_it_exists(self):
        self.assertTrue((WEB / "css" / "evolve.css").exists())
        self.assertIn('@import url("evolve.css")', (WEB / "css" / "dog-kit.css").read_text(encoding="utf-8"))

    def test_the_reduced_motion_path_schedules_nothing_before_the_answer(self):
        src = (WEB / "js" / "dog-evolve.js").read_text(encoding="utf-8")
        self.assertIn("if (!reduced) later(TIMING.skipAfter", src)
        self.assertIn("if (reduced) { showCard(false); return; }", src)


def make_handler(api):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, *a):
            pass

        def _json(self, status, payload):
            body = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith("/web/"):
                return super().do_GET()
            hit = api.get(path)
            if hit is None and path.startswith("/hounds/series"):
                hit = (200, {"series": {}})
            if hit is None and path.startswith("/hounds/kennels"):
                hit = (200, {"kennels": [], "count": 0})
            if hit is None and path == "/hounds/looks":
                hit = (200, {"looks": {}})
            self._json(*(hit or (404, {"detail": "not in the fixture"})))

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            hit = api.get("POST " + self.path.split("?")[0])
            self._json(*(hit or (404, {"detail": "not in the fixture"})))

    return Handler


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class TheEvolutionFitsAPhoneAtEveryBeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        from tests import test_kennel_page as kennel_tests
        routes = rites.kennel_routes([kennel_tests.dog("u-1", version_no=1)])
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(routes))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.play = staticmethod(lambda mode: json.loads([ln for ln in subprocess.run(
            ["node", str(HERE / "evolve_390.mjs"), CHROME, cls.base, "-", mode], capture_output=True, text=True, encoding="utf-8", timeout=120).stdout.splitlines()
            if ln.startswith("{")][-1]))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_every_beat_of_the_full_sequence_fits_390_and_all_of_them_play(self):
        out = self.play("full")
        self.assertEqual(out["errors"], [])
        for phase in ("before", "charge", "burst", "reveal", "card"):
            self.assertIn(phase, out["phases"])
        bad = [s for s in out["samples"] if s["sw"] > s["iw"] + 1 or s["sheetSw"] > s["sheetCw"] + 1 or s["wide"]]
        self.assertEqual(bad, [], json.dumps(bad[:3]))

    def test_the_reduced_motion_card_fits_390(self):
        out = self.play("reduced")
        self.assertEqual(out["errors"], [])
        self.assertIn("static", out["phases"])
        self.assertNotIn("charge", out["phases"])
        bad = [s for s in out["samples"] if s["sw"] > s["iw"] + 1 or s["sheetSw"] > s["sheetCw"] + 1 or s["wide"]]
        self.assertEqual(bad, [], json.dumps(bad[:3]))


if __name__ == "__main__":
    unittest.main()
