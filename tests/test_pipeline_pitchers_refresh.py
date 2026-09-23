"""Regression tests for the ongoing-season pitcher-log refresh policy.

THE DEFECT (found 2026-09-22, "0 pitchers fetched" for five straight daily
runs since 2026-09-19)
--------------------------------------------------------------------------
`src.pipeline.pitchers.build_log_store`'s `resume=True` skip check
(`_has_season`) fires the moment ANY row -- a real appearance or the
"fetched, none found" empty marker -- exists for a season, with no regard
for whether that row is stale. That is the right contract for a CLOSED
season nothing will ever add rows to again (2025 and earlier), and the
wrong one for the CURRENT season, which is still accruing appearances every
day: once a starter has one cached 2026 row, every later start he makes is
never fetched again, and a pitcher marked empty before his debut is
"complete" forever even after he starts pitching.

`src.cli.py`'s daily loop (`cmd_daily`'s step 3, `do_pitchers`) calls
`build_log_store(ids, today[:4])` -- the CURRENT season, `resume` at its
default `True` -- every single day, which is exactly the call path this
defect lived on in production.

The fix adds a `refresh=True` mode (see `build_log_store`'s own docstring)
that separates the two contracts: a pitcher is re-checked once its own
per-season "checked_utc" marker is stale, rather than skipped forever the
moment any row for the season exists.

Every test below calls `build_log_store(..., refresh=True, now=...)`. Run
against the PRE-FIX module (no `refresh` keyword existed at all) every one
of these raises `TypeError: build_log_store() got an unexpected keyword
argument 'refresh'` -- the correct and expected pre-fix failure, since the
capability under test simply did not exist yet. That verbatim output is
recorded in the accompanying report, not reproduced here as a doctest,
because re-running it would require reverting the fix.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import pitchers
from src.providers import mlb
from src.providers.mlb import MLBError


def appearance(person, day, ip=6.0, er=2, k=6, bb=2, h=5, hr=1, bf=24,
               started=1, season="2026"):
    return {
        "person_id": int(person), "date": day, "season": season,
        "is_home": False, "games_started": started,
        "innings_pitched": ip, "earned_runs": er, "runs": er,
        "hits": h, "walks": bb, "strikeouts": k, "home_runs": hr,
        "batters_faced": bf, "pitches": 95,
    }


class TestRefreshPicksUpNewAppearances(unittest.TestCase):
    def test_stale_cached_pitcher_gains_a_later_completed_appearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            # A prior refresh already ran and cached one April start, with a
            # checked_utc marker over 20h in the past relative to `now` below.
            pitchers.write_logs({
                "1": [appearance("1", "2026-04-05"),
                      {"person_id": 1, "season": "2026", "date": None,
                       "empty": False,
                       "checked_utc": "2026-04-06T00:00:00+00:00"}],
            }, path)

            full_season = [appearance("1", "2026-04-05"),
                           appearance("1", "2026-09-10")]
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=full_season) as fake:
                report = pitchers.build_log_store(
                    ["1"], "2026", path, refresh=True,
                    now=datetime(2026, 9, 11, tzinfo=timezone.utc))

            fake.assert_called_once()
            self.assertEqual(report["processed"], 1)
            logs = pitchers.read_logs(path)
            dates = sorted(a["date"] for a in logs["1"] if a.get("date"))
            self.assertEqual(dates, ["2026-04-05", "2026-09-10"])


class TestEmptyMarkerIsNotPermanent(unittest.TestCase):
    def test_empty_season_marker_followed_by_first_appearance_is_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            # A legacy empty marker exactly as the pre-fix code always wrote
            # it -- no checked_utc, because that field did not exist before
            # this change. This is what every already-injured/not-yet-debuted
            # pitcher looks like in the real store today.
            pitchers.write_logs({
                "7": [{"person_id": 7, "season": "2026", "date": None,
                      "empty": True}],
            }, path)

            debut = appearance("7", "2026-09-15")
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=[debut]) as fake:
                pitchers.build_log_store(
                    ["7"], "2026", path, refresh=True,
                    now=datetime(2026, 9, 16, tzinfo=timezone.utc))

            fake.assert_called_once()
            logs = pitchers.read_logs(path)
            dates = [a["date"] for a in logs["7"] if a.get("date")]
            self.assertEqual(dates, ["2026-09-15"])


class TestNoDuplicationAcrossRepeatedRefreshes(unittest.TestCase):
    def test_repeated_refresh_does_not_duplicate_appearances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            first_pull = [appearance("1", "2026-04-05"),
                         appearance("1", "2026-04-11")]
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=first_pull):
                pitchers.build_log_store(
                    ["1"], "2026", path, refresh=True,
                    now=datetime(2026, 4, 12, tzinfo=timezone.utc))

            # A second refresh, >20h later, whose cumulative season log
            # repeats both prior games (as the real endpoint always returns
            # the full season) plus one genuinely new one.
            second_pull = first_pull + [appearance("1", "2026-04-16")]
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=second_pull):
                report = pitchers.build_log_store(
                    ["1"], "2026", path, refresh=True,
                    now=datetime(2026, 4, 13, tzinfo=timezone.utc))

            self.assertEqual(report["processed"], 1)
            logs = pitchers.read_logs(path)
            dates = [a["date"] for a in logs["1"] if a.get("date")]
            self.assertEqual(sorted(dates),
                             ["2026-04-05", "2026-04-11", "2026-04-16"])
            self.assertEqual(len(dates), len(set(dates)),
                             "a repeated refresh must not duplicate a row")


class TestFailurePreservesCacheAndCoverage(unittest.TestCase):
    def test_provider_failure_preserves_cache_and_does_not_advance_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            pitchers.write_logs({
                "1": [appearance("1", "2026-04-05"),
                      {"person_id": 1, "season": "2026", "date": None,
                       "empty": False,
                       "checked_utc": "2026-04-06T00:00:00+00:00"}],
            }, path)

            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   side_effect=MLBError("HTTP 500")):
                report = pitchers.build_log_store(
                    ["1"], "2026", path, refresh=True,
                    now=datetime(2026, 9, 1, tzinfo=timezone.utc))

            self.assertEqual(report["failed"], 1)
            self.assertEqual(report["processed"], 0)
            logs = pitchers.read_logs(path)
            dates = sorted(a["date"] for a in logs["1"] if a.get("date"))
            self.assertEqual(dates, ["2026-04-05"], "cache must be untouched")
            marker = pitchers.coverage_marker(logs["1"], "2026")
            self.assertIsNotNone(marker)
            self.assertEqual(marker["checked_utc"], "2026-04-06T00:00:00+00:00",
                            "coverage state must not advance on a failed fetch")

            # Retryable: a later run whose fetch succeeds picks the pitcher
            # right back up, because the marker was never advanced above.
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=[appearance("1", "2026-04-05"),
                                                appearance("1", "2026-09-01")]) as fake:
                pitchers.build_log_store(
                    ["1"], "2026", path, refresh=True,
                    now=datetime(2026, 9, 2, tzinfo=timezone.utc))

            fake.assert_called_once()
            logs2 = pitchers.read_logs(path)
            dates2 = sorted(a["date"] for a in logs2["1"] if a.get("date"))
            self.assertIn("2026-09-01", dates2)


class TestNoLookaheadThroughRefresh(unittest.TestCase):
    def test_refresh_produced_rows_still_respect_the_asof_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            season_log = [appearance("1", "2026-04-05"),
                         appearance("1", "2026-09-10")]
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=season_log):
                pitchers.build_log_store(
                    ["1"], "2026", path, refresh=True,
                    now=datetime(2026, 9, 11, tzinfo=timezone.utc))

            logs = pitchers.read_logs(path)
            # As of a date before the September start, only the April game
            # may be visible, and the refresh's own bookkeeping marker
            # (date=None) must never appear as an "appearance".
            prior = pitchers.appearances_before(logs, "1", "2026-05-01")
            self.assertEqual([a["date"] for a in prior], ["2026-04-05"])

            features = pitchers.pitcher_features(logs, "1", "2026-05-01",
                                                 fip_constant=3.1)
            self.assertEqual(features["sp_appearances"], 1)


class TestRefreshBudget(unittest.TestCase):
    def test_max_refetch_per_run_defers_the_least_urgent_and_stays_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            now = datetime(2026, 9, 11, tzinfo=timezone.utc)
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=[appearance("1", "2026-04-05")]):
                report = pitchers.build_log_store(
                    ["1", "2", "3"], "2026", path, refresh=True,
                    now=now, max_refetch_per_run=1)

            self.assertEqual(report["attempted"], 1)
            self.assertEqual(report["deferred_by_budget"], 2)
            logs = pitchers.read_logs(path)
            # Exactly one of the three ever got a marker written this run.
            checked = [p for p in ("1", "2", "3")
                      if pitchers.coverage_marker(logs.get(p, []), "2026")]
            self.assertEqual(len(checked), 1)


class TestSnapshotBeforeOverwrite(unittest.TestCase):
    def test_a_mutating_refresh_snapshots_the_pre_existing_store_first(self):
        from src.pipeline import store_archive

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            pitchers.write_logs({"1": [appearance("1", "2026-04-05")]}, path)
            original_bytes = path.read_bytes()

            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=[appearance("1", "2026-04-05"),
                                                appearance("1", "2026-09-10")]):
                pitchers.build_log_store(
                    ["1"], "2026", path, refresh=True,
                    now=datetime(2026, 9, 11, tzinfo=timezone.utc))

            segs = store_archive.segments(path)
            self.assertEqual(len(segs), 1,
                            "exactly one snapshot segment for the one mutating run")
            import gzip
            with gzip.open(segs[0], "rb") as fh:
                snapshotted = fh.read()
            self.assertEqual(snapshotted, original_bytes,
                            "the snapshot must be byte-identical to the "
                            "pre-overwrite store")
            # The live store itself now has the new appearance -- the
            # snapshot preserved the OLD content without blocking the write.
            logs = pitchers.read_logs(path)
            dates = sorted(a["date"] for a in logs["1"] if a.get("date"))
            self.assertEqual(dates, ["2026-04-05", "2026-09-10"])


if __name__ == "__main__":
    unittest.main()
