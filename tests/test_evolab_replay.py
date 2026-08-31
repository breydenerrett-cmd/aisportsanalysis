"""Acceptance tests for the replay engine (docs/EVOLAB_DESIGN.md section 14).

The five the Phase 1 brief names are here by their design numbers -- 1
determinism, 2 structural leakage, 3 absent futures, 5 execution honesty --
plus the starter-identity refusal and the sealed-window refusal, which are
project rules rather than design numbers and are no less binding.

Everything runs on a hand-built fixture universe: six games, priced instants
chosen so every branch of the two-class ladder is exercised, and a price path
that CARRIES `home_won` and `total_runs` on purpose. The outcome fields are
there so the tests can prove the engine ignores them rather than proving it on
a fixture that never offered one.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from src.evolab import decide as decide_mod
from src.evolab import genome as genome_mod
from src.evolab import replay
from src.evolab.decide import BoardMeta, WorldView
from src.evolab.registry import SignalRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]

UTC = dt.timezone.utc

# Books that quote every fixture board. Nine so the six-book consensus floor
# is cleared with room, and two of them (`ties_a`, `ties_b`) always quote the
# same number so the tie-break has something to refuse.
BOOKS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
         "ties_a", "ties_b")


def small_registry() -> SignalRegistry:
    """Two features, three rungs each -- the same shape test_evolab_core uses.

    One class D feature and one class C feature, so the availability rules get
    exercised from both sides.
    """
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


def a_genome(registry=None):
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
    }, registry or SMALL)


# ---------------------------------------------------------------------------
# Fixture stores
# ---------------------------------------------------------------------------

def _quotes(observed, commence, *, offset=0):
    """One instant's quotes, one row per book, pricepath-shaped."""
    gap = (commence - observed).total_seconds() / 60.0
    rows = []
    for index, book in enumerate(BOOKS):
        # ties_a and ties_b share a price on purpose; everything else is
        # distinct so the "best price" has an unambiguous owner when it should.
        step = 0 if book.startswith("ties_") else index
        rows.append({"book": book,
                     "snapshot_at": observed,
                     "gap_minutes": gap,
                     "away_price": -120 - step * 2 - offset,
                     "home_price": 100 + step * 3 + offset})
    return rows


def fixture_stores(*, extra_paths=(), extra_matrix=(), inject_future=False):
    """(paths_by_season, matrix_rows_by_season) for the fixture universe.

    Six games across the two replay seasons:
      G1, G2, G3 -- three instants each (early, middle, late)
      G4        -- one instant only, so early and late collapse
      G5        -- two instants, both early, so they still collapse
      G6        -- a matrix row with no price path at all (excluded)

    `inject_future` adds a quote one second after each game's LATE board and a
    whole extra instant an hour later, which is acceptance test 2's injection.
    """
    paths = {2023: [], 2024: []}
    rows = {2023: [], 2024: []}
    plan = [
        ("801", 2023, "2023-05-01", dt.datetime(2023, 5, 2, 1, 10, tzinfo=UTC),
         (1440.0, 700.0, 90.0)),
        ("802", 2023, "2023-05-02", dt.datetime(2023, 5, 2, 23, 5, tzinfo=UTC),
         (1200.0, 600.0, 45.0)),
        ("803", 2024, "2024-06-11", dt.datetime(2024, 6, 11, 22, 40, tzinfo=UTC),
         (900.0, 420.0, 120.0)),
        ("804", 2024, "2024-06-12", dt.datetime(2024, 6, 12, 22, 40, tzinfo=UTC),
         (200.0,)),
        ("805", 2024, "2024-06-13", dt.datetime(2024, 6, 13, 22, 40, tzinfo=UTC),
         (900.0, 480.0)),
    ]
    for index, (game_pk, season, date, commence, gaps) in enumerate(plan):
        quotes = []
        latest = None
        for offset, gap in enumerate(gaps):
            observed = commence - dt.timedelta(minutes=gap)
            quotes.extend(_quotes(observed, commence, offset=offset))
            latest = observed
        if inject_future:
            quotes.extend(_quotes(latest + dt.timedelta(seconds=1), commence,
                                  offset=99))
            quotes.extend(_quotes(latest + dt.timedelta(minutes=60), commence,
                                  offset=98))
        paths[season].append({
            "event_id": f"evt-{game_pk}",
            "commence_time": commence,
            "away_team": "CIN", "home_team": "NYM",
            "game_pk": game_pk, "date": date,
            # Deliberately present. The engine must never read either.
            "home_won": index % 2 == 0,
            "total_runs": 7 + index,
            "quotes": quotes,
        })
        rows[season].append({
            "game_pk": game_pk, "date": date,
            "start_time_utc": commence.isoformat().replace("+00:00", "Z"),
            "cutoff": date[:8] + "01",
            "away_team": "CIN", "home_team": "NYM",
            "away_top_minus_bottom": 0.05, "home_top_minus_bottom": 0.01,
            "away_starter_velocity_gap": 1.0,
            "home_starter_velocity_gap": 3.5,
        })
    # G6: a matrix row with no priced event.
    rows[2024].append({
        "game_pk": "806", "date": "2024-06-14",
        "start_time_utc": "2024-06-14T22:40:00Z", "cutoff": "2024-06-01",
        "away_team": "CIN", "home_team": "NYM",
        "away_top_minus_bottom": 0.05, "home_top_minus_bottom": 0.01,
        "away_starter_velocity_gap": 1.0, "home_starter_velocity_gap": 3.5,
    })
    for path in extra_paths:
        paths[path["_season"]].append({k: v for k, v in path.items()
                                       if k != "_season"})
    for row in extra_matrix:
        rows[row["_season"]].append({k: v for k, v in row.items()
                                     if k != "_season"})
    return paths, rows


def fixture_universe(*, inject_future=False, extra_paths=(), extra_matrix=()):
    """The fixture universe, loaded through the real loader.

    `code_commit` is pinned so the manifest fingerprint is a function of the
    fixture rather than of whatever commit the suite happens to run at.
    """
    paths, rows = fixture_stores(inject_future=inject_future,
                                 extra_paths=extra_paths,
                                 extra_matrix=extra_matrix)
    return replay.load_universe(
        (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
        registry=SMALL, code_commit="0" * 40)


def replay_digest(universe=None, points=None) -> str:
    """One digest over every WorldView and Decision in the fixture universe.

    The whole replay in one number, which is what the determinism tests
    compare -- across calls, across processes and across hash seeds.

    `points` replays a FIXED ladder against a different universe, which is
    what the leakage test needs: a store that gains an observation after T
    gains a new decision point, and comparing ladders would confuse "a new
    decision exists" with "an old decision moved". Only the second is leakage.
    """
    import hashlib
    universe = universe or fixture_universe()
    genome = a_genome()
    digest = hashlib.sha256()
    for point in (points if points is not None
                  else replay.decision_points(universe=universe)):
        game = universe.get(point.game_pk)
        view = replay.world_view(game, point.T, point_class=point.point_class)
        decision = decide_mod.decide(genome, view, registry=SMALL)
        digest.update(json.dumps(point.to_dict(), sort_keys=True).encode())
        digest.update(replay.worldview_digest(view).encode())
        digest.update(replay.decision_digest(decision).encode())
        for mode in replay.EXECUTION_MODES:
            quote = replay.execution_quote(
                view, "h2h", "home", mode,
                book="alpha" if mode == replay.SPECIFIC_BOOK_EXECUTION
                else None)
            digest.update(json.dumps(quote.to_dict(), sort_keys=True).encode())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Acceptance 1 -- determinism
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):

    def test_the_same_game_and_T_produce_a_byte_identical_worldview(self):
        first, second = fixture_universe(), fixture_universe()
        for game_a, game_b in zip(first.games, second.games):
            for klass, instant in replay.classify_points(game_a):
                view_a = replay.world_view(game_a, instant.observed,
                                           point_class=klass)
                view_b = replay.world_view(game_b, instant.observed,
                                           point_class=klass)
                self.assertEqual(replay.worldview_digest(view_a),
                                 replay.worldview_digest(view_b))

    def test_the_whole_replay_is_byte_identical_across_two_runs(self):
        self.assertEqual(replay_digest(), replay_digest())

    def test_the_replay_is_byte_identical_across_three_hash_seeds(self):
        """Dict and set iteration order is perturbed between PROCESSES, not
        between calls, so this one has to run in subprocesses (the same shape
        test_evolab_core.py already uses)."""
        program = ("import tests.test_evolab_replay as t;"
                   "print(t.replay_digest())")
        digests = set()
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run([sys.executable, "-c", program],
                                 cwd=REPO_ROOT, env=env, capture_output=True,
                                 text=True, check=True)
            digests.add(out.stdout.strip())
        self.assertEqual(len(digests), 1, f"replay drifted: {digests}")

    def test_decision_point_order_is_total_and_stable(self):
        universe = fixture_universe()
        points = [p.to_dict() for p in replay.decision_points(universe=universe)]
        again = [p.to_dict() for p in replay.decision_points(universe=universe)]
        self.assertEqual(points, again)
        keys = [(p["commence_time"], p["game_pk"],
                 replay.POINT_CLASSES.index(p["point_class"])) for p in points]
        self.assertEqual(keys, sorted(keys))

    def test_universe_order_does_not_follow_input_order(self):
        """Hazard H7: file order is a property of how a resumable build ran."""
        paths, rows = fixture_stores()
        for season in rows:
            rows[season] = list(reversed(rows[season]))
            paths[season] = list(reversed(paths[season]))
        shuffled = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        self.assertEqual([g.game_pk for g in shuffled.games],
                         [g.game_pk for g in fixture_universe().games])


# ---------------------------------------------------------------------------
# Acceptance 2 -- structural leakage
# ---------------------------------------------------------------------------

class TestStructuralLeakage(unittest.TestCase):

    def test_a_row_dated_one_second_after_T_changes_nothing(self):
        """Acceptance test 2, at every decision point in the ladder.

        The injected store carries, for every game, a full board one second
        after that game's last observation and another an hour later. Every
        decision the base ladder makes is replayed against the injected store
        and must come out byte-identical -- the WorldView, the Decision and
        all three execution quotes.
        """
        base = fixture_universe()
        points = list(replay.decision_points(universe=base))
        injected = fixture_universe(inject_future=True)
        self.assertEqual(replay_digest(base, points),
                         replay_digest(injected, points))

    def test_the_injected_rows_really_are_in_the_injected_store(self):
        """Guards the test above from passing because nothing was injected."""
        base = fixture_universe()
        injected = fixture_universe(inject_future=True)
        self.assertGreater(len(injected.get("801").instants),
                           len(base.get("801").instants))
        # And they are visible once T reaches them: the engine hides nothing,
        # it simply never reaches past T.
        latest = injected.get("801").instants[-1].observed
        self.assertTrue(replay.world_view(injected.get("801"), latest))

    def test_an_entire_later_game_injected_into_both_stores_changes_nothing(self):
        commence = dt.datetime(2024, 9, 30, 23, 0, tzinfo=UTC)
        extra_path = {
            "_season": 2024, "event_id": "evt-999", "game_pk": "999",
            "commence_time": commence, "date": "2024-09-30",
            "away_team": "CIN", "home_team": "NYM",
            "home_won": True, "total_runs": 11,
            "quotes": _quotes(commence - dt.timedelta(minutes=60), commence),
        }
        extra_row = {
            "_season": 2024, "game_pk": "999", "date": "2024-09-30",
            "start_time_utc": commence.isoformat().replace("+00:00", "Z"),
            "cutoff": "2024-09-01", "away_team": "CIN", "home_team": "NYM",
            "away_top_minus_bottom": 0.9, "home_top_minus_bottom": 0.0,
            "away_starter_velocity_gap": 9.0,
            "home_starter_velocity_gap": 0.0,
        }
        widened = fixture_universe(extra_paths=(extra_path,),
                                   extra_matrix=(extra_row,))
        base = fixture_universe()
        # The new game is served in its own right...
        self.assertEqual(len(widened), len(base) + 1)
        # ...and changes nothing about any decision that came before it.
        genome = a_genome()
        for game in base.games:
            other = widened.get(game.game_pk)
            for klass, instant in replay.classify_points(game):
                a = replay.world_view(game, instant.observed, point_class=klass)
                b = replay.world_view(other, instant.observed, point_class=klass)
                self.assertEqual(replay.worldview_digest(a),
                                 replay.worldview_digest(b))
                self.assertEqual(
                    replay.decision_digest(decide_mod.decide(genome, a,
                                                             registry=SMALL)),
                    replay.decision_digest(decide_mod.decide(genome, b,
                                                             registry=SMALL)))

    def test_the_board_generator_stops_at_T_rather_than_skipping_past_it(self):
        universe = fixture_universe(inject_future=True)
        game = universe.get("801")
        cutoff = game.instants[2].observed
        seen = [i.observed for i in replay.iter_instants_through(game, cutoff)]
        self.assertEqual(seen, [i.observed for i in game.instants[:3]])
        self.assertTrue(all(o <= cutoff for o in seen))
        # The injected future instants exist on the game and are simply never
        # reached -- absence at the decision point, not a filtered store.
        self.assertGreater(len(game.instants), len(seen))

    def test_a_board_stamped_after_T_is_a_named_error(self):
        universe = fixture_universe()
        game = universe.get("801")
        with self.assertRaises(replay.ReplayError):
            replay.world_view(game, game.instants[0].observed
                              - dt.timedelta(minutes=5))

    def test_the_engine_refuses_to_interpolate_a_board(self):
        universe = fixture_universe()
        game = universe.get("801")
        between = game.instants[0].observed + dt.timedelta(minutes=30)
        with self.assertRaises(replay.ReplayError) as caught:
            replay.world_view(game, between)
        self.assertIn("never interpolates", str(caught.exception))

    def test_flipping_the_stored_outcome_cannot_move_a_single_decision(self):
        paths, rows = fixture_stores()
        for season in paths:
            for path in paths[season]:
                path["home_won"] = not path["home_won"]
                path["total_runs"] = 99
        flipped = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        self.assertEqual(replay_digest(flipped), replay_digest())


# ---------------------------------------------------------------------------
# Acceptance 3 -- absent futures
# ---------------------------------------------------------------------------

class TestAbsentFutures(unittest.TestCase):

    def setUp(self):
        self.universe = fixture_universe()
        self.game = self.universe.get("801")
        self.view = replay.world_view(self.game,
                                      self.game.instants[-1].observed)

    def test_the_worldview_exposes_no_outcome_and_no_closing_price(self):
        for name in ("outcome", "home_won", "winner", "result", "final_score",
                     "closing_price", "close", "clv", "closing_line"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(self.view, name))
                with self.assertRaises(AttributeError):
                    getattr(self.view, name)

    def test_the_replay_game_exposes_no_outcome_either(self):
        for name in ("home_won", "outcome", "result", "closing_price"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    getattr(self.game, name)

    def test_no_outcome_field_is_anywhere_in_the_serialised_worldview(self):
        blob = json.dumps(replay.worldview_dict(self.view)).lower()
        for token in ("home_won", "total_runs", "winner", "closing"):
            self.assertNotIn(token, blob)

    def test_a_replay_game_cannot_have_an_outcome_attached_later(self):
        with self.assertRaises(replay.ReplayError):
            self.game.home_won = True

    def test_a_feature_named_like_an_outcome_is_refused_at_construction(self):
        with self.assertRaises(decide_mod.WorldViewError):
            WorldView(game_id="g", official_date="2024-05-01",
                      commence_time="2024-05-01T23:10:00Z",
                      point_class=replay.LATE_BOARD, game={}, board={},
                      features={"home_won": 1},
                      board_meta=BoardMeta(observed_utc="x"))


# ---------------------------------------------------------------------------
# Acceptance 5 -- execution honesty, and the tie-break
# ---------------------------------------------------------------------------

def a_board(prices, *, simultaneous=True):
    """A WorldView carrying one hand-made board. `prices` is {book: (away, home)}."""
    return WorldView(
        game_id="fixture", official_date="2024-05-01",
        commence_time="2024-05-01T23:10:00Z", point_class=replay.LATE_BOARD,
        game={"away": "CIN", "home": "NYM", "park": "Citi Field",
              "commence_time": "2024-05-01T23:10:00Z"},
        features={},
        board={"h2h": {book: {"away_price": away, "home_price": home}
                       for book, (away, home) in prices.items()}},
        board_meta=BoardMeta(observed_utc="2024-05-01T21:40:00Z",
                             books=tuple(sorted(prices)),
                             simultaneous=simultaneous, staleness_seconds=0),
        available=("h2h",), lineup_posted=True)


class TestExecution(unittest.TestCase):

    def board(self, **prices):
        return a_board(prices)

    def test_best_observed_refuses_a_board_that_is_not_simultaneous(self):
        view = a_board({b: (-110, 100) for b in BOOKS}, simultaneous=False)
        quote = replay.execution_quote(view, "h2h", "home",
                                       replay.BEST_OBSERVED_EXECUTION)
        self.assertFalse(quote)
        self.assertEqual(quote.refused, replay.NOT_SIMULTANEOUS)
        self.assertIsNone(quote.price)

    def test_the_other_modes_still_answer_on_a_stitched_board(self):
        """Only best-price depends on simultaneity: a named book's own price
        and the consensus are both true of the quotes as recorded."""
        view = a_board({b: (-110, 100) for b in BOOKS}, simultaneous=False)
        self.assertTrue(replay.execution_quote(
            view, "h2h", "home", replay.CONSENSUS_EXECUTION))
        self.assertTrue(replay.execution_quote(
            view, "h2h", "home", replay.SPECIFIC_BOOK_EXECUTION, book="alpha"))

    def test_a_tie_at_the_best_price_names_no_book(self):
        prices = {b: (-110, 100) for b in BOOKS}
        prices["alpha"] = (-110, 150)
        prices["bravo"] = (-110, 150)
        quote = replay.execution_quote(self.board(**prices), "h2h", "home",
                                       replay.BEST_OBSERVED_EXECUTION)
        self.assertEqual(quote.price, 150)
        self.assertIsNone(quote.book)
        self.assertEqual(quote.tied_books, ("alpha", "bravo"))

    def test_a_unique_best_price_does_name_its_book(self):
        prices = {b: (-110, 100) for b in BOOKS}
        prices["golf"] = (-110, 155)
        quote = replay.execution_quote(self.board(**prices), "h2h", "home",
                                       replay.BEST_OBSERVED_EXECUTION)
        self.assertEqual((quote.price, quote.book, quote.tied_books),
                         (155, "golf", ("golf",)))

    def test_the_tie_break_is_not_alphabetical(self):
        """Reversing the books changes nothing, and no book is crowned."""
        prices = {b: (-110, 100) for b in BOOKS}
        prices["alpha"] = prices["ties_b"] = (-110, 150)
        forward = replay.execution_quote(a_board(prices), "h2h", "home",
                                         replay.BEST_OBSERVED_EXECUTION)
        reversed_board = a_board(dict(reversed(list(prices.items()))))
        backward = replay.execution_quote(reversed_board, "h2h", "home",
                                          replay.BEST_OBSERVED_EXECUTION)
        self.assertEqual(forward.to_dict(), backward.to_dict())
        self.assertIsNone(forward.book)

    def test_plus_and_minus_one_hundred_are_the_same_price(self):
        """Hazard H12: max() over American integers prefers +100 over -100
        even though they are one decimal. Comparing decimals makes them tie,
        and a tie names no book."""
        prices = {b: (-110, -200) for b in BOOKS}
        prices["alpha"] = (-110, 100)
        prices["bravo"] = (-110, -100)
        quote = replay.execution_quote(a_board(prices), "h2h", "home",
                                       replay.BEST_OBSERVED_EXECUTION)
        self.assertIsNone(quote.book)
        self.assertEqual(quote.tied_books, ("alpha", "bravo"))

    def test_consensus_refuses_below_the_six_book_floor(self):
        prices = {b: (-110, 100) for b in BOOKS[:5]}
        quote = replay.execution_quote(a_board(prices), "h2h", "home",
                                       replay.CONSENSUS_EXECUTION)
        self.assertFalse(quote)
        self.assertEqual(quote.refused, replay.THIN_CONSENSUS)

    def test_consensus_returns_a_probability_and_not_a_price(self):
        quote = replay.execution_quote(self.board(**{b: (-110, 100)
                                                     for b in BOOKS}),
                                       "h2h", "home",
                                       replay.CONSENSUS_EXECUTION)
        self.assertIsNone(quote.price)
        self.assertTrue(0.0 < quote.consensus_probability < 1.0)

    def test_consensus_does_not_depend_on_book_order(self):
        prices = {b: (-115 - i, 105 + i) for i, b in enumerate(BOOKS)}
        forward = replay.execution_quote(a_board(prices), "h2h", "away",
                                         replay.CONSENSUS_EXECUTION)
        backward = replay.execution_quote(
            a_board(dict(reversed(list(prices.items())))), "h2h", "away",
            replay.CONSENSUS_EXECUTION)
        self.assertEqual(repr(forward.consensus_probability),
                         repr(backward.consensus_probability))

    def test_a_named_book_that_is_absent_is_a_refusal_not_a_substitute(self):
        quote = replay.execution_quote(
            self.board(**{b: (-110, 100) for b in BOOKS}), "h2h", "home",
            replay.SPECIFIC_BOOK_EXECUTION, book="nowhere")
        self.assertFalse(quote)
        self.assertEqual(quote.refused, replay.BOOK_ABSENT)

    def test_specific_book_will_not_choose_a_book_for_the_caller(self):
        with self.assertRaises(replay.ReplayError):
            replay.execution_quote(
                self.board(**{b: (-110, 100) for b in BOOKS}), "h2h", "home",
                replay.SPECIFIC_BOOK_EXECUTION)

    def test_an_absent_market_is_a_refusal(self):
        quote = replay.execution_quote(
            self.board(**{b: (-110, 100) for b in BOOKS}), "totals", "home",
            replay.CONSENSUS_EXECUTION)
        self.assertEqual(quote.refused, replay.MARKET_UNAVAILABLE)

    def test_every_quote_carries_the_line_shopping_label(self):
        quote = replay.execution_quote(
            self.board(**{b: (-110, 100) for b in BOOKS}), "h2h", "home",
            replay.BEST_OBSERVED_EXECUTION)
        self.assertIn("line-shopping", quote.to_dict()["label"])
        self.assertNotIn("expected value", quote.to_dict()["label"].lower()
                         .replace("not expected value", ""))

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(replay.ReplayError):
            replay.execution_quote(
                self.board(**{b: (-110, 100) for b in BOOKS}), "h2h", "home",
                "WHATEVER_EXECUTION")


# ---------------------------------------------------------------------------
# The starter-identity refusal
# ---------------------------------------------------------------------------

class TestStarterIdentity(unittest.TestCase):

    def test_starter_conditioned_features_are_refused_as_point_in_time(self):
        for feature in ("starter_velocity_gap", "starter_groundball_share",
                        "primary_pitch_share", "away_starter_velocity_gap",
                        "home_primary_pitch_share"):
            with self.subTest(feature=feature):
                with self.assertRaises(replay.NotPointInTimeError) as caught:
                    replay.assert_point_in_time(feature)
                message = str(caught.exception)
                self.assertIn("class C", message)
                self.assertIn("AUDIT_PROBABLE_PITCHER_PIT", message)

    def test_lineup_conditioned_features_are_refused_too(self):
        for feature in ("top_minus_bottom", "lineup_platoon_share",
                        "away_lineup_vs_primary_pitch"):
            with self.subTest(feature=feature):
                with self.assertRaises(replay.NotPointInTimeError) as caught:
                    replay.assert_point_in_time(feature)
                self.assertIn("class D", str(caught.exception))

    def test_schedule_and_market_facts_are_point_in_time(self):
        self.assertEqual(replay.assert_point_in_time("commence_time"), "A")
        self.assertEqual(replay.assert_point_in_time("away_price"), "B")
        self.assertEqual(replay.assert_point_in_time("board"), "B")

    def test_an_unclassified_quantity_is_refused_rather_than_assumed_clean(self):
        with self.assertRaises(replay.ReplayError):
            replay.availability_class("some_new_feature")

    def test_every_registry_feature_is_classified_and_none_is_point_in_time(self):
        from src.evolab.registry import DEFAULT_REGISTRY
        for feature in DEFAULT_REGISTRY.features():
            with self.subTest(feature=feature):
                self.assertIn(replay.availability_class(feature), ("C", "D"))
                with self.assertRaises(replay.NotPointInTimeError):
                    replay.assert_point_in_time(feature)

    def test_the_starter_conditioned_set_is_the_audit_s_set(self):
        self.assertTrue(replay.is_starter_conditioned("starter_velocity_gap"))
        self.assertTrue(replay.is_starter_conditioned("lineup_platoon_share"))
        # top_minus_bottom needs the lineup and not the probable.
        self.assertFalse(replay.is_starter_conditioned("top_minus_bottom"))

    def test_the_measured_agreement_is_the_audit_s_number(self):
        measured = replay.STARTER_IDENTITY.measured
        self.assertEqual(measured["measured_agreement_with_actual_2023"],
                         0.9990)
        self.assertEqual(measured["measured_agreement_with_actual_2024"],
                         0.9992)
        self.assertIs(measured["announced_probable_available"], False)


# ---------------------------------------------------------------------------
# The sealed window
# ---------------------------------------------------------------------------

class TestSealedWindow(unittest.TestCase):

    def test_a_sealed_season_is_refused_by_name(self):
        with self.assertRaises(replay.SealedWindowError):
            replay.load_universe(2026)

    def test_a_sealed_season_is_refused_before_anything_is_read(self):
        """No store path is even constructed: the guard runs first."""
        with self.assertRaises(replay.SealedWindowError):
            list(replay.decision_points((2024, 2026)))

    def test_every_day_of_the_sealed_window_is_refused(self):
        for day in ("2026-01-01", "2026-04-15", "2026-08-27"):
            with self.subTest(day=day):
                with self.assertRaises(replay.SealedWindowError):
                    replay.refuse_sealed(day)

    def test_the_days_either_side_of_the_seal_are_not_refused(self):
        replay.refuse_sealed("2025-12-31")
        replay.refuse_sealed("2026-08-28")

    def test_a_decision_time_inside_the_seal_is_refused(self):
        game = fixture_universe().get("801")
        with self.assertRaises(replay.SealedWindowError):
            replay.world_view(game, "2026-05-01T18:00:00Z")

    def test_2025_is_refused_as_tuning_only_but_not_as_sealed(self):
        with self.assertRaises(replay.ReplayError) as caught:
            replay.load_universe(2025)
        self.assertNotIsInstance(caught.exception, replay.SealedWindowError)
        self.assertIn("tuning-only", str(caught.exception))


# ---------------------------------------------------------------------------
# The two-class ladder
# ---------------------------------------------------------------------------

class TestDecisionPoints(unittest.TestCase):

    def setUp(self):
        self.universe = fixture_universe()
        self.points = list(replay.decision_points(universe=self.universe))
        self.by_game = {}
        for point in self.points:
            self.by_game.setdefault(point.game_pk, []).append(point)

    def test_only_the_two_measured_classes_are_served(self):
        self.assertEqual({p.point_class for p in self.points},
                         set(replay.POINT_CLASSES))

    def test_the_finer_design_rungs_do_not_exist(self):
        for gone in ("T_MINUS_30M", "LINEUP_POSTED", "T_MINUS_24H",
                     "T_MINUS_6H"):
            self.assertNotIn(gone, replay.POINT_CLASSES)

    def test_a_three_instant_game_gets_an_early_and_a_late_board(self):
        classes = [p.point_class for p in self.by_game["801"]]
        self.assertEqual(classes, [replay.EARLY_BOARD, replay.LATE_BOARD])

    def test_a_one_instant_game_is_scored_once(self):
        self.assertEqual([p.point_class for p in self.by_game["804"]],
                         [replay.LATE_BOARD])

    def test_two_early_instants_still_collapse_to_one_late_board(self):
        """G5's boards are both outside the early threshold, so its latest IS
        its early board; emitting both would score one board twice."""
        self.assertEqual([p.point_class for p in self.by_game["805"]],
                         [replay.LATE_BOARD])

    def test_every_T_is_an_observed_instant(self):
        for point in self.points:
            game = self.universe.get(point.game_pk)
            observed = {replay._iso(i.observed) for i in game.instants}
            self.assertIn(point.T, observed)

    def test_the_early_board_clears_the_stated_gap(self):
        for point in self.points:
            if point.point_class == replay.EARLY_BOARD:
                self.assertGreaterEqual(point.gap_minutes,
                                        replay.EARLY_BOARD_MIN_GAP_MINUTES)

    def test_the_late_board_carries_its_gap_so_it_cannot_be_read_as_a_close(self):
        late = [p for p in self.points if p.point_class == replay.LATE_BOARD]
        self.assertTrue(all(p.gap_minutes > 0 for p in late))
        self.assertIn("NOT a close",
                      replay.point_class_definitions()[replay.LATE_BOARD]
                      ["definition"])

    def test_a_universe_and_loader_arguments_cannot_both_be_given(self):
        with self.assertRaises(replay.ReplayError):
            list(replay.decision_points(universe=self.universe,
                                        paths_by_season={}))


# ---------------------------------------------------------------------------
# WorldView assembly and the declared assumptions
# ---------------------------------------------------------------------------

class TestWorldViewAssembly(unittest.TestCase):

    def setUp(self):
        self.universe = fixture_universe()
        self.game = self.universe.get("801")

    def test_the_board_is_the_instant_at_T_and_carries_every_book(self):
        instant = self.game.instants[1]
        view = replay.world_view(self.game, instant.observed)
        self.assertEqual(view.board_meta.observed_utc,
                         replay._iso(instant.observed))
        self.assertEqual(view.board_meta.books, tuple(sorted(BOOKS)))
        self.assertEqual(view.books_for("h2h"), len(BOOKS))
        self.assertTrue(view.board_meta.simultaneous)
        self.assertEqual(view.board_meta.staleness_seconds, 0)

    def test_the_board_never_carries_a_later_instant_s_prices(self):
        early = replay.world_view(self.game, self.game.instants[0].observed)
        late = replay.world_view(self.game, self.game.instants[-1].observed)
        self.assertNotEqual(early.board["h2h"]["alpha"],
                            late.board["h2h"]["alpha"])

    def test_only_registered_features_are_served(self):
        view = replay.world_view(self.game, self.game.instants[-1].observed)
        self.assertEqual(sorted(view.features),
                         ["away_starter_velocity_gap", "away_top_minus_bottom",
                          "home_starter_velocity_gap",
                          "home_top_minus_bottom"])

    def test_a_non_numeric_feature_becomes_none_rather_than_a_number(self):
        paths, rows = fixture_stores()
        rows[2023][0]["away_top_minus_bottom"] = {"pa": 0, "woba": None}
        universe = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        game = universe.get("801")
        self.assertIsNone(game.features["away_top_minus_bottom"])

    def test_lineup_posted_is_the_declared_assumption_not_a_fact(self):
        late = replay.world_view(self.game, self.game.instants[-1].observed)
        early = replay.world_view(self.game, self.game.instants[0].observed)
        self.assertTrue(late.lineup_posted)     # 90 minutes out
        self.assertFalse(early.lineup_posted)   # 24 hours out
        self.assertEqual(
            replay.LINEUP_POSTING.measured[
                "assumed_post_minutes_before_first_pitch"],
            replay.LINEUP_ASSUMED_POST_MINUTES)
        self.assertIs(
            replay.LINEUP_POSTING.measured["posting_timestamp_available"],
            False)

    def test_the_market_list_is_h2h_only(self):
        view = replay.world_view(self.game, self.game.instants[-1].observed)
        self.assertEqual(view.available, ("h2h",))
        self.assertNotIn("spreads", replay.MARKETS_SERVED)

    def test_an_unknown_point_class_is_refused(self):
        with self.assertRaises(replay.ReplayError):
            replay.world_view(self.game, self.game.instants[-1].observed,
                              point_class="T_MINUS_30M")

    def test_a_decision_can_be_made_from_a_served_worldview(self):
        view = replay.world_view(self.game, self.game.instants[-1].observed)
        decision = decide_mod.decide(a_genome(), view, registry=SMALL)
        self.assertTrue(decision)
        self.assertEqual(decision.market, "h2h")
        self.assertIn(decision.side, ("away", "home"))


# ---------------------------------------------------------------------------
# Loading, deduplication and the store hazards
# ---------------------------------------------------------------------------

class TestLoading(unittest.TestCase):

    def test_a_matrix_row_with_no_price_path_is_excluded_and_counted(self):
        universe = fixture_universe()
        self.assertNotIn("806", {g.game_pk for g in universe.games})
        self.assertEqual(universe.manifest.exclusions["no_price_path"], 1)

    def test_an_identical_duplicate_quote_is_deduplicated(self):
        """Hazard H4: the API serves one snapshot for two requested times and
        pricepath appends both, which would weight that book twice."""
        paths, rows = fixture_stores()
        path = paths[2023][0]
        path["quotes"] = path["quotes"] + [dict(path["quotes"][0])]
        universe = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        game = universe.get("801")
        self.assertEqual(len(game.instants[0].quotes), len(BOOKS))
        self.assertEqual(universe.manifest.exclusions[
            "duplicate_quotes_identical"], 1)

    def test_a_conflicting_duplicate_drops_the_book_rather_than_choosing(self):
        paths, rows = fixture_stores()
        path = paths[2023][0]
        clash = dict(path["quotes"][0])
        clash["home_price"] = clash["home_price"] + 40
        path["quotes"] = path["quotes"] + [clash]
        universe = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        game = universe.get("801")
        self.assertNotIn(clash["book"], game.instants[0].books)
        self.assertEqual(universe.manifest.exclusions[
            "duplicate_quotes_conflicting"], 1)

    def test_a_quote_at_or_after_first_pitch_is_dropped_and_counted(self):
        paths, rows = fixture_stores()
        path = paths[2023][0]
        commence = path["commence_time"]
        path["quotes"] = path["quotes"] + _quotes(commence, commence)
        universe = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        game = universe.get("801")
        self.assertTrue(all(i.observed < commence for i in game.instants))
        self.assertEqual(universe.manifest.exclusions[
            "quotes_at_or_after_first_pitch"], 1)

    def test_two_events_for_one_game_resolve_by_a_stated_rule(self):
        """Hazard H5. The richer board wins; an exact tie falls to event_id."""
        paths, rows = fixture_stores()
        thin = dict(paths[2023][0])
        thin["event_id"] = "evt-801-alt"
        thin["quotes"] = paths[2023][0]["quotes"][:len(BOOKS)]
        paths[2023].append(thin)
        universe = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        self.assertEqual(universe.get("801").event_id, "evt-801")
        self.assertEqual(universe.manifest.exclusions["multi_event_games"], 1)

    def test_a_duplicated_matrix_row_is_a_loud_refusal(self):
        paths, rows = fixture_stores()
        rows[2023].append(dict(rows[2023][0]))
        with self.assertRaises(replay.ReplayError):
            replay.load_universe((2023, 2024), paths_by_season=paths,
                                 matrix_rows_by_season=rows, registry=SMALL,
                                 code_commit="0" * 40)

    def test_the_universe_is_ordered_by_first_pitch_then_game(self):
        games = fixture_universe().games
        keys = [(g.commence_time, g.game_pk) for g in games]
        self.assertEqual(keys, sorted(keys))

    def test_an_unknown_game_is_a_named_refusal(self):
        with self.assertRaises(replay.ReplayError):
            fixture_universe().get("no-such-game")


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

class TestManifest(unittest.TestCase):

    def setUp(self):
        self.manifest = fixture_universe().manifest

    def test_it_records_the_universe_and_the_seasons(self):
        payload = self.manifest.to_dict()
        self.assertEqual(payload["universe_size"], 5)
        self.assertEqual(payload["seasons"], [2023, 2024])
        self.assertEqual(payload["games_by_season"], {"2023": 2, "2024": 3})
        self.assertEqual(payload["phase0_expected_universe"], 4819)

    def test_it_records_the_commit_and_never_invents_one(self):
        self.assertEqual(self.manifest.code_commit, "0" * 40)
        self.assertIsNone(replay._git_commit(repo_root="/nonexistent-repo-xyz"))

    def test_it_records_both_declared_assumptions_with_versions(self):
        payload = self.manifest.to_dict()
        self.assertEqual(payload["starter_identity"]["name"],
                         "starter_identity")
        self.assertEqual(payload["starter_identity"]["value"],
                         "actual_at_first_pitch")
        self.assertTrue(payload["starter_identity"]["version"])
        self.assertEqual(
            payload["starter_identity"]["measured"][
                "measured_agreement_with_actual_2023"], 0.9990)
        self.assertEqual(payload["lineup_posting"]["value"],
                         "assumed_T_minus_180_minutes")

    def test_it_records_the_point_class_definitions_and_the_amendment(self):
        classes = self.manifest.to_dict()["point_classes"]
        self.assertEqual(sorted(k for k in classes
                                if k in replay.POINT_CLASSES),
                         sorted(replay.POINT_CLASSES))
        self.assertIn("177 minutes", classes["amended_from_design"])

    def test_it_records_the_tie_break_rule_in_words(self):
        rule = self.manifest.to_dict()["best_price_tie_break"]
        self.assertIn("DECIMAL", rule)
        self.assertIn("never names", rule)

    def test_a_fixture_run_cannot_be_mistaken_for_a_store_run(self):
        prints = self.manifest.to_dict()["store_fingerprints"]
        self.assertIn("__injected__", prints)
        self.assertIn("no store file was read",
                      prints["__injected__"]["note"])

    def test_real_store_fingerprints_are_content_hashes(self):
        prints = replay.store_fingerprints((2023,))
        entry = prints["matchup_matrix_2023"]
        if entry.get("missing"):
            self.skipTest("matchup matrix store not present")
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertGreater(entry["bytes"], 0)

    def test_it_says_nothing_here_is_evidence(self):
        self.assertIn("NOT evidence", self.manifest.to_dict()["evidence"])

    def test_stamping_attaches_the_manifest_without_mutating_the_artifact(self):
        artifact = {"result": 1}
        stamped = self.manifest.stamp(artifact)
        self.assertEqual(artifact, {"result": 1})
        self.assertEqual(stamped["replay_manifest"]["universe_size"], 5)
        self.assertIn("evidence", stamped)

    def test_a_second_stamp_is_refused(self):
        stamped = self.manifest.stamp({"result": 1})
        with self.assertRaises(replay.ReplayError):
            self.manifest.stamp(stamped)

    def test_the_fingerprint_is_stable_and_moves_with_the_universe(self):
        self.assertEqual(self.manifest.fingerprint(),
                         fixture_universe().manifest.fingerprint())
        paths, rows = fixture_stores()
        rows[2023] = rows[2023][:1]
        smaller = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        self.assertNotEqual(self.manifest.fingerprint(),
                            smaller.manifest.fingerprint())

    def test_it_reconciles_its_count_against_phase_zero(self):
        self.assertIn("4,819", self.manifest.to_dict()[
            "universe_reconciliation"])

    def test_the_module_says_nothing_it_produces_is_evidence(self):
        self.assertIn("NOTHING IN THIS PACKAGE IS EVIDENCE",
                      replay.__doc__)


# ---------------------------------------------------------------------------
# One pass over the real stores
# ---------------------------------------------------------------------------

class TestAgainstTheRealStore(unittest.TestCase):
    """One season, loaded from the stores as they stand.

    Everything above runs on fixtures, which proves the logic and proves
    nothing about the data. This pins the count the engine actually serves so
    a change in a store or a reader shows up as a failing test rather than as
    a different number in a report nobody diffed.
    """

    SEASON = 2023
    # 2,406 = Phase 0's 2,408 for 2023, less the two games whose every quote
    # is stamped at or after the schedule's first pitch. See the manifest's
    # universe_reconciliation.
    EXPECTED = 2406

    universe = None

    def setUp(self):
        from src.pipeline import backfill
        matrix_file = (Path("data/research")
                       / f"matchup_matrix_{self.SEASON}.jsonl")
        odds_file = Path(backfill.DEFAULT_STORE) / f"mlb_{self.SEASON}.jsonl"
        if not matrix_file.exists() or not odds_file.exists():
            self.skipTest("historical stores are not present")
        # Loaded once for the class: a season costs a few seconds to build and
        # every test here wants the same universe.
        if TestAgainstTheRealStore.universe is None:
            TestAgainstTheRealStore.universe = replay.load_universe(
                self.SEASON, code_commit="pinned")

    def test_the_served_universe_is_the_reconciled_count(self):
        universe = self.universe
        self.assertEqual(len(universe), self.EXPECTED)
        self.assertEqual(universe.manifest.games_by_season[self.SEASON],
                         self.EXPECTED)
        # The join itself still reproduces Phase 0's number exactly.
        exclusions = universe.manifest.exclusions
        self.assertEqual(exclusions["matrix_rows"] - exclusions["no_price_path"],
                         replay.PHASE0_UNIVERSE_BY_SEASON[self.SEASON])

    def test_every_real_board_is_pre_game_simultaneous_and_deduplicated(self):
        universe = self.universe
        self.assertEqual(universe.manifest.exclusions[
            "duplicate_quotes_conflicting"], 0)
        for game in universe.games[:200]:
            for instant in game.instants:
                self.assertLess(instant.observed, game.commence_time)
                self.assertTrue(instant.simultaneous)
                self.assertEqual(len(set(instant.books)),
                                 len(instant.books))

    def test_a_real_replay_is_byte_identical_across_two_loads(self):
        first = self.universe
        second = replay.load_universe(self.SEASON, code_commit="pinned")
        self.assertEqual(first.manifest.fingerprint(),
                         second.manifest.fingerprint())
        genome = a_genome(replay.DEFAULT_REGISTRY)
        for game_a, game_b in zip(first.games[:300], second.games[:300]):
            for klass, instant in replay.classify_points(game_a):
                view_a = replay.world_view(game_a, instant.observed,
                                           point_class=klass)
                view_b = replay.world_view(game_b, instant.observed,
                                           point_class=klass)
                self.assertEqual(replay.worldview_digest(view_a),
                                 replay.worldview_digest(view_b))
                self.assertEqual(
                    replay.decision_digest(decide_mod.decide(genome, view_a)),
                    replay.decision_digest(decide_mod.decide(genome, view_b)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
