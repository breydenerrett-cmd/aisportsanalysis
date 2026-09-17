#!/usr/bin/env python3
"""H4 lint: catch an append-only store that exists in the tree but was
never added to scripts/append_only_stores.txt -- the failure mode that
used to be caught only by a person remembering to edit two shell scripts
by name (the exact class of bug that let lineups.jsonl shrink nine times
unnoticed).

WHAT COUNTS AS "APPEND-ONLY", AND WHY THIS DEFINITION
------------------------------------------------------
This script cannot know a file's write-mode from data alone, so it infers
append-only-ness from its GROWTH HISTORY instead: scan every top-level
`*.jsonl` and `*.json` file directly under data/historical/ (the directory
the 2026-09-16 incident's stores live in -- this is a location boundary,
not a second hand-kept filename list) that has at least two commits, and
flag it as an append-only candidate only if its size (rows for .jsonl,
bytes for .json, matching lib_shrink_guard.sh's own unit choice) never
decreased between any two consecutive commits touching that path. A store
that only ever grows across its whole observed history is, empirically,
append-only; nothing else here special-cases any particular filename.

WHAT THIS DELIBERATELY CANNOT DETECT (read this before trusting a clean
run)
-------------------------------------------------------------------------
* A store with fewer than two commits -- there is no growth history yet
  to test the "never shrinks" property against, so it is silently
  skipped, not declared safe. A brand-new store looks identical to one
  that will never grow.
* A store nested in a subdirectory of data/historical/ (arsenals/,
  statcast/, balldontlie/, ...) -- only TOP-LEVEL *.jsonl/*.json files are
  scanned. Those subtrees hold per-entity fan-out data this incident's
  guard was never scoped to (lib_shrink_guard.sh's own header: multi-
  megabyte churn that does not belong in a 96-times-a-day commit), and
  walking them would need a different growth model (per-entity counts,
  not one whole-file count).
* Any append-only store outside data/historical/ entirely (data/watch,
  data/processed, evidence, data/paper_accounts) -- those directories are
  staged wholesale by capture_slot.sh/forward_capture.sh (`git add
  data/watch ...`), never by individual filename, so they are not at risk
  from the specific "someone forgot to list this file" bug this lint
  exists for. data/watch/*.jsonl etc. were walked by hand for H4 (see
  append_only_stores.txt's header) and none has ever shrunk, but that
  finding is not re-verified by this script on every run.
* A store that grew consistently up to now but would ALSO be fine to
  shrink (e.g. a cache) -- growth history proves "has only ever grown",
  never "must never shrink". That gap is why this stays a lint a human
  reads, not an auto-declare step.

USAGE
-----
    python3 scripts/lint_append_only_declarations.py [repo_root]

Exits 1 and prints one "UNDECLARED: <path>" line per candidate missing
from scripts/append_only_stores.txt; exits 0 (silent) otherwise.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store_registry import load_declared_stores  # noqa: E402

CANDIDATE_DIR = "data/historical"
CANDIDATE_EXTS = (".jsonl", ".json")


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout


def _size_at(repo_root: Path, commit: str, path: str, jsonl: bool) -> int:
    content = _git(repo_root, "show", f"{commit}:{path}")
    if jsonl:
        if not content:
            return 0
        n = content.count("\n")
        if not content.endswith("\n"):
            n += 1
        return n
    return len(content.encode("utf-8"))


def _only_ever_grows(repo_root: Path, path: str, jsonl: bool) -> bool | None:
    """None means "not enough history to judge" (fewer than two commits)."""
    commits = _git(repo_root, "log", "--format=%H", "--follow", "--", path).split()
    commits.reverse()  # oldest first
    if len(commits) < 2:
        return None
    prev = None
    for commit in commits:
        size = _size_at(repo_root, commit, path, jsonl)
        if prev is not None and size < prev:
            return False
        prev = size
    return True


def find_undeclared(repo_root: Path) -> list[str]:
    declared = set(load_declared_stores(repo_root / "scripts" / "append_only_stores.txt"))
    candidates_dir = repo_root / CANDIDATE_DIR
    undeclared = []
    if not candidates_dir.is_dir():
        return undeclared
    for entry in sorted(candidates_dir.iterdir()):
        if not entry.is_file() or entry.suffix not in CANDIDATE_EXTS:
            continue
        rel = f"{CANDIDATE_DIR}/{entry.name}"
        grows_only = _only_ever_grows(repo_root, rel, jsonl=entry.suffix == ".jsonl")
        if grows_only and rel not in declared:
            undeclared.append(rel)
    return undeclared


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    repo_root = Path(argv[0]).resolve() if argv else Path(__file__).resolve().parents[1]
    undeclared = find_undeclared(repo_root)
    for path in undeclared:
        print(f"UNDECLARED: {path} grows-only across its history but is not "
              f"in scripts/append_only_stores.txt")
    return 1 if undeclared else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
