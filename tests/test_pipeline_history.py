"""Tests for src/pipeline/history.py. No network -- mlb.fetch_results is patched.

The behaviours worth protecting: re-ingesting never duplicates, a dead run resumes from
durable state, and an unfetched gap stays distinguishable from a genuine off day.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import history
from src.pipeline.history import HistoryError
from src.providers import mlb


def final_game(pk, away="TOR", home="CWS", away_score=1, home_score=2,
               day="2025-07-09"):
    return {
        "game_pk": pk, "date": day, "start_time_utc": f"{day}T18:10:00Z",
        "venue": "Rate Field", "state": "final",
        "away_team": away, "home_team": home,
        "away_team_id": 141, "home_team_id": 145,
        "away_probable": "Eric Lauer", "home_probable": "Adrian Houser",
        "away_probable_id": 1, "home_probable_id": 2,
        "away_score": away_score, "home_score": home_score,
        "winner": home if home_score > away_score else away,
        "home_won": 1 if home_score > away_score else 0,
        "total_runs": away_score + home_score,
        "run_differential": abs(home_score - away_score),
        "double_header": "N", "game_number": 1,
    }


def results(day, final=(), pending=0, cancelled=0):
    return {
        "date": day, "final": list(final), "pending": [], "cancelled": [],
        "summary": {"total": len(final) + pending + cancelled,
                    "final": len(final), "pending": pending,
                    "cancelled": cancelled},
    }


class TempStore:
    """Give each test its own store and manifest paths."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.store = base / "results.csv"
        self.manifest = base / "results.manifest.json"
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


class TestIdempotency(unittest.TestCase):
    def test_reingesting_the_same_date_does_not_duplicate(self):
        payload = results("2025-07-09", [final_game(1), final_game(2, away="NYY",
                                                                  home="BOS")])
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=payload):
                history.ingest_range("2025-07-09", "2025-07-09",
                                     t.store, t.manifest, resume=False)
                history.ingest_range("2025-07-09", "2025-07-09",
                                     t.store, t.manifest, resume=False)
            stored = history.read_results(t.store)
        self.assertEqual(len(stored), 2)

    def test_reingesting_updates_rather_than_appends(self):
        first = results("2025-07-09", [final_game(1, home_score=2)])
        second = results("2025-07-09", [final_game(1, home_score=9)])
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=first):
                history.ingest_range("2025-07-09", "2025-07-09", t.store,
                                     t.manifest, resume=False)
            with mock.patch.object(mlb, "fetch_results", return_value=second):
                history.ingest_range("2025-07-09", "2025-07-09", t.store,
                                     t.manifest, resume=False)
            stored = history.read_results(t.store)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored["1"]["home_score"], "9")

    def test_ingest_date_reports_added_versus_updated(self):
        store, manifest = {}, {}
        payload = results("2025-07-09", [final_game(1)])
        with mock.patch.object(mlb, "fetch_results", return_value=payload):
            first = history.ingest_date("2025-07-09", store, manifest)
            second = history.ingest_date("2025-07-09", store, manifest)
        self.assertEqual((first["added"], first["updated"]), (1, 0))
        self.assertEqual((second["added"], second["updated"]), (0, 1))

    def test_only_final_games_enter_the_store(self):
        # Pending games carry partial scores that look exactly like final ones.
        payload = results("2025-07-09", [final_game(1)], pending=5, cancelled=1)
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=payload):
                history.ingest_range("2025-07-09", "2025-07-09", t.store,
                                     t.manifest, resume=False)
            stored = history.read_results(t.store)
            manifest = history.read_manifest(t.manifest)
        self.assertEqual(len(stored), 1)
        # But the manifest records that 7 games existed, so coverage stays honest.
        self.assertEqual(manifest["2025-07-09"]["total"], 7)
        self.assertEqual(manifest["2025-07-09"]["pending"], 5)


class TestResumability(unittest.TestCase):
    def test_missing_dates_excludes_already_fetched(self):
        with TempStore() as t:
            history.write_manifest({"2025-07-01": {"total": 5, "final": 5,
                                                   "pending": 0, "cancelled": 0}},
                                   t.manifest)
            missing = history.missing_dates("2025-07-01", "2025-07-03", t.manifest)
        self.assertEqual(missing, ["2025-07-02", "2025-07-03"])

    def test_resume_skips_completed_dates(self):
        with TempStore() as t:
            history.write_manifest({"2025-07-01": {"total": 0, "final": 0,
                                                   "pending": 0, "cancelled": 0}},
                                   t.manifest)
            payload = results("2025-07-02", [final_game(1)])
            with mock.patch.object(mlb, "fetch_results",
                                   return_value=payload) as fake:
                report = history.ingest_range("2025-07-01", "2025-07-02",
                                              t.store, t.manifest, resume=True)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(report["skipped_already_done"], 1)
        self.assertEqual(report["attempted"], 1)

    def test_resume_false_refetches_everything(self):
        with TempStore() as t:
            history.write_manifest({"2025-07-01": {"total": 0, "final": 0,
                                                   "pending": 0, "cancelled": 0}},
                                   t.manifest)
            payload = results("2025-07-01", [final_game(1)])
            with mock.patch.object(mlb, "fetch_results",
                                   return_value=payload) as fake:
                history.ingest_range("2025-07-01", "2025-07-02", t.store,
                                     t.manifest, resume=False)
        self.assertEqual(fake.call_count, 2)

    def test_periodic_flush_preserves_work_when_a_run_dies(self):
        # The scenario: a long backfill dies partway. Without flushing, everything
        # collected so far is lost with the process.
        days = [f"2025-07-{d:02d}" for d in range(1, 8)]
        payloads = [results(d, [final_game(i)]) for i, d in enumerate(days, start=1)]

        def side_effect(day, timeout=20):
            if day == "2025-07-06":
                raise KeyboardInterrupt("simulated interruption")
            return payloads[days.index(day)]

        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", side_effect=side_effect):
                with self.assertRaises(KeyboardInterrupt):
                    history.ingest_range("2025-07-01", "2025-07-07", t.store,
                                         t.manifest, resume=False, flush_every=2)
            stored = history.read_results(t.store)
        # Flushed at 2 and 4; the 5th was in memory when the interrupt hit.
        self.assertGreaterEqual(len(stored), 4)

    def test_a_failing_date_does_not_abort_the_run(self):
        def side_effect(day, timeout=20):
            if day == "2025-07-02":
                raise mlb.MLBError("HTTP 500")
            return results(day, [final_game(int(day[-2:]))])

        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", side_effect=side_effect):
                report = history.ingest_range("2025-07-01", "2025-07-03",
                                              t.store, t.manifest, resume=False)
        self.assertEqual(report["processed"], 2)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["errors"][0]["date"], "2025-07-02")

    def test_a_failed_date_is_retried_on_the_next_resume(self):
        # It must not be marked done, or the gap becomes permanent.
        def failing(day, timeout=20):
            raise mlb.MLBError("HTTP 500")

        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", side_effect=failing):
                history.ingest_range("2025-07-01", "2025-07-01", t.store,
                                     t.manifest, resume=False)
            still_missing = history.missing_dates("2025-07-01", "2025-07-01",
                                                  t.manifest)
        self.assertEqual(still_missing, ["2025-07-01"])


class TestCoverageHonesty(unittest.TestCase):
    """The manifest exists so an off day and an unfetched gap stay distinguishable."""

    def test_an_off_day_is_recorded_with_zero_games(self):
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results",
                                   return_value=results("2025-07-15")):
                history.ingest_range("2025-07-15", "2025-07-15", t.store,
                                     t.manifest, resume=False)
            manifest = history.read_manifest(t.manifest)
        self.assertIn("2025-07-15", manifest)
        self.assertEqual(manifest["2025-07-15"]["total"], 0)

    def test_report_separates_off_days_from_unfetched_gaps(self):
        with TempStore() as t:
            # 07-01 played, 07-02 never fetched, 07-03 a real off day.
            history.write_manifest({
                "2025-07-01": {"total": 5, "final": 5, "pending": 0, "cancelled": 0},
                "2025-07-03": {"total": 0, "final": 0, "pending": 0, "cancelled": 0},
            }, t.manifest)
            report = history.quality_report(t.store, t.manifest)
        self.assertEqual(report["off_days"], 1)
        self.assertEqual(report["gap_count"], 1)
        self.assertEqual(report["unfetched_gaps_in_span"], ["2025-07-02"])

    def test_no_manifest_reports_unknown_coverage_not_zero(self):
        with TempStore() as t:
            report = history.quality_report(t.store, t.manifest)
        self.assertIn("unknown", report["note"])

    def test_corrupt_manifest_raises_rather_than_silently_resetting(self):
        # Treating a corrupt manifest as empty would re-fetch everything and,
        # worse, make gaps look like fresh work.
        with TempStore() as t:
            t.manifest.parent.mkdir(parents=True, exist_ok=True)
            t.manifest.write_text("{not json}")
            with self.assertRaises(HistoryError):
                history.read_manifest(t.manifest)

    def test_report_counts_dates_with_unresolved_games(self):
        with TempStore() as t:
            history.write_manifest({
                "2025-07-01": {"total": 5, "final": 4, "pending": 1, "cancelled": 0},
            }, t.manifest)
            report = history.quality_report(t.store, t.manifest)
        self.assertEqual(report["dates_with_unresolved_games"], 1)


class TestSanityChecks(unittest.TestCase):
    def write(self, path, rows):
        store = {str(r["game_pk"]): r for r in rows}
        history.write_results(store, path)

    def test_clean_store_has_no_violations(self):
        with TempStore() as t:
            self.write(t.store, [final_game(1), final_game(2, away_score=7,
                                                           home_score=3)])
            self.assertEqual(history.sanity_checks(t.store), [])

    def test_tied_final_is_flagged(self):
        with TempStore() as t:
            bad = final_game(1, away_score=3, home_score=3)
            bad["winner"] = "CWS"
            self.write(t.store, [bad])
            problems = history.sanity_checks(t.store)
        self.assertTrue(any("tied" in p for p in problems))

    def test_winner_disagreeing_with_score_is_flagged(self):
        with TempStore() as t:
            bad = final_game(1, away_score=1, home_score=5)
            bad["winner"] = "TOR"  # away team, but home won
            self.write(t.store, [bad])
            problems = history.sanity_checks(t.store)
        self.assertTrue(any("disagrees with score" in p for p in problems))

    def test_total_runs_mismatch_is_flagged(self):
        with TempStore() as t:
            bad = final_game(1, away_score=2, home_score=3)
            bad["total_runs"] = 99
            self.write(t.store, [bad])
            self.assertTrue(any("total_runs" in p
                                for p in history.sanity_checks(t.store)))

    def test_home_won_disagreeing_with_score_is_flagged(self):
        with TempStore() as t:
            bad = final_game(1, away_score=1, home_score=5)
            bad["home_won"] = 0
            self.write(t.store, [bad])
            self.assertTrue(any("home_won" in p
                                for p in history.sanity_checks(t.store)))

    def test_run_differential_mismatch_is_flagged(self):
        with TempStore() as t:
            bad = final_game(1, away_score=1, home_score=5)
            bad["run_differential"] = 1
            self.write(t.store, [bad])
            self.assertTrue(any("run_differential" in p
                                for p in history.sanity_checks(t.store)))


class TestPersistence(unittest.TestCase):
    def test_round_trip_preserves_every_column(self):
        with TempStore() as t:
            game = final_game(1)
            history.write_results({"1": game}, t.store)
            back = history.read_results(t.store)
        for column in history.RESULT_COLUMNS:
            self.assertIn(column, back["1"])
        self.assertEqual(back["1"]["winner"], "CWS")

    def test_rows_are_sorted_for_a_stable_diff(self):
        with TempStore() as t:
            history.write_results({
                "9": final_game(9, day="2025-07-10"),
                "1": final_game(1, day="2025-07-09"),
            }, t.store)
            lines = t.store.read_text().strip().splitlines()
        self.assertIn("2025-07-09", lines[1])
        self.assertIn("2025-07-10", lines[2])

    def test_missing_store_reads_as_empty(self):
        self.assertEqual(history.read_results("/nonexistent/results.csv"), {})

    def test_manifest_is_written_sorted(self):
        with TempStore() as t:
            history.write_manifest({
                "2025-07-03": {"total": 1, "final": 1, "pending": 0, "cancelled": 0},
                "2025-07-01": {"total": 1, "final": 1, "pending": 0, "cancelled": 0},
            }, t.manifest)
            data = json.loads(t.manifest.read_text())
        self.assertEqual(list(data["dates"]), ["2025-07-01", "2025-07-03"])


if __name__ == "__main__":
    unittest.main()
