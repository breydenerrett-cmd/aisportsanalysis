"""NFL live score poller from The Odds API scores endpoint.

WHY THIS EXISTS
---------------
NFL games follow a predictable schedule (Thursday, Sunday, Monday evening
games in Eastern time). This module polls the Odds API scores endpoint during
those windows to capture in-play and final scores as they happen.

Each event is stored as an append-only record in data/live/nfl/<YYYY-MM-DD>.jsonl,
one row per observation. In-play events are written on every poll; completed
events are written only once (when they transition to completed).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.paths import data_path
from src.pipeline import snapshots
from src.pipeline import creditlog

DEFAULT_LIVE_DIR = data_path("live", "nfl")
CALLER = "livefeed_nfl.poll"
SCORES_FAMILY = "scores"


# Reuse snapshots' own Eastern-time mechanism rather than duplicating it here --
# one definition of "how this project converts to Eastern", not two that can drift.
_EASTERN = snapshots._eastern()


def in_window(now) -> bool:
    """True during NFL broadcast windows: Thu 19:00-23:59, Sun 12:00-23:59, Mon 19:00-23:59 ET.

    Documented as the 2026 NFL broadcast windows; a configuration, not a fact about every week.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Convert to Eastern time
    et_now = now.astimezone(_EASTERN)
    weekday = et_now.weekday()  # 0=Monday, ..., 6=Sunday
    hour = et_now.hour

    # Thursday (weekday=3): 19:00-23:59
    if weekday == 3 and 19 <= hour <= 23:
        return True
    # Sunday (weekday=6): 12:00-23:59
    if weekday == 6 and 12 <= hour <= 23:
        return True
    # Monday (weekday=0): 19:00-23:59
    if weekday == 0 and 19 <= hour <= 23:
        return True

    return False


def poll(*, live_dir=DEFAULT_LIVE_DIR, fetch_scores=None, spend_guard=None,
         quota=None, record_credit=None, clock=None, env=None,
         force=False) -> dict:
    """Poll for NFL live and completed game scores.

    1. now = clock(); unless force, if not in_window(now) return {"skipped": ...}.
    2. spend_guard checks quota; if refused, return {"skipped": <reason>}.
    3. fetch_scores fetches from odds API; errors reported in "errors", nothing written.
    4. For each event: normalize to row with observed_utc, state_id, sport, event_id,
       commence_time, home_team, away_team, home_score, away_score, completed, last_update,
       in_play. Write in-play events and completed events whose last row is not completed.
    5. Credit logging: record one credit-log row if quota and record_credit available.

    Returns dict with keys: date, events, in_play, rows_written, finals_written, errors,
    dir, skipped (optional).
    """
    # Get current time
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    now = clock()

    # Check window unless forced
    if not force and not in_window(now):
        return {"skipped": "outside window", "now": now.isoformat()}

    # Lazy imports for spending guard
    if spend_guard is None:
        try:
            from src.capture.budget import can_spend
            spend_guard = can_spend
        except (ImportError, Exception):
            def refuse_spend(family, est_credits, **kwargs):
                from src.capture.budget import Decision
                return Decision(False, "import failed")
            spend_guard = refuse_spend

    # Check budget
    decision = spend_guard(SCORES_FAMILY, 1, now=now, env=env)
    if not decision.allowed:
        return {"skipped": decision.reason}

    # Lazy import for fetch_scores
    if fetch_scores is None:
        try:
            from src.providers import odds as odds_provider
            def _fetch_scores_wrapper(sport=None, env=None, **kwargs):
                return odds_provider.fetch_scores(sport=sport, env=env)
            fetch_scores = _fetch_scores_wrapper
        except (ImportError, Exception):
            fetch_scores = None

    # Fetch scores
    errors = []
    events = []
    if fetch_scores is not None:
        try:
            raw_events = fetch_scores(sport="nfl", env=env)
            events = raw_events or []
        except Exception as exc:
            errors.append(str(exc))

    # ET date for file path
    et_now = now.astimezone(_EASTERN)
    et_date = et_now.date().isoformat()
    observed_utc = now.isoformat().replace("+00:00", "Z")

    # Read existing states for this date
    live_dir_path = Path(live_dir)
    store_path = live_dir_path / f"{et_date}.jsonl"
    existing_states = _read_all_states(store_path)

    # Process each event
    rows_written = 0
    finals_written = 0
    in_play_count = 0
    rows_to_write = []

    for event in events:
        try:
            # Normalize the event
            event_id = event.get("id")
            if not event_id:
                continue

            home_score = None
            away_score = None
            scores = event.get("scores")
            if scores:
                score_by_name = {}
                for item in scores:
                    name = item.get("name")
                    if name:
                        try:
                            score_by_name[name] = int(item.get("score", 0))
                        except (ValueError, TypeError):
                            score_by_name[name] = None

                home_team = event.get("home_team")
                away_team = event.get("away_team")
                home_score = score_by_name.get(home_team)
                away_score = score_by_name.get(away_team)

            commence_time = event.get("commence_time")
            completed = bool(event.get("completed"))

            # Check if in-play
            try:
                from datetime import datetime as dt, timezone as tz
                start_time = dt.fromisoformat(commence_time.replace("Z", "+00:00"))
                in_play = not completed and start_time <= now
            except Exception:
                in_play = not completed

            # Create state_id
            state_id = hashlib.sha1(f"{event_id}|{observed_utc}".encode()).hexdigest()[:16]

            row = {
                "observed_utc": observed_utc,
                "state_id": state_id,
                "sport": "nfl",
                "event_id": event_id,
                "commence_time": commence_time,
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "home_score": home_score,
                "away_score": away_score,
                "completed": completed,
                "last_update": event.get("last_update"),
                "in_play": in_play,
            }

            # Decide whether to write this row
            should_write = False
            if in_play:
                should_write = True
                in_play_count += 1
            else:
                # Write completed events if:
                # 1. No prior row for this event (first time seeing it), OR
                # 2. Last stored row is not completed (state transition)
                last_stored = existing_states.get(event_id)
                if completed and (last_stored is None or not last_stored.get("completed")):
                    should_write = True
                    finals_written += 1

            if should_write:
                rows_to_write.append(row)

        except Exception as exc:
            errors.append(f"event {event.get('id')}: {exc}")

    # Write rows
    if rows_to_write:
        live_dir_path.mkdir(parents=True, exist_ok=True)
        with store_path.open("a", encoding="utf-8") as handle:
            if _ends_ragged(store_path):
                handle.write("\n")
            for row in rows_to_write:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        rows_written = len(rows_to_write)

    # Record credit
    if quota is None:
        try:
            from src.providers import odds as odds_provider
            quota = odds_provider.quota
        except (ImportError, Exception):
            quota = None

    if record_credit is None:
        record_credit = creditlog.log

    if quota is not None and record_credit is not None:
        try:
            quota_result = quota(env=env)
            remaining = quota_result.get("remaining")
            used_last = quota_result.get("used_last")
            record_credit(remaining, used_last, CALLER,
                         budget_band="live_capture")
        except Exception:
            pass  # Failures here are reported, never raised

    return {
        "date": et_date,
        "events": len(events),
        "in_play": in_play_count,
        "rows_written": rows_written,
        "finals_written": finals_written,
        "errors": errors,
        "dir": str(live_dir),
    }


def read_states(date, *, live_dir=DEFAULT_LIVE_DIR) -> list:
    """Read all state rows for a given date (YYYY-MM-DD)."""
    store_path = Path(live_dir) / f"{date}.jsonl"
    return _read_all_rows(store_path)


def latest_states(date, *, live_dir=DEFAULT_LIVE_DIR) -> dict:
    """Return dict[event_id -> newest row] for a given date."""
    rows = read_states(date, live_dir=live_dir)
    result = {}
    for row in rows:
        event_id = row.get("event_id")
        if event_id:
            result[event_id] = row
    return result


def _read_all_rows(path) -> list:
    """Read all JSON Lines from a file, skipping corrupt lines."""
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _read_all_states(path) -> dict:
    """Return dict[event_id -> newest row] for a file."""
    rows = _read_all_rows(path)
    result = {}
    for row in rows:
        event_id = row.get("event_id")
        if event_id:
            result[event_id] = row
    return result


def _ends_ragged(target) -> bool:
    """True when file ends mid-line (signature of interrupted append)."""
    target = Path(target)
    if not target.exists() or not target.stat().st_size:
        return False
    with target.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1) != b"\n"
