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
import signal
import subprocess
import sys
import threading
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

try:
    from scripts.foundry_beat import foundry_beat  # noqa: E402
except Exception:  # pragma: no cover -- heartbeat is optional, never fatal
    def foundry_beat(*args, **kwargs):  # type: ignore[no-redef]
        pass

# Modules that spawn bash/git subprocesses with hard wall-clock timeouts
# (8 s, 30 s, 120 s). Run beside 20+ other busy workers they time out for
# reasons that have nothing to do with the code (2026-10-04: a full run printed
# nothing for 60 minutes). They are taken OUT of the parallel shards and run
# afterwards, ALONE, one at a time. Override with --serial-modules, disable
# with --no-serial.
DEFAULT_SERIAL_MODULES = ("tests.test_daily_bootstrap",
                          "tests.test_capture_no_set_time")

HEARTBEAT_SECONDS = 60.0  # periodic "still running" line while shards run
TIMEOUT_RETURNCODE = 124  # `timeout(1)` convention

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


def normalize_module(name: str) -> str:
    """`test_x`, `tests.test_x` and `test_x.py` all become `tests.test_x`."""
    return "tests." + name.strip().removeprefix("tests.").removesuffix(".py")


def partition_serial(modules: list[str],
                     serial: list[str] | tuple[str, ...]
                     ) -> tuple[list[str], list[str]]:
    """Split `modules` into (parallel, serial_to_run_alone).

    Only serial modules that are actually in `modules` are returned (a
    `--modules` subset or an exclude file may drop them), in the order the
    serial list names them. Pure function: no I/O.
    """
    wanted = [normalize_module(m) for m in serial]
    present = set(modules)
    serial_run = [m for m in dict.fromkeys(wanted) if m in present]
    drop = set(serial_run)
    parallel = [m for m in modules if m not in drop]
    return parallel, serial_run


def parse_unittest_output(text: str) -> dict:
    """Pull Ran N / failures / errors / skipped out of a `unittest -q` tail."""
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
    return {"tests": tests, "failures": failures, "errors": errors,
            "skipped": skipped}


def aggregate_results(parallel_results: list[dict],
                      serial_results: list[dict]) -> dict:
    """Summary arithmetic: totals over BOTH phases, broken list, exit verdict.

    A result is broken if its returncode != 0 (this includes timeouts, which
    carry TIMEOUT_RETURNCODE). Pure function: unit-tested with fake results.
    """
    every = list(parallel_results) + list(serial_results)
    return {
        "total_tests": sum(r["tests"] for r in every),
        "failures": sum(r["failures"] for r in every),
        "errors": sum(r["errors"] for r in every),
        "skipped": sum(r["skipped"] for r in every),
        "timeouts": sum(1 for r in every if r.get("timed_out")),
        "broken": [r for r in every if r["returncode"] != 0],
        "parallel_tests": sum(r["tests"] for r in parallel_results),
        "serial_tests": sum(r["tests"] for r in serial_results),
    }


def _hb(msg: str) -> None:
    """Heartbeat line. stderr, flushed, `[hb]`-prefixed so it can never be
    mistaken for a `Ran N tests` / `FAIL:` / `OK:` / `FAILED:` line."""
    print(f"[hb {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


_ACTIVE: dict[str, tuple[subprocess.Popen, float, list[str]]] = {}
_ACTIVE_LOCK = threading.Lock()


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and its children (the shell-script tests spawn bash/git)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_shard(modules: list[str], label: str = "shard") -> dict:
    """Run one worker's modules in a single `unittest -q` invocation.

    One process per shard (not per module) -- see module docstring, "WHY
    SHARD BY MODULE, NOT BY INDIVIDUAL TEST" for why modules are the grain,
    and this is what keeps interpreter-startup overhead to N processes
    total instead of one per module.

    Emits a heartbeat line when the group starts and when it finishes (with
    seconds). The live Popen is registered in _ACTIVE so the overall timeout
    can name and kill what is still running.
    """
    if not modules:
        return {"modules": [], "returncode": 0, "tests": 0, "failures": 0,
                 "errors": 0, "skipped": 0, "seconds": 0.0, "output": "",
                 "timed_out": False, "label": label}
    _hb(f"{label} started: {len(modules)} module(s): {', '.join(modules)}")
    start = time.perf_counter()
    popen_kwargs = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, "-m", "unittest", "-q", *modules],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=_CLEAN_ENV, **popen_kwargs)
    with _ACTIVE_LOCK:
        _ACTIVE[label] = (proc, time.perf_counter(), modules)
    try:
        stdout, stderr = proc.communicate()
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.pop(label, None)
    elapsed = time.perf_counter() - start
    killed = bool(getattr(proc, "_tp_killed", False))
    parsed = parse_unittest_output(stderr or "")
    returncode = TIMEOUT_RETURNCODE if killed else proc.returncode
    out = (stdout or "") + (stderr or "")
    if killed:
        out += (f"\nTIMED OUT: {label} was killed after {elapsed:.0f}s by the "
                "overall --timeout-minutes limit.\n")
    _hb(f"{label} finished in {elapsed:.1f}s: {parsed['tests']} tests "
        f"[{'TIMED OUT' if killed else ('OK' if returncode == 0 else 'FAILED')}]")
    return {"modules": modules, "returncode": returncode, **parsed,
            "seconds": round(elapsed, 3), "output": out,
            "timed_out": killed, "label": label}


def _kill_all_active() -> list[tuple[str, float, list[str]]]:
    """Kill every registered shard; return (label, seconds_running, modules)."""
    with _ACTIVE_LOCK:
        snapshot = [(lab, proc, t0, mods)
                    for lab, (proc, t0, mods) in _ACTIVE.items()]
    now = time.perf_counter()
    named = []
    for lab, proc, t0, mods in snapshot:
        proc._tp_killed = True  # type: ignore[attr-defined]
        _kill_tree(proc)
        named.append((lab, now - t0, mods))
    return named


def run_parallel_phase(shards: list[list[str]], n_workers: int,
                       deadline: float | None,
                       runner=run_shard) -> tuple[list[dict], list[str]]:
    """Run shards concurrently; periodic heartbeat; honour `deadline`.

    Returns (results_in_shard_order, timed_out_report_lines). `deadline` is a
    time.perf_counter() value or None. `runner(modules, label=...)` is
    injectable for tests.
    """
    results: dict[int, dict] = {}
    report: list[str] = []
    if not shards:
        return [], report
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, n_workers)) as pool:
        futures = {pool.submit(runner, mods, label=f"worker {i}"): i
                   for i, mods in enumerate(shards)}
        pending = set(futures)
        t_phase = time.perf_counter()
        killed_already = False
        while pending:
            wait_for = HEARTBEAT_SECONDS
            if deadline is not None:
                wait_for = max(0.0, min(wait_for, deadline - time.perf_counter()))
            done, pending = concurrent.futures.wait(
                pending, timeout=wait_for,
                return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                results[futures[f]] = f.result()
            if not pending:
                break
            if (deadline is not None and time.perf_counter() >= deadline
                    and not killed_already):
                killed_already = True
                for lab, secs, mods in _kill_all_active():
                    report.append(f"{lab} still running after {secs:.0f}s: "
                                  f"{', '.join(mods)}")
                continue  # loop again to collect the killed (now finished) futures
            if not done and not killed_already:
                with _ACTIVE_LOCK:
                    live = [(lab, time.perf_counter() - t0)
                            for lab, (_p, t0, _m) in _ACTIVE.items()]
                _hb(f"{len(pending)} shard(s) still running after "
                    f"{time.perf_counter() - t_phase:.0f}s: "
                    + ", ".join(f"{lab} ({secs:.0f}s)" for lab, secs in sorted(live)))
    return [results[i] for i in range(len(shards))], report


def run_serial_phase(serial_modules: list[str], deadline: float | None,
                     runner=run_shard) -> tuple[list[dict], list[str]]:
    """Run each serial module ALONE, one after another, in this thread."""
    results: list[dict] = []
    report: list[str] = []
    for i, mod in enumerate(serial_modules):
        label = f"serial {i + 1}/{len(serial_modules)}"
        if deadline is not None and time.perf_counter() >= deadline:
            report.append(f"{label}: not started, overall timeout reached: {mod}")
            results.append({"modules": [mod], "returncode": TIMEOUT_RETURNCODE,
                            "tests": 0, "failures": 0, "errors": 0,
                            "skipped": 0, "seconds": 0.0, "timed_out": True,
                            "label": label,
                            "output": "NOT STARTED: overall timeout reached.\n"})
            continue
        timer = None
        if deadline is not None:
            def _expire():
                for lab, secs, mods in _kill_all_active():
                    report.append(f"{lab} still running after {secs:.0f}s: "
                                  f"{', '.join(mods)}")
            timer = threading.Timer(max(0.0, deadline - time.perf_counter()),
                                    _expire)
            timer.daemon = True
            timer.start()
        try:
            results.append(runner([mod], label=label))
        finally:
            if timer is not None:
                timer.cancel()
    return results, report


def check_forward_stores_unchanged(baseline: dict) -> tuple[bool, str]:
    """The authoritative, whole-run fingerprint check. See module docstring.

    Returns (ok, message). `ok=True` covers both "unchanged" and "skipped
    because a live capture is running" -- see
    tests/test_zz_forward_store_guard.py's `capture_probe` docstring for why
    a live capture must never read as a failure here either, AND for why "I
    could not read /proc" is no longer allowed to masquerade as that: it
    skipped this check on every run of every non-Linux checkout, printing a
    named cause that was not true.
    """
    state, detail = guard_mod.capture_probe()
    if state == guard_mod.CAPTURE_RUNNING:
        return True, ("SKIPPED forward-store fingerprint check: "
                       f"scripts/forward_capture.sh is running ({detail}); its "
                       "appends are real captures, not contamination.")
    after = suite.snapshot_stores()
    changed = [path for path, before in sorted(baseline.items())
               if after[path] != before]
    if not changed:
        return True, f"forward-store fingerprint check: OK ({len(baseline)} stores unchanged)"
    if state == guard_mod.CAPTURE_UNKNOWN:
        # Something appended AND no process table to rule a capture in or
        # out. Not a pass and not a red: say so in full.
        lines = "\n".join(f"  - {p}" for p in changed)
        return True, ("INCONCLUSIVE forward-store fingerprint check: "
                       f"{len(changed)} store(s) changed and a live capture "
                       f"could not be ruled in or out here ({detail}).\n"
                       f"{lines}\nRe-run where the process table is readable, "
                       "or confirm by hand that no capture was in flight.")
    lines = "\n".join(f"  - {p}" for p in changed)
    return False, ("forward-store fingerprint check FAILED -- these stores "
                    f"changed during the run:\n{lines}\n"
                    "Do NOT delete the new rows; quarantine them to a dated "
                    "sidecar and find the test that wrote here.")


def main(argv: list[str] | None = None) -> int:
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
    parser.add_argument("--serial-modules", nargs="*",
                         default=list(DEFAULT_SERIAL_MODULES),
                         help="Modules removed from the parallel shards and run "
                              "afterwards ALONE, one at a time (default: "
                              + ", ".join(DEFAULT_SERIAL_MODULES) + ").")
    parser.add_argument("--no-serial", action="store_true",
                         help="Disable the serial phase: shard every module "
                              "in parallel as before.")
    parser.add_argument("--timeout-minutes", type=float, default=None,
                         help="Overall wall-clock limit. When hit, name the "
                              "shard(s) still running, kill them, and fail.")
    args = parser.parse_args(argv)

    foundry_beat("test_runner", "start", "ok")

    all_modules = args.modules or discover_modules()
    all_modules = sorted({normalize_module(m) for m in all_modules})
    excluded = load_exclusions(args.exclude_file) if args.exclude_file else set()
    modules = [m for m in all_modules if m not in excluded]
    if not modules:
        print("no test modules selected", file=sys.stderr)
        return 2

    if args.no_serial:
        parallel_modules, serial_modules = modules, []
    else:
        parallel_modules, serial_modules = partition_serial(
            modules, args.serial_modules)

    n_workers = max(1, min(args.workers, max(1, len(parallel_modules))))
    timings = load_timings(args.timings)
    shards = (shard_modules(parallel_modules, n_workers, timings)
              if parallel_modules else [])

    # Baseline taken above at import time (`suite.BASELINE_STORES`), i.e.
    # before any worker below has had a chance to run. That ordering is the
    # entire point -- see "WHY THE FORWARD-STORE FINGERPRINT CHECK RUNS
    # ONCE, HERE" above.
    baseline = suite.BASELINE_STORES

    print(f"running {len(modules)} modules "
          f"({len(excluded)} excluded) across {n_workers} workers "
          f"+ {len(serial_modules)} serial module(s) run alone afterwards...",
          file=sys.stderr, flush=True)

    wall_start = time.perf_counter()
    deadline = (wall_start + args.timeout_minutes * 60.0
                if args.timeout_minutes else None)

    # subprocess blocks its calling thread but releases the GIL while the
    # child runs, so a thread pool is enough to get N real OS processes
    # running concurrently.
    results, timeout_report = run_parallel_phase(shards, n_workers, deadline)
    serial_results: list[dict] = []
    if serial_modules:
        _hb(f"parallel phase done; running {len(serial_modules)} serial "
            f"module(s) alone: {', '.join(serial_modules)}")
        serial_results, serial_report = run_serial_phase(serial_modules, deadline)
        timeout_report += serial_report
    wall_elapsed = time.perf_counter() - wall_start

    fp_ok, fp_message = check_forward_stores_unchanged(baseline)

    agg = aggregate_results(results, serial_results)
    broken = agg["broken"]

    print("-" * 72)
    for i, r in enumerate(results):
        status = ("TIMED OUT" if r.get("timed_out")
                  else "OK" if r["returncode"] == 0 else "FAILED")
        print(f"worker {i}: {len(r['modules']):>3} modules, "
              f"{r['tests']:>4} tests, {r['seconds']:>7.1f}s  [{status}]")
    if serial_results:
        print("-" * 72)
        print("SERIAL MODULES (run alone, one at a time, after the parallel "
              "workers finished)")
        for r in serial_results:
            status = ("TIMED OUT" if r.get("timed_out")
                      else "OK" if r["returncode"] == 0 else "FAILED")
            print(f"serial {', '.join(r['modules'])}: {r['tests']:>4} tests, "
                  f"{r['seconds']:>7.1f}s  [{status}]")
    print("-" * 72)
    overall_ok = not broken and fp_ok
    summary = ("OK" if overall_ok else "FAILED")
    print(f"{summary}: {agg['total_tests']} tests in {wall_elapsed:.1f}s wall "
          f"({n_workers} workers) -- failures={agg['failures']} "
          f"errors={agg['errors']} skipped={agg['skipped']}"
          + (f" timeouts={agg['timeouts']}" if agg["timeouts"] else "")
          + (f" (parallel={agg['parallel_tests']} serial={agg['serial_tests']})"
             if serial_results else ""))
    print(fp_message)
    if timeout_report:
        print(f"OVERALL TIMEOUT: --timeout-minutes {args.timeout_minutes:g} "
              "reached; shard(s) still running when it fired:")
        for line in timeout_report:
            print(f"  - {line}")

    if broken:
        print(f"\n{len(broken)} worker(s) had failures/errors; output follows:\n",
              file=sys.stderr)
        for r in broken:
            kind = "serial module" if r in serial_results else "worker"
            print(f"=== {kind} running {', '.join(r['modules'])} ===",
                  file=sys.stderr)
            print(r["output"], file=sys.stderr)

    if overall_ok:
        foundry_beat("test_runner", "end", "ok",
                     f"{agg['total_tests']}/{agg['total_tests']} passed")
    else:
        failed = agg["failures"] + agg["errors"] + len(broken)
        foundry_beat("test_runner", "end", "down", f"{failed} failed")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
