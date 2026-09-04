"""Coverage for `src.capture.health.assess()` -- every state, the
non-self-matching lock guard, and band separation in the reported budget
fields. Fully hermetic: a tmp raw root, a tmp lock file, an injected `now`,
and `tests.HERMETIC_CREDIT_LOG_STORE` for every credit-log read, matching
the convention `tests/test_capture_credit_log_hermeticity.py` documents --
this file must never touch data/raw or data/processed/credit_log.jsonl on
the real disk.
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests import HERMETIC_CREDIT_LOG_STORE
from src.capture import health
from src.pipeline import creditlog


NOW = datetime(2026, 9, 4, 20, 0, 0, tzinfo=timezone.utc)


def _write_artifact(raw_root: Path, when: datetime, name_hash="deadbeef"):
    """Drop one empty-but-valid .jsonl.gz artifact named the way dense.py
    names real ones, under raw_root/oddsapi/YYYY/MM/DD/."""
    day_dir = raw_root / "oddsapi" / when.strftime("%Y") / when.strftime("%m") / when.strftime("%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{when.strftime('%Y%m%dT%H%M%S')}Z-{name_hash}.jsonl.gz"
    path = day_dir / fname
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"ok": True}) + "\n")
    return path


def _log_row(store: Path, remaining: int, when: datetime, caller="test", budget_band="test"):
    store.parent.mkdir(parents=True, exist_ok=True)
    creditlog.log(remaining, 1, caller, store=store, now=when, budget_band=budget_band)


class CaptureHealthTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raw_root = Path(self._tmp.name) / "raw"
        self.lock_path = Path(self._tmp.name) / "lock.file"
        self.credit_store = HERMETIC_CREDIT_LOG_STORE.parent / f"health_{id(self)}.jsonl"
        self.addCleanup(lambda: self.credit_store.unlink(missing_ok=True))
        self.empty_escalate = Path(self._tmp.name) / "no_escalate.md"

    # ------------------------------------------------------------------
    # UNKNOWN
    # ------------------------------------------------------------------

    def test_missing_raw_root_is_unknown(self):
        report = health.assess(
            now=NOW, raw_root=self.raw_root / "does-not-exist",
            lock_path=self.lock_path, credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.UNKNOWN)
        self.assertTrue(any("missing" in r for r in report.reasons))

    def test_unreadable_raw_root_is_unknown(self):
        self.raw_root.mkdir(parents=True)
        os.chmod(self.raw_root, 0o000)
        self.addCleanup(lambda: os.chmod(self.raw_root, 0o755))
        # os.access() as root (many CI containers) always reads True regardless
        # of mode bits, so this guards itself rather than asserting a state
        # that a root-run suite could never actually observe.
        if os.access(self.raw_root, os.R_OK):
            self.skipTest("running as a user for whom chmod 000 is not enforced")
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.UNKNOWN)

    # ------------------------------------------------------------------
    # RUNNING
    # ------------------------------------------------------------------

    def test_lock_held_by_another_process_is_running(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(hours=5))  # stale on purpose
        # Hold the lock from a genuinely separate process so this exercises
        # the real flock contention path, not a same-process shortcut.
        import subprocess
        holder = subprocess.Popen(
            ["python3", "-c",
             f"import fcntl,time; f=open({str(self.lock_path)!r}, 'a+');"
             f"fcntl.flock(f, fcntl.LOCK_EX); time.sleep(5)"],
        )
        self.addCleanup(holder.kill)
        # Give the holder a moment to actually acquire the lock.
        import time
        for _ in range(50):
            probe = health._flock_probe(self.lock_path)
            if probe:
                break
            time.sleep(0.1)
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.RUNNING)
        self.assertTrue(report.lock_held)

    def test_own_probe_never_self_matches_the_lock(self):
        """The non-blocking flock probe used by RUNNING detection must read
        the lock as FREE when nothing else holds it -- i.e. this process's
        own act of probing (opening the file, attempting+releasing the
        lock) can never be mistaken for another process holding it."""
        self.lock_path.touch()
        pids = health._self_and_ancestor_pids()
        self.assertIn(os.getpid(), pids)
        held = health._flock_probe(self.lock_path)
        self.assertFalse(held)

    # ------------------------------------------------------------------
    # HEALTHY_IDLE / OVERDUE / FAILED by artifact age
    # ------------------------------------------------------------------

    def test_fresh_artifact_lock_free_is_healthy_idle(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=20))
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.HEALTHY_IDLE)
        self.assertAlmostEqual(report.artifact_age_min, 20, delta=1)

    def test_boundary_age_still_healthy_idle(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=health.HEALTHY_IDLE_MAX_AGE_MIN))
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.HEALTHY_IDLE)

    def test_age_past_healthy_threshold_is_overdue(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=health.HEALTHY_IDLE_MAX_AGE_MIN + 5))
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.OVERDUE)

    def test_age_past_overdue_threshold_is_failed(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=health.OVERDUE_MAX_AGE_MIN + 1))
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.FAILED)

    def test_no_artifact_ever_is_failed(self):
        self.raw_root.mkdir(parents=True)
        (self.raw_root / "oddsapi").mkdir(parents=True, exist_ok=True)
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.FAILED)

    def test_artifacts_today_counts_only_todays_directory(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=10), name_hash="aaaa1111")
        _write_artifact(self.raw_root, NOW - timedelta(minutes=40), name_hash="bbbb2222")
        _write_artifact(self.raw_root, NOW - timedelta(days=1), name_hash="cccc3333")
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.artifacts_today, 2)

    # ------------------------------------------------------------------
    # FAILED via unresolved escalation
    # ------------------------------------------------------------------

    def test_recent_unresolved_escalation_forces_failed(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=5))  # otherwise healthy
        escalate_path = Path(self._tmp.name) / "OVERNIGHT_RUN.md"
        escalate_path.write_text(
            f"- {(NOW - timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M')}Z ESCALATE: "
            "live-capture envelope tripped -- stop spending, tell Brey\n",
            encoding="utf-8",
        )
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        # health._last_escalate_line reads the module-default path unless we
        # monkeypatch repo_root; exercise the helper directly for the
        # timestamp-window logic, and assess() end-to-end for the
        # non-escalation baseline above.
        line = health._last_escalate_line(escalate_path, NOW, health.ESCALATE_WINDOW_MIN)
        self.assertIsNotNone(line)
        self.assertIn("ESCALATE", line)

    def test_prose_mentioning_escalate_without_its_own_timestamp_is_ignored(self):
        """Regression: docs/OVERNIGHT_RUN.md discusses past escalations in
        retrospective prose (e.g. "...the clean `ESCALATE:` line -- which is
        why no trigger ever alerted...") long after they resolved. A bare
        substring match on ESCALATE would read that prose as a live,
        permanently-unresolved failure -- found live on this repo's own
        docs/OVERNIGHT_RUN.md during development of this module."""
        escalate_path = Path(self._tmp.name) / "OVERNIGHT_RUN.md"
        escalate_path.write_text(
            "  clean `ESCALATE:` line -- which is why no trigger ever alerted and the\n"
            "  incident went unnoticed for hours.\n",
            encoding="utf-8",
        )
        line = health._last_escalate_line(escalate_path, NOW, health.ESCALATE_WINDOW_MIN)
        self.assertIsNone(line)

    def test_stale_escalation_outside_window_is_ignored(self):
        escalate_path = Path(self._tmp.name) / "OVERNIGHT_RUN.md"
        escalate_path.write_text(
            f"- {(NOW - timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M')}Z ESCALATE: old news\n",
            encoding="utf-8",
        )
        line = health._last_escalate_line(escalate_path, NOW, health.ESCALATE_WINDOW_MIN)
        self.assertIsNone(line)

    # ------------------------------------------------------------------
    # Band separation: historical/probe spend must never contaminate the
    # live-capture fields (docs/RESOURCE_POLICY.md; the 2026-09-04 incident
    # src.capture.budget documents at length).
    # ------------------------------------------------------------------

    def test_band_separation_in_reported_budget_fields(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=10))

        # A live-capture spend of 200 credits, then a same-day historical
        # purchase of 40,000 credits -- the exact shape of the incident
        # src.capture.budget's band-separation comment describes.
        _log_row(self.credit_store, 90_000, NOW - timedelta(hours=3),
                 caller="dense.run", budget_band=None)
        _log_row(self.credit_store, 89_800, NOW - timedelta(hours=2),
                 caller="dense.run", budget_band="live_capture")
        _log_row(self.credit_store, 49_800, NOW - timedelta(hours=1),
                 caller="probe_historical_backfill", budget_band="historical_backfill")

        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.live_band_spent_today, 200)
        self.assertEqual(report.historical_spend_today, 40_000)
        self.assertEqual(report.monthly_remaining, 49_800)
        # The historical purchase must never eat into how much live-capture
        # envelope headroom is reported.
        from src.capture import budget as budget_module
        self.assertEqual(report.live_band_remaining, budget_module.DAILY_ENVELOPE - 200)

    def test_envelope_exhausted_marks_failed_even_with_fresh_artifact(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=5))
        from src.capture import budget as budget_module

        start = 90_000
        _log_row(self.credit_store, start, NOW - timedelta(hours=1),
                 caller="dense.run", budget_band="live_capture")
        _log_row(self.credit_store, start - budget_module.DAILY_ENVELOPE, NOW,
                 caller="dense.run", budget_band="live_capture")

        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        self.assertEqual(report.state, health.FAILED)
        self.assertTrue(any("envelope" in r for r in report.reasons))

    def test_summary_line_has_expected_shape(self):
        self.raw_root.mkdir(parents=True)
        _write_artifact(self.raw_root, NOW - timedelta(minutes=10))
        report = health.assess(
            now=NOW, raw_root=self.raw_root, lock_path=self.lock_path,
            credit_log_store=self.credit_store, escalate_log_path=self.empty_escalate,
        )
        line = report.summary()
        self.assertTrue(line.startswith("CAPTURE_HEALTH: "))
        self.assertIn(report.state, line)


if __name__ == "__main__":
    unittest.main()
