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

WHY "I CANNOT SEE /proc" IS NOT "A CAPTURE IS RUNNING" (2026-09-16)
--------------------------------------------------------------------
The first version of the probe below answered any error with `return True`
on the reasoning that "if we cannot tell, skipping is the safe call". That
made the probe's answer a constant on every platform without a Linux /proc:
on the Windows developer checkout `Path("/proc").iterdir()` raises
FileNotFoundError immediately, the probe answered True, and BOTH this
module's fingerprint test AND scripts/test_parallel.py's authoritative
whole-run version of it skipped on every single run -- printing
"forward_capture.sh is running" about a script that cannot even execute
there. The only check that can catch a write this process's `open` patch
does not intercept was therefore permanently off, while reporting a
specific, false reason for being off.

So the probe now answers three states, not two, and only a capture we
actually SAW skips outright:

  RUNNING      a /proc entry's cmdline really contains forward_capture
  NOT_RUNNING  /proc was scanned successfully and nothing matched
  UNAVAILABLE  there is no readable /proc here; we know nothing either way

UNAVAILABLE still runs the comparison, because an UNCHANGED fingerprint is
unambiguous no matter who might have been running: nothing appended, so
there is nothing to attribute to anybody. Only UNAVAILABLE *plus* a changed
store is genuinely ambiguous, and that -- not the platform -- is what earns
a skip. The result: a real contamination on a machine with no /proc now goes
red instead of vanishing, and a live capture still never produces a false
red anywhere.
"""

from __future__ import annotations

import builtins
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import tests as suite


#: The process table this probe reads, named once so a future edit that
#: points it somewhere else breaks `test_the_probe_reads_proc` rather than
#: silently changing what "a capture is running" means.
PROC_ROOT = Path("/proc")

#: The three answers `capture_probe` can give. See the module docstring's
#: "WHY 'I CANNOT SEE /proc' IS NOT 'A CAPTURE IS RUNNING'".
CAPTURE_RUNNING = "running"
CAPTURE_NOT_RUNNING = "not_running"
CAPTURE_UNKNOWN = "unavailable"


def capture_probe(proc_root: Path = None) -> tuple:
    """(state, detail) for "is scripts/forward_capture.sh live right now".

    Reads `PROC_ROOT` directly rather than shelling out to `ps`, so it works
    in the minimal containers this runs in. `proc_root` is injectable so the
    probe's own three answers can be tested without a real process table.

    Returns CAPTURE_RUNNING only when a cmdline actually matched;
    CAPTURE_NOT_RUNNING when the scan completed and found nothing; and
    CAPTURE_UNKNOWN when there is no readable process table here at all --
    which is a statement about this machine, never about the capture.
    """
    root = PROC_ROOT if proc_root is None else Path(proc_root)
    try:
        entries = list(root.iterdir())
    except Exception as exc:  # noqa: BLE001 -- no /proc on this platform, etc.
        return CAPTURE_UNKNOWN, f"{root} is not readable here ({exc})"
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        if b"forward_capture" in cmdline:
            return CAPTURE_RUNNING, f"pid {entry.name} is running forward_capture"
    return CAPTURE_NOT_RUNNING, f"scanned {root}; no forward_capture process"


def _capture_is_running() -> bool:
    """Back-compatible boolean: True ONLY when a capture was actually seen.

    Kept because scripts/test_parallel.py and any other caller may still ask
    the yes/no question. It no longer answers True for "I could not look",
    which is the bug this shape had: see the module docstring.
    """
    return capture_probe()[0] == CAPTURE_RUNNING


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


class CaptureProbeTests(unittest.TestCase):
    """The probe must not answer "a capture is running" about a machine it
    simply cannot see into. Regression test for 2026-09-16: on the Windows
    developer checkout `Path("/proc").iterdir()` raises FileNotFoundError,
    the old probe answered True, and the fingerprint check below -- plus
    scripts/test_parallel.py's authoritative whole-run copy of it -- skipped
    on every run while naming forward_capture.sh as the reason.
    """

    def test_the_probe_reads_the_process_table_it_names(self):
        # The docstring and every skip message say "is forward_capture.sh
        # running"; the artifact that answers that is the process table.
        # Named as a constant so a swapped path breaks here, not silently.
        self.assertEqual(PROC_ROOT, Path("/proc"))

    def test_an_unreadable_process_table_is_unavailable_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-such-proc"
            state, detail = capture_probe(missing)
        self.assertEqual(state, CAPTURE_UNKNOWN)
        self.assertNotEqual(state, CAPTURE_RUNNING)
        self.assertIn("not readable", detail)

    def test_a_scanned_empty_process_table_is_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, detail = capture_probe(Path(tmp))
        self.assertEqual(state, CAPTURE_NOT_RUNNING)
        self.assertIn("no forward_capture", detail)

    def test_a_real_capture_cmdline_is_still_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_dir = Path(tmp) / "4242"
            pid_dir.mkdir()
            (pid_dir / "cmdline").write_bytes(
                b"/bin/bash\x00scripts/forward_capture.sh\x00")
            (Path(tmp) / "not-a-pid").mkdir()
            state, detail = capture_probe(Path(tmp))
        self.assertEqual(state, CAPTURE_RUNNING)
        self.assertIn("4242", detail)

    def test_the_boolean_wrapper_is_false_when_it_could_not_look(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "gone"
            self.assertEqual(capture_probe(missing)[0], CAPTURE_UNKNOWN)
        # And the wrapper only ever says True for CAPTURE_RUNNING.
        self.assertIs(_capture_is_running(),
                      capture_probe()[0] == CAPTURE_RUNNING)

    def test_the_parallel_runner_uses_the_three_state_probe(self):
        # scripts/test_parallel.py holds the AUTHORITATIVE whole-run version
        # of the fingerprint check. If it goes back to the boolean that
        # answered True for "cannot look", the whole-run proof silently
        # switches off again on any machine without /proc.
        runner = (Path(__file__).resolve().parent.parent
                  / "scripts" / "test_parallel.py").read_text(encoding="utf-8")
        self.assertIn("guard_mod.capture_probe()", runner)
        self.assertIn("guard_mod.CAPTURE_RUNNING", runner)
        self.assertNotIn("guard_mod._capture_is_running()", runner)


class ForwardStoresUnchangedTests(unittest.TestCase):
    """The end-of-suite fingerprint check."""

    def test_no_forward_store_changed_during_the_suite(self):
        state, detail = capture_probe()
        if state == CAPTURE_RUNNING:
            self.skipTest(
                f"scripts/forward_capture.sh is running ({detail}); its "
                "appends are real captures, not contamination, and cannot be "
                "told apart from one here. Re-run with the capture stopped "
                "for a clean check.")
        after = suite.snapshot_stores()
        changed = [p for p, b in suite.BASELINE_STORES.items() if after[p] != b]
        if changed and state == CAPTURE_UNKNOWN:
            # The ONLY genuinely ambiguous case: something appended, and this
            # machine has no process table to rule a live capture in or out.
            # An unchanged fingerprint needs no such alibi, which is why this
            # branch is reached only once `changed` is non-empty.
            self.skipTest(
                f"{len(changed)} forward store(s) changed and a live capture "
                f"could not be ruled in or out here ({detail}). This is NOT a "
                "clean result: re-run somewhere the process table is readable, "
                "or confirm by hand that no capture was in flight.")
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
