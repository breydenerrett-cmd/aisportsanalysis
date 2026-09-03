"""Regression test: ReplayUniverse.get() must stay behaviour-identical after
being routed through by_id() instead of a linear scan.

WHY THIS TEST EXISTS
---------------------
map-compute-scale.md section 2b found `get()` doing `for game in self.games:
if game.game_pk == str(game_pk)` beside an unused `by_id()` dict -- O(n) sitting
next to an O(1) that nothing called. The fix (src/evolab/replay.py) routes
`get()` through `by_id()`; this test pins that the visible behaviour -- same
game object back for a hit, the same ReplayError for a miss -- did not change,
using the same fixture universe the rest of the replay suite already trusts.
"""

from __future__ import annotations

import unittest

from src.evolab import replay
from tests.test_evolab_replay import fixture_universe


class TestGetMatchesById(unittest.TestCase):

    def setUp(self):
        self.universe = fixture_universe()

    def test_get_returns_the_same_object_by_id_would(self):
        for game in self.universe.games:
            self.assertIs(self.universe.get(game.game_pk),
                          self.universe.by_id()[game.game_pk])

    def test_get_accepts_a_non_string_game_pk_like_by_id_would_after_str(self):
        game = self.universe.games[0]
        # game_pk is stored as str (replay.py's own convention); get() must
        # still find it when called with e.g. an int, exactly as the old
        # linear-scan implementation did (`game.game_pk == str(game_pk)`).
        looked_up = self.universe.get(int(game.game_pk))
        self.assertIs(looked_up, game)

    def test_get_raises_replay_error_on_a_miss_same_as_before(self):
        with self.assertRaises(replay.ReplayError):
            self.universe.get("no-such-game-pk")

    def test_get_and_by_id_agree_on_every_game_in_the_universe(self):
        by_id = self.universe.by_id()
        self.assertEqual(len(by_id), len(self.universe.games))
        for game_pk, game in by_id.items():
            self.assertIs(self.universe.get(game_pk), game)


if __name__ == "__main__":
    unittest.main()
