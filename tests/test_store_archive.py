"""src.pipeline.store_archive -- the fix for the 2026-09-21 100MB-push
incident: data/processed/odds_multibook.jsonl grew to 100.08 MB and GitHub
started rejecting every push from the capture runners, losing a 13-minute
capture slot every time until rotation shipped.

Every test here works ONLY in a temp directory. Nothing in this file reads,
writes, or rotates the real data/processed/ files -- see this program's hard
rule against touching production data from a test.

WHAT "CORRECT" MEANS FOR THIS MODULE (repeated from store_archive.py's own
docstring because it is exactly what these tests exist to prove): the
LOGICAL store -- every archive segment, oldest first, decompressed, then the
hot file -- must be BYTE-IDENTICAL to what the hot file's bytes were before
any rotation touched it. Several tests below assert that literally (sha256
or `==` on raw bytes), not just "the same JSON rows", because a reader
somewhere may hash or diff raw lines.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import store_archive


def _row(day: str, hour: int = 10, **extra) -> dict:
    row = {"observed_utc": f"{day}T{hour:02d}:00:00.000000+00:00",
           "event_id": "e1", "book": "fanduel"}
    row.update(extra)
    return row


def _write_rows(path: Path, rows: list) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")
    path.write_bytes(data)
    return data


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)  # cutoff (keep_days=3) -> 2026-09-18


class TempStoreTestCase(unittest.TestCase):
    """Every test gets its own throwaway directory; never the real repo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.hot = self.root / "odds_multibook.jsonl"


class SegmentDirAndListing(TempStoreTestCase):
    def test_segment_dir_is_a_per_store_sibling_of_archive(self):
        self.assertEqual(
            store_archive.segment_dir(self.hot),
            self.root / "archive" / "odds_multibook")

    def test_segments_is_empty_with_no_archive_directory(self):
        self.assertEqual(store_archive.segments(self.hot), [])

    def test_exists_is_false_with_neither_hot_file_nor_archive(self):
        self.assertFalse(store_archive.exists(self.hot))

    def test_exists_is_true_for_a_bare_hot_file(self):
        _write_rows(self.hot, [_row("2026-09-21")])
        self.assertTrue(store_archive.exists(self.hot))


class IterLinesWithNoArchive(TempStoreTestCase):
    """"iter_lines on a path with no archive == plain read" -- the
    contract every existing caller (that never rotated) depends on."""

    def test_iter_lines_matches_a_plain_readlines_of_the_hot_file(self):
        rows = [_row("2026-09-19", i) for i in range(4)]
        data = _write_rows(self.hot, rows)
        expected = data.decode("utf-8").splitlines(keepends=True)
        self.assertEqual(list(store_archive.iter_lines(self.hot)), expected)

    def test_iter_lines_on_a_missing_store_yields_nothing(self):
        self.assertEqual(list(store_archive.iter_lines(self.hot)), [])


class RotateNoOp(TempStoreTestCase):
    def test_missing_hot_file_is_a_clean_no_op(self):
        report = store_archive.rotate(
            self.hot, keep_days=3, now=NOW, threshold_bytes=1)
        self.assertFalse(report["rotated"])
        self.assertIn("does not exist", report["reason"])

    def test_under_threshold_is_a_no_op_and_touches_nothing(self):
        rows = [_row("2026-09-01"), _row("2026-09-02")]
        data = _write_rows(self.hot, rows)
        report = store_archive.rotate(
            self.hot, keep_days=3, now=NOW, threshold_bytes=len(data) + 1)
        self.assertFalse(report["rotated"])
        self.assertIn("threshold", report["reason"])
        self.assertEqual(self.hot.read_bytes(), data)
        self.assertEqual(store_archive.segments(self.hot), [])

    def test_no_lines_older_than_cutoff_is_a_no_op(self):
        # Every row is dated on/after the 2026-09-18 cutoff (keep_days=3
        # from NOW) -- nothing qualifies to archive even though the file is
        # over threshold.
        rows = [_row("2026-09-19"), _row("2026-09-20"), _row("2026-09-21")]
        data = _write_rows(self.hot, rows)
        report = store_archive.rotate(
            self.hot, keep_days=3, now=NOW, threshold_bytes=1)
        self.assertFalse(report["rotated"])
        self.assertEqual(self.hot.read_bytes(), data)


class RotateByteIdentity(TempStoreTestCase):
    def test_round_trip_is_byte_identical_to_the_pre_rotation_hot_file(self):
        rows = ([_row("2026-09-01", i) for i in range(3)]
                + [_row("2026-09-10", i) for i in range(2)]
                + [_row("2026-09-21", i) for i in range(4)])
        original = _write_rows(self.hot, rows)

        report = store_archive.rotate(
            self.hot, keep_days=3, now=NOW, threshold_bytes=1)

        self.assertTrue(report["rotated"])
        self.assertEqual(report["archived_lines"], 5)  # 09-01 (3) + 09-10 (2)

        rebuilt = "".join(store_archive.iter_lines(self.hot)).encode("utf-8")
        self.assertEqual(rebuilt, original)
        self.assertEqual(hashlib.sha256(rebuilt).hexdigest(),
                         hashlib.sha256(original).hexdigest())

    def test_hot_file_after_rotation_holds_only_the_unarchived_suffix(self):
        rows = [_row("2026-09-01"), _row("2026-09-21")]
        _write_rows(self.hot, rows)
        store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)
        remaining = [json.loads(line) for line in
                     self.hot.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["observed_utc"][:10], "2026-09-21")

    def test_segment_is_named_with_a_zero_padded_sequence_and_date_range(self):
        rows = [_row("2026-09-01"), _row("2026-09-02"), _row("2026-09-21")]
        _write_rows(self.hot, rows)
        report = store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)
        segs = store_archive.segments(self.hot)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].name, "0001_2026-09-01_2026-09-02.jsonl.gz")
        self.assertEqual(report["segment"], str(segs[0]))

    def test_segment_gzip_is_deterministic(self):
        """mtime=0, no filename: rotating the same input bytes twice
        produces a byte-identical segment, never one that merely
        decompresses to the same content."""
        rows = [_row("2026-09-01"), _row("2026-09-21")]
        _write_rows(self.hot, rows)
        store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)
        first_bytes = store_archive.segments(self.hot)[0].read_bytes()

        # A second store, same input, same rotation -- independent archive
        # directory, so this compares two INDEPENDENT gzip writes rather
        # than re-reading the same file.
        other_hot = self.root / "other" / "odds_multibook.jsonl"
        _write_rows(other_hot, rows)
        store_archive.rotate(other_hot, keep_days=3, now=NOW, threshold_bytes=1)
        second_bytes = store_archive.segments(other_hot)[0].read_bytes()

        self.assertEqual(first_bytes, second_bytes)


class RotatePrefixStop(TempStoreTestCase):
    """"stop at the first line >= cutoff or unparseable" -- lines are never
    reordered, and everything from the stopping line onward stays in the
    hot file even if a LATER line would have qualified on its own."""

    def test_stops_at_first_line_on_or_after_cutoff_even_if_later_lines_qualify(self):
        # 09-19 (>= cutoff) sits between two pre-cutoff dates. The scan must
        # stop AT the 09-19 line, archiving only the first row, never
        # skipping past it to also archive the 09-02 row that follows.
        rows = [_row("2026-09-01"), _row("2026-09-19"), _row("2026-09-02")]
        _write_rows(self.hot, rows)
        report = store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)
        self.assertEqual(report["archived_lines"], 1)
        remaining = self.hot.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(remaining), 2)
        self.assertEqual(json.loads(remaining[0])["observed_utc"][:10], "2026-09-19")
        self.assertEqual(json.loads(remaining[1])["observed_utc"][:10], "2026-09-02")

    def test_stops_at_first_unparseable_json_line(self):
        path = self.hot
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(_row("2026-09-01")) + "\n",
                 "{not valid json\n",
                 json.dumps(_row("2026-09-02")) + "\n"]
        path.write_bytes("".join(lines).encode("utf-8"))
        report = store_archive.rotate(path, keep_days=3, now=NOW, threshold_bytes=1)
        self.assertEqual(report["archived_lines"], 1)
        self.assertEqual(path.read_bytes(), ("".join(lines[1:])).encode("utf-8"))

    def test_stops_at_first_line_missing_the_stamp_field(self):
        path = self.hot
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(_row("2026-09-01")) + "\n",
                 json.dumps({"event_id": "no-stamp-here"}) + "\n",
                 json.dumps(_row("2026-09-02")) + "\n"]
        path.write_bytes("".join(lines).encode("utf-8"))
        report = store_archive.rotate(path, keep_days=3, now=NOW, threshold_bytes=1)
        self.assertEqual(report["archived_lines"], 1)

    def test_incomplete_trailing_line_is_never_touched(self):
        """A run killed mid-write leaves a final line with no trailing
        newline (src.pipeline.snapshots.append's own `_ends_ragged`
        contract) -- rotation must stop there, never archive it, never
        silently drop it."""
        path = self.hot
        path.parent.mkdir(parents=True, exist_ok=True)
        complete = json.dumps(_row("2026-09-01")) + "\n"
        ragged = json.dumps(_row("2026-09-02"))  # no trailing "\n"
        path.write_bytes((complete + ragged).encode("utf-8"))
        original = path.read_bytes()

        report = store_archive.rotate(path, keep_days=3, now=NOW, threshold_bytes=1)

        self.assertEqual(report["archived_lines"], 1)
        rebuilt = "".join(store_archive.iter_lines(path)).encode("utf-8")
        self.assertEqual(rebuilt, original)
        # The ragged fragment itself must be exactly what remains in the
        # hot file -- not silently completed with a newline, not dropped.
        self.assertEqual(path.read_bytes(), ragged.encode("utf-8"))


class RotateMultiple(TempStoreTestCase):
    def test_multiple_rotations_keep_order(self):
        # Timestamps are non-decreasing throughout, matching what a real
        # append-only capture (src.pipeline.snapshots.append) actually
        # writes -- rotation only ever archives a PREFIX (module docstring),
        # so out-of-order input is a test-data bug, not something a second
        # rotation is meant to repair.
        rows = ([_row("2026-08-01", i) for i in range(2)]
                + [_row("2026-08-15", i) for i in range(2)]
                + [_row("2026-09-21")])
        original = _write_rows(self.hot, rows)

        # First rotation: cutoff far in the future archives everything
        # except the newest row.
        r1 = store_archive.rotate(
            self.hot, keep_days=3,
            now=datetime(2026, 9, 10, tzinfo=timezone.utc), threshold_bytes=1)
        self.assertTrue(r1["rotated"])

        # Append a newer row, then rotate again with a later `now` -- the
        # remaining 2026-09-21 row now falls before ITS cutoff and archives
        # into a second segment; the freshly appended row stays in the hot
        # file. The new segment must get sequence 0002, sorting after the
        # first.
        more = [_row("2026-09-24")]
        with self.hot.open("a", encoding="utf-8") as fh:
            for row in more:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")

        r2 = store_archive.rotate(
            self.hot, keep_days=3,
            now=datetime(2026, 9, 25, tzinfo=timezone.utc), threshold_bytes=1)
        self.assertTrue(r2["rotated"])
        self.assertEqual(r2["archived_lines"], 1)

        segs = store_archive.segments(self.hot)
        self.assertEqual([s.name.split("_", 1)[0] for s in segs], ["0001", "0002"])

        # The logical store must still contain every original row plus the
        # appended one, in original append order.
        logical_rows = [json.loads(line) for line in store_archive.iter_lines(self.hot)]
        expected_rows = rows + more
        self.assertEqual([r["observed_utc"] for r in logical_rows],
                         [r["observed_utc"] for r in expected_rows])
        self.assertEqual(self.hot.read_text(encoding="utf-8").strip(),
                         json.dumps(more[0], separators=(",", ":")))


class RotateMismatchRefusal(TempStoreTestCase):
    def test_a_failed_verification_raises_and_leaves_the_hot_file_intact(self):
        rows = [_row("2026-09-01"), _row("2026-09-21")]
        original = _write_rows(self.hot, rows)

        real_gzip_open = gzip.open

        def corrupting_open(path, mode="rb", *a, **kw):
            # Only corrupt the read-back of rotate's own temp segment (the
            # verification step); anything else (including a real archive
            # segment elsewhere) opens normally.
            if str(path).endswith(".tmp") and "r" in mode:
                class _Corrupt:
                    def __enter__(self_):
                        return self_

                    def __exit__(self_, *exc):
                        return False

                    def read(self_):
                        return b"this is not the archived prefix at all"
                return _Corrupt()
            return real_gzip_open(path, mode, *a, **kw)

        with mock.patch.object(store_archive.gzip, "open", side_effect=corrupting_open):
            with self.assertRaises(store_archive.StoreArchiveError):
                store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)

        # HOT FILE UNTOUCHED.
        self.assertEqual(self.hot.read_bytes(), original)
        # NO ORPHAN SEGMENT: a failed proof must leave the archive directory
        # exactly as empty as it was before `rotate` was ever called, not a
        # corrupt file nothing points at.
        self.assertEqual(store_archive.segments(self.hot), [])
        # NO LEFTOVER TEMP FILES either.
        seg_dir = store_archive.segment_dir(self.hot)
        leftovers = list(seg_dir.glob("*.tmp")) if seg_dir.exists() else []
        self.assertEqual(leftovers, [])


class RotateRollbackOnHotFileFailure(TempStoreTestCase):
    """2026-09-21 review, the central bug this pass fixes: the segment is
    made durable (`os.replace`) BEFORE the hot file is rewritten. Before this
    fix, a failure replacing the hot file -- ENOSPC/EIO on a CI runner, or a
    Windows `PermissionError` when another process (a `--reload` dev server,
    Defender) still has the hot file open -- left the segment in place while
    the hot file still held every row that segment had just archived. The
    logical store then duplicated the archived prefix, and the next
    successful rotation would archive the same rows again as a new segment,
    making the duplication permanent."""

    def test_hot_file_replace_failure_rolls_back_the_segment(self):
        rows = [_row("2026-09-01"), _row("2026-09-21")]
        original = _write_rows(self.hot, rows)
        real_replace = os.replace
        calls = {"n": 0}

        def fail_second_replace(src, dst, **kw):
            calls["n"] += 1
            if calls["n"] == 2:  # 1st call moves the segment; 2nd moves the hot file
                raise OSError(28, "No space left on device")
            return real_replace(src, dst, **kw)

        with mock.patch.object(store_archive.os, "replace", side_effect=fail_second_replace):
            with self.assertRaises(OSError):
                store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)

        # NO ORPHAN SEGMENT -- this is the assertion that fails against the
        # pre-2026-09-21-review code (its `except Exception` after the hot
        # write only unlinked the HOT tmp file, never the already-placed
        # segment).
        self.assertEqual(store_archive.segments(self.hot), [])
        self.assertEqual(self.hot.read_bytes(), original)
        rebuilt = "".join(store_archive.iter_lines(self.hot)).encode("utf-8")
        self.assertEqual(rebuilt, original)


class RotateConcurrentWriteGuard(TempStoreTestCase):
    """A writer appending between rotate's read of the hot file and its
    final replace must not have its row silently discarded (2026-09-21
    review)."""

    def test_a_row_appended_mid_rotation_is_never_discarded(self):
        rows = [_row("2026-09-01"), _row("2026-09-21")]
        _write_rows(self.hot, rows)
        real_replace = os.replace
        calls = {"n": 0}

        def racing_replace(src, dst, **kw):
            calls["n"] += 1
            result = real_replace(src, dst, **kw)
            if calls["n"] == 1:
                # Right after the segment is placed durably, but before
                # rotate re-stats the hot file -- simulates a writer landing
                # in that exact window.
                with open(self.hot, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(_row("2026-09-22"), separators=(",", ":")) + "\n")
            return result

        with mock.patch.object(store_archive.os, "replace", side_effect=racing_replace):
            with self.assertRaises(store_archive.StoreArchiveError):
                store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)

        # Segment rolled back -- a retry must not re-archive the same prefix
        # into a second segment once the race has passed.
        self.assertEqual(store_archive.segments(self.hot), [])
        # The concurrently-appended row survives, exactly as written.
        self.assertIn("2026-09-22", self.hot.read_text(encoding="utf-8"))


class RotateSequenceNumbering(TempStoreTestCase):
    """2026-09-21 review: `next_seq` used to be `len(segments) + 1`, which a
    gap in the sequence (a segment removed by hand, or a previous partial
    rotation cleaned up manually) would compute as an EXISTING segment's
    name -- and `os.replace` does not check whether its target already
    exists, so that rotation would silently overwrite it."""

    def test_a_sequence_gap_does_not_overwrite_an_existing_segment(self):
        # 0001 and 0003 present, 0002 missing (removed by hand, or cleaned
        # up after a partial rotation). Pre-fix `len(segments) + 1` counts 2
        # existing files and computes next_seq=3 -- exactly "0003", the name
        # of the segment that is already there -- and `os.replace` does not
        # check whether its target exists, so that rotation would silently
        # replace PRECIOUS with new content.
        seg_dir = store_archive.segment_dir(self.hot)
        seg_dir.mkdir(parents=True)
        (seg_dir / "0001_2026-06-01_2026-06-02.jsonl.gz").write_bytes(
            gzip.compress(b'{"marker":"EARLIER"}\n'))
        precious = seg_dir / "0003_2026-07-01_2026-07-02.jsonl.gz"
        precious_bytes = gzip.compress(b'{"marker":"PRECIOUS"}\n')
        precious.write_bytes(precious_bytes)

        rows = [_row("2026-09-01"), _row("2026-09-21")]
        _write_rows(self.hot, rows)
        report = store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)

        self.assertTrue(report["rotated"])
        segs = store_archive.segments(self.hot)
        names = [s.name.split("_", 1)[0] for s in segs]
        # max(1, 3) + 1 = 4 -- never "0003" again.
        self.assertIn("0004", names)
        self.assertEqual(names.count("0003"), 1)
        # PRECIOUS must be exactly what it was -- never overwritten.
        self.assertEqual(precious.read_bytes(), precious_bytes)

    def test_refuses_rather_than_overwrite_a_colliding_segment_name(self):
        """`max(existing seqs) + 1` (the fix above) already makes a
        collision with `segments()`'s own listing unreachable by
        construction -- the whole point of taking the max. This proves the
        SEPARATE, defensive `segment_path.exists()` check on top of it: the
        belt-and-suspenders backstop for a TOCTOU a bare max()+1 cannot see
        (something places the exact target name between this rotation
        listing segments and it writing one), reproduced here by mocking
        `segments()` to under-report what next_seq should be while the real
        file already sits on disk at that name."""
        rows = [_row("2026-09-01"), _row("2026-09-21")]
        _write_rows(self.hot, rows)
        seg_dir = store_archive.segment_dir(self.hot)
        seg_dir.mkdir(parents=True)
        # The name a rotation from an EMPTY archive directory would compute
        # (next_seq=1) -- planted directly on disk, bypassing whatever
        # `segments()` reports, to simulate exactly that race.
        colliding = seg_dir / "0001_2026-09-01_2026-09-01.jsonl.gz"
        colliding.write_bytes(b"not a real segment")
        with mock.patch.object(store_archive, "segments", return_value=[]):
            with self.assertRaises(store_archive.StoreArchiveError):
                store_archive.rotate(self.hot, keep_days=3, now=NOW, threshold_bytes=1)
        self.assertEqual(colliding.read_bytes(), b"not a real segment")
        self.assertEqual(self.hot.read_bytes(),
                         "".join(json.dumps(r, separators=(",", ":")) + "\n"
                                 for r in rows).encode("utf-8"))


class RotateInvalidUtf8(TempStoreTestCase):
    """2026-09-21 review: only `json.JSONDecodeError` was caught in the
    prefix scan. Invalid UTF-8 bytes in a line raise `UnicodeDecodeError`
    (also a `ValueError`, but not a `JSONDecodeError`) out of `json.loads`,
    which used to propagate out of `rotate` as an uncaught traceback instead
    of stopping the prefix scan the same way any other unparseable line
    does."""

    def test_invalid_utf8_line_stops_the_scan_instead_of_crashing(self):
        path = self.hot
        path.parent.mkdir(parents=True, exist_ok=True)
        good = json.dumps(_row("2026-09-01")).encode("utf-8") + b"\n"
        # 0xFF is never valid as a UTF-8 lead byte -- json.loads(bytes)
        # decodes internally and this raises UnicodeDecodeError.
        bad = b'{"observed_utc": "2026-09-02T00:00:00+00:00", "x": "\xff"}\n'
        path.write_bytes(good + bad)
        original = path.read_bytes()

        report = store_archive.rotate(path, keep_days=3, now=NOW, threshold_bytes=1)

        self.assertEqual(report["archived_lines"], 1)
        self.assertEqual(path.read_bytes(), bad)
        # The archived prefix + remaining hot bytes still equal the original
        # file exactly -- the byte-identity contract holds even though one
        # of the remaining lines is not valid UTF-8 (this test does not call
        # `iter_lines` on it: that function decodes every line as UTF-8 by
        # design, per its own docstring, and this line is deliberately not
        # valid UTF-8).
        segs = store_archive.segments(path)
        with gzip.open(segs[0], "rb") as fh:
            archived = fh.read()
        self.assertEqual(archived + path.read_bytes(), original)


class RotateKeepDaysValidation(TempStoreTestCase):
    """2026-09-21 review: `--keep-days -5` used to reach the cutoff
    arithmetic unchecked, computing a cutoff AFTER `now` and archiving rows
    written moments ago, including everything in the hot file."""

    def test_negative_keep_days_is_rejected_before_anything_is_read(self):
        rows = [_row("2026-09-21")]
        original = _write_rows(self.hot, rows)
        with self.assertRaises(ValueError):
            store_archive.rotate(self.hot, keep_days=-5, now=NOW, threshold_bytes=1)
        self.assertEqual(self.hot.read_bytes(), original)
        self.assertEqual(store_archive.segments(self.hot), [])


class RotateTimezoneNormalization(TempStoreTestCase):
    """2026-09-21 review: the cutoff used to be `now.date() - keep_days`
    with `now` taken exactly as given -- `datetime.date()` does not convert
    a timezone offset, it just strips the time off whatever wall-clock value
    is stored. A `now` with a non-UTC offset therefore used to compute a
    cutoff in THAT offset's calendar, not UTC's, even though every stamp in
    this project is written in UTC."""

    def test_cutoff_is_computed_in_utc_not_the_callers_own_offset(self):
        # now = 2026-09-21T02:00+05:00 is 2026-09-20T21:00 UTC. keep_days=3
        # -> the correct UTC cutoff is 2026-09-17. The pre-fix code took
        # `now.date()` literally (2026-09-21, the wall-clock date as given)
        # and computed cutoff 2026-09-18 instead.
        now_plus_five = datetime(2026, 9, 21, 2, 0, tzinfo=timezone(timedelta(hours=5)))
        rows = [_row("2026-09-17")]  # >= the correct UTC cutoff (09-17): must NOT archive
        original = _write_rows(self.hot, rows)
        report = store_archive.rotate(
            self.hot, keep_days=3, now=now_plus_five, threshold_bytes=1)
        # The pre-fix cutoff (09-18, from the naive +05:00 wall-clock date)
        # would have archived this row (09-17 < 09-18); the fixed, UTC-based
        # cutoff (09-17) must not.
        self.assertFalse(report["rotated"])
        self.assertEqual(report["cutoff_date"], "2026-09-17")
        self.assertEqual(self.hot.read_bytes(), original)


class RegistryTestCase(unittest.TestCase):
    def test_odds_multibook_is_registered_with_the_observed_utc_stamp_field(self):
        self.assertIn("odds_multibook", store_archive.ROTATABLE_STORES)
        cfg = store_archive.ROTATABLE_STORES["odds_multibook"]
        self.assertEqual(cfg["stamp_field"], "observed_utc")


if __name__ == "__main__":
    unittest.main()
