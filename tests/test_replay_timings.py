"""Additive timing instrumentation on replay.py: load_universe and world_view.

Pins two things: (1) passing a TimingCollector records the expected stage,
and (2) not passing one (the default) changes nothing about the universe or
view returned -- instrumentation must never leak into research content
(map-compute-scale.md section 1).
"""

from __future__ import annotations

import unittest

from src.core.timing import TimingCollector
from src.evolab import decide as decide_mod
from src.evolab import replay
from tests.test_evolab_replay import a_genome, fixture_stores, SMALL


class TestLoadUniverseTimings(unittest.TestCase):

    def test_universe_build_stage_is_recorded_when_collector_given(self):
        paths, rows = fixture_stores()
        collector = TimingCollector()
        universe = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40, timings=collector)
        self.assertEqual([r["stage"] for r in collector.to_list()],
                         ["universe_build"])
        self.assertGreater(len(universe.games), 0)

    def test_omitting_timings_gives_the_identical_universe(self):
        paths, rows = fixture_stores()
        kwargs = dict(paths_by_season=paths, matrix_rows_by_season=rows,
                     registry=SMALL, code_commit="0" * 40)
        without = replay.load_universe((2023, 2024), **kwargs)
        with_timings = replay.load_universe(
            (2023, 2024), timings=TimingCollector(), **kwargs)
        self.assertEqual([g.game_pk for g in without.games],
                         [g.game_pk for g in with_timings.games])
        self.assertEqual(without.manifest.registry_fingerprint,
                         with_timings.manifest.registry_fingerprint)


class TestWorldViewTimings(unittest.TestCase):

    def test_world_view_stage_is_recorded_when_collector_given(self):
        paths, rows = fixture_stores()
        universe = replay.load_universe(
            (2023, 2024), paths_by_season=paths, matrix_rows_by_season=rows,
            registry=SMALL, code_commit="0" * 40)
        point = next(iter(replay.decision_points(universe=universe)))
        game = universe.get(point.game_pk)
        collector = TimingCollector()
        view = replay.world_view(game, point.T, point_class=point.point_class,
                                 timings=collector)
        self.assertEqual([r["stage"] for r in collector.to_list()],
                         ["world_view"])

        # Same call without a collector must return an equivalent view.
        view_again = replay.world_view(game, point.T,
                                       point_class=point.point_class)
        self.assertEqual(replay.worldview_digest(view),
                         replay.worldview_digest(view_again))


if __name__ == "__main__":
    unittest.main()
