"""Tests for src.factory.scorecard: build_fitness / build_scorecard.

The central claim under test, per the task: assembling a real Fitness from
genuine inputs must (a) never let bankroll alone promote a system -- even a
system with a great ROI and literally nothing else measured -- and (b) mark
every component it cannot compute as explicitly ABSENT with a reason, never
silently defaulted to a passing value.
"""

from __future__ import annotations

import unittest

from src.accounts.paper import PaperBet, settle_bet
from src.board.settle import GameResult
from src.factory.fitness import promotion_verdict
from src.factory.scorecard import (
    MIN_CALIBRATION_PAIRS,
    NEUTRAL_BRIER,
    NEUTRAL_LOGLOSS,
    ScorecardError,
    _calibration,
    _decision_review_pairs,
    build_calibration_report,
    build_fitness,
    build_scorecard,
    compute_clv_stats,
    compute_realized_stats,
    decision_key_for,
    falsification_from_battery,
    multiplicity_from_funnel_family,
)
from src.ledger.records import (
    DecisionRecord,
    PROBABILITY_PROVENANCE_MARKET_DERIVED,
    PROBABILITY_PROVENANCE_MODEL_DERIVED,
    ReviewRecord,
)
from src.research import battery as battery_module


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _win_bet(bet_id, price_american=-110, stake=1.0):
    bet = PaperBet(bet_id=bet_id, system_id="sys-1", market_key="h2h",
                    selection_id="home", side="home", line=None,
                    price_american=price_american, settlement_rule="h2h")
    return settle_bet(bet, GameResult(home_runs=5, away_runs=2))


def _loss_bet(bet_id, price_american=-110, stake=1.0):
    bet = PaperBet(bet_id=bet_id, system_id="sys-1", market_key="h2h",
                    selection_id="home", side="home", line=None,
                    price_american=price_american, settlement_rule="h2h")
    return settle_bet(bet, GameResult(home_runs=1, away_runs=6))


def _decision(day, *, event_id="evt-x", edge_bps=200, p_model=0.6,
              verdict="play", price_american=-110, known_at_grade="A",
              point_class="LATE_BOARD", system_id="sys-1",
              p_model_provenance=PROBABILITY_PROVENANCE_MODEL_DERIVED):
    # Mirror src.engine.analyze's real invariant here too: edge_bps is
    # structurally None for anything but model_derived provenance -- a
    # fixture that ignored this could construct a DecisionRecord the real
    # engine never could.
    if p_model_provenance != PROBABILITY_PROVENANCE_MODEL_DERIVED:
        edge_bps = None
    return DecisionRecord(
        engine_version="v1", system_id=system_id, system_version="1.0.0",
        registry_fingerprint="fp1", frame_fingerprint=None,
        snapshot_fingerprint="snap1", game_pk=1, event_id=event_id,
        decision_utc=f"{day}T18:00:00Z", point_class=point_class,
        information_time=f"{day}T17:55:00Z",
        recorded_utc=f"{day}T18:00:01Z", verdict=verdict,
        selection_id="home" if verdict == "play" else None,
        market_key="h2h" if verdict == "play" else None,
        line=None, book="book_a" if verdict == "play" else None,
        price_american=price_american if verdict == "play" else None,
        consensus_fair=0.5, books_at_decision=5, friction=None,
        p_model=p_model, p_model_interval=None, edge_bps=edge_bps,
        price_improvement_bps=None, rating=None, thesis="thesis note",
        evidence=["evidence note"], counterarguments=[],
        supporting_systems=[], refusal_reason=None
        if verdict == "play" else "refused_thin",
        assumption_exposure={}, stake_units=1.0 if verdict == "play" else 0.0,
        known_at_grade=known_at_grade,
        p_model_provenance=p_model_provenance,
    )


def _review(decision, *, settled="win", close_price=None):
    return ReviewRecord(
        decision_key=decision_key_for(decision),
        review_utc=decision.decision_utc, settled=settled,
        thesis_outcome="UNTESTED", mechanism_checks=(),
        market_path={} if close_price is None else {"close_price": close_price},
        late_information=(), missed_information=(), lineup_delta={},
        bullpen_delta={}, counterargument_realized=(), variance_flag=False,
        system_action="none", new_hypothesis=None,
    )


FAVORABLE_RESEARCH = {
    "robustness": {"cscv_pbo": 0.2, "spa_p": 0.3, "placebo_percentile": 95.0,
                   "stable_across_splits": True},
    "forward_survival": {"out_of_sample": True, "within_sealed_epochs": True},
    "price_resilience": {"survives_worst_book": True, "survives_shrink": True,
                          "shrink_fraction": 0.25},
    "multiplicity": {"effective_tests": 5, "raw_tests": 20,
                      "total_searched_at_verdict": 30,
                      "multiplicity_charge": 0.01},
}


def _real_passing_battery():
    """A genuine call into src.research.battery.run() -- not a stub -- with a
    minimal, clearly-positive, unclustered sample so every optional check is
    skipped (no team/season/book/price keys) and only the baseline runs."""
    rows = [{"date": f"2026-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}",
             "won": i % 5 != 0, "implied": 0.5} for i in range(40)]
    return battery_module.run(rows, effect_floor=0.01)


# ---------------------------------------------------------------------------
# compute_realized_stats
# ---------------------------------------------------------------------------

class RealizedStatsTests(unittest.TestCase):
    def test_empty_bets_are_real_zeros_not_fabricated(self):
        stats = compute_realized_stats([])
        self.assertEqual(stats.n_settled, 0)
        self.assertEqual(stats.roi_units, 0.0)
        self.assertEqual(stats.drawdown_max, 0.0)
        self.assertIsNone(stats.hit_rate)
        self.assertIsNone(stats.avg_odds_decimal)
        self.assertIsNone(stats.volatility)

    def test_known_bets_produce_exact_bankroll_arithmetic(self):
        win = _win_bet("b1", price_american=-110)  # profit +0.90909...
        loss = _loss_bet("b2", price_american=-110)  # profit -1.0
        stats = compute_realized_stats([win, loss], starting_bankroll=1000.0)
        self.assertEqual(stats.n_wins, 1)
        self.assertEqual(stats.n_losses, 1)
        self.assertAlmostEqual(stats.hit_rate, 0.5)
        self.assertAlmostEqual(stats.total_staked_units, 2.0)
        self.assertAlmostEqual(
            stats.total_profit_units,
            win.profit_units + loss.profit_units)
        self.assertAlmostEqual(stats.bankroll,
                               1000.0 + win.profit_units + loss.profit_units)
        # peak after the win, drawdown is peak - bankroll after the loss
        expected_peak = 1000.0 + win.profit_units
        expected_drawdown = expected_peak - stats.bankroll
        self.assertAlmostEqual(stats.peak, expected_peak)
        self.assertAlmostEqual(stats.drawdown_max, expected_drawdown)

    def test_volatility_is_stdev_of_per_bet_returns(self):
        import statistics
        win = _win_bet("b1", price_american=-110)
        loss = _loss_bet("b2", price_american=-110)
        stats = compute_realized_stats([win, loss])
        returns = [win.profit_units / 1.0, loss.profit_units / 1.0]
        self.assertAlmostEqual(stats.volatility, statistics.stdev(returns))

    def test_single_bet_has_no_volatility(self):
        stats = compute_realized_stats([_win_bet("b1")])
        self.assertIsNone(stats.volatility)

    def test_push_and_void_excluded_from_stake_exposure_and_returns(self):
        bet = PaperBet(bet_id="b3", system_id="sys-1", market_key="totals",
                        selection_id="over", side="over", line="8.5",
                        price_american=-110, settlement_rule="totals")
        # A push settlement rule/result combination -- reuse GameResult with
        # an exact total match is settlement-rule specific; instead assert
        # directly on the accounting path via a hand-built SettledBet-shaped
        # win instead, and separately confirm PUSH/VOID never enters
        # total_staked_units through the public accounting reused from
        # PaperAccount._record_settlement's own documented behavior.
        from src.accounts.paper import SettledBet
        from src.board.settle import PUSH
        pushed = SettledBet(bet=bet, outcome=PUSH, profit_units=0.0)
        stats = compute_realized_stats([pushed])
        self.assertEqual(stats.total_staked_units, 0.0)
        self.assertEqual(stats.per_bet_returns, ())
        self.assertEqual(stats.n_pushes, 1)


# ---------------------------------------------------------------------------
# build_fitness -- the bankroll-only refusal (the task's required test)
# ---------------------------------------------------------------------------

class BankrollOnlyRefusalTests(unittest.TestCase):
    def test_great_roi_and_nothing_else_is_refused(self):
        """A system with excellent bankroll performance and NO decisions,
        NO reviews, and NO research artifact must still be refused --
        promotion_verdict's bankroll-only rule must hold even when every
        other component is genuinely absent, not merely unfavorable."""
        wins = [_win_bet(f"w{i}") for i in range(20)]
        assembly = build_fitness("sys-1", wins, [], [], None)

        self.assertGreater(assembly.fitness.bankroll.realized_roi, 0.0)
        self.assertTrue(assembly.fitness.bankroll.bankroll_positive)

        verdict = promotion_verdict(assembly.fitness)
        self.assertFalse(verdict.promote)
        self.assertEqual(verdict.positive_components, ("bankroll",))
        self.assertTrue(any("bankroll alone" in r for r in verdict.reasons))

    def test_every_non_bankroll_component_is_recorded_absent(self):
        wins = [_win_bet(f"w{i}") for i in range(5)]
        assembly = build_fitness("sys-1", wins, [], [], None)
        reasons = assembly.absent_reasons()
        for expected in ("robustness", "falsification", "multiplicity",
                         "forward_survival.out_of_sample/within_sealed_epochs",
                         "price_resilience"):
            self.assertIn(expected, reasons)
            self.assertTrue(reasons[expected])  # never an empty reason


# ---------------------------------------------------------------------------
# build_fitness -- absent-component honesty in general
# ---------------------------------------------------------------------------

class AbsentComponentHonestyTests(unittest.TestCase):
    def test_absent_robustness_reads_negative_not_neutral(self):
        assembly = build_fitness("sys-1", [], [], [], None)
        self.assertFalse(assembly.fitness.robustness.stable_across_splits)

    def test_absent_forward_survival_reads_negative(self):
        assembly = build_fitness("sys-1", [], [], [], None)
        self.assertFalse(assembly.fitness.forward_survival.survived)

    def test_absent_falsification_is_not_run_not_pass(self):
        assembly = build_fitness("sys-1", [], [], [], None)
        self.assertEqual(assembly.fitness.falsification.battery_verdict,
                         "NOT_RUN")
        self.assertFalse(assembly.fitness.falsification.survived)

    def test_absent_price_resilience_reads_negative(self):
        assembly = build_fitness("sys-1", [], [], [], None)
        self.assertFalse(assembly.fitness.price_resilience.resilient)

    def test_absent_economic_reads_negative(self):
        assembly = build_fitness("sys-1", [], [], [], None)
        self.assertFalse(assembly.fitness.economic.economically_meaningful)
        self.assertEqual(assembly.fitness.economic.logloss_vs_market,
                         NEUTRAL_LOGLOSS)

    def test_sample_sufficiency_is_never_absent_even_at_zero(self):
        assembly = build_fitness("sys-1", [], [], [], None)
        names = [a.field for a in assembly.absent]
        self.assertFalse(any(n.startswith("sample_sufficiency") for n in names))
        self.assertEqual(assembly.fitness.sample_sufficiency.n_decisions, 0)
        self.assertFalse(assembly.fitness.sample_sufficiency.sufficient)

    def test_bankroll_is_never_absent_even_with_zero_bets(self):
        assembly = build_fitness("sys-1", [], [], [], None)
        names = [a.field for a in assembly.absent]
        self.assertFalse(any(n.startswith("bankroll") for n in names))


# ---------------------------------------------------------------------------
# build_fitness -- genuinely computed economic component
# ---------------------------------------------------------------------------

class EconomicComponentTests(unittest.TestCase):
    def _decisions_and_reviews(self, n_days=8, edge_bps=200, p_model=0.65):
        decisions, reviews = [], []
        for i in range(n_days):
            day = f"2026-08-{i + 1:02d}"
            d = _decision(day, event_id=f"evt-{i}", edge_bps=edge_bps,
                          p_model=p_model)
            decisions.append(d)
            reviews.append(self._review_for(d))
        return decisions, reviews

    def _review_for(self, decision, close_price=-130):
        return _review(decision, settled="win", close_price=close_price)

    def test_edge_and_calibration_computed_when_present(self):
        decisions, reviews = self._decisions_and_reviews()
        assembly = build_fitness("sys-1", [], decisions, reviews, None,
                                 required_clusters=1)
        self.assertTrue(assembly.fitness.economic.economically_meaningful)
        self.assertLess(assembly.fitness.economic.logloss_vs_market,
                        NEUTRAL_LOGLOSS)
        self.assertGreater(assembly.fitness.economic.realized_return, 0.0)
        names = [a.field for a in assembly.absent]
        self.assertNotIn("economic.realized_return", names)
        self.assertNotIn("economic.logloss_vs_market", names)

    def test_edge_present_but_no_settlement_still_absent_and_negative(self):
        decisions = [_decision("2026-08-01", edge_bps=200)]
        assembly = build_fitness("sys-1", [], decisions, [], None)
        self.assertFalse(assembly.fitness.economic.economically_meaningful)
        names = [a.field for a in assembly.absent]
        self.assertIn("economic.logloss_vs_market", names)
        self.assertNotIn("economic.realized_return", names)  # edge WAS present

    def test_bad_calibration_does_not_read_economically_meaningful(self):
        # p_model confidently WRONG every time -- logloss must be worse than
        # the neutral baseline, and economically_meaningful must be False.
        decisions, reviews = [], []
        for i in range(8):
            day = f"2026-08-{i + 1:02d}"
            d = _decision(day, event_id=f"evt-{i}", edge_bps=200, p_model=0.95)
            decisions.append(d)
            reviews.append(_review(d, settled="loss"))
        assembly = build_fitness("sys-1", [], decisions, reviews, None,
                                 required_clusters=1)
        self.assertGreater(assembly.fitness.economic.logloss_vs_market,
                           NEUTRAL_LOGLOSS)
        self.assertFalse(assembly.fitness.economic.economically_meaningful)


# ---------------------------------------------------------------------------
# The named regression test: docs/PREREG_CALIBRATED_PROBABILITY.md §5.
#
# "A market-derived probability can never satisfy the economic component
# of promotion_verdict -- structurally, not by good intentions ... The
# trap: 0.67275 < 0.693, so the log-loss half of that conjunction PASSES
# on the market's own forecast. What holds it shut is n_edge ... That
# chain is the guarantee and must carry a named regression test."
# ---------------------------------------------------------------------------

class MarketDerivedNeverEconomicallyMeaningfulTests(unittest.TestCase):
    def _well_calibrated_market_derived_decisions(self, n_days=12):
        """A market_derived system whose p_model genuinely tracks outcomes
        (unlike EconomicComponentTests' overconfident-loser fixture) --
        exactly the shape that makes the log-loss half of the economic
        conjunction PASS, so the test proves the gate is held shut by
        n_edge, not by logloss failing to compute or failing to beat the
        neutral baseline."""
        decisions, reviews = [], []
        # 8 wins at p_model=0.65, 4 losses at p_model=0.65 -- a textbook
        # well-calibrated forecast (65% win rate, 65% stated confidence),
        # log-loss well under ln(2).
        outcomes = (["win"] * 8) + (["loss"] * 4)
        for i, outcome in enumerate(outcomes):
            day = f"2026-08-{i + 1:02d}"
            d = _decision(
                day, event_id=f"evt-{i}", p_model=0.65,
                p_model_provenance=PROBABILITY_PROVENANCE_MARKET_DERIVED,
            )
            decisions.append(d)
            reviews.append(_review(d, settled=outcome))
        return decisions, reviews

    def test_logloss_half_of_the_conjunction_passes_on_its_own(self):
        """The trap, isolated: fed straight into `_calibration`, this
        market_derived sample's mean log-loss genuinely beats ln(2) --
        confirming the log-loss half of `economically_meaningful` is not
        what blocks promotion here."""
        decisions, reviews = self._well_calibrated_market_derived_decisions()
        logloss_mean, brier_mean, n_calibration = _calibration(decisions, reviews)
        self.assertGreater(n_calibration, 0)
        self.assertLess(logloss_mean, NEUTRAL_LOGLOSS)

    def test_economically_meaningful_is_false_because_n_edge_is_zero(self):
        """The guarantee itself: even though log-loss passes (previous
        test), `economically_meaningful` is False, and specifically
        because n_edge == 0 -- `edge_bps` is structurally None for
        market_derived (src.engine.analyze / src.ledger.records'
        invariant), never because calibration failed to compute or failed
        to beat the neutral baseline."""
        decisions, reviews = self._well_calibrated_market_derived_decisions()
        assembly = build_fitness("sys-market-derived", [], decisions, reviews,
                                 None, required_clusters=1)
        economic = assembly.fitness.economic

        # Every decision here structurally carries edge_bps=None.
        self.assertTrue(all(d.edge_bps is None for d in decisions))

        # The log-loss half of the conjunction passes -- restated on the
        # actual Fitness object this test gates on, not just the helper.
        self.assertLess(economic.logloss_vs_market, NEUTRAL_LOGLOSS)

        # And yet: not economically meaningful, and not promotable.
        self.assertFalse(economic.economically_meaningful)
        verdict = promotion_verdict(assembly.fitness)
        self.assertFalse(verdict.promote)

        # Named cause, not a vague failure: n_edge == 0 is on record as an
        # AbsentComponent for economic.realized_return, and realized_return
        # itself reads as the negative 0.0 fallback, never a fabricated
        # positive one.
        reasons = assembly.absent_reasons()
        self.assertIn("economic.realized_return", reasons)
        self.assertIn("model_derived", reasons["economic.realized_return"])
        self.assertEqual(economic.realized_return, 0.0)


# ---------------------------------------------------------------------------
# build_calibration_report -- docs/PREREG_CALIBRATED_PROBABILITY.md §4
# ---------------------------------------------------------------------------

class CalibrationReportTests(unittest.TestCase):
    def _market_derived_pairs(self, n, *, clustered_days=True):
        decisions, reviews = [], []
        for i in range(n):
            day = f"2026-{1 + (i // 28):02d}-{1 + (i % 28):02d}"
            d = _decision(
                day, event_id=f"evt-{i}", p_model=0.55 + (0.001 * (i % 20)),
                p_model_provenance=PROBABILITY_PROVENANCE_MARKET_DERIVED,
            )
            decisions.append(d)
            reviews.append(_review(d, settled="win" if i % 2 == 0 else "loss"))
        return decisions, reviews

    def test_below_minimum_pairs_reports_insufficient_sample(self):
        decisions, reviews = self._market_derived_pairs(50)
        report = build_calibration_report(decisions, reviews)
        self.assertFalse(report.sufficient)
        self.assertEqual(report.n_pairs, 50)
        self.assertIsNone(report.log_loss)
        self.assertEqual(report.reliability_fixed_width, ())
        self.assertEqual(report.reliability_equal_count, ())

    def test_below_minimum_clusters_reports_insufficient_sample_even_with_enough_pairs(self):
        # >=500 pairs but all crammed into far fewer than 9 distinct
        # 7-day game-day clusters (one decision per day, 60 days -> 8
        # clusters at 7 days each).
        decisions, reviews = [], []
        for i in range(600):
            day_index = i % 60
            day = f"2026-01-{1 + day_index:02d}" if day_index < 28 else \
                f"2026-02-{1 + (day_index - 28):02d}"
            d = _decision(
                day, event_id=f"evt-{i}", p_model=0.6,
                p_model_provenance=PROBABILITY_PROVENANCE_MARKET_DERIVED,
            )
            decisions.append(d)
            reviews.append(_review(d, settled="win" if i % 2 == 0 else "loss"))
        report = build_calibration_report(decisions, reviews,
                                          required_clusters=9)
        self.assertGreaterEqual(report.n_pairs, MIN_CALIBRATION_PAIRS)
        self.assertLess(report.n_clusters, 9)
        self.assertFalse(report.sufficient)

    def test_sufficient_sample_computes_real_scores_and_both_bin_schemes(self):
        decisions, reviews = [], []
        # 9 clusters worth of distinct game-days (9 * 7 = 63 days), several
        # decisions per day so n_pairs clears 500 too.
        n_per_day = 10
        for day_index in range(63):
            month, dom = divmod(day_index, 28)
            day = f"2026-{1 + month:02d}-{1 + dom:02d}"
            for j in range(n_per_day):
                i = day_index * n_per_day + j
                d = _decision(
                    day, event_id=f"evt-{i}", p_model=0.6,
                    p_model_provenance=PROBABILITY_PROVENANCE_MARKET_DERIVED,
                )
                decisions.append(d)
                reviews.append(_review(d, settled="win" if i % 2 == 0 else "loss"))
        report = build_calibration_report(decisions, reviews,
                                          required_clusters=9)
        self.assertTrue(report.sufficient)
        self.assertGreaterEqual(report.n_pairs, MIN_CALIBRATION_PAIRS)
        self.assertGreaterEqual(report.n_clusters, 9)
        self.assertIsNotNone(report.log_loss)
        self.assertIsNotNone(report.brier)
        self.assertEqual(len(report.reliability_fixed_width), 10)
        self.assertEqual(len(report.reliability_equal_count), 10)
        # Baseline 1 (§4): the de-vigged consensus on the same games -- for
        # market_derived this IS the same forecast, so the delta is exactly
        # zero, published, never omitted.
        self.assertEqual(report.baseline_market_delta_log_loss, 0.0)
        self.assertIsNotNone(report.baseline_base_rate_log_loss)
        self.assertEqual(report.baseline_phase2a_log_loss, 0.67275)
        self.assertEqual(report.baseline_phase2a_brier, 0.23999)


# ---------------------------------------------------------------------------
# CLV -- advisory only, never gates promotion
# ---------------------------------------------------------------------------

class ClvTests(unittest.TestCase):
    def test_clv_absent_without_close_price(self):
        decision = _decision("2026-08-01")
        review = _review(decision, settled="win", close_price=None)
        clv = compute_clv_stats([decision], [review])
        self.assertEqual(clv.n_graded, 0)
        self.assertEqual(clv.n_total_reviewed, 1)
        self.assertIsNone(clv.mean_cents)

    def test_clv_computed_when_close_present(self):
        decision = _decision("2026-08-01", price_american=-110)
        review = _review(decision, settled="win", close_price=-130)
        clv = compute_clv_stats([decision], [review])
        self.assertEqual(clv.n_graded, 1)
        self.assertGreater(clv.mean_prob_edge, 0.0)  # took a better price than close
        self.assertEqual(clv.beat_rate, 1.0)

    def test_clv_never_appears_on_fitness(self):
        # Structural: Fitness has no CLV-named field anywhere.
        from dataclasses import fields
        from src.factory.fitness import Fitness
        names = {f.name for f in fields(Fitness)}
        for comp_name in Fitness.component_names(
                build_fitness("sys-1", [], [], [], None).fitness):
            pass  # component_names is an instance method; smoke only
        self.assertNotIn("clv", names)
        self.assertNotIn("clv_bps_mean", names)


# ---------------------------------------------------------------------------
# battery.py / funnel.py real translation
# ---------------------------------------------------------------------------

class BatteryTranslationTests(unittest.TestCase):
    def test_real_battery_run_translates_to_pass(self):
        result = _real_passing_battery()
        self.assertTrue(result["survives"])
        self.assertTrue(result["ran"])
        component = falsification_from_battery(result)
        self.assertEqual(component.battery_verdict, "PASS")
        self.assertEqual(component.fatal_rules_triggered, 0)
        self.assertTrue(component.survived)

    def test_vacuous_survival_is_not_run_never_pass(self):
        # Under the battery's own MIN_N floor -- survives=True is vacuous.
        rows = [{"date": "2026-01-01", "won": True, "implied": 0.5}] * 5
        result = battery_module.run(rows)
        self.assertTrue(result["survives"])
        self.assertFalse(result["ran"])
        component = falsification_from_battery(result)
        self.assertEqual(component.battery_verdict, "NOT_RUN")
        self.assertFalse(component.survived)

    def test_fatal_battery_translates_to_failed(self):
        result = {"survives": False, "ran": True, "fatal": ["season_split"],
                  "report": {}, "rules": {"version": "2.0.0"}}
        component = falsification_from_battery(result)
        self.assertEqual(component.battery_verdict, "FAILED")
        self.assertEqual(component.fatal_rules_triggered, 1)
        self.assertFalse(component.survived)


class MultiplicityTranslationTests(unittest.TestCase):
    def test_translates_a_funnel_family(self):
        family = [
            {"name": "sys-1", "q_pass": True, "fdr_threshold": 0.01},
            {"name": "sys-2", "q_pass": False, "fdr_threshold": 0.005},
            {"name": "sys-3", "q_pass": True, "fdr_threshold": 0.015},
        ]
        out = multiplicity_from_funnel_family(family, "sys-1")
        self.assertEqual(out["raw_tests"], 3)
        self.assertEqual(out["effective_tests"], 2)
        self.assertEqual(out["multiplicity_charge"], 0.01)
        self.assertEqual(out["total_searched_at_verdict"], 3)

    def test_unknown_system_name_raises(self):
        with self.assertRaises(ScorecardError):
            multiplicity_from_funnel_family(
                [{"name": "other", "q_pass": True, "fdr_threshold": 0.01}],
                "sys-1")


# ---------------------------------------------------------------------------
# Full assembly -- every component genuinely positive promotes
# ---------------------------------------------------------------------------

class FullPositiveAssemblyTests(unittest.TestCase):
    def test_all_components_positive_promotes(self):
        decisions, reviews = [], []
        for i in range(8):
            day = f"2026-08-{i + 1:02d}"
            d = _decision(day, event_id=f"evt-{i}", edge_bps=200, p_model=0.65)
            decisions.append(d)
            reviews.append(_review(d, settled="win", close_price=-130))
        bets = [_win_bet(f"w{i}") for i in range(5)]
        research = dict(FAVORABLE_RESEARCH)
        research["battery"] = _real_passing_battery()

        assembly = build_fitness("sys-1", bets, decisions, reviews, research,
                                 required_clusters=1)
        self.assertEqual(assembly.absent, ())
        verdict = promotion_verdict(assembly.fitness)
        self.assertTrue(verdict.promote)
        self.assertEqual(set(verdict.positive_components),
                         {"economic", "robustness", "forward_survival",
                          "sample_sufficiency", "price_resilience",
                          "falsification", "multiplicity", "bankroll"})


# ---------------------------------------------------------------------------
# build_scorecard -- ObjectiveView split
# ---------------------------------------------------------------------------

class BuildScorecardTests(unittest.TestCase):
    def test_scorecard_objective_view_carries_no_money(self):
        from dataclasses import fields
        bets = [_win_bet("w1")]
        scorecard, absent = build_scorecard(
            "sys-1", "real", "2026-09-03", "LATE_BOARD", "h2h",
            bets, [], [], None)
        view = scorecard.objective_view()
        self.assertNotIn("account", [f.name for f in fields(view)])
        dumped = view.to_dict()
        for forbidden in ("account", "bankroll", "units", "drawdown",
                          "roi_units", "profit_units"):
            self.assertNotIn(forbidden, dumped)

    def test_scorecard_account_carries_the_money(self):
        bets = [_win_bet("w1"), _loss_bet("w2")]
        scorecard, absent = build_scorecard(
            "sys-1", "real", "2026-09-03", "LATE_BOARD", "h2h",
            bets, [], [], None)
        self.assertEqual(scorecard.account.roi_units,
                         compute_realized_stats(bets).roi_units)

    def test_scorecard_absent_fields_documented(self):
        scorecard, absent = build_scorecard(
            "sys-1", "real", "2026-09-03", "LATE_BOARD", "h2h",
            [], [], [], None)
        names = [a.field for a in absent]
        self.assertIn("reliability_bins", names)
        self.assertIn("realized_return_ci", names)
        self.assertIn("stability.season_month_stability", names)
        self.assertEqual(scorecard.reliability_bins, ())
        self.assertEqual(scorecard.realized_return_ci, ())
        self.assertIsNone(scorecard.stability["season_month_stability"])

    def test_scorecard_never_exceeds_raw_tests_invariant(self):
        # Reuses Scorecard's own __post_init__ guard -- proves this module
        # never hands it an inconsistent multiplicity pair.
        scorecard, _ = build_scorecard(
            "sys-1", "real", "2026-09-03", "LATE_BOARD", "h2h",
            [], [], [], None)
        self.assertLessEqual(scorecard.effective_tests, scorecard.raw_tests)


class CrossSystemCalibrationContaminationTests(unittest.TestCase):
    """B4 regression: two systems that decide the SAME (event_id,
    market_key, selection_id, decision_utc) -- routine when several genomes
    evaluate the same board at the same capture instant -- must never share
    a review. Before the fix, `decision_key_for` omitted `system_id`, so
    `_decision_review_pairs`/`_calibration` paired one system's decision
    with the OTHER system's review of that identical key; reproduced on
    2026-09-03 as `trivial_always_home` (27 settled bets) picking up n=41
    calibration pairs -- exactly what the published `window=2026-08-31`
    scorecard carried, and `logloss_vs_market` IS `objective()`.
    """

    def _same_instant_pair(self, *, outcome_a="win", outcome_b="loss"):
        # Same event/market/selection/decision_utc -- ONLY system_id
        # differs, exactly the collision the review describes.
        decision_a = _decision("2026-08-31", event_id="evt-shared",
                                system_id="sys-a", p_model=0.6)
        decision_b = _decision("2026-08-31", event_id="evt-shared",
                                system_id="sys-b", p_model=0.9)
        review_a = _review(decision_a, settled=outcome_a)
        review_b = _review(decision_b, settled=outcome_b)
        return decision_a, decision_b, review_a, review_b

    def test_decision_key_for_includes_system_id(self):
        decision_a, decision_b, _, _ = self._same_instant_pair()
        key_a = decision_key_for(decision_a)
        key_b = decision_key_for(decision_b)
        self.assertIn("sys-a", key_a)
        self.assertIn("sys-b", key_b)
        self.assertNotEqual(key_a, key_b)

    def test_pairing_never_crosses_systems_at_the_same_instant(self):
        decision_a, decision_b, review_a, review_b = self._same_instant_pair()
        # Handing sys-a's decision BOTH systems' reviews (the exact bug:
        # settle_slate.py handed build_scorecard every system's reviews) --
        # sys-a must only ever pair with its OWN review.
        pairs = list(_decision_review_pairs([decision_a], [review_a, review_b]))
        self.assertEqual(len(pairs), 1)
        paired_decision, paired_review = pairs[0]
        self.assertIs(paired_decision, decision_a)
        self.assertIs(paired_review, review_a)

    def test_calibration_is_not_contaminated_by_the_other_system(self):
        decision_a, decision_b, review_a, review_b = self._same_instant_pair(
            outcome_a="win", outcome_b="loss")
        # sys-a alone: exactly one real pair (its own win).
        logloss_alone, brier_alone, n_alone = _calibration(
            [decision_a], [review_a])
        # sys-a handed BOTH reviews (the bug's exact input shape): must
        # compute IDENTICALLY -- the other system's (contradictory) loss
        # must never leak in.
        logloss_mixed, brier_mixed, n_mixed = _calibration(
            [decision_a], [review_a, review_b])
        self.assertEqual(n_alone, 1)
        self.assertEqual(n_mixed, 1)
        self.assertEqual(logloss_alone, logloss_mixed)
        self.assertEqual(brier_alone, brier_mixed)

    def test_build_scorecard_per_system_reviews_never_contaminate(self):
        decision_a, decision_b, review_a, review_b = self._same_instant_pair(
            outcome_a="win", outcome_b="loss")
        bets_a = [_win_bet("wa1")]
        # sys-a's own scorecard, built from JUST its own review.
        scorecard_isolated, _ = build_scorecard(
            "sys-a", "real", "2026-08-31", "LATE_BOARD", "h2h",
            bets_a, [decision_a], [review_a])
        # sys-a's scorecard built from the WHOLE shared review chain (both
        # systems' reviews) -- the exact call shape `run_settle` made
        # before the fix. Must agree with the isolated computation.
        scorecard_shared_chain, _ = build_scorecard(
            "sys-a", "real", "2026-08-31", "LATE_BOARD", "h2h",
            bets_a, [decision_a], [review_a, review_b])
        self.assertEqual(scorecard_isolated.logloss_vs_market,
                         scorecard_shared_chain.logloss_vs_market)
        self.assertEqual(scorecard_isolated.brier, scorecard_shared_chain.brier)
        self.assertNotEqual(scorecard_shared_chain.logloss_vs_market,
                            NEUTRAL_LOGLOSS)


if __name__ == "__main__":
    unittest.main()
