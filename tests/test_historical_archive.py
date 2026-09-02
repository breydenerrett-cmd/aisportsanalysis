"""The paid historical odds purchase must be durable, and the repo must prove it.

WHY THIS TEST EXISTS
--------------------
data/historical/odds_history/ (~133MB) and data/historical/odds_first_five/
(~1.6MB) are a one-time PAID purchase from the odds provider, not a
reproducible pull -- and both live only on an ephemeral container's disk
(data/historical/* in .gitignore). That is exactly the shape of the bug
tests/test_forward_evidence_tracked.py exists to catch for forward captures:
a correct-when-written ignore rule that silently applies to data it was
never meant to cover. scripts/archive_historical.sh is the fix -- it gzips
the purchase into data/archive/historical/ so it survives in git -- and this
test checks the property that fix depends on: the archive path is actually
trackable, the scripts that produce and consume it are wired up, and
whatever has been archived so far still round-trips to the hash it was
archived with.

This test does not run the archive script itself (that costs nothing to run
here, but a stale archive left over from a previous run, or none at all on
a fresh checkout, must not fail CI) -- it only ever CHECKS what is already
on disk, skipping the content checks when nothing has been archived yet.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = REPO / "data" / "archive" / "historical"
SIDECAR = ARCHIVE_ROOT / "SHA256SUMS"
ARCHIVE_SCRIPT = REPO / "scripts" / "archive_historical.sh"
RESTORE_SCRIPT = REPO / "scripts" / "restore_historical.sh"


def _is_ignored(path: str) -> bool:
    """True when the ignore RULES would exclude this path.

    `--no-index` matters here for the same reason it does in
    test_forward_evidence_tracked.py: without it, an already-tracked file
    reads as "not ignored" regardless of what the rules say, so this would
    pass vacuously once the archive existed and only catch a mistake before
    that -- exactly backwards from what's useful.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=REPO, capture_output=True, check=False)
    return result.returncode == 0


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_gzip(gz_path: Path) -> str:
    h = hashlib.sha256()
    with gzip.open(gz_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _materialize_and_hash(rel_path: str):
    """Return the sha256 of what `rel_path` decompresses to, or None if
    nothing is on disk for it (neither a whole .gz nor split parts)."""
    full = ARCHIVE_ROOT / rel_path

    if not rel_path.endswith(".gz"):
        return _sha256_of_file(full) if full.exists() else None

    if full.exists():
        return _sha256_of_gzip(full)

    parts = sorted(ARCHIVE_ROOT.glob(f"{rel_path}.part-*"))
    if not parts:
        return None

    fd, tmp_name = tempfile.mkstemp(suffix=".gz")
    try:
        with os.fdopen(fd, "wb") as out:
            for part in parts:
                out.write(part.read_bytes())
        return _sha256_of_gzip(Path(tmp_name))
    finally:
        os.unlink(tmp_name)


def _sidecar_entries():
    entries = []
    for line in SIDECAR.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        expected_hash, rel_path = line.split(None, 1)
        entries.append((expected_hash, rel_path))
    return entries


class HistoricalArchiveWiringTests(unittest.TestCase):
    """Static checks: these must pass on every checkout, archived or not."""

    def test_archive_and_restore_scripts_exist_and_are_executable(self):
        for script in (ARCHIVE_SCRIPT, RESTORE_SCRIPT):
            self.assertTrue(script.exists(), f"missing {script}")
            self.assertTrue(
                os.access(script, os.X_OK),
                f"{script} exists but is not executable (chmod +x)")

    def test_archive_path_is_not_gitignored(self):
        probe_paths = [
            "data/archive/historical",
            "data/archive/historical/SHA256SUMS",
            "data/archive/historical/odds_history",
            "data/archive/historical/odds_history/mlb_2023.jsonl.gz",
            "data/archive/historical/odds_first_five",
            "data/archive/historical/odds_first_five/manifest.json",
        ]
        ignored = [p for p in probe_paths if _is_ignored(p)]
        self.assertEqual(
            ignored, [],
            "These archive paths are gitignored, so the paid historical "
            "odds purchase would never leave this container's disk: "
            + ", ".join(ignored))

    def test_historical_source_dirs_are_still_ignored(self):
        """The archive un-ignore must not accidentally un-ignore the live,
        ephemeral-disk copies under data/historical/ itself -- those stay
        out of git on purpose (they're what the archive is a copy OF)."""
        for path in (
            "data/historical/odds_history/mlb_2023.jsonl",
            "data/historical/odds_first_five/mlb_2023.jsonl",
        ):
            self.assertTrue(
                _is_ignored(path),
                f"{path} is no longer gitignored -- the archive negation in "
                ".gitignore is too broad and now un-ignores the live copy too")


class HistoricalArchiveContentTests(unittest.TestCase):
    """These only run once scripts/archive_historical.sh has actually
    produced an archive -- there is nothing to check on a checkout where it
    hasn't been run yet, and that must not be a failure."""

    def setUp(self):
        if not SIDECAR.exists():
            self.skipTest(f"no archive yet at {SIDECAR}")

    def test_sidecar_has_entries(self):
        self.assertTrue(_sidecar_entries(), f"{SIDECAR} exists but is empty")

    def test_each_archived_entry_decompresses_to_its_sidecar_sha256(self):
        mismatches = []
        for expected_hash, rel_path in _sidecar_entries():
            actual = _materialize_and_hash(rel_path)
            if actual is None:
                mismatches.append(f"{rel_path}: no .gz and no split parts on disk")
            elif actual != expected_hash:
                mismatches.append(
                    f"{rel_path}: sidecar says {expected_hash}, decompressed to {actual}")
        self.assertEqual(mismatches, [], "\n".join(mismatches))

    def test_no_archived_gz_exceeds_githubs_soft_limit(self):
        """A single committed blob over ~50MB is what scripts/
        archive_historical.sh's split step exists to avoid."""
        oversized = []
        for gz_path in ARCHIVE_ROOT.rglob("*.gz"):
            size = gz_path.stat().st_size
            if size > 50 * 1024 * 1024:
                oversized.append(f"{gz_path.relative_to(ARCHIVE_ROOT)} ({size}B)")
        for part_path in ARCHIVE_ROOT.rglob("*.gz.part-*"):
            size = part_path.stat().st_size
            if size > 50 * 1024 * 1024:
                oversized.append(f"{part_path.relative_to(ARCHIVE_ROOT)} ({size}B)")
        self.assertEqual(oversized, [], "committed file(s) over 50MB: " + ", ".join(oversized))


if __name__ == "__main__":
    unittest.main()
