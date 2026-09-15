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
