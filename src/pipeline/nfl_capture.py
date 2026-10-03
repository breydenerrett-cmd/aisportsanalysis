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

from src.data.eastern import EASTERN_FALLBACK
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

# THE GAME-DAY WINDOW (added 2026-10-01).
#
# The five phases alone are not enough for the NFL card. It judges a price
# only against a board no more than an hour old
# (src/analysis/nfl_value.FRESH_BOARD_SECONDS), and it is rebuilt on every
# capture slot, so with phase captures only it can look at a slate for five
# separate hours and is blind in between.
#
# Nobody saw this, because until 2026-10-01 the done file was git-ignored:
# every runner started from an empty one, found every phase due again and
# bought the board on every slot, about 75 times a day at 3 credits, on
# days with no game as well. That accident kept the card's board fresh. The
# done file is now committed, the phases work as written, and the freshness
# the card relied on has to be bought on purpose and only when it is used:
# inside the six hours before a kickoff, the board is refreshed whenever the
# last capture is 25 minutes old. Slots run about 13 minutes apart, so that
# is every second slot and the board the card sees is never older than
# about 40 minutes. Outside that window the phases stand alone.
GAMEDAY_WINDOW_MINUTES = 6 * 60
GAMEDAY_REFRESH_MINUTES = 25
REFRESH_MARK = ("_gameday_refresh", "refresh")


def _eastern():
    """NFL's official timezone, with a fallback for machines without a tz database.

    The fallback is `src.data.eastern.EASTERN_FALLBACK`, the US daylight rules
    written out; until 2026-10-03 it was a fixed -04:00, an hour off from the
    first Sunday of November to the end of the season.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact, not a bug
        return EASTERN_FALLBACK


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


def last_capture_utc(path: str | Path) -> Optional[datetime]:
    """When the board was last bought, by any phase or refresh: the newest
    `observed_utc` in the done file. None when the file has no datable row."""
    target = Path(path)
    if not target.exists():
        return None
    newest = None
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            stamp = _parse_iso(json.loads(line).get("observed_utc"))
        except (json.JSONDecodeError, AttributeError):
            continue
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
    return newest


def gameday_refresh_due(games: list[dict], now: datetime,
                        last_capture: Optional[datetime]) -> bool:
    """True when some game kicks off within `GAMEDAY_WINDOW_MINUTES` (and has
    not kicked off) and the last capture is at least
    `GAMEDAY_REFRESH_MINUTES` old or unknown. See THE GAME-DAY WINDOW."""
    window = timedelta(minutes=GAMEDAY_WINDOW_MINUTES)
    in_window = False
    for game in games:
        start_utc = _parse_iso(game.get("start_utc") or "")
        if start_utc is not None and timedelta(0) < start_utc - now <= window:
            in_window = True
            break
    if not in_window:
        return False
    if last_capture is None:
        return True
    return now - last_capture >= timedelta(minutes=GAMEDAY_REFRESH_MINUTES)


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

    refresh = False
    if not due_list:
        refresh = gameday_refresh_due(games, clock_now, last_capture_utc(done_path))
        if not refresh:
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

    # Mark all due phases as done. A game-day refresh marks only itself: its
    # row carries the time `last_capture_utc` reads on the next slot.
    mark_done(done_path, due_list or [REFRESH_MARK], clock_now)

    result = {
        "due": due_list,
        "captured": True,
        "credits": CREDITS_PER_CAPTURE,
        "summary": summary,
    }
    if refresh:
        result["refresh"] = True
        result["reason"] = "game-day refresh (a kickoff is within 6 hours)"
    return result
