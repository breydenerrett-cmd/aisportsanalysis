#!/usr/bin/env python3
"""Time every tests/test_*.py module in its own subprocess.

WHY PER-MODULE, NOT `cProfile` OVER ONE DISCOVER RUN
-----------------------------------------------------
`unittest discover` runs everything in one process, so a profiler wrapped
around it tells you nothing about which *module* to hand to which *worker*.
scripts/test_parallel.py shards work by module, so the input it needs is a
wall-clock number per module, measured the same way test_parallel.py will
actually run it: `python3 -m unittest -q tests.<module>` in its own process.
That also means each measurement gets tests/__init__.py's guard and app-db
redirect fresh, exactly like a real worker would.

WHY CONCURRENT MEASUREMENT IS STILL HONEST
-------------------------------------------
Running 130-odd subprocesses one at a time would itself take about as long
as the serial suite (this is the same work, just repackaged) -- roughly
20 minutes paid by whoever runs this. Since each module's timer starts and
stops around its own subprocess, running several subprocesses at once under
a bounded pool (default: one per CPU) still gives a correct wall-clock
reading for THAT module; it only stops being a clean *idle-machine* number
under contention. For sharding purposes -- relative ranking, and rough
per-worker load balancing -- that is exactly what's needed, and it turns a
~20 minute measurement pass into one bounded by cpu_count().

OUTPUT
------
Writes scripts/module_timings.json (module -> seconds, tests, status),
sorted by wall time descending. test_parallel.py reads this file, when
present, to balance shards; it is deliberately checked into the repo (like
a build cache) so a fresh worker gets balanced shards without re-timing the
whole suite first. Also prints the full table to stdout.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
TIMINGS_PATH = REPO_ROOT / "scripts" / "module_timings.json"

# unittest -q prints a summary like one of:
#   Ran 12 tests in 0.345s
#   OK
#   OK (skipped=1)
#   FAILED (failures=1, errors=2, skipped=1)
_RAN_RE = re.compile(r"^Ran (\d+) tests? in ([\d.]+)s", re.MULTILINE)
_STATUS_RE = re.compile(r"^(OK|FAILED)\b(?:\s*\(([^)]*)\))?", re.MULTILINE)


def discover_modules() -> list[str]:
    """Dotted module names for every tests/test_*.py, sorted for determinism."""
    return sorted(
        f"tests.{p.stem}"
        for p in TESTS_DIR.glob("test_*.py")
        if p.stem != "__init__"
    )


def _parse_counts(text: str) -> dict:
    """Best-effort parse of unittest -q's summary; never raises.

    A module that crashes before printing a summary (import error, segfault)
    still needs a row -- callers treat missing keys as "unknown", not zero.
    """
    counts = {"tests": None, "ok": None, "failures": 0, "errors": 0, "skipped": 0}
    ran = _RAN_RE.search(text)
    if ran:
        counts["tests"] = int(ran.group(1))
    status = _STATUS_RE.search(text)
    if status:
        counts["ok"] = status.group(1) == "OK"
        detail = status.group(2) or ""
        for part in detail.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            key, _, val = part.partition("=")
            key = key.strip()
            if key in ("failures", "errors", "skipped") and val.strip().isdigit():
                counts[key] = int(val.strip())
    return counts


def time_module(module: str) -> dict:
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", module],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    # unittest -q writes its summary to stderr; stdout is normally empty.
    counts = _parse_counts(proc.stderr)
    return {
        "module": module,
        "seconds": round(elapsed, 3),
        "returncode": proc.returncode,
        **counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Concurrent subprocesses (default: os.cpu_count()).")
    parser.add_argument(
        "--top", type=int, default=15,
        help="Rows to print in the summary table (default 15).")
    parser.add_argument(
        "--out", type=Path, default=TIMINGS_PATH,
        help=f"Where to write the JSON timings file (default {TIMINGS_PATH}).")
    args = parser.parse_args()

    modules = discover_modules()
    if not modules:
        print("no tests/test_*.py modules found", file=sys.stderr)
        return 2

    workers = args.workers or None  # None -> ThreadPoolExecutor's own default
    print(f"timing {len(modules)} modules ({workers or 'cpu_count()'} at a time)...",
          file=sys.stderr)

    results = []
    wall_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        # subprocess.run blocks the calling thread but releases the GIL while
        # waiting on the child, so a thread pool (not multiprocessing) is
        # enough to run several `python3 -m unittest` children concurrently.
        for result in pool.map(time_module, modules):
            results.append(result)
    wall_elapsed = time.perf_counter() - wall_start

    results.sort(key=lambda r: r["seconds"], reverse=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "generated_by": "scripts/time_tests.py",
        "wall_seconds": round(wall_elapsed, 3),
        "modules": results,
    }, indent=2) + "\n")

    total_seconds = sum(r["seconds"] for r in results)
    failed = [r for r in results if r["returncode"] != 0]

    header = f"{'module':<45} {'seconds':>8} {'tests':>6}  status"
    print(header)
    print("-" * len(header))
    for row in results[: args.top]:
        status = "OK" if row["returncode"] == 0 else "FAILED"
        tests = row["tests"] if row["tests"] is not None else "?"
        print(f"{row['module']:<45} {row['seconds']:>8.3f} {tests!s:>6}  {status}")
    print("-" * len(header))
    print(f"sum of per-module seconds: {total_seconds:.1f}s   "
          f"measurement wall time: {wall_elapsed:.1f}s   "
          f"written to {args.out}")
    if failed:
        print(f"WARNING: {len(failed)} module(s) exited non-zero while timing "
              f"(pre-existing failures, not this script's doing): "
              + ", ".join(r["module"] for r in failed), file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
