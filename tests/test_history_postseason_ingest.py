"""The postseason has to reach the results store, or October grades VOID.

Nothing in the card path filters on `game_type`: a Wild Card game is
modelled, priced, published and locked exactly like a regular-season one.
Settlement then reads `mlb_results.csv` through `history.read_results()`
(`src/cli.py`), and until 2026-09-23 that store ingested regular-season
games only -- so every postseason pick would have graded VOID with "no
final score stored for this game".

Wild Card play begins 2026-09-29 (`docs/SEASON_END_PLAN.md`). These tests
pin the fix and the default that must not change with it.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from src.pipeline import history
from src.providers import mlb


def _final(game_pk, game_type, date="2026-09-29"):
    return {
        "game_pk": game_pk, "date": date, "game_type": game_type,
        "start_time_utc": f"{date}T20:08:00Z", "venue": "Somewhere Park",
        "away_team": "TOR", "home_team": "NYY",
        "away_team_id": 141, "home_team_id": 147,
        "away_score": 3, "home_score": 5, "winner": "NYY", "home_won": True,
        "total_runs": 8, "run_differential": 2,
        "double_header": "N", "game_number": 1,
    }


def _results(finals):
    return {
        "date": finals[0]["date"] if finals else "2026-09-29",
        "final": finals,
        "summary": {"total": len(finals), "final": len(finals),
                    "pending": 0, "cancelled": 0},
    }


class IngestDateGameTypes(unittest.TestCase):

    def _run(self, finals, **kwargs):
        store, manifest = {}, {}
        with mock.patch.object(mlb, "fetch_results",
                               return_value=_results(finals)):
            summary = history.ingest_date("2026-09-29", store, manifest,
                                          **kwargs)
        return store, manifest, summary

    def test_the_default_still_stores_regular_season_only(self):
        """The pre-existing contract. Every caller that does not ask for the
        postseason must keep getting exactly what it got before."""
        store, _m, summary = self._run(
            [_final(1, "R"), _final(2, "F"), _final(3, "W")])
        self.assertEqual(["1"], sorted(store))
        self.assertEqual(2, summary["skipped_game_type"])

    def test_decisive_game_types_store_the_postseason(self):
        store, _m, summary = self._run(
            [_final(1, "R"), _final(2, "F"), _final(3, "D"),
             _final(4, "L"), _final(5, "W")],
            game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual(["1", "2", "3", "4", "5"], sorted(store))
        self.assertEqual(0, summary["skipped_game_type"])

    def test_spring_training_is_still_excluded_from_the_decisive_set(self):
        """'Decisive' is not 'everything'. Spring games are a different
        process wearing the same uniforms and must not arrive by accident."""
        store, _m, _s = self._run(
            [_final(1, "W"), _final(2, "S"), _final(3, "E"), _final(4, "A")],
            game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual(["1"], sorted(store))

    def test_the_stored_row_keeps_its_game_type(self):
        """Grading and any postseason analysis both need to tell a Wild Card
        game from a regular-season one after the fact."""
        store, _m, _s = self._run([_final(9, "F")],
                                  game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual("F", store["9"]["game_type"])


class IngestRangeForwardsGameTypes(unittest.TestCase):
    """`ingest_range` is what the CLI and any scheduled job call. Forwarding
    was the actual gap -- `ingest_date` already took the argument and
    `ingest_range` never passed it on."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = os.path.join(self._tmp.name, "results.csv")
        self.manifest = os.path.join(self._tmp.name, "manifest.json")

    def _range(self, **kwargs):
        finals = [_final(1, "R"), _final(2, "F")]
        with mock.patch.object(mlb, "fetch_results",
                               return_value=_results(finals)):
            return history.ingest_range(
                "2026-09-29", "2026-09-29", store_path=self.store,
                manifest_path=self.manifest, **kwargs)

    def test_default_range_ingest_drops_the_postseason(self):
        self._range()
        stored = history.read_results(self.store)
        self.assertEqual(["1"], sorted(stored))

    def test_range_ingest_keeps_the_postseason_when_asked(self):
        self._range(game_types=mlb.DECISIVE_GAME_TYPES)
        stored = history.read_results(self.store)
        self.assertEqual(["1", "2"], sorted(stored))
        self.assertEqual("F", stored["2"]["game_type"])

    def test_the_manifest_records_what_was_skipped(self):
        self._range()
        with open(self.manifest, encoding="utf-8") as fh:
            manifest = json.load(fh)
        day = manifest["dates"]["2026-09-29"]
        self.assertEqual(1, day["skipped_game_type"])
        self.assertEqual(2, day["final"])


class DecisiveTypesCoverTheWholeBracket(unittest.TestCase):
    """The 2026 calendar in docs/SEASON_END_PLAN.md names exactly these
    gameTypes; if the constant ever loses one, October goes ungraded again
    and nothing else would say so."""

    def test_every_postseason_round_is_in_the_decisive_set(self):
        for code in ("F", "D", "L", "W"):
            self.assertIn(code, mlb.DECISIVE_GAME_TYPES, code)
        self.assertIn(mlb.GAME_TYPE_REGULAR, mlb.DECISIVE_GAME_TYPES)

    def test_training_types_remain_regular_season_only(self):
        self.assertEqual(frozenset({"R"}), mlb.TRAINING_GAME_TYPES)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
