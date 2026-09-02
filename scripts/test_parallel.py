#!/usr/bin/env python3
"""Stdlib-only parallel test runner: shards tests/test_*.py MODULES across N
worker processes, aggregates the results, and exits non-zero on any failure.

Exists so nobody -- human or agent -- has to pay the ~20-minute cost of
`python3 -m unittest discover -s tests -q` on every iteration. See
docs/RUNBOOK.md's "Running tests" section for when to use this vs
scripts/test_fast.sh vs the raw discover command.

WHY SHARD BY MODULE, NOT BY INDIVIDUAL TEST
--------------------------------------------
Splitting individual TestCase methods across processes would need a real
test-collection step (import every module up front, enumerate methods, hand
them out) and would scatter a module's shared fixtures/class-level setup
across workers that no longer share them. Sharding whole modules keeps each
worker's `python3 -m unittest -q tests.a tests.b ...` invocation identical in
spirit to what a human would type by hand, just aimed at a subset -- so a
failure reproduces with the exact command the summary prints.

WHY THE FORWARD-STORE FINGERPRINT CHECK RUNS ONCE, HERE, NOT INSIDE A WORKER
------------------------------------------------------------------------------
tests/__init__.py installs its write-blocker (which raises the instant any
code tries to open a protected forward-evidence store for writing) at PACKAGE
IMPORT TIME. That happens fresh in every worker subprocess the moment it
imports `tests`, exactly like it happens once under plain `discover` -- so
the defence itself needs nothing special here, and this file never touches
it.

The end-of-suite PROOF (tests/test_zz_forward_store_guard.py's
`ForwardStoresUnchangedTests`) is different: it compares a baseline captured
at *its own process's* import time against the state after *that process's*
tests ran. Under `discover` there is one process, so the comparison covers
every test that ran before it. Sharded across N workers, each worker only
ever sees its OWN slice -- a worker whose baseline snapshot happens to be
taken after some other worker already ran (and, hypothetically, corrupted a
store) would compare corrupted-state against corrupted-state and PASS. That
is exactly the silent-miss this guard exists to catch, so letting each
worker's copy of that one test be the only check would quietly weaken it.

So: this runner takes ITS OWN baseline before spawning any worker, and
re-checks it once, here, in the parent, after every worker has finished --
restoring the "covers the whole run" property `discover` gave it for free.
(The module's OTHER tests in that file -- the write-blocker actually raising,
the app-db redirect actually redirecting -- do not depend on process
ordering and keep running normally as part of whichever shard draws that
module; only the cross-run authority for the fingerprint moves to the
parent, and it still contributes exactly the one test to the reported total,
same as it does under plain discover.)

WHY EACH WORKER GETS ITS OWN, UNSHARED APP-DB TEMP FILE
---------------------------------------------------------
tests/__init__.py redirects APP_DB_PATH to a fresh `tempfile.mkdtemp()` at
import time UNLESS the environment already has it set. This process imports
`tests` too (to read PROTECTED_STORES/BASELINE_STORES for the fingerprint
check below), which would set APP_DB_PATH in *this* process's environment --
and if that got inherited by every worker subprocess, every worker would
share one sqlite file and could hit real lock contention under concurrent
writes for no reason. So the environment snapshot handed to workers is taken
BEFORE importing `tests` here, guaranteeing each worker computes its own
independent temp app-db path, isolated from its siblings and from this
process.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
DEFAULT_TIMINGS_PATH = REPO_ROOT / "scripts" / "module_timings.json"

# Snapshot the environment BEFORE importing `tests` -- see module docstring,
# "WHY EACH WORKER GETS ITS OWN, UNSHARED APP-DB TEMP FILE".
_CLEAN_ENV = dict(os.environ)

sys.path.insert(0, str(REPO_ROOT))
import tests as suite  # noqa: E402  (side effect: installs guard, sets baseline)
from tests import test_zz_forward_store_guard as guard_mod  # noqa: E402

_RAN_RE = re.compile(r"^Ran (\d+) tests? in ([\d.]+)s", re.MULTILINE)
_STATUS_RE = re.compile(r"^(OK|FAILED)\b(?:\s*\(([^)]*)\))?", re.MULTILINE)


def discover_modules() -> list[str]:
    """Dotted module names for every tests/test_*.py, sorted for determinism."""
    return sorted(
        f"tests.{p.stem}"
        for p in TESTS_DIR.glob("test_*.py")
        if p.stem != "__init__"
    )


def load_exclusions(path: Path) -> set[str]:
    """Read a slow/exclude list: one module per line, `#` comments, blank ok.

    Accepts either form -- `test_evolab_sweep` or `tests.test_evolab_sweep`
    or `test_evolab_sweep.py` -- so tests/slow_modules.txt can be written by
    hand without fussing over the exact dotted form test_parallel.py uses.
    """
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        stem = line.removeprefix("tests.").removesuffix(".py")
        names.add(f"tests.{stem}")
    return names


def load_timings(path: Path) -> dict[str, float]:
    """module -> measured seconds, from scripts/time_tests.py's output.

    Returns {} (never raises) if the file is missing or unreadable -- a
    stale or absent timings file degrades balancing to round-robin, not to
    a crash. Recompute it with `python3 scripts/time_tests.py` periodically;
    nothing here checks it for staleness.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {m["module"]: float(m["seconds"]) for m in data.get("modules", [])}


def shard_modules(modules: list[str], n_workers: int,
                   timings: dict[str, float]) -> list[list[str]]:
    """Split `modules` into `n_workers` balanced groups.

    Longest-processing-time-first (LPT): sort heaviest-first, always hand
    the next module to whichever shard currently carries the least total
    time. This is a greedy 2-approximation of the optimal balanced split --
    plenty good here since the goal is "no worker left holding the bag
    while three others idle," not a provably-optimal schedule. Modules
    absent from `timings` (no timing file, or a module added since it was
    last generated) are weighted at the timing set's own mean so a handful
    of unknowns don't all pile onto the same shard by sorting to one end.
    """
    unknown_weight = (sum(timings.values()) / len(timings)) if timings else 1.0
    ordered = sorted(modules, key=lambda m: timings.get(m, unknown_weight),
                      reverse=True)
    loads = [0.0] * n_workers
    shards: list[list[str]] = [[] for _ in range(n_workers)]
    for module in ordered:
        i = min(range(n_workers), key=lambda w: loads[w])
        shards[i].append(module)
        loads[i] += timings.get(module, unknown_weight)
    return shards


def run_shard(modules: list[str]) -> dict:
    """Run one worker's modules in a single `unittest -q` invocation.

    One process per shard (not per module) -- see module docstring, "WHY
    SHARD BY MODULE, NOT BY INDIVIDUAL TEST" for why modules are the grain,
    and this is what keeps interpreter-startup overhead to N processes
    total instead of one per module.
    """
    if not modules:
        return {"modules": [], "returncode": 0, "tests": 0, "failures": 0,
                 "errors": 0, "skipped": 0, "seconds": 0.0, "output": ""}
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", *modules],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )
    elapsed = time.perf_counter() - start
    text = proc.stderr
    tests = failures = errors = skipped = 0
    ran = _RAN_RE.search(text)
    if ran:
        tests = int(ran.group(1))
    status = _STATUS_RE.search(text)
    if status:
        for part in (status.group(2) or "").split(","):
            part = part.strip()
            if "=" not in part:
                continue
            key, _, val = part.partition("=")
            val = val.strip()
            if not val.isdigit():
                continue
            if key.strip() == "failures":
                failures = int(val)
            elif key.strip() == "errors":
                errors = int(val)
            elif key.strip() == "skipped":
                skipped = int(val)
    return {
        "modules": modules, "returncode": proc.returncode, "tests": tests,
        "failures": failures, "errors": errors, "skipped": skipped,
        "seconds": round(elapsed, 3), "output": proc.stdout + proc.stderr,
    }


def check_forward_stores_unchanged(baseline: dict) -> tuple[bool, str]:
    """The authoritative, whole-run fingerprint check. See module docstring.

    Returns (ok, message). `ok=True` covers both "unchanged" and "skipped
    because a live capture is running" -- see
    tests/test_zz_forward_store_guard.py's `_capture_is_running` docstring
    for why a live capture must never read as a failure here either.
    """
    if guard_mod._capture_is_running():
        return True, ("SKIPPED forward-store fingerprint check: "
                       "scripts/forward_capture.sh is running (its appends "
                       "are real captures, not contamination).")
    after = suite.snapshot_stores()
    changed = [path for path, before in sorted(baseline.items())
               if after[path] != before]
    if not changed:
        return True, f"forward-store fingerprint check: OK ({len(baseline)} stores unchanged)"
    lines = "\n".join(f"  - {p}" for p in changed)
    return False, ("forward-store fingerprint check FAILED -- these stores "
                    f"changed during the run:\n{lines}\n"
                    "Do NOT delete the new rows; quarantine them to a dated "
                    "sidecar and find the test that wrote here.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1,
                         help="Worker processes (default: os.cpu_count()).")
    parser.add_argument("--timings", type=Path, default=DEFAULT_TIMINGS_PATH,
                         help="JSON timings file from scripts/time_tests.py "
                              f"(default {DEFAULT_TIMINGS_PATH}; balancing "
                              "falls back to round-robin if absent).")
    parser.add_argument("--exclude-file", type=Path, default=None,
                         help="Module exclude list, e.g. tests/slow_modules.txt "
                              "(one module per line). Used by scripts/test_fast.sh.")
    parser.add_argument("--modules", nargs="*", default=None,
                         help="Run only these modules (dotted or bare name); "
                              "default is every tests/test_*.py.")
    args = parser.parse_args()

    all_modules = args.modules or discover_modules()
    all_modules = sorted({m if m.startswith("tests.") else f"tests.{m}"
                           for m in all_modules})
    excluded = load_exclusions(args.exclude_file) if args.exclude_file else set()
    modules = [m for m in all_modules if m not in excluded]
    if not modules:
        print("no test modules selected", file=sys.stderr)
        return 2

    n_workers = max(1, min(args.workers, len(modules)))
    timings = load_timings(args.timings)
    shards = shard_modules(modules, n_workers, timings)

    # Baseline taken above at import time (`suite.BASELINE_STORES`), i.e.
    # before any worker below has had a chance to run. That ordering is the
    # entire point -- see "WHY THE FORWARD-STORE FINGERPRINT CHECK RUNS
    # ONCE, HERE" above.
    baseline = suite.BASELINE_STORES

    print(f"running {len(modules)} modules "
          f"({len(excluded)} excluded) across {n_workers} workers...",
          file=sys.stderr)

    wall_start = time.perf_counter()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        # subprocess.run() blocks its calling thread but releases the GIL
        # while the child runs, so a thread pool is enough to get N real
        # OS processes running concurrently.
        for result in pool.map(run_shard, shards):
            results.append(result)
    wall_elapsed = time.perf_counter() - wall_start

    fp_ok, fp_message = check_forward_stores_unchanged(baseline)

    total_tests = sum(r["tests"] for r in results)
    total_failures = sum(r["failures"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    broken = [r for r in results if r["returncode"] != 0]

    print("-" * 72)
    for i, r in enumerate(results):
        status = "OK" if r["returncode"] == 0 else "FAILED"
        print(f"worker {i}: {len(r['modules']):>3} modules, "
              f"{r['tests']:>4} tests, {r['seconds']:>7.1f}s  [{status}]")
    print("-" * 72)
    overall_ok = not broken and fp_ok
    summary = ("OK" if overall_ok else "FAILED")
    print(f"{summary}: {total_tests} tests in {wall_elapsed:.1f}s wall "
          f"({n_workers} workers) -- failures={total_failures} "
          f"errors={total_errors} skipped={total_skipped}")
    print(fp_message)

    if broken:
        print(f"\n{len(broken)} worker(s) had failures/errors; output follows:\n",
              file=sys.stderr)
        for r in broken:
            print(f"=== worker running {', '.join(r['modules'])} ===",
                  file=sys.stderr)
            print(r["output"], file=sys.stderr)

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
