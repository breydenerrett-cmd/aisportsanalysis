"""Tennis live game state (src/sports/live_state/tennis.py): the net-breaks math checked against EVERY possible game
sequence, the server memory, derivation from the REAL 2026-10-29 ESPN captures, the statistics rule, and the one-line text.

No network: every fetch is a function over tests/fixtures/live_state/.
"""
from __future__ import annotations

import copy
import re
import unittest

from src.providers import espn_tennis_results as espn
from src.sports.live_state import lines, store, tennis
from tests import live_state_support as S


class TheMathAgainstEverySequence(unittest.TestCase):
    """For every way a set can unfold (each game won by its server or its returner) and for both possible first servers,
    the formula must equal the break count obtained by simply counting."""

    def walk(self, first, ga, gb, ba, bb, depth, out):
        """Depth first over game sequences; `ba`/`bb` are the breaks A/B have won. Stops where a set is decided or at 6-6."""
        if espn.set_completed(ga, gb) or (ga == gb == 6) or depth == 13:
            return
        played = ga + gb
        server = first if played % 2 == 0 else ("b" if first == "a" else "a")      # who serves the NEXT game
        out.append((ga, gb, server, ba - bb))
        for winner in ("a", "b"):
            broke = winner != server
            self.walk(first, ga + (winner == "a"), gb + (winner == "b"), ba + (broke and winner == "a"), bb + (broke and winner == "b"),
                      depth + 1, out)

    def test_the_formula_equals_the_count_for_every_reachable_score_server_and_history(self):
        wrong, visited, answers = [], 0, {}
        for first in ("a", "b"):
            seen = []
            self.walk(first, 0, 0, 0, 0, 0, seen)
            for ga, gb, server, counted in seen:
                visited += 1
                if tennis.net_breaks(ga, gb, server) != counted or tennis.first_server(ga, gb, server) != first:
                    wrong.append((first, ga, gb, server, counted))
                # every history that reaches the same score with the same server to serve must count the same breaks
                self.assertEqual(answers.setdefault((ga, gb, server), counted), counted)
        self.assertEqual(wrong, [])
        self.assertGreater(visited, 2500)                                           # every game sequence of every set, both first servers
        self.assertEqual(len({k for k in answers}), len(answers))

    def test_b_is_the_mirror_of_a(self):
        for ga in range(0, 8):
            for gb in range(0, 8):
                for server in ("a", "b"):
                    a = tennis.net_breaks(ga, gb, server)
                    b = tennis.net_breaks(gb, ga, "b" if server == "a" else "a")
                    self.assertEqual(None if a is None else -a, b, (ga, gb, server))

    def test_worked_examples(self):
        # 3-2 with B to serve: 5 games played, so A served first and had 3 service games; A has won 3 games, so A has not broken
        self.assertEqual(tennis.net_breaks(3, 2, "b"), 0)
        # 3-2 with A to serve: B served first, A had 2 service games and won 3 games: A has broken once
        self.assertEqual(tennis.net_breaks(3, 2, "a"), 1)
        self.assertEqual(tennis.net_breaks(0, 0, "a"), 0)
        self.assertEqual(tennis.net_breaks(2, 0, "a"), 1)          # A served game 1 and held; B served game 2 and A broke
        self.assertEqual(tennis.net_breaks(2, 0, "b"), 1)          # B served first and was broken, A held game 2
        self.assertEqual(tennis.net_breaks(0, 2, "a"), -1)         # A served first and was broken once
        self.assertEqual(tennis.net_breaks(5, 0, "a"), 3)          # B served games 1, 3, 5 and lost them all
        self.assertEqual(tennis.net_breaks(5, 0, "b"), 2)
        self.assertEqual(tennis.net_breaks(4, 4, "a"), 0)

    def test_a_tiebreak_is_no_answer(self):
        for server in ("a", "b"):
            self.assertIsNone(tennis.net_breaks(6, 6, server))
            self.assertIsNone(tennis.first_server(6, 6, server))

    def test_a_decided_set_is_no_answer(self):
        for score in ((6, 0), (6, 4), (7, 5), (7, 6), (6, 3), (0, 6), (4, 6), (5, 7), (6, 7), (10, 8)):
            for server in ("a", "b"):
                with self.subTest(score=score):
                    self.assertIsNone(tennis.net_breaks(*score, server))

    def test_an_unknown_server_or_a_bad_score_is_no_answer(self):
        for server in (None, "", "c", "A", 1, True):
            self.assertIsNone(tennis.net_breaks(3, 2, server))
        for score in ((-1, 2), (2, -1), (None, 2), (2, None), (2.5, 1), (True, 1)):
            self.assertIsNone(tennis.net_breaks(*score, "a"), score)

    def test_advantage_sets_past_6_6_still_count(self):                             # an old-style final set: 7-7, 8-7
        self.assertEqual(tennis.net_breaks(7, 7, "a"), 0)
        self.assertEqual(tennis.net_breaks(8, 7, "b"), 0)
        self.assertEqual(tennis.net_breaks(7, 8, "a"), 0)
        self.assertEqual(tennis.net_breaks(9, 7, "a"), None)                           # two clear: that set is over

    def test_service_games_split_the_games_played_evenly(self):
        self.assertEqual(tennis.service_games(3, 2, "a"), (3, 2))
        self.assertEqual(tennis.service_games(3, 2, "b"), (2, 3))
        self.assertEqual(tennis.service_games(0, 0, "a"), (0, 0))


class TheServerMemory(unittest.TestCase):
    def test_a_first_server_is_trusted_on_the_second_agreeing_read(self):
        m = tennis.ServerMemory()
        self.assertFalse(m.observe("1", 2, "a"))
        self.assertTrue(m.observe("1", 2, "a"))
        self.assertTrue(m.observe("1", 2, "a"))

    def test_a_disagreeing_read_restarts_the_count_so_a_lagging_flag_cannot_flip_the_sign_silently(self):
        m = tennis.ServerMemory()
        m.observe("1", 2, "a")
        m.observe("1", 2, "a")
        self.assertFalse(m.observe("1", 2, "b"))
        self.assertFalse(m.observe("1", 2, "a"))        # back to the old answer: it must be confirmed again
        self.assertTrue(m.observe("1", 2, "a"))

    def test_a_new_set_or_match_has_its_own_count_and_unknown_never_counts(self):
        m = tennis.ServerMemory()
        m.observe("1", 2, "a")
        self.assertFalse(m.observe("1", 3, "a"))
        self.assertFalse(m.observe("2", 2, "a"))
        self.assertFalse(m.observe("1", 2, None))

    def test_finished_matches_are_forgotten(self):
        m = tennis.ServerMemory()
        m.observe("1", 2, "a")
        m.observe("2", 1, "b")
        m.forget_except(["2"])
        self.assertFalse(m.observe("1", 2, "a"))        # started over


class TheCapturedScoreboards(unittest.TestCase):
    def states(self, memory=None, reads=2):
        memory = memory or tennis.ServerMemory()
        out = []
        for _ in range(reads):
            out = tennis.states_from_scoreboards([("wta", S.load("espn_tennis_wta.json")), ("atp", S.load("espn_tennis_atp.json"))], memory)
        return {s["game_id"]: s for s in out}

    def test_only_matches_in_progress_become_states(self):
        states = self.states(reads=1)
        self.assertEqual(sorted(states), ["185684", "185810"])         # the finals and the scheduled matches are not live; the ATP board has no live match

    def test_the_rakhimova_joint_match(self):
        s = self.states()["185684"]
        self.assertEqual((s["tour"], s["tournament"], s["round"], s["best_of"]), ("wta", "Toray Pan Pacific Open Tennis", "Quarterfinal", 3))
        self.assertEqual((s["set_number"], s["sets"], s["current_set"], s["sets_won"]), (2, [[7, 5], [3, 4]], [3, 4], [1, 0]))
        self.assertEqual((s["server"], s["first_server"], s["server_confirmed"], s["tiebreak"]), ("a", "b", True, False))
        self.assertEqual(s["net_breaks"], {"a": 0, "b": 0})
        a, b = s["players"]
        self.assertEqual((a["name"], a["games"], a["serving"], a["sets_won"]), ("Kamilla Rakhimova", 3, True, 1))
        self.assertEqual((b["name"], b["games"], b["serving"], b["net_breaks"]), ("Maya Joint", 4, False, 0))

    def test_a_new_set_after_a_tiebreak_set_is_at_nil_nil_with_the_server_known(self):
        s = self.states()["185810"]
        self.assertEqual((s["set_number"], s["current_set"], s["sets_won"]), (2, [0, 0], [1, 0]))
        self.assertEqual((s["server"], s["first_server"]), ("a", "a"))
        self.assertEqual(s["net_breaks"], {"a": 0, "b": 0})

    def test_net_breaks_wait_for_the_second_read(self):
        s = self.states(reads=1)["185684"]
        self.assertEqual((s["server_confirmed"], s["net_breaks"]), (False, None))
        self.assertEqual(s["players"][0]["net_breaks"], None)

    def test_the_free_scoreboard_carries_no_in_match_statistics(self):
        for s in self.states().values():
            self.assertFalse(s["stats_available"])
            self.assertEqual([p["stats"] for p in s["players"]], [None, None])

    def test_statistics_are_kept_when_a_scoreboard_does_carry_them(self):
        doc = S.load("espn_tennis_wta.json")
        comps = doc["events"][0]["groupings"][0]["competitions"]
        live = next(c for c in comps if c["id"] == "185684")
        first = next(c for c in live["competitors"] if c["order"] == 1)          # ESPN's own order, not the list's
        first["statistics"] = [{"name": "aces", "displayValue": "5", "value": 5.0},
                                                {"name": "doubleFaults", "displayValue": "2", "value": 2.0},
                                                {"abbreviation": "BP", "displayValue": "1/3"}]
        out = tennis.states_from_scoreboards([("wta", doc)], tennis.ServerMemory())
        s = next(x for x in out if x["game_id"] == "185684")
        self.assertTrue(s["stats_available"])
        self.assertEqual(s["players"][0]["stats"], {"aces": 5.0, "doubleFaults": 2.0, "BP": "1/3"})
        self.assertIsNone(s["players"][1]["stats"])

    def test_a_match_listed_on_two_days_boards_is_one_read_not_two(self):
        memory = tennis.ServerMemory()
        doc = S.load("espn_tennis_wta.json")
        first = tennis.states_from_scoreboards([("wta", doc), ("wta", doc)], memory)           # two boards, one read
        self.assertEqual(len(first), 2)
        self.assertFalse(next(s for s in first if s["game_id"] == "185684")["server_confirmed"])

    def test_a_server_flag_that_flips_between_reads_hides_net_breaks_until_it_settles(self):
        memory = tennis.ServerMemory()
        doc = S.load("espn_tennis_wta.json")
        for _ in range(2):
            tennis.states_from_scoreboards([("wta", doc)], memory)
        flipped = copy.deepcopy(doc)
        comps = flipped["events"][0]["groupings"][0]["competitions"]
        live = next(c for c in comps if c["id"] == "185684")
        for c in live["competitors"]:
            c["possession"] = not c["possession"]
        state = next(s for s in tennis.states_from_scoreboards([("wta", flipped)], memory) if s["game_id"] == "185684")
        self.assertIsNone(state["net_breaks"])
        self.assertEqual(state["server"], "b")                         # ESPN's flag is still reported as ESPN said it
        self.assertFalse(state["server_confirmed"])

    def test_no_server_flag_means_no_server_and_no_breaks(self):
        doc = S.load("espn_tennis_wta.json")
        live = next(c for c in doc["events"][0]["groupings"][0]["competitions"] if c["id"] == "185684")
        for c in live["competitors"]:
            c["possession"] = False
        memory = tennis.ServerMemory()
        for _ in range(2):
            out = tennis.states_from_scoreboards([("wta", doc)], memory)
        s = next(x for x in out if x["game_id"] == "185684")
        self.assertEqual((s["server"], s["first_server"], s["net_breaks"]), (None, None, None))
        self.assertEqual([p["serving"] for p in s["players"]], [None, None])

    def test_a_tiebreak_in_the_set_shows_no_breaks_and_says_tiebreak(self):
        doc = S.load("espn_tennis_wta.json")
        live = next(c for c in doc["events"][0]["groupings"][0]["competitions"] if c["id"] == "185684")
        live["competitors"][0]["linescores"][1]["value"] = 6.0
        live["competitors"][1]["linescores"][1]["value"] = 6.0
        memory = tennis.ServerMemory()
        for _ in range(2):
            out = tennis.states_from_scoreboards([("wta", doc)], memory)
        s = next(x for x in out if x["game_id"] == "185684")
        self.assertEqual((s["tiebreak"], s["net_breaks"]), (True, None))

    def test_data_that_cannot_be_a_match_of_its_format_is_dropped(self):
        doc = S.load("espn_tennis_wta.json")
        live = next(c for c in doc["events"][0]["groupings"][0]["competitions"] if c["id"] == "185684")
        for c, extra in zip(live["competitors"], (6.0, 6.0)):
            c["linescores"] = [{"value": 6.0}, {"value": 6.0}, {"value": 6.0}, {"value": extra}]       # three finished sets each: not best of 3
        self.assertNotIn("185684", [s["game_id"] for s in tennis.states_from_scoreboards([("wta", doc)], tennis.ServerMemory())])

    def test_a_best_of_five_match_is_read_with_its_own_format(self):
        doc = S.load("espn_tennis_wta.json")
        live = next(c for c in doc["events"][0]["groupings"][0]["competitions"] if c["id"] == "185684")
        live["format"] = {"regulation": {"periods": 5}}
        s = next(x for x in tennis.states_from_scoreboards([("wta", doc)], tennis.ServerMemory()) if x["game_id"] == "185684")
        self.assertEqual(s["best_of"], 5)


class ThePass(unittest.TestCase):
    def setUp(self):
        store.clear()
        self.addCleanup(store.clear)
        tennis.MEMORY.clear()
        self.addCleanup(tennis.MEMORY.clear)
        self.calls = []

        def fetch(url):
            self.calls.append(url)
            return S.fixture_fetch(url)
        self.fetch = fetch

    def test_a_pass_reads_both_tours_for_todays_date_and_early_in_the_utc_day_yesterdays_too(self):
        report = tennis.fetch_and_store(S.TENNIS_NOW, self.fetch)                    # 00:30 UTC: yesterday's board may still hold a final
        self.assertEqual(report["requests"], 4)
        self.assertTrue(any("dates=20261030" in u and "/atp/" in u for u in self.calls))
        self.assertTrue(any("dates=20261029" in u and "/wta/" in u for u in self.calls))
        self.assertEqual(report["live"], 2)
        self.calls.clear()
        tennis.fetch_and_store(S.at(0, S.TENNIS_NOW.replace(hour=14)), self.fetch)
        self.assertEqual(len(self.calls), 2)                                         # afternoon UTC: today only

    def test_the_request_cap_bounds_a_pass(self):
        report = tennis.fetch_and_store(S.TENNIS_NOW, self.fetch, max_requests=1)
        self.assertEqual(report["requests"], 1)
        self.assertEqual(report["failed"], ["wta"])

    def test_a_tour_that_fails_keeps_the_other_and_the_old_entries_age_out_by_themselves(self):
        def half(url):
            if "/wta/" in url:
                raise OSError("down")
            return S.fixture_fetch(url)
        report = tennis.fetch_and_store(S.TENNIS_NOW, half)
        self.assertEqual((report["ok"], report["failed"]), (["atp"], ["wta"]))
        self.assertEqual(store.fresh_games("TENNIS", S.TENNIS_NOW), [])

    def test_the_board_gate_reads_tennis_only_around_a_tennis_match(self):
        ev = lambda **k: dict({"family": "TENNIS", "in_play": False, "_start": S.TENNIS_NOW + __import__("datetime").timedelta(hours=5)}, **k)
        self.assertFalse(tennis.needed([], S.TENNIS_NOW))
        self.assertFalse(tennis.needed([ev()], S.TENNIS_NOW))                          # five hours away
        self.assertTrue(tennis.needed([ev(in_play=True)], S.TENNIS_NOW))
        self.assertTrue(tennis.needed([ev(_start=S.TENNIS_NOW)], S.TENNIS_NOW))
        self.assertFalse(tennis.needed([ev(family="NHL", in_play=True)], S.TENNIS_NOW))
        self.assertTrue(tennis.needed([ev(_start=S.TENNIS_NOW - __import__("datetime").timedelta(hours=6))], S.TENNIS_NOW))   # "followed by": hours late


class TheLine(unittest.TestCase):
    def oriented(self, **over):
        memory = tennis.ServerMemory()
        for _ in range(2):
            states = tennis.states_from_scoreboards([("wta", S.load("espn_tennis_wta.json"))], memory)
        game = next(s for s in states if s["game_id"] == "185684")
        view = tennis.match("Maya Joint", "Kamilla Rakhimova", S.TENNIS_START, [game])        # home Joint, away Rakhimova
        view.update(over)
        return view

    def test_the_set_the_games_the_server_and_the_breaks(self):
        self.assertEqual(lines.tennis_line(self.oriented()), "Set 2 · 3-4 · Rakhimova serving · on serve · sets 1-0")

    def test_the_example_from_the_brief_the_server_up_a_break(self):
        view = self.oriented()
        view["net_breaks"] = {"a": 1, "b": -1}                                         # Rakhimova (a) serves and is up a break
        self.assertEqual(lines.tennis_line(view), "Set 2 · 3-4 · Rakhimova serving · up a break · sets 1-0")

    def test_the_returner_up_a_break_is_named(self):
        view = self.oriented()
        view["net_breaks"] = {"a": -1, "b": 1}
        self.assertEqual(lines.tennis_line(view), "Set 2 · 3-4 · Rakhimova serving · Joint up a break · sets 1-0")
        view["net_breaks"] = {"a": -2, "b": 2}
        self.assertIn("Joint up 2 breaks", lines.tennis_line(view))

    def test_unknown_breaks_and_unknown_server_leave_those_parts_out(self):
        view = self.oriented(net_breaks=None)
        self.assertEqual(lines.tennis_line(view), "Set 2 · 3-4 · Rakhimova serving · sets 1-0")
        view["home"]["serving"] = view["away"]["serving"] = None
        self.assertEqual(lines.tennis_line(view), "Set 2 · 3-4 · sets 1-0")

    def test_a_tiebreak_says_so_and_claims_no_breaks(self):
        view = self.oriented(tiebreak=True, net_breaks={"a": 1, "b": -1})
        view["home"]["games"] = view["away"]["games"] = 6
        self.assertEqual(lines.tennis_line(view), "Set 2 · 6-6 · tiebreak · Rakhimova serving · sets 1-0")

    def test_a_match_that_is_not_live_has_no_line(self):
        self.assertIsNone(lines.tennis_line(self.oriented(state="final")))

    def test_no_line_uses_edge_lock_beta_new_or_bet_wording(self):
        text = lines.tennis_line(self.oriented())
        self.assertIsNone(re.search(r"(?i)\b(edge|lock|beta|new|bet|wager|pick)\b", text), text)


class TheSnapshotRow(unittest.TestCase):
    def game(self, reads=2):
        memory = tennis.ServerMemory()
        for _ in range(reads):
            states = tennis.states_from_scoreboards([("wta", S.load("espn_tennis_wta.json"))], memory)
        game = next(s for s in states if s["game_id"] == "185684")
        game["as_of"] = "2026-10-30T00:30:00Z"
        return game

    def test_the_row_keeps_sets_games_server_and_breaks(self):
        row = tennis.log_row(self.game())
        self.assertEqual((row["sp"], row["id"], row["n"], row["ss"], row["cs"], row["sv"], row["nb"]),
                         ("TENNIS", "185684", ["Kamilla Rakhimova", "Maya Joint"], [[7, 5], [3, 4]], [3, 4], "a", {"a": 0, "b": 0}))
        self.assertIsNone(row["stats"])

    def test_a_new_game_changes_the_signature_and_a_re_read_does_not(self):
        g = self.game()
        row = tennis.log_row(g)
        again = tennis.log_row(dict(g, as_of="2026-10-30T00:31:00Z"))
        self.assertEqual(tennis.signature(row), tennis.signature(again))
        moved = copy.deepcopy(g)
        moved["current_set"] = [3, 5]
        self.assertNotEqual(tennis.signature(row), tennis.signature(tennis.log_row(moved)))


if __name__ == "__main__":
    unittest.main()
