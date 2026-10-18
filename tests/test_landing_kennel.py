"""The landing page's kennel panel (web/js/landing-kennel.js): the three top dogs by paper units and the latest put down.

Runs the module's own code under node against a fake DOM built from the real web/landing.html and payloads built
by the real contract code (tests/hounds_web_fixtures.py). The static half of the first screen (the headline, the
two buttons, the hard lines, the one human line and its link) is pinned in tests/test_landing_first_screen.py.

What this file holds the panel to:
  * the board is the top three by paper units among dogs still in the race with bets, baselines left to the kennel
    page, each row with its W-L, its bet count and its badge, so a hot start on a few bets never reads as more;
  * the latest put-down dog wears its epitaph and the cause of death in a bettor's words;
  * with no answer the panel says so and names no figure; a server still warming up says that and nothing else.
"""

from __future__ import annotations

import json
import re
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def mk(hid, name, units, bets=10, status="running", category="stats", label="TOO EARLY", retired=None, **extra):
    h = {"id": hid, "name": name, "kind": "house", "category": category, "status": status,
         "verdict": {"label": label}, "retired": retired,
         "record": {"bets": bets, "wins": bets // 2, "losses": bets - bets // 2, "pushes": 0,
                    "units_average_price": units, "units_recorded_price": units}}
    h.update(extra)
    return h


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as K from "./landing-kennel.js";\n' + body)

    def test_the_top_three_are_the_three_most_paper_units_in_the_race_with_bets_and_no_baselines(self):
        hs = [mk("a", "A", 1.0), mk("b", "B", 9.0), mk("c", "C", -4.0), mk("d", "D", 5.0),
              mk("base", "Base", 50.0, category="baseline"), mk("gone", "Gone", 80.0, status="retired"),
              mk("none", "None", None, bets=0), mk("fresh", "Fresh", 99.0, status="not_started")]
        hs[6]["record"] = {"bets": 0}
        out = self.js(f"console.log(JSON.stringify(K.topDogs({json.dumps(hs)}).map(h => h.id)));")
        self.assertEqual(out, ["b", "d", "a"])

    def test_the_latest_put_down_is_the_newest_by_the_day_it_was_put_down(self):
        yard = [mk("old", "Old", -30.0, status="retired", retired={"date": "2026-10-01", "cause": "x"}),
                mk("new", "New", -30.0, status="retired", retired={"date": "2026-10-14", "cause": "y"}),
                mk("mid", "Mid", -30.0, status="retired", retired={"date": "2026-10-09", "cause": "z"})]
        out = self.js(f"console.log(JSON.stringify(K.latestPutDown({json.dumps(yard)}).id));")
        self.assertEqual(out, "new")
        self.assertIsNone(self.js("console.log(JSON.stringify(K.latestPutDown([])));"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePanelOnThePage(unittest.TestCase):
    def routes(self, **over):
        r = {k: list(v) for k, v in F.routes().items()}
        r.update(over)
        return r

    def page(self, routes=None, **kw):
        return run_page("landing_kennel", routes=self.routes() if routes is None else routes, **kw)

    def test_the_board_lists_three_dogs_with_units_wl_bets_and_a_badge(self):
        out = self.page(queries=[
            q("ids", "[data-hook='kennel-board'] .kennel__row", "attrs", attr="data-hound"),
            q("ranks", ".kennel__rank", "texts"), q("units", "[data-hook='kennel-units']", "texts"),
            q("badges", "[data-hook='kennel-badge']", "texts"),
            q("who", ".kennel__who", "texts"),
            q("links", ".kennel__name", "attrs", attr="href"),
            q("avatars", ".kennel__row .hd-avatar", "count")])
        f = out["final"]
        self.assertEqual(len(f["ids"]), 3)
        self.assertEqual(f["ranks"], ["#1", "#2", "#3"])
        units = [float(u.rstrip("u")) for u in f["units"]]
        self.assertEqual(units, sorted(units, reverse=True), "most paper units first")
        self.assertTrue(all(re.match(r"^[+-]\d+\.\d\du$", u) for u in f["units"]))
        self.assertTrue(all(re.search(r"\d+-\d+(-\d+)? in \d+ bets", w) for w in f["who"]), f["who"])
        self.assertTrue(all(b.split()[-1] in ("🔥", "🪙", "💸", "🐣", "🐾") for b in f["badges"]), f["badges"])
        self.assertTrue(all(h.startswith("hound.html?id=") for h in f["links"]))
        self.assertEqual(f["avatars"], 3)
        # baselines are the kennel page's business
        self.assertFalse({"always-fave", "always-dog"} & set(f["ids"]))

    def test_the_latest_put_down_dog_shows_its_epitaph_and_the_cause_of_death(self):
        out = self.page(queries=[q("hidden", "[data-hook='kennel-putdown']", "hidden"),
                                 q("label", ".kennel__putdown-label"), q("name", "[data-hook='kennel-putdown-name']"),
                                 q("epitaph", "[data-hook='kennel-epitaph']"), q("cause", ".kennel__cause")])
        f = out["final"]
        self.assertFalse(f["hidden"])
        self.assertEqual(f["label"], "Latest put down 💀")
        self.assertEqual(f["name"], "Old Faithful")                  # put down Oct 20; Slowpoke went on Oct 14
        self.assertEqual(f["epitaph"], "“Gone, but still on the record.”")   # a builder's dog has no epitaph of its own
        self.assertEqual(f["cause"], "Cut by the kennel boss. (Oct 20)")

    def test_a_dogs_own_epitaph_and_a_25_unit_cause_read_like_a_tombstone(self):
        r = self.routes()
        yard = json.loads(json.dumps(r["/hounds/graveyard"][1]))
        yard["hounds"] = [h for h in yard["hounds"] if h["id"] == "slowpoke"]
        r["/hounds/graveyard"] = [200, yard]
        out = self.page(routes=r, queries=[q("name", "[data-hook='kennel-putdown-name']"),
                                           q("epitaph", "[data-hook='kennel-epitaph']"), q("cause", ".kennel__cause")])
        self.assertEqual(out["final"]["name"], "Slowpoke")
        self.assertEqual(out["final"]["epitaph"], "“Went under one last time.”")
        self.assertEqual(out["final"]["cause"], "Went more than 25 units under. (Oct 14)")

    def test_no_answer_says_so_and_names_no_figure(self):
        out = self.page(routes={}, queries=[q("board", "[data-hook='kennel-board']"),
                                            q("down", "[data-hook='kennel-down']", "count"),
                                            q("put_hidden", "[data-hook='kennel-putdown']", "hidden")])
        self.assertEqual(out["final"]["down"], 1)
        self.assertIn("isn't answering right now", out["final"]["board"])
        self.assertNotRegex(out["final"]["board"], r"\d")
        self.assertTrue(out["final"]["put_hidden"])

    def test_a_server_still_warming_up_says_that_and_nothing_else(self):
        from src.hounds import contract
        r = self.routes(**{"/hounds": [200, contract.warming_payload({"hounds": []})]})
        out = self.page(routes=r, queries=[q("w", "[data-hook='kennel-warming']"),
                                           q("rows", ".kennel__row", "count")])
        self.assertIn("The kennel is warming up", out["final"]["w"])
        self.assertEqual(out["final"]["rows"], 0)

    def test_an_empty_kennel_and_an_empty_graveyard_are_honest_about_it(self):
        r = self.routes(**{"/hounds": [200, {"hounds": []}], "/hounds/graveyard": [200, {"hounds": []}]})
        out = self.page(routes=r, queries=[q("empty", "[data-hook='kennel-empty']"),
                                           q("put_hidden", "[data-hook='kennel-putdown']", "hidden")])
        self.assertIn("No dog has a bet on the board yet", out["final"]["empty"])
        self.assertTrue(out["final"]["put_hidden"])

    def test_a_missing_graveyard_hides_the_put_down_block_and_keeps_the_board(self):
        r = self.routes()
        r.pop("/hounds/graveyard")
        out = self.page(routes=r, queries=[q("rows", ".kennel__row", "count"),
                                           q("put_hidden", "[data-hook='kennel-putdown']", "hidden")])
        self.assertEqual(out["final"]["rows"], 3)
        self.assertTrue(out["final"]["put_hidden"])

    def test_it_asks_only_for_the_two_public_routes(self):
        out = self.page()
        self.assertEqual(sorted(g.split("?")[0] for g in out["gets"]), ["/hounds", "/hounds/graveyard"])


if __name__ == "__main__":
    unittest.main()
