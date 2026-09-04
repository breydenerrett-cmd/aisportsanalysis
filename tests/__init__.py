"""Test-suite package init -- the containment layer for the unit suite.

WHY THIS FILE HAS CODE IN IT
----------------------------
Two of this project's stores are append-only forward evidence and cannot be
rebuilt from any provider at any price:

    data/processed/odds_snapshots.jsonl   data/processed/odds_multibook.jsonl
    data/processed/f5_close.jsonl         data/processed/prop_listing.jsonl
    data/processed/weather_forecast.jsonl data/processed/prop_prices.jsonl
    data/processed/credit_log.jsonl
    data/watch/{probables,lineups,transactions}_watch.jsonl

and one is real user state (hashed auth tokens, saved bets, analytics):

    data/app/app.db

A unit test that appends to any of them does not "fail loudly" -- it succeeds,
and the row it wrote is indistinguishable from a real capture forever after.
The production defaults make that easy to do by accident: every writer resolves
its own path from the repo root when the caller does not pass one, and
`events.record_event_safe` swallows every exception by contract, so a test that
reaches a route which records analytics writes to the REAL app db and reports
nothing. That is exactly how 1,593 test-generated analytics rows ended up in
data/app/app.db (found 2026-09-01).

So the suite defends itself twice, at package-import time -- which under
`unittest discover` and under `python3 -m unittest tests.test_x` alike happens
before any test module is imported:

 1. REDIRECT. APP_DB_PATH is pointed at a per-process temp file unless the
    caller set it. Nothing a test does can reach the real app db.
 2. BLOCK. Any attempt to open the forward-evidence stores for writing raises.
    Not a warning, not a log line -- a test that tries this must go red, since
    a silent append to an append-only store is unrecoverable.

Plus a baseline (size + sha256 of each forward store) recorded here and
asserted unchanged by tests/test_zz_forward_store_guard.py, which is the
belt-and-braces check for a write route this file does not intercept
(subprocess, C extension, os.pwrite on an fd opened read-write elsewhere).
"""

from __future__ import annotations

import atexit
import builtins
import hashlib
import os
import shutil
import tempfile
import traceback
from pathlib import Path

# The repo root, derived the same way src/paths.py derives it: from this
# file's own location, never from the cwd. Deliberately NOT via
# src.paths.data_root() -- a test that legitimately sets AISPORTS_DATA_DIR
# must not thereby unlock the real stores.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_REAL_DATA = _REPO_ROOT / "data"

#: The files a test may never write. Absolute and resolved, so a relative
#: path, a symlink, or an `os.chdir` cannot route around the check.
PROTECTED_STORES = frozenset({
    _REAL_DATA / "processed" / "odds_snapshots.jsonl",
    _REAL_DATA / "processed" / "odds_multibook.jsonl",
    _REAL_DATA / "processed" / "f5_close.jsonl",
    _REAL_DATA / "processed" / "prop_listing.jsonl",
    # Added with the weather/credit-log/prop-price capture streams: the same
    # failure this file exists to prevent applies to any new forward-evidence
    # store from day one, not just the ones that already learned the lesson.
    _REAL_DATA / "processed" / "weather_forecast.jsonl",
    _REAL_DATA / "processed" / "prop_prices.jsonl",
    _REAL_DATA / "processed" / "credit_log.jsonl",
    _REAL_DATA / "watch" / "probables_watch.jsonl",
    _REAL_DATA / "watch" / "lineups_watch.jsonl",
    _REAL_DATA / "watch" / "transactions_watch.jsonl",
})

#: Forward-evidence stores whose filenames are not fixed -- one file per
#: capture, named by timestamp -- so they are protected by directory prefix
#: rather than by exact path. Added with the raw (L0) odds-payload capture
#: layer (docs/COLLECTION_POLICY.md, "Raw layer and all-books persistence"):
#: a test that exercises `fetch_normalized`/`fetch_event_odds` without
#: redirecting `AISPORTS_DATA_DIR` would otherwise write a real, permanent
#: raw-capture file into the real repo on every run -- the exact failure
#: mode this file exists to prevent, just with a dynamic filename instead of
#: a fixed one.
PROTECTED_DIRS = frozenset({
    _REAL_DATA / "raw" / "oddsapi",
})


class ForwardStoreWriteAttempt(RuntimeError):
    """A test tried to write to an append-only forward-evidence store.

    Raised instead of allowing the write. The message carries the offending
    path and the frames that led there, because the only useful thing to do
    with this is fix the test that forgot to redirect its store path.
    """


# ---------------------------------------------------------------------------
# 1. Redirect the app db away from data/app/app.db
# ---------------------------------------------------------------------------

_APP_DB_ENV = "APP_DB_PATH"
#: Set when this module (rather than the caller) chose the app db location.
#: tests/test_appstate_users.py's "default path" test clears the variable to
#: exercise the no-override branch, and needs to know it was ours to clear.
APP_DB_REDIRECTED = False

if not (os.environ.get(_APP_DB_ENV) or "").strip():
    _tmp_app_dir = tempfile.mkdtemp(prefix="aisports-test-appdb-")
    os.environ[_APP_DB_ENV] = str(Path(_tmp_app_dir) / "app.db")
    APP_DB_REDIRECTED = True
    atexit.register(shutil.rmtree, _tmp_app_dir, True)


# ---------------------------------------------------------------------------
# 1b. A hermetic double for data/processed/credit_log.jsonl
# ---------------------------------------------------------------------------
#
# dense.run/prop_listing.run/prop_prices.run/derivative_markets.run/
# batter_props.run all gate a spend through `budget.can_spend`, whose
# ENVELOPE half (unlike the floor half, which every one of those callers
# already threads a freshly-read `remaining` through) falls back to
# `budget.spent_today()` -- a read of the real, mutating
# data/processed/credit_log.jsonl -- whenever a caller doesn't override
# `store`. Blocking WRITES to that file (section 2 below) does nothing
# about this: a read of whatever the log happens to hold today (a handful
# of rows on a quiet day, tens of thousands after an owner-approved
# historical purchase, as happened 2026-09-04) silently changes which
# branch of `can_spend` a "spend $N credits" assertion exercises. That is
# not a flaky test -- it is a test with an unpinned input, and it produced
# exactly this: 5 modules' capture tests went from green to 54 failures
# the moment a legitimate backfill purchase logged a day's spend north of
# DAILY_ENVELOPE, with no code change at all.
#
# The fix is the same shape as the app-db redirect just above: every
# affected `run()` now takes a `credit_log_store` kwarg (default None ==
# real disk, unchanged production behavior) that is threaded straight into
# `can_spend(..., store=...)`/`spent_today(store=...)`. Tests pass this
# path instead. It is a file that is guaranteed never to exist -- a fresh
# tempdir per process, never written to by anything -- so `spent_today()`
# and `remaining_today()` against it always read as "no rows for today"
# (0 spent, unknown remaining), which is why every affected test ALSO still
# passes its own `remaining=...` through the provider's `quota()` stand-in:
# this fixture only controls the half of the decision `remaining` doesn't.
_tmp_creditlog_dir = tempfile.mkdtemp(prefix="aisports-test-creditlog-")
HERMETIC_CREDIT_LOG_STORE = Path(_tmp_creditlog_dir) / "credit_log.jsonl"
atexit.register(shutil.rmtree, _tmp_creditlog_dir, True)


# ---------------------------------------------------------------------------
# 2. Block writes to the forward stores
# ---------------------------------------------------------------------------

_real_open = builtins.open
_real_path_open = Path.open
_real_os_open = os.open
_real_rename = os.rename
_real_replace = os.replace


def _is_write_mode(mode) -> bool:
    """True if `mode` would let the caller modify the file.

    Accepts both the string modes of `open()` and the int flag bitmask of
    `os.open()`; O_CREAT/O_TRUNC/O_APPEND count even without O_WRONLY,
    because creating or truncating the file is itself the damage.
    """
    if isinstance(mode, int):
        writable = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        return bool(mode & writable)
    return any(ch in str(mode) for ch in "wax+")


def _protected(path):
    """The resolved protected path `path` refers to, or None."""
    try:
        resolved = Path(path).resolve()
    except (TypeError, ValueError, OSError):
        return None  # fds, buffers, unresolvable names: not our business
    if resolved in PROTECTED_STORES:
        return resolved
    for directory in PROTECTED_DIRS:
        try:
            resolved.relative_to(directory)
        except ValueError:
            continue
        return resolved
    return None


def _refuse(path, mode):
    target = _protected(path)
    if target is None or not _is_write_mode(mode):
        return
    frames = "".join(traceback.format_stack()[:-2][-8:])
    raise ForwardStoreWriteAttempt(
        f"test tried to open {target} for writing (mode={mode!r}).\n"
        "These stores are append-only forward evidence: a row written here by "
        "a test is indistinguishable from a real capture forever. Point the "
        "writer at a tmp path (most take a path argument; snapshots/rosterwatch "
        "take snapshot_path/multibook_path/watch_dir) or set AISPORTS_DATA_DIR."
        f"\n--- call site ---\n{frames}")


def _guarded_open(file, mode="r", *args, **kwargs):
    _refuse(file, mode)
    return _real_open(file, mode, *args, **kwargs)


def _guarded_path_open(self, mode="r", *args, **kwargs):
    _refuse(self, mode)
    return _real_path_open(self, mode, *args, **kwargs)


def _guarded_os_open(path, flags, *args, **kwargs):
    _refuse(path, flags)
    return _real_os_open(path, flags, *args, **kwargs)


def _guarded_rename(src, dst, **kwargs):
    _refuse(dst, "w")
    return _real_rename(src, dst, **kwargs)


def _guarded_replace(src, dst, **kwargs):
    _refuse(dst, "w")
    return _real_replace(src, dst, **kwargs)


builtins.open = _guarded_open
Path.open = _guarded_path_open        # Path.write_text/write_bytes go through this
os.open = _guarded_os_open
os.rename = _guarded_rename
os.replace = _guarded_replace

#: Asserted by the guard test -- if someone deletes the block above, the
#: suite says so rather than quietly losing its only real defence.
WRITE_GUARD_INSTALLED = True


# ---------------------------------------------------------------------------
# 3. Baseline, for the end-of-suite check
# ---------------------------------------------------------------------------

def fingerprint_store(path: Path) -> dict:
    """Size, line count and sha256 of one store; `exists: False` if absent.

    Read with the UNWRAPPED open so the guard cannot be confused by its own
    bookkeeping, and tolerant of a store being written by a live capture
    between two calls -- that is the capture's job, and the guard test skips
    when it is running.
    """
    try:
        with _real_open(path, "rb") as fh:
            blob = fh.read()
    except FileNotFoundError:
        return {"exists": False}
    return {"exists": True, "bytes": len(blob), "lines": blob.count(b"\n"),
            "sha256": hashlib.sha256(blob).hexdigest()}


def snapshot_stores() -> dict:
    return {str(p): fingerprint_store(p) for p in sorted(PROTECTED_STORES)}


#: Taken at import time, i.e. before the first test module is even imported.
BASELINE_STORES = snapshot_stores()
