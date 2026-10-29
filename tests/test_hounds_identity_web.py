"""The training review card, run for real under node (tests/hounds_web_harness.mjs): "Core: NHL (kept)", the "Why it lost" block at the
top, and the "Keep going: no change" card that offers Close.

The proposal payloads are made by the real Python (training.review over a temp database) for the production hound, HOCKEYCHIEF, so a
drift between the server and the page fails here and not in front of an owner. Skipped when node is not installed.
"""

from __future__ import annotations

import copy
import json
import re
import unittest

from src.hounds.interact import training
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for
from tests.hounds_web_runner import HAS_NODE, run_page
from tests import test_hounds_interact_web as interact_web
from tests import test_hounds_rites_web as rites_web
from tests.test_hounds_identity import MLB_BAD, PRODUCTION, SPORTS

hook, q = interact_web.hook, interact_web.q
click, kennel_routes, dog, SIGNED = rites_web.click, rites_web.kennel_routes, rites_web.dog, rites_web.SIGNED

OPEN = "[data-hook='dog-action-train']"
BANNED = re.compile(r"\b(better|improve\w*|stronger|smarter|profit\w*|will win|edge|lock|beta|bet check|dogs?)\b", re.I)


class World(RitesCase):
    runTest = lambda self: None            # noqa: E731 -- a TestCase used as a fixture, never run

    @classmethod
    def build(cls):
        w = cls()
        w.setUp()
        try:
            out = {}
            for key, plan in (("keep", PRODUCTION), ("changes", MLB_BAD)):
                hound = w.dog("HOCKEYCHIEF" if key == "keep" else "HOCKEYCHIEF Two", sports=SPORTS)
                out[key] = training.review(w.resolve(hound["id"]), w.owner.id, now=NOW, rows=rows_for(hound["id"], plan))
            return {k: json.loads(json.dumps(v)) for k, v in out.items()}
        finally:
            w.doCleanups()


_PAYLOADS = {}


def payloads():
    if not _PAYLOADS:
        _PAYLOADS.update(World.build())
    return _PAYLOADS


def flow(proposal, actions, **kw):
    routes = kennel_routes([dog("u-1")])
    routes["POST /hounds/u-1/train/propose"] = [200, proposal]
    return run_page("kennel", routes=routes, **SIGNED, reducedMotion=True, actions=actions, **kw)


def review_caps():
    return [q("kind", ".rt-sheet", "attr", attr="data-hook"), q("core", hook("review-core")), q("heading", hook("review-heading")),
            q("lostHeading", hook("review-losses") + " h3"), q("lostLines", hook("review-loss-line"), "texts"), q("lostBlocks", hook("review-losses"), "count"),
            q("changes", hook("review-change"), "count"), q("message", hook("review-message")), q("buttons", hook("rites-actions") + " button", "texts"),
            q("all", hook("training-review")), q("applyDisabled", hook("review-apply"), "attr", attr="disabled")]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCardNamesTheCoreAndSaysWhyItLost(unittest.TestCase):
    def test_a_card_with_changes_shows_the_core_line_and_the_why_it_lost_block_at_the_top(self):
        data = payloads()["changes"]
        self.assertEqual(data["core"]["text"], "Core: NHL (kept)")
        out = flow(data, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=review_caps())])
        cap = out["captures"]["r"]
        self.assertEqual(cap["kind"], "training-review-sheet")
        self.assertEqual(cap["core"], "Core: NHL (kept)")
        self.assertEqual((cap["lostBlocks"], cap["lostHeading"]), (1, "Why it lost"))
        self.assertEqual(cap["lostLines"], data["losses"]["lines"])
        self.assertTrue(3 <= len(cap["lostLines"]) <= 5, cap["lostLines"])
        self.assertTrue(cap["all"].startswith("Why it lost"), "the block is at the top of the card")
        self.assertLess(cap["all"].index("Core: NHL (kept)"), cap["all"].index("What it would change"))
        self.assertEqual(cap["heading"], "What it would change")
        self.assertEqual(cap["buttons"], ["Veto", "Tweak", "Apply"])
        self.assertIsNone(BANNED.search(cap["all"]), cap["all"])

    def test_a_hound_with_no_core_gets_no_core_line_and_a_card_with_no_losses_gets_no_block(self):
        data = copy.deepcopy(payloads()["changes"])
        data["core"] = {"sports": [], "markets": [], "source": None, "kept": True, "text": ""}
        data["losses"] = None
        out = flow(data, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=review_caps())])
        cap = out["captures"]["r"]
        self.assertEqual((cap["core"], cap["lostBlocks"]), (None, 0))
        self.assertGreater(cap["changes"], 0)

    def test_what_the_server_wrote_is_drawn_as_text_never_as_markup(self):
        data = copy.deepcopy(payloads()["changes"])
        data["losses"]["lines"] = ["<b>bold</b> <img src=x onerror=alert(1)>", "second", "third"]
        out = flow(data, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=[q("lines", hook("review-loss-line"), "texts"),
                                                                                                q("imgs", hook("review-losses") + " img", "count")])])
        self.assertEqual(out["captures"]["r"]["lines"][0], "<b>bold</b> <img src=x onerror=alert(1)>")
        self.assertEqual(out["captures"]["r"]["imgs"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class KeepGoingNoChange(unittest.TestCase):
    def test_the_production_card_says_the_numbers_and_offers_close_not_apply(self):
        data = payloads()["keep"]
        self.assertEqual((data["mode"], data["nothing"], data["changes"]), ("keep", True, []))
        out = flow(data, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=review_caps())])
        cap = out["captures"]["r"]
        self.assertEqual(cap["heading"], "Keep going: no change")
        self.assertEqual(cap["message"], "2-3 on 5 NHL bets is too few to tell from luck at these prices. Nothing here is a pattern yet, "
                                         "so HOCKEYCHIEF keeps its rule.")
        self.assertEqual(cap["core"], "Core: NHL (kept)")
        self.assertEqual((cap["changes"], cap["lostBlocks"]), (0, 1))
        self.assertEqual(cap["buttons"], ["Close", "Tweak"])
        self.assertIsNone(BANNED.search(cap["all"]), cap["all"])

    def test_close_leaves_without_sending_anything_that_writes(self):
        out = flow(payloads()["keep"], [click(OPEN, "a"), click(hook("training-go"), "r", wait=300),
                                        click(hook("review-close"), "c", wait=200, capture=[q("sheets", ".rt-sheet", "count"), q("card", hook("training-card"), "count")])])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/train/diagnose", "/hounds/u-1/train/propose"])
        self.assertEqual(out["captures"]["c"], {"sheets": 0, "card": 0})

    def test_a_nothing_card_that_is_not_a_keep_card_gets_close_beside_the_old_buttons(self):
        data = copy.deepcopy(payloads()["changes"])
        data.update(changes=[], picks=[], nothing=True, mode="loosen", message="Nothing sensible to change.")
        out = flow(data, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=review_caps())])
        cap = out["captures"]["r"]
        self.assertEqual((cap["heading"], cap["buttons"]), ("Nothing to change", ["Close", "Veto", "Tweak", "Apply"]))
        self.assertIsNotNone(cap["applyDisabled"])


if __name__ == "__main__":
    unittest.main()
