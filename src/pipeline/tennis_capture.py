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
        env: Optional[dict] = None) -> dict:
    """Run one cycle of tennis h2h capture.

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
        decision = spend_guard(FAMILY, CREDITS_PER_CAPTURE, now=current_time, store=done_path,
                                families_path=None, remaining=None, spent=None)
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

        # Log credit usage
        creditlog.log(remaining=None, used_last=CREDITS_PER_CAPTURE,
                     caller=f"tennis_capture.run ({key})", store=None, now=current_time,
                     budget_band=FAMILY)

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
