"""Tests for the mechanism-check layer: the frozen predicate and its measure.

WHAT THESE ARE DEFENDING
--------------------------
The layer exists because every ReviewRecord this project ever wrote carried
`mechanism_checks=()`, so no loss in our history could have been classed
REASONING_WRONG by any game ever played. The failure modes of the fix are
worse than the gap it closes, and each of these tests pins one of them:

  - a predicate INVENTED at settlement for a decision that promised nothing
    (settlement must return `()`, not a check it made up);
  - a predicate SCORED ON THE BET rather than on the mechanism;
  - UNDETERMINED quietly coerced to PASS or FAIL when the sample is thin;
  - a later edit to the predicate table silently RE-SCORING an older pick,
    which is why every rule is copied onto the frozen row and read back from
    there;
  - post-game data reaching the decision path (that one is
    tests/test_gameflow_pit.py's, extended there rather than duplicated).
"""

from __future__ import annotations

import unittest

from src.engine import mechanism_predicates as mp
from src.pipeline import gameflow
from src.review import mechanism_eval as me
from tests.test_pipeline_gameflow import make_play, make_play_by_play

GAME_PK = 4242


def _pa(index, half, event, event_type, *, batter, pitcher=(2, "Home Starter")):
    return make_play(index=index, inning=1 + index // 9, half=half,
                     outs_after=0, event=event, event_type=event_type,
                     away_score=0, home_score=0, batter=batter,
                     pitcher=pitcher)


def build_flow(plays):
    rows = gameflow.build_rows("2026-09-02", GAME_PK, make_play_by_play(plays),
                               [], "2026-09-03T04:00:00Z",
                               game_meta={"home_team": "CIN", "away_team": "SD",
                                           "home_score": 0, "away_score": 0})
    return gameflow.load_game(rows, GAME_PK)


def away_lineup_game(reached_of_18: int, *, pitcher=(2, "Home Starter")):
    """18 away plate appearances against one home starter, `reached_of_18` of
    them reaching base, cycling the nine batters twice so the batting order is
    readable."""
    plays = []
    for i in range(18):
        reached = i < reached_of_18
        plays.append(_pa(
            i, "top",
            "Single" if reached else "Strikeout",
            "single" if reached else "strikeout",
            batter=(100 + (i % 9), f"Batter {i % 9}"), pitcher=pitcher))
    return plays


class TestPredicatesAreFrozenAtDecisionTime(unittest.TestCase):

    def test_every_registered_feature_has_a_predicate(self):
        from src.evolab.registry import DEFAULT_REGISTRY
        for feature in DEFAULT_REGISTRY.features():
            with self.subTest(feature=feature):
                self.assertIn(feature, mp.PREDICATES)

    def test_the_unregistered_feature_has_none(self):
        """`starter_platoon_gap` has no honest standalone direction, so it
        can never fire and must never carry a predicate."""
        self.assertNotIn("starter_platoon_gap", mp.PREDICATES)

    def test_a_row_carries_its_own_rule_not_a_reference_to_this_module(self):
        row = mp.predicates_for((("lineup_vs_primary_pitch", 1),), "away",
                                {"away_lineup_vs_primary_pitch": 0.33,
                                 "home_lineup_vs_primary_pitch": 0.27})[0]
        for key in ("subject", "measure", "comparison", "threshold",
                     "min_sample", "claim", "expected", "version"):
            self.assertIn(key, row)
        self.assertEqual(row["away_value"], 0.33)
        self.assertEqual(row["home_value"], 0.27)
        self.assertEqual(row["predicate_id"], "lineup_vs_primary_pitch@rung1")

    def test_an_absent_feature_value_is_reported_absent_never_defaulted(self):
        row = mp.predicates_for((("top_minus_bottom", 0),), "home", {})[0]
        self.assertIsNone(row["away_value"])
        self.assertIsNone(row["home_value"])

    def test_a_feature_with_no_predicate_yields_no_row(self):
        self.assertEqual(
            mp.predicates_for((("starter_platoon_gap", 0),), "away", {}), ())

    def test_a_side_that_is_not_a_side_is_refused(self):
        with self.assertRaises(mp.PredicateError):
            mp.predicates_for((("top_minus_bottom", 0),), "neither", {})

    def test_settlement_reads_the_frozen_rule_not_the_current_table(self):
        """The point of copying the rule onto the row: a row frozen with an
        absurd threshold must be scored against THAT threshold, even though
        no entry in `PREDICATES` carries it."""
        row = dict(mp.predicates_for((("lineup_vs_primary_pitch", 0),), "away",
                                     {})[0], threshold=0.99)
        flow = build_flow(away_lineup_game(9))  # 0.500, way over the real 0.3245
        check = me.evaluate((row,), flow)[0]
        self.assertEqual(check["verdict"], me.VERDICT_REFUTED)


class TestMeasurement(unittest.TestCase):

    def test_reached_base_rate_counts_only_real_plate_appearances(self):
        plays = away_lineup_game(6) + [
            _pa(99, "top", "Caught Stealing 2B", "caught_stealing_2b",
                batter=(100, "Batter 0"))]
        flow = build_flow(plays)
        rate, sample = me.reached_base_rate(flow["plays"], "away", 2)
        self.assertEqual(sample, 18, "a caught stealing is not a plate "
                                      "appearance and must not be an out")
        self.assertAlmostEqual(rate, 6 / 18)

    def test_reaching_on_an_error_is_not_reaching_base(self):
        plays = [_pa(i, "top", "Field Error", "field_error",
                     batter=(100 + i, f"B{i}")) for i in range(9)]
        flow = build_flow(plays)
        rate, sample = me.reached_base_rate(flow["plays"], "away", 2)
        self.assertEqual((rate, sample), (0.0, 9))

    def test_the_starter_is_whoever_threw_the_first_pitch_of_that_half(self):
        plays = away_lineup_game(3, pitcher=(77, "Actual Starter"))
        flow = build_flow(plays)
        self.assertEqual(me.starter_faced_by(flow["plays"], "away"), 77)
        self.assertIsNone(me.starter_faced_by(flow["plays"], "home"))

    def test_ground_ball_share_excludes_the_ambiguous_events(self):
        plays = [
            _pa(0, "top", "Groundout", "field_out", batter=(101, "a")),
            _pa(1, "top", "Flyout", "field_out", batter=(102, "b")),
            _pa(2, "top", "Forceout", "force_out", batter=(103, "c")),
            _pa(3, "top", "Fielders Choice", "fielders_choice",
                batter=(104, "d")),
        ]
        flow = build_flow(plays)
        share, total = me.ground_ball_out_share(flow["plays"], 2)
        self.assertEqual(total, 2, "a forceout does not say what was hit and "
                                    "must not be assigned to either half")
        self.assertAlmostEqual(share, 0.5)

    def test_the_batting_order_is_read_off_the_game(self):
        flow = build_flow(away_lineup_game(0))
        self.assertEqual(me.batting_order(flow["plays"], "away"),
                          [100 + i for i in range(9)])

    def test_an_unreadable_order_is_none_never_partial(self):
        plays = [_pa(i, "top", "Strikeout", "strikeout", batter=(100, "same"))
                 for i in range(9)]
        flow = build_flow(plays)
        self.assertIsNone(me.batting_order(flow["plays"], "away"))


class TestVerdicts(unittest.TestCase):

    def _check(self, feature, side, plays, **overrides):
        row = dict(mp.predicates_for(((feature, 0),), side, {})[0], **overrides)
        return me.evaluate((row,), build_flow(plays))[0]

    def test_a_lineup_that_out_produced_the_baseline_confirms(self):
        check = self._check("lineup_vs_primary_pitch", "away",
                            away_lineup_game(9))
        self.assertEqual(check["verdict"], me.VERDICT_CONFIRMED)
        self.assertIn("0.500", check["observed"])

    def test_a_lineup_that_did_not_is_refuted(self):
        check = self._check("lineup_vs_primary_pitch", "away",
                            away_lineup_game(2))
        self.assertEqual(check["verdict"], me.VERDICT_REFUTED)

    def test_a_thin_sample_is_undetermined_never_coerced(self):
        """Six plate appearances, all of them outs -- a rate of 0.000, which
        would REFUTE if the floor were ignored. It must not."""
        plays = [_pa(i, "top", "Strikeout", "strikeout",
                     batter=(100 + i, f"B{i}")) for i in range(6)]
        check = self._check("lineup_vs_primary_pitch", "away", plays)
        self.assertEqual(check["verdict"], me.VERDICT_UNDETERMINED)
        self.assertIn("sample floor", check["observed"])

    def test_no_play_by_play_is_undetermined_for_every_predicate(self):
        row = mp.predicates_for((("lineup_vs_primary_pitch", 0),), "away", {})
        checks = me.evaluate(row, None)
        self.assertEqual([c["verdict"] for c in checks],
                          [me.VERDICT_UNDETERMINED])
        self.assertIn("no play-by-play stored", checks[0]["observed"])

    def test_a_decision_that_promised_nothing_gets_no_check_invented(self):
        self.assertEqual(me.evaluate((), build_flow(away_lineup_game(9))), ())

    def test_the_velocity_predicate_scores_the_backed_sides_own_starter(self):
        """Backed HOME on velocity means the HOME starter is the harder
        thrower, so the check is on what the AWAY lineup did to him."""
        check = self._check("starter_velocity_gap", "home",
                            away_lineup_game(2))
        self.assertEqual(check["verdict"], me.VERDICT_CONFIRMED)
        check = self._check("starter_velocity_gap", "home",
                            away_lineup_game(12))
        self.assertEqual(check["verdict"], me.VERDICT_REFUTED)

    def test_a_dead_tie_on_the_order_split_is_undetermined(self):
        """Every batter reached exactly once in two turns: top minus bottom is
        exactly zero, and zero is not a pass and not a fail."""
        plays = []
        for i in range(18):
            reached = i < 9
            plays.append(_pa(i, "top", "Single" if reached else "Strikeout",
                              "single" if reached else "strikeout",
                              batter=(100 + (i % 9), f"B{i % 9}")))
        check = self._check("top_minus_bottom", "away", plays)
        self.assertEqual(check["verdict"], me.VERDICT_UNDETERMINED)


class TestSettlementWiring(unittest.TestCase):
    """`build_review_for` is the seam that was writing `mechanism_checks=()`
    for every bet this project ever settled. These pin what it does now."""

    def _settled(self, outcome, game_pk=GAME_PK):
        from src.accounts.paper import PaperBet, SettledBet
        bet = PaperBet(bet_id="b1", system_id="sys1", market_key="h2h",
                       selection_id="sel1", side="away", line=None,
                       price_american=-120, settlement_rule="h2h",
                       stake_units=1.0, game_pk=game_pk)
        return SettledBet(bet=bet, outcome=outcome, profit_units=-1.0)

    def _decision(self, predicates):
        from types import SimpleNamespace
        return SimpleNamespace(
            event_id="evt1", system_id="sys1", market_key="h2h",
            selection_id="sel1", decision_utc="2026-09-02T16:00:00+00:00",
            game_pk=GAME_PK, mechanism_predicates=predicates)

    def _flow_rows(self, plays):
        return gameflow.build_rows(
            "2026-09-02", GAME_PK, make_play_by_play(plays), [],
            "2026-09-03T04:00:00Z",
            game_meta={"home_team": "CIN", "away_team": "SD",
                        "home_score": 0, "away_score": 0})

    def test_a_frozen_predicate_becomes_a_real_check_on_the_review(self):
        from src.engine.settle_slate import build_review_for
        predicates = mp.predicates_for((("lineup_vs_primary_pitch", 0),),
                                       "away", {})
        review = build_review_for(
            self._decision(predicates), self._settled("loss"),
            "2026-09-03T04:00:00Z", information_events_path="/nonexistent",
            flow_rows=self._flow_rows(away_lineup_game(2)))
        self.assertEqual(len(review.mechanism_checks), 1)
        self.assertEqual(review.mechanism_checks[0]["verdict"],
                          me.VERDICT_REFUTED)
        self.assertEqual(review.thesis_outcome, "REFUTED")

    def test_a_confirmed_check_on_a_loss_is_real_variance(self):
        from src.engine.settle_slate import build_review_for
        predicates = mp.predicates_for((("lineup_vs_primary_pitch", 0),),
                                       "away", {})
        review = build_review_for(
            self._decision(predicates), self._settled("loss"),
            "2026-09-03T04:00:00Z", information_events_path="/nonexistent",
            flow_rows=self._flow_rows(away_lineup_game(9)))
        self.assertEqual(review.thesis_outcome, "VARIANCE")
        self.assertTrue(review.variance_flag)

    def test_a_decision_with_no_predicates_still_gets_no_checks(self):
        from src.engine.settle_slate import build_review_for
        review = build_review_for(
            self._decision(()), self._settled("loss"),
            "2026-09-03T04:00:00Z", information_events_path="/nonexistent",
            flow_rows=self._flow_rows(away_lineup_game(9)))
        self.assertEqual(review.mechanism_checks, ())
        self.assertEqual(review.thesis_outcome, "UNTESTED")

    def test_the_predicates_survive_a_ledger_round_trip(self):
        """A predicate that does not come back off the chain is a predicate
        that was never frozen."""
        from src.ledger.records import DecisionRecord
        predicates = mp.predicates_for((("top_minus_bottom", 2),), "home",
                                       {"home_top_minus_bottom": 0.09})
        row = {"mechanism_predicates": [dict(p) for p in predicates],
               "engine_version": "engine-1", "system_id": "s",
               "system_version": "v", "registry_fingerprint": "",
               "frame_fingerprint": None, "snapshot_fingerprint": "",
               "game_pk": None, "event_id": "e", "decision_utc": "t",
               "point_class": "LATE_BOARD", "information_time": "t",
               "recorded_utc": "t", "verdict": "no_play",
               "selection_id": "sel", "market_key": "h2h", "line": None,
               "book": None, "price_american": None, "consensus_fair": None,
               "books_at_decision": 0, "friction": {}, "p_model": None,
               "p_model_provenance": "none", "p_model_interval": None,
               "edge_bps": None, "price_improvement_bps": None,
               "rating": None, "thesis": None, "evidence": [],
               "counterarguments": [], "supporting_systems": [],
               "refusal_reason": None, "assumption_exposure": {},
               "stake_units": 0.0, "known_at_grade": "D"}
        record = DecisionRecord.from_row(row)
        self.assertEqual(record.mechanism_predicates[0]["predicate_id"],
                          "top_minus_bottom@rung2")
        self.assertEqual(record.mechanism_predicates[0]["home_value"], 0.09)


class TestTheCheckNeverSeesTheBet(unittest.TestCase):

    def test_no_evaluation_function_takes_an_outcome_argument(self):
        """By signature, not by inspection of the body: a settled outcome
        that cannot be passed in cannot be read."""
        import inspect
        for name in ("evaluate", "reached_base_rate", "ground_ball_out_share",
                      "top_minus_bottom_reached_base", "starter_faced_by",
                      "batting_order"):
            with self.subTest(function=name):
                params = inspect.signature(getattr(me, name)).parameters
                self.assertFalse(
                    [p for p in params
                     if p in ("settled", "outcome", "won", "result", "bet")],
                    f"{name} can be handed the bet's outcome")


if __name__ == "__main__":
    unittest.main()
