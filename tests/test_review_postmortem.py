"""Tests for src/review/postmortem.py -- the verdict rule and the control.

WHAT THESE TESTS ARE ACTUALLY DEFENDING
-----------------------------------------
A post-mortem is the easiest artifact in this project to make dishonest, in
two opposite directions at once: blame the reasoning for every loss (and
"discover" a fix), or blame variance for every loss (and never learn
anything). The tests below pin the parts that stop both:

  - all three verdicts are REACHABLE, from stored facts, on real inputs;
  - LOSING is not itself evidence: the same decision, the same game, settled
    win or loss, gets the same verdict;
  - the won control is built by DEFAULT and pattern suggestions are withheld
    without it;
  - a pivot measured on the run-margin proxy is never rendered as a
    probability;
  - no suggestion may be a parameter change.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.ledger.records import ReviewRecord, compute_thesis_outcome
from src.pipeline import gameflow
from src.review import postmortem as pm
from tests.test_pipeline_gameflow import (SIMPLE_PLAYS, SIMPLE_WP_PCT,
                                          make_play, make_play_by_play,
                                          make_win_probability)

DECISION_KEY = ("evt1", "sys1", "h2h", "sel1", "2026-09-02T16:00:00+00:00")


def make_flow(*, plays=SIMPLE_PLAYS, wp_pct=SIMPLE_WP_PCT, game_pk=42,
              meta=None):
    rows = gameflow.build_rows(
        "2026-09-02", game_pk, make_play_by_play(plays),
        make_win_probability(plays, wp_pct) if wp_pct is not None else [],
        "2026-09-03T04:00:00Z",
        game_meta=meta or {"home_team": "CIN", "away_team": "SD",
                           "home_score": 0, "away_score": 2,
                           "home_probable_id": 2, "away_probable_id": 4})
    return gameflow.load_game(rows, game_pk)


def make_decision(**overrides):
    base = dict(event_id="evt1", system_id="sys1", market_key="h2h",
                selection_id="sel1", decision_utc=DECISION_KEY[4],
                thesis="home starter dominates left-handed bats",
                assumption_exposure={}, counterarguments=())
    base.update(overrides)
    return SimpleNamespace(**base)


def make_review(settled="loss", mechanism_checks=(), late_information=(),
                missed_information=(), counterargument_realized=(),
                decision_key=DECISION_KEY):
    outcome = compute_thesis_outcome(mechanism_checks, settled)
    return ReviewRecord(
        decision_key=tuple(decision_key), review_utc="2026-09-03T04:00:00Z",
        settled=settled, thesis_outcome=outcome,
        mechanism_checks=tuple(mechanism_checks), market_path={},
        late_information=tuple(late_information),
        missed_information=tuple(missed_information),
        lineup_delta={}, bullpen_delta={},
        counterargument_realized=tuple(counterargument_realized),
        variance_flag=(outcome == "VARIANCE"), system_action="none",
        new_hypothesis=None)


def make_wager(**overrides):
    base = dict(bet_id="b1", date="2026-09-02", event_id="evt1",
                system_id="sys1", market_key="h2h", selection_id="sel1",
                decision_utc=DECISION_KEY[4], side="home", line=None,
                settlement_rule="h2h", price_american=-120, game_pk=42,
                stake_units=1.0)
    base.update(overrides)
    return base


CONFIRMED_CHECK = ({"name": "starter_k_rate", "expected": ">=6",
                    "observed": "8", "verdict": "confirmed"},)
REFUTED_CHECK = ({"name": "starter_k_rate", "expected": ">=6",
                  "observed": "1", "verdict": "refuted"},)


class TestVerdictRuleReachesAllThreeClasses(unittest.TestCase):

    def _verdict(self, review, decision=None, flow=None):
        built = pm.build_postmortem(decision or make_decision(), review,
                                    make_wager(), flow or make_flow())
        return built.verdict, built.verdict_qualifier, built

    def test_refuted_mechanism_check_is_reasoning_wrong(self):
        verdict, qualifier, built = self._verdict(
            make_review(mechanism_checks=REFUTED_CHECK))
        self.assertEqual(verdict, pm.VERDICT_REASONING_WRONG)
        self.assertIsNone(qualifier)
        self.assertTrue(any("refuted" in b for b in built.verdict_basis))

    def test_realized_counterargument_is_also_reasoning_wrong(self):
        verdict, _q, _b = self._verdict(
            make_review(counterargument_realized=({"name": "bullpen"},)))
        self.assertEqual(verdict, pm.VERDICT_REASONING_WRONG)

    def test_late_information_is_information_missing(self):
        verdict, _q, built = self._verdict(make_review(late_information=(
            {"kind": "lineup_changed", "observed_utc": "2026-09-02T17:00:00Z"},)))
        self.assertEqual(verdict, pm.VERDICT_INFORMATION_MISSING)
        self.assertTrue(any("late_information" in b for b in built.verdict_basis))

    def test_a_late_scratch_is_information_missing_computed_from_the_game(self):
        """The probable we assumed never took the ball -- detectable only
        after the fact, from who actually pitched the first half-inning."""
        decision = make_decision(assumption_exposure={"A:home_probable_id": 1})
        flow = make_flow(meta={"home_team": "CIN", "away_team": "SD",
                                "home_score": 0, "away_score": 2,
                                # the schedule said 77 would start; play 0 of
                                # the top half shows pitcher 2 on the mound
                                "home_probable_id": 77, "away_probable_id": 4})
        verdict, _q, built = self._verdict(make_review(), decision=decision,
                                            flow=flow)
        self.assertEqual(verdict, pm.VERDICT_INFORMATION_MISSING)
        self.assertTrue(any("late scratch" in b for b in built.verdict_basis))

    def test_no_scratch_flagged_when_the_probable_actually_pitched(self):
        decision = make_decision(assumption_exposure={"A:home_probable_id": 1})
        verdict, _q, _b = self._verdict(make_review(), decision=decision)
        self.assertEqual(verdict, pm.VERDICT_VARIANCE)

    def test_confirmed_checks_and_a_loss_is_real_variance(self):
        verdict, qualifier, _b = self._verdict(
            make_review(mechanism_checks=CONFIRMED_CHECK))
        self.assertEqual(verdict, pm.VERDICT_VARIANCE)
        self.assertEqual(qualifier, pm.QUALIFIER_MECHANISM_CONFIRMED)

    def test_no_mechanism_checks_is_variance_but_labelled_unfalsifiable(self):
        verdict, qualifier, built = self._verdict(make_review())
        self.assertEqual(verdict, pm.VERDICT_VARIANCE)
        self.assertEqual(qualifier, pm.QUALIFIER_NO_FALSIFIABLE_MECHANISM)
        self.assertTrue(any("never testable" in l for l in built.limitations),
                         "an unfalsifiable thesis must not read as exonerated")

    def test_information_missing_pre_empts_reasoning_wrong(self):
        """If the board we decided on was wrong, we are not entitled to the
        claim that the reasoning failed."""
        verdict, _q, _b = self._verdict(make_review(
            mechanism_checks=REFUTED_CHECK,
            late_information=({"kind": "lineup_changed"},)))
        self.assertEqual(verdict, pm.VERDICT_INFORMATION_MISSING)


class TestLosingIsNotItselfEvidence(unittest.TestCase):

    def test_the_same_inputs_win_or_lose_get_the_same_verdict(self):
        flow = make_flow()
        loss = pm.build_postmortem(make_decision(), make_review("loss"),
                                   make_wager(), flow)
        win = pm.build_postmortem(make_decision(), make_review("win"),
                                  make_wager(), flow)
        self.assertEqual(loss.verdict, win.verdict)
        self.assertEqual(loss.verdict_qualifier, win.verdict_qualifier)

    def test_a_real_mechanism_check_is_scored_on_the_game_not_the_bet(self):
        """The same frozen predicate, the same real game, settled WIN in one
        run and LOSS in the other, evaluated through the real settlement
        evaluator -- identical checks, identical verdict.

        This is the extension of the test above, not a replacement for it:
        that one proved the CLASSIFIER ignores the outcome when there are no
        checks; this one proves the CHECKS themselves do, now that there are
        some. If a mechanism check could ever come back different because the
        bet won, this whole layer would be a machine for writing 'the
        reasoning was wrong' on every loss.
        """
        from src.engine import mechanism_predicates as mech
        from src.review import mechanism_eval

        predicates = mech.predicates_for(
            (("lineup_vs_primary_pitch", 0),), "home",
            {"away_lineup_vs_primary_pitch": 0.27,
             "home_lineup_vs_primary_pitch": 0.33})
        flow = make_flow()
        checks = mechanism_eval.evaluate(predicates, flow)
        self.assertTrue(checks, "sanity: the predicate must actually evaluate")

        built = {}
        for settled in ("win", "loss"):
            built[settled] = pm.build_postmortem(
                make_decision(), make_review(settled, mechanism_checks=checks),
                make_wager(), flow)
        self.assertEqual(built["win"].mechanism_checks,
                          built["loss"].mechanism_checks)
        self.assertEqual(built["win"].verdict, built["loss"].verdict)
        self.assertEqual(built["win"].verdict_qualifier,
                          built["loss"].verdict_qualifier)
        self.assertNotEqual(built["loss"].verdict_qualifier,
                            pm.QUALIFIER_NO_FALSIFIABLE_MECHANISM,
                            "sanity: the checks must have reached the "
                            "classifier, or this proves nothing")

    def test_settlement_never_hands_the_evaluator_the_outcome(self):
        """The structural half of the same guarantee: `build_review_for`
        computes the checks BEFORE and independently of the outcome, so the
        two runs above cannot diverge by construction rather than by luck."""
        import inspect

        from src.engine import settle_slate
        source = inspect.getsource(settle_slate.evaluate_mechanism_checks)
        for forbidden in ("outcome", "settled.outcome", "won"):
            self.assertNotIn(forbidden, source,
                              "the mechanism evaluator can see the bet result")


class TestPivot(unittest.TestCase):

    def test_h2h_uses_the_real_win_probability_series(self):
        built = pm.build_postmortem(make_decision(), make_review(),
                                    make_wager(), make_flow())
        self.assertEqual(built.pivot.metric, pm.PIVOT_METRIC_WIN_PROBABILITY)
        # The 2-run homer: home WP 46% -> 25%.
        self.assertEqual(built.pivot.event, "Home Run")
        self.assertAlmostEqual(built.pivot.before, 0.46, places=6)
        self.assertAlmostEqual(built.pivot.after, 0.25, places=6)
        self.assertIn("win probability 46% -> 25%", pm.render_pivot(built.pivot))

    def test_the_away_side_sees_the_mirror_image_of_the_same_play(self):
        built = pm.build_postmortem(make_decision(), make_review(),
                                    make_wager(side="away"), make_flow())
        # That home run moved the game FOR the away side, so it can never be
        # the away side's worst moment.
        self.assertNotEqual(built.pivot.event, "Home Run")

    def test_no_win_probability_falls_back_to_a_labelled_proxy(self):
        built = pm.build_postmortem(make_decision(), make_review(),
                                    make_wager(),
                                    make_flow(wp_pct=None))
        self.assertEqual(built.pivot.metric, pm.PIVOT_METRIC_RUN_MARGIN)
        self.assertIn("PROXY", built.pivot.metric_reason)
        rendered = pm.render_pivot(built.pivot)
        self.assertIn("PROXY", rendered)
        self.assertNotIn("%", rendered)
        self.assertTrue(any("PROXY" in l for l in built.limitations))

    def test_a_market_the_wp_series_does_not_predict_uses_the_proxy(self):
        built = pm.build_postmortem(
            make_decision(), make_review(),
            make_wager(market_key="totals", settlement_rule="totals",
                       side="under", line="1.5"),
            make_flow())
        self.assertEqual(built.pivot.metric, pm.PIVOT_METRIC_RUN_MARGIN)
        # Under 1.5 with 2 runs in: the homer put the bet under water.
        self.assertEqual(built.pivot.event, "Home Run")
        self.assertAlmostEqual(built.pivot.before, 1.5, places=6)
        self.assertAlmostEqual(built.pivot.after, -0.5, places=6)

    def test_first_five_freezes_after_the_fifth_inning(self):
        # A 9-run 8th inning for the other side would dwarf everything in the
        # first five -- but it cannot settle a first-five bet, so the freeze
        # must keep it out of the pivot entirely.
        plays = list(SIMPLE_PLAYS) + [
            make_play(index=4, inning=8, half="top", outs_after=0,
                      event="Grand Slam", event_type="home_run", away_score=11,
                      home_score=0, rbi=9, scoring=True)]
        built = pm.build_postmortem(
            make_decision(), make_review(),
            make_wager(market_key="h2h_1st_5_innings",
                       settlement_rule="h2h_1st_5", side="home"),
            make_flow(plays=plays, wp_pct=SIMPLE_WP_PCT + [1.0]))
        self.assertEqual(built.pivot.metric, pm.PIVOT_METRIC_RUN_MARGIN)
        self.assertEqual(built.pivot.inning, 1)
        self.assertEqual(built.pivot.event, "Home Run")

    def test_the_worst_half_inning_aggregates_the_same_swing(self):
        built = pm.build_postmortem(make_decision(), make_review(),
                                    make_wager(), make_flow())
        self.assertEqual((built.half_inning_pivot.inning,
                          built.half_inning_pivot.half), (1, "top"))
        self.assertIn("Worst half-inning: top 1st",
                      pm.render_half_inning_pivot(built.half_inning_pivot))


class TestGameShape(unittest.TestCase):

    def test_final_score_and_when_it_stopped_being_in_doubt(self):
        built = pm.build_postmortem(make_decision(), make_review(),
                                    make_wager(), make_flow())
        self.assertEqual((built.shape.away_score, built.shape.home_score),
                          (2, 0))
        self.assertEqual(built.shape.decided_inning, 1)
        self.assertIn("win probability", built.shape.decided_basis)

    def test_missing_flow_is_reported_never_invented(self):
        built = pm.build_postmortem(make_decision(), make_review(),
                                    make_wager(), None)
        self.assertFalse(built.flow_available)
        self.assertIsNone(built.shape)
        self.assertIsNone(built.pivot)
        self.assertTrue(any("no play-by-play" in l for l in built.limitations))
        self.assertIn("Unknown", pm.render_postmortem(built))


class TestBuildPostmortems(unittest.TestCase):

    def _corpus(self, n_losses=4, n_wins=4):
        decisions, reviews, wagers, flow_rows = [], [], [], []
        for index in range(n_losses + n_wins):
            settled = "loss" if index < n_losses else "win"
            key = ("evt%d" % index, "sys1", "h2h", "sel1",
                   "2026-09-02T16:00:00+00:00")
            decisions.append(make_decision(event_id=key[0]))
            reviews.append(make_review(settled, decision_key=key))
            wagers.append(make_wager(event_id=key[0], game_pk=100 + index))
            flow_rows.extend(gameflow.build_rows(
                "2026-09-02", 100 + index, make_play_by_play(SIMPLE_PLAYS),
                make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT),
                "2026-09-03T04:00:00Z",
                game_meta={"home_score": 0, "away_score": 2}))
        return decisions, reviews, wagers, flow_rows

    def test_the_won_control_is_built_by_default(self):
        built = pm.build_postmortems(*self._corpus())
        summary = pm.summarize(built["postmortems"])
        self.assertEqual(summary["n_losses"], 4)
        self.assertEqual(summary["n_wins"], 4)

    def test_a_review_with_no_matching_wager_is_skipped_with_a_reason(self):
        decisions, reviews, wagers, flow_rows = self._corpus()
        reviews.append(make_review("loss", decision_key=(
            "unknown", "sys1", "h2h", "sel1", "2026-09-02T16:00:00+00:00")))
        built = pm.build_postmortems(decisions, reviews, wagers, flow_rows)
        self.assertEqual(len(built["skipped"]), 1)
        self.assertIn("no paper wager row", built["skipped"][0]["reason"])

    def test_an_ambiguous_legacy_key_is_skipped_not_guessed(self):
        decisions, reviews, wagers, flow_rows = self._corpus()
        # Two systems, same event/market/selection/instant: the pre-B4
        # 4-field key cannot tell them apart, and neither may this.
        wagers.append(make_wager(event_id="evt0", system_id="sys2",
                                 game_pk=100))
        reviews.append(make_review("loss", decision_key=(
            "evt0", "h2h", "sel1", "2026-09-02T16:00:00+00:00")))
        built = pm.build_postmortems(decisions, reviews, wagers, flow_rows)
        self.assertTrue(any("ambiguous" in s["reason"]
                            for s in built["skipped"]))

    def test_an_unambiguous_legacy_key_joins_and_says_so(self):
        decisions, reviews, wagers, flow_rows = self._corpus()
        reviews.append(make_review("loss", decision_key=(
            "evt0", "h2h", "sel1", "2026-09-02T16:00:00+00:00")))
        built = pm.build_postmortems(decisions, reviews, wagers, flow_rows)
        legacy = [p for p in built["postmortems"]
                  if len(p.decision_key) == 4]
        self.assertEqual(len(legacy), 1)
        self.assertTrue(any("pre-B4" in l for l in legacy[0].limitations))

    def test_rendering_is_deterministic(self):
        built = pm.build_postmortems(*self._corpus())
        first = pm.render_section(built["postmortems"])
        second = pm.render_section(built["postmortems"])
        self.assertEqual(first, second)

    def test_a_degenerate_table_says_it_separated_nothing(self):
        built = pm.build_postmortems(*self._corpus())
        rendered = pm.render_section(built["postmortems"])
        self.assertIn("separated NOTHING", rendered)


class TestSuggestResearch(unittest.TestCase):

    def _pms(self, n_losses, n_wins, loss_event="Home Run"):
        out = []
        for index in range(n_losses):
            out.append(pm.build_postmortem(
                make_decision(), make_review("loss"),
                make_wager(game_pk=200 + index), make_flow(game_pk=200 + index)))
        for index in range(n_wins):
            out.append(pm.build_postmortem(
                make_decision(), make_review("win"),
                make_wager(game_pk=300 + index, side="away"),
                make_flow(game_pk=300 + index)))
        return out

    def test_one_loss_is_an_anecdote_and_says_so(self):
        result = pm.suggest_research(self._pms(1, 3))
        self.assertEqual(result["suggestions"], [])
        self.assertTrue(any("anecdote" in n for n in result["notes"]))

    def test_no_control_withholds_every_suggestion(self):
        result = pm.suggest_research(self._pms(5, 0))
        self.assertEqual(result["suggestions"], [])
        self.assertTrue(any("no control exists" in n for n in result["notes"]))

    def test_a_signature_common_to_wins_too_is_not_a_finding(self):
        """Losses and wins here share market/verdict signatures exactly, so
        nothing may clear the lift floor."""
        result = pm.suggest_research(self._pms(5, 5))
        for suggestion in result["suggestions"]:
            self.assertNotIn("verdict:VARIANCE", suggestion)

    def test_a_real_over_representation_is_reported_as_a_question(self):
        losses = self._pms(4, 0)
        wins = [pm.build_postmortem(
            make_decision(), make_review("win"),
            make_wager(game_pk=400, market_key="totals",
                       settlement_rule="totals", side="under", line="9.5"),
            make_flow(game_pk=400)) for _ in range(4)]
        result = pm.suggest_research(losses + wins)
        self.assertTrue(result["suggestions"])
        for suggestion in result["suggestions"]:
            self.assertIn("QUESTION to prespecify", suggestion)

    def test_no_suggestion_may_read_as_a_parameter_change(self):
        losses = self._pms(4, 0)
        wins = [pm.build_postmortem(
            make_decision(), make_review("win"),
            make_wager(game_pk=400, market_key="totals",
                       settlement_rule="totals", side="under", line="9.5"),
            make_flow(game_pk=400)) for _ in range(4)]
        result = pm.suggest_research(losses + wins)
        for suggestion in result["suggestions"]:
            for term in pm._REFUSED_SUGGESTION_TERMS:
                self.assertNotIn(term, suggestion.lower())

    def test_the_section_repeats_the_no_threshold_rescue_rule(self):
        rendered = pm.render_section(self._pms(4, 4))
        self.assertIn("never evidence for a strategy change", rendered)
        self.assertIn("T8", rendered)


if __name__ == "__main__":
    unittest.main()
