"""The adapter that mates the Phase 1 replay engine to the Phase 2B sweep.

NOTHING HERE IS EVIDENCE. These run on a hand-built fixture universe except
the real-store smoke, which is opt-in (EVOLAB_REAL_STORE=1) because it reads
the whole 2023-24 store, and which BUILDS THE FEED ONLY -- it runs no search.
A search run is a separately reviewed event and no test starts one.

The load-bearing test is `test_flipping_every_outcome_changes_no_decision`: it
is the feed's version of replay's own future-injection digest test. The replay
engine refuses to serve outcomes at all; this module is the one sanctioned
place they join, so the property that makes that safe -- the join happens
after every decision is resolved and hashed, and cannot reach back -- has to be
measured rather than asserted in a docstring.
"""

from __future__ import annotations

import datetime as dt
import inspect
import os
import unittest
from pathlib import Path

from src.evolab import feed as feed_mod
from src.evolab import genome as genome_mod
from src.evolab import placebo, replay, sweep
from src.evolab.registry import SignalRegistry

UTC = dt.timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]

# Eight books, so the six-book consensus floor clears with room and a thin
# board can be built by naming fewer of them.
BOOKS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
         "hotel")


def small_registry() -> SignalRegistry:
    """Two features, three rungs each -- the shape the other evolab tests use."""
    reg = SignalRegistry()
    reg.register(
        feature="top_minus_bottom",
        mechanism="a top-heavy order concentrates its best bats where the "
                  "extra plate appearances go",
        direction=+1, ladder=(0.01, 0.02, 0.03), scope="FIRST_FIVE",
        provenance="hand-made for tests, not derived from data")
    reg.register(
        feature="starter_velocity_gap",
        mechanism="a starter whose fastball sits above league pace is holding "
                  "stuff the season line has not caught up to",
        direction=-1, ladder=(0.5, 1.0, 2.0), scope="FIRST_FIVE",
        provenance="hand-made for tests, not derived from data")
    return reg


SMALL = small_registry()

# Twelve game-days, two games a day: enough days that a blocked sweep has
# something to block, without making the fixture a data set.
N_DAYS = 12
GAMES_PER_DAY = 2


def _quotes(observed, commence, *, offset, books=BOOKS):
    """One instant's quotes, pricepath-shaped, one row per book."""
    gap = (commence - observed).total_seconds() / 60.0
    return [{"book": book,
             "snapshot_at": observed,
             "gap_minutes": gap,
             "away_price": -120 - index * 2 - offset,
             "home_price": 100 + index * 3 + offset}
            for index, book in enumerate(books)]


def fixture_stores(*, thin_decision=(), single_instant=()):
    """(paths_by_season, matrix_rows_by_season) for the fixture universe.

    Every game carries an early board (10 hours out) and a late board (75
    minutes out) at DIFFERENT prices, so the movement window is a real number
    rather than zero.

    `thin_decision` names game_pks whose EARLY board is quoted by three books
    -- below the consensus floor, so the decision cannot be resolved.
    `single_instant` names game_pks with one observation only, which is how
    replay's ladder collapses and leaves no movement window at all.
    """
    paths, rows = {2023: [], 2024: []}, {2023: [], 2024: []}
    for day in range(N_DAYS):
        date = dt.date(2023, 5, 1) + dt.timedelta(days=day)
        for slot in range(GAMES_PER_DAY):
            game_pk = f"9{day:02d}{slot}"
            commence = dt.datetime(date.year, date.month, date.day, 23, 5,
                                   tzinfo=UTC) + dt.timedelta(minutes=slot)
            early = commence - dt.timedelta(minutes=600)
            late = commence - dt.timedelta(minutes=75)
            quotes = _quotes(
                early, commence, offset=day + slot,
                books=BOOKS[:3] if game_pk in thin_decision else BOOKS)
            if game_pk not in single_instant:
                quotes += _quotes(late, commence, offset=day + slot + 7)
            paths[2023].append({
                "event_id": f"evt-{game_pk}",
                "commence_time": commence,
                "game_pk": game_pk,
                "date": date.isoformat(),
                "away_team": "CIN", "home_team": "NYM",
                # Present on purpose, exactly as the real price path carries
                # them. Nothing in the decision pass may read either.
                "home_won": slot == 0,
                "total_runs": 7 + day,
                "quotes": quotes,
            })
            rows[2023].append({
                "game_pk": game_pk,
                "date": date.isoformat(),
                "start_time_utc": commence.isoformat().replace("+00:00", "Z"),
                "cutoff": "2023-04-01",
                "away_team": "CIN", "home_team": "NYM",
                # Varied by day so a genome fires on some games and not
                # others: a fixture where every game selects would hide a
                # masking bug behind a full board.
                "away_top_minus_bottom": 0.01 + 0.004 * day,
                "home_top_minus_bottom": 0.01,
                "away_starter_velocity_gap": 1.0,
                "home_starter_velocity_gap": 1.0 + 0.3 * slot + 0.1 * day,
            })
    return paths, rows


def fixture_universe(**kwargs):
    """The fixture universe through the real loader, at a pinned commit."""
    paths, rows = fixture_stores(**kwargs)
    return replay.load_universe(
        (2023,), paths_by_season=paths, matrix_rows_by_season=rows,
        registry=SMALL, code_commit="0" * 40)


def fixture_outcomes(universe, *, flipped=False, drop=()):
    """{game_pk: home_won} for a universe, optionally inverted or thinned.

    Injected rather than written to a file so the flip test can invert every
    outcome in the world without touching the store.
    """
    out = {}
    for index, game in enumerate(universe.games):
        if game.game_pk in drop:
            continue
        won = index % 2 == 0
        out[game.game_pk] = (not won) if flipped else won
    return out


def a_genome(registry=SMALL):
    """One validated genome that fires on the fixture features."""
    return genome_mod.validate({
        "eligibility": {"markets": ["h2h"], "min_books": 6,
                        "require_lineup": False},
        "signals": [{"feature": "top_minus_bottom", "threshold_index": 0,
                     "weight": 1.0},
                    {"feature": "starter_velocity_gap", "threshold_index": 0,
                     "weight": 1.0}],
        "combination": {"rule": "weighted_sum"},
        "entry": {"min_score": 1.0, "min_confirmations": 1},
        "routing": {"market_preference": ["h2h"], "f5_condition": "never"},
        "execution": genome_mod.DEFAULT_EXECUTION,
    }, registry)


class FeedShapeTest(unittest.TestCase):
    """What the adapter produces, and against which board it produced it."""

    def setUp(self):
        self.universe = fixture_universe()
        self.outcomes = fixture_outcomes(self.universe)
        self.feed = feed_mod.build_feed(universe=self.universe, registry=SMALL,
                                        outcomes=self.outcomes)

    def test_feed_is_a_sweep_replayfeed_of_a_placebo_world(self):
        self.assertIsInstance(self.feed, sweep.ReplayFeed)
        self.assertIsInstance(self.feed.world, placebo.World)
        self.assertEqual(self.feed.world.generator, placebo.REAL)
        self.assertEqual(self.feed.world.n_games, N_DAYS * GAMES_PER_DAY)
        self.assertEqual(self.feed.world.n_days, N_DAYS)

    def test_every_game_carries_the_shape_sweep_documents(self):
        for game in self.feed.world.games:
            self.assertIsInstance(game.home_fair, float)
            self.assertTrue(0.0 < game.home_fair < 1.0)
            self.assertIsNotNone(game.home_fair_close)
            self.assertIn(game.home_won, (True, False))
            for spec in SMALL.specs():
                self.assertIn("away_" + spec.feature, game.features)
                self.assertIn("home_" + spec.feature, game.features)

    def test_the_decision_is_the_early_board_and_the_endpoint_is_the_late_one(self):
        """The decision instant is EARLY_BOARD; the endpoint is a later board.

        Pinned against replay's own ladder rather than against the fixture's
        arithmetic, so a change to `classify_points` cannot leave this passing
        while the feed silently decides somewhere else.
        """
        rows, _ = feed_mod.resolve_decisions(self.universe, registry=SMALL)
        by_pk = {r.game_pk: r for r in rows}
        for game in self.universe.games:
            points = dict(replay.classify_points(game))
            row = by_pk[game.game_pk]
            self.assertEqual(
                row.decision_T,
                points[replay.EARLY_BOARD].observed.isoformat())
            self.assertEqual(row.late_T,
                             points[replay.LATE_BOARD].observed.isoformat())
            self.assertGreater(row.decision_gap_minutes, row.late_gap_minutes)

    def test_consensus_fair_is_the_engines_own_resolution(self):
        """The adapter calls `replay.execution_quote`, it does not re-derive.

        Asserted by recomputing the CONSENSUS_EXECUTION quote at the row's own
        decision instant and demanding bit equality: an adapter with its own
        de-vig would be a second execution model wearing the engine's name.
        """
        rows, _ = feed_mod.resolve_decisions(self.universe, registry=SMALL)
        for row in rows:
            game = self.universe.get(row.game_pk)
            view = replay.world_view(game, row.decision_T,
                                     point_class=replay.EARLY_BOARD)
            quote = replay.execution_quote(view, replay.H2H, "home",
                                           replay.CONSENSUS_EXECUTION)
            self.assertEqual(row.home_fair, quote.consensus_probability)
            self.assertEqual(row.decision_books, quote.books)

    def test_manifest_carries_replays_manifest_through(self):
        manifest = self.feed.manifest.to_dict()
        self.assertEqual(manifest["replay_manifest"],
                         self.universe.manifest.to_dict())
        self.assertEqual(manifest["decision_point_class"], replay.EARLY_BOARD)
        self.assertEqual(manifest["movement_endpoint_class"],
                         replay.LATE_BOARD)
        self.assertIn("NOT a close", manifest["reconciliation"])
        self.assertIn("median_minutes",
                      manifest["movement_endpoint_gap_minutes"])
        self.assertIn("NOT evidence", manifest["evidence"])
        self.assertIn("never EV", manifest["evidence"])
        self.assertIn("is EV or edge",
                      manifest["consensus_price_definition"])

    def test_a_below_floor_min_books_is_refused_rather_than_claimed(self):
        with self.assertRaises(feed_mod.FeedError):
            feed_mod.resolve_decisions(self.universe, registry=SMALL,
                                       min_books=replay.MIN_BOOKS - 1)


class OutcomeIsolationTest(unittest.TestCase):
    """The one property that makes joining outcomes here safe."""

    def test_resolve_decisions_cannot_be_handed_an_outcome(self):
        """Structural, not behavioural: the signature has nowhere to put one.

        The same style of guarantee replay's allowlist gives -- an outcome
        cannot arrive by default because there is no parameter it could arrive
        through, and no results store is opened anywhere in the pass.
        """
        params = set(inspect.signature(feed_mod.resolve_decisions).parameters)
        self.assertEqual(params, {"universe", "registry", "min_books"})
        # The names the compiled pass can reach, not the prose around them: a
        # docstring may discuss outcomes, the bytecode may not touch one.
        names = set(feed_mod.resolve_decisions.__code__.co_names)
        for forbidden in ("home_won", "total_runs", "read_outcomes",
                          "join_outcomes", "DEFAULT_RESULTS_PATH"):
            self.assertNotIn(forbidden, names)

    def test_flipping_every_outcome_changes_no_decision(self):
        """Invert every result in the store; every decision is byte-identical.

        The feed's echo of replay's future-injection digest test. The digest is
        taken before the outcome store is read, so a leak would have to travel
        backwards in the program to show up -- and if one ever could, this
        fails loudly rather than producing a slightly better number.
        """
        universe = fixture_universe()
        straight = feed_mod.build_feed(
            universe=universe, registry=SMALL,
            outcomes=fixture_outcomes(universe))
        flipped = feed_mod.build_feed(
            universe=universe, registry=SMALL,
            outcomes=fixture_outcomes(universe, flipped=True))

        self.assertEqual(straight.manifest.decision_digest,
                         flipped.manifest.decision_digest)
        self.assertEqual(len(straight.world.games), len(flipped.world.games))
        for a, b in zip(straight.world.games, flipped.world.games):
            self.assertEqual(a.game_id, b.game_id)
            self.assertEqual(a.home_price, b.home_price)
            self.assertEqual(a.away_price, b.away_price)
            self.assertEqual(a.home_fair, b.home_fair)
            self.assertEqual(a.home_fair_close, b.home_fair_close)
            self.assertEqual(a.features, b.features)
            self.assertEqual(a.day_index, b.day_index)
            # The ONE thing that moved.
            self.assertEqual(a.home_won, not b.home_won)

    def test_ungraded_games_are_excluded_and_counted_never_defaulted(self):
        universe = fixture_universe()
        dropped = {universe.games[0].game_pk, universe.games[3].game_pk}
        built = feed_mod.build_feed(
            universe=universe, registry=SMALL,
            outcomes=fixture_outcomes(universe, drop=tuple(dropped)))
        manifest = built.manifest.to_dict()
        self.assertEqual(manifest["exclusions"][feed_mod.OUTCOME_ABSENT], 2)
        self.assertEqual(built.world.n_games,
                         N_DAYS * GAMES_PER_DAY - len(dropped))
        self.assertFalse(dropped & {g.game_id for g in built.world.games})
        for game in built.world.games:
            self.assertIsNotNone(game.home_won)


class ExclusionAccountingTest(unittest.TestCase):
    """Every game replay served is either fed or counted out by reason."""

    def test_collapsed_ladder_and_thin_consensus_are_counted_separately(self):
        universe = fixture_universe(single_instant=("9000",),
                                    thin_decision=("9011",))
        outcomes = fixture_outcomes(universe, drop=("9021",))
        built = feed_mod.build_feed(universe=universe, registry=SMALL,
                                    outcomes=outcomes)
        manifest = built.manifest.to_dict()
        exclusions = manifest["exclusions"]

        self.assertEqual(exclusions[feed_mod.NO_EARLY_BOARD], 1)
        self.assertEqual(exclusions[feed_mod.THIN_CONSENSUS_AT_DECISION], 1)
        self.assertEqual(exclusions[feed_mod.OUTCOME_ABSENT], 1)
        self.assertEqual(manifest["n_games_fed"], built.world.n_games)
        self.assertEqual(
            manifest["replay_universe_size"],
            manifest["n_games_fed"]
            + sum(exclusions[r] for r in feed_mod.EXCLUSION_REASONS))
        for pk in ("9000", "9011", "9021"):
            self.assertNotIn(pk, {g.game_id for g in built.world.games})
        self.assertIn("replay served", manifest["reconciliation"])

    def test_reconciliation_names_every_reason_it_counted(self):
        universe = fixture_universe()
        built = feed_mod.build_feed(universe=universe, registry=SMALL,
                                    outcomes=fixture_outcomes(universe))
        text = built.manifest.to_dict()["reconciliation"]
        for reason in feed_mod.EXCLUSION_REASONS:
            self.assertIn(reason, text)

    def test_an_empty_reduction_is_a_refusal_not_an_empty_world(self):
        universe = fixture_universe()
        with self.assertRaises(feed_mod.FeedError):
            feed_mod.build_feed(universe=universe, registry=SMALL,
                                outcomes={})


class DeterminismTest(unittest.TestCase):
    """Same stores, same feed -- bytes, not meaning."""

    def test_two_builds_of_one_store_are_identical(self):
        first = feed_mod.build_feed(
            universe=fixture_universe(), registry=SMALL,
            outcomes=fixture_outcomes(fixture_universe()))
        second = feed_mod.build_feed(
            universe=fixture_universe(), registry=SMALL,
            outcomes=fixture_outcomes(fixture_universe()))
        self.assertEqual(first.manifest.fingerprint(),
                         second.manifest.fingerprint())
        self.assertEqual(first.world.games, second.world.games)
        self.assertEqual(first.manifest.to_dict(), second.manifest.to_dict())

    def test_the_decision_digest_is_a_function_of_the_decisions_alone(self):
        universe = fixture_universe()
        rows, _ = feed_mod.resolve_decisions(universe, registry=SMALL)
        again, _ = feed_mod.resolve_decisions(universe, registry=SMALL)
        self.assertEqual(feed_mod.decisions_digest(rows),
                         feed_mod.decisions_digest(again))
        # A different store is a different digest: the hash has to be able to
        # tell two universes apart or it proves nothing about either.
        other, _ = feed_mod.resolve_decisions(
            fixture_universe(thin_decision=("9011",)), registry=SMALL)
        self.assertNotEqual(feed_mod.decisions_digest(rows),
                            feed_mod.decisions_digest(other))


class MatesWithSweepTest(unittest.TestCase):
    """The shapes actually mate: a fixture feed swept end to end."""

    def test_sweep_world_runs_over_a_real_feed(self):
        universe = fixture_universe()
        built = feed_mod.build_feed(universe=universe, registry=SMALL,
                                    outcomes=fixture_outcomes(universe))
        fitness = sweep.sweep_world(built.world, [a_genome()], SMALL,
                                    n_blocks=4, min_selections=1)
        self.assertEqual(fitness.n_games, built.world.n_games)
        self.assertGreaterEqual(fitness.n_strategies, 1)
        sid = a_genome().strategy_id
        self.assertIn(sid, fitness.totals_movement)
        self.assertEqual(len(fitness.movement_table[sid]), 4)
        self.assertEqual(len(fitness.roi_table[sid]), 4)
        self.assertGreater(fitness.n_selected[sid], 0)

    def test_movement_is_measured_between_two_boards_not_against_a_close(self):
        """`home_fair_close` here is the LATE BOARD's fair, and differs.

        A feed whose endpoint equalled the decision fair would score every
        strategy at exactly zero movement and look like a null result rather
        than a broken adapter, so the difference is asserted.
        """
        universe = fixture_universe()
        built = feed_mod.build_feed(universe=universe, registry=SMALL,
                                    outcomes=fixture_outcomes(universe))
        for game in built.world.games:
            self.assertNotEqual(game.home_fair, game.home_fair_close)
        gaps = built.manifest.to_dict()["movement_endpoint_gap_minutes"]
        self.assertGreater(gaps["min_minutes"], 0.0)


@unittest.skipUnless(os.environ.get("EVOLAB_REAL_STORE") == "1",
                     "opt-in: reads the whole 2023-24 store")
class RealStoreSmokeTest(unittest.TestCase):
    """Build the feed off the real stores and report its size. NO SEARCH.

    Building a feed is data plumbing. Running a search over it is a separately
    reviewed event, and no test in this repository starts one -- this asserts
    the reduction is arithmetically closed and prints the exclusion table, and
    then stops.
    """

    def test_real_store_feed_reconciles(self):
        built = feed_mod.build_feed()
        manifest = built.manifest.to_dict()
        exclusions = manifest["exclusions"]
        print("\nreal-store feed:", manifest["n_games_fed"], "games from",
              manifest["replay_universe_size"], "served")
        for reason in feed_mod.EXCLUSION_REASONS:
            print(f"  {reason}: {exclusions[reason]}")
        print("  kept without movement endpoint:",
              exclusions[feed_mod.NO_MOVEMENT_ENDPOINT])
        self.assertEqual(
            manifest["replay_universe_size"],
            manifest["n_games_fed"]
            + sum(exclusions[r] for r in feed_mod.EXCLUSION_REASONS))
        self.assertGreater(manifest["n_games_fed"], 0)


if __name__ == "__main__":
    unittest.main()
