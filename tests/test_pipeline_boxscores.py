"""Tests for src/pipeline/boxscores.py. No network -- fetch_* are injected."""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import boxscores

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


class TestBuildRows(unittest.TestCase):
    """Pure, network-free: exercised directly against the recorded fixtures."""

    def test_build_rows_from_the_fixture(self):
        box = _load("mlb_boxscore_822688.json")
        linescore = _load("mlb_linescore_822688.json")
        rows = boxscores.build_rows("2026-08-30", 822688, box, linescore,
                                     "2026-08-31T04:00:00Z")
        pitchers = [r for r in rows if r["type"] == "pitcher"]
        batters = [r for r in rows if r["type"] == "batter"]
        linescores = [r for r in rows if r["type"] == "linescore"]
        self.assertEqual(len(pitchers), 9)
        self.assertEqual(len(batters), 24)
        self.assertEqual(len(linescores), 1)
        for row in rows:
            self.assertEqual(row["date"], "2026-08-30")
            self.assertEqual(row["observed_utc"], "2026-08-31T04:00:00Z")
            self.assertEqual(row["game_pk"], 822688)


class TestIngestDate(unittest.TestCase):
    """ingest_date with every dependency injected -- no network, no clock."""

    def _fake_results(self, day, timeout=20):
        return {"final": [{"game_pk": 822688}, {"game_pk": 822766}]}

    def _fake_boxscore(self, game_pk, timeout=20):
        return _load(f"mlb_boxscore_{game_pk}.json")

    def _fake_linescore(self, game_pk, timeout=20):
        return _load(f"mlb_linescore_{game_pk}.json")

    def test_ingest_writes_both_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "boxscores_2026.jsonl"
            report = boxscores.ingest_date(
                "2026-08-30", path=path,
                fetch_results=self._fake_results,
                fetch_boxscore=self._fake_boxscore,
                fetch_linescore=self._fake_linescore,
                clock=lambda: __import__("datetime").datetime(
                    2026, 8, 31, 4, 0, tzinfo=__import__("datetime").timezone.utc),
                sleep=lambda s: None,
            )
            self.assertEqual(report["games_written"], 2)
            self.assertEqual(report["games_skipped"], 0)
            self.assertEqual(report["errors"], [])
            rows = boxscores.read(path)
            game_pks = {r["game_pk"] for r in rows}
            self.assertEqual(game_pks, {822688, 822766})
            # every row's observed_utc was stamped from the injected clock
            self.assertTrue(all(r["observed_utc"] == "2026-08-31T04:00:00Z"
                                 for r in rows))

    def test_idempotent_rerun_skips_already_stored_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "boxscores_2026.jsonl"
            boxscores.ingest_date(
                "2026-08-30", path=path,
                fetch_results=self._fake_results,
                fetch_boxscore=self._fake_boxscore,
                fetch_linescore=self._fake_linescore,
                sleep=lambda s: None,
            )
            first_rows = boxscores.read(path)

            # rerun: fetch_boxscore/fetch_linescore would raise if called
            # again for an already-stored game_pk, proving the skip is real.
            def boom(*a, **k):
                raise AssertionError("should not refetch an already-stored game")

            report = boxscores.ingest_date(
                "2026-08-30", path=path,
                fetch_results=self._fake_results,
                fetch_boxscore=boom,
                fetch_linescore=boom,
                sleep=lambda s: None,
            )
            self.assertEqual(report["games_written"], 0)
            self.assertEqual(report["games_skipped"], 2)
            self.assertEqual(boxscores.read(path), first_rows)  # untouched

    def test_a_failed_game_does_not_block_the_other_and_is_retried_later(self):
        def flaky_boxscore(game_pk, timeout=20):
            if game_pk == 822688:
                from src.providers.mlb import MLBError
                raise MLBError("simulated network failure")
            return _load(f"mlb_boxscore_{game_pk}.json")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "boxscores_2026.jsonl"
            report = boxscores.ingest_date(
                "2026-08-30", path=path,
                fetch_results=self._fake_results,
                fetch_boxscore=flaky_boxscore,
                fetch_linescore=self._fake_linescore,
                sleep=lambda s: None,
            )
            self.assertEqual(report["games_written"], 1)
            self.assertEqual(len(report["errors"]), 1)
            self.assertEqual(report["errors"][0]["game_pk"], 822688)
            rows = boxscores.read(path)
            self.assertEqual({r["game_pk"] for r in rows}, {822766})

            # rerun without the flake: the failed game is retried, not skipped
            report2 = boxscores.ingest_date(
                "2026-08-30", path=path,
                fetch_results=self._fake_results,
                fetch_boxscore=self._fake_boxscore,
                fetch_linescore=self._fake_linescore,
                sleep=lambda s: None,
            )
            self.assertEqual(report2["games_written"], 1)
            self.assertEqual(report2["games_skipped"], 1)
            game_pks = {r["game_pk"] for r in boxscores.read(path)}
            self.assertEqual(game_pks, {822688, 822766})


if __name__ == "__main__":
    unittest.main()
