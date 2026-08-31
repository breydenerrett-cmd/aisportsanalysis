"""The OUTCOME-fitness ceiling verdict path -- `sweep.run_sweep(primary_fitness='outcome')`.

Phase 2B (docs/EVOLAB_PHASE2B_RESULTS.md) ran and published the MOVEMENT path
only; that result is closed and untouched by anything here. This module closes
the gap noted in the Phase 2B worker reports: `OUTCOME_CEILING_GENERATORS`
(design section 7's SECOND GENERATOR AMENDMENT) existed in `sweep.py` but the
outcome verdict wiring -- reading `WorldFitness.totals_roi` instead of
`totals_movement` for the champion, the ceiling, and the electorate default --
was untested and, until this task, unused by `run_sweep`.

Nothing in this file is evidence. It is machinery plus a synthetic feed, per
the module's own module-level rule (see `sweep.py`'s and `placebo.py`'s
docstrings); no real data, no evaluation, and it does not touch the sealed
2026 artifact or the Phase 2B results doc.

THE SYNTHETIC WORLD THIS FILE ADDS
-----------------------------------
`test_evolab_sweep.py`'s `synthetic_world` plants a MOVEMENT edge: the close
drifts away from the decision price when a signal fires. That is exactly the
wrong fixture for the outcome path -- a movement edge does move `roi_table`
too, but a clean test of the outcome-only wiring wants a world where the
market's price is undisturbed (no movement edge at all, so the movement
generators have nothing to find) but the GRADE is drawn from a probability
that quietly disagrees with the priced probability when a signal fires (so
betting into the mispriced side wins more than the price implies -- a pure
outcome edge). `synthetic_outcome_world` below does exactly that: `home_fair`
and `home_fair_close` are always equal up to iid noise regardless of the
signal, so nothing here can look like a movement edge; only `home_won` is
drawn from a probability that departs from the market's when the plant fires.
"""

from __future__ import annotations

import random
import unittest

from src.core import odds as odds_math
from src.evolab import ceiling, placebo, sweep
from tests.test_evolab_sweep import (FEATURES, HOLD, PLANTED_FEATURE,
                                     PLANTED_THRESHOLD, tiny_registry)


def synthetic_outcome_world(seed: int, *, edge: float = 0.0, n_days: int = 140,
                            per_day: int = 6, season: int = 2023) -> placebo.World:
    """A season with NO movement edge and, optionally, a real OUTCOME edge.

    `home_fair` and `home_fair_close` are always the same value plus
    independent noise -- the market never drifts on the plant, so a search
    maximising MOVEMENT has nothing to find here regardless of `edge`. Only
    the GRADE departs from what the price implies: when the away side's
    `PLANTED_FEATURE` clears `PLANTED_THRESHOLD`, the true win probability
    used to draw `home_won` is shifted away from the priced `fair` by `edge`
    (home overpriced, away truly stronger) -- a genuine, gradable ROI edge
    that the price never saw and the close never reflects.
    """
    rng = random.Random(seed)
    teams = [f"T{i:02d}" for i in range(20)]
    games = []
    for d in range(n_days):
        date = f"{season}-{4 + d // 40:02d}-{1 + d % 40:02d}"
        pool = list(teams)
        rng.shuffle(pool)
        for g in range(per_day):
            home, away = pool[2 * g], pool[2 * g + 1]
            fair = min(0.80, max(0.20, rng.gauss(0.54, 0.09)))
            home_price = odds_math.probability_to_american(fair * (1 + HOLD))
            away_price = odds_math.probability_to_american((1 - fair) * (1 + HOLD))
            feats = {}
            for f in FEATURES:
                diff = rng.uniform(-1.0, 1.0)
                feats["away_" + f] = diff
                feats["home_" + f] = 0.0
            # The market never moves on the plant -- close tracks fair up to
            # noise alone, so no movement-primary search can find anything
            # here regardless of `edge`.
            close = min(0.97, max(0.03, fair + rng.gauss(0.0, 0.01)))
            true_home_prob = fair
            if edge and feats["away_" + PLANTED_FEATURE] > PLANTED_THRESHOLD:
                true_home_prob = min(0.99, max(0.01, fair - edge))
            home_won = rng.random() < true_home_prob
            games.append(placebo.make_game(
                game_id=f"{season}-{d:04d}-{g}", date=date, season=season,
                home_team=home, away_team=away,
                home_price=home_price, away_price=away_price,
                home_won=home_won, features=feats, home_fair_close=close))
    return placebo.real_world(games)


# ---------------------------------------------------------------------------
# the outcome electorate is the one that votes, and the one that is consulted
# ---------------------------------------------------------------------------

class TestOutcomeElectorateSelected(unittest.TestCase):

    def test_outcome_ceiling_generator_ids_default_to_the_outcome_set(self):
        registry = tiny_registry()
        world = synthetic_outcome_world(11, edge=0.0, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        report = sweep.run_sweep(provider, registry=registry, max_signals=2,
                                 replicates=5, base_seed=1,
                                 spa_n_bootstrap=200, primary_fitness="outcome")
        self.assertEqual(report.config["ceiling_generator_ids"],
                         list(sweep.OUTCOME_CEILING_GENERATORS))
        self.assertEqual(report.config["primary_fitness"], "outcome")
        by_generator = {c.generator for c in report.ceiling.per_generator}
        self.assertEqual(by_generator, set(sweep.OUTCOME_CEILING_GENERATORS))

    def test_movement_electorate_is_not_consulted(self):
        """P6 -- the movement analogue of P1 -- must never vote on an outcome
        ceiling: it is not in `OUTCOME_CEILING_GENERATORS` at all, so it must
        be absent from the per-generator ceiling even though it still ran."""
        registry = tiny_registry()
        world = synthetic_outcome_world(11, edge=0.0, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        report = sweep.run_sweep(provider, registry=registry, max_signals=2,
                                 replicates=5, base_seed=1,
                                 spa_n_bootstrap=200, primary_fitness="outcome")
        by_generator = {c.generator for c in report.ceiling.per_generator}
        self.assertNotIn(placebo.P6, by_generator)
        # P6 still ran and is reported -- only its vote is withheld.
        self.assertIn(placebo.P6, report.placebo_world_ids)
        self.assertEqual(len(report.placebo_world_ids[placebo.P6]), 5)

    def test_default_movement_run_is_unaffected(self):
        """Calling run_sweep with no primary_fitness argument at all must
        still reproduce the movement path exactly -- this task changes what
        the outcome path does, never the default."""
        registry = tiny_registry()
        world = synthetic_outcome_world(11, edge=0.0, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        report = sweep.run_sweep(provider, registry=registry, max_signals=2,
                                 replicates=5, base_seed=1, spa_n_bootstrap=200)
        self.assertEqual(report.config["primary_fitness"], "movement")
        self.assertEqual(report.config["ceiling_generator_ids"],
                         list(sweep.MOVEMENT_CEILING_GENERATORS))


# ---------------------------------------------------------------------------
# a planted outcome edge clears; a null world does not
# ---------------------------------------------------------------------------

class TestPlantedOutcomeEdge(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = tiny_registry()
        cls.world = synthetic_outcome_world(23, edge=0.25, n_days=200)

        def provider():
            return sweep.ReplayFeed(world=cls.world)

        cls.report = sweep.run_sweep(
            provider, registry=cls.registry, max_signals=2, replicates=10,
            base_seed=7, spa_n_bootstrap=200, primary_fitness="outcome")

    def test_the_outcome_ceiling_clears(self):
        self.assertEqual(self.report.ceiling.verdict,
                         ceiling.CLEARS_PLACEBO_CEILING)
        self.assertEqual(self.report.config["min_generators"], 3)

    def test_no_movement_edge_leaked_in(self):
        """The plant is outcome-only: a movement-primary run of the SAME
        world must find nothing (the whole point of the fixture)."""
        def provider():
            return sweep.ReplayFeed(world=self.world)

        movement_report = sweep.run_sweep(
            provider, registry=self.registry, max_signals=2, replicates=10,
            base_seed=7, spa_n_bootstrap=200, primary_fitness="movement")
        self.assertEqual(movement_report.ceiling.verdict,
                         ceiling.BELOW_PLACEBO_CEILING)


class TestNullOutcomeWorldFails(unittest.TestCase):

    def test_verdict_is_below_placebo_ceiling_with_no_outcome_edge(self):
        registry = tiny_registry()
        world = synthetic_outcome_world(31, edge=0.0, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        report = sweep.run_sweep(provider, registry=registry, max_signals=2,
                                 replicates=10, base_seed=9,
                                 spa_n_bootstrap=200, primary_fitness="outcome")
        self.assertEqual(report.ceiling.verdict, ceiling.BELOW_PLACEBO_CEILING)
        self.assertTrue(report.ceiling.is_kill)


# ---------------------------------------------------------------------------
# P4 stays excluded from any ceiling, whichever fitness is primary
# ---------------------------------------------------------------------------

class TestP4ExcludedFromOutcomeCeilingToo(unittest.TestCase):

    def test_p4_absent_from_the_outcome_ceiling_but_still_reported(self):
        registry = tiny_registry()
        world = synthetic_outcome_world(41, edge=0.18, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        report = sweep.run_sweep(provider, registry=registry, max_signals=2,
                                 replicates=10, base_seed=2,
                                 spa_n_bootstrap=200, primary_fitness="outcome")
        generators = {c.generator for c in report.ceiling.per_generator}
        self.assertNotIn(placebo.P4, generators)
        self.assertIn(placebo.P4, report.placebo_world_ids)
        self.assertIsNotNone(report.p4_dispersion)
        self.assertEqual(report.p4_dispersion["generator"], placebo.P4)


# ---------------------------------------------------------------------------
# determinism and the WorldFitness.totals seam, directly
# ---------------------------------------------------------------------------

class TestDeterminismAndSeam(unittest.TestCase):

    def test_two_outcome_runs_are_byte_identical(self):
        registry = tiny_registry()
        world = synthetic_outcome_world(23, edge=0.18, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        kwargs = dict(registry=registry, max_signals=2, replicates=5,
                     base_seed=3, spa_n_bootstrap=200, primary_fitness="outcome")
        first = sweep.run_sweep(provider, **kwargs)
        second = sweep.run_sweep(provider, **kwargs)
        self.assertEqual(first.canonical_json(), second.canonical_json())

    def test_worldfitness_totals_reads_the_matching_table(self):
        registry = tiny_registry()
        from src.evolab import genome as genome_mod
        genomes = genome_mod.enumerate_genomes(registry, max_signals=2)
        world = synthetic_outcome_world(23, edge=0.18, n_days=140)
        fit = sweep.sweep_world(world, genomes, registry)
        self.assertEqual(fit.totals("movement"), fit.totals_movement)
        self.assertEqual(fit.totals("outcome"), fit.totals_roi)
        with self.assertRaises(sweep.SweepError):
            fit.totals("not_a_fitness")

    def test_run_sweep_refuses_an_unknown_primary_fitness(self):
        registry = tiny_registry()
        world = synthetic_outcome_world(2, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        with self.assertRaises(sweep.SweepError):
            sweep.run_sweep(provider, registry=registry, max_signals=2,
                            primary_fitness="roi")


if __name__ == "__main__":
    unittest.main()
