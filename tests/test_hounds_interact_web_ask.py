"""The two page changes of 2026-10-20, run for real under node (same harness as test_hounds_interact_web.py):

  * the Fire now panel says which of today's games already started BEFORE the headline, and puts a day heading
    ("Thursday") above the picks it lists;
  * an Ask answer that carries pick cards draws them (selection, price, game and time, the reason) in the answer.

Skipped when node is not installed.
"""

from __future__ import annotations

import unittest

from src.hounds.interact import ask
from tests.hounds_web_runner import HAS_NODE
from tests.test_hounds_interact_ask import FIRE_WITH_PICK, context
from tests.test_hounds_interact_web import HID, Payloads, dog_routes, hook, page, q, unleash_day


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFirePanelSaysWhichGamesStarted(unittest.TestCase):
    def payload(self):
        out = Payloads.fire_payload()
        out["slate"] = {"today": "2026-10-20", "today_state": "started",
                        "line": "Tonight's games already started: Tampa Bay Rays @ Cleveland Guardians (8:10 pm ET). "
                                "Next games I can bet: Thursday.",
                        "started": [{"game": "Tampa Bay Rays @ Cleveland Guardians", "start_utc": "2026-10-21T00:10:00Z",
                                     "start_et": "8:10 pm ET"}], "in_window": [], "next_day_label": "Thursday", "days": []}
        out["picks"][0]["day_label"] = "Thursday"
        return out

    def test_the_slate_sentence_comes_first_and_the_picks_sit_under_their_day(self):
        # the visitor's read-only preview
        out = page(dog_routes(owner=False, fire_payload=self.payload()), actions=[dict(do="click", sel=hook("fire-btn"), wait=80, capture=[
            q("slate", hook("fire-slate")), q("headline", hook("fire-headline")), q("day", hook("fire-day")),
            q("picks", hook("fire-pick"), "count"), q("order", ".dk-headline", "texts")])])
        c = out["captures"]["0"]
        self.assertIn("Tonight's games already started: Tampa Bay Rays @ Cleveland Guardians (", c["slate"])
        self.assertIn("Next games I can bet: Thursday.", c["slate"])
        self.assertEqual(c["day"], "Thursday")
        self.assertEqual(c["picks"], 1)
        self.assertEqual(c["order"][0], c["slate"])                  # said first
        self.assertEqual(c["order"][1], c["headline"])

    def test_the_owners_unleash_says_it_first_too(self):
        # the owner's real Unleash (2026-10-22: the same button the studio has) opens on the same sentence
        out = page(dog_routes(unleash_payload=unleash_day(slate=self.payload()["slate"])), actions=[dict(do="click", sel=hook("fire-btn"), wait=120, capture=[
            q("slate", hook("fire-slate")), q("headline", hook("unleash-headline")), q("picks", hook("unleash-pick"), "count"),
            q("order", ".dk-headline", "texts")])])
        c = out["captures"]["0"]
        self.assertIn("Tonight's games already started: Tampa Bay Rays @ Cleveland Guardians (", c["slate"])
        self.assertIn("Next games I can bet: Thursday.", c["slate"])
        self.assertEqual(c["picks"], 1)
        self.assertEqual(c["order"][0], c["slate"])
        self.assertEqual(c["order"][1], c["headline"])

    def test_with_nothing_to_say_there_is_no_slate_paragraph(self):
        quiet = Payloads.fire_payload()
        quiet["slate"] = dict(quiet["slate"], line="", started=[], in_window=[])
        out = page(dog_routes(owner=False, fire_payload=quiet), actions=[dict(do="click", sel=hook("fire-btn"), wait=80, capture=[
            q("slate", hook("fire-slate"), "count"), q("picks", hook("fire-pick"), "count")])])
        self.assertEqual(out["captures"]["0"]["slate"], 0)
        self.assertEqual(out["captures"]["0"]["picks"], 1)
        own = page(dog_routes(unleash_payload=unleash_day(slate=quiet["slate"])), actions=[dict(do="click", sel=hook("fire-btn"), wait=120, capture=[
            q("slate", hook("fire-slate"), "count"), q("picks", hook("unleash-pick"), "count")])])
        self.assertEqual((own["captures"]["0"]["slate"], own["captures"]["0"]["picks"]), (0, 1))


@unittest.skipUnless(HAS_NODE, "node not installed")
class AskDrawsPickCards(unittest.TestCase):
    def routes(self):
        routes = dog_routes()
        ctx = context(dog_id=HID, name="Closer", fire_fn=lambda: FIRE_WITH_PICK)
        routes[f"POST /hounds/{HID}/ask"] = [200, ask.answer("What would you bet right now?", ctx)]
        return routes

    def test_the_answer_carries_a_card_with_the_pick_and_its_price(self):
        out = page(self.routes(), actions=[
            dict(do="set", sel=hook("ask-input"), value="What would you bet right now?", wait=10),
            dict(do="click", sel=hook("ask-send"), wait=100, capture=[
                q("cards", hook("ask-card"), "count"), q("sel", hook("ask-card") + " .dk-pick__sel"),
                q("price", hook("ask-card") + " .dk-chip"), q("stake", hook("ask-stake")),
                q("game", hook("ask-card") + " .dk-pick__game"),
                q("folds", hook("ask-checked"), "count"), q("foldsOpen", hook("ask-checked"), "attrs", attr="open"),
                q("foldTitle", hook("ask-checked") + " summary"), q("foldText", hook("ask-checked")),
                q("answers", hook("ask-answer"), "texts"), q("note", hook("ask-note"), "count"),
                q("fine", hook("ask-fine")),
                q("intents", hook("ask-answer"), "attrs", attr="data-intent")])])
        c = out["captures"]["1"]
        self.assertEqual(c["cards"], 1)
        self.assertEqual(c["sel"], "Cleveland Guardians to win")
        self.assertIn("+131", c["price"])
        self.assertEqual(c["stake"], "Stake $10")                       # the viewer's sizing (the runner pins the reference account)
        self.assertIn("Tampa Bay Rays @ Cleveland Guardians", c["game"])
        self.assertIn("7:10 pm ET", c["game"])
        # the rule text is behind ONE collapsed "How I checked it", never inline
        self.assertEqual(c["folds"], 1)
        self.assertEqual(c["foldTitle"], "How I checked it")
        self.assertEqual(c["foldsOpen"], [None])
        self.assertIn("Rule 2: Stats Nerd", c["foldText"])
        self.assertEqual(c["answers"][-1].count("Rule 2"), 1)           # once, inside the fold: not inline as well
        self.assertEqual(c["note"], 0)                                  # the "not written by an AI model" line is gone
        self.assertIn("21+", c["fine"])
        self.assertEqual(c["intents"][-1], "picks_now")

    def test_the_answers_of_the_page_never_say_it_was_not_written_by_an_ai_model(self):
        out = page(self.routes(), queries=[q("ask", hook("dog-ask"))])
        self.assertTrue(out["final"]["ask"])
        self.assertNotIn("not written by an AI", out["final"]["ask"])


if __name__ == "__main__":
    unittest.main()
