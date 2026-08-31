"""Evolution Lab statistics: placebo generators, CSCV/PBO, SPA, and the ceiling.

THE TESTS THAT MATTER MOST ARE THE VALIDATOR VALIDATION
-------------------------------------------------------
`TestValidatorValidation` and `TestEndToEndCeiling` are the acceptance criteria
from the design's section 8 and section 14.7. Until they pass, no PBO number
may be reported anywhere:

- planted edge  -> PBO must come out LOW and the planted strategy must clear
  the placebo ceiling;
- pure noise    -> PBO must come out about 0.5 and the best strategy must NOT
  clear the ceiling;
- identical strategies -> no spurious ranking signal of any kind.

The third is the one a plumbing test would miss. A table of identical
strategies contains no information, so the honest PBO is 0.5. Counting only
strict "below median" would report 0.0 -- "no overfitting detected" -- from a
table with nothing in it, and regressing out-of-sample on in-sample across the
252 splits would report a confident slope built entirely from the last bits of
float addition. Both are asserted against here.

THE OTHER HALF: DOES EACH PLACEBO WORLD PRESERVE WHAT IT CLAIMS
---------------------------------------------------------------
A placebo world that is EASIER than reality understates the ceiling, and a
worthless strategy then clears it. That failure is silent, so each generator is
tested for the structure it claims to preserve -- exactly where exact
preservation is possible -- and `TestGeneratorFaithfulness` measures the search
maxima the generators actually produce against the search maxima of genuinely
null real worlds. That measurement is the only thing that can catch an "easier
world" that every structural test still passes.

Two generator properties are asserted here as FACTS, not as flaws to fix
quietly, because both change how their numbers must be read:

1. P1 detaches outcome from PRICE as well as from features, so its search
   maxima run high. Conservative for a ceiling, and not a null for any rule
   that selects on price.
2. P4 copies whole days with features, prices and outcomes still attached, so
   a REAL EDGE SURVIVES INTO A P4 WORLD. P4 measures resampling dispersion of
   the search maximum, not the maximum reachable with no edge present. It is
   asserted below that a planted edge does survive it (`test_p4_carries_a_planted_edge`)
   so nobody reads P4 as an edge-destroying null by mistake.

Nothing produced by any of this is evidence.
"""

from __future__ import annotations

import math
import random
import statistics
import unittest

from src.core import odds as odds_math
from src.evolab import ceiling, cscv, placebo, spa

# --------------------------------------------------------------------------
# synthetic worlds
#
# Deliberately price-INDEPENDENT features: with a feature that tracks the
# line, P1's documented artifact would dominate every measurement below and
# the tests would be measuring the generator instead of the machinery. The one
# test that wants that artifact builds a price-correlated feature on purpose.
# --------------------------------------------------------------------------

FEATURES = tuple(f"{side}_f{i}" for side in ("home", "away") for i in range(3))
THRESHOLDS = (0.4, 0.55, 0.7)
SIDES = ("home", "away")
HOLD = 0.045                      # 4.5% two-way hold, proportional
PLANTED_FEATURE = "home_f0"
PLANTED_THRESHOLD = 0.5
PLANTED_EDGE = 0.15               # probability points added to the home side


MIN_SELECTIONS = 100              # a gate, not a penalty (design section 6)


def synthetic_world(seed: int, *, edge: float = 0.0, n_days: int = 200,
                    per_day: int = 6, season: int = 2023,
                    price_feature: bool = False) -> placebo.World:
    """A season of games with known prices, known outcomes and a known edge.

    Prices are built from a fair probability inflated by a proportional hold,
    so `src.core.odds.devig_two_way` recovers the planted fair probability
    exactly -- the market in this world is calibrated by construction, which is
    what makes it a fair test bed for P5.

    `edge` plants a genuine feature -> outcome relationship: when
    `home_f0 > 0.5` the home side wins `edge` more often than its price says.
    `price_feature` instead makes `home_f0` a copy of the line, which is how
    the P1 artifact is demonstrated.
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
            feats = {f: rng.random() for f in FEATURES}
            if price_feature:
                feats[PLANTED_FEATURE] = fair
            p = fair
            if edge and feats[PLANTED_FEATURE] > PLANTED_THRESHOLD:
                p = min(0.97, fair + edge)
            games.append(placebo.make_game(
                game_id=f"{season}-{d:04d}-{g}", date=date, season=season,
                home_team=home, away_team=away,
                home_price=home_price, away_price=away_price,
                home_won=rng.random() < p, features=feats))
    return placebo.real_world(games)


def two_season_world(seed: int) -> placebo.World:
    """Two seasons, so the per-season logic in P2 and P3 is exercised."""
    a = synthetic_world(seed, n_days=60, per_day=4, season=2023)
    b = synthetic_world(seed + 1, n_days=60, per_day=4, season=2024)
    return placebo.real_world(list(a.games) + list(b.games))


def strategy_ids() -> list[str]:
    return [f"{f}>{t}|{s}" for f in FEATURES for t in THRESHOLDS for s in SIDES]


def roi_search(world: placebo.World, n_blocks: int = 10,
               min_selections: int = MIN_SELECTIONS):
    """Enumerate every threshold rule and score it by flat-stake outcome ROI.

    Stands in for the lab's real enumeration: the point of these tests is the
    statistics, and the statistics only need a search that is deterministic,
    identical across worlds, and scored per chronological block so CSCV has a
    table to work on. Returns (total_roi_by_strategy, per_block_roi_by_strategy).

    `min_selections` is a gate in the design's sense -- a rule that bets forty
    games is killed, not penalised. Without it the search maximum is routinely
    a forty-game rule holding a huge number by luck, and every comparison in
    this file would be measuring small samples rather than the machinery.
    """
    days = world.days()
    bounds = cscv.chronological_blocks(len(days), n_blocks)
    block_of = {}
    for block_index, (lo, hi) in enumerate(bounds):
        for day_position in range(lo, hi):
            block_of[days[day_position][0]] = block_index

    totals: dict[str, float] = {}
    per_block: dict[str, list[float]] = {}
    for feature in FEATURES:
        for threshold in THRESHOLDS:
            for side in SIDES:
                returns = [0.0] * n_blocks
                counts = [0] * n_blocks
                for game in world.games:
                    if game.home_won is None:
                        continue          # never bet a game we cannot grade
                    value = game.features.get(feature)
                    if value is None or value <= threshold:
                        continue
                    block = block_of[game.day_index]
                    counts[block] += 1
                    won = game.home_won if side == "home" else not game.home_won
                    price = game.home_price if side == "home" else game.away_price
                    returns[block] += (
                        odds_math.american_to_decimal(price) - 1.0 if won else -1.0)
                n = sum(counts)
                if n < min_selections:
                    continue
                sid = f"{feature}>{threshold}|{side}"
                totals[sid] = sum(returns) / n
                per_block[sid] = [r / c if c else 0.0
                                  for r, c in zip(returns, counts)]
    return totals, per_block


def features_key(game: placebo.Game):
    return tuple(sorted(game.features.items()))


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):
    """Same world, same seed, identical placebo world -- for every generator.

    Determinism is not a nicety here. A ceiling is a comparison against 50
    fictional worlds; if those worlds cannot be rebuilt exactly from their
    recorded seed, the comparison cannot be reproduced and the number means
    nothing.
    """

    @classmethod
    def setUpClass(cls):
        cls.world = synthetic_world(11, n_days=40, per_day=4)

    def test_every_generator_is_reproducible_from_its_seed(self):
        for gid in placebo.GENERATOR_IDS:
            with self.subTest(generator=gid):
                a = placebo.generate(gid, self.world, 12345)
                b = placebo.generate(gid, self.world, 12345)
                self.assertEqual(a.games, b.games)
                self.assertEqual(a.world_id, b.world_id)

    def test_different_seeds_give_different_worlds(self):
        for gid in placebo.GENERATOR_IDS:
            with self.subTest(generator=gid):
                a = placebo.generate(gid, self.world, 1)
                b = placebo.generate(gid, self.world, 2)
                self.assertNotEqual(a.games, b.games)
                self.assertNotEqual(a.world_id, b.world_id)

    def test_world_id_records_generator_and_seed(self):
        world = placebo.p5_market_truth(self.world, 77)
        self.assertTrue(world.world_id.startswith("P5-s77-"))
        self.assertEqual(world.source_world_id, self.world.world_id)
        self.assertEqual(world.seed, 77)

    def test_generators_never_touch_the_global_rng(self):
        """A generator that used the global RNG would change other people's draws."""
        random.seed(4)
        before = [random.random() for _ in range(3)]
        random.seed(4)
        for gid in placebo.GENERATOR_IDS:
            placebo.generate(gid, self.world, 9)
        after = [random.random() for _ in range(3)]
        self.assertEqual(before, after)

    def test_suite_yields_fifty_distinct_worlds(self):
        worlds = list(placebo.placebo_suite(self.world, replicates=10, base_seed=3))
        self.assertEqual(len(worlds), 50)
        self.assertEqual(len({w.world_id for w in worlds}), 50)
        again = list(placebo.placebo_suite(self.world, replicates=10, base_seed=3))
        self.assertEqual([w.world_id for w in worlds], [w.world_id for w in again])

    def test_unknown_generator_raises_rather_than_defaulting(self):
        with self.assertRaises(placebo.PlaceboError):
            placebo.generate("P9", self.world, 1)


# --------------------------------------------------------------------------
# P1
# --------------------------------------------------------------------------

class TestP1OutcomePermutation(unittest.TestCase):
    """P1 must preserve the slate and every price EXACTLY, and break outcomes."""

    @classmethod
    def setUpClass(cls):
        cls.world = synthetic_world(21, n_days=200, per_day=6)
        cls.p1 = placebo.p1_outcome_permutation(cls.world, 5)
        cls.by_id = {g.game_id: g for g in cls.world.games}

    def test_slate_is_identical_game_for_game(self):
        self.assertEqual([g.game_id for g in self.p1.games],
                         [g.game_id for g in self.world.games])
        real_counts = {d: len(games) for d, games in self.world.days()}
        placebo_counts = {d: len(games) for d, games in self.p1.days()}
        self.assertEqual(real_counts, placebo_counts)

    def test_every_price_and_feature_survives_untouched(self):
        for game in self.p1.games:
            source = self.by_id[game.game_id]
            self.assertEqual(game.home_price, source.home_price)
            self.assertEqual(game.away_price, source.away_price)
            self.assertEqual(game.home_fair, source.home_fair)
            self.assertEqual(game.features, source.features)
            self.assertEqual(game.home_team, source.home_team)
            self.assertEqual(game.away_team, source.away_team)

    def test_home_wins_per_date_are_preserved_exactly(self):
        for (day, real_games), (_, placebo_games) in zip(
                self.world.days(), self.p1.days()):
            with self.subTest(day=day):
                self.assertEqual(sum(1 for g in real_games if g.home_won),
                                 sum(1 for g in placebo_games if g.home_won))
        self.assertEqual(placebo.home_win_rate(self.p1),
                         placebo.home_win_rate(self.world))

    def test_outcomes_actually_moved(self):
        moved = sum(1 for g in self.p1.games
                    if g.home_won != self.by_id[g.game_id].home_won)
        self.assertGreater(moved, self.world.n_games // 10)

    def test_p1_detaches_outcome_from_price_and_the_option_repairs_it(self):
        """The documented limitation, asserted rather than left as prose.

        Aggregate calibration is untouched by P1 -- the day's home-win count is
        preserved -- so only the price/outcome alignment can see the damage.
        Stratifying the permutation by price band restores it, which is why the
        option exists.
        """
        real = placebo.price_outcome_alignment(self.world)
        broken = placebo.price_outcome_alignment(self.p1)
        self.assertGreater(real, 0.01)
        self.assertLess(abs(broken), 0.6 * real)

        # Aggregate calibration is blind to this, on purpose:
        self.assertAlmostEqual(placebo.calibration_error(self.p1),
                               placebo.calibration_error(self.world), places=12)

        stratified = placebo.p1_outcome_permutation(
            self.world, 5, price_band_width=0.05)
        repaired = placebo.price_outcome_alignment(stratified)
        self.assertGreater(repaired, 0.8 * real)

    def test_ungraded_games_stay_ungraded(self):
        games = list(self.world.games[:20])
        games[0] = placebo.make_game(
            game_id="ungraded", date=games[0].date, season=games[0].season,
            home_team="AAA", away_team="BBB", home_price=-110, away_price=-110,
            home_won=None, features={"home_f0": 0.5})
        world = placebo.real_world(games)
        out = placebo.p1_outcome_permutation(world, 1)
        self.assertIsNone(
            next(g for g in out.games if g.game_id == "ungraded").home_won)


# --------------------------------------------------------------------------
# P2
# --------------------------------------------------------------------------

class TestP2TeamPermutation(unittest.TestCase):
    """P2's whole safety property: the price never leaves the team that played."""

    @classmethod
    def setUpClass(cls):
        cls.world = two_season_world(31)
        cls.p2 = placebo.p2_team_permutation(cls.world, 5)
        cls.by_id = {g.game_id: g for g in cls.world.games}

    def test_price_outcome_and_team_labels_are_untouched(self):
        """The design hazard, tested directly.

        If a permutation carried the price onto a team that did not play, the
        world would contain a real, trivially findable mispricing and its
        maxima would measure that artifact instead of our search.
        """
        for game in self.p2.games:
            source = self.by_id[game.game_id]
            self.assertEqual(game.home_price, source.home_price)
            self.assertEqual(game.away_price, source.away_price)
            self.assertEqual(game.home_fair, source.home_fair)
            self.assertEqual(game.home_won, source.home_won)
            self.assertEqual(game.home_team, source.home_team)
            self.assertEqual(game.away_team, source.away_team)
            self.assertEqual(game.date, source.date)

    def test_market_calibration_is_bit_identical(self):
        self.assertEqual(placebo.price_outcome_alignment(self.p2),
                         placebo.price_outcome_alignment(self.world))
        self.assertEqual(placebo.calibration_error(self.p2),
                         placebo.calibration_error(self.world))

    def test_features_moved_for_essentially_every_game(self):
        changed = sum(1 for g in self.p2.games
                      if g.features != self.by_id[g.game_id].features)
        self.assertGreater(changed, 0.9 * self.p2.n_games)

    def test_every_side_block_is_a_real_block_from_the_donor_team(self):
        """Features are borrowed, never synthesised.

        Each side's block in the placebo world must be a block that the donor
        team really produced on that side, in that season -- otherwise P2 would
        be inventing feature values, and the world's feature distribution would
        no longer be the real one.
        """
        pools = {}
        for game in self.world.games:
            pools.setdefault((game.season, "home", game.home_team), []).append(
                {k: v for k, v in game.features.items() if k.startswith("home_")})
            pools.setdefault((game.season, "away", game.away_team), []).append(
                {k: v for k, v in game.features.items() if k.startswith("away_")})

        permutations = self.p2.params["permutations"]
        for game in self.p2.games:
            season = game.season
            perm = permutations[str(season)]
            home_block = {k: v for k, v in game.features.items()
                          if k.startswith("home_")}
            away_block = {k: v for k, v in game.features.items()
                          if k.startswith("away_")}
            self.assertIn(home_block, pools[(season, "home", perm[game.home_team])])
            self.assertIn(away_block, pools[(season, "away", perm[game.away_team])])

    def test_permutation_is_a_derangement_within_each_season(self):
        for season, perm in self.p2.params["permutations"].items():
            with self.subTest(season=season):
                self.assertEqual(sorted(perm), sorted(perm.values()))
                self.assertFalse([t for t, donor in perm.items() if t == donor])

    def test_permutations_are_independent_across_seasons(self):
        perms = self.p2.params["permutations"]
        self.assertEqual(len(perms), 2)
        self.assertNotEqual(perms["2023"], perms["2024"])


# --------------------------------------------------------------------------
# P3
# --------------------------------------------------------------------------

class TestP3DateShift(unittest.TestCase):
    """P3 must preserve the multiset of feature vectors exactly."""

    @classmethod
    def setUpClass(cls):
        cls.world = two_season_world(41)
        cls.p3 = placebo.p3_date_shift(cls.world, 5)
        cls.by_id = {g.game_id: g for g in cls.world.games}

    def test_feature_vectors_are_rotated_not_resampled(self):
        """A rotation drops nothing and duplicates nothing.

        Any other shift -- truncating at the season edge, or drawing a donor at
        random -- would change the feature distribution the search sees, and a
        world with a thinner feature distribution is an easier world.
        """
        self.assertEqual(sorted(features_key(g) for g in self.world.games),
                         sorted(features_key(g) for g in self.p3.games))

    def test_prices_outcomes_and_identities_are_untouched(self):
        for game in self.p3.games:
            source = self.by_id[game.game_id]
            self.assertEqual(game.home_price, source.home_price)
            self.assertEqual(game.home_won, source.home_won)
            self.assertEqual(game.home_team, source.home_team)
            self.assertEqual(game.date, source.date)

    def test_alignment_is_broken_for_every_game(self):
        unchanged = sum(1 for g in self.p3.games
                        if g.features == self.by_id[g.game_id].features)
        self.assertEqual(unchanged, 0)

    def test_features_never_cross_a_season_boundary(self):
        seasons = {}
        for game in self.world.games:
            seasons.setdefault(features_key(game), set()).add(game.season)
        for game in self.p3.games:
            self.assertIn(game.season, seasons[features_key(game)])

    def test_shift_is_measured_in_game_days_and_is_never_zero(self):
        for season, shift in self.p3.params["shift_by_season"].items():
            with self.subTest(season=season):
                self.assertGreaterEqual(shift, 1)
        fixed = placebo.p3_date_shift(self.world, 5, k_days=10)
        self.assertEqual(set(fixed.params["shift_by_season"].values()), {10})

    def test_market_calibration_survives(self):
        self.assertEqual(placebo.price_outcome_alignment(self.p3),
                         placebo.price_outcome_alignment(self.world))


# --------------------------------------------------------------------------
# P4
# --------------------------------------------------------------------------

class TestP4BlockBootstrap(unittest.TestCase):
    """P4 must move whole days, intact, and must be honest about what it is."""

    @classmethod
    def setUpClass(cls):
        cls.world = synthetic_world(51, n_days=200, per_day=6)
        cls.p4 = placebo.p4_block_bootstrap(cls.world, 5)

    def test_game_day_count_is_preserved(self):
        self.assertEqual(self.p4.n_days, self.world.n_days)
        self.assertEqual([d for d, _ in self.p4.days()],
                         list(range(self.world.n_days)))

    def test_every_resampled_day_is_an_exact_copy_of_a_real_day(self):
        """Features, prices and outcomes travel together or the day is a fiction."""
        def signature(games):
            return tuple(sorted(
                (g.origin, g.home_price, g.away_price, g.home_won,
                 features_key(g)) for g in games))

        real = {signature(games) for _, games in self.world.days()}
        for day, games in self.p4.days():
            with self.subTest(day=day):
                self.assertIn(signature(games), real)

    def test_days_are_drawn_with_replacement(self):
        drawn = self.p4.params["distinct_days_drawn"]
        self.assertLess(drawn, self.world.n_days)
        self.assertGreater(drawn, self.world.n_days // 2)

    def test_copies_get_unique_ids_and_keep_their_provenance(self):
        ids = [g.game_id for g in self.p4.games]
        self.assertEqual(len(ids), len(set(ids)))
        real_ids = {g.game_id for g in self.world.games}
        for game in self.p4.games:
            self.assertIn(game.source_game_id, real_ids)

    def test_blocks_are_contiguous_runs_of_days(self):
        """Streaks survive: a stationary bootstrap must copy runs, not points."""
        source_rank = {games[0].date: day for day, games in self.world.days()}
        drawn = [source_rank[games[0].date] for _, games in self.p4.days()]
        runs = sum(1 for a, b in zip(drawn, drawn[1:]) if b == a + 1)
        self.assertGreater(runs, len(drawn) // 3)

    def test_p4_carries_a_planted_edge(self):
        """P4 is NOT an edge-destroying null, and that must never be forgotten.

        A P4 world is a resample of the real world with features, prices and
        outcomes still attached to each other, so any real feature -> outcome
        relationship is copied along with them. Its maxima therefore answer
        "how far does the search maximum move under resampling", and using P4
        in the kill criterion makes that criterion strictly harder in a way
        that can mask a genuine edge. Asserted, so the property is visible in
        the suite rather than discovered later in a verdict.
        """
        planted = synthetic_world(52, edge=PLANTED_EDGE, n_days=200, per_day=6)
        real_totals, _ = roi_search(planted)
        _, real_max = ceiling.search_maximum(real_totals)

        surviving = []
        for i in range(4):
            world = placebo.p4_block_bootstrap(planted, 900 + i)
            totals, _ = roi_search(world)
            surviving.append(ceiling.search_maximum(totals)[1])
        self.assertGreater(statistics.mean(surviving), 0.6 * real_max)

        # P5, the sharpest null, destroys the same edge completely.
        destroyed = []
        for i in range(4):
            world = placebo.p5_market_truth(planted, 900 + i)
            totals, _ = roi_search(world)
            destroyed.append(ceiling.search_maximum(totals)[1])
        self.assertLess(statistics.mean(destroyed), 0.35 * real_max)


# --------------------------------------------------------------------------
# P5
# --------------------------------------------------------------------------

class TestP5MarketTruth(unittest.TestCase):
    """P5 asserts one thing -- the market is right -- and must change nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.world = synthetic_world(61, n_days=200, per_day=6)
        cls.p5 = placebo.p5_market_truth(cls.world, 5)
        cls.by_id = {g.game_id: g for g in cls.world.games}

    def test_everything_except_the_outcome_is_bit_identical(self):
        self.assertEqual([g.game_id for g in self.p5.games],
                         [g.game_id for g in self.world.games])
        for game in self.p5.games:
            source = self.by_id[game.game_id]
            self.assertEqual(game.home_price, source.home_price)
            self.assertEqual(game.away_price, source.away_price)
            self.assertEqual(game.home_fair, source.home_fair)
            self.assertEqual(game.features, source.features)
            self.assertEqual(game.home_team, source.home_team)
            self.assertEqual(game.away_team, source.away_team)
            self.assertEqual(game.date, source.date)
            self.assertEqual(game.day_index, source.day_index)

    def test_outcome_base_rate_matches_the_market_within_sampling_error(self):
        rate = placebo.home_win_rate(self.p5)
        expected = placebo.mean_home_fair(self.world)
        se = math.sqrt(0.25 / self.world.n_games)
        self.assertLess(abs(rate - expected), 4 * se)

    def test_the_market_stays_calibrated(self):
        """The property that makes P5 the sharpest null: nothing about the
        market changed, so a P5 world is exactly 'the market is right'."""
        self.assertGreater(placebo.price_outcome_alignment(self.p5), 0.01)
        self.assertLess(
            abs(placebo.price_outcome_alignment(self.p5)
                - placebo.price_outcome_alignment(self.world)), 0.02)

    def test_expected_roi_of_any_selection_is_minus_the_vig(self):
        """Design section 14.6, the outcome half: no selection beats the vig.

        Betting every home side is as arbitrary a selection as any other; under
        P5 its return has to sit at the theoretical mean, which is negative by
        exactly the hold. A P5 world where this came out positive would be a
        world with free money in it, and no ceiling built on it would mean
        anything.
        """
        theoretical = statistics.mean(
            g.home_fair * odds_math.american_to_decimal(g.home_price) - 1.0
            for g in self.world.games)
        realised = statistics.mean(
            (odds_math.american_to_decimal(g.home_price) - 1.0) if g.home_won else -1.0
            for g in self.p5.games)
        self.assertLess(theoretical, -0.02)
        self.assertLess(abs(realised - theoretical),
                        4 * 1.0 / math.sqrt(self.world.n_games))

    def test_ungraded_games_are_not_quietly_given_outcomes(self):
        games = list(self.world.games[:20])
        games[0] = placebo.make_game(
            game_id="ungraded", date=games[0].date, season=games[0].season,
            home_team="AAA", away_team="BBB", home_price=-110, away_price=-110,
            home_won=None, features={"home_f0": 0.5})
        world = placebo.real_world(games)
        out = placebo.p5_market_truth(world, 1)
        self.assertIsNone(
            next(g for g in out.games if g.game_id == "ungraded").home_won)
        self.assertEqual(out.params["n_outcomes_drawn"], 19)

    def test_p5_erases_a_planted_edge_entirely(self):
        """Two worlds identical but for a planted edge must give the SAME P5 world.

        P5 redraws every outcome from the price, and the price does not know
        about the planted edge, so the placebo worlds are literally identical.
        That is what "apparent edge found here is definitionally a search
        artifact" means in code.
        """
        clean = synthetic_world(62, edge=0.0, n_days=40, per_day=4)
        planted = synthetic_world(62, edge=PLANTED_EDGE, n_days=40, per_day=4)
        a = placebo.p5_market_truth(clean, 7)
        b = placebo.p5_market_truth(planted, 7)
        self.assertEqual([g.home_won for g in a.games],
                         [g.home_won for g in b.games])


# --------------------------------------------------------------------------
# faithfulness: is any generator EASIER than reality?
# --------------------------------------------------------------------------

class TestGeneratorFaithfulness(unittest.TestCase):
    """The measurement no structural test can replace.

    A generator understates the ceiling when its worlds give the search LESS
    room to manufacture apparent edge than a genuinely null real world does.
    So: build 8 real worlds that contain no edge at all, record the search
    maximum in each, and compare with the search maxima P5 produces from one of
    them. P5 is the generator this matters most for, because it is the one the
    design weights most and the only one that leaves the market intact.
    """

    @classmethod
    def setUpClass(cls):
        cls.real_maxima = []
        for i in range(8):
            totals, _ = roi_search(
                synthetic_world(7000 + i, n_days=200, per_day=6))
            cls.real_maxima.append(ceiling.search_maximum(totals)[1])

        base = synthetic_world(7000, n_days=200, per_day=6)
        cls.p5_maxima = []
        for i in range(8):
            totals, _ = roi_search(placebo.p5_market_truth(base, 8000 + i))
            cls.p5_maxima.append(ceiling.search_maximum(totals)[1])

    def test_p5_is_not_easier_than_a_genuinely_null_real_world(self):
        real = statistics.mean(self.real_maxima)
        p5 = statistics.mean(self.p5_maxima)
        self.assertGreater(real, 0.0)
        # The dangerous direction is p5 << real: that would set the ceiling
        # below what our search manufactures from real structure.
        self.assertGreater(p5, 0.5 * real)
        self.assertLess(p5, 2.0 * real)

    def test_the_search_manufactures_apparent_edge_from_nothing(self):
        """The lab's whole premise, in one assertion.

        These worlds contain no edge whatsoever, and the search still crowns a
        champion with a positive return in most of them -- a flat-stake return
        of a couple of percent, against a market that charges 4.5%. That number
        is the noise ceiling, and it is why a positive backtest is not a
        finding.
        """
        self.assertGreaterEqual(sum(1 for v in self.real_maxima if v > 0), 6)
        self.assertGreater(statistics.mean(self.real_maxima), 0.005)

    def test_p1_runs_hot_when_a_feature_tracks_the_price(self):
        """The P1 artifact, measured rather than asserted in prose.

        With a feature that IS the line, P1's detachment of outcome from price
        hands the search a rule that fades favourites into outcomes that no
        longer respect the price. Its maxima explode past the real world's,
        which makes P1 conservative as a ceiling and useless as a null for any
        price-sensitive rule.
        """
        world = synthetic_world(7100, n_days=200, per_day=6, price_feature=True)
        real_max = ceiling.search_maximum(roi_search(world)[0])[1]
        p1 = [ceiling.search_maximum(
            roi_search(placebo.p1_outcome_permutation(world, 8100 + i))[0])[1]
            for i in range(4)]
        p5 = [ceiling.search_maximum(
            roi_search(placebo.p5_market_truth(world, 8100 + i))[0])[1]
            for i in range(4)]
        self.assertGreater(statistics.mean(p1), 5 * real_max)
        self.assertGreater(statistics.mean(p1), 1.5 * statistics.mean(p5))


# --------------------------------------------------------------------------
# CSCV mechanics
# --------------------------------------------------------------------------

class TestCSCVMechanics(unittest.TestCase):

    def test_ten_blocks_give_two_hundred_and_fifty_two_splits(self):
        table = {f"s{i}": [float(i + b) for b in range(10)] for i in range(5)}
        result = cscv.cscv(table)
        self.assertEqual(result.n_splits, 252)
        self.assertEqual(result.n_blocks, 10)
        self.assertEqual(result.n_strategies, 5)
        self.assertEqual(len({sp.in_sample_blocks for sp in result.splits}), 252)
        for split in result.splits:
            self.assertEqual(len(split.in_sample_blocks), 5)

    def test_splits_are_symmetric(self):
        """Every split's complement is also a split -- the 'symmetric' in CSCV."""
        table = {f"s{i}": [float(i + b) for b in range(10)] for i in range(4)}
        result = cscv.cscv(table)
        seen = {sp.in_sample_blocks for sp in result.splits}
        for blocks in seen:
            complement = tuple(sorted(set(range(10)) - set(blocks)))
            self.assertIn(complement, seen)

    def test_ragged_or_odd_tables_are_refused(self):
        with self.assertRaises(cscv.CSCVError):
            cscv.cscv({"a": [1.0] * 10, "b": [1.0] * 9})
        with self.assertRaises(cscv.CSCVError):
            cscv.cscv({"a": [1.0] * 9, "b": [1.0] * 9})
        with self.assertRaises(cscv.CSCVError):
            cscv.cscv({"a": [1.0] * 10})

    def test_non_finite_fitness_is_refused_not_coerced(self):
        """A missing block is not a zero, and pretending otherwise ranks a
        strategy on evidence it never faced."""
        with self.assertRaises(cscv.CSCVError):
            cscv.cscv({"a": [float("nan")] + [1.0] * 9, "b": [1.0] * 10})
        with self.assertRaises(cscv.CSCVError):
            cscv.cscv({"a": [float("inf")] + [1.0] * 9, "b": [1.0] * 10})

    def test_result_is_independent_of_dict_order(self):
        rng = random.Random(3)
        table = {f"s{i:02d}": [rng.gauss(0, 1) for _ in range(10)] for i in range(12)}
        reordered = dict(reversed(list(table.items())))
        self.assertEqual(cscv.cscv(table).pbo, cscv.cscv(reordered).pbo)

    def test_chronological_blocks_are_contiguous_and_cover_everything(self):
        bounds = cscv.chronological_blocks(203, 10)
        self.assertEqual(len(bounds), 10)
        self.assertEqual(bounds[0][0], 0)
        self.assertEqual(bounds[-1][1], 203)
        for (_, end), (start, _) in zip(bounds, bounds[1:]):
            self.assertEqual(end, start)
        sizes = [hi - lo for lo, hi in bounds]
        self.assertLessEqual(max(sizes) - min(sizes), 1)
        with self.assertRaises(cscv.CSCVError):
            cscv.chronological_blocks(5, 10)


# --------------------------------------------------------------------------
# validator validation -- the acceptance criteria
# --------------------------------------------------------------------------

def noise_table(seed: int, n_strategies: int = 60, n_blocks: int = 10,
                sigma: float = 0.01) -> dict[str, list[float]]:
    rng = random.Random(seed)
    return {f"s{i:03d}": [rng.gauss(0.0, sigma) for _ in range(n_blocks)]
            for i in range(n_strategies)}


def planted_table(seed: int, mu: float = 0.02, **kwargs) -> dict[str, list[float]]:
    table = noise_table(seed, **kwargs)
    rng = random.Random(seed + 99991)
    n_blocks = len(next(iter(table.values())))
    table["PLANTED"] = [mu + rng.gauss(0.0, 0.01) for _ in range(n_blocks)]
    return table


class TestValidatorValidation(unittest.TestCase):
    """Design section 8: until these pass, no PBO number is reported anywhere."""

    def test_planted_edge_gives_low_pbo(self):
        for seed in range(6):
            with self.subTest(seed=seed):
                result = cscv.cscv(planted_table(seed))
                self.assertLess(result.pbo, 0.10)
                self.assertEqual(result.most_selected, "PLANTED")
                self.assertGreater(result.selection_counts["PLANTED"],
                                   0.7 * result.n_splits)
                self.assertLess(result.prob_oos_loss, 0.10)

    def test_pure_noise_gives_pbo_about_one_half(self):
        """The honest expectation on a barren space.

        Averaged over 20 pinned seeds, because a single PBO is one draw of a
        statistic whose 252 splits share one table: individual seeds range from
        roughly 0.1 to 0.9 on pure noise, and quoting one of them would be
        quoting noise about noise. The mean is what is centred on 0.5.
        """
        pbos = [cscv.cscv(noise_table(seed)).pbo for seed in range(20)]
        mean = statistics.mean(pbos)
        self.assertGreater(mean, 0.40)
        self.assertLess(mean, 0.60)
        self.assertTrue(any(p < 0.5 for p in pbos))
        self.assertTrue(any(p > 0.5 for p in pbos))

    def test_pure_noise_selection_does_not_persist(self):
        """No strategy should be selected in most splits when nothing is real."""
        result = cscv.cscv(noise_table(5))
        best = max(result.selection_counts.values())
        self.assertLess(best, 0.5 * result.n_splits)

    def test_identical_strategies_produce_no_ranking_signal(self):
        """The degenerate case, which a plumbing test would pass and a reader
        would misread as 'no overfitting'."""
        table = {f"s{i:02d}": [0.01] * 10 for i in range(20)}
        result = cscv.cscv(table)
        self.assertTrue(result.degenerate)
        self.assertEqual(result.pbo, 0.5)
        self.assertEqual(result.n_below_median, 0)
        self.assertEqual(result.n_at_median, result.n_splits)
        for split in result.splits:
            self.assertEqual(split.logit, 0.0)
            self.assertEqual(split.relative_rank, 0.5)
            self.assertTrue(split.is_selection_tied)
        # And no slope may be conjured out of float non-associativity.
        self.assertIsNone(result.performance_degradation)

    def test_identical_strategies_at_zero_fitness_behave_the_same(self):
        result = cscv.cscv({f"s{i}": [0.0] * 10 for i in range(8)})
        self.assertEqual(result.pbo, 0.5)
        self.assertIsNone(result.performance_degradation)

    def test_one_dominant_strategy_gives_pbo_zero(self):
        table = {f"s{i:02d}": [0.001 * i] * 10 for i in range(10)}
        result = cscv.cscv(table)
        self.assertEqual(result.pbo, 0.0)
        self.assertEqual(result.most_selected, "s09")

    def test_a_pure_overfit_gives_pbo_one(self):
        """Two mirror-image strategies: whichever wins in-sample must lose
        out-of-sample, in every split. That is the pure overfit, and PBO has to
        say so without hedging."""
        table = {
            "first_half": [1.0] * 5 + [-1.0] * 5,
            "second_half": [-1.0] * 5 + [1.0] * 5,
            "steady_a": [0.0] * 10,
            "steady_b": [0.001] * 10,
        }
        result = cscv.cscv(table)
        self.assertEqual(result.pbo, 1.0)
        self.assertLess(result.performance_degradation, 0.0)


# --------------------------------------------------------------------------
# SPA
# --------------------------------------------------------------------------

class TestSPA(unittest.TestCase):

    @staticmethod
    def noise_series(seed, n_strategies=30, n_periods=200, sigma=0.05):
        rng = random.Random(seed)
        return {f"s{i:02d}": [rng.gauss(0.0, sigma) for _ in range(n_periods)]
                for i in range(n_strategies)}

    def test_planted_edge_is_detected(self):
        series = self.noise_series(3)
        series["PLANTED"] = [v + 0.02 for v in series["s00"]]
        result = spa.spa_test(series, seed=3, n_bootstrap=200, block_length=5)
        self.assertLess(result.p_value, 0.05)
        self.assertEqual(result.best_strategy, "PLANTED")

    def test_pure_noise_is_not_detected(self):
        """Over 8 seeds a 5%-level test must not be rejecting everywhere."""
        rejections = 0
        for seed in range(8):
            result = spa.spa_test(self.noise_series(seed), seed=seed,
                                  n_bootstrap=200, block_length=5)
            if result.p_value < 0.05:
                rejections += 1
        self.assertLessEqual(rejections, 1)

    def test_p_value_bounds_bracket_the_consistent_variant(self):
        series = self.noise_series(4)
        result = spa.spa_test(series, seed=4, n_bootstrap=200, block_length=5)
        self.assertLessEqual(result.p_lower, result.p_value + 1e-12)
        self.assertLessEqual(result.p_value, result.p_upper + 1e-12)

    def test_p_value_never_reports_zero(self):
        """A finite bootstrap has not earned a p-value of zero."""
        series = self.noise_series(6, n_strategies=5)
        series["HUGE"] = [1.0 + 0.01 * i for i in range(200)]
        result = spa.spa_test(series, seed=6, n_bootstrap=200, block_length=5)
        self.assertGreater(result.p_value, 0.0)
        self.assertAlmostEqual(result.p_value, 1 / 201, places=6)

    def test_is_deterministic(self):
        series = self.noise_series(5)
        a = spa.spa_test(series, seed=5, n_bootstrap=200, block_length=5)
        b = spa.spa_test(series, seed=5, n_bootstrap=200, block_length=5)
        self.assertEqual(a.p_value, b.p_value)
        self.assertEqual(a.statistic, b.statistic)
        self.assertEqual(a.omegas, b.omegas)

    def test_result_is_independent_of_dict_order(self):
        series = self.noise_series(8, n_strategies=10)
        reordered = dict(reversed(list(series.items())))
        a = spa.spa_test(series, seed=8, n_bootstrap=200, block_length=5)
        b = spa.spa_test(reordered, seed=8, n_bootstrap=200, block_length=5)
        self.assertEqual(a.p_value, b.p_value)
        self.assertEqual(a.statistic, b.statistic)

    def test_more_useless_strategies_cannot_help(self):
        """The multiplicity property SPA exists for: padding the universe with
        junk must not make the best strategy look better."""
        base = self.noise_series(9, n_strategies=5)
        base["CANDIDATE"] = [v + 0.012 for v in base["s00"]]
        small = spa.spa_test(base, seed=9, n_bootstrap=300, block_length=5)

        padded = dict(base)
        padded.update({f"junk{i:03d}": row for i, row in
                       enumerate(self.noise_series(10, n_strategies=60).values())})
        large = spa.spa_test(padded, seed=9, n_bootstrap=300, block_length=5)
        self.assertGreaterEqual(large.p_value, small.p_value)

    def test_ragged_short_or_non_finite_input_is_refused(self):
        with self.assertRaises(spa.SPAError):
            spa.spa_test({"a": [0.1] * 20, "b": [0.1] * 19}, seed=1)
        with self.assertRaises(spa.SPAError):
            spa.spa_test({"a": [0.1] * 4}, seed=1)
        with self.assertRaises(spa.SPAError):
            spa.spa_test({"a": [float("nan")] * 20}, seed=1)
        with self.assertRaises(spa.SPAError):
            spa.spa_test({"a": [0.1] * 20}, seed=1, n_bootstrap=10)

    def test_a_riskless_differential_is_a_bug_report_not_an_edge(self):
        series = {"a": [0.05] * 40, "b": [0.0] * 40}
        with self.assertRaises(spa.SPAError):
            spa.spa_test(series, seed=1, n_bootstrap=100)

    def test_a_strategy_that_never_bets_is_inactive_not_an_error(self):
        series = self.noise_series(11, n_strategies=4)
        series["NO_PLAY"] = [0.0] * 200
        result = spa.spa_test(series, seed=11, n_bootstrap=200, block_length=5)
        self.assertIn("NO_PLAY", result.inactive)

    def test_differentials_from_returns_subtracts_the_benchmark(self):
        out = spa.differentials_from_returns({"a": [0.1, 0.2]}, benchmark=0.05)
        self.assertAlmostEqual(out["a"][0], 0.05)
        self.assertAlmostEqual(out["a"][1], 0.15)
        with self.assertRaises(spa.SPAError):
            spa.differentials_from_returns({"a": [0.1, 0.2]}, benchmark=[0.1])

    def test_cross_check_names_a_disagreement_as_a_bug(self):
        series = self.noise_series(12)
        result = spa.spa_test(series, seed=12, n_bootstrap=200, block_length=5)
        status, message = spa.cross_check(result, clears_ceiling=False)
        self.assertEqual(status, "AGREE_NULL")
        status, message = spa.cross_check(result, clears_ceiling=True)
        self.assertEqual(status, "DISAGREE")
        self.assertIn("bug", message.lower())

    def test_bootstrap_blocks_and_indices_are_the_same_draw(self):
        rng_a = random.Random(2)
        rng_b = random.Random(2)
        blocks = placebo.stationary_bootstrap_blocks(50, 7, rng_a)
        indices = placebo.stationary_bootstrap_indices(50, 7, rng_b)
        expanded = [(start + i) % 50 for start, run in blocks for i in range(run)]
        self.assertEqual(expanded, indices)
        self.assertEqual(len(indices), 50)


# --------------------------------------------------------------------------
# ceiling and the kill criterion
# --------------------------------------------------------------------------

class TestPercentile(unittest.TestCase):

    def test_nearest_rank_never_invents_a_threshold(self):
        values = [float(i) for i in range(1, 11)]
        self.assertEqual(ceiling.percentile(values, 95), 10.0)
        self.assertEqual(ceiling.percentile(values, 50), 5.0)
        self.assertEqual(ceiling.percentile(values, 0), 1.0)
        self.assertEqual(ceiling.percentile(values, 100), 10.0)

    def test_ten_worlds_make_the_95th_percentile_the_maximum(self):
        """Stated in the module docstring; asserted so nobody quotes a
        95th percentile from 10 worlds as if it were resolved."""
        values = [0.1 * i for i in range(10)]
        self.assertEqual(ceiling.percentile(values, 95), max(values))

    def test_linear_interpolates(self):
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(ceiling.percentile(values, 50, method="linear"), 2.5)

    def test_bad_input_raises(self):
        with self.assertRaises(ceiling.CeilingError):
            ceiling.percentile([], 50)
        with self.assertRaises(ceiling.CeilingError):
            ceiling.percentile([1.0], 101)
        with self.assertRaises(ceiling.CeilingError):
            ceiling.percentile([1.0], 50, method="guess")


class TestKillCriterion(unittest.TestCase):

    @staticmethod
    def _ceilings(pattern, n_worlds=10):
        out = []
        for i, clears in enumerate(pattern):
            maxima = [0.10] * n_worlds
            real = 0.20 if clears else 0.05
            out.append(ceiling.generator_ceiling(f"P{i + 1}", real, maxima))
        return out

    def test_majority_failing_is_the_kill(self):
        verdict, reason = ceiling.kill_criterion(
            self._ceilings([False, False, False, True, True]))
        self.assertEqual(verdict, ceiling.BELOW_PLACEBO_CEILING)
        self.assertIn("does not get built", reason)

    def test_majority_clearing_is_permission_not_evidence(self):
        verdict, reason = ceiling.kill_criterion(
            self._ceilings([True, True, True, False, False]))
        self.assertEqual(verdict, ceiling.CLEARS_PLACEBO_CEILING)
        self.assertIn("not evidence", reason)

    def test_a_split_decision_is_not_rounded_toward_proceeding(self):
        verdict, _ = ceiling.kill_criterion(
            self._ceilings([True, True, False, False]))
        self.assertEqual(verdict, ceiling.INCONCLUSIVE)

    def test_too_few_generators_is_not_a_verdict(self):
        verdict, _ = ceiling.kill_criterion(self._ceilings([True, True]))
        self.assertEqual(verdict, ceiling.INSUFFICIENT_EVIDENCE)

    def test_underpowered_generators_do_not_vote(self):
        """A 95th percentile over three worlds is a number, not a threshold."""
        thin = [ceiling.generator_ceiling("P1", 0.2, [0.1] * 3),
                ceiling.generator_ceiling("P2", 0.2, [0.1] * 3),
                ceiling.generator_ceiling("P3", 0.2, [0.1] * 3)]
        verdict, _ = ceiling.kill_criterion(thin)
        self.assertEqual(verdict, ceiling.INSUFFICIENT_EVIDENCE)
        verdict, _ = ceiling.kill_criterion(thin, count_underpowered=True)
        self.assertEqual(verdict, ceiling.CLEARS_PLACEBO_CEILING)

    def test_equal_to_the_threshold_does_not_clear(self):
        """'No better than the 95th percentile' means a tie is a failure."""
        c = ceiling.generator_ceiling("P5", 0.10, [0.10] * 10)
        self.assertFalse(c.clears)


class TestCeilingReport(unittest.TestCase):

    def test_percentile_rank_and_exceedance_p(self):
        c = ceiling.generator_ceiling("P5", 0.5, [0.1, 0.2, 0.3, 0.4, 0.6])
        self.assertEqual(c.n_worlds, 5)
        self.assertEqual(c.percentile_rank, 80.0)
        self.assertAlmostEqual(c.exceedance_p, 2 / 6)
        self.assertEqual(c.placebo_median, 0.3)

    def test_report_pools_and_warns(self):
        report = ceiling.ceiling_report(
            0.20,
            {"P1": [0.05] * 10, "P2": [0.05] * 10, "P5": [0.05] * 10},
            real_champion="alpha",
            n_strategies_real=100,
            n_strategies_placebo={"P1": 100, "P2": 50, "P5": 100})
        self.assertEqual(report.verdict, ceiling.CLEARS_PLACEBO_CEILING)
        self.assertEqual(report.pooled.n_worlds, 30)
        self.assertEqual(report.generators_cleared, ("P1", "P2", "P5"))
        joined = " ".join(report.warnings)
        self.assertIn("P2", joined)
        self.assertIn("five design generators", joined)

    def test_report_marks_underpowered_generators(self):
        report = ceiling.ceiling_report(
            0.20, {"P1": [0.05] * 4, "P2": [0.05] * 10, "P5": [0.05] * 10})
        self.assertEqual(report.generators_underpowered, ("P1",))
        self.assertEqual(report.verdict, ceiling.INSUFFICIENT_EVIDENCE)

    def test_non_finite_input_is_refused(self):
        with self.assertRaises(ceiling.CeilingError):
            ceiling.ceiling_report(float("nan"), {"P5": [0.1] * 10})
        with self.assertRaises(ceiling.CeilingError):
            ceiling.ceiling_report(0.1, {"P5": [float("inf")] * 10})
        with self.assertRaises(ceiling.CeilingError):
            ceiling.ceiling_report(0.1, {})

    def test_search_maximum_breaks_ties_deterministically(self):
        best, value = ceiling.search_maximum({"b": 1.0, "a": 1.0, "c": 0.5})
        self.assertEqual(best, "a")
        self.assertEqual(value, 1.0)
        with self.assertRaises(ceiling.CeilingError):
            ceiling.search_maximum({})

    def test_format_report_states_it_is_not_evidence(self):
        report = ceiling.ceiling_report(0.02, {"P5": [0.05] * 10})
        text = ceiling.format_report(report)
        self.assertIn("Nothing here is evidence", text)
        self.assertIn("P5", text)
        self.assertIn("POOLED", text)


# --------------------------------------------------------------------------
# end to end: the placebo ceiling and PBO on the same synthetic data
# --------------------------------------------------------------------------

class TestEndToEndCeiling(unittest.TestCase):
    """Section 14.7 run through the whole machine, not just the statistics.

    One synthetic world with a planted edge and one without, the same
    enumeration run on the real world and on ten worlds from each of the five
    generators, and the two verdicts the design demands: the planted edge
    clears the ceiling with a low PBO, and pure noise does not clear it with a
    PBO near a coin flip.
    """

    REPLICATES = 10
    BASE_SEED = 31337

    @classmethod
    def _run(cls, edge):
        world = synthetic_world(20000, edge=edge, n_days=250, per_day=8)
        totals, per_block = roi_search(world)
        champion, real_max = ceiling.search_maximum(totals)
        maxima = {}
        for gid in placebo.GENERATOR_IDS:
            values = []
            for i in range(cls.REPLICATES):
                seed = placebo._derive_seed(cls.BASE_SEED, gid, i)
                placebo_world = placebo.generate(gid, world, seed)
                values.append(ceiling.search_maximum(
                    roi_search(placebo_world)[0])[1])
            maxima[gid] = values
        report = ceiling.ceiling_report(real_max, maxima, real_champion=champion)
        return report, cscv.cscv(per_block)

    @classmethod
    def setUpClass(cls):
        cls.planted_report, cls.planted_cscv = cls._run(PLANTED_EDGE)
        cls.noise_report, cls.noise_cscv = cls._run(0.0)

    def test_planted_edge_clears_the_ceiling(self):
        self.assertEqual(self.planted_report.verdict,
                         ceiling.CLEARS_PLACEBO_CEILING)
        self.assertEqual(self.planted_report.real_champion,
                         f"{PLANTED_FEATURE}>0.55|home")

    def test_planted_edge_clears_the_sharpest_null_by_a_wide_margin(self):
        p5 = next(c for c in self.planted_report.per_generator
                  if c.generator == "P5")
        self.assertTrue(p5.clears)
        self.assertGreater(p5.margin, 0.05)
        self.assertEqual(p5.percentile_rank, 100.0)

    def test_planted_edge_gives_low_pbo(self):
        self.assertLess(self.planted_cscv.pbo, 0.10)
        self.assertEqual(self.planted_cscv.most_selected,
                         self.planted_report.real_champion)

    def test_pure_noise_does_not_clear_the_ceiling(self):
        self.assertEqual(self.noise_report.verdict,
                         ceiling.BELOW_PLACEBO_CEILING)
        self.assertEqual(self.noise_report.generators_cleared, ())

    def test_pure_noise_gives_pbo_near_a_coin_flip(self):
        """Looser than the tabletop test on purpose: this is one draw of a
        statistic, not an average over seeds."""
        self.assertGreater(self.noise_cscv.pbo, 0.25)
        self.assertLess(self.noise_cscv.pbo, 0.75)

    def test_the_noise_world_still_produced_a_positive_champion(self):
        """The point of the whole lab, in one number: a search over a world
        with no edge in it still crowns a strategy with a positive return."""
        self.assertGreater(self.noise_report.real_max, 0.0)

    def test_spa_and_the_ceiling_agree_on_both_worlds(self):
        """Design section 8's cross-check. Disagreement means a bug in one of
        them, which is exactly why both are run."""
        for label, report, edge in (("planted", self.planted_report, PLANTED_EDGE),
                                    ("noise", self.noise_report, 0.0)):
            with self.subTest(world=label):
                world = synthetic_world(20000, edge=edge, n_days=250, per_day=8)
                series = self._daily_returns(world)
                result = spa.spa_test(series, seed=7, n_bootstrap=200,
                                      block_length=7)
                status, message = spa.cross_check(
                    result, report.verdict == ceiling.CLEARS_PLACEBO_CEILING)
                self.assertNotEqual(status, "DISAGREE", message)

    @staticmethod
    def _daily_returns(world):
        """Per-game-day mean return for each strategy: the clustering unit."""
        days = world.days()
        series = {sid: [0.0] * len(days) for sid in strategy_ids()}
        for position, (_, games) in enumerate(days):
            for feature in FEATURES:
                for threshold in THRESHOLDS:
                    for side in SIDES:
                        sid = f"{feature}>{threshold}|{side}"
                        total = 0.0
                        for game in games:
                            value = game.features.get(feature)
                            if value is None or value <= threshold:
                                continue
                            won = (game.home_won if side == "home"
                                   else not game.home_won)
                            price = (game.home_price if side == "home"
                                     else game.away_price)
                            total += (odds_math.american_to_decimal(price) - 1.0
                                      if won else -1.0)
                        series[sid][position] = total / len(games)
        return series


if __name__ == "__main__":
    unittest.main()
