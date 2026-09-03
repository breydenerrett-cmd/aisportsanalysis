"""S3 -- the replay driver (`src.engine.adapters.evolab_system`): historical
replay through `analyze()`, and the registered systems set.

The historical odds/results archive under `data/historical/` is large and
not part of every checkout (see docs/CHECKPOINT_PHASE0_2026-09-03.md and
tests/test_validation_m3.py's own guard for the same store); this module
skips its real-data tests, rather than failing, when that store is absent.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.pipeline import backfill

_ODDS_HISTORY_PRESENT = Path(backfill.DEFAULT_STORE).exists()


class TestRegisteredSystems(unittest.TestCase):
    """No real historical data needed -- this is pure enumeration."""

    def test_registered_systems_include_trivial_control_and_genomes(self):
        from src.engine.adapters.evolab_system import (
            REGISTERED_EVOLAB_SYSTEMS, REGISTERED_SYSTEMS,
        )

        self.assertGreaterEqual(len(REGISTERED_SYSTEMS), 9)
        self.assertLessEqual(len(REGISTERED_EVOLAB_SYSTEMS) + 1,
                             17)  # trivial + "say 8-16" genomes
        self.assertEqual(REGISTERED_SYSTEMS[0].id, "trivial_always_home")
        ids = [s.id for s in REGISTERED_SYSTEMS]
        self.assertEqual(len(ids), len(set(ids)),
                         "every registered system must have a unique id")

    def test_registered_systems_are_deterministic_across_calls(self):
        from src.engine.adapters.evolab_system import _select_registered_genomes

        first = tuple(g.strategy_id for g in _select_registered_genomes())
        second = tuple(g.strategy_id for g in _select_registered_genomes())
        self.assertEqual(first, second)


@unittest.skipUnless(_ODDS_HISTORY_PRESENT,
                     "data/historical/odds_history not present in this "
                     "checkout -- skipping real-replay S3 tests")
class TestReplayDriverThroughTheWaist(unittest.TestCase):
    def test_historical_snapshot_and_board_use_glue_construction_functions(self):
        from src.evolab import replay as replay_module
        from src.engine.adapters.evolab_system import historical_snapshot_and_board
        from src.engine.snapshot import PriceBlindSnapshot, PricedBoard

        universe = replay_module.load_universe([2023])
        game = universe.games[0]
        points = [p for p in replay_module.decision_points([2023], universe=universe)
                  if p.game_pk == game.game_pk]
        self.assertTrue(points)
        point = points[-1]

        snapshot, board = historical_snapshot_and_board(
            game, point.T, point_class=point.point_class)
        self.assertIsInstance(snapshot, PriceBlindSnapshot)
        self.assertIsInstance(board, PricedBoard)
        self.assertEqual(snapshot.game_pk, board.game_pk)
        self.assertTrue(board.quotes)

    def test_replay_decision_agrees_with_decide_with_reason_on_selection(self):
        """The equivalence obligation, exercised directly (not via the
        equivalence script): for a genome that plays SOMEWHERE in a small
        sample, the S3 driver's `analyze()` output names the same
        (market, side) as `decide_with_reason` -- the ONLY thing evolab's
        own decision primitive promises."""
        from src.board.ids import selection_id as _sel_id
        from src.engine.adapters.evolab_system import replay_decision
        from src.evolab import replay as replay_module
        from src.evolab.decide import decide_with_reason
        from src.evolab.genome import enumerate_genomes
        from src.evolab.registry import DEFAULT_REGISTRY

        universe = replay_module.load_universe([2023])
        points = list(replay_module.decision_points([2023], universe=universe))[:60]
        games_by_pk = {g.game_pk: g for g in universe.games}
        genomes = enumerate_genomes()[:20]

        checked = 0
        for genome in genomes:
            for point in points:
                game = games_by_pk.get(point.game_pk)
                if game is None:
                    continue
                view = replay_module.world_view(game, point.T,
                                                point_class=point.point_class)
                decision, _reason = decide_with_reason(
                    genome, view, registry=DEFAULT_REGISTRY)
                if not decision:
                    continue
                analysis = replay_decision(genome, game, point.T,
                                           point_class=point.point_class,
                                           adversaries=())
                self.assertEqual(len(analysis.records), 1)
                rec = analysis.records[0]
                expected = _sel_id(sport="mlb", market_key=decision.market,
                                   side=decision.side)
                self.assertEqual(rec.market_key, decision.market)
                self.assertEqual(rec.selection_id, expected)
                # Honest probabilities: evolab's own decision primitive
                # never carries a p_model, so the driven record must not
                # either.
                self.assertIsNone(rec.p_model)
                self.assertIsNone(rec.rating)
                self.assertIsNotNone(rec.value_basis)
                checked += 1
                if checked >= 3:
                    return
        self.skipTest("no genome in this small sample played anywhere -- "
                      "not a failure, just an uninformative sample")


if __name__ == "__main__":
    unittest.main()
