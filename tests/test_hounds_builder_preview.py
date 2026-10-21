"""The builder's live dog (round 2, 2026-10-19): a large preview that reacts to the name, the colour and how much has been said.

The critic: "sidebar cards flat/empty; colour/badge pickers a different palette from the dog; dog preview tiny. Large live-updating dog
preview (renderDog) that reacts to name/colour/look choices; pickers share the dog palette." The preview is 176px; a breed word in the
name picks that breed; the coat follows the name; the backdrop follows the colour; each swatch is drawn as the dog backdrop nearest to
its colour; a new dog is saved with the look that was in the preview (a best-effort PUT /hounds/{id}/look after the create).
"""

from __future__ import annotations

import re
import unittest

from tests.hounds_web_runner import HAS_NODE, WEB
from tests.test_hounds_builder_web import CLICK_BLANK, SIGNED, base_routes, build, english_answer, posts_to, q

CSS = (WEB / "css" / "studio.css").read_text(encoding="utf-8")
JS = (WEB / "js" / "hounds-build.js").read_text(encoding="utf-8")
HTML = (WEB / "build-a-hound.html").read_text(encoding="utf-8")

PREVIEW = [q("breed", "[data-hook='dog-preview-dog'] svg", "attrs", attr="data-breed"), q("bg", "[data-hook='dog-preview-dog'] svg", "attrs", attr="data-bg"),
           q("coat", "[data-hook='dog-preview-dog'] svg", "attrs", attr="data-coat"), q("size", "[data-hook='dog-preview-dog'] svg", "attrs", attr="width"),
           q("pose", "[data-hook='dog-preview-dog']", "attr", attr="data-pose"), q("note", "[data-hook='dog-preview-breed']")]


def typed(name):
    return dict(do="set", sel="[data-hook='f-name']", value=name)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLiveDog(unittest.TestCase):
    def test_the_preview_is_large(self):
        out = build(actions=[CLICK_BLANK], queries=PREVIEW)
        self.assertEqual(out["final"]["size"], ["176"])
        self.assertRegex(CSS, r"\.bd-dog--stage \.bd-dog__dog svg \{ width: 176px; height: 176px;")

    def test_a_breed_word_in_the_name_picks_that_breed_and_the_note_says_where_it_came_from(self):
        for name, breed, label in (("Husky Harry", "husky", "Husky"), ("Professor Poodle", "poodle", "Poodle"), ("Cora the Corgi", "corgi", "Corgi")):
            with self.subTest(name=name):
                f = build(actions=[CLICK_BLANK, typed(name)], queries=PREVIEW)["final"]
                self.assertEqual(f["breed"], [breed])
                self.assertIn(f"{label}, from the name", f["note"])

    def test_a_name_without_a_breed_draws_a_retriever_and_says_the_breed_comes_with_the_dog(self):
        f = build(actions=[CLICK_BLANK, typed("Jsmooth")], queries=PREVIEW)["final"]
        self.assertEqual(f["breed"], ["retriever"])
        self.assertIn("The breed comes with the hound", f["note"])

    def test_the_coat_follows_the_name(self):
        coats = {build(actions=[CLICK_BLANK, typed(n)], queries=PREVIEW)["final"]["coat"][0] for n in ("Ace", "Bo", "Cleo", "Dash", "Echo", "Fig", "Gus", "Hank")}
        self.assertGreaterEqual(len(coats), 3, "different names are different-coloured dogs")

    def test_the_backdrop_follows_the_colour_and_the_swatch_is_the_same_backdrop(self):
        expect = {"sky": "navy", "mint": "forest", "violet": "violet", "lime": "forest", "crimson": "maroon", "ember": "sand"}
        for color, bg in expect.items():
            with self.subTest(color=color):
                out = build(actions=[CLICK_BLANK, typed("Rex"), dict(do="click", sel=f"[data-color='{color}']", wait=40)],
                            queries=PREVIEW + [q("swatch", f"[data-color='{color}']", "attr", attr="data-bg")])
                self.assertEqual(out["final"]["bg"], [bg])
                self.assertEqual(out["final"]["swatch"], bg, "the swatch is drawn as the backdrop the dog will wear")

    def test_the_pose_follows_how_much_has_been_said(self):
        empty = build(queries=PREVIEW)["final"]["pose"]
        named = build(actions=[CLICK_BLANK, typed("Rex")], queries=PREVIEW)["final"]["pose"]
        self.assertEqual(empty, "thinking")
        self.assertIn(named, ("idle", "happy"))

    def test_the_sidebar_cards_each_have_a_dog(self):
        out = build(queries=[q("dogs", ".bd-side__dog svg.dk-badge", "count"), q("poses", ".bd-side__dog svg.dk-badge", "attrs", attr="data-pose")])
        self.assertEqual(out["final"]["dogs"], 2)
        self.assertEqual(HTML.count("data-side-dog="), 2)
        self.assertRegex(CSS, r"\.hounds-page \.bd-side \.hd-panel \{[^}]*min-height: 148px")


@unittest.skipUnless(HAS_NODE, "node not installed")
class ANewDogKeepsItsPreviewLook(unittest.TestCase):
    TEXT = "bet home underdogs between +120 and +200 when they're on 2+ days rest. max 2 bets a day"

    def test_after_the_create_the_look_that_was_in_the_preview_is_saved_to_the_dog(self):
        routes = base_routes(**{"POST /hounds/english": [200, english_answer(self.TEXT)], "POST /hounds": [200, {"hound": {"id": "u-x", "name": "Husky Harry"}}],
                                "PUT /hounds/u-x/look": [200, {"ok": True}]})
        out = build(routes, **SIGNED, actions=[
            dict(do="set", sel="[data-hook='english-input']", value=self.TEXT), dict(do="click", sel="[data-hook='english-go']", wait=300),
            typed("Husky Harry"), dict(do="click", sel="[data-color='sky']", wait=30), dict(do="click", sel="[data-hook='build-submit']", wait=300)],
            queries=PREVIEW)
        puts = [p for p in out["posts"] if p["method"] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertTrue(puts[0]["url"].endswith("/hounds/u-x/look"))
        look = puts[0]["body"]["look"]
        self.assertEqual(look["bg"], "navy")
        self.assertEqual((look["head"], look["face"], look["neck"], look["body"]), ("none", "none", "none", "none"), "cosmetic only: no gear")
        self.assertEqual(look["coat"], out["final"]["coat"][0], "the saved coat is the previewed coat")
        self.assertEqual(len(posts_to(out, "/hounds")), 1)

    def test_a_failing_look_save_does_not_fail_the_create(self):
        routes = base_routes(**{"POST /hounds/english": [200, english_answer(self.TEXT)], "POST /hounds": [200, {"hound": {"id": "u-x", "name": "Rex"}}],
                                "PUT /hounds/u-x/look": [500, {"detail": "boom"}]})
        out = build(routes, **SIGNED, actions=[
            dict(do="set", sel="[data-hook='english-input']", value=self.TEXT), dict(do="click", sel="[data-hook='english-go']", wait=300),
            typed("Rex"), dict(do="click", sel="[data-hook='build-submit']", wait=300)], queries=[q("msg", "[data-hook='build-message']")])
        self.assertIn("is in the kennel", out["final"]["msg"])


class TheScripts(unittest.TestCase):
    def test_the_mapping_is_by_hue_and_stays_inside_the_dog_palette(self):
        self.assertIn("export function nearestBackground", JS)
        self.assertIn("BACKGROUNDS", JS)
        self.assertRegex(JS, r'data-bg": nearestBackground\(c\.hex\)')
        self.assertRegex(CSS, r"\.hounds-page \.bd-swatch \{[^}]*linear-gradient\(180deg, var\(--bg1")


if __name__ == "__main__":
    unittest.main()
