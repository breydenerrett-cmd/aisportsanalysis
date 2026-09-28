"""Hot/cold rotation for the hash-chained decisions ledger
(`evidence/decisions_v2.jsonl`, `src.ledger.chain.HashChainLedger`), reusing
`src.pipeline.store_archive` (the 2026-09-21 odds_multibook incident's fix).

WHY THIS LEDGER NEEDED MORE THAN "REGISTER IT LIKE ODDS_MULTIBOOK"
--------------------------------------------------------------------
Three things `store_archive.rotate` did not originally handle, all
exercised below:

  1. It is a HASH CHAIN, not a plain append-only log -- every row, the row
     ORDER, and the prev_hash/row_hash links across the hot/segment boundary
     must all survive rotation, and `HashChainLedger.append()`'s
     `last_hash()` must never silently start a new, disconnected chain.
  2. Its stamp (`recorded_utc`) is NOT monotone in file order (~1,739
     decreases in the real ledger, mostly within a day), so a segment's
     name must be the MIN/MAX of the dates it actually holds, not the first
     and last row processed.
  3. Row 1 is a genesis row with NO timestamp at all, and `ensure_genesis`
     (`src.ledger.bridge`) must still find it as `existing[0]` after
     rotation moves it into a cold segment.

Every test here builds its OWN synthetic chain in a temp directory via
`HashChainLedger`/`bridge.ensure_genesis` -- this file never reads, writes to,
or rotates the real `evidence/decisions_v2.jsonl`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.engine import settle_slate
from src.engine import slate as slate_module
from src.ledger import bridge
from src.ledger.chain import GENESIS_HASH, HashChainLedger
from src.ledger.records import PROBABILITY_PROVENANCE_NONE
from src.pipeline import lineup_store, store_archive
from scripts import research_readiness

DECISIONS_CFG = store_archive.ROTATABLE_STORES["decisions_v2"]
STAMP_OF = DECISIONS_CFG["stamp_of"]
MIN_HOT_ROWS = DECISIONS_CFG["min_hot_rows"]

# now=2026-09-28T15:00Z, keep_days=1 -> cutoff_date = 2026-09-27 (rows dated
# strictly before 2026-09-27 archive; 2026-09-27/28 stay hot). Matches this
# task's own SIMULATION parameters so the unit tests and the simulation
# script exercise the same cutoff arithmetic.
NOW = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)
KEEP_DAYS = 1
THRESHOLD_BYTES = 1  # always "over threshold" by size; the cutoff date and
                      # min_hot_rows are the only real gates under test.


def _decision_row(event_id: str, system_id: str, recorded_utc: str,
                   decision_utc: str | None = None, **overrides) -> dict:
    """A minimally-valid DecisionRecord-shaped row (every REQUIRED field of
    `src.ledger.records.DecisionRecord` present, `verdict="no_play"` so
    `__post_init__` demands nothing further) -- shaped like
    `tests/test_ledger_records.py`'s own `_decision()` helper, but a plain
    dict (what actually lives in the JSONL file) rather than a constructed
    dataclass instance."""
    decision_utc = decision_utc or recorded_utc
    row = dict(
        engine_version="v1", system_id=system_id, system_version="1.0.0",
        registry_fingerprint="fp1", frame_fingerprint=None,
        snapshot_fingerprint="snap1", game_pk=12345, event_id=event_id,
        decision_utc=decision_utc, point_class="LATE_BOARD",
        information_time=decision_utc, recorded_utc=recorded_utc,
        verdict="no_play", selection_id=None, market_key=None, line=None,
        book=None, price_american=None, consensus_fair=None,
        books_at_decision=None, friction=None, p_model=None,
        p_model_interval=None, edge_bps=None, price_improvement_bps=None,
        rating=None, thesis=None, evidence=[], counterarguments=[],
        supporting_systems=[], refusal_reason=None, assumption_exposure={},
        stake_units=0.0, known_at_grade="A",
        p_model_provenance=PROBABILITY_PROVENANCE_NONE,
    )
    row.update(overrides)
    return row


def _correction_row(decision_key: list, corrected_utc: str, **overrides) -> dict:
    """Shaped exactly like `scripts/append_edge_withdrawal_corrections.py`'s
    own payload -- `kind="correction"`, `corrected_utc`, no `decision_utc`
    at all (so `load_decisions`/`_load_existing_decision_keys` skip it, same
    as production)."""
    row = {
        "kind": "correction",
        "correction_code": "edge_withdrawn:placeholder_probability",
        "decision_key": list(decision_key),
        "original_edge_bps": None,
        "original_p_model": None,
        "p_model_provenance": "placeholder",
        "reason": "test correction row",
        "corrected_utc": corrected_utc,
    }
    row.update(overrides)
    return row


def _last_row_hash_of_segment(segment_path: Path) -> str:
    with gzip.open(segment_path, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return rows[-1]["row_hash"]


def _rewrite_segment_row(segment_path: Path, index: int, mutate) -> None:
    """Decompress `segment_path`, apply `mutate` to row `index` IN PLACE
    (without touching its `row_hash` -- the point is to simulate a row
    edited by hand after the fact, exactly like
    `tests/test_ledger_chain.py`'s own tampering tests do for a plain hot
    file), and re-gzip it back to the same path."""
    with gzip.open(segment_path, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    mutate(rows[index])
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    with open(segment_path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(body)


def _rewrite_hot_row(hot_path: Path, index: int, mutate) -> None:
    lines = hot_path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[index])
    mutate(row)
    lines[index] = json.dumps(row, sort_keys=True)
    hot_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class DecisionsLedgerRotationTestCase(unittest.TestCase):
    """Base fixture: a genesis row + 10 decision/correction rows spanning
    2026-09-24 .. 2026-09-28, built fresh (own temp dir) per test method.

    THE DATES ARE DELIBERATELY NOT MONOTONE, mirroring the real ledger's own
    ~1,739 out-of-order `recorded_utc` values: row 4 (2026-09-24) is dated
    EARLIER than rows 2-3 (2026-09-25) that precede it in file order, and
    row 8 (2026-09-25) is dated EARLIER than rows 6-7 (2026-09-26) that
    precede IT. This means the true MIN (2026-09-24) and MAX (2026-09-26) of
    the archived prefix's dates differ from "the first row's date" (row 2,
    2026-09-25) and "the last row's date" (row 8, 2026-09-25) -- exactly the
    distinction DESIGN item 2(c) exists to get right.

    With NOW/KEEP_DAYS above (cutoff=2026-09-27), rows 1-8 are archivable and
    rows 9-10 (dated 2026-09-27/28) stay in the hot file.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / "decisions_v2.jsonl"
        self.v1_path = self.root / "forward_ledger.jsonl"  # deliberately absent

    def build_fixture(self) -> list[dict]:
        """Populate `self.path` with the 10-row chain described above and
        return the full rows (each carrying `prev_hash`/`row_hash`) in file
        order, exactly as `HashChainLedger.append()` returned them."""
        rows = []
        genesis = bridge.ensure_genesis(v2_path=self.path, v1_path=self.v1_path)
        rows.append(genesis)
        self.genesis = genesis

        ledger = HashChainLedger(self.path)
        d1 = ledger.append(_decision_row(
            "e1", "sysA", "2026-09-25T10:00:00+00:00"))
        rows.append(d1)
        d2 = ledger.append(_decision_row(
            "e2", "sysA", "2026-09-25T09:00:00+00:00"))  # within-day decrease
        rows.append(d2)
        d3 = ledger.append(_decision_row(
            "e3", "sysB", "2026-09-24T23:00:00+00:00"))  # cross-day decrease
        rows.append(d3)
        correction = ledger.append(_correction_row(
            decision_key=["e1", "sysA", None, None, d1["decision_utc"]],
            corrected_utc="2026-09-26T12:00:00+00:00"))
        rows.append(correction)
        d4 = ledger.append(_decision_row(
            "e4", "sysA", "2026-09-26T08:00:00+00:00"))
        rows.append(d4)
        d5 = ledger.append(_decision_row(
            "e5", "sysB", "2026-09-26T20:00:00+00:00"))  # the true MAX date
        rows.append(d5)
        d6 = ledger.append(_decision_row(
            "e6", "sysA", "2026-09-25T05:00:00+00:00"))  # last archived row,
        rows.append(d6)                                  # NOT the max date
        d7 = ledger.append(_decision_row(
            "e7", "sysA", "2026-09-27T09:00:00+00:00"))  # >= cutoff: stays hot
        rows.append(d7)
        d8 = ledger.append(_decision_row(
            "e8", "sysB", "2026-09-28T10:00:00+00:00"))  # stays hot
        rows.append(d8)

        self.original_bytes = self.path.read_bytes()
        return rows

    def rotate(self, **overrides):
        kwargs = dict(keep_days=KEEP_DAYS, now=NOW,
                      threshold_bytes=THRESHOLD_BYTES,
                      stamp_of=STAMP_OF, min_hot_rows=MIN_HOT_ROWS)
        kwargs.update(overrides)
        return store_archive.rotate(self.path, **kwargs)


class A_LogicalRowCountUnchanged(DecisionsLedgerRotationTestCase):
    def test_row_count_before_equals_after(self):
        rows = self.build_fixture()
        before = len(HashChainLedger(self.path).read())
        self.assertEqual(before, len(rows))

        report = self.rotate()
        self.assertTrue(report["rotated"])

        after = len(HashChainLedger(self.path).read())
        self.assertEqual(after, before)
        self.assertEqual(after, 10)


class B_ByteIdentityAndHashSequence(DecisionsLedgerRotationTestCase):
    def test_concat_of_segments_plus_hot_equals_original_bytes(self):
        rows = self.build_fixture()
        original = self.original_bytes
        original_sha = hashlib.sha256(original).hexdigest()

        report = self.rotate()
        self.assertTrue(report["rotated"])

        segs = store_archive.segments(self.path)
        self.assertEqual(len(segs), 1)
        rebuilt = b"".join(gzip.decompress(s.read_bytes()) for s in segs)
        rebuilt += self.path.read_bytes()

        self.assertEqual(rebuilt, original)
        self.assertEqual(hashlib.sha256(rebuilt).hexdigest(), original_sha)

        # Also via iter_lines, the interface every reader actually uses.
        via_iter_lines = "".join(store_archive.iter_lines(self.path)).encode("utf-8")
        self.assertEqual(via_iter_lines, original)

    def test_row_hash_sequence_is_unchanged(self):
        rows = self.build_fixture()
        hashes_before = [r["row_hash"] for r in rows]

        self.rotate()

        hashes_after = [r["row_hash"] for r in HashChainLedger(self.path).read()]
        self.assertEqual(hashes_after, hashes_before)

    def test_segment_name_uses_min_and_max_of_dated_rows_not_first_and_last_row(self):
        """The archived prefix's FIRST dated row (row 2, e1) is 2026-09-25;
        its LAST row (row 8, e6) is also 2026-09-25. The true MIN across the
        whole prefix is 2026-09-24 (row 4, e3) and the true MAX is
        2026-09-26 (row 7, e5) -- both interior rows. A "first row / last
        row" naming scheme (the pre-`stamp_of` behaviour) would wrongly name
        this segment 0001_2026-09-25_2026-09-25."""
        self.build_fixture()
        report = self.rotate()
        self.assertTrue(report["rotated"])
        segs = store_archive.segments(self.path)
        self.assertEqual(segs[0].name, "0001_2026-09-24_2026-09-26.jsonl.gz")
        self.assertEqual(report["archived_lines"], 8)


class C_ReaderParityBeforeAndAfter(DecisionsLedgerRotationTestCase):
    def test_load_decisions_identical(self):
        self.build_fixture()
        before = settle_slate.load_decisions(path=self.path)
        self.assertEqual(len(before), 8)  # 10 rows - genesis - 1 correction

        self.rotate()

        after = settle_slate.load_decisions(path=self.path)
        self.assertEqual(after, before)
        ids_before = sorted((d.event_id, d.system_id, d.decision_utc) for d in before)
        ids_after = sorted((d.event_id, d.system_id, d.decision_utc) for d in after)
        self.assertEqual(ids_after, ids_before)
        self.assertEqual(hash(tuple(ids_after)), hash(tuple(ids_before)))

    def test_load_existing_decision_keys_identical(self):
        self.build_fixture()
        before = slate_module._load_existing_decision_keys(self.path)
        self.assertEqual(len(before), 8)

        self.rotate()

        after = slate_module._load_existing_decision_keys(self.path)
        self.assertEqual(after, before)

    def test_ensure_genesis_returns_same_row_and_appends_nothing(self):
        self.build_fixture()
        rows_before_rotation = len(HashChainLedger(self.path).read())

        self.rotate()

        rows_before_second_call = len(HashChainLedger(self.path).read())
        genesis_after = bridge.ensure_genesis(v2_path=self.path, v1_path=self.v1_path)
        rows_after_second_call = len(HashChainLedger(self.path).read())

        self.assertEqual(genesis_after, self.genesis)
        self.assertEqual(rows_after_second_call, rows_before_second_call)
        self.assertEqual(rows_before_second_call, rows_before_rotation)

    def test_slate_due_last_decision_utc_identical(self):
        self.build_fixture()
        empty_watch = self.root / "watch.jsonl"  # never written -- irrelevant here
        before = lineup_store.slate_due(watch_path=empty_watch, decisions_path=self.path)

        self.rotate()

        after = lineup_store.slate_due(watch_path=empty_watch, decisions_path=self.path)
        self.assertEqual(after["last_decision_utc"], before["last_decision_utc"])
        self.assertEqual(before["last_decision_utc"], "2026-09-28T10:00:00+00:00")

    def test_research_readiness_decision_rows_identical(self):
        self.build_fixture()
        before = research_readiness._decision_rows(self.path)
        self.assertEqual(len(before), 10)

        self.rotate()

        after = research_readiness._decision_rows(self.path)
        self.assertEqual(after, before)

    def test_verify_rows_checked_identical(self):
        self.build_fixture()
        before = HashChainLedger(self.path).verify()
        self.assertTrue(before.ok)
        self.assertEqual(before.rows_checked, 10)

        self.rotate()

        after = HashChainLedger(self.path).verify()
        self.assertTrue(after.ok)
        self.assertEqual(after.rows_checked, before.rows_checked)

    def test_tier_ladder_raw_read_identical(self):
        from scripts import test_tier_ladder
        self.build_fixture()
        with mock.patch.object(test_tier_ladder, "DECISIONS", str(self.path)), \
             mock.patch.object(test_tier_ladder, "system_class",
                               lambda sid: "FORWARD_TEST"):
            # Every row here is verdict="no_play", so this is a (legitimately
            # empty, and identically so) parity check on the read path
            # itself -- `_load_plays` only records verdict=="play" rows.
            before = test_tier_ladder._load_plays()
            self.rotate()
            after = test_tier_ladder._load_plays()
        self.assertEqual({k: dict(v) for k, v in after.items()},
                         {k: dict(v) for k, v in before.items()})


class D_VerifyAcrossSegmentBoundary(DecisionsLedgerRotationTestCase):
    def test_verify_ok_spanning_segment_and_hot(self):
        self.build_fixture()
        self.rotate()
        result = HashChainLedger(self.path).verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 10)

    def test_tampering_a_row_inside_the_segment_is_detected_at_the_right_logical_line(self):
        self.build_fixture()
        self.rotate()
        segs = store_archive.segments(self.path)
        self.assertEqual(len(segs), 1)

        # Row index 2 within the segment (0=genesis, 1=e1, 2=e2, ...) is
        # logical line 3 -- tamper its payload without recomputing row_hash.
        _rewrite_segment_row(segs[0], 2, lambda row: row.__setitem__("event_id", "TAMPERED"))

        result = HashChainLedger(self.path).verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 3)
        self.assertIn("row_hash", result.reason)

    def test_tampering_a_row_inside_the_hot_file_is_detected_at_the_right_logical_line(self):
        self.build_fixture()
        self.rotate()

        # Hot file holds logical rows 9-10 (e7, e8); index 0 within it is
        # logical line 9.
        _rewrite_hot_row(self.path, 0, lambda row: row.__setitem__("event_id", "TAMPERED"))

        result = HashChainLedger(self.path).verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 9)
        self.assertIn("row_hash", result.reason)


class E_AppendChainsAcrossRotation(DecisionsLedgerRotationTestCase):
    def test_append_after_rotation_chains_to_true_last_row(self):
        rows = self.build_fixture()
        last_hash_before = rows[-1]["row_hash"]

        self.rotate()

        new_row = HashChainLedger(self.path).append({"probe": "after-rotation"})
        self.assertEqual(new_row["prev_hash"], last_hash_before)

        result = HashChainLedger(self.path).verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 11)

    def test_last_hash_falls_back_to_last_segment_when_hot_file_is_forced_empty(self):
        rows = self.build_fixture()
        self.rotate()
        segs = store_archive.segments(self.path)
        expected_fallback = _last_row_hash_of_segment(segs[-1])
        self.assertEqual(expected_fallback, rows[7]["row_hash"])  # e6, last archived row

        self.path.write_bytes(b"")  # force the hot file empty

        self.assertEqual(HashChainLedger(self.path).last_hash(), expected_fallback)

        appended = HashChainLedger(self.path).append({"probe": "forced-empty-hot"})
        self.assertEqual(appended["prev_hash"], expected_fallback)
        self.assertTrue(HashChainLedger(self.path).verify().ok)

    def test_last_hash_falls_back_to_last_segment_when_hot_file_is_forced_absent(self):
        rows = self.build_fixture()
        self.rotate()
        segs = store_archive.segments(self.path)
        expected_fallback = _last_row_hash_of_segment(segs[-1])

        self.path.unlink()  # force the hot file absent entirely

        self.assertEqual(HashChainLedger(self.path).last_hash(), expected_fallback)

        appended = HashChainLedger(self.path).append({"probe": "forced-absent-hot"})
        self.assertEqual(appended["prev_hash"], expected_fallback)
        self.assertTrue(self.path.exists())  # append() recreates it
        self.assertTrue(HashChainLedger(self.path).verify().ok)

    def test_last_hash_never_opens_the_archive_when_the_hot_file_already_answers(self):
        """Performance contract (DESIGN item 1): once the hot file has a
        row, `last_hash()` must not decompress any segment at all."""
        self.build_fixture()
        self.rotate()

        with mock.patch("gzip.open", side_effect=AssertionError(
                "last_hash() must not open a segment when the hot file "
                "already has a row")):
            result = HashChainLedger(self.path).last_hash()
        self.assertEqual(result, HashChainLedger(self.path).read()[-1]["row_hash"])


class F_RerotateWithSameNowIsNoOp(DecisionsLedgerRotationTestCase):
    def test_second_rotate_is_a_no_op_and_creates_no_segment(self):
        self.build_fixture()
        first = self.rotate()
        self.assertTrue(first["rotated"])
        segs_before = store_archive.segments(self.path)
        self.assertEqual(len(segs_before), 1)
        seg_bytes_before = segs_before[0].read_bytes()
        hot_bytes_before = self.path.read_bytes()

        second = self.rotate()
        self.assertFalse(second["rotated"])

        segs_after = store_archive.segments(self.path)
        self.assertEqual(segs_after, segs_before)
        self.assertEqual(segs_after[0].read_bytes(), seg_bytes_before)
        self.assertEqual(self.path.read_bytes(), hot_bytes_before)


class G_InterruptedRotationLeavesStoreUnchanged(DecisionsLedgerRotationTestCase):
    def test_a_failed_byte_identity_proof_leaves_the_store_unchanged_and_verifiable(self):
        rows = self.build_fixture()
        original_bytes = self.original_bytes

        real_gzip_open = gzip.open

        def corrupting_open(path, mode="rb", *a, **kw):
            if str(path).endswith(".tmp") and "r" in mode:
                class _Corrupt:
                    def __enter__(self_):
                        return self_

                    def __exit__(self_, *exc):
                        return False

                    def read(self_):
                        return b"not the archived prefix"
                return _Corrupt()
            return real_gzip_open(path, mode, *a, **kw)

        with mock.patch.object(store_archive.gzip, "open", side_effect=corrupting_open):
            with self.assertRaises(store_archive.StoreArchiveError):
                self.rotate()

        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(store_archive.segments(self.path), [])

        result = HashChainLedger(self.path).verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 10)
        self.assertEqual(HashChainLedger(self.path).read(), rows)

    def test_a_failed_hot_file_replace_rolls_back_the_segment(self):
        import os as os_module
        rows = self.build_fixture()
        original_bytes = self.original_bytes

        real_replace = os_module.replace
        calls = {"n": 0}

        def fail_second_replace(src, dst, **kw):
            calls["n"] += 1
            if calls["n"] == 2:  # 1st moves the segment; 2nd moves the hot file
                raise OSError(28, "No space left on device")
            return real_replace(src, dst, **kw)

        with mock.patch.object(store_archive.os, "replace", side_effect=fail_second_replace):
            with self.assertRaises(OSError):
                self.rotate()

        self.assertEqual(store_archive.segments(self.path), [])
        self.assertEqual(self.path.read_bytes(), original_bytes)

        result = HashChainLedger(self.path).verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 10)
        self.assertEqual(HashChainLedger(self.path).read(), rows)


class H_MinHotRowsAlwaysLeavesLastRow(DecisionsLedgerRotationTestCase):
    def test_min_hot_rows_one_keeps_the_last_row_even_though_every_row_qualifies_by_date(self):
        # A fresh, small chain where EVERY row (including the last) is dated
        # long before the cutoff, so the cutoff-date rule ALONE would archive
        # everything -- min_hot_rows=1 must still keep one row in the hot file.
        genesis = bridge.ensure_genesis(v2_path=self.path, v1_path=self.v1_path)
        ledger = HashChainLedger(self.path)
        d1 = ledger.append(_decision_row("x1", "sysA", "2026-09-01T01:00:00+00:00"))
        d2 = ledger.append(_decision_row("x2", "sysA", "2026-09-01T02:00:00+00:00"))
        d3 = ledger.append(_decision_row("x3", "sysA", "2026-09-01T03:00:00+00:00"))

        report = store_archive.rotate(
            self.path, keep_days=KEEP_DAYS, now=NOW, threshold_bytes=THRESHOLD_BYTES,
            stamp_of=STAMP_OF, min_hot_rows=MIN_HOT_ROWS)
        self.assertTrue(report["rotated"])
        self.assertEqual(report["archived_lines"], 3)  # genesis + d1 + d2, NOT d3

        remaining = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(json.loads(remaining[0])["row_hash"], d3["row_hash"])

        self.assertTrue(HashChainLedger(self.path).verify().ok)
        self.assertEqual(HashChainLedger(self.path).read(),
                         [genesis, d1, d2, d3])

    def test_min_hot_rows_leaves_nothing_eligible_is_a_clear_no_op(self):
        # A lone genesis row: min_hot_rows=1 caps the archivable prefix at
        # zero lines outright (n_complete=1, min_hot_rows=1).
        bridge.ensure_genesis(v2_path=self.path, v1_path=self.v1_path)
        report = store_archive.rotate(
            self.path, keep_days=KEEP_DAYS, now=NOW, threshold_bytes=THRESHOLD_BYTES,
            stamp_of=STAMP_OF, min_hot_rows=MIN_HOT_ROWS)
        self.assertFalse(report["rotated"])
        self.assertIn("min_hot_rows", report["reason"])
        self.assertEqual(store_archive.segments(self.path), [])


class NoArchiveDirectoryBehavesExactlyAsBefore(unittest.TestCase):
    """A card-ledger-style chain (arbitrary schema, no dates, never
    rotated) must be completely unaffected by chain.py's archive-awareness:
    `store_archive.segments()` returns `[]` for it, so every new code path
    falls through to a plain read, byte for byte."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "card_ledger_v1.jsonl"

    def test_read_verify_last_hash_append_all_match_a_plain_file_read(self):
        ledger = HashChainLedger(self.path)
        appended = [ledger.append({"bet_id": f"b{i}", "stake": i}) for i in range(5)]

        self.assertEqual(store_archive.segments(self.path), [])

        # Reconstruct rows from the raw bytes exactly the way `iter_lines`
        # does (binary mode, decode, strip) rather than assuming a specific
        # line terminator -- HashChainLedger.append() opens its file in text
        # mode without `newline=""`, so this platform's own convention
        # (`\r\n` on Windows, `\n` on POSIX) is whatever is actually on disk;
        # every real reader already tolerates either (`.strip()` before
        # `json.loads`), which is exactly what this re-proves for the
        # no-archive-directory path.
        raw = self.path.read_bytes()
        reconstructed = [json.loads(line.strip()) for line in raw.split(b"\n") if line.strip()]
        self.assertEqual(reconstructed, appended)

        self.assertEqual(ledger.read(), appended)
        self.assertEqual(list(ledger), appended)
        self.assertEqual(ledger.last_hash(), appended[-1]["row_hash"])

        result = ledger.verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 5)

        # A missing chain still falls all the way back to GENESIS_HASH.
        missing = HashChainLedger(Path(self._tmp.name) / "never_written.jsonl")
        self.assertEqual(missing.last_hash(), GENESIS_HASH)
        self.assertEqual(missing.read(), [])
        self.assertTrue(missing.verify().ok)
        self.assertEqual(missing.verify().rows_checked, 0)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Additions from the 2026-09-28 design review: a second segment, the
# interrupted-rotation duplicate prefix, a non-vacuous tier-ladder parity
# check, and bridge.verify across the boundary.
# ---------------------------------------------------------------------------

class I_SecondSegment(DecisionsLedgerRotationTestCase):
    def _two_segments(self):
        rows = self.build_fixture()
        self.rotate()  # -> 0001 (rows 1-8 archived; d7, d8 stay hot)
        ledger = HashChainLedger(self.path)
        later = [ledger.append(_decision_row(f"late{i}", "sysA", f"{day}T10:00:00+00:00"))
                 for i, day in enumerate(("2026-09-29", "2026-09-30", "2026-10-01"))]
        report = self.rotate(now=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))
        self.assertTrue(report["rotated"], report)
        return rows, later

    def test_a_later_day_rotation_creates_0002_named_from_its_own_dates(self):
        self._two_segments()
        names = [s.name for s in store_archive.segments(self.path)]
        self.assertEqual(names[0][:4], "0001")
        # d7 (09-27), d8 (09-28), late0 (09-29), late1 (09-30) are archived;
        # min_hot_rows=1 keeps late2 (10-01) in the hot file.
        self.assertEqual(names[1], "0002_2026-09-27_2026-09-30.jsonl.gz")

    def test_readers_span_both_segments_in_order_and_the_chain_verifies(self):
        rows, later = self._two_segments()
        expected = [r["row_hash"] for r in rows + later]
        self.assertEqual([r["row_hash"] for r in HashChainLedger(self.path).read()], expected)
        result = HashChainLedger(self.path).verify()
        self.assertTrue(result.ok, result)
        self.assertEqual(result.rows_checked, len(expected))

    def test_last_hash_prefers_the_hot_file_then_the_newest_segment(self):
        rows, later = self._two_segments()
        ledger = HashChainLedger(self.path)
        self.assertEqual(ledger.last_hash(), later[2]["row_hash"])
        self.path.write_bytes(b"")  # forced empty hot file
        self.assertEqual(ledger.last_hash(), later[1]["row_hash"],
                         "must fall back to the NEWEST segment's last row, not 0001's")


class J_InterruptedRotationDuplicatePrefix(DecisionsLedgerRotationTestCase):
    """A hard kill between rotate()'s two os.replace calls leaves the
    archived prefix in the segment AND still in the hot file. verify() must
    see it, and the next rotate() must refuse rather than archive the same
    prefix a second time."""

    def _duplicate_state(self):
        self.build_fixture()
        report = self.rotate()
        self.assertTrue(report["rotated"])
        # the segment is durable; the hot file was never replaced
        self.path.write_bytes(self.original_bytes)
        return report

    def test_verify_reports_the_break_at_the_first_hot_row(self):
        report = self._duplicate_state()
        result = HashChainLedger(self.path).verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, report["archived_lines"] + 1)

    def test_a_second_rotate_refuses_and_touches_nothing(self):
        self._duplicate_state()
        segments_before = store_archive.segments(self.path)
        report = self.rotate()
        self.assertFalse(report["rotated"])
        self.assertTrue(report["reason"].startswith("ESCALATE duplicate prefix"), report["reason"])
        self.assertEqual(store_archive.segments(self.path), segments_before)
        self.assertEqual(self.path.read_bytes(), self.original_bytes)

    def test_the_cli_treats_the_refusal_as_a_failure(self):
        import io
        from contextlib import redirect_stdout
        from src import cli
        self._duplicate_state()
        registry = {"tmpledger": {"path": self.path, "stamp_of": STAMP_OF,
                                  "min_hot_rows": MIN_HOT_ROWS}}
        out = io.StringIO()
        with mock.patch.object(store_archive, "ROTATABLE_STORES", registry), \
             redirect_stdout(out):
            code = cli.main(["store", "rotate", "--store", "tmpledger",
                             "--if-over-mb", "0.000001", "--keep-days", str(KEEP_DAYS),
                             "--now", NOW.isoformat()])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ESCALATE duplicate prefix", out.getvalue())
        self.assertEqual(self.path.read_bytes(), self.original_bytes)


class K_TierLadderParityIsNotVacuous(DecisionsLedgerRotationTestCase):
    def test_a_forward_test_play_inside_the_archived_prefix_is_still_read(self):
        from scripts import test_tier_ladder
        self.build_fixture()
        # A real play row, dated inside the prefix the rotation will archive.
        HashChainLedger(self.path).append(_decision_row(
            "e9", "sysF", "2026-09-26T11:00:00+00:00", verdict="play",
            market_key="h2h", selection_id="sel-9", price_american=-110,
            stake_units=1.0))
        with mock.patch.object(test_tier_ladder, "DECISIONS", str(self.path)), \
             mock.patch.object(test_tier_ladder, "system_class",
                               lambda sid: "FORWARD_TEST"):
            before = {k: dict(v) for k, v in test_tier_ladder._load_plays().items()}
            report = self.rotate(now=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc))
            self.assertTrue(report["rotated"])
            after = {k: dict(v) for k, v in test_tier_ladder._load_plays().items()}
        self.assertEqual(list(before), ["2026-09-26"])
        self.assertEqual(list(before["2026-09-26"].values()), [["sysF"]])
        self.assertEqual(after, before)


class L_BridgeVerifyAfterRotation(DecisionsLedgerRotationTestCase):
    def test_bridge_verify_walks_the_whole_logical_chain(self):
        rows = self.build_fixture()
        self.rotate()
        report = bridge.verify(v1_path=self.v1_path, v2_path=self.path)
        self.assertTrue(report["v2_chain_ok"], report)
        self.assertEqual(report["v2_rows_checked"], len(rows))
        self.assertEqual(HashChainLedger(self.path).read()[0]["row_hash"],
                         self.genesis["row_hash"])
