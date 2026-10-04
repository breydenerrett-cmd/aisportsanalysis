"""Adversarial review of the collection pieces merged 2026-10-04 (red team, same day).

Each class tells the story of one defect the review reproduced in `src/pipeline/refresh_fetch.py` or
`src/pipeline/store_persist.py` (docs/audit/2026-10-04/COLLECTION.md). A test marked `expectedFailure` FAILS today
for the reason in its docstring; when the fix lands the decorator comes off and the test guards it. Tests with no
marker pin behaviour the review confirmed is already right.

No network, no sleeping, no git: the wire is scripted, "git" is a directory behind `reader`, the disk is a temp
directory. Outcomes are never printed: the sealed-window test counts by date only.
"""

from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
import urllib.error
import email.message
from pathlib import Path
from unittest import mock

from src.pipeline import display_refresh as dr
from src.pipeline import history, pitchers
from src.pipeline import store_persist as sp
from src.pipeline.refresh_fetch import (CONSECUTIVE_FAILURE_LIMIT, MAX_RETRIES, MAX_RETRY_AFTER_S, FetchLayer)
from src.providers import mlb, mlb_news, statcast
from tests.test_display_refresh import seed_root


def http_error(code, retry_after=None, path="schedule"):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    cause = urllib.error.HTTPError("https://example.test", code, "x", headers, io.BytesIO(b""))
    cause.close()
    err = mlb.MLBError(f"MLB API returned HTTP {code} for {path}")
    err.__cause__ = cause
    return err


def schedule_day(code, pk=7, away=3, home=2):
    return {"dates": [{"games": [{"gamePk": pk, "status": {"codedGameState": code},
                                  "teams": {"away": {"score": away}, "home": {"score": home}}}]}]}


class Wire:
    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, path, params=None, timeout=None):
        self.calls.append((path, dict(params or {})))
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


class FetchBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "cache"
        self.sleeps = []

    def layer(self, **kw):
        kw.setdefault("sleep", self.sleeps.append)
        kw.setdefault("cache_dir", self.cache)
        return FetchLayer(**kw)

    def ask(self, wire, layer, params=None):
        with mock.patch.object(mlb, "_get_json", wire), layer.install():
            return mlb._get_json("schedule", params or {"date": "2026-10-03"})


class ASettledAnswerOnDiskIsOneThatCannotChange(FetchBase):
    """The layer keeps a schedule day on disk for seven days once every game on it is in a SETTLED state, and never
    asks again inside that window. 'O' (Game Over: the last out, before the official Final) and the suspended codes
    'T'/'U' are in the settled set, but a game in those states DOES change: it becomes 'F', or it resumes."""

    @unittest.expectedFailure
    def test_game_over_and_suspended_days_are_not_pinned_on_disk(self):
        for code in ("O", "T", "U"):
            with self.subTest(code=code):
                self.cache = Path(self._tmp.name) / f"cache_{code}"
                first = Wire(schedule_day(code, away=3, home=2))
                self.ask(first, self.layer())
                later = Wire(schedule_day("F", away=4, home=2))          # upstream moved on within the hour
                got = self.ask(later, self.layer())
                self.assertEqual(len(later.calls), 1, f"a day left in state {code!r} must be asked for again")
                self.assertEqual(got["dates"][0]["games"][0]["status"]["codedGameState"], "F")

    def test_a_day_that_is_all_final_is_served_from_disk_to_a_new_run(self):
        # Pins what already works and is the intent: a Final day is not asked twice by a restart.
        self.ask(Wire(schedule_day("F")), self.layer())
        again = Wire(AssertionError("asked again"))
        self.assertEqual(self.ask(again, self.layer())["dates"][0]["games"][0]["gamePk"], 7)
        self.assertEqual(again.calls, [])


class ARefusedRetryAfterIsStillAFailureNotACrash(FetchBase):

    @unittest.expectedFailure
    def test_a_negative_or_nan_retry_after_header_is_a_failed_fetch_not_a_valueerror(self):
        """`_retry_after` returns min(float(raw), 30): -5 and nan survive (both truthy), and `time.sleep` raises
        ValueError out of `_call`, so the caller sees a ValueError where it handles only the provider's error."""
        for raw in ("-5", "nan"):
            with self.subTest(retry_after=raw):
                wire = Wire(http_error(503, retry_after=raw))
                layer = self.layer(sleep=time.sleep)                    # the real sleep: the injected list hides this
                with self.assertRaises(mlb.MLBError):
                    self.ask(wire, layer)


class RetrySleepsFitTheRunsOwnBudget(FetchBase):

    @unittest.expectedFailure
    def test_the_worst_case_retry_sleep_before_the_run_halts_is_inside_the_refresh_budget(self):
        """Every call that keeps answering 503 with Retry-After: 30 sleeps 30 s twice before it fails, and the run
        halts only after CONSECUTIVE_FAILURE_LIMIT such calls: 6 x 60 s = 360 s, past --max-seconds 270 and past
        the daily loop's `timeout 330`, which then kills the process mid-step instead of the run stopping itself."""
        wire = Wire(http_error(503, retry_after=MAX_RETRY_AFTER_S))
        layer = self.layer()
        with mock.patch.object(mlb, "_get_json", wire), layer.install():
            for n in range(CONSECUTIVE_FAILURE_LIMIT + 2):
                try:
                    mlb._get_json("schedule", {"date": f"2026-10-0{n + 1}"})
                except mlb.MLBError:
                    pass
        self.assertTrue(layer.halted)
        self.assertLessEqual(sum(self.sleeps), dr.DEFAULT_MAX_SECONDS,
                             f"slept {sum(self.sleeps)} s before halting; the budget is {dr.DEFAULT_MAX_SECONDS} s "
                             f"({CONSECUTIVE_FAILURE_LIMIT} calls x {MAX_RETRIES} retries x {MAX_RETRY_AFTER_S} s)")


class ATimeoutOnTheNewsAndSavantSeamsIsAFailureTheReportCounts(FetchBase):

    @unittest.expectedFailure
    def test_a_bare_timeout_is_counted_as_a_failed_fetch(self):
        """`mlb_news._get_json` and `statcast.fetch_arsenal` wrap URLError and HTTPError but not the bare
        TimeoutError a read timeout raises (src/providers/mlb.py says so in its own docstring). The layer catches
        only the provider's error class, so the call is logged with outcome None: counted as a network call, not as
        failed, never in the failure streak, so `failed` reads 0 and a storm of timeouts never halts the run."""
        layer = self.layer()
        news = mock.Mock(side_effect=TimeoutError("timed out"))
        with mock.patch.object(mlb_news, "_get_json", news), layer.install():
            for day in range(CONSECUTIVE_FAILURE_LIMIT + 1):
                with self.assertRaises(Exception):
                    mlb_news._get_json("transactions", {"startDate": f"2026-10-0{day + 1}"})
        summary = layer.summary()
        self.assertEqual(summary["failed"], CONSECUTIVE_FAILURE_LIMIT + 1, summary["outcomes"])
        self.assertTrue(layer.halted, "six timeouts in a row are a run of hard failures")


class CorruptCacheIsAMiss(FetchBase):

    def test_a_truncated_cache_file_is_asked_for_again_and_rewritten(self):
        self.ask(Wire(schedule_day("F")), self.layer())
        files = list(self.cache.rglob("*.json"))
        self.assertEqual(len(files), 1)
        files[0].write_text(files[0].read_text(encoding="utf-8")[:40], encoding="utf-8")      # torn write
        wire = Wire(schedule_day("F"))
        self.ask(wire, self.layer())
        self.assertEqual(len(wire.calls), 1)
        json.loads(files[0].read_text(encoding="utf-8"))                       # healed


# -- the union ---------------------------------------------------------------------------------------------

def jsonl(rows):
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def relief(person, day, innings, gs=0):
    return {"person_id": person, "date": day, "season": "2026", "games_started": gs, "innings_pitched": innings,
            "earned_runs": 0, "runs": 0, "hits": 0, "walks": 0, "strikeouts": 1, "home_runs": 0,
            "batters_faced": 4, "pitches": 15}


class PersistBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.head_root = seed_root(base / "head")
        self.disk_root = seed_root(base / "disk")
        self.head = self.head_root / "historical"
        self.disk = self.disk_root / "historical"

    def reader(self, name):
        path = self.head / name
        return path.read_bytes() if path.exists() else None

    def union(self, prefer="disk"):
        return sp.union_stores(self.disk_root, reader=self.reader, prefer=prefer, season="2026")


class TwoAppearancesOnOneDateAreTwoRecords(PersistBase):

    @unittest.expectedFailure
    def test_a_doubleheader_second_relief_outing_held_only_by_git_survives_the_union(self):
        """A pitcher's appearance is identified by (date, started), so two relief outings on one date (a
        doubleheader; the repo's own pitcher_logs has three such pairs) are ONE identity. Git holds both; the disk
        copy holds one of them plus a new date: no key 'loses' an identity, the disk copy wins, the second outing is
        dropped, and the row count is unchanged (+1 new, -1 lost) so `guard_staged_no_shrink` stays silent."""
        both = [relief(111, "2026-09-10", 1.0), relief(111, "2026-09-10", 0.2)]
        start = pitchers.read_logs(self.head / "pitcher_logs.jsonl")["111"]
        pitchers.write_logs({"111": start + both}, self.head / "pitcher_logs.jsonl")
        pitchers.write_logs({"111": start + [relief(111, "2026-09-10", 1.0), relief(111, "2026-10-01", 1.0)]},
                            self.disk / "pitcher_logs.jsonl")
        self.union()
        merged = [a for a in pitchers.read_logs(self.disk / "pitcher_logs.jsonl")["111"]
                  if a.get("date") == "2026-09-10"]
        self.assertEqual(sorted(a["innings_pitched"] for a in merged), [0.2, 1.0],
                         "the committed second outing was lost by the union")


class ASchemaWiderThanTheCodeKnowsIsNotNarrowed(PersistBase):

    @unittest.expectedFailure
    def test_restoring_a_git_only_game_does_not_drop_a_column_the_committed_file_carries(self):
        """`_restore_results` rewrites the whole CSV through `history.write_results`, which writes only
        RESULT_COLUMNS (extrasaction='ignore'). A committed file with one more column (written by newer code, or
        by a later schema) loses that column on every row, and `_loses_nothing` only compares game_pk keys."""
        head_csv = self.head / "mlb_results.csv"
        text = head_csv.read_text(encoding="utf-8")
        lines = text.splitlines()
        widened = [lines[0] + ",venue_id"] + [ln + ",31" for ln in lines[1:]]
        head_csv.write_text("\r\n".join(widened) + "\r\n", encoding="utf-8")
        rows = history.read_results(self.disk / "mlb_results.csv")
        rows.pop("900")                                                         # the cache lost a git-only game
        history.write_results(rows, self.disk / "mlb_results.csv")
        self.union()
        header = (self.disk / "mlb_results.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("venue_id", header.split(","), "the committed column was dropped from every row")


class TheSealedWindowIsNotCommittedByTheUnion(PersistBase):

    @unittest.expectedFailure
    def test_rows_dated_inside_the_sealed_window_that_only_the_cache_holds_are_not_persisted(self):
        """The refresh never asks for 2026-01-01..2026-08-27 and `_keep_sealed_pitcher_rows` keeps git's rows there,
        but `union_one` keeps a record 'held by only one side', so an Actions cache that once ingested the window
        has rows that `persist` then reports as differing from HEAD and the loop stages and commits. Counted by
        date only; no outcome is read or printed."""
        rows = history.read_results(self.disk / "mlb_results.csv")
        template = dict(rows["1"])
        for pk, day in ((5001, "2026-03-30"), (5002, "2026-06-15"), (5003, "2026-08-27")):
            rows[str(pk)] = {**template, "game_pk": str(pk), "date": day}
        history.write_results(rows, self.disk / "mlb_results.csv")
        head_dates = {r["date"] for r in history.read_results(self.head / "mlb_results.csv").values()}
        self.union()
        new_sealed = sorted(r["date"] for r in history.read_results(self.disk / "mlb_results.csv").values()
                            if dr._in_sealed_window(r["date"]) and r["date"] not in head_dates)
        self.assertEqual(new_sealed, [], f"{len(new_sealed)} sealed-window row(s) newly reach the commit "
                                         f"(dates {new_sealed})")
        differing = sp.differing_from_head(self.disk_root, reader=self.reader, season="2026")
        self.assertNotIn("mlb_results.csv", differing)


class TheUnionDecisionsThatAreRight(PersistBase):

    def test_a_correction_on_disk_wins_over_the_committed_value(self):
        rows = history.read_results(self.disk / "mlb_results.csv")
        rows["1"]["away_score"] = "9"
        history.write_results(rows, self.disk / "mlb_results.csv")
        self.union(prefer="disk")
        self.assertEqual(history.read_results(self.disk / "mlb_results.csv")["1"]["away_score"], "9")

    def test_seeding_prefers_git_so_an_old_cache_cannot_overwrite_it(self):
        rows = history.read_results(self.disk / "mlb_results.csv")
        rows["1"]["away_score"] = "0"                                           # a stale cache row
        history.write_results(rows, self.disk / "mlb_results.csv")
        self.union(prefer="head")
        self.assertEqual(history.read_results(self.disk / "mlb_results.csv")["1"]["away_score"], "3")

    def test_a_git_only_game_and_a_cache_only_game_both_survive(self):
        rows = history.read_results(self.disk / "mlb_results.csv")
        rows.pop("900")
        rows["5"] = {**rows["1"], "game_pk": "5", "date": "2026-09-30"}
        history.write_results(rows, self.disk / "mlb_results.csv")
        self.union()
        merged = history.read_results(self.disk / "mlb_results.csv")
        self.assertIn("900", merged)
        self.assertIn("5", merged)

    def test_no_stray_staging_files_and_the_scratch_directory_is_gone(self):
        self.union()
        leftovers = [p.name for p in self.disk_root.rglob("*") if p.name.endswith(".tmp") or p.name == ".union_work"]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
