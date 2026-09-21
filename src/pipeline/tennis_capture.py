"""Bounded h2h capture per active tennis tournament key.

WHY THIS EXISTS
---------------
Tennis tournaments are accessed via per-tournament keys (e.g., "tennis_atp_open"),
not a single sport key. The /events endpoint is free and lists matches with
commence_time; odds for one key costs 1 credit. This module schedules captures
in phases (24h, 6h, 2h windows) and tracks which (event_id, phase) pairs have
been captured so the same match is not fetched twice per window.

DESIGN: APPEND-ONLY DONE-LOG, BOUNDED PER-DAY
----------------------------------------------
Done pairs are appended to tennis_capture_done.jsonl, never deleted. Reading
the entire done log at run time and filtering by phase and commence_time is
O(n) but n is small (a few hundred/day max), and append-only is the only way
to survive a crash mid-write with correctness.

The phase window for a match is determined by its commence_time and the wall
clock now. For each phase (24h, 6h, 2h), a match is "due" in that phase if:
- The window opened (commence_time <= now + phase_minutes)
- The match has not started yet (commence_time > now)
- The (event_id, phase) pair is not in the done log
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Callable

from src.paths import processed_path
from src.pipeline import snapshots, creditlog
from src.capture import budget

LOG = logging.getLogger(__name__)

PHASES = (("t24h", 24 * 60), ("t6h", 6 * 60), ("t2h", 2 * 60))
MAX_KEYS_PER_DAY = 6
FAMILY = "tennis_h2h"
CREDITS_PER_CAPTURE = 1
DEFAULT_DONE_PATH = processed_path("tennis_capture_done.jsonl")

# ---------------------------------------------------------------------------
# THE PAUSE SWITCH (2026-09-21, docs/drafts/CREDIT_TRIM_PLAN_2026-09-21.md
# section 5.3)
# ---------------------------------------------------------------------------
#
# WHY. BALLDONTLIE's ATP/WTA results endpoint returns HTTP 401 while the
# account's real plan tier is unverified, so nothing captured by this module
# right now can ever be graded -- every credit spent is pure spend with zero
# evidence value, at ANY cadence. This is a PAUSE, not a cadence cut: an
# ungradable capture is worth the same near-zero amount whether it runs
# every 13 minutes or once a day, so slowing tennis down would not address
# the actual problem the way it does for dense.run.
#
# THE SWITCH is explicit and easy to flip back, the same shape as
# scripts/capture_slot.sh's own CAPTURE_CHAIN kill switch: an env var,
# defaulting to the paused state so nobody has to remember to re-set it
# during the squeeze this change exists to fix. Set TENNIS_CAPTURE_PAUSED to
# "0"/"false"/"no"/"off" to resume once BALLDONTLIE's auth/tier question is
# resolved -- no code change needed either direction.
ENV_TENNIS_PAUSED = "TENNIS_CAPTURE_PAUSED"
TENNIS_PAUSE_REASON = (
    "paused: BALLDONTLIE ATP/WTA results return HTTP 401, so captured tennis "
    "prices are ungradable (docs/drafts/CREDIT_TRIM_PLAN_2026-09-21.md 5.3); "
    "set TENNIS_CAPTURE_PAUSED=0 to resume once results are readable again"
)


def tennis_capture_paused(env=None) -> bool:
    """True unless TENNIS_CAPTURE_PAUSED is explicitly set to a falsy value.

    `env`, if given, is a dict to read (used for testing); omit it to read
    the real process environment. Defaults to PAUSED (True) with no env var
    set at all -- see the block comment above for why that is the safe
    default while BALLDONTLIE returns 401 on tennis results.
    """
    import os
    if env is None:
        env = os.environ
    value = env.get(ENV_TENNIS_PAUSED, "1").strip().lower()
    return value not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class DonePair:
    """Immutable marker: (key, event_id, phase) was captured at observed_utc."""
    key: str
    event_id: str
    phase: str
    observed_utc: str


def _read_done(path: str | Path = DEFAULT_DONE_PATH) -> set:
    """Read done pairs as a set of (key, event_id, phase) tuples for O(1) lookup.

    Never raises. Corrupted lines (invalid JSON) are skipped; empty file or
    file not found returns an empty set.
    """
    done_set = set()
    path = Path(path)
    if not path.exists():
        return done_set
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    key = obj.get("key")
                    event_id = obj.get("event_id")
                    phase = obj.get("phase")
                    if key and event_id and phase:
                        done_set.add((key, event_id, phase))
                except json.JSONDecodeError as e:
                    LOG.warning(f"Skipping corrupted line {line_num} in {path}: {e}")
    except Exception as e:
        LOG.warning(f"Error reading done log {path}: {e}")
    return done_set


def _append_done(pairs: list[DonePair], path: str | Path = DEFAULT_DONE_PATH) -> int:
    """Append done pairs as JSON Lines. Never rewrites existing content.

    Returns the number of rows written. Never raises.
    """
    if not pairs:
        return 0
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            if path.stat().st_size > 0:
                # Check if file ends with newline
                with path.open("rb") as rb:
                    rb.seek(-1, 2)
                    if rb.read(1) != b"\n":
                        f.write("\n")
            for pair in pairs:
                row = {
                    "key": pair.key,
                    "event_id": pair.event_id,
                    "phase": pair.phase,
                    "observed_utc": pair.observed_utc,
                }
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
        return len(pairs)
    except Exception as e:
        LOG.warning(f"Error appending to done log {path}: {e}")
        return 0


def _now(now: Optional[datetime] = None) -> datetime:
    """Get current UTC time or the provided override."""
    return now if now is not None else datetime.now(timezone.utc)


def _timestamp(now: Optional[datetime] = None) -> str:
    """ISO string timestamp for observations."""
    return _now(now).isoformat()


def run(*, now: Optional[datetime] = None, keys: Optional[list] = None,
        list_events: Optional[Callable] = None, fetch_normalized: Optional[Callable] = None,
        spend_guard: Optional[Callable] = None, snapshot_path: Optional[str] = None,
        multibook_path: Optional[str] = None, done_path: str = DEFAULT_DONE_PATH,
        env: Optional[dict] = None, quota: Optional[Callable] = None,
        record_credit: Optional[Callable] = None,
        paused: Optional[bool] = None) -> dict:
    """Run one cycle of tennis h2h capture.

    `paused`: None (the default) reads `tennis_capture_paused()` off the
    real process environment; a test passes True/False explicitly to
    control it without touching os.environ. Paused returns immediately --
    no `keys` resolution, no `list_events`/`fetch_normalized` call, no
    credit spend -- so the pause is a true no-op, not a cheaper capture.

    Args:
        now: Override current time for testing.
        keys: Tournament keys to capture. Default: lazy import and call
              src.pipeline.tennis_discovery.active_keys()
        list_events: Function to list events. Default: lazy import and call
                     src.providers.odds.list_events(env=env, sport=key)
        fetch_normalized: Function to fetch normalized odds. Default: lazy import
                          and call src.providers.odds.fetch_normalized(markets=["h2h"],
                          env=env, sport=key)
        spend_guard: Function to check budget. Default: lazy import and call
                     src.capture.budget.can_spend(FAMILY, CREDITS_PER_CAPTURE, now=now)
        snapshot_path: Path to write legacy rows. Default: snapshots.DEFAULT_SNAPSHOT_PATH
        multibook_path: Path to write multibook rows. Default: derived from snapshot_path
        done_path: Path to the done log.
        env: Environment dict for API calls.

    Returns:
        dict with keys: keys, captured, skipped, credits, rows
    """
    current_time = _now(now)
    observed_utc = _timestamp(current_time)

    if paused is None:
        paused = tennis_capture_paused()
    if paused:
        return {"keys": [], "captured": [], "skipped": {"_all": TENNIS_PAUSE_REASON},
                "credits": 0, "rows": 0, "paused": True}

    # Lazy defaults
    if keys is None:
        try:
            from src.pipeline import tennis_discovery
            keys = tennis_discovery.active_keys()
        except Exception as e:
            LOG.error(f"Failed to load active_keys: {e}")
            keys = []

    if list_events is None:
        from src.providers import odds
        list_events = odds.list_events

    if fetch_normalized is None:
        from src.providers import odds
        fetch_normalized = odds.fetch_normalized
        # Credit logging defaults ON only for the real provider. A caller
        # that injects a fake fetch (every test) spends nothing, so it logs
        # nothing unless it injects a logger too -- which keeps tests out of
        # data/processed/credit_log.jsonl by construction.
        if quota is None:
            quota = odds.quota
        if record_credit is None:
            record_credit = creditlog.log

    if spend_guard is None:
        spend_guard = budget.can_spend

    # Derive default paths
    if snapshot_path is None:
        snapshot_path = snapshots.DEFAULT_SNAPSHOT_PATH
    if multibook_path is None:
        multibook_path = snapshots._resolve_multibook_path(snapshot_path, None)

    # Read done pairs
    done_set = _read_done(done_path)

    # Select at most MAX_KEYS_PER_DAY, ordered by earliest upcoming match
    selected_keys = _select_keys(keys, list_events, current_time, env, max_count=MAX_KEYS_PER_DAY)

    captured_keys = []
    skipped = {}
    total_rows = 0

    for key in selected_keys:
        # List events for this tournament (free)
        try:
            events = list_events(env=env, sport=key)
        except Exception as e:
            skipped[key] = f"list_events error: {str(e)}"
            continue

        if not events:
            continue

        # Determine which (event_id, phase) pairs are due
        due_pairs = []
        for event in events:
            event_id = event.get("id")
            commence_time_str = event.get("commence_time")
            if not event_id or not commence_time_str:
                continue

            try:
                commence_time = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            # A match is due in a phase if:
            # - window opened: commence_time <= now + phase_minutes
            # - not started: commence_time > now
            # - not already done: (key, event_id, phase) not in done_set
            if commence_time <= current_time:
                # Match has started or is in the past; no phases are due
                continue

            for phase_name, phase_minutes in PHASES:
                phase_window = current_time + timedelta(minutes=phase_minutes)
                if commence_time <= phase_window and (key, event_id, phase_name) not in done_set:
                    due_pairs.append((event_id, phase_name))

        if not due_pairs:
            continue

        # Check budget
        # No `store=` here. The first version passed store=done_path -- this
        # module's own done log -- as the CREDIT log, so the guard found no
        # credit row for today and refused every tennis capture with "quota
        # unreadable" on the runner (2026-09-15 05:14Z), minutes after the
        # NFL capture read the same real log fine.
        decision = spend_guard(FAMILY, CREDITS_PER_CAPTURE, now=current_time)
        if not decision.allowed:
            skipped[key] = decision.reason
            continue

        # Fetch normalized odds for this key
        try:
            payload = fetch_normalized(markets=["h2h"], env=env, sport=key)
        except Exception as e:
            skipped[key] = f"fetch error: {str(e)}"
            continue

        # Build rows (legacy + multibook) exactly as snapshots.capture does
        rows = []
        for event in payload.get("events", []):
            event_id = event.get("event_id")
            for market_key, market in (event.get("markets") or {}).items():
                row = {
                    "observed_utc": observed_utc,
                    "event_id": event_id,
                    "commence_time": event.get("commence_time"),
                    "away_team": event.get("away_team"),
                    "home_team": event.get("home_team"),
                    "market": market_key,
                    "book": market.get("book"),
                    "prices": {k: v for k, v in market.items() if k not in ("book", "last_update")},
                    "book_last_update": market.get("last_update"),
                    "sport": key,
                    "tournament_key": key,
                }
                rows.append(row)

        # Write legacy rows
        written = snapshots.append(rows, path=snapshot_path)

        # Write multibook rows
        mb_rows = snapshots.multibook_rows(observed_utc, payload.get("events", []), sport=key)
        for row in mb_rows:
            row["tournament_key"] = key
        mb_written = snapshots.append(mb_rows, path=multibook_path)

        # Mark done pairs
        done_pairs = [DonePair(key, event_id, phase, observed_utc)
                      for event_id, phase in due_pairs]
        _append_done(done_pairs, done_path)

        captured_keys.append(key)
        total_rows += written + mb_written

        # Log credit usage: the provider's real remaining balance, in a real
        # budget band. The first version wrote remaining=None under the
        # family name as the band (not a band) to store=None; a None
        # "remaining" row is the one thing that can make the budget guard
        # read the quota as unreadable and refuse every capture after it.
        if record_credit is not None:
            try:
                quota_now = quota(env) if quota is not None else {}
                record_credit(quota_now.get("remaining"), quota_now.get("last"),
                              f"tennis_capture.run ({key})", now=current_time,
                              budget_band="live_capture")
            except Exception as exc:  # noqa: BLE001 -- logging never fails a capture
                LOG.warning("tennis_capture: credit log failed for %s: %s", key, exc)

    return {
        "keys": selected_keys,
        "captured": captured_keys,
        "skipped": skipped,
        "credits": len(captured_keys) * CREDITS_PER_CAPTURE,
        "rows": total_rows,
    }


def _select_keys(keys: list, list_events: Callable, now: datetime,
                 env: Optional[dict], max_count: int) -> list:
    """Select at most max_count keys, ordered by earliest upcoming match.

    Returns a list of keys ordered so that the key with the earliest
    upcoming match comes first. If we have more keys than max_count,
    we drop the ones with the latest earliest matches.
    """
    if not keys or len(keys) <= max_count:
        return keys[:max_count]

    # Build (earliest_commence_time, key) pairs
    key_times = []
    for key in keys:
        try:
            events = list_events(env=env, sport=key)
            earliest = None
            for event in events:
                commence_time_str = event.get("commence_time")
                if not commence_time_str:
                    continue
                try:
                    t = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
                    if t > now and (earliest is None or t < earliest):
                        earliest = t
                except (ValueError, AttributeError):
                    pass
            if earliest is not None:
                key_times.append((earliest, key))
        except Exception:
            pass

    # Sort by earliest time, take first max_count
    key_times.sort()
    return [key for _, key in key_times[:max_count]]
