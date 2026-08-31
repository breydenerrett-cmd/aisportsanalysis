"""The Phase 2B sweep driver -- src/evolab/sweep.py.

WHAT THESE TESTS ESTABLISH
---------------------------
Every scenario below is driven by a SYNTHETIC injected `ReplayProvider`
(design section 14b / this module's own docstring): none of it touches
`src/evolab/replay.py`, and none of it is evidence about baseball.

The acceptance list this file exists to satisfy:

  1. determinism: two runs of the identical sweep are byte-identical.
  2. the bitset fast path agrees with `decide.py`'s reference semantics,
     game for game, genome for genome -- the correctness argument for using
     bitsets at all (design section 12).
  3. a planted MOVEMENT edge: the real search maximum clears the generators
     that can see it (P2, P3) and PBO comes out low.
  4. a genuine finding surfaced along the way, asserted rather than
     suppressed: P1 and P5 permute only `home_won`, so a MOVEMENT-primary
     fitness (design section 6) is invariant under both -- every placebo
     replicate reproduces the real maximum exactly, and `run_sweep` warns
     about it instead of letting the tie masquerade as "does not clear".
     This is why the planted-edge scenario checks per-generator ceilings and
     a majority restricted to the discriminating generators, rather than
     asserting the default four-generator vote clears -- that vote is
     structurally capped at 2 of 4 for this fitness, which section 15's
     kill criterion correctly reports as INCONCLUSIVE, not a bug to route
     around.
  5. pure noise: the verdict is BELOW_PLACEBO_CEILING and PBO averages to
     about 0.5 (individual seeds range widely -- the same property
     `tests/test_evolab_stats.py` documents for `cscv.cscv` directly).
  6. P4 is absent from the ceiling and the kill criterion by default, and
     present as a labelled dispersion diagnostic.
  7. every artifact is stamped per design section 11, and namespace
     isolation is enforced by `SweepReport.write`, not by convention.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import tempfile
import unittest

from src.core import odds as odds_math
from src.evolab import ceiling, decide, genome as genome_mod, placebo, sweep
from src.evolab.decide import BoardMeta, WorldView
from src.evolab.registry import SignalRegistry

HOLD = 0.045
FEATURES = ("lineup_platoon_share", "top_minus_bottom")
PLANTED_FEATURE = "lineup_platoon_share"
PLANTED_THRESHOLD = 0.2


def tiny_registry() -> SignalRegistry:
    """Two features, three-rung ladders -- small enough to enumerate fast and
    reason about by hand, built the way registry.py's own docstring says
    tests should (a private registry, never the shared default)."""
    reg = SignalRegistry()
    reg.register(
        feature="lineup_platoon_share",
        mechanism="synthetic test mechanism only, exactly five words",
        direction=+1, ladder=(0.2, 0.4, 0.6), scope="FIRST_FIVE",
        provenance="synthetic test fixture, not derived from any real data")
    reg.register(
        feature="top_minus_bottom",
        mechanism="a second synthetic mechanism used only by this test module",
        direction=-1, ladder=(0.2, 0.4, 0.6), scope="FIRST_FIVE",
        provenance="synthetic test fixture, not derived from any real data")
    return reg


def synthetic_world(seed: int, *, edge: float = 0.0, n_days: int = 140,
                    per_day: int = 6, season: int = 2023) -> placebo.World:
    """A season of games with a known price, a known grade and (optionally) a
    known MOVEMENT edge: away-side differential on `PLANTED_FEATURE` above
    `PLANTED_THRESHOLD` shifts the close away from the decision price in the
    away side's favour by `edge`. Deliberately price- and outcome-independent
    of the feature otherwise, so a search that finds it found the plant and
    nothing else.
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
            noise = rng.gauss(0.0, 0.01)
            close = fair + noise
            if edge and feats["away_" + PLANTED_FEATURE] > PLANTED_THRESHOLD:
                close = fair - edge + noise      # away side advantaged
            close = min(0.97, max(0.03, close))
            home_won = rng.random() < close
            games.append(placebo.make_game(
                game_id=f"{season}-{d:04d}-{g}", date=date, season=season,
                home_team=home, away_team=away,
                home_price=home_price, away_price=away_price,
                home_won=home_won, features=feats, home_fair_close=close))
    return placebo.real_world(games)


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):

    def test_two_runs_are_byte_identical(self):
        registry = tiny_registry()
        world = synthetic_world(11, edge=0.05, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world, manifest={"note": "fixture"})

        kwargs = dict(registry=registry, max_signals=2, replicates=5,
                     base_seed=3, spa_n_bootstrap=200)
        first = sweep.run_sweep(provider, **kwargs)
        second = sweep.run_sweep(provider, **kwargs)
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_different_base_seed_gives_a_different_report(self):
        registry = tiny_registry()
        world = synthetic_world(11, edge=0.0, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        a = sweep.run_sweep(provider, registry=registry, max_signals=2,
                            replicates=5, base_seed=1, spa_n_bootstrap=200)
        b = sweep.run_sweep(provider, registry=registry, max_signals=2,
                            replicates=5, base_seed=2, spa_n_bootstrap=200)
        self.assertNotEqual(a.canonical_json(), b.canonical_json())
        # what does NOT move with the placebo seed: the real world itself.
        self.assertEqual(a.real_world_id, b.real_world_id)
        self.assertEqual(a.real_max_movement, b.real_max_movement)


# ---------------------------------------------------------------------------
# the bitset fast path against decide.py's reference semantics
# ---------------------------------------------------------------------------

class TestAgreesWithDecide(unittest.TestCase):
    """`sweep._side_profiles` / `_resolve_ties` must select exactly what
    `decide.decide` selects, game for game, for every enumerated genome.

    This is the correctness argument for the whole bitset shortcut (design
    section 12): it is bound to `decide.py` not by shared code but by this
    test running both paths over the same genomes and games.
    """

    @classmethod
    def setUpClass(cls):
        cls.registry = tiny_registry()
        cls.genomes = genome_mod.enumerate_genomes(cls.registry, max_signals=2)
        cls.world = synthetic_world(3, edge=0.05, n_days=40, per_day=6)

    @staticmethod
    def _worldview_for(game) -> WorldView:
        # Three identical books: decide()'s default eligibility wants
        # min_books=3, and the sweep's own contract is that the provider has
        # already resolved eligibility -- so the comparison must hand
        # decide() a board that clears the same gate the sweep assumes.
        board = {"h2h": {b: {"away_price": game.away_price,
                            "home_price": game.home_price}
                        for b in ("book1", "book2", "book3")}}
        return WorldView(
            game_id=game.game_id, official_date=game.date,
            commence_time=game.date + "T00:00:00Z", point_class="LATE_BOARD",
            game={"away": game.away_team, "home": game.home_team,
                 "park": "synthetic", "commence_time": game.date},
            features=dict(game.features), board=board,
            board_meta=BoardMeta(observed_utc=game.date + "T00:00:00Z",
                                books=("book1", "book2", "book3"),
                                simultaneous=True, staleness_seconds=0),
            available=("h2h",), lineup_posted=True)

    def test_every_genome_selects_the_same_side_as_decide(self):
        diffs = sweep._differentials_by_feature(self.world, self.registry)
        from src.evolab.bitsets import build_signal_mask_table, universe_mask
        mask_table = build_signal_mask_table(self.registry, diffs)
        universe = universe_mask(self.world.n_games)
        worldviews = [self._worldview_for(g) for g in self.world.games]

        checked = 0
        for g in self.genomes:
            away_mask, home_mask = sweep._resolve_ties(
                sweep._side_profiles(g, mask_table, universe))
            for i, wv in enumerate(worldviews):
                decision = decide.decide(g, wv, registry=self.registry)
                expected = decision.side if decision else None
                bit_side = ("away" if (away_mask >> i) & 1 else
                           "home" if (home_mask >> i) & 1 else None)
                self.assertEqual(
                    expected, bit_side,
                    f"genome {g.strategy_id} game {i}: decide()={expected!r} "
                    f"bitset={bit_side!r}")
                checked += 1
        self.assertGreater(checked, 1000)


# ---------------------------------------------------------------------------
# planted movement edge
# ---------------------------------------------------------------------------

class TestPlantedEdge(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = tiny_registry()
        cls.world = synthetic_world(11, edge=0.06, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=cls.world)

        cls.report = sweep.run_sweep(
            provider, registry=cls.registry, max_signals=2, replicates=10,
            base_seed=3, spa_n_bootstrap=200)

    def test_p2_and_p3_clear_with_a_real_margin(self):
        by_generator = {c.generator: c for c in self.report.ceiling.per_generator}
        for gid in (placebo.P2, placebo.P3):
            c = by_generator[gid]
            self.assertTrue(c.clears, f"{gid} should clear for a planted edge")
            self.assertGreater(c.margin, 0.0)

    def test_p1_and_p5_tie_the_real_maximum_and_are_flagged(self):
        """The finding: outcome-only permutation cannot null a movement edge."""
        by_generator = {c.generator: c for c in self.report.ceiling.per_generator}
        for gid in (placebo.P1, placebo.P5):
            c = by_generator[gid]
            self.assertFalse(c.clears)
            self.assertEqual(c.placebo_max, self.report.real_max_movement)
        joined = " ".join(self.report.warnings)
        self.assertIn("P1", joined)
        self.assertIn("P5", joined)
        self.assertIn("structurally uninformative", joined)

    def test_default_four_generator_vote_is_inconclusive_not_a_false_clear(self):
        """2 of 4 clearing is not a majority; the kill criterion must not be
        fooled into CLEARS by rounding a tie in the champion's favour."""
        self.assertEqual(self.report.ceiling.verdict, ceiling.INCONCLUSIVE)

    def test_restricted_to_the_discriminating_generators_it_clears(self):
        def provider():
            return sweep.ReplayFeed(world=self.world)

        restricted = sweep.run_sweep(
            provider, registry=self.registry, max_signals=2, replicates=10,
            base_seed=3, spa_n_bootstrap=200,
            ceiling_generator_ids=(placebo.P2, placebo.P3), min_generators=2)
        self.assertEqual(restricted.ceiling.verdict,
                         ceiling.CLEARS_PLACEBO_CEILING)

    def test_pbo_is_low(self):
        self.assertLess(self.report.cscv.pbo, 0.15)

    def test_spa_cross_check_agrees_with_the_restricted_ceiling(self):
        # SPA is analytic and does not know about generators at all; it
        # should reject the null here, agreeing with the empirical signal.
        self.assertLess(self.report.spa.p_value, 0.10)


# ---------------------------------------------------------------------------
# pure noise
# ---------------------------------------------------------------------------

class TestPureNoise(unittest.TestCase):

    def test_verdict_is_below_placebo_ceiling(self):
        registry = tiny_registry()
        world = synthetic_world(17, edge=0.0, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        report = sweep.run_sweep(provider, registry=registry, max_signals=2,
                                 replicates=10, base_seed=5,
                                 spa_n_bootstrap=200)
        self.assertEqual(report.ceiling.verdict, ceiling.BELOW_PLACEBO_CEILING)
        self.assertTrue(report.ceiling.is_kill)

    def test_pbo_averages_to_about_one_half(self):
        """Individual seeds range widely (see test_evolab_stats.py's own
        validator-validation test); the average over pinned seeds is what is
        centred on 0.5. Computed directly from `sweep_world` + `cscv.cscv`,
        skipping the placebo suite entirely, because PBO is a property of the
        real fitness table alone (design section 8) and does not need 40
        placebo worlds recomputed per seed to check it."""
        from src.evolab import cscv as cscv_mod
        registry = tiny_registry()
        genomes = genome_mod.enumerate_genomes(registry, max_signals=2)
        pbos = []
        for seed in range(20):
            world = synthetic_world(seed, edge=0.0, n_days=140)
            fit = sweep.sweep_world(world, genomes, registry, min_selections=30)
            pbos.append(cscv_mod.cscv(fit.movement_table).pbo)
        mean = statistics.mean(pbos)
        self.assertGreater(mean, 0.35)
        self.assertLess(mean, 0.65)
        self.assertTrue(any(p < 0.5 for p in pbos))
        self.assertTrue(any(p > 0.5 for p in pbos))


# ---------------------------------------------------------------------------
# P4 is a diagnostic, never a ceiling input
# ---------------------------------------------------------------------------

class TestP4Excluded(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        registry = tiny_registry()
        world = synthetic_world(9, edge=0.06, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        cls.report = sweep.run_sweep(provider, registry=registry,
                                     max_signals=2, replicates=10,
                                     base_seed=4, spa_n_bootstrap=200)

    def test_p4_is_absent_from_the_ceiling(self):
        generators = {c.generator for c in self.report.ceiling.per_generator}
        self.assertNotIn(placebo.P4, generators)

    def test_p4_still_ran_and_is_reported_as_a_dispersion_diagnostic(self):
        self.assertIn(placebo.P4, self.report.placebo_world_ids)
        self.assertEqual(len(self.report.placebo_world_ids[placebo.P4]), 10)
        self.assertIsNotNone(self.report.p4_dispersion)
        self.assertEqual(self.report.p4_dispersion["generator"], placebo.P4)
        self.assertIn("dispersion diagnostic", self.report.p4_dispersion["note"])

    def test_default_ceiling_generator_ids_exclude_p4_only(self):
        self.assertNotIn(placebo.P4, self.report.config["ceiling_generator_ids"])
        for gid in (placebo.P1, placebo.P2, placebo.P3, placebo.P5):
            self.assertIn(gid, self.report.config["ceiling_generator_ids"])


# ---------------------------------------------------------------------------
# artifact stamping and namespace isolation
# ---------------------------------------------------------------------------

class TestArtifactStamping(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = tiny_registry()
        cls.world = synthetic_world(21, edge=0.0, n_days=140)
        cls.manifest = {"engine_version": "test-1", "seasons": [2023]}

        def provider():
            return sweep.ReplayFeed(world=cls.world, manifest=cls.manifest)

        cls.report = sweep.run_sweep(provider, registry=cls.registry,
                                     max_signals=2, replicates=5,
                                     base_seed=6, spa_n_bootstrap=200)

    def test_every_required_stamp_is_present(self):
        d = self.report.to_dict()
        self.assertEqual(len(d["enumeration_spec_hash"]), 64)
        self.assertEqual(d["registry_fingerprint"], self.registry.fingerprint())
        self.assertIn("code_commit", d)   # None is a legal, honest value too
        self.assertEqual(d["replay_manifest"], self.manifest)
        self.assertEqual(d["real_world_id"], self.world.world_id)
        for gid in placebo.GENERATOR_IDS:
            self.assertEqual(len(d["placebo_world_ids"][gid]), 5)
            self.assertEqual(len(d["placebo_seeds"][gid]), 5)
            # every world id is unique -- no seed collision across replicates
            self.assertEqual(len(set(d["placebo_world_ids"][gid])), 5)

    def test_manifest_object_with_to_dict_is_normalised(self):
        class FakeManifest:
            def to_dict(self):
                return {"engine_version": "test-2"}

        def provider():
            return sweep.ReplayFeed(world=self.world, manifest=FakeManifest())

        report = sweep.run_sweep(provider, registry=self.registry,
                                 max_signals=2, replicates=3, base_seed=1,
                                 spa_n_bootstrap=200)
        self.assertEqual(report.replay_manifest, {"engine_version": "test-2"})

    def test_report_round_trips_through_json(self):
        payload = json.loads(self.report.canonical_json())
        self.assertEqual(payload["real_world_id"], self.world.world_id)

    def test_write_refuses_outside_the_evolab_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                os.makedirs(os.path.join("data", "research", "evolab"))
                with self.assertRaises(sweep.SweepError):
                    self.report.write("data/research/somewhere_else")
                with self.assertRaises(sweep.SweepError):
                    self.report.write("/etc")
            finally:
                os.chdir(cwd)

    def test_write_succeeds_inside_the_namespace_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                path = self.report.write()
                self.assertTrue(os.path.exists(path))
                self.assertTrue(path.startswith(
                    os.path.join(tmp, "data", "research", "evolab")))
                with open(path, encoding="utf-8") as fh:
                    on_disk = json.load(fh)
                self.assertEqual(on_disk, json.loads(self.report.canonical_json()))
                # re-running and re-writing is idempotent: same bytes, same path
                second_path = self.report.write()
                self.assertEqual(path, second_path)
            finally:
                os.chdir(cwd)


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

class TestGuards(unittest.TestCase):

    def test_run_sweep_refuses_a_non_consensus_execution_mode(self):
        registry = tiny_registry()
        world = synthetic_world(2, n_days=140)

        def provider():
            return sweep.ReplayFeed(world=world)

        with self.assertRaises(sweep.SweepError):
            sweep.run_sweep(provider, registry=registry, max_signals=2,
                            execution="BEST_OBSERVED_EXECUTION")

    def test_run_sweep_refuses_a_provider_that_returns_the_wrong_type(self):
        def bad_provider():
            return {"world": None}

        with self.assertRaises(sweep.SweepError):
            sweep.run_sweep(bad_provider, registry=tiny_registry(),
                            max_signals=2)

    def test_sweep_world_refuses_an_f5_routed_genome(self):
        registry = tiny_registry()
        world = synthetic_world(2, n_days=140)
        genomes = genome_mod.enumerate_genomes(
            registry, max_signals=1,
            eligibility={"markets": genome_mod.MARKETS, "min_books": 3,
                        "require_lineup": True},
            routings=[{"market_preference": (genome_mod.F5_MARKET,),
                      "f5_condition": "if_all_signals_first_five"}])
        with self.assertRaises(sweep.SweepError):
            sweep.sweep_world(world, genomes, registry)

    def test_dead_strategies_are_absent_not_zeroed(self):
        """A genome demanding both signals fire, at the top ladder rung, on a
        small world should not clear a realistic min_selections gate -- and
        must be ABSENT from the fitness table, per design section 6's "gates
        are gates, not additive terms"."""
        registry = tiny_registry()
        world = synthetic_world(5, n_days=20, per_day=2)   # only 40 games
        genomes = genome_mod.enumerate_genomes(registry, max_signals=2)
        fit = sweep.sweep_world(world, genomes, registry, n_blocks=4,
                                min_selections=1_000_000)
        self.assertEqual(fit.n_strategies, 0)
        self.assertEqual(fit.movement_table, {})

    def test_run_sweep_raises_when_the_real_world_clears_no_gate(self):
        registry = tiny_registry()
        world = synthetic_world(5, n_days=20, per_day=2)

        def provider():
            return sweep.ReplayFeed(world=world)

        with self.assertRaises(sweep.SweepError):
            sweep.run_sweep(provider, registry=registry, max_signals=2,
                            n_blocks=4, min_selections=1_000_000,
                            replicates=2, spa_n_bootstrap=110)


if __name__ == "__main__":
    unittest.main()
