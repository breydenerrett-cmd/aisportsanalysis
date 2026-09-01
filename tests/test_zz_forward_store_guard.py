"""The suite must leave the forward-evidence stores byte-for-byte untouched.

Named `test_zz_...` on purpose: `unittest discover` imports and runs modules in
sorted order, so this one runs last and its comparison covers every test that
came before it in the same process.

WHAT THIS IS DEFENDING AGAINST
------------------------------
data/processed/odds_*.jsonl and data/watch/*_watch.jsonl are append-only
records of prices and roster news observed at a moment. A row appended by a
test is not a bug that shows up as a red test -- it is a permanent, silent
falsification of the evidence the whole validation plan rests on, and it looks
exactly like a real capture. So:

  * tests/__init__.py BLOCKS such writes (defence), and
  * this module PROVES none happened (evidence), by comparing a sha256 taken
    at package-import time against one taken after the suite has run.

The two are not redundant. The blocker only covers writes that go through this
process's `open`/`os.open`; the fingerprint catches anything else -- a
subprocess, a C extension, a write through an fd that predates the patch.

WHY IT SKIPS DURING A LIVE CAPTURE
----------------------------------
scripts/forward_capture.sh runs hourly and appends to exactly these files. If
it fires mid-suite the fingerprints legitimately differ, and failing there
would train everyone to ignore this test -- the one outcome that must never
happen. So a live capture process means SKIP, loudly, never PASS-by-accident
and never a false red.
"""

from __future__ import annotations

import builtins
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import tests as suite


def _capture_is_running() -> bool:
    """True if scripts/forward_capture.sh is live right now.

    Reads /proc directly rather than shelling out to `ps`, so it works in the
    minimal containers this runs in. Any error answers "yes": if we cannot
    tell whether a capture is in flight, skipping is the safe call -- a
    false skip costs a check, a false failure costs trust in the check.
    """
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes()
            except (OSError, PermissionError):
                continue
            if b"forward_capture" in cmdline:
                return True
        return False
    except Exception:
        return True


class ForwardStoreWriteBlockerTests(unittest.TestCase):
    """The blocker installed by tests/__init__.py actually blocks."""

    def test_guard_is_installed(self):
        # If someone deletes the patching in tests/__init__.py, every other
        # assertion in this file becomes a coincidence. Check it explicitly.
        self.assertTrue(suite.WRITE_GUARD_INSTALLED)
        self.assertIsNot(builtins.open, suite._real_open)

    def test_appending_to_a_forward_store_raises(self):
        for store in sorted(suite.PROTECTED_STORES):
            with self.subTest(store=store.name):
                with self.assertRaises(suite.ForwardStoreWriteAttempt):
                    open(store, "a")
                with self.assertRaises(suite.ForwardStoreWriteAttempt):
                    Path(store).open("w")
                with self.assertRaises(suite.ForwardStoreWriteAttempt):
                    os.open(store, os.O_WRONLY | os.O_APPEND)

    def test_reading_a_forward_store_is_still_allowed(self):
        # Plenty of tests legitimately read these files. Blocking reads would
        # be a cure worse than the disease.
        store = sorted(suite.PROTECTED_STORES)[0]
        if store.exists():
            with open(store, "rb") as fh:
                fh.read(1)

    def test_unrelated_paths_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "anything.jsonl"
            target.write_text('{"ok": true}\n')
            self.assertEqual(target.read_text(), '{"ok": true}\n')

    def test_a_same_named_file_elsewhere_is_not_blocked(self):
        # The guard matches resolved absolute paths, not basenames -- a test
        # writing its own odds_snapshots.jsonl in a tmpdir is the CORRECT
        # pattern and must keep working.
        with tempfile.TemporaryDirectory() as tmp:
            decoy = Path(tmp) / "odds_snapshots.jsonl"
            decoy.write_text("{}\n")
            self.assertTrue(decoy.exists())


class AppDbIsRedirectedTests(unittest.TestCase):
    """No test may reach data/app/app.db -- real users, tokens, saved bets.

    Regression test for the bug this file was written for: api routes call
    `events.record_event_safe(...)` with no `db=`, that resolves the DEFAULT
    app db, and `record_event_safe` swallows every exception by contract --
    so tests exercising those routes wrote analytics rows into the real store
    and said nothing. 1,593 such rows were found on 2026-09-01.
    """

    def test_app_db_path_env_points_outside_the_repo(self):
        from src.appstate import events, savedbets, users
        real = Path(__file__).resolve().parent.parent / "data" / "app" / "app.db"
        for module in (events, savedbets, users):
            with self.subTest(module=module.__name__):
                self.assertNotEqual(module.db_path(), real)

    def test_recording_an_event_does_not_touch_the_real_app_db(self):
        from src.appstate import events
        real = Path(__file__).resolve().parent.parent / "data" / "app" / "app.db"
        before = suite.fingerprint_store(real)
        events.record_event_safe(1, events.BET_SAVED)
        self.assertEqual(suite.fingerprint_store(real), before)


class ForwardStoresUnchangedTests(unittest.TestCase):
    """The end-of-suite fingerprint check."""

    def test_no_forward_store_changed_during_the_suite(self):
        if _capture_is_running():
            self.skipTest(
                "scripts/forward_capture.sh is running; its appends are real "
                "captures, not contamination, and cannot be told apart from "
                "one here. Re-run with the capture stopped for a clean check.")
        after = suite.snapshot_stores()
        for path, baseline in sorted(suite.BASELINE_STORES.items()):
            with self.subTest(store=Path(path).name):
                self.assertEqual(
                    after[path], baseline,
                    f"{path} changed while the unit suite ran. Rows in this "
                    "store are append-only forward evidence and must come "
                    "only from a real capture -- find the test that wrote "
                    "here and give it a tmp path. Do NOT delete the rows; "
                    "quarantine them to a dated sidecar so the correction "
                    "is visible.")


if __name__ == "__main__":
    unittest.main()
