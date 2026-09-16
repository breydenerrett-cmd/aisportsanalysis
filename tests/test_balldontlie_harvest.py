"""Tests for scripts/balldontlie_harvest.py.

Everything runs in a temp directory with a fake transport under
src.providers.balldontlie.Client -- nothing here touches the network or the
real data/historical/balldontlie tree. Covers: the plan builds for every
sport and is priority-ordered (newest-value jobs first), --dry-run prints
without network, --probe makes exactly one request per sport and prints
only status + whitelisted headers, a job writes gzip rows plus a correct
manifest entry (sha256/rows), resume skips completed jobs and continues a
partial one from its saved cursor (including after a reorder of the plan),
a 403 is recorded and skipped, a 429 that exhausts max_429_wait_seconds or
the deadline is recorded as partial (resumable) not error, and
--max-minutes stops cleanly.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import balldontlie_harvest as harvest  # noqa: E402
from src.providers.balldontlie import (  # noqa: E402
    BallDontLieDeadlineExceeded,
    BallDontLieHTTPError,
    BallDontLieRateLimitExhausted,
)

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

    def __init__(self, page_script=None, get_script=None, http_errors=None,
                 rate_limit_errors=None):
        # page_script: {(path, frozenset(base_params.items())): [rows_page1, rows_page2, ...]}
        self.page_script = page_script or {}
        self.get_script = get_script or {}
        self.http_errors = http_errors or {}  # path -> status
        # path -> exception instance (BallDontLieRateLimitExhausted or
        # BallDontLieDeadlineExceeded) to raise instead of serving data --
        # simulates the real Client giving up on a 429 wait.
        self.rate_limit_errors = rate_limit_errors or {}
        self.calls = []

    def _key(self, path, params):
        base = {k: v for k, v in params.items() if k not in ("cursor", "per_page")}
        return (path, tuple(sorted((k, _freeze(v)) for k, v in base.items())))

    def pages(self, path, params=None, *, page_cap=None, start_cursor=None, deadline=None):
        # Cursor values are simply the index of the next page, so resuming
        # from start_cursor=N genuinely skips pages 0..N-1 -- this is what
        # makes test_resume_continues_from_saved_cursor_after_deadline a
        # real check that the harvester passed the saved cursor back, not
        # just that it re-fetched everything from scratch.
        params = dict(params or {})
        self.calls.append(("pages", path, dict(params)))
        if path in self.rate_limit_errors:
            raise self.rate_limit_errors[path]
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

    def get(self, path, params=None, *, deadline=None):
        params = dict(params or {})
        self.calls.append(("get", path, dict(params)))
        if path in self.rate_limit_errors:
            raise self.rate_limit_errors[path]
        if path in self.http_errors:
            raise BallDontLieHTTPError(self.http_errors[path], path)
        key = self._key(path, params)
        return self.get_script.get(key, {"data": []})

    def probe(self, path, params=None):
        params = dict(params or {})
        self.calls.append(("probe", path, dict(params)))
        if path in self.http_errors:
            return self.http_errors[path], {}
        return 200, {"x-ratelimit-remaining": "99"}

    def rate_state(self):
        return {"rate_per_minute": 550.0, "total_429_wait_seconds": 0.0}


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


class TestManifestSkipsOnlyPermanentStatus(unittest.TestCase):
    """Root cause A (2026-09-15 incident): a manifest entry recording an
    http_status must only skip the job on a PERMANENT status (4xx other
    than 429). 429 and 5xx are exactly the transient statuses the 429-wait
    machinery exists to survive -- the incident poisoned MANIFEST.json with
    http_status:429 on every tennis season, silently skipping all of it
    forever under the old skip test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _poisoned_manifest(self, http_status):
        rel = "tennis/atp_matches_2024.jsonl.gz"
        return rel, {rel: {
            "file": rel, "sport": "tennis", "endpoint": "atp_matches",
            "params": {"season": 2024}, "harvested_utc": "2026-09-15T00:00:00Z",
            "rows": 0, "sha256": None, "bytes": 0, "complete": False,
            "http_status": http_status,
        }}

    def test_429_recorded_status_does_not_skip_the_job(self):
        job = harvest._paged_job(
            "tennis", "atp_matches", "/atp/v1/matches", {"season": 2024},
            "atp_matches_2024", "test job", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/matches", (("season", 2024),)): [[{"id": 1}]],
        })
        _rel, manifest = self._poisoned_manifest(429)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest)

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(len(client.calls), 1)

    def test_5xx_recorded_status_does_not_skip_the_job(self):
        job = harvest._paged_job(
            "tennis", "atp_matches", "/atp/v1/matches", {"season": 2024},
            "atp_matches_2024", "test job", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/matches", (("season", 2024),)): [[{"id": 1}]],
        })
        _rel, manifest = self._poisoned_manifest(503)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest)

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["completed"], 1)

    def test_permanent_4xx_recorded_status_still_skips_the_job(self):
        job = harvest._paged_job(
            "tennis", "atp_matches", "/atp/v1/matches", {"season": 2024},
            "atp_matches_2024", "test job", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/matches", (("season", 2024),)): [[{"id": 1}]],
        })
        _rel, manifest = self._poisoned_manifest(403)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest)

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(client.calls, [])

    def test_400_recorded_status_does_not_skip_the_job(self):
        # DEFECT 1/2 (2026-09-15): a 400 means THIS request was malformed --
        # exactly what the old unfiltered odds jobs and (maybe) the NHL
        # games job hit -- not "never entitled" like 401/403/404. Once the
        # request is corrected, a recorded 400 must not keep skipping it
        # forever just because the manifest key (file path) is unchanged.
        job = harvest._paged_job(
            "tennis", "atp_matches", "/atp/v1/matches", {"season": 2024},
            "atp_matches_2024", "test job", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/matches", (("season", 2024),)): [[{"id": 1}]],
        })
        _rel, manifest = self._poisoned_manifest(400)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest)

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(len(client.calls), 1)

    def test_400_recorded_status_resumes_from_saved_cursor_not_from_scratch(self):
        # The other half of "does not prevent a new OR RESUMED job from
        # running": a partially-written job with both a saved cursor and a
        # recorded 400 must resume from that cursor, not skip, and not
        # restart from page 0.
        job = harvest._paged_job(
            "mlb", "games", "/mlb/v1/games", {"seasons[]": [2024]},
            "mlb_games_2024", "test job", 1)
        out_path = harvest._out_path(self.out_dir, "mlb", "mlb_games_2024")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Sentinel id 999 stands in for "page 0's real historical row" --
        # distinct from what the fake's page_script would return for page 0
        # (id 1) below, so the assertion can tell "resumed, appended" apart
        # from "restarted from scratch, overwrote": a broken resume would
        # re-fetch page 0 and either lose 999 (if it overwrites) or produce
        # {1, 2} instead of {999, 2}.
        with gzip.open(out_path, "wb") as gz:
            gz.write((json.dumps({"id": 999, "_harvested_utc": "2026-09-15T00:00:00Z"}) + "\n")
                     .encode("utf-8"))
        harvest._sidecar_path(out_path).write_text(json.dumps({"cursor": 1}), encoding="utf-8")

        client = ScriptedClient(page_script={
            ("/mlb/v1/games", (("seasons[]", (2024,)),)): [[{"id": 1}], [{"id": 2}]],
        })
        rel = "mlb/mlb_games_2024.jsonl.gz"
        manifest = {rel: {
            "file": rel, "sport": "mlb", "endpoint": "games",
            "params": {"seasons[]": [2024]}, "harvested_utc": "2026-09-15T00:00:00Z",
            "rows": 1, "sha256": None, "bytes": out_path.stat().st_size,
            "complete": False, "http_status": 400,
        }}
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest)

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["completed"], 1)
        rows = _read_jsonl_gz(out_path)
        # 999 (preserved from before) + 2 (page index 1, fetched via
        # start_cursor=1) -- id 1 (page index 0) must NOT have been
        # re-fetched, and 999 must not have been discarded.
        self.assertEqual({r["id"] for r in rows}, {999, 2})


class TestRateLimitDoesNotEndTheRun(unittest.TestCase):
    """Root cause B (2026-09-15 incident): a rate-limit exhaustion on one
    job must not end the whole run while run time remains -- the ACCOUNT is
    still rate-limited, not the RUN out of time. Only a genuine deadline
    (BallDontLieDeadlineExceeded, or run_plan's own pre-job clock check)
    ends the run early."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_rate_limited_partial_continues_to_the_next_job(self):
        path1, path2 = "/mlb/v1/games", "/nba/v1/games"
        job1 = harvest._paged_job("mlb", "games", path1, {"seasons[]": [2024]},
                                   "mlb_games_2024", "games", 1)
        job2 = harvest._paged_job("nba", "games", path2, {"seasons[]": [2024]},
                                   "nba_games_2024", "games", 1)
        client = ScriptedClient(
            rate_limit_errors={path1: BallDontLieRateLimitExhausted(path1, 900.0)},
            page_script={(path2, (("seasons[]", (2024,)),)): [[{"id": 1}]]},
        )
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan([job1, job2], ctx)

        self.assertEqual(summary["partial"], 1)
        self.assertEqual(summary["partial_rate_limited"], 1)
        self.assertEqual(summary["partial_deadline"], 0)
        self.assertEqual(summary["completed"], 1)
        # job2 ran -- the old unconditional "partial => break" would have
        # stopped the whole run after job1 and never reached it.
        self.assertEqual(len(client.calls), 2)

    def test_deadline_exceeded_partial_still_ends_the_run(self):
        path1, path2 = "/mlb/v1/games", "/nba/v1/games"
        job1 = harvest._paged_job("mlb", "games", path1, {"seasons[]": [2024]},
                                   "mlb_games_2024", "games", 1)
        job2 = harvest._paged_job("nba", "games", path2, {"seasons[]": [2024]},
                                   "nba_games_2024", "games", 1)
        client = ScriptedClient(
            rate_limit_errors={path1: BallDontLieDeadlineExceeded(path1)},
            page_script={(path2, (("seasons[]", (2024,)),)): [[{"id": 1}]]},
        )
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan([job1, job2], ctx)

        self.assertEqual(summary["partial"], 1)
        self.assertEqual(summary["partial_deadline"], 1)
        self.assertEqual(summary["partial_rate_limited"], 0)
        self.assertEqual(summary["completed"], 0)
        # A genuine deadline still ends the run -- job2 must not run.
        self.assertEqual(len(client.calls), 1)

    def test_hard_block_stops_after_consecutive_rate_limited_partials(self):
        # Pathological-case guard: an account that is hard-blocked for the
        # rest of the run must not sleep max_429_wait_seconds per job for
        # 330 minutes -- see _RATE_LIMIT_HARD_BLOCK_THRESHOLD.
        n_jobs = harvest._RATE_LIMIT_HARD_BLOCK_THRESHOLD + 2
        jobs = []
        rate_limit_errors = {}
        for i in range(n_jobs):
            path = f"/mlb/v1/games_{i}"
            jobs.append(harvest._paged_job("mlb", "games", path, {"seasons[]": [2024]},
                                            f"mlb_games_{i}", "games", 1))
            rate_limit_errors[path] = BallDontLieRateLimitExhausted(path, 900.0)
        client = ScriptedClient(rate_limit_errors=rate_limit_errors)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan(jobs, ctx)

        self.assertEqual(summary["partial"], harvest._RATE_LIMIT_HARD_BLOCK_THRESHOLD)
        self.assertEqual(len(client.calls), harvest._RATE_LIMIT_HARD_BLOCK_THRESHOLD)

    def test_a_completed_job_resets_the_consecutive_rate_limited_counter(self):
        # One rate-limited job, then a SUCCESS, must not count toward the
        # hard-block threshold -- only CONSECUTIVE rate-limited partials do.
        path1, path2 = "/mlb/v1/games", "/nba/v1/games"
        path3 = "/nhl/v1/games"
        job1 = harvest._paged_job("mlb", "games", path1, {"seasons[]": [2024]},
                                   "mlb_games_2024", "games", 1)
        job2 = harvest._paged_job("nba", "games", path2, {"seasons[]": [2024]},
                                   "nba_games_2024", "games", 1)
        job3 = harvest._paged_job("nhl", "games", path3, {"seasons": [2024]},
                                   "nhl_games_2024", "games", 1)
        client = ScriptedClient(
            rate_limit_errors={
                path1: BallDontLieRateLimitExhausted(path1, 900.0),
                path3: BallDontLieRateLimitExhausted(path3, 900.0),
            },
            page_script={(path2, (("seasons[]", (2024,)),)): [[{"id": 1}]]},
        )
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan([job1, job2, job3], ctx)

        # All three ran (2 < threshold even though 2 partials occurred,
        # because they were not consecutive).
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(summary["partial"], 2)
        self.assertEqual(summary["completed"], 1)


class TestPagedJobFlushOrdering(unittest.TestCase):
    """Root cause D: rows must be flushed to disk BEFORE the cursor/state
    sidecar that claims them is persisted, and a page with no next_cursor
    (the job's last page) is not a resumable stopping point."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_flush_happens_before_the_cursor_sidecar_is_written(self):
        job = harvest._paged_job(
            "tennis", "atp_matches", "/atp/v1/matches", {"season": 2024},
            "atp_matches_2024", "test job", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/matches", (("season", 2024),)): [[{"id": 1}], [{"id": 2}]],
        })
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        events = []
        real_flush = harvest._flush_to_disk

        def recording_flush(gz):
            events.append("flush")
            real_flush(gz)

        real_write_text = Path.write_text

        def recording_write_text(self_path, *args, **kwargs):
            if self_path.name.endswith(".cursor"):
                events.append("cursor_write")
            return real_write_text(self_path, *args, **kwargs)

        with mock.patch.object(harvest, "_flush_to_disk", recording_flush), \
             mock.patch.object(Path, "write_text", recording_write_text):
            summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["completed"], 1)
        self.assertIn("flush", events)
        self.assertIn("cursor_write", events)
        self.assertLess(events.index("flush"), events.index("cursor_write"))

    def test_last_page_with_no_next_cursor_completes_even_at_the_deadline(self):
        # Before the fix, the deadline check ran unconditionally after
        # EVERY page including the last one, so hitting the deadline
        # exactly on the final page (next_cursor is None) returned
        # "partial" and left a resumable state that would duplicate that
        # final page on the next run. next_cursor is None means the job is
        # DONE, not a resumable stopping point.
        job = harvest._paged_job(
            "tennis", "atp_players", "/atp/v1/players", {},
            "atp_players", "test job", 1)
        client = ScriptedClient(page_script={
            ("/atp/v1/players", ()): [[{"id": 1}]],  # exactly one page
        })
        clock = _FakeMonotonic(start=0.0, step=1.0)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={},
                                  deadline=1.0, clock=clock)

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["partial"], 0)
        out_path = harvest._out_path(self.out_dir, "tennis", "atp_players")
        self.assertFalse(harvest._sidecar_path(out_path).exists())


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

            def get(self, path, params, *, deadline=None):
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

            def get(self, path, params, *, deadline=None):
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

    def test_orphan_state_without_data_file_restarts_clean(self):
        # Root cause E(1): mirrors _run_paged_job's identical guard. A
        # state sidecar can survive a chained run without its .jsonl.gz
        # (data/historical/* is not committed) -- without this guard the
        # job resumes mid-fill onto a FRESH file and marks complete=True
        # over silently truncated data.
        job = harvest._ranking_probe_job(
            "tennis", "atp_rankings", "atp", "atp_rankings", "rankings", 100)
        out_path = harvest._out_path(self.out_dir, "tennis", "atp_rankings")
        state_path = harvest._sidecar_path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Orphan state: claims the fill phase is almost done, but the data
        # file it would be appending to does not exist on this checkout.
        state_path.write_text(json.dumps({"phase": "fill", "next_date": "2026-09-07",
                                           "until": "2026-09-14", "known_good": "2020-01-06"}),
                               encoding="utf-8")
        self.assertFalse(out_path.exists())

        class RankingClient:
            EARLIEST = date(2026, 8, 31)

            def get(self, path, params, *, deadline=None):
                d = date.fromisoformat(params["date"])
                if d >= self.EARLIEST:
                    return {"data": [{"player_id": 1, "rank": 1}]}
                return {"data": []}

            def pages(self, path, params=None, **kwargs):
                yield self.get(path, params or {})

        client = RankingClient()
        today = date(2026, 9, 14)  # a Monday
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={}, today=today)

        summary = harvest.run_plan([job], ctx)
        self.assertEqual(summary["completed"], 1)

        rows = _read_jsonl_gz(out_path)
        # Discarded the orphan state and restarted the probe from today,
        # same as test_probe_then_fill_writes_every_monday_with_data (3
        # Mondays: 08-31, 09-07, 09-14) -- NOT the truncated 2-row result a
        # trusted orphan fill (resuming at 09-07) would have produced.
        self.assertEqual(len(rows), 3)

    def test_first_empty_probe_keeps_stepping_backward_not_collapsing(self):
        # Root cause E(2): an empty probe at TODAY with no known_good yet
        # (e.g. this week's rankings just haven't posted) must not
        # collapse to a single-week fill and mark the job complete -- it
        # must keep stepping backward until data is found.
        job = harvest._ranking_probe_job(
            "tennis", "atp_rankings", "atp", "atp_rankings", "rankings", 100)

        class RankingClient:
            EARLIEST = date(2026, 6, 1)
            TODAY_GAP = date(2026, 9, 14)  # this week hasn't posted yet

            def __init__(self):
                self.probe_dates = []

            def get(self, path, params, *, deadline=None):
                d = date.fromisoformat(params["date"])
                self.probe_dates.append(d)
                if d == self.TODAY_GAP:
                    return {"data": []}
                if d >= self.EARLIEST:
                    return {"data": [{"player_id": 1, "rank": 1}]}
                return {"data": []}

            def pages(self, path, params=None, **kwargs):
                yield self.get(path, params or {})

        client = RankingClient()
        today = date(2026, 9, 14)  # a Monday; the FIRST probe here is empty
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={}, today=today)

        summary = harvest.run_plan([job], ctx)
        self.assertEqual(summary["completed"], 1)

        out_path = harvest._out_path(self.out_dir, "tennis", "atp_rankings")
        manifest = harvest.load_manifest(self.out_dir)
        entry = manifest["tennis/atp_rankings.jsonl.gz"]
        self.assertNotIn("zero_rows", entry)
        rows = _read_jsonl_gz(out_path)
        # Real history (weeks in [EARLIEST, today) other than the gap
        # itself) must have been found, not lost to the single-week
        # collapse the old code did on an empty first probe.
        self.assertGreater(len(rows), 5)
        self.assertIn(date(2026, 8, 17), client.probe_dates)  # stepped backward

    def test_probe_reaches_floor_with_no_data_marks_zero_rows(self):
        # Root cause E(2), other half: if there is truly no data anywhere
        # back to the floor, the job completes with 0 rows -- but that
        # must be visibly distinguishable from an ordinary successful pull
        # rather than silently looking like one.
        job = harvest._ranking_probe_job(
            "tennis", "wta_rankings", "wta", "wta_rankings", "rankings", 100)

        class NoDataClient:
            def get(self, path, params, *, deadline=None):
                return {"data": []}

            def pages(self, path, params=None, **kwargs):
                yield self.get(path, params or {})

        client = NoDataClient()
        today = date(2026, 9, 14)
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={}, today=today)

        summary = harvest.run_plan([job], ctx)
        self.assertEqual(summary["completed"], 1)

        manifest = harvest.load_manifest(self.out_dir)
        entry = manifest["tennis/wta_rankings.jsonl.gz"]
        self.assertEqual(entry["rows"], 0)
        self.assertTrue(entry.get("zero_rows"))


class TestPlanOrder(unittest.TestCase):
    """build_plan() priority order -- see the block comment above
    _TIER0_SEASON_FLOOR in scripts/balldontlie_harvest.py. A slow/rate-
    limited account may not finish the whole plan, so job order decides
    what survives; the highest-value jobs (newest-season tennis matches,
    then NFL games/odds, then MLB/NBA/NHL games/odds) must come first."""

    def test_first_jobs_are_2026_tennis_matches(self):
        jobs = harvest.build_plan(["tennis"])
        first = jobs[0]
        self.assertEqual(first.endpoint, "atp_matches")
        self.assertEqual(first.params["season"], harvest._CEILING_YEAR)

    def test_2026_tennis_and_nfl_precede_everything_else(self):
        jobs = harvest.build_plan(harvest.ALL_SPORTS)
        first_30 = jobs[:30]
        # Every one of the first 30 jobs must be a phase-0 (newest-value)
        # job: tennis matches or NFL games/odds, season >= their floor.
        for job in first_30:
            if job.sport == "tennis":
                self.assertIn(job.endpoint, ("atp_matches", "wta_matches"))
                self.assertGreaterEqual(job.params["season"], 2019)
            elif job.sport == "nfl":
                self.assertIn(job.endpoint, ("games", "odds", "odds_opening"))
            else:
                self.fail(f"unexpected sport this early in the plan: {job.sport} ({job.out_name})")
        # Tennis (higher value) must fully precede NFL within those 30.
        sports_seen = [job.sport for job in first_30]
        if "nfl" in sports_seen:
            last_tennis_idx = max(i for i, s in enumerate(sports_seen) if s == "tennis")
            first_nfl_idx = sports_seen.index("nfl")
            self.assertLess(last_tennis_idx, first_nfl_idx)

    def test_tennis_matches_season_strictly_descends_to_the_2019_floor(self):
        jobs = harvest.build_plan(["tennis"], only="atp_matches")
        seasons = [j.params["season"] for j in jobs]
        top = [s for s in seasons if s >= 2019]
        self.assertEqual(top, sorted(top, reverse=True))
        self.assertEqual(top[0], harvest._CEILING_YEAR)

    def test_older_tennis_seasons_come_after_non_season_priority_endpoints(self):
        jobs = harvest.build_plan(["tennis"])
        index = {id(j): i for i, j in enumerate(jobs)}
        players_idx = min(i for i, j in enumerate(jobs) if j.endpoint == "atp_players")
        old_match_idx = min(i for i, j in enumerate(jobs)
                             if j.endpoint == "atp_matches" and j.params["season"] < 2019)
        self.assertLess(players_idx, old_match_idx)

    def test_sports_and_only_filters_still_work_after_reordering(self):
        jobs = harvest.build_plan(["nfl", "mlb"])
        self.assertTrue(all(j.sport in ("nfl", "mlb") for j in jobs))
        only_jobs = harvest.build_plan(harvest.ALL_SPORTS, only="games")
        self.assertTrue(only_jobs)
        self.assertTrue(all(j.endpoint == "games" for j in only_jobs))

    def test_output_names_still_unique_after_reordering(self):
        jobs = harvest.build_plan(harvest.ALL_SPORTS)
        names = [(j.sport, j.out_name) for j in jobs]
        self.assertEqual(len(names), len(set(names)))


class TestProbeMode(unittest.TestCase):
    def test_probe_makes_exactly_one_request_per_sport_and_prints_status_and_headers(self):
        client = ScriptedClient()
        buf = io.StringIO()
        with redirect_stdout(buf):
            harvest.run_probe(client, ["tennis", "nfl", "mlb", "nba", "nhl"])
        out = buf.getvalue()

        probe_calls = [c for c in client.calls if c[0] == "probe"]
        self.assertEqual(len(probe_calls), 5)
        # Exactly the documented cheap per-sport endpoints, per_page=1.
        called_paths = {path for (_kind, path, _params) in probe_calls}
        self.assertEqual(called_paths, {
            "/atp/v1/players", "/nfl/v1/teams", "/mlb/v1/teams",
            "/nba/v1/teams", "/nhl/v1/teams",
        })
        for _kind, _path, params in probe_calls:
            self.assertEqual(params.get("per_page"), 1)

        for sport in ("tennis", "nfl", "mlb", "nba", "nhl"):
            self.assertIn(sport, out)
        self.assertIn("status=200", out)
        self.assertIn("x-ratelimit-remaining", out)

    def test_probe_prints_no_body_no_key_no_query_string(self):
        client = ScriptedClient()
        buf = io.StringIO()
        with redirect_stdout(buf):
            harvest.run_probe(client, ["tennis"])
        out = buf.getvalue()
        self.assertNotIn(FAKE_KEY, out)
        self.assertNotIn("?", out)
        self.assertNotIn("per_page=1", out)  # per_page is a request param, not printed


class TestRateLimitJobHandling(unittest.TestCase):
    """A 429 that exhausts max_429_wait_seconds or the caller's deadline is
    resumable, not a terminal error -- src/providers/balldontlie.py raises
    BallDontLieRateLimitExhausted / BallDontLieDeadlineExceeded for those
    two cases specifically (never BallDontLieHTTPError), and the harvester
    must record "partial" with the cursor saved, not "error"."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_paged_job_rate_limit_exhausted_is_partial_with_cursor_saved(self):
        path = "/mlb/v1/games"
        job = harvest._paged_job("mlb", "games", path, {"seasons[]": [2024]},
                                  "mlb_games_2024", "games", 1)
        client = ScriptedClient(
            page_script={(path, (("seasons[]", (2024,)),)): [[{"id": 1}], [{"id": 2}]]},
        )
        # First run: page 1 succeeds (cursor saved), then simulate the
        # vendor 429ing out on page 2 by swapping in a rate-limit error for
        # the same path after the first page has already been fetched once.
        real_pages = client.pages

        def pages_then_exhaust(*args, **kwargs):
            for i, payload in enumerate(real_pages(*args, **kwargs)):
                if i == 1:
                    raise BallDontLieRateLimitExhausted(path, 900.0)
                yield payload

        client.pages = pages_then_exhaust
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["partial"], 1)
        self.assertEqual(summary["errored"], 0)
        out_path = harvest._out_path(self.out_dir, "mlb", "mlb_games_2024")
        self.assertTrue(harvest._sidecar_path(out_path).exists())
        manifest = harvest.load_manifest(self.out_dir)
        entry = manifest["mlb/mlb_games_2024.jsonl.gz"]
        self.assertFalse(entry["complete"])
        self.assertIsNone(entry.get("http_status"))

    def test_paged_job_deadline_exceeded_is_partial(self):
        path = "/nba/v1/games"
        job = harvest._paged_job("nba", "games", path, {"seasons[]": [2024]},
                                  "nba_games_2024", "games", 1)
        client = ScriptedClient(rate_limit_errors={path: BallDontLieDeadlineExceeded(path)})
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["partial"], 1)
        self.assertEqual(summary["errored"], 0)

    def test_single_job_rate_limit_exhausted_is_partial_not_error(self):
        path = "/nfl/v1/standings"
        job = harvest._single_job("nfl", "standings", path, {"season": 2024},
                                   "nfl_standings_2024", "standings", 1)
        client = ScriptedClient(rate_limit_errors={path: BallDontLieRateLimitExhausted(path, 900.0)})
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})

        summary = harvest.run_plan([job], ctx)

        self.assertEqual(summary["partial"], 1)
        self.assertEqual(summary["errored"], 0)
        manifest = harvest.load_manifest(self.out_dir)
        entry = manifest["nfl/nfl_standings_2024.jsonl.gz"]
        self.assertFalse(entry["complete"])
        self.assertIsNone(entry.get("http_status"))
        # Not marked complete/errored, so a later run retries it.
        client.calls.clear()
        ctx2 = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest)
        harvest.run_plan([job], ctx2)
        self.assertEqual(len(client.calls), 1)

    def test_deadline_is_passed_through_to_the_client(self):
        path = "/nhl/v1/standings"
        job = harvest._single_job("nhl", "standings", path, {"season": 2024},
                                   "nhl_standings_2024", "standings", 1)

        class DeadlineCapturingClient:
            def __init__(self):
                self.seen_deadlines = []

            def get(self, path, params, *, deadline=None):
                self.seen_deadlines.append(deadline)
                return {"data": []}

        client = DeadlineCapturingClient()
        # Fixed clock well before the deadline -- RunContext.clock defaults
        # to the real time.monotonic() (process/system uptime), which can
        # already exceed a small test deadline like this one and make
        # run_plan's own pre-job check skip the job before it ever runs.
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={},
                                  deadline=123.0, clock=lambda: 0.0)

        harvest.run_plan([job], ctx)

        self.assertEqual(client.seen_deadlines, [123.0])


class TestResumeAfterReorder(unittest.TestCase):
    """Manifest entries and .cursor sidecars are keyed by output file name,
    not plan position -- reordering build_plan() must not break resume."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reordered_plan_still_resumes_completed_job_by_file_name(self):
        jobs = harvest.build_plan(["tennis"], only="atp_matches")
        job = jobs[0]  # newest season first under the new priority order
        client = ScriptedClient(page_script={
            (job.path, tuple(sorted((k, tuple(v) if isinstance(v, list) else v)
                                     for k, v in job.params.items()))): [[{"id": 1}]],
        })
        ctx = harvest.RunContext(client=client, out_dir=self.out_dir, manifest={})
        harvest.run_plan([job], ctx)

        manifest2 = harvest.load_manifest(self.out_dir)
        rel = f"tennis/{job.out_name}.jsonl.gz"
        self.assertIn(rel, manifest2)
        self.assertTrue(manifest2[rel]["complete"])

        client.calls.clear()
        ctx2 = harvest.RunContext(client=client, out_dir=self.out_dir, manifest=manifest2)
        summary2 = harvest.run_plan([job], ctx2)
        self.assertEqual(summary2["skipped"], 1)
        self.assertEqual(client.calls, [])


class TestDefect1SeasonParamNames(unittest.TestCase):
    """DEFECT 1: each sport's `games` job must use the exact season-filter
    key its own OpenAPI spec names -- confirmed 2026-09-15 by reading each
    spec's raw YAML directly (not a summary). NFL/MLB/NBA all spell it
    `seasons[]` (with brackets); NHL's spec spells the identical filter
    `seasons` (no brackets) -- a real per-sport inconsistency in the
    vendor's own docs (confirmed: NHL's own `dates` param on this same
    endpoint, and MLB's `dates` on /mlb/v1/odds, are ALSO unbracketed),
    not a bug to paper over by forcing every sport to match NFL/MLB/NBA."""

    def _first_games_job(self, sport):
        jobs = harvest.build_plan([sport], only="games")
        self.assertTrue(jobs, f"no games job built for {sport}")
        return jobs[0]

    def test_nfl_games_uses_bracketed_seasons(self):
        job = self._first_games_job("nfl")
        self.assertIn("seasons[]", job.params)
        self.assertNotIn("seasons", job.params)

    def test_mlb_games_uses_bracketed_seasons(self):
        job = self._first_games_job("mlb")
        self.assertIn("seasons[]", job.params)
        self.assertNotIn("seasons", job.params)

    def test_nba_games_uses_bracketed_seasons(self):
        job = self._first_games_job("nba")
        self.assertIn("seasons[]", job.params)
        self.assertNotIn("seasons", job.params)

    def test_nhl_games_uses_unbracketed_seasons(self):
        job = self._first_games_job("nhl")
        self.assertIn("seasons", job.params)
        self.assertNotIn("seasons[]", job.params)


class TestDefect2NoUnfilteredOddsJobs(unittest.TestCase):
    """DEFECT 2: MLB/NBA/NHL's `.../odds` and `.../odds/opening` specs both
    say "Either dates or game_ids is required"; tennis's `.../odds/opening`
    accepts `season`. An unfiltered call to any of them 400'd in production
    (see MANIFEST.json) -- the plan must never build one of those again, and
    must no longer emit the exact output names that recorded those 400s."""

    OLD_UNFILTERED_NAMES = {
        ("mlb", "mlb_odds"), ("mlb", "mlb_odds_opening"),
        ("nba", "nba_odds"), ("nba", "nba_odds_opening"),
        ("nhl", "nhl_odds"), ("nhl", "nhl_odds_opening"),
        ("tennis", "atp_odds_opening"), ("tennis", "wta_odds_opening"),
    }

    def test_no_job_has_empty_params_for_an_odds_endpoint(self):
        for sport in ("mlb", "nba", "nhl", "tennis"):
            for job in harvest.build_plan([sport]):
                if "odds" in job.endpoint:
                    self.assertTrue(
                        job.params,
                        f"{job.sport}/{job.out_name} ({job.endpoint}) is an unfiltered odds job")

    def test_old_unfiltered_out_names_no_longer_emitted(self):
        jobs = harvest.build_plan(harvest.ALL_SPORTS)
        names = {(j.sport, j.out_name) for j in jobs}
        for old in self.OLD_UNFILTERED_NAMES:
            self.assertNotIn(old, names)


class TestDefect2OddsSweepShape(unittest.TestCase):
    """DEFECT 2: the odds sweep jobs must use the exact per-endpoint filter
    key each spec confirms, run newest-season-first, and never collide in
    output name with each other or with the retired unfiltered jobs."""

    def test_mlb_odds_swept_one_job_per_date(self):
        jobs = harvest.build_plan(["mlb"], only="odds")
        self.assertTrue(jobs)
        for job in jobs:
            self.assertEqual(set(job.params.keys()), {"dates"})
            self.assertEqual(len(job.params["dates"]), 1)

    def test_nba_odds_and_odds_opening_use_different_literal_date_keys(self):
        # Confirmed against nba.yml directly: /nba/v2/odds pulls in the
        # shared DatesParam component, which nba.yml itself defines as
        # `dates[]`; /nba/v2/odds/opening inlines `dates` (no brackets) --
        # a real inconsistency within one sport's own spec, not a typo.
        odds_jobs = harvest.build_plan(["nba"], only="odds")
        opening_jobs = harvest.build_plan(["nba"], only="odds_opening")
        self.assertTrue(odds_jobs)
        self.assertTrue(opening_jobs)
        self.assertIn("dates[]", odds_jobs[0].params)
        self.assertIn("dates", opening_jobs[0].params)
        self.assertNotIn("dates[]", opening_jobs[0].params)

    def test_nhl_odds_swept_one_job_per_date(self):
        jobs = harvest.build_plan(["nhl"], only="odds")
        self.assertTrue(jobs)
        for job in jobs:
            self.assertEqual(set(job.params.keys()), {"dates"})

    def test_tennis_odds_opening_swept_one_job_per_season_within_coverage_window(self):
        jobs = harvest.build_plan(["tennis"], only="atp_odds_opening")
        self.assertTrue(jobs)
        for job in jobs:
            self.assertEqual(set(job.params.keys()), {"season"})
        seasons = sorted(job.params["season"] for job in jobs)
        self.assertEqual(seasons, list(harvest.OPENING_ODDS_SEASON_RANGE))

    def test_odds_sweeps_are_newest_season_first(self):
        for sport in ("mlb", "nba", "nhl"):
            jobs = harvest.build_plan([sport], only="odds")
            self.assertEqual(jobs[0].priority_season, harvest._CEILING_YEAR,
                              f"{sport} odds sweep's first job is not the newest season")

    def test_output_names_unique_across_full_plan_with_odds_sweep(self):
        jobs = harvest.build_plan(harvest.ALL_SPORTS)
        names = [(j.sport, j.out_name) for j in jobs]
        self.assertEqual(len(names), len(set(names)))

    def test_dry_run_builds_odds_sweep_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = harvest.main(["--dry-run", "--sports", "mlb,nba,nhl,tennis", "--out-dir", tmp])
            self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("mlb_odds_", out)
        self.assertIn("nba_odds_", out)
        self.assertIn("nhl_odds_", out)
        self.assertIn("atp_odds_opening_", out)
        self.assertNotIn("mlb_odds.jsonl", out)
        self.assertNotIn("nba_odds.jsonl", out)
        self.assertNotIn("nhl_odds.jsonl", out)


class TestGameDatesFromFile(unittest.TestCase):
    """The odds sweep's date enumeration: real dates from an already-
    harvested games file when one exists, a generated fallback window when
    it does not."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_games_file(self, sport, season, rows):
        path = harvest._out_path(self.out_dir, sport, f"{sport}_games_{season}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        return path

    def test_reads_distinct_sorted_dates_from_mlb_style_date_field(self):
        self._write_games_file("mlb", 2024, [
            {"id": 1, "date": "2024-04-02"},
            {"id": 2, "date": "2024-04-01"},
            {"id": 3, "date": "2024-04-02"},  # same date, different game
        ])
        dates = harvest._game_dates_from_file(self.out_dir, "mlb", 2024)
        self.assertEqual(dates, ["2024-04-01", "2024-04-02"])

    def test_reads_nhl_style_game_date_field(self):
        self._write_games_file("nhl", 2024, [{"id": 1, "game_date": "2024-01-05"}])
        dates = harvest._game_dates_from_file(self.out_dir, "nhl", 2024)
        self.assertEqual(dates, ["2024-01-05"])

    def test_missing_file_returns_empty(self):
        self.assertEqual(harvest._game_dates_from_file(self.out_dir, "mlb", 1999), [])

    def test_dates_for_odds_sweep_falls_back_cleanly_when_file_missing(self):
        dates = harvest._dates_for_odds_sweep(self.out_dir, "mlb", 2024)
        self.assertTrue(dates)
        self.assertEqual(dates, harvest._fallback_date_range("mlb", 2024))

    def test_dates_for_odds_sweep_prefers_the_real_file_over_the_fallback(self):
        self._write_games_file("mlb", 2024, [{"id": 1, "date": "2024-07-04"}])
        dates = harvest._dates_for_odds_sweep(self.out_dir, "mlb", 2024)
        self.assertEqual(dates, ["2024-07-04"])


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
