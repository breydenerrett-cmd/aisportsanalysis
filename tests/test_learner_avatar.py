"""The Learner draws its own mascot (web/img/learner-hound.svg) on its hound card; every other hound is drawn by the rig, unchanged.

Run for real under node against the leaderboard page (web/js/hounds-page.js -> dogFace in web/js/dog-avatar.js) with one fixture hound given the
category "learner". Skipped when node is not installed.
"""

from __future__ import annotations

import copy
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLearnersMascot(unittest.TestCase):
    def rows(self, category):
        routes = {k: [s, b] for k, (s, b) in F.routes().items()}
        board = copy.deepcopy(routes["/hounds"][1])
        board["hounds"][0]["category"] = category
        self.first = board["hounds"][0]["name"]
        routes["/hounds"] = [200, board]
        return run_page("hounds", routes=routes, queries=[
            q("learner", "[data-hook='row-dog'] svg[data-hound='learner']", "count"),
            q("images", "[data-hook='row-dog'] svg[data-hound='learner'] image", "attrs", attr="href"),
            q("all", "[data-hook='row-dog'] svg", "count")])["final"]

    def test_a_learner_card_draws_the_learner_svg_and_only_one_card_does(self):
        f = self.rows("learner")
        self.assertEqual(f["learner"], 1, f)
        self.assertTrue(f["images"] and f["images"][0].endswith("img/learner-hound.svg"), f)
        self.assertGreater(f["all"], 1, "the other hounds are still drawn")

    def test_no_other_category_gets_the_learner_art(self):
        f = self.rows("stats")
        self.assertEqual(f["learner"], 0, f)

    def test_the_art_file_is_there_and_has_no_script(self):
        text = (WEB / "img" / "learner-hound.svg").read_text(encoding="utf-8")
        self.assertIn("<svg", text)
        self.assertNotIn("<script", text.lower())


if __name__ == "__main__":
    unittest.main()
