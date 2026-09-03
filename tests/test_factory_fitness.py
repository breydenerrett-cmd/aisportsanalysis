"""Tests for src.factory.fitness: Fitness and promotion_verdict."""

from __future__ import annotations

import unittest
from dataclasses import fields

from src.factory.fitness import (
    BankrollComponent,
    EconomicComponent,
    FalsificationComponent,
    Fitness,
    FitnessError,
    ForwardSurvivalComponent,
    MultiplicityComponent,
    PriceResilienceComponent,
    RobustnessComponent,
    SampleSufficiencyComponent,
    promotion_verdict,
)


def _good_components(**overrides) -> dict:
    base = dict(
        system_id="sys-1", world="mlb", window="2026-forward",
        economic=EconomicComponent(logloss_vs_market=0.65,
                                    realized_return=0.04,
                                    economically_meaningful=True),
        robustness=RobustnessComponent(cscv_pbo=0.2, spa_p=0.3,
                                        placebo_percentile=95.0,
                                        stable_across_splits=True),
        forward_survival=ForwardSurvivalComponent(
            forward_selections=300, ledger_days=60, out_of_sample=True,
            within_sealed_epochs=True, point_class="A"),
        sample_sufficiency=SampleSufficiencyComponent(
            n_decisions=500, n_independent_clusters=80, required_clusters=60),
        price_resilience=PriceResilienceComponent(
            survives_worst_book=True, survives_shrink=True,
            shrink_fraction=0.25),
        falsification=FalsificationComponent(
            battery_verdict="PASS", battery_rules_version="2.0.0",
            fatal_rules_triggered=0),
        multiplicity=MultiplicityComponent(
            effective_tests=12, raw_tests=80, total_searched_at_verdict=200,
            multiplicity_charge=0.01),
        bankroll=BankrollComponent(realized_roi=0.03, drawdown_max=5.0,
                                    bankroll_positive=True),
    )
    base.update(overrides)
    return base


class FitnessShapeTests(unittest.TestCase):
    def test_fitness_has_no_scalar_collapse(self):
        fitness = Fitness(**_good_components())
        self.assertFalse(hasattr(fitness, "score"))
        self.assertFalse(hasattr(fitness, "__float__"))

    def test_component_names_excludes_identity_fields(self):
        fitness = Fitness(**_good_components())
        names = fitness.component_names()
        self.assertNotIn("system_id", names)
        self.assertNotIn("world", names)
        self.assertNotIn("window", names)
        self.assertIn("bankroll", names)
        self.assertIn("multiplicity", names)

    def test_multiplicity_effective_never_exceeds_raw(self):
        with self.assertRaises(FitnessError):
            MultiplicityComponent(effective_tests=100, raw_tests=10,
                                   total_searched_at_verdict=10,
                                   multiplicity_charge=0.0)

    def test_negative_multiplicity_charge_refused(self):
        with self.assertRaises(FitnessError):
            MultiplicityComponent(effective_tests=1, raw_tests=1,
                                   total_searched_at_verdict=1,
                                   multiplicity_charge=-0.1)

    def test_negative_drawdown_refused(self):
        with self.assertRaises(FitnessError):
            BankrollComponent(realized_roi=0.1, drawdown_max=-1.0,
                               bankroll_positive=True)


class PromotionVerdictTests(unittest.TestCase):
    def test_all_positive_promotes(self):
        fitness = Fitness(**_good_components())
        verdict = promotion_verdict(fitness)
        self.assertTrue(verdict.promote)
        self.assertIn("bankroll", verdict.positive_components)

    def test_bankroll_only_positive_is_refused(self):
        components = _good_components(
            economic=EconomicComponent(logloss_vs_market=0.9,
                                        realized_return=-0.01,
                                        economically_meaningful=False),
            robustness=RobustnessComponent(cscv_pbo=0.9, spa_p=0.9,
                                            placebo_percentile=10.0,
                                            stable_across_splits=False),
            forward_survival=ForwardSurvivalComponent(
                forward_selections=0, ledger_days=0, out_of_sample=False,
                within_sealed_epochs=False, point_class="D"),
            sample_sufficiency=SampleSufficiencyComponent(
                n_decisions=5, n_independent_clusters=1,
                required_clusters=60),
            price_resilience=PriceResilienceComponent(
                survives_worst_book=False, survives_shrink=False,
                shrink_fraction=0.25),
            falsification=FalsificationComponent(
                battery_verdict="BELOW_PLACEBO_CEILING",
                battery_rules_version="2.0.0", fatal_rules_triggered=2),
            multiplicity=MultiplicityComponent(
                effective_tests=0, raw_tests=0, total_searched_at_verdict=0,
                multiplicity_charge=0.0),
        )
        fitness = Fitness(**components)
        verdict = promotion_verdict(fitness)
        self.assertFalse(verdict.promote)
        self.assertEqual(verdict.positive_components, ("bankroll",))
        self.assertTrue(any("bankroll alone" in r for r in verdict.reasons))

    def test_bankroll_negative_but_everything_else_positive_still_refused(self):
        # A single failed non-bankroll component is disqualifying even
        # though bankroll being negative was never the concern here --
        # this asserts the conjunctive gate, not just the bankroll-only
        # special case.
        components = _good_components(
            falsification=FalsificationComponent(
                battery_verdict="BELOW_PLACEBO_CEILING",
                battery_rules_version="2.0.0", fatal_rules_triggered=1),
        )
        fitness = Fitness(**components)
        verdict = promotion_verdict(fitness)
        self.assertFalse(verdict.promote)
        self.assertIn("falsification", verdict.negative_components)

    def test_verdict_bool_matches_promote(self):
        fitness = Fitness(**_good_components())
        verdict = promotion_verdict(fitness)
        self.assertEqual(bool(verdict), verdict.promote)

    def test_insufficient_sample_refuses_even_with_good_bankroll_and_economics(self):
        components = _good_components(
            sample_sufficiency=SampleSufficiencyComponent(
                n_decisions=5, n_independent_clusters=2,
                required_clusters=60),
        )
        fitness = Fitness(**components)
        verdict = promotion_verdict(fitness)
        self.assertFalse(verdict.promote)
        self.assertIn("sample_sufficiency", verdict.negative_components)


if __name__ == "__main__":
    unittest.main()
