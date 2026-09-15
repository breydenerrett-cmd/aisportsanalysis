"""GET /live: Live game states and research candidates for active games.

Internal testing surface. All live selections are research candidates, never
picks. A game state row carries the observed_utc, score, and inning/quarter,
never a recommendation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException

from src.appstate import live_ledger
from src.pipeline import livefeed_mlb, livefeed_nfl

router = APIRouter()

# Module-level so tests can patch them.
_get_livefeed_mlb_latest_states: Callable = livefeed_mlb.latest_states
_get_livefeed_nfl_latest_states: Callable = livefeed_nfl.latest_states
_get_live_ledger_candidates: Callable = live_ledger.candidates


def _et_date_today() -> str:
    """ET date (YYYY-MM-DD) for today."""
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except Exception:
        from datetime import timedelta, timezone
        et = timezone(timedelta(hours=-4))

    dt = datetime.now(timezone.utc).astimezone(et)
    return dt.strftime("%Y-%m-%d")


def _age_seconds(observed_utc: Optional[str]) -> Optional[int]:
    """Age in seconds from observed_utc to now."""
    if not observed_utc:
        return None

    try:
        dt = datetime.fromisoformat(observed_utc.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - dt
        return int(age.total_seconds())
    except (ValueError, TypeError):
        return None


def _poller_status(newest_observed_utc: Optional[str],
                   sport: str) -> str:
    """Determine poller status from newest observed_utc.

    "live": under 3 minutes old (MLB) or 10 minutes old (NFL)
    "stale": older
    "idle": no rows
    """
    if not newest_observed_utc:
        return "idle"

    age = _age_seconds(newest_observed_utc)
    if age is None:
        return "idle"

    # Threshold in seconds
    threshold = 180 if sport == "mlb" else 600  # 3 min vs 10 min

    if age <= threshold:
        return "live"
    return "stale"


def _reduce_game_row(row: dict, sport: str) -> dict:
    """Reduce a state row to plain fields for the API response."""
    # Common fields across both sports
    reduced = {
        "home_team": row.get("home_team"),
        "away_team": row.get("away_team"),
        "observed_utc": row.get("observed_utc"),
        "status": row.get("status"),
    }

    # Sport-specific fields
    if sport == "mlb":
        # For MLB, inning/half are the key status fields
        inning = row.get("inning")
        half = row.get("half")
        if inning is not None:
            inning_display = f"{half or 'unknown'} of the {inning}"
            reduced["inning"] = inning_display
        reduced["score"] = f"{row.get('away_team', 'Away')} {row.get('away_runs', 0)}, " \
                          f"{row.get('home_team', 'Home')} {row.get('home_runs', 0)}"
    elif sport == "nfl":
        # For NFL, quarter is the key field, score is separate
        if row.get("completed"):
            reduced["score"] = f"{row.get('away_team', 'Away')} {row.get('away_score', 0)}, " \
                              f"{row.get('home_team', 'Home')} {row.get('home_score', 0)}"
        else:
            quarter = row.get("quarter")
            reduced["quarter"] = quarter
            reduced["score"] = f"{row.get('away_team', 'Away')} {row.get('away_score', 0)}, " \
                              f"{row.get('home_team', 'Home')} {row.get('home_score', 0)}"

    return reduced


@router.get("/live")
def get_live(sport: str = "mlb") -> dict:
    """Live game states and research candidates for today.

    Args:
        sport: "mlb" or "nfl" (default "mlb")

    Returns:
        {
            "sport": "mlb" | "nfl",
            "generated_utc": ISO string,
            "notice": "Live analysis is in internal testing...",
            "poller": {
                "last_observed_utc": ISO string or null,
                "fresh": bool,
                "status": "live" | "stale" | "idle"
            },
            "games": [
                {
                    "home_team": str,
                    "away_team": str,
                    "score": str (e.g. "Yankees 3, Red Sox 2, top of the 6th"),
                    "status": str,
                    "observed_utc": ISO string
                }
            ],
            "candidates": [
                {
                    "rule_id": str,
                    "bet": str,
                    "price": int,
                    "observed_utc": ISO string,
                    ... (other live_ledger candidate fields)
                }
            ]
        }
    """
    if sport not in ("mlb", "nfl"):
        raise HTTPException(
            status_code=400,
            detail=f"sport must be 'mlb' or 'nfl' (got {sport!r})")

    # Get today's ET date
    today = _et_date_today()

    # Fetch newest game states
    if sport == "mlb":
        states_by_game = _get_livefeed_mlb_latest_states(today)
    else:  # nfl
        states_by_game = _get_livefeed_nfl_latest_states(today)

    # Extract newest observed_utc across all games
    newest_observed_utc = None
    for row in states_by_game.values():
        obs_utc = row.get("observed_utc")
        if obs_utc:
            if newest_observed_utc is None or obs_utc > newest_observed_utc:
                newest_observed_utc = obs_utc

    # Determine poller status
    status = _poller_status(newest_observed_utc, sport)

    # Reduce game rows to plain fields
    games = [
        _reduce_game_row(row, sport)
        for row in states_by_game.values()
    ]

    # Fetch candidates for today (newest first)
    candidates_list = _get_live_ledger_candidates(date=today)
    # Filter to this sport and reverse to get newest first
    candidates_list = [c for c in candidates_list if c.get("sport") == sport]
    candidates_list.reverse()

    return {
        "sport": sport,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "Live analysis is in internal testing. No alerts are sent.",
        "poller": {
            "last_observed_utc": newest_observed_utc,
            "fresh": status == "live",
            "status": status,
        },
        "games": games,
        "candidates": candidates_list,
    }
