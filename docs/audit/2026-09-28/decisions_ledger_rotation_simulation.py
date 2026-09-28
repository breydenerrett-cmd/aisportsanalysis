"""Deterministic simulation of hot/cold rotation for evidence/decisions_v2.jsonl.

Runs ONLY against fresh copies of decisions_v2.origin.jsonl (this script's own
sibling file), made inside a fresh tempfile.TemporaryDirectory() per copy.
Never reads, writes, or rotates:
  - the real repo file (C:\\Users\\KC\\Desktop\\aisportsanalysis\\evidence\\decisions_v2.jsonl)
  - the origin copy itself (decisions_v2.origin.jsonl) -- read-only, checked
    against its known sha256/size before every use and never opened for
    writing.

For each `now` in NOW_VALUES (2026-09-28T15:00Z, 2026-09-29T13:00Z), with
keep_days=1 and threshold=60 MiB, using the REAL registered
store_archive.ROTATABLE_STORES["decisions_v2"] settings (stamp_of,
min_hot_rows) -- not a hand-rolled equivalent -- this reports:
  - BEFORE: bytes, rows, sha256, verify() result
  - the rotate() report
  - AFTER: segment name(s) + compressed size, hot bytes/rows, logical rows,
    whether sha256(concat(decompressed segments) + hot) == the original
    sha256, verify() result
  - reader-output equality before vs after: load_decisions count + a hash of
    the sorted identities, the dedupe key set hash, ensure_genesis row_hash,
    slate_due last_decision_utc, plus the two raw readers
    (research_readiness._decision_rows, test_tier_ladder._load_plays)
  - a second rotate() call (same `now`) proving a no-op
  - one synthetic append after rotation, followed by verify()
  - last_hash()/append() wall-clock timing before vs after rotation

Usage:
    python simulate_rotation.py > simulate_rotation.txt 2>&1
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(r"C:\Users\KC\Desktop\aisportsanalysis")
sys.path.insert(0, str(REPO_ROOT))

from src.engine import settle_slate  # noqa: E402
from src.engine import slate as slate_module  # noqa: E402
from src.ledger import bridge  # noqa: E402
from src.ledger.chain import HashChainLedger  # noqa: E402
from src.pipeline import lineup_store, store_archive  # noqa: E402
from scripts import research_readiness  # noqa: E402
from scripts import test_tier_ladder  # noqa: E402

SCRATCH_P1 = Path(__file__).resolve().parent
ORIGIN = SCRATCH_P1 / "decisions_v2.origin.jsonl"
EXPECTED_ORIGIN_SHA256 = "1ccee141ba0e751e3b82888609e64c7c6bf81543560fbd0af505e79e629a5721"
EXPECTED_ORIGIN_ROWS = 33252

KEEP_DAYS = 1
THRESHOLD_BYTES = 60 * 1024 * 1024  # 60 MiB
CFG = store_archive.ROTATABLE_STORES["decisions_v2"]

NOW_VALUES = [
    datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc),
    datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc),
]

OUT: list[str] = []


def emit(line: str = "") -> None:
    OUT.append(line)
    print(line)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_concat_logical(path: Path) -> str:
    """sha256 of decompress(segment) for every segment, oldest first, then
    the hot file -- exactly the byte-identity claim `rotate()`'s own proof
    makes, recomputed independently here."""
    h = hashlib.sha256()
    for segment in store_archive.segments(path):
        with gzip.open(segment, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_hot_rows(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open("rb") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def identity_of_decision(d) -> tuple:
    return (str(d.event_id), str(d.system_id), str(d.market_key),
            str(d.selection_id), str(d.decision_utc))


def hash_of_sorted(items) -> str:
    encoded = json.dumps(sorted(items), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fresh_copy(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Binary copy of the read-only origin -- shutil.copyfile never opens the
    # source for writing.
    shutil.copyfile(ORIGIN, dest)
    return dest


def verify_origin_untouched() -> None:
    size = ORIGIN.stat().st_size
    sha = sha256_file(ORIGIN)
    emit(f"origin file: {ORIGIN}")
    emit(f"  size={size} (expected 104665523: {size == 104665523})")
    emit(f"  sha256={sha} (expected match: {sha == EXPECTED_ORIGIN_SHA256})")
    if sha != EXPECTED_ORIGIN_SHA256 or size != 104665523:
        raise SystemExit("ORIGIN FILE DOES NOT MATCH THE EXPECTED FACTS -- refusing to simulate")


def reader_snapshot(path: Path, label: str) -> dict:
    t0 = time.perf_counter()
    decisions = settle_slate.load_decisions(path=path)
    t_load = time.perf_counter() - t0
    identities = [identity_of_decision(d) for d in decisions]

    t0 = time.perf_counter()
    dedupe_keys = slate_module._load_existing_decision_keys(path)
    t_dedupe = time.perf_counter() - t0
    dedupe_str_keys = [tuple(str(x) for x in k) for k in dedupe_keys]

    t0 = time.perf_counter()
    genesis = bridge.ensure_genesis(
        v2_path=path, v1_path=path.parent / "does_not_exist_forward_ledger.jsonl")
    t_genesis = time.perf_counter() - t0

    t0 = time.perf_counter()
    due = lineup_store.slate_due(
        watch_path=path.parent / "does_not_exist_watch.jsonl", decisions_path=path)
    t_slate_due = time.perf_counter() - t0

    t0 = time.perf_counter()
    rr_rows = research_readiness._decision_rows(path)
    t_rr = time.perf_counter() - t0

    with mock_module_attr(test_tier_ladder, "DECISIONS", str(path)):
        t0 = time.perf_counter()
        plays = test_tier_ladder._load_plays()
        t_plays = time.perf_counter() - t0

    snap = {
        "load_decisions_count": len(decisions),
        "load_decisions_identity_hash": hash_of_sorted(identities),
        "dedupe_key_count": len(dedupe_keys),
        "dedupe_key_hash": hash_of_sorted(dedupe_str_keys),
        "ensure_genesis_row_hash": genesis["row_hash"],
        "slate_due_last_decision_utc": due["last_decision_utc"],
        "research_readiness_decision_rows_count": len(rr_rows),
        "test_tier_ladder_plays_dates": sorted(plays.keys()),
    }
    emit(f"  [{label}] load_decisions: count={snap['load_decisions_count']} "
         f"identity_hash={snap['load_decisions_identity_hash']} ({t_load:.3f}s)")
    emit(f"  [{label}] dedupe keys: count={snap['dedupe_key_count']} "
         f"hash={snap['dedupe_key_hash']} ({t_dedupe:.3f}s)")
    emit(f"  [{label}] ensure_genesis row_hash={snap['ensure_genesis_row_hash']} "
         f"({t_genesis:.3f}s)")
    emit(f"  [{label}] slate_due last_decision_utc={snap['slate_due_last_decision_utc']} "
         f"({t_slate_due:.3f}s)")
    emit(f"  [{label}] research_readiness._decision_rows: count="
         f"{snap['research_readiness_decision_rows_count']} ({t_rr:.3f}s)")
    emit(f"  [{label}] test_tier_ladder._load_plays: dates="
         f"{snap['test_tier_ladder_plays_dates']} ({t_plays:.3f}s)")
    return snap


class mock_module_attr:
    """Tiny context manager: set `module.name = value`, restore on exit --
    avoids importing unittest.mock just for one attribute swap."""

    def __init__(self, module, name, value):
        self.module, self.name, self.value = module, name, value

    def __enter__(self):
        self.original = getattr(self.module, self.name)
        setattr(self.module, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.module, self.name, self.original)


def run_for_now(now: datetime, root: Path) -> None:
    emit("")
    emit("=" * 96)
    emit(f"SIMULATION now={now.isoformat()} keep_days={KEEP_DAYS} "
         f"threshold_bytes={THRESHOLD_BYTES} (60 MiB) registry=decisions_v2")
    emit("=" * 96)

    main_path = fresh_copy(root / "main" / "decisions_v2.jsonl")

    # ---------------------------------------------------------------- BEFORE
    before_bytes = main_path.stat().st_size
    before_verify = HashChainLedger(main_path).verify()
    before_sha256 = sha256_file(main_path)
    emit("")
    emit("-- BEFORE --")
    emit(f"  bytes={before_bytes}")
    emit(f"  rows={before_verify.rows_checked}")
    emit(f"  sha256={before_sha256}")
    emit(f"  verify: ok={before_verify.ok} rows_checked={before_verify.rows_checked} "
         f"broken_at_line={before_verify.broken_at_line} reason={before_verify.reason}")
    emit("")
    emit("-- BEFORE readers --")
    before_snapshot = reader_snapshot(main_path, "BEFORE")

    # ---------------------------------------------------------------- ROTATE
    report = store_archive.rotate(
        main_path, keep_days=KEEP_DAYS, now=now, threshold_bytes=THRESHOLD_BYTES,
        stamp_of=CFG["stamp_of"], min_hot_rows=CFG["min_hot_rows"])
    emit("")
    emit("-- ROTATE report --")
    for k in ("rotated", "segment", "archived_lines", "archived_bytes",
              "hot_size_before", "hot_size_after", "cutoff_date", "reason"):
        if k in report:
            emit(f"  {k}={report[k]}")

    # ---------------------------------------------------------------- AFTER
    segments = store_archive.segments(main_path)
    seg_info = [(s.name, s.stat().st_size) for s in segments]
    hot_bytes = main_path.stat().st_size
    hot_rows = count_hot_rows(main_path)
    logical_rows = len(HashChainLedger(main_path).read())
    concat_sha256 = sha256_concat_logical(main_path)
    after_verify = HashChainLedger(main_path).verify()

    emit("")
    emit("-- AFTER --")
    emit(f"  segments: {seg_info}")
    emit(f"  hot_bytes={hot_bytes}")
    emit(f"  hot_rows={hot_rows}")
    emit(f"  logical_rows={logical_rows}")
    emit(f"  sha256(concat(decompressed segments) + hot) == original sha256: "
         f"{concat_sha256 == before_sha256}")
    emit(f"  verify: ok={after_verify.ok} rows_checked={after_verify.rows_checked} "
         f"broken_at_line={after_verify.broken_at_line} reason={after_verify.reason}")
    emit("")
    emit("-- AFTER readers --")
    after_snapshot = reader_snapshot(main_path, "AFTER")

    emit("")
    emit("-- READER EQUALITY (before vs after) --")
    all_equal = True
    for key in before_snapshot:
        eq = before_snapshot[key] == after_snapshot[key]
        all_equal = all_equal and eq
        line = f"  {key}: equal={eq}"
        if not eq:
            line += f"  BEFORE={before_snapshot[key]!r} AFTER={after_snapshot[key]!r}"
        emit(line)
    emit(f"  ALL READER OUTPUTS IDENTICAL: {all_equal}")

    # --------------------------------------------------- SECOND ROTATE: NO-OP
    second_report = store_archive.rotate(
        main_path, keep_days=KEEP_DAYS, now=now, threshold_bytes=THRESHOLD_BYTES,
        stamp_of=CFG["stamp_of"], min_hot_rows=CFG["min_hot_rows"])
    emit("")
    emit("-- SECOND rotate() (identical now/keep_days/threshold) --")
    emit(f"  rotated={second_report['rotated']} reason={second_report.get('reason')}")
    emit(f"  segments unchanged: {store_archive.segments(main_path) == segments}")
    emit(f"  hot file unchanged: {main_path.stat().st_size == hot_bytes}")

    # ----------------------------------------------- SYNTHETIC APPEND+VERIFY
    prev_last_hash = HashChainLedger(main_path).last_hash()
    synthetic = HashChainLedger(main_path).append({
        "kind": "simulation_probe",
        "note": "synthetic row appended by simulate_rotation.py",
        "created_utc": now.isoformat(),
    })
    append_verify = HashChainLedger(main_path).verify()
    emit("")
    emit("-- SYNTHETIC APPEND after rotation, then verify() --")
    emit(f"  prev_hash used for the new row == last_hash() just before appending: "
         f"{synthetic['prev_hash'] == prev_last_hash}")
    emit(f"  new row_hash={synthetic['row_hash']}")
    emit(f"  verify after append: ok={append_verify.ok} "
         f"rows_checked={append_verify.rows_checked} "
         f"(before-append logical rows + 1 = {logical_rows + 1}, "
         f"match={append_verify.rows_checked == logical_rows + 1})")

    # --------------------------------------------------------------- TIMING
    emit("")
    emit("-- TIMING: last_hash() and one append(), before vs after rotation --")

    timing_before_path = fresh_copy(root / "timing_before" / "decisions_v2.jsonl")
    t0 = time.perf_counter()
    lh_before = HashChainLedger(timing_before_path).last_hash()
    t_lh_before = time.perf_counter() - t0
    t0 = time.perf_counter()
    HashChainLedger(timing_before_path).append(
        {"kind": "timing_probe", "created_utc": now.isoformat()})
    t_append_before = time.perf_counter() - t0

    timing_after_path = fresh_copy(root / "timing_after" / "decisions_v2.jsonl")
    t0 = time.perf_counter()
    store_archive.rotate(
        timing_after_path, keep_days=KEEP_DAYS, now=now, threshold_bytes=THRESHOLD_BYTES,
        stamp_of=CFG["stamp_of"], min_hot_rows=CFG["min_hot_rows"])
    t_rotate_itself = time.perf_counter() - t0
    t0 = time.perf_counter()
    lh_after = HashChainLedger(timing_after_path).last_hash()
    t_lh_after = time.perf_counter() - t0
    t0 = time.perf_counter()
    HashChainLedger(timing_after_path).append(
        {"kind": "timing_probe", "created_utc": now.isoformat()})
    t_append_after = time.perf_counter() - t0

    emit(f"  last_hash() BEFORE rotation (whole ~100MB file): {t_lh_before:.4f}s "
         f"(last_hash={lh_before[:16]}...)")
    emit(f"  append()    BEFORE rotation:                     {t_append_before:.4f}s")
    emit(f"  [rotation itself, for reference]:                {t_rotate_itself:.4f}s")
    emit(f"  last_hash() AFTER  rotation (hot file only):     {t_lh_after:.4f}s "
         f"(last_hash={lh_after[:16]}...)")
    emit(f"  append()    AFTER  rotation:                     {t_append_after:.4f}s")
    if t_lh_after > 0:
        emit(f"  last_hash() speedup (before/after): {t_lh_before / max(t_lh_after, 1e-9):.1f}x")


def main() -> None:
    emit(f"simulate_rotation.py -- run at {datetime.now(timezone.utc).isoformat()}")
    emit(f"repo root: {REPO_ROOT}")
    emit("")
    verify_origin_untouched()
    emit(f"  rows (from FACTS, not re-derived here): {EXPECTED_ORIGIN_ROWS}")

    for now in NOW_VALUES:
        with tempfile.TemporaryDirectory(prefix="decisions_rotation_sim_") as tmp:
            run_for_now(now, Path(tmp))

    emit("")
    emit("=" * 96)
    emit("SIMULATION COMPLETE -- origin file never modified (re-checking):")
    verify_origin_untouched()


if __name__ == "__main__":
    main()
