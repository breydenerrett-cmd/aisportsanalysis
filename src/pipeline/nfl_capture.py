"""NFL pre-game featured-board capture cadence.

WHY THIS EXISTS
---------------
The featured call (h2h, spreads, totals in one region = 3 credits) returns EVERY NFL
event, so a capture is taken once whenever any game reaches a phase, and every game
whose phase was due is then marked done. This ensures we capture prices at key moments
(72h before, 24h before, 6h before, 2h before, 30m before kickoff) without redundant
API calls or missed windows.

PHASES AND STRATEGY
-------------------
PHASES = (("t72h", 72*60), ("t24h", 24*60), ("t6h", 6*60), ("t2h", 2*60), ("t30m", 30))

A phase becomes "due" when: now >= start_utc - phase_minutes.

A capture is taken once whenever ANY game reaches a due phase. Because the featured
call returns every game, marking all due phases done in a single capture eliminates
redundant requests.

Games that have already kicked off (start_utc <= now) are never due for any phase,
ensuring we do not make featured calls for completed games.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.paths import processed_path
from src.pipeline import snapshots
from src.providers import nfl as nfl_provider
from src.capture import budget as budget_module

LOG = logging.getLogger(__name__)

# Phase definitions: (name, minutes_before_kickoff)
PHASES = (
    ("t72h", 72 * 60),
    ("t24h", 24 * 60),
    ("t6h", 6 * 60),
    ("t2h", 2 * 60),
    ("t30m", 30),
)

FAMILY = "featured"
CREDITS_PER_CAPTURE = 3
DEFAULT_DONE_PATH = processed_path("nfl_capture_done.jsonl")


def _eastern():
    """NFL's official timezone, with a fallback for tzdata-less containers."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact, not a bug
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def _now(now) -> datetime:
    """Resolve the clock argument to a timezone-aware UTC datetime."""
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(
            "the clock must return a timezone-aware datetime; "
            "a naive observation time cannot be used"
        )
    return moment


def _utc_iso(moment: datetime) -> str:
    """Format a datetime as ISO 8601 UTC string ending in Z."""
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO 8601 string to a timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _et_today_date_strs(now: datetime, count: int = 4) -> list[str]:
    """Generate `count` ET date strings starting from ET today.

    Args:
        now: Current UTC datetime.
        count: Number of days to generate (default 4).

    Returns:
        List of date strings in "YYYY-MM-DD" format (ET local date).
    """
    # Convert to Eastern time
    et_now = now.astimezone(_EASTERN)
    dates = []
    for i in range(count):
        date = (et_now + timedelta(days=i)).date()
        dates.append(date.isoformat())
    return dates


def load_done(path: str | Path) -> set:
    """Load the done set from a file.

    Args:
        path: Path to the done file (JSONL format).

    Returns:
        Set of (game_id, phase) tuples that have been marked done.
    """
    target = Path(path)
    if not target.exists():
        return set()

    done = set()
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            game_id = row.get("game_id")
            phase = row.get("phase")
            if game_id and phase:
                done.add((game_id, phase))
        except json.JSONDecodeError:
            LOG.warning(
                "nfl_capture: %s:%s is not valid JSON (likely an "
                "interrupted append); skipped",
                target,
                number,
            )
    return done


def mark_done(path: str | Path, pairs: list[tuple[str, str]], now: datetime) -> None:
    """Mark (game_id, phase) pairs as done.

    Args:
        path: Path to the done file.
        pairs: List of (game_id, phase) tuples to mark done.
        now: Current UTC datetime for observed_utc field.
    """
    if not pairs:
        return

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    observed_utc = _utc_iso(now)
    with target.open("a", encoding="utf-8") as handle:
        if snapshots._ends_ragged(target):
            handle.write("\n")
        for game_id, phase in pairs:
            row = {
                "game_id": game_id,
                "phase": phase,
                "observed_utc": observed_utc,
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def due_phases(
    games: list[dict], done: set, now: datetime
) -> list[tuple[str, str]]:
    """Find all (game_id, phase) pairs that are due.

    A phase is due when:
    - The game's start_utc is in the future (now < start_utc)
    - The phase window has opened (now >= start_utc - phase_minutes)
    - The (game_id, phase) pair is not in the done set

    Args:
        games: List of game dicts with 'game_id' and 'start_utc' fields.
        done: Set of (game_id, phase) tuples already done.
        now: Current UTC datetime.

    Returns:
        List of (game_id, phase) tuples that are due.
    """
    due = []
    for game in games:
        game_id = game.get("game_id")
        start_utc_str = game.get("start_utc")

        if not game_id or not start_utc_str:
            continue

        start_utc = _parse_iso(start_utc_str)
        if start_utc is None:
            continue

        # Skip games that have already kicked off or are currently playing
        if now >= start_utc:
            continue

        # Check each phase
        for phase_name, phase_minutes in PHASES:
            if (game_id, phase_name) in done:
                continue

            # Phase is due if the current time has reached the window
            phase_cutoff = start_utc - timedelta(minutes=phase_minutes)
            if now >= phase_cutoff:
                due.append((game_id, phase_name))

    return due


def run(
    *,
    now: Optional[datetime] = None,
    games: Optional[list[dict]] = None,
    capture: Optional[callable] = None,
    spend_guard: Optional[callable] = None,
    done_path: str | Path = DEFAULT_DONE_PATH,
    env: Optional[dict] = None,
) -> dict:
    """Run one NFL capture cadence tick.

    Args:
        now: Current UTC datetime (defaults to now).
        games: List of games with 'game_id' and 'start_utc' fields.
               Defaults to lazy fetch from NFL schedule for next 4 ET days.
        capture: Callable that takes env and sport kwargs and returns a summary dict.
                 Defaults to src.pipeline.snapshots.capture.
        spend_guard: Callable that takes (family, credits, now) and returns a Decision.
                     Defaults to src.capture.budget.can_spend.
        done_path: Path to the done file.
        env: Environment dict for the odds provider.

    Returns:
        Dict with keys:
            - due: List of (game_id, phase) tuples that were due
            - captured: Boolean, whether a capture was made
            - credits: Integer, credits used (0 if not captured)
            - reason: String, reason if not captured
            - summary: Dict, the summary from the capture call (if made)
    """
    clock_now = _now(now)
    done = load_done(done_path)

    # Default games: lazy fetch from NFL schedule
    if games is None:
        try:
            date_strs = _et_today_date_strs(clock_now, count=4)
            all_games = []
            for date_str in date_strs:
                try:
                    day_games = nfl_provider.schedule_for_date(date_str)
                    # Convert to SportSpec shape
                    all_games.extend(
                        {
                            "game_id": g["game_id"],
                            "away": g["away_team"],
                            "home": g["home_team"],
                            "start_utc": g["start_utc"],
                        }
                        for g in day_games
                    )
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("nfl_capture: failed to fetch schedule for %s: %s", date_str, exc)
            games = all_games
        except Exception as exc:  # noqa: BLE001
            return {
                "due": [],
                "captured": False,
                "reason": f"failed to load game schedule: {exc}",
                "credits": 0,
            }

    # Check which phases are due
    due_list = due_phases(games, done, clock_now)

    if not due_list:
        return {
            "due": [],
            "captured": False,
            "reason": "no phase due",
            "credits": 0,
        }

    # Default capture function
    if capture is None:
        capture = snapshots.capture

    # Default spend guard
    if spend_guard is None:
        spend_guard = budget_module.can_spend

    # Check budget
    decision = spend_guard(FAMILY, CREDITS_PER_CAPTURE, now=clock_now)
    if not decision.allowed:
        return {
            "due": due_list,
            "captured": False,
            "reason": decision.reason,
            "credits": 0,
        }

    # Make the capture
    summary = capture(env=env, sport="nfl")

    # An unconfigured provider is not a capture. snapshots.capture reports
    # it with configured=False and no "error" key, and treating that as a
    # success would mark every due phase done with nothing written -- the
    # window would be spent without a price in it.
    if summary.get("configured") is False:
        return {
            "due": due_list,
            "captured": False,
            "reason": f"odds provider not configured: {summary.get('message')}",
            "credits": 0,
            "summary": summary,
        }

    # Check if capture had an error
    if summary.get("error"):
        return {
            "due": due_list,
            "captured": False,
            "reason": f"capture error: {summary['error']}",
            "credits": CREDITS_PER_CAPTURE,
            "summary": summary,
        }

    # Mark all due phases as done
    mark_done(done_path, due_list, clock_now)

    return {
        "due": due_list,
        "captured": True,
        "credits": CREDITS_PER_CAPTURE,
        "summary": summary,
    }
