"""NFL schedule, injuries and team statistics from nflverse release CSVs.

WHY THIS EXISTS
---------------
The nflverse project maintains comprehensive NFL data in public CSV format, including
schedules with historical and future games, injury reports by week and team, and
aggregated team statistics by week. This module provides a lightweight, cacheable
interface to those feeds for schedule queries, injury lookups, and team performance
analysis across game weeks.

Design choice: fetch-on-demand over cached downloads, to avoid stale data in long-running
processes and to keep the fetch logic testable by patching a single seam (_get_text).
"""

from __future__ import annotations

import csv
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

ATTRIBUTION = "Schedule, injury and team statistics: nflverse (github.com/nflverse/nflverse-data), CC BY 4.0."

DEFAULT_TIMEOUT = 30
USER_AGENT = "linehound-nfl/1.0"

SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
INJURIES_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
TEAM_STATS_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv"


class NFLError(RuntimeError):
    """Raised when NFL data cannot be fetched or parsed."""


def _eastern():
    """NFL's official timezone, with a fallback for tzdata-less containers.

    NFL games fall entirely within daylight time (March-December), so a fixed
    -04:00 offset handles all games correctly. This matches the fallback
    in src/pipeline/snapshots.py.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact, not a bug
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def _get_text(url, timeout=DEFAULT_TIMEOUT) -> str:
    """Fetch and decode a URL as UTF-8 text.

    The single network seam for testing: patch this function to return fixture
    data without making real requests.

    Args:
        url: HTTP(S) URL to fetch.
        timeout: Seconds to wait before raising NFLError.

    Returns:
        Decoded UTF-8 text response body.

    Raises:
        NFLError: On network, decode, or HTTP errors (URL not included in message).
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError, UnicodeDecodeError) as e:
        raise NFLError(f"Failed to fetch NFL data: {e}") from e


def _parse_csv(text) -> list[dict]:
    """Parse CSV text via csv.DictReader.

    Args:
        text: CSV text with header row.

    Returns:
        List of dicts, one per data row.
    """
    rows = []
    for row_dict in csv.DictReader(text.splitlines()):
        rows.append(row_dict)
    return rows


def current_season(now=None) -> int:
    """The NFL season year.

    The NFL season spans calendar years and is named after the year it STARTS.
    A game in January 2027 belongs to the 2026 season. Games in March onward
    belong to the year given (e.g., March 2026 game is in the 2026 season).

    Args:
        now: datetime object (naive is treated as local). Defaults to now.

    Returns:
        Season year (e.g., 2026).
    """
    if now is None:
        now = datetime.now()

    # If month >= 3 (March onward), season is the current year
    # If month < 3 (Jan-Feb), season is the previous year
    if now.month >= 3:
        return now.year
    return now.year - 1


def start_utc(gameday, gametime) -> Optional[str]:
    """Convert NFL gameday and gametime (Eastern) to ISO UTC string.

    Args:
        gameday: Date string in format "YYYY-MM-DD".
        gametime: Time string in format "HH:MM" Eastern, or empty string.

    Returns:
        ISO 8601 UTC string ending in "Z", e.g., "2026-09-18T00:15:00Z".
        None if gametime is empty/falsy.

    Raises:
        ValueError: If gameday or gametime format is invalid.
    """
    if not gametime or not gametime.strip():
        return None

    gameday = gameday.strip()
    gametime = gametime.strip()

    # Parse gameday as date
    game_date = datetime.strptime(gameday, "%Y-%m-%d").date()

    # Parse gametime as time
    game_time = datetime.strptime(gametime, "%H:%M").time()

    # Combine into naive Eastern datetime
    eastern_dt = datetime.combine(game_date, game_time)

    # Localize to Eastern and convert to UTC
    localized = eastern_dt.replace(tzinfo=_EASTERN)
    utc_dt = localized.astimezone(timezone.utc)

    # Format without timezone offset, ending in Z
    iso_str = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_str


def normalize_game(row) -> dict:
    """Normalize a raw game row from the schedule CSV.

    Maps CSV fields to a standard shape and converts types. Handles optional fields
    like moneyline and spread gracefully.

    Args:
        row: Dict from csv.DictReader, keyed by CSV column names.

    Returns:
        Dict with keys:
            game_id, season (int), week (int), game_type, gameday, gametime,
            start_utc, away_team, home_team, away_score (int or None),
            home_score (int or None), completed (bool), stadium, roof, surface,
            away_moneyline, home_moneyline, spread_line, total_line (float or None),
            neutral_site (bool).

    Raises:
        ValueError: If required fields are missing or unparseable.
    """
    # Determine neutral_site from location column
    neutral_site = False
    if "location" in row and row["location"].strip().lower() == "neutral":
        neutral_site = True

    # Parse scores: None if absent or empty
    away_score = None
    home_score = None
    if row.get("away_score", "").strip():
        try:
            away_score = int(row["away_score"])
        except ValueError:
            pass
    if row.get("home_score", "").strip():
        try:
            home_score = int(row["home_score"])
        except ValueError:
            pass

    completed = away_score is not None and home_score is not None

    # Compute start_utc from gameday and gametime
    computed_start_utc = start_utc(row["gameday"], row.get("gametime", ""))

    # Parse float fields that might be None/empty
    def parse_float(val):
        if not val or not str(val).strip():
            return None
        try:
            return float(val)
        except ValueError:
            return None

    return {
        "game_id": row["game_id"],
        "season": int(row["season"]),
        "week": int(row["week"]),
        "game_type": row["game_type"],
        "gameday": row["gameday"],
        "gametime": row.get("gametime", ""),
        "start_utc": computed_start_utc,
        "away_team": row["away_team"],
        "home_team": row["home_team"],
        "away_score": away_score,
        "home_score": home_score,
        "completed": completed,
        "stadium": row.get("stadium", ""),
        "roof": row.get("roof", ""),
        "surface": row.get("surface", ""),
        "away_moneyline": parse_float(row.get("away_moneyline", "")),
        "home_moneyline": parse_float(row.get("home_moneyline", "")),
        "spread_line": parse_float(row.get("spread_line", "")),
        "total_line": parse_float(row.get("total_line", "")),
        "neutral_site": neutral_site,
    }


def fetch_schedule(season=None, week=None, *, timeout=DEFAULT_TIMEOUT) -> list[dict]:
    """Fetch and normalize NFL schedule from nflverse.

    Args:
        season: Season year to filter by (e.g., 2026). Defaults to current_season().
        week: Optional week number to further filter by.
        timeout: Request timeout in seconds.

    Returns:
        List of normalized game dicts, filtered by season and optionally week.

    Raises:
        NFLError: If the schedule cannot be fetched or parsed.
    """
    if season is None:
        season = current_season()

    try:
        text = _get_text(SCHEDULE_URL, timeout=timeout)
        raw_rows = _parse_csv(text)
    except NFLError:
        raise
    except Exception as e:
        raise NFLError(f"Failed to parse schedule: {e}") from e

    normalized = []
    for row in raw_rows:
        try:
            game = normalize_game(row)
            if game["season"] == season:
                if week is None or game["week"] == week:
                    normalized.append(game)
        except (KeyError, ValueError) as e:
            # Skip malformed rows
            continue

    return normalized


def schedule_for_date(date_str, *, season=None, timeout=DEFAULT_TIMEOUT) -> list[dict]:
    """Fetch games scheduled for a specific date.

    Args:
        date_str: Date in format "YYYY-MM-DD".
        season: Season to fetch (defaults to current_season()). Primarily for efficiency.
        timeout: Request timeout in seconds.

    Returns:
        List of games where gameday == date_str.

    Raises:
        NFLError: If schedule cannot be fetched or parsed.
    """
    if season is None:
        season = current_season()

    games = fetch_schedule(season=season, timeout=timeout)
    return [g for g in games if g["gameday"] == date_str]


def schedule_for_week(season, week, *, timeout=DEFAULT_TIMEOUT) -> list[dict]:
    """Fetch games for a specific season and week.

    Args:
        season: Season year (required).
        week: Week number.
        timeout: Request timeout in seconds.

    Returns:
        List of games where season and week match.

    Raises:
        NFLError: If schedule cannot be fetched or parsed.
    """
    return fetch_schedule(season=season, week=week, timeout=timeout)


def fetch_injuries(season, *, timeout=DEFAULT_TIMEOUT) -> list[dict]:
    """Fetch injury reports for a season.

    Args:
        season: Season year.
        timeout: Request timeout in seconds.

    Returns:
        List of dicts with keys: season, week (int), team, gsis_id, full_name,
        position, report_status, practice_status, and date_modified.

    Raises:
        NFLError: If injury data cannot be fetched or parsed.
    """
    url = INJURIES_URL_TEMPLATE.format(season=season)

    try:
        text = _get_text(url, timeout=timeout)
        raw_rows = _parse_csv(text)
    except NFLError:
        raise
    except Exception as e:
        raise NFLError(f"Failed to parse injuries: {e}") from e

    normalized = []
    for row in raw_rows:
        try:
            normalized.append(
                {
                    "season": int(row["season"]),
                    "week": int(row["week"]),
                    "team": row["team"],
                    "gsis_id": row["gsis_id"],
                    "full_name": row["full_name"],
                    "position": row["position"],
                    "report_status": row.get("report_status", ""),
                    "practice_status": row.get("practice_status", ""),
                    "date_modified": row.get("date_modified", ""),
                }
            )
        except (KeyError, ValueError):
            # Skip malformed rows
            continue

    return normalized


def fetch_team_stats(season, *, timeout=DEFAULT_TIMEOUT) -> list[dict]:
    """Fetch team statistics by week for a season.

    All numeric columns are converted to float where they parse as numbers.
    Non-numeric columns are left as strings.

    Columns include EPA measures:
    - passing_epa: Expected points added by passing
    - rushing_epa: Expected points added by rushing
    - receiving_epa: Expected points added by receiving

    Args:
        season: Season year.
        timeout: Request timeout in seconds.

    Returns:
        List of dicts with keys: season, week (int), team, opponent_team,
        and all other columns (numeric as float, text as string).

    Raises:
        NFLError: If team stats cannot be fetched or parsed.
    """
    url = TEAM_STATS_URL_TEMPLATE.format(season=season)

    try:
        text = _get_text(url, timeout=timeout)
        raw_rows = _parse_csv(text)
    except NFLError:
        raise
    except Exception as e:
        raise NFLError(f"Failed to parse team stats: {e}") from e

    normalized = []
    for row in raw_rows:
        try:
            normalized_row = {}
            for key, val in row.items():
                # Always include the key
                if key in ("season", "week", "team", "opponent_team"):
                    # Special handling for typed fields
                    if key == "season":
                        normalized_row[key] = int(val)
                    elif key == "week":
                        normalized_row[key] = int(val)
                    else:
                        normalized_row[key] = val
                else:
                    # Try to parse as float, fall back to string
                    if val and str(val).strip():
                        try:
                            normalized_row[key] = float(val)
                        except ValueError:
                            normalized_row[key] = val
                    else:
                        normalized_row[key] = val

            normalized.append(normalized_row)
        except (KeyError, ValueError):
            # Skip malformed rows
            continue

    return normalized


def registry_schedule_fn(date_str) -> list[dict]:
    """Schedule adapter for SportSpec registry.

    Maps fetch result to the shape {"game_id", "away", "home", "start_utc"}.

    Args:
        date_str: Date in format "YYYY-MM-DD".

    Returns:
        List of games on that date, with keys:
            game_id, away (away_team), home (home_team), start_utc.

    Raises:
        NFLError: If schedule cannot be fetched.
    """
    games = schedule_for_date(date_str)
    return [
        {
            "game_id": g["game_id"],
            "away": g["away_team"],
            "home": g["home_team"],
            "start_utc": g["start_utc"],
        }
        for g in games
    ]
