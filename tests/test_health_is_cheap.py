"""/health must be cheap, because a load balancer polls it forever.

apphealth's own module docstring says this check "must answer it with zero
network access and near-zero latency, because it is the thing a host's load
balancer or uptime checker polls every few seconds."

It did not. Measured on the live container 2026-09-11: 1,087-1,212ms, warm,
with nothing else in flight. `_newest_timestamp` read and JSON-parsed EVERY
LINE of every store to find the newest one -- 123,182 rows, about 40 MB, per
call. Fly polls /health every 30 seconds, so that was a second of CPU burned
every thirty, continuously, on a shared vCPU with a quota. It is a large part
of why everything else on the box was being throttled, and it is the exact
failure the docstring warned about.

The stores are append-only and change only when a capture runs. The scan is
memoised on (size, mtime_ns).

WHAT IS PINNED, AND WHY IT IS NOT A TIMING TEST
------------------------------------------------
Wall time would pass or fail by machine. What is asserted instead is the
behaviour that makes it cheap and the behaviour that keeps it honest:

  - an unchanged file is not re-read
  - a CHANGED file is, immediately -- a cache that served a stale "newest
    row" would be lying about the one number this check exists to report
  - the cache does not grow without bound

A staleness check that reports an old timestamp as current is worse than a
slow one.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.appstate import apphealth


class TheScanIsMemoisedOnTheFilesFingerprint(unittest.TestCase):

    def setUp(self):
        apphealth._SCAN_CACHE.clear()
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self.path = Path(path)
        self._write(["2026-09-10T10:00:00+00:00", "2026-09-10T11:00:00+00:00"])

    def tearDown(self):
        apphealth._SCAN_CACHE.clear()
        if self.path.exists():
            os.remove(self.path)

    def _write(self, stamps, mode="w"):
        with self.path.open(mode, encoding="utf-8") as fh:
            for s in stamps:
                fh.write(json.dumps({"observed_utc": s}) + "\n")

    def _scan(self):
        return apphealth._newest_timestamp(self.path, "observed_utc")

    def test_it_reads_the_file_the_first_time(self):
        rows, newest = self._scan()
        self.assertEqual(rows, 2)
        self.assertEqual(newest,
                         datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc))

    def test_an_unchanged_file_is_not_read_again(self):
        """THE ONE THAT MATTERS, and it counts OPENS rather than timing.

        The first version of this test deleted the file and expected the
        cached answer anyway. That was wrong about the implementation:
        building the fingerprint needs `stat()`, so a deleted file cannot be
        recognised as unchanged, and the test failed against correct code.
        stat() is the cheap part -- what must not happen twice is the READ.
        """
        opens = []
        real_open = Path.open

        def counting_open(self_, *a, **k):
            opens.append(str(self_))
            return real_open(self_, *a, **k)

        Path.open = counting_open
        try:
            first = self._scan()
            self.assertEqual(len(opens), 1, "the first scan did not read")
            second = self._scan()
        finally:
            Path.open = real_open
        self.assertEqual(second, first)
        self.assertEqual(len(opens), 1,
                         f"the store was read {len(opens)} times; an "
                         f"unchanged file must be served from cache")

    def test_a_changed_file_is_rescanned(self):
        """A cache that serves a stale newest-row is lying about the one
        number this check exists to report."""
        self._scan()
        self._write(["2026-09-10T23:00:00+00:00"], mode="a")
        rows, newest = self._scan()
        self.assertEqual(rows, 3)
        self.assertEqual(newest,
                         datetime(2026, 9, 10, 23, 0, tzinfo=timezone.utc))

    def test_a_rewritten_file_of_the_same_length_is_rescanned(self):
        """Size alone is not a fingerprint. Same byte count, different
        content -- mtime is what catches it."""
        self._scan()
        size_before = self.path.stat().st_size
        self._write(["2026-09-10T10:00:00+00:00", "2026-09-11T11:00:00+00:00"])
        self.assertEqual(self.path.stat().st_size, size_before,
                         "test setup no longer exercises the same-size case")
        _rows, newest = self._scan()
        self.assertEqual(newest.day, 11,
                         "a rewritten store of identical length served a "
                         "stale answer")

    def test_the_cache_holds_one_entry_per_store(self):
        """The key carries size and mtime, so a growing file would otherwise
        leave a copy of every version it ever had -- a slow leak, in the
        module whose job is noticing that sort of thing."""
        for i in range(5):
            self._write([f"2026-09-10T1{i}:00:00+00:00"], mode="a")
            self._scan()
        mine = [k for k in apphealth._SCAN_CACHE if k[0] == str(self.path)]
        self.assertEqual(len(mine), 1,
                         f"{len(mine)} cache entries for one store")

    def test_a_missing_store_still_raises_for_the_caller_to_report(self):
        """check_store turns the error into an honest `present: False`.
        Swallowing it here would report a missing store as healthy."""
        os.remove(self.path)
        apphealth._SCAN_CACHE.clear()
        with self.assertRaises(OSError):
            self._scan()


if __name__ == "__main__":
    unittest.main()
