"""Multisport game calendar for quiet-hours checks in the capture chain.

WHY THIS EXISTS: the capture chain's quiet-hours check (scripts/capture_slot.sh)
reads only the MLB schedule, so on an NFL-only day it would sleep an hour
between slots. This module reads every sport with a schedule and de-duplicates
their start times.
"""

import datetime as dt
from typing import Optional

import src.sports


def upcoming_starts(now, *, horizon_hours, specs=None) -> list[str]:
    """Collect all game starts from registered sports within the horizon.

    For each sport with a schedule_fn, fetches games for UTC dates now-1, now,
    now+1 and collects start_utc strings that fall inside (now, now + horizon).
    A sport whose schedule_fn raises is skipped and its error recorded (never
    raises). Returns a sorted, de-duplicated list of ISO start time strings.

    Args:
        now: datetime object (timezone-aware, UTC expected)
        horizon_hours: hours from now to look ahead
        specs: optional list of SportSpec objects (default: all registry specs
               with a schedule_fn)

    Returns:
        list of ISO 8601 strings, sorted, de-duplicated, within the horizon
    """
    if specs is None:
        specs = [src.sports.spec(key) for key in src.sports.keys()
                 if src.sports.spec(key).schedule_fn is not None]

    horizon = now + dt.timedelta(hours=horizon_hours)
    starts = []

    for sport_spec in specs:
        if sport_spec.schedule_fn is None:
            continue

        for delta in (-1, 0, 1):
            date_str = (now + dt.timedelta(days=delta)).date().isoformat()
            try:
                games = sport_spec.schedule_fn(date_str)
                for game in games:
                    start_utc = game.get("start_utc")
                    if start_utc:
                        starts.append(start_utc)
            except Exception:
                # Skip this date for this sport; error is recorded but never
                # raised, so an unreadable schedule never stops the check.
                pass

    # Filter to upcoming games within horizon, de-duplicate, and sort.
    upcoming = set()
    for start_str in starts:
        try:
            start_dt = dt.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if now < start_dt <= horizon:
                upcoming.add(start_str)
        except (ValueError, AttributeError):
            # Skip malformed start times.
            pass

    return sorted(upcoming)


def next_start_within(now, horizon_hours, specs=None) -> Optional[str]:
    """Return the earliest game start within the horizon, or None if none exist.

    Args:
        now: datetime object (timezone-aware, UTC expected)
        horizon_hours: hours from now to look ahead
        specs: optional list of SportSpec objects (default: all registry specs)

    Returns:
        ISO 8601 string or None
    """
    starts = upcoming_starts(now, horizon_hours=horizon_hours, specs=specs)
    return starts[0] if starts else None


def verdict(now, horizon_hours, specs=None) -> str:
    """Return the quiet-hours verdict for the capture chain.

    Args:
        now: datetime object (timezone-aware, UTC expected)
        horizon_hours: hours from now to look ahead
        specs: optional list of SportSpec objects (default: all registry specs)

    Returns:
        "ACTIVE next start <iso>" if a game starts within horizon, else "QUIET"
    """
    start = next_start_within(now, horizon_hours=horizon_hours, specs=specs)
    if start:
        return f"ACTIVE next start {start}"
    return "QUIET"


def main(argv=None, env=None, now=None):
    """CLI entry point: python -m src.sports.calendar --horizon 26

    Args:
        argv: command-line arguments (default: sys.argv[1:])
        env: environment dict (default: os.environ)
        now: current datetime for testing (default: now in UTC)

    Returns:
        None; prints verdict to stdout
    """
    import argparse
    import os
    import sys

    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    parser = argparse.ArgumentParser(description="Quiet-hours verdict for the capture chain")
    parser.add_argument("--horizon", type=int, required=True,
                        help="hours from now to check for upcoming starts")
    args = parser.parse_args(argv)

    # Check for CHAIN_FIRST_PITCHES override: space-separated ISO times.
    # Note: checking is not None, not truthiness, so empty string runs the real schedule.
    override = env.get("CHAIN_FIRST_PITCHES")
    if override is not None:
        starts = override.split()
        horizon = now + dt.timedelta(hours=args.horizon)
        upcoming = []
        for start_str in starts:
            # Do not catch exceptions here: if override is malformed, let it crash
            # so the shell sees no output and treats it as UNKNOWN (game-day cadence).
            start_dt = dt.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if now < start_dt <= horizon:
                upcoming.append(start_str)
        upcoming = sorted(upcoming)
        if upcoming:
            print(f"ACTIVE next start {upcoming[0]}")
        else:
            print("QUIET")
    else:
        print(verdict(now, args.horizon))


if __name__ == "__main__":
    main()
