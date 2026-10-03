"""The refresh child and the container guard on a 1 GB machine (2026-10-03,
review items 6 and 7).

ITEM 6, OOM PRIORITY. The web server and the refresh child share one small
machine. If memory truly runs out the kernel must kill the refresh, never the
web server: the child raises its OWN `oom_score_adj` to 1000, the maximum
(raising your own score needs no privilege). Linux only; a no-op elsewhere. The
write is injected here, so the call path is proved on a machine with no /proc.

ITEM 7, OVERLAP WITH THE WARM-UP. The guard waited for the FIRST warm-up pass,
but the warm-up repeats every 600 s and page caches rebuild in the background
(each peaks near 540 MB on the 1 GB machine). A guard tick that finds a pass or a
rebuild running is now SKIPPED, not blocked on, and asked again in a minute
instead of an hour. The busy check is the warm-up's own status plus
`src.appstate.freshness`'s one-build-at-a-time counter, handed in by api/app.py.

Temp roots and injected clocks, waits and children. No sleeping, no network.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import display_refresh as dr, history, store_freshness as sf

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:                                     # pragma: no cover
    _HAVE_FASTAPI = False

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)


class TheRefreshChildAsksToBeKilledFirst(unittest.TestCase):

    def test_on_linux_it_writes_the_maximum_to_the_processes_own_score(self):
        calls = []
        note = dr.raise_oom_priority(platform="linux", writer=lambda path, text: calls.append((path, text)))
        self.assertIsNone(note)
        self.assertEqual(calls, [("/proc/self/oom_score_adj", "1000")])
        self.assertEqual(dr.OOM_SCORE_ADJ, 1000)

    def test_a_given_value_is_passed_through(self):
        calls = []
        dr.raise_oom_priority(500, platform="linux", writer=lambda path, text: calls.append(text))
        self.assertEqual(calls, ["500"])

    def test_it_is_a_no_op_off_linux(self):
        for platform in ("win32", "darwin", "cygwin", "freebsd14"):
            calls = []
            self.assertIsNone(dr.raise_oom_priority(
                platform=platform, writer=lambda path, text: calls.append(text)), platform)
            self.assertEqual(calls, [], platform)

    def test_a_write_that_fails_is_a_note_never_an_exception(self):
        def refuse(path, text):
            raise PermissionError(13, "denied")
        note = dr.raise_oom_priority(platform="linux", writer=refuse)
        self.assertIn("could not raise oom_score_adj", note)
        self.assertIn("denied", note)

    def test_the_real_writer_puts_the_value_in_the_file_it_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "oom_score_adj"
            self.assertIsNone(dr.raise_oom_priority(platform="linux", path=str(target)))
            self.assertEqual(target.read_text(encoding="ascii"), "1000")

    def test_the_guards_child_command_asks_for_it(self):
        seen = {}

        def runner(cmd, **kw):
            seen["cmd"] = cmd
            return mock.Mock(returncode=0, stdout="display refresh: through x\n")

        dr._run_child("/tmp/data", runner=runner)
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--oom-score-adj") + 1], "1000")
        self.assertIn("--max-memory-mb", cmd)          # the address-space cap is still there

    def test_the_cli_applies_it_when_asked_and_only_then(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "historical").mkdir()
            asked = []
            with mock.patch("builtins.print"):
                self.assertEqual(dr.main(["--root", tmp, "--check", "--oom-score-adj", "1000"],
                                         oom=lambda value: asked.append(value)), 0)
                self.assertEqual(asked, [1000])
                asked.clear()
                self.assertEqual(dr.main(["--root", tmp, "--check"], oom=lambda value: asked.append(value)), 0)
                self.assertEqual(asked, [])

    def test_a_failed_write_is_printed_and_the_run_goes_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "historical").mkdir()
            with mock.patch("builtins.print") as printed:
                rc = dr.main(["--root", tmp, "--check", "--oom-score-adj", "1000"],
                             oom=lambda value: "could not raise oom_score_adj: nope")
            self.assertEqual(rc, 0)
            self.assertTrue([c for c in printed.call_args_list if "could not raise" in str(c.args[0])])

    def test_a_real_child_process_takes_the_flag_on_any_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "historical").mkdir()
            done = subprocess.run(
                [sys.executable, "-m", "src.pipeline.display_refresh", "--root", tmp, "--check",
                 "--oom-score-adj", "1000"], cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertIn('"core_stale"', done.stdout)


class _StaleRoot(unittest.TestCase):
    """A data root whose core stores are all absent, so every tick wants a
    refresh."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "historical").mkdir()
        sf.reset_cache_for_tests()
        self.children = []

    def child(self, root):
        self.children.append(root)
        return {"exit": 0, "result": "ok"}


class TheGuardSkipsACycleWhileTheMachineIsBusy(_StaleRoot):

    def test_a_stale_store_is_not_refreshed_while_a_build_runs(self):
        decision = dr.guard_tick(now=NOW, root=self.root, child=self.child,
                                 busy=lambda: "a page cache is being rebuilt")
        self.assertFalse(decision["ran"])
        self.assertTrue(decision["busy"])
        self.assertIn("skipped this cycle", decision["reason"])
        self.assertIn("a page cache is being rebuilt", decision["reason"])
        self.assertEqual(self.children, [])
        self.assertIn("mlb_results", decision["core_stale"])

    def test_it_runs_the_moment_nothing_is_running(self):
        decision = dr.guard_tick(now=NOW, root=self.root, child=self.child, busy=lambda: None)
        self.assertTrue(decision["ran"])
        self.assertEqual(len(self.children), 1)

    def test_with_no_busy_check_it_behaves_as_before(self):
        self.assertTrue(dr.guard_tick(now=NOW, root=self.root, child=self.child)["ran"])

    def test_current_stores_do_not_even_ask(self):
        hist = self.root / "historical"
        day = "2026-10-02"
        history.write_manifest({day: {"total": 0, "final": 0, "pending": 0, "cancelled": 0}},
                               hist / "mlb_results.manifest.json")
        (hist / "mlb_results.csv").write_text("game_pk,date,game_type\n", encoding="utf-8")
        (hist / "bullpen_log.jsonl").write_text('{"date": "2026-10-02", "empty": true}\n', encoding="utf-8")
        (hist / "standings.jsonl").write_text('{"date": "2026-10-02", "team_abbrev": "NYY"}\n', encoding="utf-8")
        (hist / "pitcher_logs.jsonl").write_text(
            '{"person_id": 1, "season": "2026", "date": null, "empty": true, '
            '"checked_utc": "2026-10-03T10:00:00+00:00"}\n', encoding="utf-8")
        sf.reset_cache_for_tests()
        asked = []
        decision = dr.guard_tick(now=NOW, root=self.root, child=self.child,
                                 busy=lambda: asked.append(1) or "busy")
        self.assertEqual(decision["reason"], "core stores current")
        self.assertEqual(asked, [])

    def test_the_minimum_gap_is_decided_before_busy_is_asked(self):
        asked = []
        decision = dr.guard_tick(now=NOW, root=self.root, last_run_at=1000.0,
                                 clock=lambda: 1060.0, child=self.child,
                                 busy=lambda: asked.append(1) or "busy")
        self.assertEqual(decision["reason"], "refreshed recently; waiting")
        self.assertNotIn("busy", decision)
        self.assertEqual(asked, [])


class TheGuardLoopAsksAgainSoon(_StaleRoot):

    def setUp(self):
        super().setUp()
        saved = dict(dr._GUARD_STATUS)
        self.addCleanup(lambda: (dr._GUARD_STATUS.clear(), dr._GUARD_STATUS.update(saved)))

    def run_loop(self, answers, stop_after):
        waits = []

        def fake_wait(seconds):
            waits.append(seconds)
            return len(waits) >= stop_after

        feed = iter(answers)
        thread = dr.start_background_guard(
            env={dr.ENV_GUARD_INTERVAL: "3600", dr.ENV_GUARD_DELAY: "0"}, root=self.root,
            child=self.child, sleep=fake_wait, busy=lambda: next(feed))
        thread.join(30)
        self.assertFalse(thread.is_alive())
        return waits

    def test_a_skipped_cycle_is_retried_in_a_minute_not_an_hour(self):
        before = dr.guard_status()
        waits = self.run_loop(["a cache warm-up pass is running", None], stop_after=3)
        self.assertEqual(waits, [0.0, dr.GUARD_BUSY_RETRY_S, 3600.0])
        self.assertEqual(len(self.children), 1, "it ran once, on the second look")
        after = dr.guard_status()
        self.assertEqual(after["busy_skips"] - before["busy_skips"], 1)
        self.assertEqual(after["runs"] - before["runs"], 1)

    def test_a_machine_that_stays_busy_never_starts_the_child_and_keeps_asking(self):
        waits = self.run_loop(["warm-up"] * 10, stop_after=6)
        self.assertEqual(self.children, [])
        self.assertEqual(waits, [0.0] + [dr.GUARD_BUSY_RETRY_S] * 5)
        self.assertIn("skipped this cycle", dr.guard_status()["last_result"])

    def test_a_busy_check_that_raises_costs_a_cycle_not_the_thread(self):
        def broken():
            raise RuntimeError("status unavailable")
        waits = []

        def fake_wait(seconds):
            waits.append(seconds)
            return len(waits) >= 3

        thread = dr.start_background_guard(
            env={dr.ENV_GUARD_INTERVAL: "3600", dr.ENV_GUARD_DELAY: "0"}, root=self.root,
            child=self.child, sleep=fake_wait, busy=broken)
        thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.children, [])
        self.assertIn("guard error", dr.guard_status()["last_result"])
        self.assertEqual(waits[1:], [3600.0, 3600.0])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class TheAppHandsTheGuardItsBusyCheck(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api import app as app_mod
        from src.appstate import freshness
        cls.app_mod, cls.freshness = app_mod, freshness

    def test_a_running_warm_up_pass_is_busy(self):
        with mock.patch.object(self.app_mod.warmup, "status", return_value={"running": True}):
            self.assertIn("warm-up", self.app_mod._caches_busy())

    def test_a_running_cache_build_is_busy(self):
        with mock.patch.object(self.app_mod.warmup, "status", return_value={"running": False}), \
                mock.patch.object(self.freshness, "build_stats", return_value={"running": 1}):
            self.assertIn("rebuilt", self.app_mod._caches_busy())

    def test_an_idle_machine_is_not(self):
        with mock.patch.object(self.app_mod.warmup, "status", return_value={"running": False}), \
                mock.patch.object(self.freshness, "build_stats", return_value={"running": 0}):
            self.assertIsNone(self.app_mod._caches_busy())

    def test_the_real_one_build_at_a_time_gate_is_what_it_reads(self):
        with mock.patch.object(self.app_mod.warmup, "status", return_value={"running": False}):
            with self.freshness._gated_build():
                self.assertIn("rebuilt", self.app_mod._caches_busy())

    def test_the_startup_hook_passes_it_to_the_guard(self):
        with mock.patch.object(dr, "start_background_guard") as start:
            self.app_mod._start_display_refresh_guard()
        kwargs = start.call_args.kwargs
        self.assertIs(kwargs["busy"], self.app_mod._caches_busy)
        self.assertTrue(callable(kwargs["ready"]))


if __name__ == "__main__":
    unittest.main()
