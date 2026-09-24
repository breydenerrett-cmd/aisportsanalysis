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


class ResumeIsScopeAware(unittest.TestCase):
    """A date stored under a NARROWER gameType scope is not complete for a
    wider request.

    This is what made the 2025 backfill silently return nothing: every
    October 2025 date had been ingested under the R-only filter, recorded
    its postseason games as `skipped_game_type`, and marked the date done.
    A later decisive request was told "all 38 dates already ingested" and
    only `--no-resume` recovered them -- which re-fetches genuinely finished
    dates too. Resume has to be correct so the daily job heals itself.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.manifest = os.path.join(self._tmp.name, "manifest.json")

    def _manifest(self, entry):
        history.write_manifest({"2025-10-05": entry}, self.manifest)

    def test_an_r_only_date_is_incomplete_for_a_decisive_request(self):
        self._manifest({"total": 4, "final": 4, "pending": 0, "cancelled": 0,
                        "stored": 0, "skipped_game_type": 4,
                        "game_types": ["R"]})
        missing = history.missing_dates("2025-10-05", "2025-10-05",
                                        self.manifest,
                                        game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual(["2025-10-05"], missing)

    def test_a_decisive_date_is_complete_for_a_training_request(self):
        """Scope containment runs one way: a wider store satisfies a
        narrower ask, and must not trigger a pointless re-fetch."""
        self._manifest({"total": 4, "final": 4, "pending": 0, "cancelled": 0,
                        "stored": 4, "skipped_game_type": 0,
                        "game_types": sorted(mlb.DECISIVE_GAME_TYPES)})
        missing = history.missing_dates("2025-10-05", "2025-10-05",
                                        self.manifest,
                                        game_types=mlb.TRAINING_GAME_TYPES)
        self.assertEqual([], missing)

    def test_a_decisive_date_stays_complete_for_a_decisive_request(self):
        """Idempotency. The daily job must not re-fetch the same date
        forever once it has been stored at the right scope."""
        self._manifest({"total": 4, "final": 4, "pending": 0, "cancelled": 0,
                        "stored": 4, "skipped_game_type": 0,
                        "game_types": sorted(mlb.DECISIVE_GAME_TYPES)})
        missing = history.missing_dates("2025-10-05", "2025-10-05",
                                        self.manifest,
                                        game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual([], missing)

    def test_a_legacy_entry_with_no_scope_reads_as_regular_season_only(self):
        """Every manifest entry written before this existed came from the
        one caller there was, which passed TRAINING_GAME_TYPES. That is a
        fact about those runs, not an assumption."""
        self._manifest({"total": 4, "final": 4, "pending": 0,
                        "cancelled": 0, "stored": 0, "skipped_game_type": 4})
        self.assertEqual(
            ["2025-10-05"],
            history.missing_dates("2025-10-05", "2025-10-05", self.manifest,
                                  game_types=mlb.DECISIVE_GAME_TYPES))
        self.assertEqual(
            [],
            history.missing_dates("2025-10-05", "2025-10-05", self.manifest,
                                  game_types=mlb.TRAINING_GAME_TYPES))

    def test_unfinished_dates_still_come_back_regardless_of_scope(self):
        """A date fetched while games were in progress owes results whatever
        the scope question says."""
        self._manifest({"total": 4, "final": 1, "pending": 3, "cancelled": 0,
                        "stored": 1, "skipped_game_type": 0,
                        "game_types": sorted(mlb.DECISIVE_GAME_TYPES)})
        self.assertEqual(
            ["2025-10-05"],
            history.missing_dates("2025-10-05", "2025-10-05", self.manifest,
                                  game_types=mlb.DECISIVE_GAME_TYPES))

    def test_omitting_game_types_preserves_the_old_behaviour_exactly(self):
        self._manifest({"total": 4, "final": 4, "pending": 0, "cancelled": 0,
                        "stored": 0, "skipped_game_type": 4,
                        "game_types": ["R"]})
        self.assertEqual(
            [], history.missing_dates("2025-10-05", "2025-10-05",
                                      self.manifest))

    def test_the_scope_is_recorded_on_the_manifest_entry(self):
        store, manifest, _s = {}, {}, None
        with mock.patch.object(mlb, "fetch_results",
                               return_value=_results([_final(1, "F")])):
            history.ingest_date("2026-09-29", store, manifest,
                                game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual(sorted(mlb.DECISIVE_GAME_TYPES),
                         manifest["2026-09-29"]["game_types"])


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
