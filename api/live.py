"""GET /live: Live game states and research candidates for active games.

Internal testing surface. All live selections are research candidates, never
picks. A game state row carries the observed_utc, score, and inning/quarter,
never a recommendation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException

from src.appstate import live_ledger
from src.pipeline import livefeed_mlb, livefeed_nfl, live_remote

router = APIRouter()

# Module-level so tests can patch them.
_get_livefeed_mlb_latest_states: Callable = livefeed_mlb.latest_states
_get_livefeed_nfl_latest_states: Callable = livefeed_nfl.latest_states
_get_live_ledger_candidates: Callable = live_ledger.candidates
_remote_state_rows: Callable = live_remote.live_state_rows
_remote_candidate_rows: Callable = live_remote.live_candidate_rows


def _eastern():
    """America/New_York when tz data is installed, else a fixed -4 offset.

    THE BUG THIS REPLACES (2026-09-15): the fallback branch used to do
    `from datetime import timedelta, timezone` INSIDE the except clause,
    which made `timezone` a local name for the whole function. On a Windows
    box without tz data the except ran and everything worked; in the
    container, where tz data exists, the try succeeded, the local was never
    bound, and every /live request died with UnboundLocalError -- a 500 on
    staging that no local run could reproduce.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- missing tz data is the only case
        return timezone(timedelta(hours=-4))


def _et_date_today(now: Optional[datetime] = None) -> str:
    """ET date (YYYY-MM-DD) for today."""
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(_eastern()).strftime("%Y-%m-%d")


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
                "status": "live" | "stale" | "idle",
                "source": "local" | "remote" | "merged"
            },
            "games": [
                {
                    "home_team": str,
                    "away_team": str,
                    "score": str (e.g. "Yankees 3, Red Sox 2, top of the 6th"),
                    "status": str,
                    "observed_utc": ISO string,
                    "source": "local" | "remote" | "merged"
                }
            ],
            "candidates": [
                {
                    "rule_id": str,
                    "bet": str,
                    "price": int,
                    "observed_utc": ISO string,
                    "source": "local" | "remote" | "merged",
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

    # Fetch newest game states from local
    if sport == "mlb":
        states_by_game = _get_livefeed_mlb_latest_states(today)
        game_key = "game_pk"
    else:  # nfl
        states_by_game = _get_livefeed_nfl_latest_states(today)
        game_key = "event_id"

    # Mark all local rows with source
    for row in states_by_game.values():
        row["source"] = "local"

    # Merge with remote states if enabled
    if live_remote.enabled():
        try:
            remote_rows = _remote_state_rows(sport, today)
            for remote_row in remote_rows:
                game_id = remote_row.get(game_key)
                if game_id is None:
                    continue

                remote_row["source"] = "remote"

                if game_id in states_by_game:
                    # Both exist: take newer by observed_utc
                    local_obs = states_by_game[game_id].get("observed_utc")
                    remote_obs = remote_row.get("observed_utc")
                    if remote_obs and (not local_obs or remote_obs > local_obs):
                        # Remote is newer
                        states_by_game[game_id] = remote_row
                        states_by_game[game_id]["source"] = "merged"
                    else:
                        # Local is newer (or equally old); mark as merged since it was compared
                        states_by_game[game_id]["source"] = "merged"
                else:
                    # Only in remote
                    states_by_game[game_id] = remote_row
        except Exception:
            # Remote failure never fails the request
            pass

    # Extract newest observed_utc across all games
    newest_observed_utc = None
    source_for_newest = None
    for row in states_by_game.values():
        obs_utc = row.get("observed_utc")
        if obs_utc:
            if newest_observed_utc is None or obs_utc > newest_observed_utc:
                newest_observed_utc = obs_utc
                source_for_newest = row.get("source", "local")

    # Determine poller status
    status = _poller_status(newest_observed_utc, sport)

    # Reduce game rows to plain fields, keeping source
    games = []
    for row in states_by_game.values():
        reduced = _reduce_game_row(row, sport)
        reduced["source"] = row.get("source", "local")
        games.append(reduced)

    # Fetch candidates for today from local
    candidates_list = _get_live_ledger_candidates(date=today)
    # Filter to this sport
    local_candidates = [c for c in candidates_list if c.get("sport") == sport]
    for c in local_candidates:
        c["source"] = "local"

    # Build index of local candidates by (rule_id, sport, game_id)
    candidates_by_key = {}
    for c in local_candidates:
        key = (c.get("rule_id"), c.get("sport"), c.get("game_id"))
        candidates_by_key[key] = c

    # Merge with remote candidates if enabled
    if live_remote.enabled():
        try:
            remote_candidates = _remote_candidate_rows()
            for remote_c in remote_candidates:
                if remote_c.get("sport") != sport:
                    continue

                key = (remote_c.get("rule_id"), remote_c.get("sport"), remote_c.get("game_id"))
                remote_c["source"] = "remote"

                if key in candidates_by_key:
                    # Both exist: take newer by observed_utc
                    local_obs = candidates_by_key[key].get("observed_utc")
                    remote_obs = remote_c.get("observed_utc")
                    if remote_obs and (not local_obs or remote_obs > local_obs):
                        candidates_by_key[key] = remote_c
                        candidates_by_key[key]["source"] = "merged"
                    else:
                        # Local is newer (or equally old); mark as merged since it was compared
                        candidates_by_key[key]["source"] = "merged"
                else:
                    # Only in remote
                    candidates_by_key[key] = remote_c
        except Exception:
            # Remote failure never fails the request
            pass

    # Convert to list, filter to today, and sort newest first
    candidates_list = list(candidates_by_key.values())
    today_candidates = []
    for c in candidates_list:
        # Get the date from the candidate, or compute it from a timestamp
        c_date = c.get("date")
        if not c_date:
            timestamp_str = c.get("recorded_utc") or c.get("observed_utc")
            if timestamp_str:
                try:
                    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    c_date = dt.astimezone(_eastern()).strftime("%Y-%m-%d")
                except (ValueError, TypeError, AttributeError):
                    c_date = today
            else:
                c_date = today
        if c_date == today:
            today_candidates.append(c)

    # `or ""`, not a .get default: a row whose observed_utc is present but
    # null would otherwise compare None with a string and 500 the page.
    today_candidates.sort(key=lambda c: c.get("observed_utc") or "", reverse=True)

    return {
        "sport": sport,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "Live analysis is in internal testing. No alerts are sent.",
        "poller": {
            "last_observed_utc": newest_observed_utc,
            "fresh": status == "live",
            "status": status,
            "source": source_for_newest or "local",
        },
        "games": games,
        "candidates": today_candidates,
    }
