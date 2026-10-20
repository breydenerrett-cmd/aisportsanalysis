"""The landing page's live mini leaderboard (web/js/landing-board.js): the top five models by paper bankroll and the
latest five tickets.

Runs the module's own code under node against a fake DOM built from the real web/landing.html and payloads built
by the real contract code (tests/hounds_web_fixtures.py). The static half of the first screen (the headline, the
subline, the two buttons, the one human line and its link) is pinned in tests/test_landing_first_screen.py.

What this file holds the panel to:
  * the board is the top five by bankroll (the $1,000 paper account, docs/BANKROLL.md) among running models with a
    graded bet, baselines left to the leaderboard page, each row with its record, balance, return % and bet count,
    so a hot start on a few bets never reads as more; a thin sample is greyed with the reason in its tooltip;
  * the latest five tickets are real bets (a refusal is not a ticket), each with its status word;
  * with no answer a panel says so and names no figure; a server still warming up says that and nothing else;
  * no cartoon drawing and no emoji.
"""

from __future__ import annotations

import json
import re
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page
from tests.test_hounds_board_pages import EMOJI


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def mk(hid, name, units, bets=10, status="running", category="stats", **extra):
    h = {"id": hid, "name": name, "kind": "house", "category": category, "status": status,
         "verdict": {"label": "TOO EARLY"},
         "record": {"bets": bets, "wins": bets // 2, "losses": bets - bets // 2, "pushes": 0,
                    "units_average_price": units, "units_recorded_price": units}}
    h.update(extra)
    return h


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as K from "./landing-board.js";\n' + body)

    def test_the_top_five_are_the_most_units_among_running_models_with_a_graded_bet_and_no_baselines(self):
        hs = [mk(c, c.upper(), u) for c, u in zip("abcdefg", (1.0, 9.0, -4.0, 5.0, 7.0, 3.0, 2.0))]
        hs += [mk("base", "Base", 50.0, category="baseline"), mk("gone", "Gone", 80.0, status="retired"),
               mk("none", "None", None, bets=0), mk("fresh", "Fresh", 99.0, status="not_started")]
        hs[-2]["record"] = {"bets": 0}
        out = self.js(f"console.log(JSON.stringify(K.topModels({json.dumps(hs)}).map(h => h.id)));")
        self.assertEqual(out, ["b", "e", "d", "f", "g"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePanelsOnThePage(unittest.TestCase):
    def routes(self, **over):
        r = {k: list(v) for k, v in F.routes().items()}
        r.update(over)
        return r

    def page(self, routes=None, **kw):
        return run_page("landing_board", routes=self.routes() if routes is None else routes, **kw)

    def test_the_board_lists_five_models_with_record_bankroll_return_and_bets(self):
        out = self.page(queries=[
            q("ids", "[data-hook='lb-board'] .lbrow", "attrs", attr="data-hound"), q("ranks", ".lbrank", "texts"),
            q("bank", "[data-hook='lb-bankroll']", "texts"), q("ret", "[data-hook='lb-return']", "texts"),
            q("bets", "[data-hook='lb-bets']", "texts"), q("rec", "[data-hook='lb-record']", "texts"),
            q("links", ".lbname", "attrs", attr="href"), q("heads", "[data-hook='lb-board-table'] thead th", "texts"),
            q("asof", "[data-hook='lb-asof']"), q("note", "[data-hook='lb-bankroll-note']"),
            q("title", ".lbpanel__title", "texts")])
        f = out["final"]
        self.assertEqual(len(f["ids"]), 5)
        self.assertEqual(f["ranks"], ["1", "2", "3", "4", "5"])
        self.assertTrue(all(re.fullmatch(r"\$[\d,]+", b) for b in f["bank"]), f["bank"])
        balances = [int(b.replace("$", "").replace(",", "")) for b in f["bank"]]
        self.assertEqual(balances, sorted(balances, reverse=True), "most dollars first")
        self.assertTrue(all(re.fullmatch(r"[+-]\d+\.\d%", r) for r in f["ret"]), f["ret"])
        self.assertTrue(all(re.fullmatch(r"\d+-\d+(-\d+)?", r) for r in f["rec"]), f["rec"])
        self.assertTrue(all(b.isdigit() for b in f["bets"]))
        self.assertTrue(all(h.startswith("hound.html?id=") for h in f["links"]))
        self.assertEqual(f["heads"], ["#", "Hound", "Record", "Bankroll", "Return", "Bets"])   # owner ruling 2026-10-20, complete-product positioning
        self.assertFalse({"always-fave", "always-dog"} & set(f["ids"]))           # baselines are the leaderboard page's business
        self.assertEqual(f["asof"], "Data as of Oct 24")
        self.assertEqual(f["note"], "Every model starts with the same $1,000 paper bankroll. 1 unit = $10.")
        self.assertIn("The house pack: top hounds by bankroll", f["title"][0])   # owner ruling 2026-10-20, complete-product positioning

    def test_the_return_is_the_balance_over_the_shared_thousand_dollar_start(self):
        # Never a per-bet yield: a model up $14 on a $1,000 account shows +1.4%, whatever its bet count.
        out = self.page(queries=[q("bank", "[data-hook='lb-bankroll']", "texts"), q("ret", "[data-hook='lb-return']", "texts")])
        self.assertEqual(len(out["final"]["bank"]), 5)
        for bank, ret in zip(out["final"]["bank"], out["final"]["ret"]):
            dollars = int(bank.replace("$", "").replace(",", ""))
            self.assertAlmostEqual(float(ret.rstrip("%")), (dollars - 1000) / 10, delta=0.06, msg=(bank, ret))

    def test_a_ranked_model_under_twenty_settled_bets_is_greyed_with_the_reason(self):
        board = json.loads(json.dumps(F.leaderboard()))
        row = next(h for h in board["hounds"] if h["id"] == "closer")
        row["bankroll"]["small_sample"] = True
        r = self.routes(**{"/hounds": [200, board]})
        out = self.page(routes=r, queries=[
            q("grey", "[data-hook='lb-bankroll'].lbtone--small", "count"),
            q("title", "[data-hook='lb-return'].lbtone--small", "attrs", attr="title")])
        self.assertEqual(out["final"]["grey"], 1)
        self.assertTrue(out["final"]["title"][0].startswith("Ranked in full at"), out["final"]["title"])   # owner ruling 2026-10-20, complete-product positioning

    def test_the_latest_tickets_are_real_bets_with_a_status_word_and_a_refusal_is_not_one(self):
        out = self.page(queries=[q("n", "[data-hook='lb-ticket']", "count"), q("models", ".lbticket__model", "texts"),
                                 q("picks", ".lbticket__pick", "texts"), q("status", "[data-hook='lb-status']", "texts"),
                                 q("game", ".lbticket__game", "texts")])
        f = out["final"]
        self.assertEqual(f["n"], 2)
        self.assertEqual(f["models"], ["Closer", "Coin Flip"])
        self.assertEqual(f["status"], ["PENDING", "LOST"])
        self.assertIn("Yankees to win", f["picks"][0])
        self.assertIn("-120", f["picks"][0])
        self.assertIn("recorded 29m before the start", f["game"][0])

    def test_the_first_screen_has_character_dogs_and_the_race_but_no_emoji_and_no_toy_voice(self):
        # Design system v2 (owner, 2026-10-19): the first screen is alive. Each model is a dog drawn by the character rig
        # (web/js/dog-rig.js), in the board and in the bankroll race (tests/test_landing_race.py), instead of an initials tile.
        # What stays pinned from the earlier professional pass: no emoji, and none of the toy words in the copy.
        out = self.page(queries=[q("race", "[data-hook='lb-hero'] svg.lbrace__svg", "count"), q("mono", ".hd-mono", "texts"),
                                 q("boardDogs", "[data-hook='lb-board'] svg.dk-badge", "count"),
                                 q("raceDogs", "[data-hook='lb-race'] svg.dk-badge", "count"), q("hero", "[data-hook='lb-hero']")])
        self.assertEqual(out["final"]["race"], 1)
        self.assertEqual(out["final"]["mono"], [], "the initials tile is gone from the first screen")
        self.assertEqual((out["final"]["boardDogs"], out["final"]["raceDogs"]), (5, 5))
        self.assertEqual(EMOJI.findall(out["final"]["hero"]), [])
        self.assertNotRegex(out["final"]["hero"].lower(), r"kennel|houndmaster|put down|bark|doghouse")

    def test_no_answer_says_so_and_names_no_figure(self):
        out = self.page(routes={}, queries=[q("board", "[data-hook='lb-board']"), q("down", "[data-hook='lb-down']", "count"),
                                            q("tickets", "[data-hook='lb-tickets']")])
        self.assertEqual(out["final"]["down"], 1)
        self.assertIn("not answering right now", out["final"]["board"])
        self.assertNotRegex(out["final"]["board"], r"\d")
        self.assertIn("not answering right now", out["final"]["tickets"])

    def test_a_server_still_warming_up_says_that_and_nothing_else(self):
        from src.hounds import contract
        r = self.routes(**{"/hounds": [200, contract.warming_payload({"hounds": []})]})
        out = self.page(routes=r, queries=[q("w", "[data-hook='lb-warming']"), q("rows", ".lbrow", "count")])
        self.assertIn("The leaderboard is warming up", out["final"]["w"])
        self.assertEqual(out["final"]["rows"], 0)

    def test_an_empty_board_and_an_empty_feed_are_honest_about_it(self):
        r = self.routes(**{"/hounds": [200, {"hounds": []}], "/hounds/stream": [200, {"items": []}]})
        out = self.page(routes=r, queries=[q("empty", "[data-hook='lb-empty']"), q("t", "[data-hook='lb-tickets-empty']")])
        self.assertIn("settled bets in this season yet", out["final"]["empty"])
        self.assertIn("No tickets recorded yet", out["final"]["t"])

    def test_a_missing_feed_keeps_the_board(self):
        r = self.routes()
        r.pop("/hounds/stream")
        out = self.page(routes=r, queries=[q("rows", ".lbrow", "count"), q("t", "[data-hook='lb-tickets-down']")])
        self.assertEqual(out["final"]["rows"], 5)
        self.assertIn("not answering", out["final"]["t"])

    def test_it_asks_only_for_the_two_public_routes(self):
        out = self.page()
        self.assertEqual(sorted(g.split("?")[0] for g in out["gets"]), ["/hounds", "/hounds/stream"])


if __name__ == "__main__":
    unittest.main()
