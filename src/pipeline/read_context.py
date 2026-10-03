"""The facts ABOUT our own inputs that the written game read needs.

WHY THIS EXISTS
---------------
`src.analysis.matchup_read` writes a plain-English read of one game from the
game payload alone. Two things it needs are not in the payload and cannot be
guessed from it:

  * how old each store behind the payload is. A team's "rest days" is the gap
    since the newest game in OUR results, so when our results stop ten days
    before first pitch it reads ten days of rest for every club. The read has
    to know the results end on a stated date to say so, and a pitcher log or a
    bullpen log that ends weeks early looks, in the payload, exactly like a
    club that did not play;
  * two league-level numbers the run arithmetic is scaled by, the league run
    rate and the park's run factor, both measured from the same results store
    the team rates come from.

Everything here is read from files the app already loads, nothing touches the
network, and every field is absent-safe: an unreadable store yields None for
that field and the read says so, it never substitutes a date.

THE STAT CACHE
--------------
The pitcher log and the bullpen log are megabytes each. Their newest date is
all this needs, so each file is scanned line by line for its date strings
(no JSON parse, nothing kept but the distinct dates) and the result is cached
on the file's size and modification time. A new capture changes the stat and
the next call rescans; a thousand page views in between cost one dict lookup.
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Optional

from src.pipeline import bullpen as bullpen_mod
from src.pipeline import parkfactors
from src.pipeline import pitchers as pitchers_mod

_DATE = re.compile(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})')

# path -> ((size, mtime_ns), sorted tuple of distinct ISO dates)
_scan_cache: dict = {}


def _log_dates(path) -> tuple:
    """Every distinct `"date"` value in a JSONL log, sorted. Cached on the
    file's stat. Empty when the file is missing or unreadable."""
    try:
        stat = os.stat(path)
    except OSError:
        return ()
    signature = (stat.st_size, stat.st_mtime_ns)
    cached = _scan_cache.get(str(path))
    if cached and cached[0] == signature:
        return cached[1]
    found = set()
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = _DATE.search(line)
                if match:
                    found.add(match.group(1))
    except OSError:
        return ()
    dates = tuple(sorted(found))
    _scan_cache[str(path)] = (signature, dates)
    return dates


def newest_before(dates, game_date: str) -> Optional[str]:
    """The newest ISO date strictly before `game_date`, or None."""
    older = [d for d in dates if d < str(game_date)]
    return max(older) if older else None


def _int(value) -> Optional[int]:
    return parkfactors._int(value)


def results_summary(store: Mapping, game_date: str) -> dict:
    """The newest scored game in the results store before `game_date`, and
    the league run rate over the same season's games before it."""
    cutoff = str(game_date)
    season = cutoff[:4]
    dates = set()
    runs = 0
    games = 0
    for row in (store or {}).values():
        date = str(row.get("date") or "")
        if not date or date >= cutoff:
            continue
        away, home = _int(row.get("away_score")), _int(row.get("home_score"))
        if away is None or home is None:
            continue
        dates.add(date)
        if date[:4] == season:
            runs += away + home
            games += 1
    through = max(dates) if dates else None
    league = round(runs / (2.0 * games), 4) if games else None
    return {"through": through, "games": games, "league_runs_per_game": league}


def build(store: Mapping, game_date: str, home_team: str, *,
          pitcher_log_path=None, bullpen_log_path=None) -> dict:
    """The `read_inputs` block that rides beside a game payload.

    Shape (every leaf may be None, and the read treats None as "unknown",
    never as "fresh"):

        results:        {through, games}
        league_runs_per_game: {value, games}
        park_factor:    {team, factor, raw_factor, home_games, away_games, thin}
        pitcher_logs:   {through}
        bullpen_log:    {through}
    """
    summary = results_summary(store, game_date)
    out = {
        "results": {"through": summary["through"], "games": summary["games"]},
        "league_runs_per_game": {"value": summary["league_runs_per_game"],
                                 "games": summary["games"]},
        "park_factor": None,
        "pitcher_logs": {"through": newest_before(
            _log_dates(pitcher_log_path or pitchers_mod.DEFAULT_LOG_STORE),
            game_date)},
        "bullpen_log": {"through": newest_before(
            _log_dates(bullpen_log_path or bullpen_mod.DEFAULT_LOG),
            game_date)},
    }
    try:
        factors = parkfactors.park_factors(store, game_date)
        row = factors.get(home_team)
        if isinstance(row, Mapping):
            out["park_factor"] = {
                "team": home_team,
                "factor": row.get("factor"),
                "raw_factor": row.get("raw_factor"),
                "home_games": row.get("home_games"),
                "away_games": row.get("away_games"),
                "thin": bool(row.get("thin")),
            }
    except Exception:  # noqa: BLE001 -- a park factor gap is a gap, never a 500
        out["park_factor"] = None
    return out
