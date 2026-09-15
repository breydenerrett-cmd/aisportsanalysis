"""Free MLB live game-state poller.

WHY THIS EXISTS
---------------
Live betting markets close as games progress, and a live-odds capture needs
to know the game's state at each observation time. The MLB Stats API's
linescore endpoint is free, keyless, and updates in real time for in-play games.

This module polls for games in "Live" state, fetches their linescore, and appends
one state row per observation. For games that reach "Final", it records exactly
one final row and stops -- settlement needs the official score, and the poller
must never append a second final row.

WHY THIS IS INJECTABLE
----------------------
Every fetch is injectable (fetch_schedule, fetch_linescore) and the clock is
injectable, so tests run without the network and with deterministic time.
Network failures are recorded and do not abort the poll.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.paths import data_path
from src.providers import mlb

LOG = logging.getLogger(__name__)

DEFAULT_LIVE_DIR = data_path("live", "mlb")


def _eastern():
    """MLB's official timezone; a fixed -04:00 when no zone database is installed."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def poll(game_date=None, *, live_dir=DEFAULT_LIVE_DIR,
         fetch_schedule=mlb.fetch_schedule,
         fetch_linescore=mlb.fetch_linescore,
         clock=None, timeout=20) -> dict:
    """Poll MLB games for live state, appending one row per observation.

    Fetches the schedule for `game_date` (defaults to ET date of clock()),
    and for every game in "Live" state, fetches and records its linescore.
    For a game whose state is "Final" and whose last stored row is not Final,
    appends one final row and stops.

    Never raises on a network error: records it in report["errors"] and continues.

    Returns a summary: {"date", "live_games", "rows_written", "finals_written",
    "errors": [...], "dir"}.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    observed_utc = _utc_iso(clock())
    iso_date = _to_iso_date(game_date, clock)

    directory = Path(live_dir)
    directory.mkdir(parents=True, exist_ok=True)

    report = {
        "date": iso_date,
        "dir": str(directory),
        "live_games": 0,
        "rows_written": 0,
        "finals_written": 0,
        "errors": [],
    }

    # Fetch the schedule.
    try:
        games = fetch_schedule(iso_date, timeout=timeout)
    except Exception as exc:
        LOG.warning("livefeed_mlb: schedule fetch failed: %s", exc)
        report["errors"].append({"source": "schedule", "error": str(exc)})
        return report

    # Index the last stored row per game.
    last_rows = _last_rows(directory / f"{iso_date}.jsonl")

    # Process each game.
    for game in games or []:
        game_pk = game.get("gamePk")
        if game_pk is None:
            continue

        abstract_state = (game.get("status") or {}).get("abstractGameState")
        if abstract_state not in ("Live", "Final"):
            continue

        if abstract_state == "Live":
            report["live_games"] += 1
            # Fetch the linescore.
            try:
                linescore = fetch_linescore(game_pk, timeout=timeout)
            except Exception as exc:
                LOG.warning("livefeed_mlb: linescore fetch for game %s failed: %s",
                           game_pk, exc)
                report["errors"].append({
                    "source": "linescore",
                    "game_pk": game_pk,
                    "error": str(exc),
                })
                continue

            # Build the state row.
            row = _build_row(game, linescore, observed_utc)
            if row is not None:
                _append(directory / f"{iso_date}.jsonl", [row])
                report["rows_written"] += 1

        elif abstract_state == "Final":
            # Only write a final row if the last stored row is not already Final.
            last = last_rows.get(game_pk)
            if last is None or last.get("status") != "Final":
                row = _build_final_row(game, observed_utc)
                if row is not None:
                    _append(directory / f"{iso_date}.jsonl", [row])
                    report["finals_written"] += 1

    return report


def _build_row(game: dict, linescore: dict, observed_utc: str) -> dict | None:
    """Build a Live state row from a game and its linescore."""
    game_pk = game.get("gamePk")
    if game_pk is None:
        return None

    state_id = _state_id(game_pk, observed_utc)

    teams = game.get("teams") or {}
    away_team = teams.get("away") or {}
    home_team = teams.get("home") or {}

    away_name = (away_team.get("team") or {}).get("name")
    home_name = (home_team.get("team") or {}).get("name")

    away_probable_id = _pitcher_id(away_team)
    home_probable_id = _pitcher_id(home_team)

    linescore_data = linescore or {}
    current_inning = linescore_data.get("currentInning")
    inning_half = linescore_data.get("inningHalf")
    inning_state = linescore_data.get("inningState")
    outs = linescore_data.get("outs")
    balls = linescore_data.get("balls")
    strikes = linescore_data.get("strikes")

    offense = linescore_data.get("offense") or {}
    batter_id = (offense.get("batter") or {}).get("id")

    defense = linescore_data.get("defense") or {}
    pitcher_id = (defense.get("pitcher") or {}).get("id")

    # Runners on base.
    runners = {
        "first": (offense.get("first") or {}).get("id"),
        "second": (offense.get("second") or {}).get("id"),
        "third": (offense.get("third") or {}).get("id"),
    }

    home_stats = (linescore_data.get("teams") or {}).get("home") or {}
    away_stats = (linescore_data.get("teams") or {}).get("away") or {}

    return {
        "observed_utc": observed_utc,
        "state_id": state_id,
        "sport": "mlb",
        "game_pk": int(game_pk),
        "date": game.get("officialDate") or (game.get("gameDate") or "")[:10] or None,
        "status": "Live",
        "detailed_state": (game.get("status") or {}).get("detailedState"),
        "inning": current_inning,
        "half": inning_half.lower() if inning_half else None,
        "inning_state": inning_state,
        "outs": outs,
        "balls": balls,
        "strikes": strikes,
        "runners": runners,
        "batter_id": batter_id,
        "pitcher_id": pitcher_id,
        "home_team": home_name,
        "away_team": away_name,
        "home_runs": home_stats.get("runs"),
        "away_runs": away_stats.get("runs"),
        "home_hits": home_stats.get("hits"),
        "away_hits": away_stats.get("hits"),
        "home_probable_pitcher_id": home_probable_id,
        "away_probable_pitcher_id": away_probable_id,
    }


def _build_final_row(game: dict, observed_utc: str) -> dict | None:
    """Build a Final state row from a game."""
    game_pk = game.get("gamePk")
    if game_pk is None:
        return None

    state_id = _state_id(game_pk, observed_utc)

    teams = game.get("teams") or {}
    away_team = teams.get("away") or {}
    home_team = teams.get("home") or {}

    away_name = (away_team.get("team") or {}).get("name")
    home_name = (home_team.get("team") or {}).get("name")

    away_probable_id = _pitcher_id(away_team)
    home_probable_id = _pitcher_id(home_team)

    return {
        "observed_utc": observed_utc,
        "state_id": state_id,
        "sport": "mlb",
        "game_pk": int(game_pk),
        "date": game.get("officialDate") or (game.get("gameDate") or "")[:10] or None,
        "status": "Final",
        "detailed_state": (game.get("status") or {}).get("detailedState"),
        "inning": None,
        "half": None,
        "inning_state": None,
        "outs": None,
        "balls": None,
        "strikes": None,
        "runners": {"first": None, "second": None, "third": None},
        "batter_id": None,
        "pitcher_id": None,
        "home_team": home_name,
        "away_team": away_name,
        "home_runs": (home_team.get("score")),
        "away_runs": (away_team.get("score")),
        "home_hits": None,
        "away_hits": None,
        "home_probable_pitcher_id": home_probable_id,
        "away_probable_pitcher_id": away_probable_id,
    }


def _state_id(game_pk: int, observed_utc: str) -> str:
    """SHA1 hash of game_pk|observed_utc, first 16 hex chars."""
    text = f"{game_pk}|{observed_utc}"
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _pitcher_id(side: dict) -> int | None:
    """Extract pitcher id from a team's probable pitcher."""
    pitcher = side.get("probablePitcher") or {}
    pitcher_id = pitcher.get("id")
    return int(pitcher_id) if pitcher_id is not None else None


def read_states(date, *, live_dir=DEFAULT_LIVE_DIR) -> list[dict]:
    """Read all state rows for one date."""
    path = Path(live_dir) / f"{date}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("livefeed_mlb: %s:%s is not valid JSON; skipped",
                       path, len(rows) + 1)
    return rows


def latest_states(date, *, live_dir=DEFAULT_LIVE_DIR) -> dict:
    """Map game_pk to the newest state row for one date."""
    states = read_states(date, live_dir=live_dir)
    result = {}
    for row in states:
        game_pk = row.get("game_pk")
        if game_pk is not None:
            result[game_pk] = row
    return result


def is_final(row) -> bool:
    """True when a state row represents a final game."""
    return row.get("status") == "Final"


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _last_rows(path: Path) -> dict:
    """Map game_pk to the last row for each game in the file."""
    last = {}
    for line in _read_lines(path):
        try:
            row = json.loads(line)
            game_pk = row.get("game_pk")
            if game_pk is not None:
                last[game_pk] = row
        except json.JSONDecodeError:
            pass
    return last


def _read_lines(path: Path) -> list:
    """Every line in the file that exists."""
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _append(path: Path, rows: list) -> None:
    """Append rows, first newline-terminating any ragged end."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    ragged = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            ragged = handle.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as handle:
        if ragged:
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _utc_iso(moment: datetime) -> str:
    """ISO format UTC timestamp."""
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(
            "the clock must return a timezone-aware datetime")
    return moment.astimezone(timezone.utc).isoformat()


def _to_iso_date(value, clock=None) -> str:
    """Get the date in YYYY-MM-DD format, using ET as the official date."""
    if value is None:
        moment = clock() if clock is not None else datetime.now(timezone.utc)
        if not isinstance(moment, datetime) or moment.tzinfo is None:
            raise ValueError(
                "the clock must return a timezone-aware datetime")
        return moment.astimezone(_EASTERN).date().isoformat()
    if isinstance(value, str):
        return value
    return str(value)
