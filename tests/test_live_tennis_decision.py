"""State detection, the fresh board, the selection rule and closing-line value (docs/PREREG_LIVE_TENNIS.md 4 to 7).

All pure: hand-built ESPN matches, hand-built quotes, hand-computed expected numbers. The decision rule is
checked at its boundary (a gap of exactly the threshold bets, a hair under does not), and determinism is checked
by running the same inputs twice and comparing the JSON.
"""

from __future__ import annotations

import json
import math
import unittest
from datetime import timedelta
from unittest import mock

from src.core import odds as core_odds
from src.providers import espn_tennis_results as espn
from src.research.live_tennis import board, clv, config, decision, state

from tests.live_tennis_fixtures import utc


def match(sets, status="STATUS_IN_PROGRESS", st="in"):
    return espn.TennisMatch(tour="atp", tournament="T", espn_event_id="1", match_id="9", start_utc="2026-11-02T10:00:00Z",
                            status=status, state=st, player_a="A A", player_b="B B", winner=None, sets=tuple(sets))


def q(book, when, home, away):
    return {"book": book, "last_update": when, "home_price": float(home), "away_price": float(away)}


T0 = utc("2026-11-02T11:00:00Z")
FRESH = "2026-11-02T11:00:05Z"
STALE = "2026-11-02T10:59:59Z"


class StateTests(unittest.TestCase):
    def test_set_start_cases(self):
        two = 2
        cases = [
            ([(6, 3)], True, "set 2 not listed yet"),
            ([(6, 3), (0, 0)], True, "set 2 listed at 0-0"),
            ([(6, 3), (1, 0)], False, "a game has been played"),
            ([(6, 3), (3, 6), (0, 0)], True, "set 3 start"),
            ([(0, 0)], False, "set 1 is never a decision point"),
            ([(3, 2)], False, "set 1 in progress"),
            ([(6, 4), (6, 2)], False, "match decided"),
            ([(6, 4), (6, 5)], False, "set 2 in progress at 6-5"),
            ([(6, 4), (6, 7)], True, "6-7 is a completed tiebreak set: set 3 about to start"),
        ]
        for sets, expect, why in cases:
            self.assertEqual(state.is_set_start(state.live_state(match(sets), two)), expect, why)

    def test_only_in_progress_matches_arm(self):
        for status, st in (("STATUS_SCHEDULED", "pre"), ("STATUS_FINAL", "post"), ("STATUS_SUSPENDED", "in"),
                           ("STATUS_RETIRED", "post")):
            self.assertFalse(state.is_set_start(state.live_state(match([(6, 3)], status, st), 2)), status)

    def test_sets_won_current_and_numbers(self):
        s = state.live_state(match([(6, 3), (3, 6), (2, 1)]), 2)
        self.assertEqual((s.completed, s.sets_won, s.current, s.set_number), (2, (1, 1), (2, 1), 3))
        s = state.live_state(match([(7, 6), (4, 6)]), 3)
        self.assertEqual((s.completed, s.sets_won, s.current, s.decided), (2, (1, 1), None, False))
        self.assertFalse(state.live_state(match([(6, 4), (6, 4)]), 3).decided)
        self.assertTrue(state.live_state(match([(6, 4), (6, 4)]), 2).decided)

    def test_format_contradictions_are_named_not_guessed(self):
        s = state.live_state(match([(6, 4), (4, 6), (6, 4), (4, 6)]), 2)
        self.assertIsNotNone(s.contradiction)                      # four completed sets cannot be best of three
        s = state.live_state(match([(6, 4), (4, 6), (3, 3), (0, 0)]), 2)
        self.assertIsNotNone(s.contradiction)                      # a set after an unfinished one
        self.assertFalse(state.is_set_start(s))

    def test_same_set_start_requires_the_same_score_on_both_reads(self):
        a = state.live_state(match([(6, 3)]), 2)
        b = state.live_state(match([(6, 3), (0, 0)]), 2)
        c = state.live_state(match([(6, 3), (1, 0)]), 2)
        d = state.live_state(match([(3, 6)]), 2)
        self.assertTrue(state.same_set_start(a, b))
        self.assertFalse(state.same_set_start(a, c))
        self.assertFalse(state.same_set_start(a, d))
        self.assertFalse(state.same_set_start(a, None))

    def test_round_trip_and_orientation(self):
        s = state.live_state(match([(6, 3), (0, 0)]), 2)
        self.assertEqual(state.from_dict(json.loads(json.dumps(state.to_dict(s)))), s)
        self.assertIsNone(state.from_dict(None))
        self.assertEqual(state.orient((1, 0), "straight"), (1, 0))
        self.assertEqual(state.orient((1, 0), "crossed"), (0, 1))
        with self.assertRaises(ValueError):
            state.orient((1, 0), "sideways")

    def test_possession_map_reads_one_flagged_server(self):
        doc = {"events": [{"groupings": [{"competitions": [
            {"id": "5", "competitors": [{"order": 1, "possession": False}, {"order": 2, "possession": True}]},
            {"id": "6", "competitors": [{"order": 1}, {"order": 2}]},
            {"id": "7", "competitors": [{"order": 1, "possession": True}, {"order": 2, "possession": True}]}]}]}]}
        self.assertEqual(state.possession_map(doc), {"5": "b"})
        self.assertEqual(state.possession_map(None), {})


class BoardTests(unittest.TestCase):
    def test_parse_quotes_keeps_two_sided_valid_books_only(self):
        event = {"home_team": "H", "away_team": "A", "bookmakers": [
            {"key": "zeta", "last_update": FRESH, "markets": [{"key": "h2h", "outcomes": [
                {"name": "H", "price": -150}, {"name": "A", "price": 130}]}]},
            {"key": "alpha", "last_update": FRESH, "markets": [{"key": "h2h", "last_update": STALE, "outcomes": [
                {"name": "H", "price": 120}, {"name": "A", "price": -140}]}]},
            {"key": "one_side", "last_update": FRESH, "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 100}]}]},
            {"key": "bad_price", "last_update": FRESH, "markets": [{"key": "h2h", "outcomes": [
                {"name": "H", "price": 50}, {"name": "A", "price": -140}]}]},
            {"key": "spreads", "last_update": FRESH, "markets": [{"key": "spreads", "outcomes": []}]}]}
        got = board.parse_quotes(event)
        self.assertEqual([x["book"] for x in got], ["alpha", "zeta"])                  # sorted by book
        self.assertEqual(got[0]["last_update"], STALE)                                 # the market's own stamp wins
        self.assertEqual((got[1]["home_price"], got[1]["away_price"]), (-150.0, 130.0))

    def test_freshness_is_at_or_after_and_unreadable_is_stale(self):
        quotes = [q("a", FRESH, -110, -110), q("b", "2026-11-02T11:00:00Z", -110, -110), q("c", STALE, -110, -110),
                  q("d", None, -110, -110), q("e", "garbage", -110, -110)]
        fresh, stale = board.split_fresh(quotes, T0)
        self.assertEqual([x["book"] for x in fresh], ["a", "b"])                       # exactly t_c counts
        self.assertEqual([x["book"] for x in stale], ["c", "d", "e"])

    def test_stats_consensus_best_and_average(self):
        quotes = [q("a", FRESH, -150, 130), q("b", FRESH, -140, 125), q("c", FRESH, -160, 140)]
        stats = board.board_stats(quotes)
        fair = [core_odds.devig_two_way(h, a)[0] for h, a in ((-150, 130), (-140, 125), (-160, 140))]
        self.assertAlmostEqual(stats["consensus_home"], sum(fair) / 3, places=12)
        self.assertAlmostEqual(stats["consensus_home"] + stats["consensus_away"], 1.0, places=12)
        self.assertEqual((stats["best_home"]["price"], stats["best_home"]["book"]), (-140.0, "b"))   # least negative
        self.assertEqual((stats["best_away"]["price"], stats["best_away"]["book"]), (140.0, "c"))
        self.assertAlmostEqual(stats["avg_implied_home"], (0.6 + 140 / 240 + 160 / 260) / 3, places=12)
        self.assertAlmostEqual(stats["best_implied_sum"], 140 / 240 + 100 / 240, places=12)
        self.assertIsNone(board.board_stats([]))
        view = board.side_view(stats, "away")
        self.assertEqual(view["best_book"], "c")
        with self.assertRaises(ValueError):
            board.side_view(stats, "both")

    def test_a_tie_for_the_best_price_goes_to_the_first_book_sorted(self):
        stats = board.board_stats([q("a", FRESH, 120, -140), q("b", FRESH, 120, -140), q("c", FRESH, 110, -130)])
        self.assertEqual(stats["best_home"]["book"], "a")


def board_of(*specs):
    return [q(f"b{i}", FRESH, h, a) for i, (h, a) in enumerate(specs)]


class EvaluateTests(unittest.TestCase):
    def test_thin_board_is_refused_before_anything_else(self):
        out = decision.evaluate(0.9, board_of((100, -105), (100, -105)))
        self.assertEqual((out["status"], out["reason"], out["side"]), (decision.EXCLUDED, "THIN_BOARD", None))
        self.assertEqual(out["n_fresh"], 2)
        self.assertEqual(decision.evaluate(0.9, [])["reason"], "THIN_BOARD")

    def test_an_arbitrage_board_is_inconsistent(self):
        # best home +110 (0.476) and best away +110 (0.476): sum 0.952, below 0.99
        out = decision.evaluate(0.9, board_of((110, -130), (-130, 110), (105, -125)))
        self.assertEqual((out["status"], out["reason"]), (decision.EXCLUDED, "INCONSISTENT_BOARD"))
        self.assertLess(out["stats"]["best_implied_sum"], config.BEST_IMPLIED_SUM_FLOOR)

    def test_threshold_boundary_bets_at_exactly_three_points(self):
        quotes = board_of((100, -105), (100, -105), (100, -105))       # best home +100 => implied exactly 0.5
        best_home = 0.5
        p_just_over = best_home + config.GAP_THRESHOLD_PP / 100.0
        out = decision.evaluate(p_just_over, quotes)
        self.assertEqual(out["status"], decision.BET)
        self.assertEqual(out["side"], "home")
        self.assertAlmostEqual(out["gap_pp_home"], config.GAP_THRESHOLD_PP, places=9)
        under = decision.evaluate(p_just_over - 0.0005, quotes)
        self.assertEqual((under["status"], under["reason"]), (decision.NO_BET, "BELOW_THRESHOLD"))
        self.assertEqual(under["side"], "home")                        # the candidate is still named for the record

    def test_a_gap_exactly_equal_to_the_threshold_bets_and_one_ulp_under_does_not(self):
        quotes = board_of((100, -105), (100, -105), (100, -105))       # best home +100: implied exactly 0.5
        p = 0.53
        gap = 100.0 * (p - 0.5)                                         # the very expression evaluate() computes
        with mock.patch.object(config, "GAP_THRESHOLD_PP", gap):
            self.assertEqual(decision.evaluate(p, quotes)["status"], decision.BET)
        with mock.patch.object(config, "GAP_THRESHOLD_PP", math.nextafter(gap, math.inf)):
            self.assertEqual(decision.evaluate(p, quotes)["status"], decision.NO_BET)

    def test_the_larger_gap_side_is_chosen_and_the_model_can_favour_the_away_player(self):
        quotes = board_of((-300, 260), (-310, 250), (-290, 240))       # best away +260, best home -290
        out = decision.evaluate(0.10, quotes)                          # the model rates the home player at 10%
        self.assertEqual(out["status"], decision.BET)
        self.assertEqual(out["side"], "away")
        self.assertGreater(out["gap_pp_away"], out["gap_pp_home"])

    def test_a_tie_in_gap_goes_to_home(self):
        quotes = board_of((-110, -110), (-110, -110), (-110, -110))
        out = decision.evaluate(0.5, quotes)
        self.assertEqual(out["side"], "home")
        self.assertEqual(out["status"], decision.NO_BET)

    def test_one_bet_at_most_and_determinism(self):
        quotes = board_of((100, -105), (105, -110), (100, -105))
        first = decision.evaluate(0.62, quotes)
        second = decision.evaluate(0.62, list(quotes))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertIn(first["status"], (decision.BET, decision.NO_BET))
        self.assertIn(first["side"], ("home", "away"))

    def test_prematch_p0_needs_three_books(self):
        self.assertIsNone(decision.prematch_p0(board_of((-150, 130), (-150, 130))))
        p0 = decision.prematch_p0(board_of((-150, 130), (-140, 120), (-160, 140)))
        self.assertEqual(p0["n_books"], 3)
        self.assertTrue(0.5 < p0["p0_home"] < 0.65)

    def test_dp_id_is_event_and_set(self):
        self.assertEqual(decision.dp_id("abc", 2), "abc:S2")
        self.assertNotEqual(decision.dp_id("abc", 2), decision.dp_id("abc", 3))

    def test_model_for_uses_the_frozen_constants_and_refuses_unknown_keys(self):
        priced = decision.model_for(0.6, "tennis_atp_vienna_open", 1, 0)
        self.assertEqual((priced["tour"], priced["serve_level"], priced["sets_to_win"]), ("atp", 0.64, 2))
        self.assertGreater(priced["p_match_home"], 0.6)                # leading a set
        self.assertIsNone(decision.model_for(0.6, "soccer_epl", 0, 0))
        self.assertEqual(decision.model_for(0.6, "tennis_atp_wimbledon", 0, 0)["sets_to_win"], 3)


class ClvTests(unittest.TestCase):
    def setUp(self):
        self.entry = board.board_stats([q("a", FRESH, 100, -105), q("b", FRESH, -105, -105), q("c", FRESH, 105, -120)])
        self.ref = board.board_stats([q("a", FRESH, -120, 100), q("b", FRESH, -125, 105), q("c", FRESH, -118, -102)])

    def test_the_arithmetic_by_hand(self):
        out = clv.clv("home", self.entry, self.ref)
        e, r = board.side_view(self.entry, "home"), board.side_view(self.ref, "home")
        self.assertAlmostEqual(out["m1"], 100 * (r["consensus"] - e["consensus"]), places=12)
        self.assertAlmostEqual(out["m2"], 100 * (r["consensus"] - e["avg_implied"]), places=12)
        self.assertAlmostEqual(out["m2_best"], 100 * (r["consensus"] - e["best_implied"]), places=12)
        # the best price is never worse than the average one, so M2 at the best is never below M2 at the average
        self.assertGreaterEqual(out["m2_best"], out["m2"])
        # the other side is the same formula on the other side
        o = clv.clv("away", self.entry, self.ref)
        self.assertAlmostEqual(out["other_m2"], o["m2"], places=12)
        self.assertAlmostEqual(out["other_m1"], o["m1"], places=12)
        # a two-way consensus moves by equal and opposite amounts
        self.assertAlmostEqual(out["m1"], -out["other_m1"], places=9)

    def test_average_price_value_is_below_the_consensus_move_by_the_overround(self):
        out = clv.clv("home", self.entry, self.ref)
        e = board.side_view(self.entry, "home")
        self.assertAlmostEqual(out["m1"] - out["m2"], 100 * (e["avg_implied"] - e["consensus"]), places=9)
        self.assertGreater(e["avg_implied"], e["consensus"])           # the average price includes vig

    def test_bad_side_refused(self):
        with self.assertRaises(ValueError):
            clv.clv("neither", self.entry, self.ref)


def snap(t_resp, event_id="e", quotes=None, before="STATUS_IN_PROGRESS", after="STATUS_IN_PROGRESS"):
    return {"snapshot_id": f"s@{t_resp}", "t_resp": t_resp,
            "events": {event_id: {"quotes": quotes if quotes is not None else board_of((-120, 100), (-125, 105), (-118, -102)),
                                  "espn_before": {"status": before}, "espn_after": {"status": after}}}}


class ReferenceTests(unittest.TestCase):
    D = utc("2026-11-02T11:00:00Z")

    def at(self, seconds, **kw):
        quotes = kw.pop("quotes", None)
        if quotes is None:
            stamp = (self.D + timedelta(seconds=seconds - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            quotes = [q(f"b{i}", stamp, -120, 100) for i in range(3)]
        return snap((self.D + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ"), quotes=quotes, **kw)

    def test_window_boundaries(self):
        self.assertFalse(clv.pick_reference(self.D, "e", [self.at(599)])["found"])
        found = clv.pick_reference(self.D, "e", [self.at(600)])
        self.assertTrue(found["found"])
        self.assertEqual(found["delay_s"], 600)
        self.assertTrue(clv.pick_reference(self.D, "e", [self.at(1500)])["found"])
        self.assertFalse(clv.pick_reference(self.D, "e", [self.at(1501)])["found"])

    def test_the_first_valid_snapshot_wins_whatever_order_they_arrive_in(self):
        late, early = self.at(1200), self.at(700)
        self.assertEqual(clv.pick_reference(self.D, "e", [late, early])["snapshot"]["t_resp"], early["t_resp"])

    def test_reference_quotes_must_be_updated_after_the_decision(self):
        old = (self.D - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stale = [q(f"b{i}", old, -120, 100) for i in range(3)]
        out = clv.pick_reference(self.D, "e", [self.at(700, quotes=stale)])
        self.assertFalse(out["found"])
        self.assertEqual(out["diagnostics"]["most_fresh"], 0)
        two_fresh = stale[:1] + [q("x", self.D.strftime("%Y-%m-%dT%H:%M:%SZ"), -120, 100), q("y", self.D.strftime("%Y-%m-%dT%H:%M:%SZ"), -120, 100)]
        self.assertTrue(clv.pick_reference(self.D, "e", [self.at(700, quotes=two_fresh)])["found"] is False)  # two fresh books
        three = two_fresh[1:] + [q("z", self.D.strftime("%Y-%m-%dT%H:%M:%SZ"), -120, 100)]
        self.assertTrue(clv.pick_reference(self.D, "e", [self.at(700, quotes=three)])["found"])

    def test_the_match_must_be_in_progress_on_both_reads_and_the_event_present(self):
        self.assertFalse(clv.pick_reference(self.D, "e", [self.at(700, before="STATUS_FINAL")])["found"])
        self.assertFalse(clv.pick_reference(self.D, "e", [self.at(700, after="STATUS_SUSPENDED")])["found"])
        out = clv.pick_reference(self.D, "e", [self.at(700, after="STATUS_SUSPENDED")])
        self.assertEqual((out["diagnostics"]["in_window"], out["diagnostics"]["in_progress"]), (1, 0))
        self.assertFalse(clv.pick_reference(self.D, "other", [self.at(700)])["found"])


if __name__ == "__main__":
    unittest.main()
