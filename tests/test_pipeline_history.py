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
               day="2025-07-09", game_type="R"):
    return {
        "game_pk": pk, "date": day, "start_time_utc": f"{day}T18:10:00Z",
        "venue": "Rate Field", "state": "final", "game_type": game_type,
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


class TestGameTypeFiltering(unittest.TestCase):
    """Spring training is real baseball but not the process being modeled.

    Split squads, minor-league rosters, pitchers on artificial pitch counts, and
    no competitive incentive. Training on it would teach the model from a
    different sport wearing the same uniforms.
    """

    def test_spring_training_games_are_not_stored(self):
        payload = results("2025-03-22", [
            final_game(1, game_type="S"),
            final_game(2, game_type="S", away="NYY", home="BOS"),
        ])
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=payload):
                history.ingest_range("2025-03-22", "2025-03-22", t.store,
                                     t.manifest, resume=False)
            stored = history.read_results(t.store)
        self.assertEqual(len(stored), 0)

    def test_skipped_spring_games_are_still_counted_in_the_manifest(self):
        # Coverage must stay honest: the date was fetched and DID have games,
        # they just were not the kind we train on. That is different from an
        # off day and different again from an unfetched gap.
        payload = results("2025-03-22", [final_game(1, game_type="S")])
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=payload):
                history.ingest_range("2025-03-22", "2025-03-22", t.store,
                                     t.manifest, resume=False)
            manifest = history.read_manifest(t.manifest)
        entry = manifest["2025-03-22"]
        self.assertEqual(entry["total"], 1)
        self.assertEqual(entry["stored"], 0)
        self.assertEqual(entry["skipped_game_type"], 1)

    def test_regular_season_games_are_stored(self):
        payload = results("2025-07-09", [final_game(1, game_type="R")])
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=payload):
                history.ingest_range("2025-07-09", "2025-07-09", t.store,
                                     t.manifest, resume=False)
            self.assertEqual(len(history.read_results(t.store)), 1)

    def test_mixed_date_stores_only_the_regular_season_game(self):
        payload = results("2025-03-27", [
            final_game(1, game_type="S"),
            final_game(2, game_type="R", away="NYY", home="BOS"),
        ])
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=payload):
                history.ingest_range("2025-03-27", "2025-03-27", t.store,
                                     t.manifest, resume=False)
            stored = history.read_results(t.store)
        self.assertEqual(list(stored), ["2"])

    def test_filter_can_be_widened_deliberately(self):
        payload = results("2025-03-22", [final_game(1, game_type="S")])
        store, manifest = {}, {}
        with mock.patch.object(mlb, "fetch_results", return_value=payload):
            history.ingest_date("2025-03-22", store, manifest,
                                game_types=frozenset({"R", "S"}))
        self.assertEqual(len(store), 1)

    def test_none_filter_stores_every_game_type(self):
        payload = results("2025-03-22", [final_game(1, game_type="S")])
        store, manifest = {}, {}
        with mock.patch.object(mlb, "fetch_results", return_value=payload):
            history.ingest_date("2025-03-22", store, manifest, game_types=None)
        self.assertEqual(len(store), 1)


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

    def test_a_date_fetched_before_its_games_finished_is_retried(self):
        # REGRESSION. The hole this store exists to prevent, in its subtlest form.
        # Fetch a date at 9pm with a west-coast game still in the seventh: the
        # finished games are stored, the unfinished one is not, and the date lands
        # in the manifest. Resume then treats the date as DONE forever. The date is
        # present, the coverage count is full, and the game is simply gone.
        with TempStore() as t:
            history.write_manifest({
                "2025-07-01": {"total": 15, "final": 14, "pending": 1,
                               "cancelled": 0},
            }, t.manifest)
            missing = history.missing_dates("2025-07-01", "2025-07-01", t.manifest)
        self.assertEqual(missing, ["2025-07-01"])

    def test_a_cancelled_game_does_not_make_a_date_retry_forever(self):
        # The other half of the fix. A postponed game is terminal for the date it
        # was scheduled on -- it reappears as a makeup elsewhere. Retrying those
        # would mean resume never converges and re-fetches the same 121 dates on
        # every run.
        with TempStore() as t:
            history.write_manifest({
                "2025-07-01": {"total": 15, "final": 14, "pending": 0,
                               "cancelled": 1},
            }, t.manifest)
            missing = history.missing_dates("2025-07-01", "2025-07-01", t.manifest)
        self.assertEqual(missing, [])

    def test_resume_refetches_a_pending_date_and_stores_the_finished_game(self):
        # End to end: the second run must actually recover the missing result.
        first = results("2025-07-01", [final_game(1)], pending=1)
        second = results("2025-07-01", [final_game(1), final_game(2, away="NYY",
                                                                 home="BOS")])
        with TempStore() as t:
            with mock.patch.object(mlb, "fetch_results", return_value=first):
                history.ingest_range("2025-07-01", "2025-07-01", t.store,
                                     t.manifest, resume=False)
            self.assertEqual(len(history.read_results(t.store)), 1)
            with mock.patch.object(mlb, "fetch_results", return_value=second) as fake:
                history.ingest_range("2025-07-01", "2025-07-01", t.store,
                                     t.manifest, resume=True)
            self.assertEqual(fake.call_count, 1)
            stored = history.read_results(t.store)
            manifest = history.read_manifest(t.manifest)
        self.assertEqual(sorted(stored), ["1", "2"])
        self.assertEqual(manifest["2025-07-01"]["pending"], 0)

    def test_unfinished_dates_lists_only_pending_dates(self):
        with TempStore() as t:
            history.write_manifest({
                "2025-07-01": {"total": 1, "final": 0, "pending": 1, "cancelled": 0},
                "2025-07-02": {"total": 1, "final": 0, "pending": 0, "cancelled": 1},
                "2025-07-03": {"total": 1, "final": 1, "pending": 0, "cancelled": 0},
            }, t.manifest)
            self.assertEqual(history.unfinished_dates(t.manifest), {"2025-07-01"})

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


class TestDurableWrites(unittest.TestCase):
    """A flush that dies mid-write must not truncate what was already collected."""

    class Explodes:
        def __str__(self):
            raise RuntimeError("serialisation blew up mid-write")

    def test_a_crash_mid_write_leaves_the_previous_store_intact(self):
        # REGRESSION. The store is rewritten whole on every flush. Written in
        # place, a process killed partway through leaves a truncated CSV beside a
        # manifest that still claims those dates were fetched: coverage reads as
        # complete, the rows are gone, and resume never asks again.
        with TempStore() as t:
            history.write_results({"1": final_game(1), "2": final_game(2)}, t.store)
            good = history.read_results(t.store)

            poisoned = dict(good)
            poisoned["3"] = {**final_game(3), "venue": self.Explodes()}
            with self.assertRaises(RuntimeError):
                history.write_results(poisoned, t.store)

            self.assertEqual(history.read_results(t.store), good)
            self.assertFalse(Path(str(t.store) + ".tmp").exists())

    def test_a_crash_mid_manifest_write_leaves_the_previous_manifest_intact(self):
        with TempStore() as t:
            entry = {"total": 1, "final": 1, "pending": 0, "cancelled": 0}
            history.write_manifest({"2025-07-01": entry}, t.manifest)
            with mock.patch.object(history.json, "dumps",
                                   side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    history.write_manifest({"2025-07-02": entry}, t.manifest)
            self.assertEqual(list(history.read_manifest(t.manifest)), ["2025-07-01"])


class TestGapClassification(unittest.TestCase):
    """251 loose dates say nothing; a run with a date range on it says everything."""

    def test_in_season_holes_are_separated_from_off_seasons(self):
        manifest = {
            "2024-07-01": {"total": 15, "final": 15, "pending": 0, "cancelled": 0},
            # 07-02 and 07-03 missing: a hole in the middle of a season.
            "2024-07-04": {"total": 15, "final": 15, "pending": 0, "cancelled": 0},
            # 07-05..12-31 missing: winter, nobody asked.
            "2025-01-01": {"total": 0, "final": 0, "pending": 0, "cancelled": 0},
        }
        runs = history.gap_runs(manifest)
        self.assertEqual(len(runs), 2)
        self.assertEqual((runs[0]["start"], runs[0]["end"], runs[0]["days"]),
                         ("2024-07-02", "2024-07-03", 2))
        self.assertEqual(runs[0]["classification"], "in_season")
        self.assertEqual(runs[1]["classification"], "between_seasons")

    def test_a_run_abutting_a_season_start_is_flagged_for_review(self):
        # A season that opens abroad (Tokyo, Seoul) puts real regular-season games
        # before the fetched window. Such a run classifies as between_seasons and
        # would be dismissed as winter unless the boundary is called out.
        manifest = {
            "2024-11-01": {"total": 0, "final": 0, "pending": 0, "cancelled": 0},
            "2025-03-20": {"total": 11, "final": 11, "pending": 0, "cancelled": 0},
        }
        run = history.gap_runs(manifest)[0]
        self.assertEqual(run["classification"], "between_seasons")
        self.assertTrue(run["touches_season_start"])

    def test_report_splits_retryable_pending_from_terminal_cancellations(self):
        with TempStore() as t:
            history.write_manifest({
                "2025-07-01": {"total": 5, "final": 4, "pending": 1, "cancelled": 0},
                "2025-07-02": {"total": 5, "final": 4, "pending": 0, "cancelled": 1},
            }, t.manifest)
            report = history.quality_report(t.store, t.manifest)
        self.assertEqual(report["dates_with_unresolved_games"], 2)
        self.assertEqual(report["dates_still_pending"], ["2025-07-01"])
        self.assertEqual(report["dates_cancelled_only"], 1)


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
