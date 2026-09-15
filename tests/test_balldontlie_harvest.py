"""Tests for scripts/balldontlie_harvest.py.

Everything runs in a temp directory with a fake transport under
src.providers.balldontlie.Client -- nothing here touches the network or the
real data/historical/balldontlie tree. Covers: the plan builds for every
sport, --dry-run prints without network, a job writes gzip rows plus a
correct manifest entry (sha256/rows), resume skips completed jobs and
continues a partial one from its saved cursor, a 403 is recorded and
skipped, and --max-minutes stops cleanly.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import balldontlie_harvest as harvest  # noqa: E402
from src.providers.balldontlie import BallDontLieHTTPError  # noqa: E402

FAKE_KEY = "sk-test-harvest-0000000000"


def _body(payload):
    return json.dumps(payload).encode("utf-8")


class ScriptedClient:
    """A fake balldontlie Client: `pages()` and `get()` driven by a script
    keyed on the exact (path, params-without-cursor) the harvester used to
    build the request, so each test only has to describe what the fake
    vendor holds, not the pacing/retry machinery (already covered in
    tests/test_balldontlie_client.py).
    """

    def __init__(self, page_script=None, get_script=None, http_errors=None):
        # page_script: {(path, frozenset(base_params.items())): [rows_page1, rows_page2, ...]}
        self.page_script = page_script or {}
        self.get_script = get_script or {}
        self.http_errors = http_errors or {}  # path -> status
        self.calls = []

    def _key(self, path, params):
        base = {k: v for k, v in params.items() if k not in ("cursor", "per_page")}
        return (path, tuple(sorted((k, _freeze(v)) for k, v in base.items())))

    def pages(self, path, params=None, *, page_cap=None, start_cursor=None):
        # Cursor values are simply the index of the next page, so resuming
        # from start_cursor=N genuinely skips pages 0..N-1 -- this is what
        # makes test_resume_continues_from_saved_cursor_after_deadline a
        # real check that the harvester passed the saved cursor back, not
        # just that it re-fetched everything from scratch.
        params = dict(params or {})
        self.calls.append(("pages", path, dict(params)))
        if path in self.http_errors:
            raise BallDontLieHTTPError(self.http_errors[path], path)
        key = self._key(path, params)
        row_pages = self.page_script.get(key, [])
        start_index = start_cursor if start_cursor is not None else 0
        count = 0
        for i in range(start_index, len(row_pages)):
            if page_cap is not None and count >= page_cap:
                return
            rows = row_pages[i]
            has_next = i < len(row_pages) - 1
            yield {"data": rows, "meta": {"next_cursor": i + 1 if has_next else None}}
            count += 1

    def get(self, path, params=None):
        params = dict(params or {})
        self.calls.append(("get", path, dict(params)))
        if path in self.http_errors:
            raise BallDontLieHTTPError(self.http_errors[path], path)
        key = self._key(path, params)
        return self.get_script.get(key, {"data": []})


def _freeze(v):
    if isinstance(v, list):
        return tuple(v)
    return v


class TestPlanBuilds(unittest.TestCase):
    def test_builds_for_every_sport(self):
        for sport in harvest.ALL_SPORTS:
            jobs = harvest.build_plan([sport])
            self.assertTrue(jobs, f"no jobs built for {sport}")
            self.assertTrue(all(j.sport == sport for j in jobs))

    def test_all_sports_together_matches_union(self):
        jobs_all = harvest.build_plan(harvest.ALL_SPORTS)
        total = sum(len(harvest.build_plan([s])) for s in harvest.ALL_SPORTS)
        self.assertEqual(len(jobs_all), total)

    def test_only_filters_to_one_endpoint(self):
        jobs = harvest.build_plan(["tennis"], only="atp_matches")
        self.assertTrue(jobs)
        self.assertTrue(all(j.endpoint == "atp_matches" for j in jobs))

    def test_job_output_names_are_unique(self):
        jobs = harvest.build_plan(harvest.ALL_SPORTS)
        names = [(j.sport, j.out_name) for j in jobs]
        self.assertEqual(len(names), len(set(names)), "duplicate output file names in the plan")


class TestDryRun(unittest.TestCase):
    def test_prints_plan_without_network(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = harvest.main(["--dry-run", "--sports", "tennis"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("tennis", out)
        self.assertIn("TOTAL:", out)
        self.assertIn("atp_matches", out)

    def test_dry_run_never_builds_a_client(self):
        # If this tried to build a real client it would raise (no env key
        # set in the test process) -- so a clean exit with no key set at
        # all is itself proof no network path was taken.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = harvest.main(["--dry-run", "--sports", "nfl", "--only", "games"])
        self.assertEqual(rc, 0)


class TestJobExecution(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_paged_job_writes_gzip_rows_and_manifest_entry(self):
        job = harvest._paged_job(
            "tennis", "atp_matches", "/atp/v1/matches", {"season": 2024},
            "atp_matches_2024", "test job", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/matches", (("season", 2024),)): [
                [{"id": 1, "match_status": "finished"}, {"id": 2, "match_status": "finished"}],
                [{"id": 3, "match_status": "finished"}],
            ],
        })
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})
        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["completed"], 1)
        out_path = harvest._out_path(self.out_dir, "tennis", "atp_matches_2024")
        self.assertTrue(out_path.exists())

        rows = _read_jsonl_gz(out_path)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["id"] for r in rows}, {1, 2, 3})
        for row in rows:
            self.assertIn("_harvested_utc", row)

        manifest = harvest.load_manifest(self.out_dir)
        rel = "tennis/atp_matches_2024.jsonl.gz"
        self.assertIn(rel, manifest)
        entry = manifest[rel]
        self.assertTrue(entry["complete"])
        self.assertEqual(entry["rows"], 3)
        self.assertEqual(entry["sport"], "tennis")
        self.assertEqual(entry["endpoint"], "atp_matches")
        self.assertEqual(entry["bytes"], out_path.stat().st_size)

        expected_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
        self.assertEqual(entry["sha256"], expected_sha)

        # No cursor sidecar left behind once a job completes cleanly.
        self.assertFalse(harvest._sidecar_path(out_path).exists())

    def test_single_job_writes_one_object_per_row(self):
        job = harvest._single_job(
            "nfl", "standings", "/nfl/v1/standings", {"season": 2024},
            "nfl_standings_2024", "test job", 1)
        client = ScriptedClient(get_script={
            ("/nfl/v1/standings", (("season", 2024),)):
                {"data": [{"team_id": 1, "wins": 10}, {"team_id": 2, "wins": 7}]},
        })
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})
        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["completed"], 1)
        out_path = harvest._out_path(self.out_dir, "nfl", "nfl_standings_2024")
        rows = _read_jsonl_gz(out_path)
        self.assertEqual(len(rows), 2)

    def test_resume_skips_completed_jobs(self):
        job = harvest._paged_job(
            "tennis", "atp_players", "/atp/v1/players", {},
            "atp_players", "players", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/players", ()): [[{"id": 1}]],
        })
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})
        harvest.run_plan([job], ctx)
        self.assertEqual(len(client.calls), 1)

        # Second run over the same manifest: the job must not run again.
        manifest2 = harvest.load_manifest(self.out_dir)
        ctx2 = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest2)
        summary2 = harvest.run_plan([job], ctx2)

        self.assertEqual(summary2["completed"], 0)
        self.assertEqual(summary2["skipped"], 1)
        self.assertEqual(len(client.calls), 1)  # no new network calls

    def test_resume_continues_from_saved_cursor_after_deadline(self):
        job = harvest._paged_job(
            "mlb", "games", "/mlb/v1/games", {"seasons[]": [2024]},
            "mlb_games_2024", "games", 1)
        client = ScriptedClient(page_script={
            ("/mlb/v1/games", (("seasons[]", (2024,)),)): [
                [{"id": 1}], [{"id": 2}], [{"id": 3}],
            ],
        })

        # Run 1: the deadline is not yet reached when run_plan does its
        # own pre-job check (clock tick 0), but IS reached by the time
        # _run_paged_job checks after writing the first page (clock tick
        # 1) -- so the job starts, writes one page, and stops cleanly.
        clock = _FakeMonotonic(start=0.0, step=1.0)
        ctx1 = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={},
                                   deadline=1.0, clock=clock)
        summary1 = harvest.run_plan([job], ctx1)
        self.assertEqual(summary1["partial"], 1)

        out_path = harvest._out_path(self.out_dir, "mlb", "mlb_games_2024")
        self.assertTrue(harvest._sidecar_path(out_path).exists())
        rows_after_run1 = _read_jsonl_gz(out_path)
        self.assertEqual(len(rows_after_run1), 1)

        # Run 2: resumes, no deadline this time, finishes the remaining pages.
        manifest2 = harvest.load_manifest(self.out_dir)
        ctx2 = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest2)
        summary2 = harvest.run_plan([job], ctx2)
        self.assertEqual(summary2["completed"], 1)

        rows_after_run2 = _read_jsonl_gz(out_path)
        self.assertEqual({r["id"] for r in rows_after_run2}, {1, 2, 3})
        self.assertFalse(harvest._sidecar_path(out_path).exists())

    def test_403_is_recorded_and_skipped(self):
        job = harvest._paged_job(
            "tennis", "atp_match_stats", "/atp/v1/match_stats", {},
            "atp_match_stats", "match stats", 1)
        client = ScriptedClient(http_errors={"/atp/v1/match_stats": 403})
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan([job], ctx)
        self.assertEqual(summary["errored"], 1)

        manifest = harvest.load_manifest(self.out_dir)
        rel = "tennis/atp_match_stats.jsonl.gz"
        self.assertEqual(manifest[rel]["http_status"], 403)
        self.assertFalse(manifest[rel]["complete"])

        # A second run must not retry a recorded permanent HTTP error.
        client.calls.clear()
        ctx2 = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest)
        summary2 = harvest.run_plan([job], ctx2)
        self.assertEqual(summary2["skipped"], 1)
        self.assertEqual(client.calls, [])

    def test_max_minutes_stops_cleanly(self):
        # Two jobs; the deadline is hit before either can run, so the run
        # must exit with zero completed/errored and no exception.
        job1 = harvest._paged_job("nba", "games", "/nba/v1/games", {"seasons[]": [2024]},
                                   "nba_games_2024", "games", 1)
        job2 = harvest._paged_job("nba", "games", "/nba/v1/games", {"seasons[]": [2025]},
                                   "nba_games_2025", "games", 1)
        client = ScriptedClient(page_script={
            ("/nba/v1/games", (("seasons[]", (2024,)),)): [[{"id": 1}]],
            ("/nba/v1/games", (("seasons[]", (2025,)),)): [[{"id": 2}]],
        })
        clock = _FakeMonotonic(start=0.0)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={},
                                  deadline=0.0, clock=clock)
        summary = harvest.run_plan([job1, job2], ctx)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(client.calls, [])  # never even started a job


class TestRankingProbe(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_probe_then_fill_writes_every_monday_with_data(self):
        job = harvest._ranking_probe_job(
            "tennis", "atp_rankings", "atp", "atp_rankings", "rankings", 100)

        class RankingClient:
            """Data exists on/after 2026-08-31 (a Monday); empty before."""

            EARLIEST = date(2026, 8, 31)

            def __init__(self):
                self.get_calls = []

            def get(self, path, params):
                self.get_calls.append(dict(params))
                d = date.fromisoformat(params["date"])
                if d >= self.EARLIEST:
                    return {"data": [{"player_id": 1, "rank": 1}]}
                return {"data": []}

            def pages(self, path, params=None, **kwargs):
                payload = self.get(path, params or {})
                yield payload

        client = RankingClient()
        today = date(2026, 9, 14)  # a Monday
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={}, today=today)

        summary = harvest.run_plan([job], ctx)
        self.assertEqual(summary["completed"], 1)

        out_path = harvest._out_path(self.out_dir, "tennis", "atp_rankings")
        rows = _read_jsonl_gz(out_path)
        # Two Mondays with data in [2026-08-31, 2026-09-14]: 08-31 and 09-07 and 09-14.
        self.assertEqual(len(rows), 3)

    def test_partial_probe_resumes(self):
        job = harvest._ranking_probe_job(
            "tennis", "wta_rankings", "wta", "wta_rankings", "rankings", 100)

        class CountingClient:
            def __init__(self):
                self.n_calls = 0

            def get(self, path, params):
                self.n_calls += 1
                return {"data": [{"player_id": 1}]}

            def pages(self, path, params=None, **kwargs):
                yield self.get(path, params or {})

        client = CountingClient()
        today = date(2026, 9, 14)

        # Deadline arrives just after the job starts (see _FakeMonotonic's
        # docstring) -- the job must save state and return "partial"
        # rather than raising or looping forever.
        clock = _FakeMonotonic(start=0.0, step=1.0)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={},
                                  deadline=1.0, clock=clock, today=today)
        summary = harvest.run_plan([job], ctx)
        self.assertEqual(summary["partial"], 1)

        out_path = harvest._out_path(self.out_dir, "tennis", "wta_rankings")
        self.assertTrue(harvest._sidecar_path(out_path).exists())


def _read_jsonl_gz(path: Path) -> list:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class _FakeMonotonic:
    """A clock callable usable as RunContext.clock in tests.

    With step=0 (the default) it is simply fixed, which is what
    test_max_minutes_stops_cleanly wants (deadline already passed before
    the run even starts, so nothing should run at all). With step>0 it
    ticks by `step` on every read, which is what lets a test place the
    deadline strictly between run_plan's own pre-job check and a job's
    first internal per-page check -- i.e. simulate "the deadline arrives
    while this job is already in progress" without needing a real clock.
    """

    def __init__(self, start: float = 0.0, step: float = 0.0):
        self.now = start
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


if __name__ == "__main__":
    unittest.main()
