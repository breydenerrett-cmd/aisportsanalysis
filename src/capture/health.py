"""Capture-health assessment: ONE canonical answer to "is forward capture
alive right now", derived from artifacts on disk and the lock file, never
from the monthly credit balance alone.

WHY THIS EXISTS
----------------
Before this module, "is capture healthy" was answered ad hoc: `ps`/`pgrep`
against a shell script name, staring at the newest file in
data/raw/oddsapi/, or reading `budget.remaining_today()` and assuming a
healthy number means a healthy capture. That last one is the dangerous
one -- docs/RESOURCE_POLICY.md's whole point is that live capture and
historical/probe spend are SEPARATE bands, and a program that is dead but
sitting on a fat monthly balance must never read as healthy. This module
never emits a health verdict from the balance; it only surfaces the
balance fields (`live_band_spent_today`, `live_band_remaining`,
`monthly_remaining`, `historical_spend_today`) for a human or a caller to
see alongside the real verdict, which comes from artifacts and the lock.

WHAT "healthy" MEANS HERE
---------------------------
Forward capture is scripts/forward_capture.sh (internal 45-min loop) or
scripts/capture_slot.sh (one externally-scheduled slot per invocation --
docs/CAPTURE_EXTERNALIZATION.md Option A). Either way the cadence is the
same: an hourly trip does 4 x 15-min dense captures, each of which writes
at least one data/raw/oddsapi/YYYY/MM/DD/*.jsonl.gz artifact (see
src/pipeline/dense.py). A healthy day therefore produces >100 artifacts,
and the newest artifact's age is the single most direct "is this still
running" signal available: fresher than one hourly slot plus slack means
something wrote very recently; a gap of hours means something stopped.

There is no separate heartbeat file in this repo as of this writing
(docs/CAPTURE_EXTERNALIZATION.md describes the externalized-slot design but
no heartbeat convention beyond the artifacts themselves) -- the artifacts
ARE the heartbeat. `heartbeat_path` is accepted as an optional second
liveness signal for whenever one exists, not because production wiring
passes one today.

LOCK PROBE, NOT A PROCESS SCAN
--------------------------------
Both capture scripts serialize their git commit/push through one shared
lock file (`/tmp/linehound_git.lock`, held via `flock` on fd 9 -- see
scripts/forward_capture.sh's own comment on why: concurrent runs raced
each other into stranded commits four times in 30h before the lock
existed). Whether that lock is currently held is itself a live-process
signal this module can read with a NON-BLOCKING flock attempt on the same
file, with no `pgrep -f`/process-name matching of any kind: matching by
command line is fragile (a stale zombie, another user's unrelated process,
a one-word substring collision) in a way a kernel-arbitrated flock is not.
The one place this module inspects `/proc` at all is `_self_and_ancestor_
pids`, a best-effort helper kept for callers that need to exclude their own
process tree from any future process-based signal -- it reads
`/proc/<pid>/stat` directly, never shells out to `ps`/`pgrep`, and excludes
`os.getpid()` and its parent chain so this process can never mistake its
own existence for someone else holding the lock.
"""

from __future__ import annotations

import fcntl
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.capture import budget
from src.paths import raw_path, repo_root

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

RUNNING = "RUNNING"
HEALTHY_IDLE = "HEALTHY_IDLE"
OVERDUE = "OVERDUE"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# One hourly slot (forward_capture.sh's internal loop, or four capture_slot.sh
# invocations 15 minutes apart) plus slack for a slow pass -- the dense
# capture itself, the free watch/umpire polls ahead of it, and the git
# commit/push tail. 75 = 60 + 15: one full hour between artifacts is normal
# cadence; the extra 15 covers one slow slot without false-alarming on
# ordinary jitter.
HEALTHY_IDLE_MAX_AGE_MIN = 75

# Above HEALTHY_IDLE_MAX_AGE_MIN but at or under this: capture has missed at
# least one hourly slot outright (forward_capture.sh's own "MISSED WINDOW"
# escalation covers the same territory) but has not yet gone dark for a full
# cycle-and-a-half. Worth flagging, not yet worth paging.
OVERDUE_MAX_AGE_MIN = 180

# Past OVERDUE_MAX_AGE_MIN: capture has been silent for two-plus hourly
# cycles. Nothing this repo's cadence produces should ever look like this
# during MLB hours without something having actually broken.
FAILED_AGE_MIN = OVERDUE_MAX_AGE_MIN

# An unresolved ESCALATE line found within this many minutes of `now` is
# treated as still-live evidence of a failure, even if artifacts happen to
# still be flowing (e.g. the prop-listing audit escalated while dense
# capture itself kept working) -- docs/OVERNIGHT_RUN.md is the append-only
# record forward_capture.sh's own escalation lines land in.
ESCALATE_WINDOW_MIN = 120

# A day's forward-capture cadence: 4 dense slots/hour across the MLB window
# this repo has actually observed capturing. Used only as the ">100
# artifacts/day" health note in reports; never a hard state threshold in
# `assess()`, because a fully healthy but very early-morning hour genuinely
# has produced 0 artifacts yet.
EXPECTED_DAILY_ARTIFACTS = 100

DEFAULT_LOCK_PATH = "/tmp/linehound_git.lock"

# data/raw/oddsapi/YYYY/MM/DD/<ISO-ish timestamp>-<hash>.jsonl.gz -- the
# timestamp is already in the filename, so age is read straight off the
# name. No need to open/decompress the artifact just to learn when it was
# written.
_ARTIFACT_TS_RE = re.compile(r"(\d{8}T\d{6})Z-[0-9a-f]+\.jsonl\.gz$")


def _now(now=None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


@dataclass
class HealthReport:
    """One assessment of forward-capture health. See module docstring for
    what each field means and why the state is never derived from the
    balance fields alone."""

    state: str
    last_artifact_at: Optional[datetime] = None
    artifact_age_min: Optional[float] = None
    artifacts_today: int = 0
    lock_held: Optional[bool] = None
    live_band_spent_today: Optional[int] = None
    live_band_remaining: Optional[int] = None
    monthly_remaining: Optional[int] = None
    historical_spend_today: Optional[int] = None
    last_escalate_line: Optional[str] = None
    reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line rendering, the same shape `scripts/capture_health.sh` prints."""
        age = "n/a" if self.artifact_age_min is None else f"{self.artifact_age_min:.0f}m"
        lock = "n/a" if self.lock_held is None else ("held" if self.lock_held else "free")
        return (
            f"CAPTURE_HEALTH: {self.state} "
            f"age={age} artifacts_today={self.artifacts_today} lock={lock} "
            f"live_spent={self.live_band_spent_today} live_remaining={self.live_band_remaining} "
            f"monthly_remaining={self.monthly_remaining} historical_today={self.historical_spend_today}"
            + (f" | {self.reasons[0]}" if self.reasons else "")
        )


def _self_and_ancestor_pids() -> set:
    """This process's pid plus every ancestor's, by walking /proc/<pid>/stat's
    4th field (ppid) up to init. Kept for any future process-based signal
    that needs to exclude this call's own process tree -- reading a file
    (even opening it for a non-blocking flock probe) never itself matches a
    cmdline scan, but the task's explicit guard is honored here rather than
    assumed: if a caller ever adds a /proc cmdline check, it must exclude
    these pids. Reads /proc directly; never shells out to ps/pgrep."""
    pids = set()
    pid = os.getpid()
    for _ in range(64):  # depth guard; a real process tree never nests this deep
        if pid in pids or pid <= 0:
            break
        pids.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
            # Field 4 is ppid, but field 2 (comm) is parenthesized and may
            # itself contain spaces/parens, so split after the LAST ')'.
            after = stat.rsplit(")", 1)[1].split()
            ppid = int(after[1])
        except Exception:  # noqa: BLE001 -- best-effort only, never fatal
            break
        pid = ppid
    return pids


def _flock_probe(lock_path) -> Optional[bool]:
    """True if `lock_path` is currently held by someone else, False if free,
    None if the probe itself could not run (e.g. no permission).

    Non-blocking flock attempt (LOCK_EX | LOCK_NB), exactly the primitive
    scripts/forward_capture.sh and scripts/capture_slot.sh already use to
    hold this same lock via fd 9 -- so this reads the SAME kernel state
    those scripts contend for, rather than approximating it. Opening the
    file and immediately trying (and releasing) the lock never blocks and
    never actually holds it for more than this call.
    """
    path = Path(lock_path)
    try:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        LOG.debug("health: could not open lock file %s (%s)", path, exc)
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True  # someone else holds it
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False  # we could take it -> it was free
    finally:
        os.close(fd)


def _iter_artifact_days(raw_root: Path):
    """Yield each YYYY/MM/DD directory under raw_root/oddsapi that exists,
    newest first, without walking the whole tree for old seasons."""
    oddsapi = raw_root / "oddsapi"
    if not oddsapi.is_dir():
        return
    for year_dir in sorted(oddsapi.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir(), reverse=True):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir(), reverse=True):
                if day_dir.is_dir():
                    yield day_dir


def _artifact_timestamp(path: Path) -> Optional[datetime]:
    match = _ARTIFACT_TS_RE.search(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _scan_artifacts(raw_root: Path, now: datetime):
    """Returns (last_artifact_at, artifacts_today). Scans at most the most
    recent couple of day-directories -- enough to find the newest artifact
    and today's count without walking a whole season's history on every
    health check."""
    last_at: Optional[datetime] = None
    artifacts_today = 0
    today_str = now.strftime("%Y/%m/%d")
    days_scanned = 0
    for day_dir in _iter_artifact_days(raw_root):
        days_scanned += 1
        day_str = "/".join(day_dir.parts[-3:])
        files = sorted(day_dir.glob("*.jsonl.gz"))
        for fp in files:
            ts = _artifact_timestamp(fp)
            if ts is None:
                continue
            if last_at is None or ts > last_at:
                last_at = ts
            if day_str == today_str:
                artifacts_today += 1
        # The newest artifact can only be in the newest non-empty day
        # directory we've seen so far, and "today's count" only needs
        # today's directory -- once we've covered at least two days and
        # found something, stop rather than walking a whole season.
        if days_scanned >= 2 and last_at is not None:
            break
    return last_at, artifacts_today


def _last_escalate_line(path: Optional[Path], now: datetime, window_min: int):
    """Most recent TIMESTAMPED `ESCALATE:` log entry in `path` (default
    docs/OVERNIGHT_RUN.md) if that entry's own timestamp is within
    `window_min` of `now` -- else None.

    OVERNIGHT_RUN.md is a hand/script-maintained running log, not a
    structured store, and it also discusses past escalations in ordinary
    prose long after they resolved (e.g. a retrospective explaining "...the
    clean `ESCALATE:` line -- which is why no trigger ever alerted..."). A
    plain substring match on "ESCALATE" catches that prose forever and
    reads as a permanently-unresolved failure, which is worse than missing
    a genuine one: this REQUIRES a parseable log-entry timestamp
    (`YYYY-MM-DDTHH:MM`) on the same line as the literal `ESCALATE:` marker
    the capture scripts themselves emit, and only that combination -- an
    actual dated escalation entry -- can mark capture FAILED. A line
    mentioning ESCALATE with no timestamp of its own is prose, not a log
    entry, and is skipped rather than guessed at.
    """
    if path is None:
        path = repo_root() / "docs" / "OVERNIGHT_RUN.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    entry_re = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)Z?.{0,80}?ESCALATE:")
    for line in reversed(text.splitlines()):
        if "ESCALATE:" not in line:
            continue
        match = entry_re.search(line)
        if not match:
            continue  # ESCALATE mentioned without its own dated log entry: prose, not a live signal
        ts_text = match.group(1)
        try:
            fmt = "%Y-%m-%dT%H:%M:%S" if len(ts_text) > 16 else "%Y-%m-%dT%H:%M"
            ts = datetime.strptime(ts_text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age_min = (now - ts).total_seconds() / 60.0
        if age_min > window_min:
            return None  # newest dated entry found is already stale -- older ones are staler still
        return line.strip()
    return None


def assess(now=None, raw_root=None, lock_path=None, heartbeat_path=None,
           credit_log_store=None, escalate_log_path=None) -> HealthReport:
    """Assess forward-capture health from artifacts on disk, the shared git
    lock, and (informationally only) the credit budget. Never raises: every
    sub-read is best-effort, matching the rest of this program's
    paid-critical-path convention (see src/pipeline/creditlog.py's own
    docstring on why nothing on this path should crash a caller).

    `raw_root` defaults to `src.paths.raw_path()` (i.e. data/raw); pass a
    tmp dir in tests. `lock_path` defaults to the same
    `/tmp/linehound_git.lock` the capture scripts themselves hold.
    `heartbeat_path`, if given, is checked for existence/mtime as a second
    liveness signal alongside artifacts -- see module docstring: no
    production heartbeat file exists yet, so this is a hook, not something
    wired into scripts/capture_health.sh today. `credit_log_store` threads
    through to `src.capture.budget` exactly like every paid-capture
    `run()`'s own `credit_log_store` kwarg, so a test can redirect it away
    from the real disk log (see tests/test_capture_credit_log_hermeticity.py
    for the convention this matches). `escalate_log_path` overrides where
    the last-ESCALATE-line check reads from; default docs/OVERNIGHT_RUN.md
    (a test should always pass its own tmp copy here -- the real file is a
    live, append-only operational log this module must never depend on for
    a hermetic result).
    """
    moment = _now(now)
    reasons: List[str] = []

    root = Path(raw_root) if raw_root is not None else raw_path()
    if not root.exists() or not os.access(root, os.R_OK):
        reasons.append(f"raw root missing or unreadable: {root}")
        return HealthReport(state=UNKNOWN, reasons=reasons)

    try:
        last_at, artifacts_today = _scan_artifacts(root, moment)
    except OSError as exc:
        reasons.append(f"raw root scan failed: {exc}")
        return HealthReport(state=UNKNOWN, reasons=reasons)

    heartbeat_at = None
    if heartbeat_path is not None:
        try:
            hb = Path(heartbeat_path)
            if hb.exists():
                heartbeat_at = datetime.fromtimestamp(hb.stat().st_mtime, tz=timezone.utc)
        except OSError as exc:
            reasons.append(f"heartbeat unreadable: {exc}")

    newest = last_at
    if heartbeat_at is not None and (newest is None or heartbeat_at > newest):
        newest = heartbeat_at

    age_min = None
    if newest is not None:
        age_min = max(0.0, (moment - newest).total_seconds() / 60.0)

    lock_held = _flock_probe(lock_path if lock_path is not None else DEFAULT_LOCK_PATH)

    # Budget fields are informational only -- see module docstring. Every
    # read here is best-effort; a budget-side failure must never block a
    # health verdict that artifacts/lock already answered.
    live_spent = live_remaining = monthly_remaining = historical_spend = None
    try:
        live_spent = budget.capture_spent_today(now=moment, store=credit_log_store)
        historical_spend = budget.spent_today(
            now=moment, store=credit_log_store, band=budget.HISTORICAL_BACKFILL)
        remaining = budget.remaining_today(now=moment, store=credit_log_store)
        monthly_remaining = remaining
        if remaining is not None and live_spent is not None:
            live_remaining = max(0, budget.DAILY_ENVELOPE - live_spent)
    except Exception as exc:  # noqa: BLE001 -- informational fields, never fatal
        reasons.append(f"budget read failed: {exc}")

    escalate_path = Path(escalate_log_path) if escalate_log_path is not None else None
    escalate_line = _last_escalate_line(escalate_path, moment, ESCALATE_WINDOW_MIN)

    envelope_exhausted = (
        live_remaining is not None and live_remaining <= 0
        and live_spent is not None and live_spent >= budget.DAILY_ENVELOPE
    )

    # --- state decision ------------------------------------------------
    # RUNNING: lock currently held -- a capture pass is mid-commit right now,
    # independent of artifact age (a slow pass mid-flight may not have
    # written its artifact yet).
    if lock_held:
        reasons.append("git lock held: a capture pass is in flight")
        return HealthReport(
            state=RUNNING, last_artifact_at=last_at, artifact_age_min=age_min,
            artifacts_today=artifacts_today, lock_held=lock_held,
            live_band_spent_today=live_spent, live_band_remaining=live_remaining,
            monthly_remaining=monthly_remaining, historical_spend_today=historical_spend,
            last_escalate_line=escalate_line, reasons=reasons,
        )

    if newest is None:
        reasons.append("no artifact or heartbeat ever observed")
        return HealthReport(
            state=FAILED, last_artifact_at=None, artifact_age_min=None,
            artifacts_today=artifacts_today, lock_held=lock_held,
            live_band_spent_today=live_spent, live_band_remaining=live_remaining,
            monthly_remaining=monthly_remaining, historical_spend_today=historical_spend,
            last_escalate_line=escalate_line, reasons=reasons,
        )

    if age_min is not None and age_min > FAILED_AGE_MIN:
        reasons.append(f"newest artifact is {age_min:.0f}m old (> {FAILED_AGE_MIN}m)")
    if escalate_line is not None:
        reasons.append(f"unresolved escalation within {ESCALATE_WINDOW_MIN}m: {escalate_line}")
    if envelope_exhausted:
        reasons.append("live-capture envelope exhausted for today")

    if (age_min is not None and age_min > FAILED_AGE_MIN) or escalate_line is not None or envelope_exhausted:
        state = FAILED
    elif age_min is not None and age_min > HEALTHY_IDLE_MAX_AGE_MIN:
        state = OVERDUE
        reasons.append(f"newest artifact is {age_min:.0f}m old (> {HEALTHY_IDLE_MAX_AGE_MIN}m)")
    else:
        state = HEALTHY_IDLE
        reasons.append(f"newest artifact is {age_min:.0f}m old, lock free")

    return HealthReport(
        state=state, last_artifact_at=last_at, artifact_age_min=age_min,
        artifacts_today=artifacts_today, lock_held=lock_held,
        live_band_spent_today=live_spent, live_band_remaining=live_remaining,
        monthly_remaining=monthly_remaining, historical_spend_today=historical_spend,
        last_escalate_line=escalate_line, reasons=reasons,
    )
