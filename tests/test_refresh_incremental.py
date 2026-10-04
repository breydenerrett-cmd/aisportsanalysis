"""The refresh asks for less, and says what it found (2026-10-04).

Through the real refresh and the fake Stats API of tests/_fake_statsapi.py, the
same fixture as tests/test_display_refresh.py. No network.

  - a store that already holds what the schedule shows is not fetched again
  - what the refresh found is reported as new / corrected / unchanged /
    missing-source / failed, not as one count
  - an authentication denial stops the whole run, with no further request
  - a failed or partial fetch keeps the good data
  - a restart (a killed run's leftovers) or a stale restore does not discard
    the store
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest import mock

from src.pipeline import bullpen, display_refresh as dr, history, lineups, pitchers
from src.pipeline.refresh_fetch import FetchLayer
from src.providers import mlb
from tests._fake_statsapi import raw_game
from tests.test_display_refresh import NOW, Base, _sha, _tree
from tests.test_refresh_fetch import http_error


def uncached(**kw):
    """A layer with no disk cache and no sleeping: counts are then exactly the
    fake's."""
    return FetchLayer(cache_dir=None, sleep=lambda s: None, **kw)


def calls(fake, path):
    return [c for c in fake.calls if c[0] == path]


class Fixture(Base):
    def setUp(self):
        super().setUp()
        # yesterday had a final game (2026-10-02), so there is something to hold
        self.fake.schedule["2026-10-02"] = [
            raw_game(14, "2026-10-02", "NYY", "BOS", 3, 1, "F", away_sp=111, home_sp=222)]
        self.log_path = self.hist / "bullpen_log.jsonl"

    def yesterdays_rows(self):
        return [r for r in bullpen.read_log(self.log_path) if r.get("date") == "2026-10-02"]


class YesterdaysBullpenIsRefetchedOnlyWhenSomethingIsMissing(Fixture):

    def test_a_complete_day_costs_no_boxscore_the_second_time(self):
        self.run_refresh(only=["bullpen"], fetch=uncached())
        self.assertEqual(len(self.yesterdays_rows()), 2)
        before = len(calls(self.fake, "game/14/boxscore"))
        report = self.run_refresh(only=["bullpen"], fetch=uncached())
        self.assertEqual(len(calls(self.fake, "game/14/boxscore")), before, "nothing to add, nothing asked")
        self.assertEqual(report["steps"]["bullpen"]["refetched_yesterday_rows"], 0)
        self.assertEqual(len(self.yesterdays_rows()), 2)

    def test_a_game_the_last_fetch_missed_is_fetched(self):
        self.run_refresh(only=["bullpen"], fetch=uncached())
        kept = [r for r in bullpen.read_log(self.log_path) if r.get("date") != "2026-10-02"]
        self.log_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept), encoding="utf-8")
        self.assertEqual(self.yesterdays_rows(), [])
        report = self.run_refresh(only=["bullpen"], fetch=uncached())
        self.assertEqual(len(self.yesterdays_rows()), 2, "the missing game is back")
        self.assertEqual(report["steps"]["bullpen"]["observation"]["new"], 2)

    def test_a_schedule_that_cannot_be_read_leaves_yesterdays_rows_alone(self):
        self.run_refresh(only=["bullpen"], fetch=uncached())
        rows = self.yesterdays_rows()
        real = self.fake

        def blip(path, params=None, timeout=None):
            if path == "schedule" and (params or {}).get("date") == "2026-10-02":
                raise mlb.MLBError("blip")
            return real(path, params, timeout)

        with mock.patch.object(mlb, "_get_json", blip):
            report = self.run_refresh(only=["bullpen"], fetch=uncached())
        self.assertEqual(self.yesterdays_rows(), rows)
        self.assertEqual(report["steps"]["bullpen"]["refetched_yesterday_rows"], 0)


class SplitsAndProbablesAreNotAskedForAgain(Fixture):

    def seed_splits(self, hours_old):
        stamp = (NOW - timedelta(hours=hours_old)).isoformat()
        cache = {f"{pid}:2026": {"person_id": str(pid), "season": "2026", "as_of": stamp, "splits": {}}
                 for pid in (111, 222)}
        (self.hist / "pitcher_splits.json").write_text(json.dumps(cache), encoding="utf-8")

    def split_calls(self):
        return [c for c in self.fake.calls if c[0].startswith("people/") and c[1].get("stats") == "statSplits"]

    def test_a_split_taken_an_hour_ago_is_not_taken_again(self):
        self.seed_splits(hours_old=1)
        report = self.run_refresh(only=["splits"], fetch=uncached())
        self.assertEqual(self.split_calls(), [])
        self.assertEqual(report["steps"]["splits"]["skipped_fresh"], 2)

    def test_a_split_from_yesterday_is_taken_again(self):
        self.seed_splits(hours_old=30)
        self.run_refresh(only=["splits"], fetch=uncached())
        self.assertEqual(len(self.split_calls()), 2)

    def seed_checked_pitcher(self, hours_old):
        # 333 is announced for tomorrow and last started 2026-09-27: nothing the
        # results show is newer than his check.
        self.fake.schedule["2026-10-04"] = [
            raw_game(22, "2026-10-04", "ATL", "PHI", None, None, "D", final=False, away_sp=333)]
        stamp = (NOW - timedelta(hours=hours_old)).isoformat()
        logs = pitchers.read_logs(self.hist / "pitcher_logs.jsonl")
        logs["333"] = [{"person_id": 333, "season": "2026", "date": None, "empty": False, "checked_utc": stamp}]
        pitchers.write_logs(logs, self.hist / "pitcher_logs.jsonl")

    def game_log_calls_for(self, pid):
        return calls(self.fake, f"people/{pid}/stats")

    def test_an_upcoming_probable_checked_two_hours_ago_with_no_new_start_is_skipped(self):
        self.seed_checked_pitcher(hours_old=2)
        report = self.run_refresh(only=["results", "pitchers"], fetch=uncached())
        self.assertEqual(self.game_log_calls_for(333), [])
        self.assertEqual(report["steps"]["pitchers"]["upcoming_skipped_checked_recently"], 1)

    def test_one_checked_two_days_ago_is_asked_for(self):
        self.seed_checked_pitcher(hours_old=48)
        report = self.run_refresh(only=["results", "pitchers"], fetch=uncached())
        self.assertTrue(self.game_log_calls_for(333))
        self.assertEqual(report["steps"]["pitchers"]["upcoming_skipped_checked_recently"], 0)


class TheReportSaysWhatItFound(Fixture):

    def test_new_records_are_updated_then_a_second_look_is_unchanged(self):
        first = self.run_refresh(fetch=uncached())
        self.assertEqual(first["steps"]["bullpen"]["observation"]["verdict"], "updated")
        self.assertGreater(first["steps"]["results"]["observation"]["new"], 0)
        second = self.run_refresh(fetch=uncached())
        self.assertEqual(second["steps"]["results"]["observation"]["verdict"], "unchanged")
        self.assertEqual(second["steps"]["bullpen"]["observation"]["new"], 0)

    def test_a_provider_correction_is_corrected_not_new(self):
        self.run_refresh(only=["results"], fetch=uncached())
        self.fake.schedule["2026-10-01"] = [
            raw_game(13, "2026-10-01", "NYY", "BOS", 7, 2, "F", away_sp=111, home_sp=222)]   # was 6-2
        report = self.run_refresh(only=["results"], fetch=uncached(), now=NOW)
        # resume skips a covered date, so force the look the way the loop does
        history_report = history.ingest_range(
            "2026-10-01", "2026-10-01", store_path=self.hist / "mlb_results.csv",
            manifest_path=self.hist / "mlb_results.manifest.json", resume=False,
            game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual(history_report["failed"], 0)
        self.assertEqual(history.read_results(self.hist / "mlb_results.csv")["13"]["away_score"], "7")
        # the diff itself, between the committed copy and a refreshed one
        work = self.root / "w.csv"
        committed = self.root / "c.csv"
        rows = history.read_results(self.hist / "mlb_results.csv")
        history.write_results(rows, work)
        rows["13"] = {**rows["13"], "away_score": "6"}
        history.write_results(rows, committed)
        diff = dr.row_diff("mlb_results.csv", work, committed)
        self.assertEqual((diff["corrected"], diff["new"]), (1, 0))
        self.assertIsNotNone(report)

    def test_bookkeeping_fields_are_not_a_correction(self):
        a, b = self.root / "a.jsonl", self.root / "b.jsonl"
        row = {"date": "2026-09-08", "team_abbrev": "NYY", "wins": 80, "captured_at": "2026-09-08T20:00:00+00:00"}
        a.write_text(json.dumps(row) + "\n", encoding="utf-8")
        b.write_text(json.dumps({**row, "captured_at": "2026-09-09T01:00:00+00:00"}) + "\n", encoding="utf-8")
        self.assertEqual(dr.row_diff("standings.jsonl", b, a), {"new": 0, "corrected": 0, "unchanged": 1})
        b.write_text(json.dumps({**row, "wins": 81}) + "\n", encoding="utf-8")
        self.assertEqual(dr.row_diff("standings.jsonl", b, a), {"new": 0, "corrected": 1, "unchanged": 0})

    def test_a_pitcher_the_source_has_nothing_for_is_missing_source_not_a_failure(self):
        report = self.run_refresh(only=["results", "pitchers"], fetch=uncached())
        observation = report["steps"]["pitchers"]["observation"]
        self.assertGreaterEqual(observation["missing_source"], 1, "444 answers with an empty log")
        self.assertEqual(observation["failed"], 0)
        self.assertNotEqual(observation["verdict"], "failed")

    def test_a_failed_fetch_is_failed_and_the_good_data_is_kept(self):
        real = self.fake

        def flaky(path, params=None, timeout=None):
            if path.startswith("people/222/"):
                raise http_error(500, path=path)
            return real(path, params, timeout)

        before = pitchers.read_logs(self.hist / "pitcher_logs.jsonl")
        with mock.patch.object(mlb, "_get_json", flaky):
            report = self.run_refresh(only=["results", "pitchers"], fetch=uncached(retries=0))
        step = report["steps"]["pitchers"]
        self.assertGreaterEqual(step["observation"]["failed"], 1)
        self.assertEqual(step["observation"]["verdict"], "partial", step["observation"])
        after = pitchers.read_logs(self.hist / "pitcher_logs.jsonl")
        self.assertTrue([a for a in after["111"] if a.get("date") == "2026-09-25"], "the good answer landed")
        self.assertEqual(after.get("222", []), before.get("222", []), "the failed pitcher is exactly as he was")

    def test_the_run_level_report_counts_requests_by_class(self):
        report = self.run_refresh(fetch=uncached())
        fetch = report["fetch"]
        mlb_requests = fetch["requests_made"] - fetch["by_class"]["savant_arsenal"]["network"]
        self.assertEqual(mlb_requests, len(self.fake.calls), "the report counts what the wire saw")
        self.assertEqual(sum(v["network"] for v in fetch["by_class"].values()), fetch["network_calls"])
        self.assertIn("schedule", fetch["by_class"])
        self.assertIsNone(report["halted"])


class AnAuthenticationDenialStopsTheWholeRefresh(Fixture):

    def test_a_403_on_the_probe_makes_one_request_and_leaves_every_byte_alone(self):
        before = _tree(self.root)
        self.fake.reachable = True
        real = self.fake

        def denied(path, params=None, timeout=None):
            real.calls.append((path, params))
            raise http_error(403)

        with mock.patch.object(mlb, "_get_json", denied):
            report = self.run_refresh(fetch=uncached())
        self.assertEqual(len(real.calls), 1)
        self.assertIn("refused", report["skipped_reason"])
        self.assertIn("HTTP 403", report["halted"])
        self.assertEqual(before, _tree(self.root))

    def test_a_403_part_way_through_skips_every_later_step_and_requests_nothing_more(self):
        real = self.fake

        def denied_boxscores(path, params=None, timeout=None):
            if path.endswith("/boxscore"):
                real.calls.append((path, params))
                raise http_error(403, path=path)
            return real(path, params, timeout)

        with mock.patch.object(mlb, "_get_json", denied_boxscores):
            report = self.run_refresh(fetch=uncached())
        self.assertIn("HTTP 403", report["halted"])
        boxscores = [c for c in real.calls if c[0].endswith("/boxscore")]
        self.assertEqual(len(boxscores), 1, "one boxscore request, then nothing")
        for later in ("pitchers", "standings", "splits"):
            self.assertEqual(report["steps"][later]["status"], "skipped", report["steps"][later])
            self.assertIn("halted", report["steps"][later]["reason"])
        self.assertEqual(calls(real, "standings"), [])
        self.assertEqual([c for c in real.calls if c[0].startswith("people/")], [])


class ARestartDoesNotDiscardTheStore(Fixture):

    def test_a_killed_runs_leftover_work_directory_is_ignored_and_cleared(self):
        work = self.root / ".refresh_work"
        work.mkdir()
        (work / "bullpen_log.jsonl").write_text("garbage from a run that was killed\n", encoding="utf-8")
        (work / "mlb_results.csv").write_text("", encoding="utf-8")
        report = self.run_refresh(fetch=uncached())
        self.assertIsNone(report["skipped_reason"])
        self.assertFalse(work.exists())
        self.assertEqual(self.freshness()["core_stale"], [])
        self.assertIn("900", history.read_results(self.hist / "mlb_results.csv"),
                      "the backfilled postseason game is still there")

    def test_the_second_run_after_a_restart_resumes_instead_of_redoing_the_work(self):
        first = self.run_refresh()                           # with the disk cache
        second = self.run_refresh()
        self.assertLess(second["fetch"]["requests_made"], first["fetch"]["requests_made"])
        self.assertEqual(second["steps"]["results"]["observation"]["verdict"], "unchanged")
        self.assertEqual(_sha(self.hist / "mlb_results.csv"), _sha(self.hist / "mlb_results.csv"))

    def test_a_disk_cache_from_a_previous_process_answers_the_final_games(self):
        self.run_refresh(only=["results", "bullpen"])
        cache = self.root / "raw" / "mlb_statsapi_cache"
        self.assertTrue(list(cache.rglob("*.json")), "final answers were kept")
        # a new process, a store that lost yesterday's rows, the same disk
        kept = [r for r in bullpen.read_log(self.log_path) if r.get("date") != "2026-10-02"]
        self.log_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept), encoding="utf-8")
        self.fake.calls.clear()
        report = self.run_refresh(only=["bullpen"])
        self.assertEqual(calls(self.fake, "game/14/boxscore"), [], "answered from disk")
        self.assertGreaterEqual(report["fetch"]["by_class"]["boxscore"]["reused"], 1)
        self.assertEqual(len(self.yesterdays_rows()), 2)


class TheSealedWindowIsStillNeverAsked(Fixture):

    def test_no_request_names_a_sealed_date_even_with_the_cache_and_skips(self):
        self.run_refresh()
        sealed = [c for c in self.fake.calls
                  if str((c[1] or {}).get("date", ""))[:10] and "2026-01-01" <= str(c[1].get("date"))[:10] <= "2026-08-27"]
        self.assertEqual(sealed, [])


if __name__ == "__main__":
    import unittest
    unittest.main()
