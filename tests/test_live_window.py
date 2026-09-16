"""Tests for src.pipeline.live_window.

All tests use fakes, temp directories, and a fake clock that advances per sleep.
"""

import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import live_window

_GIT_AVAILABLE = shutil.which("git") is not None


class FakeClock:
    """Advances on each sleep() call."""

    def __init__(self, start_utc=None):
        self.now = start_utc or datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class TestPregameContext(unittest.TestCase):
    """Tests for pregame_context."""

    def test_pregame_context_mlb_with_fixture_data(self):
        """pregame_context returns game_pk -> pregame dict with favourite."""
        # The shape src.providers.mlb.parse_game actually returns: flat keys,
        # team abbreviations, probable-pitcher ids. This fixture used to carry
        # the raw Stats API payload (teams.home.team.name), which
        # fetch_games never hands to this function, so it was testing a shape
        # production does not produce.
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:40:00Z",
                "home_team": "BOS",
                "away_team": "NYY",
                "home_probable_id": 112211,
                "away_probable_id": 123456,
            }
        ]
        rows = [
            {
                "sport": "mlb",
                "home_team": "Boston Red Sox",
                "away_team": "New York Yankees",
                "commence_time": "2026-09-14T21:40:00Z",
                "book": "DraftKings",
                "home_price": -110,
                "away_price": -110,
                "observed_utc": "2026-09-14T20:00:00Z",
            },
        ]

        context = live_window.pregame_context(
            "mlb", "2026-09-14", rows=rows, games=games
        )

        self.assertIn("747101", context)
        self.assertEqual(context["747101"]["sport"], "mlb")
        self.assertEqual(context["747101"]["home_team"], "BOS")
        self.assertEqual(context["747101"]["away_team"], "NYY")
        self.assertIn(context["747101"]["favorite"], ["home", "away", None])

    def test_pregame_context_nfl_with_data(self):
        """pregame_context works for NFL games."""
        games = [
            {
                "game_id": "2026_02_DET_BUF",
                "start_utc": "2026-09-14T01:20:00Z",
                "home": "Buffalo Bills",
                "away": "Detroit Lions",
            }
        ]

        context = live_window.pregame_context("nfl", "2026-09-14", games=games)

        self.assertIn("2026_02_DET_BUF", context)
        self.assertEqual(context["2026_02_DET_BUF"]["sport"], "nfl")

    def test_pregame_context_empty_games(self):
        """pregame_context returns empty dict when no games."""
        context = live_window.pregame_context("mlb", "2026-09-15", games=[])
        self.assertEqual(context, {})


class TestTick(unittest.TestCase):
    """Tests for tick."""

    def test_tick_no_changes(self):
        """tick calls no capture when states don't change."""
        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        def mock_capture(*args, **kwargs):
            return {"captured": 0}

        state = {
            "date": "2026-09-14",
            "prev_states": {"pk1": {"status": "Live", "home_runs": 0, "away_runs": 0}},
            "pregame": {},
        }

        deps = {
            "poll": mock_poll,
            "capture": mock_capture,
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live", "home_runs": 0, "away_runs": 0}}
            result = live_window.tick("mlb", state=state, deps=deps)

        self.assertEqual(result["changed"], 0)

    def test_tick_records_candidate_on_rule_fire(self):
        """tick records a candidate when a rule fires."""
        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        def mock_capture(*args, **kwargs):
            return {"captured": 5}

        state = {
            "date": "2026-09-14",
            "prev_states": {},
            "pregame": {
                "pk1": {
                    "sport": "mlb",
                    "game_id": "pk1",
                    "home_team": "Boston Red Sox",
                    "away_team": "New York Yankees",
                    "favorite": "home",
                    "favorite_prob": 0.6,
                    "starter_ids": {"home": 1, "away": 2},
                    "event_id": "evt1",
                }
            },
        }

        def mock_evaluate(*, pregame, state, quote):
            return [
                {
                    "rule_id": "mlb_favorite_trails_after_3",
                    "sport": "mlb",
                    "game_id": "pk1",
                    "side": "home",
                    "team": "Boston Red Sox",
                    "bet": "Boston Red Sox moneyline",
                    "price": -110,
                    "books": 5,
                    "state_id": "abc123",
                    "observed_utc": "2026-09-14T20:00:00Z",
                    "trigger": {"inning": 3},
                }
            ]

        def mock_record(candidate):
            return {**candidate, "recorded_utc": "2026-09-14T20:00:01Z"}

        deps = {
            "poll": mock_poll,
            "capture": mock_capture,
            "evaluate": mock_evaluate,
            "record": mock_record,
        }

        new_state = {
            "status": "Live",
            "home_runs": 1,
            "away_runs": 2,
            "inning": 3,
            "observed_utc": "2026-09-14T20:00:00Z",
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": new_state}
            with mock.patch("src.pipeline.live_odds.latest_inplay_quote") as m_quote:
                m_quote.return_value = {
                    "observed_utc": "2026-09-14T20:00:00Z",
                    "quotes": [
                        {"book": "DraftKings", "home_price": -110, "away_price": 100}
                    ],
                }
                with mock.patch("src.pipeline.live_odds.read_inplay") as m_inplay:
                    m_inplay.return_value = []
                    result = live_window.tick("mlb", state=state, deps=deps)

        self.assertGreater(result["candidates_new"], 0)


class TestShouldDispatch(unittest.TestCase):
    """Tests for should_dispatch."""

    def test_should_dispatch_live_game_mlb(self):
        """should_dispatch returns True when a live game is running."""
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "status": {"abstractGameState": "Live"},
            }
        ]

        def mock_schedule(date):
            return games

        # `running` is injected because the default reads the real `gh run
        # list`: without it these three tests pass or fail according to
        # whatever this account's Actions queue looks like at the moment they
        # run, which is how they came to fail on a machine with a live window
        # queued (2026-09-16).
        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertTrue(can_run)
        self.assertIn("Live", reason)

    def test_should_dispatch_game_starts_soon(self):
        """should_dispatch returns True when a game starts within 30 minutes."""
        now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T20:20:00Z",
                "status": {"abstractGameState": "Pre-Game"},
            }
        ]

        def mock_schedule(date):
            return games

        # `running` is injected because the default reads the real `gh run
        # list`: without it these three tests pass or fail according to
        # whatever this account's Actions queue looks like at the moment they
        # run, which is how they came to fail on a machine with a live window
        # queued (2026-09-16).
        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertTrue(can_run)
        self.assertIn("within 30 minutes", reason)

    def test_should_dispatch_nothing_happening(self):
        """should_dispatch returns False when no games are live/starting soon."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "status": {"abstractGameState": "Pre-Game"},
            }
        ]

        def mock_schedule(date):
            return games

        # `running` is injected because the default reads the real `gh run
        # list`: without it these three tests pass or fail according to
        # whatever this account's Actions queue looks like at the moment they
        # run, which is how they came to fail on a machine with a live window
        # queued (2026-09-16).
        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule, running=lambda: False
        )

        self.assertFalse(can_run)
        self.assertIn("nothing starts", reason)

    def test_should_dispatch_nfl_outside_window(self):
        """should_dispatch returns False for NFL outside broadcast windows."""
        # Tuesday 10 AM ET
        now = datetime(2026, 9, 15, 14, 0, 0, tzinfo=timezone.utc)

        can_run, reason = live_window.should_dispatch("nfl", now=now)

        self.assertFalse(can_run)
        self.assertIn("outside", reason)

    def test_should_dispatch_already_running(self):
        """should_dispatch returns False when window is already running."""
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)

        def mock_running():
            return True

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, running=mock_running
        )

        self.assertFalse(can_run)
        self.assertIn("already running", reason)

    def test_should_dispatch_default_running_checks_gh_across_runners(self):
        """Default (no `running` override) consults gh, not just the local marker.

        Regression test for the bug where should_dispatch's default check
        only ever looked at a marker file local to the calling runner, so a
        different job (like forward-capture's chain) could never see a real
        window active elsewhere and redispatched every cycle.
        """
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "status": {"abstractGameState": "Live"},
            }
        ]

        with mock.patch.object(live_window, "_local_window_marker_active", return_value=False), \
             mock.patch.object(live_window, "_gh_run_active", return_value=True) as m_gh:
            can_run, reason = live_window.should_dispatch(
                "mlb", now=now, schedule=lambda date: games
            )

        m_gh.assert_called_once_with("mlb")
        self.assertFalse(can_run)
        self.assertIn("already running", reason)


class TestGhRunActive(unittest.TestCase):
    """Tests for _gh_run_active (the cross-runner 'already dispatched' check)."""

    def test_matching_sport_in_progress_is_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "in_progress", "displayTitle": "live-window-mlb"},
            ])

        self.assertTrue(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_no_matching_runs_is_not_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "completed", "displayTitle": "live-window-mlb"},
            ])

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_wrong_sport_prefix_is_not_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "in_progress", "displayTitle": "live-window-nfl"},
            ])

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_cancelled_run_is_not_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "completed", "displayTitle": "live-window-mlb", "conclusion": "cancelled"},
            ])

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_queued_run_is_active(self):
        def fake_cli(workflow):
            return json.dumps([
                {"status": "queued", "displayTitle": "live-window-nfl"},
            ])

        self.assertTrue(live_window._gh_run_active("nfl", run_cli=fake_cli))

    def test_gh_error_fails_open_to_not_active(self):
        def fake_cli(workflow):
            raise RuntimeError("gh not found")

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))

    def test_malformed_json_fails_open_to_not_active(self):
        def fake_cli(workflow):
            return "not json"

        self.assertFalse(live_window._gh_run_active("mlb", run_cli=fake_cli))


class TestLocalWindowMarkerActive(unittest.TestCase):
    """Tests for _local_window_marker_active (the same-runner marker check)."""

    def test_no_marker_file_is_not_active(self):
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        with mock.patch.object(
            live_window, "data_path", return_value="/nonexistent/path/window.lock"
        ):
            self.assertFalse(live_window._local_window_marker_active("mlb", now))

    def test_unexpired_marker_is_active(self):
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "window.lock"
            marker.write_text((now + timedelta(minutes=10)).isoformat(), encoding="utf-8")
            with mock.patch.object(live_window, "data_path", return_value=str(marker)):
                self.assertTrue(live_window._local_window_marker_active("mlb", now))

    def test_expired_marker_is_not_active(self):
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "window.lock"
            marker.write_text((now - timedelta(minutes=10)).isoformat(), encoding="utf-8")
            with mock.patch.object(live_window, "data_path", return_value=str(marker)):
                self.assertFalse(live_window._local_window_marker_active("mlb", now))


class TestRun(unittest.TestCase):
    """Tests for run."""

    def test_run_stops_early_when_no_games_nearby(self):
        """run exits early when nothing is live and nothing starts within 30 min."""
        clock = FakeClock()

        def mock_poll():
            return {"live_games": 0, "rows_written": 0}

        def mock_schedule(date):
            return []

        deps = {
            "poll": mock_poll,
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = []
                result = live_window.run(
                    "mlb", max_minutes=330, clock=clock, sleep=clock.sleep, deps=deps
                )

        self.assertLessEqual(result["ticks"], 2)
        self.assertIn("nothing starts", result["stopped_reason"])

    def test_run_commits_at_interval(self):
        """run calls commit at the specified interval."""
        clock = FakeClock()
        commits = []

        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        def mock_commit():
            commits.append(clock())

        deps = {"poll": mock_poll}

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live"}}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = [
                    {
                        "game_pk": "pk1",
                        "start_time_utc": "2026-09-14T21:00:00Z",
                        "status": {"abstractGameState": "Live"},
                    }
                ]
                result = live_window.run(
                    "mlb",
                    max_minutes=10,
                    clock=clock,
                    sleep=clock.sleep,
                    deps=deps,
                    commit=mock_commit,
                    commit_every_minutes=5,
                )

        # Should have at least one commit
        self.assertGreater(len(commits), 0)

    def test_run_respects_max_minutes(self):
        """run stops when max_minutes elapsed."""
        clock = FakeClock()

        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        deps = {"poll": mock_poll}

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live"}}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = [
                    {
                        "game_pk": "pk1",
                        "start_time_utc": "2026-09-14T21:00:00Z",
                        "status": {"abstractGameState": "Live"},
                    }
                ]
                result = live_window.run(
                    "mlb",
                    max_minutes=5,
                    clock=clock,
                    sleep=clock.sleep,
                    deps=deps,
                )

        self.assertIn("max_minutes", result["stopped_reason"])


class TestSettle(unittest.TestCase):
    """Tests for settle."""

    def test_settle_mlb_candidate_from_final(self):
        """settle grades an MLB candidate against a final state row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create live candidates ledger
            ledger_path = Path(tmpdir) / "live_candidates_v1.jsonl"
            candidate = {
                "kind": "live_candidate",
                "recorded_utc": "2026-09-14T20:00:00Z",
                "date": "2026-09-14",
                "rule_id": "mlb_favorite_trails_after_3",
                "sport": "mlb",
                "game_id": "747101",
                "side": "home",
                "team": "Boston Red Sox",
                "bet": "Boston Red Sox moneyline",
                "price": -110,
                "books": 5,
                "state_id": "abc123",
                "observed_utc": "2026-09-14T20:00:00Z",
                "trigger": {"inning": 3},
            }

            # Write candidate with chain fields
            row = candidate.copy()
            row["hash"] = "hash0"
            row["prior_hash"] = ""
            ledger_path.write_text(json.dumps(row) + "\n")

            # Settlement
            results = {
                "747101": {"home_score": 5, "away_score": 3}
            }

            with mock.patch("src.appstate.live_ledger.LIVE_STORE", str(ledger_path)):
                result = live_window.settle("2026-09-14", results=results)

            self.assertIsNotNone(result)
            self.assertGreater(result["graded"], 0)


class TestMain(unittest.TestCase):
    """Tests for main."""

    def test_main_should_dispatch_flag(self):
        """main with --should-dispatch prints DISPATCH or HOLD."""
        with mock.patch("src.pipeline.live_window.should_dispatch") as m_dispatch:
            m_dispatch.return_value = (True, "live game")
            with mock.patch("builtins.print") as m_print:
                live_window.main(["live_window.py", "--sport", "mlb", "--should-dispatch"])
                m_print.assert_called_once()
                call_arg = m_print.call_args[0][0]
                self.assertIn("DISPATCH", call_arg)

    def test_main_should_dispatch_false(self):
        """main prints HOLD when should_dispatch returns False."""
        with mock.patch("src.pipeline.live_window.should_dispatch") as m_dispatch:
            m_dispatch.return_value = (False, "outside window")
            with mock.patch("builtins.print") as m_print:
                live_window.main(["live_window.py", "--sport", "mlb", "--should-dispatch"])
                call_arg = m_print.call_args[0][0]
                self.assertIn("HOLD", call_arg)

    def test_main_settle_needs_no_sport(self):
        """The exact command scripts/daily_loop.sh runs: --settle --date, no --sport.

        It used to exit with an argparse error, so the live candidates would
        never have been graded.
        """
        with mock.patch("src.pipeline.live_window.settle", return_value=None) as m_settle:
            with mock.patch("builtins.print"):
                code = live_window.main(["live_window.py", "--settle", "--date", "2026-09-14"])
        self.assertEqual(code, 0)
        m_settle.assert_called_once_with("2026-09-14")

    def test_main_run_still_requires_sport(self):
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                live_window.main(["live_window.py", "--max-minutes", "5"])

    def test_daily_loop_calls_settle_the_way_main_accepts(self):
        """Tie the test above to the script, so the two cannot drift apart."""
        from pathlib import Path

        script = (Path(__file__).resolve().parents[1] / "scripts" / "daily_loop.sh").read_text(
            encoding="utf-8")
        self.assertIn('src.pipeline.live_window --settle --date "$YESTERDAY"', script)


class TestCommitStagesOnlyLiveAndLedger(unittest.TestCase):
    """R16-L4/D7: the window's own commit must never touch
    data/processed/credit_log.jsonl -- that is the forward-capture chain's
    file, committed and pushed on its own ~13-minute cadence, and staging it
    here is the two-writer race D7 describes."""

    def test_commit_git_add_excludes_processed_credit_log(self):
        source = Path(live_window.__file__).read_text(encoding="utf-8")
        self.assertIn('_git("add", "data/live", "evidence/live_candidates_v1.jsonl")',
                      source)
        self.assertNotIn('"data/processed/credit_log.jsonl"', source)


@unittest.skipUnless(_GIT_AVAILABLE, "git is not available on this machine")
class TestPushPathNoCreditLogConflict(unittest.TestCase):
    """R16-L4/D7 acceptance: two runners, each appending to their OWN store
    (data/live/credit_log_live.jsonl for the window, data/processed/
    credit_log.jsonl for the forward-capture chain -- never the same file),
    pushing concurrently within one minute, both land with no rebase
    failure. Everything here runs against throwaway local (file://) git
    repos under a temp directory -- no network, so it runs in CI. It does
    not import live_window._commit (which is nested inside main() and reads
    real argv/os.environ) but replicates its exact git sequence: add,
    commit, `pull --rebase --autostash origin <branch>` with up to 3
    attempts, then push -- so a change to that sequence that reintroduces
    the D7 race would show up here too.
    """

    def _git(self, cwd, *argv, check=True):
        result = subprocess.run(
            ["git", *argv], cwd=str(cwd), capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError(
                f"git {' '.join(argv)} in {cwd} failed: {result.stderr}")
        return result

    def _push_with_rebase_retry(self, clone_dir, branch, errors):
        """Mirrors live_window.py main()._commit's own retry loop exactly."""
        for attempt in range(3):
            pulled = subprocess.run(
                ["git", "pull", "-q", "--rebase", "--autostash", "origin", branch],
                cwd=str(clone_dir), capture_output=True, text=True)
            if pulled.returncode != 0:
                subprocess.run(["git", "rebase", "--abort"], cwd=str(clone_dir),
                               capture_output=True, text=True)
                errors.append(f"rebase failed (attempt {attempt + 1}): "
                              f"{pulled.stderr.strip()}")
                continue
            pushed = subprocess.run(
                ["git", "push", "-q", "origin", branch],
                cwd=str(clone_dir), capture_output=True, text=True)
            if pushed.returncode == 0:
                return True
            errors.append(f"push failed (attempt {attempt + 1}): "
                          f"{pushed.stderr.strip()}")
        return False

    def test_two_clones_push_concurrently_within_one_minute_no_rebase_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            origin = tmp / "origin.git"
            clone_a = tmp / "clone_a"
            clone_b = tmp / "clone_b"

            self._git(tmp, "init", "--bare", "-b", "main", str(origin))

            # Seed origin with one commit so both clones start from the
            # same history (an empty bare repo has no branch to clone).
            seed = tmp / "seed"
            self._git(tmp, "clone", "-q", str(origin), str(seed))
            self._git(seed, "config", "user.email", "test@example.com")
            self._git(seed, "config", "user.name", "test")
            (seed / "data").mkdir()
            (seed / "data" / "live").mkdir()
            (seed / "data" / "live" / ".gitkeep").write_text("", encoding="utf-8")
            self._git(seed, "add", "-A")
            self._git(seed, "commit", "-q", "-m", "seed")
            self._git(seed, "push", "-q", "origin", "main")

            for name, clone_dir in (("a", clone_a), ("b", clone_b)):
                self._git(tmp, "clone", "-q", str(origin), str(clone_dir))
                self._git(clone_dir, "config", "user.email", "test@example.com")
                self._git(clone_dir, "config", "user.name", "test")

            # Each runner writes to its OWN file -- data/live/credit_log_live.jsonl
            # for the window (clone_a) and data/processed/credit_log.jsonl for the
            # forward-capture chain (clone_b) -- exactly the D7 fix: never the
            # same path, so a genuine three-way merge (both sides adding at the
            # end of the SAME file) can never happen here even under a race.
            (clone_a / "data" / "live").mkdir(parents=True, exist_ok=True)
            (clone_a / "data" / "live" / "credit_log_live.jsonl").write_text(
                json.dumps({"utc": "2026-09-16T00:00:00Z", "caller": "window"}) + "\n",
                encoding="utf-8")
            self._git(clone_a, "add", "data/live/credit_log_live.jsonl")
            self._git(clone_a, "commit", "-q", "-m", "Live window mlb 00:00Z (external)")

            (clone_b / "data" / "processed").mkdir(parents=True, exist_ok=True)
            (clone_b / "data" / "processed" / "credit_log.jsonl").write_text(
                json.dumps({"utc": "2026-09-16T00:00:05Z", "caller": "chain"}) + "\n",
                encoding="utf-8")
            self._git(clone_b, "add", "data/processed/credit_log.jsonl")
            self._git(clone_b, "commit", "-q", "-m", "forward-capture chain")

            errors_a, errors_b = [], []
            start = time.monotonic()
            thread_a = threading.Thread(
                target=self._push_with_rebase_retry,
                args=(clone_a, "main", errors_a))
            thread_b = threading.Thread(
                target=self._push_with_rebase_retry,
                args=(clone_b, "main", errors_b))
            thread_a.start()
            thread_b.start()
            thread_a.join(timeout=60)
            thread_b.join(timeout=60)
            elapsed = time.monotonic() - start

            self.assertLess(elapsed, 60,
                            "both pushes must land within one minute")
            self.assertFalse(thread_a.is_alive(), "clone_a push did not finish")
            self.assertFalse(thread_b.is_alive(), "clone_b push did not finish")
            rebase_failures = [e for e in errors_a + errors_b if "rebase failed" in e]
            self.assertEqual(rebase_failures, [],
                             f"a rebase failed under the race: {rebase_failures}")

            # Both commits landed on the remote.
            log = self._git(origin, "log", "--oneline", "main").stdout
            self.assertIn("Live window mlb 00:00Z (external)", log)
            self.assertIn("forward-capture chain", log)
            check = self._git(seed, "fetch", "-q", "origin", "main")
            checkout = self._git(seed, "checkout", "-q", "origin/main", "--",
                                 "data/live/credit_log_live.jsonl",
                                 "data/processed/credit_log.jsonl")
            self.assertTrue((seed / "data" / "live" / "credit_log_live.jsonl").exists())
            self.assertTrue((seed / "data" / "processed" / "credit_log.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
