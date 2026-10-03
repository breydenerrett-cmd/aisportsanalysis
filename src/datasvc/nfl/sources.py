"""nflverse release files: where they are, how to fetch them politely, how to read them.

Every parser here is a pure function over CSV text (or the rows `read_csv` makes of it) and
returns records in the shapes fixed by docs/datasvc/NFL_SCHEMA.md. Nothing here opens a
connection: `fetch_csv` takes the one `PoliteFetcher` the caller made, and tests hand it a
fake that serves saved text.

Reading rules that matter:

* CSV is read with `csv.reader` over `io.StringIO(text, newline="")`. The injuries files hold
  quoted fields with line breaks in them; `splitlines()` would cut those rows in two.
* A column is read by name. One that is absent is a missing value, not an error: the
  injuries files lost `date_modified` in 2025 and gained `season_type`.
* A blank, `NA` or `NaN` is null, never zero.
* A row that cannot be understood (no game id, a season that is not a number) is skipped and
  counted in the returned `info`, never guessed.
"""

from __future__ import annotations

import csv
import io
import math
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.datasvc.http import NotFound
from src.datasvc.nfl import timeutil
from src.datasvc.nfl.store import position_group

BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download"
LIVE_MAX_AGE_S = 3600          # a live file is re-fetched when the cached copy is older than this
LIVE_SEASONS_BACK = 1          # the current season and this many before it count as live

# A game is "final" only if its record was fetched at least this long after kickoff: no NFL
# game ends sooner, so a score seen earlier is a game in progress, not a result. A game with no
# score this long after kickoff is "no_result" (cancelled, postponed or not updated yet).
FINAL_MIN_AGE = timedelta(minutes=150)
NO_RESULT_AFTER = timedelta(hours=12)


GAMES_URL = f"{BASE_URL}/schedules/games.csv"
TEAM_STATS_TEMPLATE = BASE_URL + "/stats_team/stats_team_week_{season}.csv"
PLAYER_STATS_TEMPLATE = BASE_URL + "/stats_player/stats_player_week_{season}.csv"
INJURIES_TEMPLATE = BASE_URL + "/injuries/injuries_{season}.csv"


def games_url() -> str:
    return GAMES_URL


def team_stats_url(season: int) -> str:
    return TEAM_STATS_TEMPLATE.format(season=int(season))


def player_stats_url(season: int) -> str:
    return PLAYER_STATS_TEMPLATE.format(season=int(season))


def injuries_url(season: int) -> str:
    return INJURIES_TEMPLATE.format(season=int(season))


GAMES_SOURCE = "nflverse:games.csv"


def team_stats_source(season: int) -> str:
    return f"nflverse:stats_team_week_{int(season)}"


def player_stats_source(season: int) -> str:
    return f"nflverse:stats_player_week_{int(season)}"


def injuries_source(season: int) -> str:
    return f"nflverse:injuries_{int(season)}"


# -- fetching ---------------------------------------------------------------------------------

def is_live(season: Optional[int], current: int) -> bool:
    """True for the schedule (season None) and for the current season and the one before it."""
    return season is None or int(season) >= int(current) - LIVE_SEASONS_BACK


def fetch_csv(fetcher, url: str, *, live: bool) -> Tuple[Optional[str], Optional[str]]:
    """(text, fetched_utc) for a release file, or (None, None) when the source answers 404.

    A live file is re-fetched when its cached copy is older than `LIVE_MAX_AGE_S`; any other
    file is cached forever (its 404 too). SourceBlocked and RequestCapReached propagate.
    """
    try:
        text = fetcher.get_text(url, max_age_s=LIVE_MAX_AGE_S if live else None)
    except NotFound:
        return None, None
    return text, fetcher.fetched_utc(url)


# -- reading ----------------------------------------------------------------------------------

_NA = frozenset({"", "NA", "N/A", "NULL", "NAN", "NONE"})


def read_csv(text: str) -> List[dict]:
    """The rows of a CSV file as dicts keyed by header name (a leading byte-order mark ignored)."""
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"), newline="")))


def clean(value) -> Optional[str]:
    """A trimmed string, or None for blank, NA, NaN."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.upper() in _NA else text


def to_number(value):
    """An int when the value is integral, else a float; None when blank or not finite."""
    text = clean(value)
    if text is None:
        return None
    try:
        num = float(text)
    except ValueError:
        return None
    if not math.isfinite(num):
        return None
    return int(num) if num == int(num) else num


def to_int(value) -> Optional[int]:
    """An int for a whole number ("7", "7.0"), None for blank or a fraction."""
    num = to_number(value)
    return int(num) if num is not None and float(num).is_integer() else None


def to_float(value, digits: Optional[int] = None) -> Optional[float]:
    num = to_number(value)
    if num is None:
        return None
    return round(float(num), digits) if digits is not None else float(num)


def to_flag(value) -> Optional[bool]:
    text = clean(value)
    return {"1": True, "0": False, "1.0": True, "0.0": False}.get(text) if text is not None else None


# -- the schedule -----------------------------------------------------------------------------

def _status(home_score, away_score, kickoff_utc: Optional[str], now) -> str:
    kickoff = timeutil.instant(kickoff_utc) if kickoff_utc else None
    if home_score is not None and away_score is not None:
        return "in_progress" if kickoff is not None and now < kickoff + FINAL_MIN_AGE else "final"
    if kickoff is not None and now > kickoff + NO_RESULT_AFTER:
        return "no_result"
    return "scheduled"


def parse_games(rows: Sequence[dict], *, fetched_utc: str,
                seasons: Optional[Iterable[int]] = None) -> Tuple[List[dict], dict]:
    """`games.jsonl` records from `schedules/games.csv` rows, and a summary.

    The whole file is read before anything is filtered because `venue_check` compares a game
    with the other games of its season. `seasons` then keeps only those seasons' records.
    """
    now = timeutil.parse_instant(fetched_utc)
    wanted = {int(s) for s in seasons} if seasons is not None else None
    home_ids: Dict[Tuple[str, int], Counter] = defaultdict(Counter)
    names: Dict[Tuple[str, int], Counter] = defaultdict(Counter)
    for row in rows:
        season = to_int(row.get("season"))
        sid = clean(row.get("stadium_id"))
        if season is None or not sid:
            continue
        if clean(row.get("location")) != "Neutral" and clean(row.get("home_team")):
            home_ids[(clean(row["home_team"]), season)][sid] += 1
        if clean(row.get("stadium")):
            names[(sid, season)][clean(row["stadium"])] += 1
    out: List[dict] = []
    skipped = 0
    for row in rows:
        try:
            season = int(row["season"])
            if wanted is not None and season not in wanted:
                continue
            record = _game_record(row, season, now, fetched_utc, home_ids, names)
        except (KeyError, ValueError, TypeError):
            skipped += 1
            continue
        out.append(record)
    flagged = Counter(r["venue_check"] for r in out)
    return out, {"rows": len(rows), "games": len(out), "skipped_rows": skipped,
                 "venue_check": {k: v for k, v in flagged.items() if k != "ok"}}


def _game_record(row: dict, season: int, now, fetched_utc: str,
                 home_ids: Dict[Tuple[str, int], Counter], names: Dict[Tuple[str, int], Counter]) -> dict:
    game_id = clean(row.get("game_id"))
    home, away = clean(row.get("home_team")), clean(row.get("away_team"))
    gameday = clean(row.get("gameday"))
    week = to_int(row.get("week"))
    if not (game_id and home and away and gameday) or week is None:
        raise ValueError("a game needs an id, both teams, a date and a week")
    kickoff_et = clean(row.get("gametime"))
    kickoff_utc = timeutil.eastern_to_utc(gameday, kickoff_et)
    home_score, away_score = to_int(row.get("home_score")), to_int(row.get("away_score"))
    neutral = clean(row.get("location")) == "Neutral"
    sid = clean(row.get("stadium_id"))
    stadium = clean(row.get("stadium"))
    check = "ok"
    if sid:
        modal_home = home_ids.get((home, season))
        if neutral and modal_home and modal_home.most_common(1)[0][0] == sid:
            check = "nominal_home_stadium_on_neutral_site"
        else:
            seen = names.get((sid, season))
            if seen and len(seen) > 1 and stadium and seen[stadium] < max(seen.values()):
                check = "stadium_id_name_conflict"
    surface = clean(row.get("surface"))
    overtime = to_flag(row.get("overtime"))
    return {
        "game_id": game_id, "season": season, "week": week,
        "game_type": clean(row.get("game_type")),
        "gameday": gameday, "weekday": clean(row.get("weekday")),
        "kickoff_et": kickoff_et, "kickoff_utc": kickoff_utc,
        "status": _status(home_score, away_score, kickoff_utc, now),
        "home_team": home, "away_team": away, "home_score": home_score, "away_score": away_score,
        "overtime": overtime if home_score is not None else None,
        "neutral_site": neutral,
        "stadium_id": sid, "stadium": stadium, "venue_check": check,
        "roof": (clean(row.get("roof")) or "").lower() or None,
        "surface": surface.lower() if surface else None,
        "temp_f": to_int(row.get("temp")), "wind_mph": to_int(row.get("wind")),
        "div_game": to_flag(row.get("div_game")),
        "home_rest_days": to_int(row.get("home_rest")), "away_rest_days": to_int(row.get("away_rest")),
        "home_coach": clean(row.get("home_coach")), "away_coach": clean(row.get("away_coach")),
        "referee": clean(row.get("referee")),
        "home_qb_id": clean(row.get("home_qb_id")), "home_qb_name": clean(row.get("home_qb_name")),
        "away_qb_id": clean(row.get("away_qb_id")), "away_qb_name": clean(row.get("away_qb_name")),
        "spread_line": to_float(row.get("spread_line")), "total_line": to_float(row.get("total_line")),
        "home_moneyline": to_int(row.get("home_moneyline")), "away_moneyline": to_int(row.get("away_moneyline")),
        "home_spread_odds": to_int(row.get("home_spread_odds")),
        "away_spread_odds": to_int(row.get("away_spread_odds")),
        "over_odds": to_int(row.get("over_odds")), "under_odds": to_int(row.get("under_odds")),
        "espn_id": clean(row.get("espn")), "pfr_id": clean(row.get("pfr")), "gsis_id": clean(row.get("gsis")),
        "source": GAMES_SOURCE, "fetched_utc": fetched_utc,
    }


# -- team statistics --------------------------------------------------------------------------

# (our name, the source's column, digits when a float is rounded)
TEAM_STAT_FIELDS = (
    ("pass_attempts", "attempts", None), ("completions", "completions", None),
    ("passing_yards", "passing_yards", None), ("passing_tds", "passing_tds", None),
    ("interceptions", "passing_interceptions", None), ("sacks_taken", "sacks_suffered", None),
    ("sack_yards_lost", "sack_yards_lost", None),
    ("carries", "carries", None), ("rushing_yards", "rushing_yards", None), ("rushing_tds", "rushing_tds", None),
    ("fumbles_lost", "fumbles_lost_total", None),
    ("penalties", "penalties", None), ("penalty_yards", "penalty_yards", None),
    ("passing_first_downs", "passing_first_downs", None), ("rushing_first_downs", "rushing_first_downs", None),
    ("passing_epa", "passing_epa", 3), ("rushing_epa", "rushing_epa", 3),
    ("sacks_made", "def_sacks", None), ("def_interceptions", "def_interceptions", None),
)
TEAM_STAT_NAMES = tuple(name for name, _, _ in TEAM_STAT_FIELDS)


def parse_team_stats(rows: Sequence[dict]) -> Tuple[Dict[Tuple[str, str], dict], dict]:
    """(game_id, team) -> that team's statistics for the game, from `stats_team_week_{season}.csv`.

    `sack_yards_lost` is stored positive (the source writes it negative).
    """
    out: Dict[Tuple[str, str], dict] = {}
    skipped = duplicates = 0
    for row in rows:
        game_id, team = clean(row.get("game_id")), clean(row.get("team"))
        if not game_id or not team:
            skipped += 1
            continue
        stats = {}
        for name, column, digits in TEAM_STAT_FIELDS:
            value = to_float(row.get(column), digits) if digits is not None else to_number(row.get(column))
            if name == "sack_yards_lost" and value is not None:
                value = abs(value)
            stats[name] = value
        if (game_id, team) in out:
            duplicates += 1
        out[(game_id, team)] = stats
    return out, {"rows": len(rows), "team_rows": len(out), "skipped_rows": skipped, "duplicates": duplicates}


def _ratio(num, den, digits=4):
    return round(num / den, digits) if num is not None and den else None


def _derived(stats: Optional[dict]) -> dict:
    """plays, net_yards, yards_per_play and giveaways from one team's raw statistics."""
    blank = {"plays": None, "net_yards": None, "yards_per_play": None, "giveaways": None}
    if not stats:
        return blank
    need = ("pass_attempts", "sacks_taken", "carries", "passing_yards", "sack_yards_lost", "rushing_yards")
    out = dict(blank)
    if all(stats.get(k) is not None for k in need):
        out["plays"] = stats["pass_attempts"] + stats["sacks_taken"] + stats["carries"]
        out["net_yards"] = stats["passing_yards"] - stats["sack_yards_lost"] + stats["rushing_yards"]
        out["yards_per_play"] = _ratio(out["net_yards"], out["plays"])
    if stats.get("interceptions") is not None and stats.get("fumbles_lost") is not None:
        out["giveaways"] = stats["interceptions"] + stats["fumbles_lost"]
    return out


def build_team_games(games: Iterable[dict], team_stats: Dict[Tuple[str, str], dict], *,
                     fetched_utc: str, stats_source: Optional[str] = None) -> List[dict]:
    """`team_games.jsonl` records: two per game, from the games and the team statistics.

    A game with no statistics row for a team gets that team's row with every statistic null
    and `has_stats` false. `takeaways` is the opponent's giveaways, so a game's two turnover
    margins sum to zero; it is null when the opponent's row is missing.
    """
    out: List[dict] = []
    for game in games:
        for side, other in (("home", "away"), ("away", "home")):
            team, opp = game[f"{side}_team"], game[f"{other}_team"]
            mine = team_stats.get((game["game_id"], team))
            theirs = team_stats.get((game["game_id"], opp))
            final = game.get("status") == "final"
            pf, pa = game.get(f"{side}_score"), game.get(f"{other}_score")
            have_score = pf is not None and pa is not None
            mine_derived, theirs_derived = _derived(mine), _derived(theirs)
            giveaways = mine_derived["giveaways"]
            takeaways = theirs_derived["giveaways"]
            record = {
                "game_id": game["game_id"], "team": team, "opponent": opp,
                "season": game["season"], "week": game["week"], "game_type": game.get("game_type"),
                "kickoff_utc": game.get("kickoff_utc"), "status": game.get("status"),
                "site": "neutral" if game.get("neutral_site") else side,
                "points_for": pf, "points_against": pa,
                "margin": pf - pa if final and have_score else None,
                "result": ("W" if pf > pa else "L" if pf < pa else "T") if final and have_score else None,
                "overtime": game.get("overtime"),
                "rest_days_source": game.get(f"{side}_rest_days"),
                "coach": game.get(f"{side}_coach"),
                "qb_id": game.get(f"{side}_qb_id"), "qb_name": game.get(f"{side}_qb_name"),
                "has_stats": mine is not None,
            }
            for name in TEAM_STAT_NAMES:
                record[name] = mine.get(name) if mine else None
            record.update(mine_derived)
            record["takeaways"] = takeaways if mine is not None else None
            record["turnover_margin"] = (takeaways - giveaways) if takeaways is not None and giveaways is not None else None
            if mine is not None and stats_source:
                record["source"] = f"{GAMES_SOURCE}+{stats_source.split(':', 1)[-1]}"
            else:
                record["source"] = GAMES_SOURCE
            record["fetched_utc"] = fetched_utc
            out.append(record)
    return out


# -- player statistics ------------------------------------------------------------------------

# (our name, the source's column, digits when a float is rounded)
PLAYER_STAT_FIELDS = (
    ("pass_attempts", "attempts", None), ("completions", "completions", None),
    ("passing_yards", "passing_yards", None), ("passing_tds", "passing_tds", None),
    ("interceptions", "passing_interceptions", None), ("sacks_taken", "sacks_suffered", None),
    ("carries", "carries", None), ("rushing_yards", "rushing_yards", None), ("rushing_tds", "rushing_tds", None),
    ("targets", "targets", None), ("receptions", "receptions", None),
    ("receiving_yards", "receiving_yards", None), ("receiving_tds", "receiving_tds", None),
    ("target_share", "target_share", 4), ("air_yards_share", "air_yards_share", 4),
)
PLAYER_STAT_NAMES = tuple(name for name, _, _ in PLAYER_STAT_FIELDS)
OFFENSE_GROUPS = frozenset({"QB", "RB", "WR", "TE"})


def parse_player_stats(rows: Sequence[dict], games_by_id: Dict[str, dict], *, fetched_utc: str,
                       source: str) -> Tuple[List[dict], dict]:
    """`player_games.jsonl` records from `stats_player_week_{season}.csv` rows, and a summary.

    Kept: a quarterback, running back, wide receiver or tight end row, and any other row with
    a pass attempt, a carry or a target. The summary counts every row that was not kept and why,
    so source rows = kept + the dropped counts.
    """
    info = Counter({"rows": len(rows)})
    out: Dict[Tuple[str, str], dict] = {}
    for row in rows:
        player_id, game_id = clean(row.get("player_id")), clean(row.get("game_id"))
        if not player_id:
            info["dropped_no_player_id"] += 1
            continue
        game = games_by_id.get(game_id) if game_id else None
        if game is None:
            info["dropped_unknown_game"] += 1
            continue
        position = clean(row.get("position"))
        group = position_group(position, clean(row.get("position_group")))
        stats = {}
        for name, column, digits in PLAYER_STAT_FIELDS:
            stats[name] = to_float(row.get(column), digits) if digits is not None else to_number(row.get(column))
        usage = sum(stats[k] or 0 for k in ("pass_attempts", "carries", "targets"))
        if group not in OFFENSE_GROUPS and usage <= 0:
            info["dropped_not_offense"] += 1
            continue
        team = clean(row.get("team"))
        record = {
            "game_id": game_id, "player_id": player_id,
            "season": game["season"], "week": game["week"], "game_type": game.get("game_type"),
            "kickoff_utc": game.get("kickoff_utc"),
            "team": team, "opponent": clean(row.get("opponent_team")),
            "name": clean(row.get("player_display_name")) or clean(row.get("player_name")),
            "position": position, "position_group": group,
        }
        record.update(stats)
        record["source"] = source
        record["fetched_utc"] = fetched_utc
        if (game_id, player_id) in out:
            info["duplicates"] += 1
        out[(game_id, player_id)] = record
    info["kept"] = len(out)
    return list(out.values()), dict(info)


# -- injury reports ---------------------------------------------------------------------------

_REPORT_CODES = {"out": "out", "doubtful": "doubtful", "questionable": "questionable", "note": "note"}
_PRACTICE_CODES = (("full participation", "full"), ("limited participation", "limited"),
                   ("did not participate", "dnp"), ("note", "note"))


def _report_status(value) -> Optional[str]:
    text = clean(value)
    if text is None:
        return None
    return _REPORT_CODES.get(text.lower(), text.lower())


def _practice_status(value) -> Optional[str]:
    text = clean(value)
    if text is None:
        return None
    lowered = text.lower()
    for prefix, code in _PRACTICE_CODES:
        if lowered.startswith(prefix):
            return code
    return lowered


def _stamp(value) -> Optional[str]:
    text = clean(value)
    if text is None:
        return None
    try:
        return timeutil.iso_utc(timeutil.parse_instant(text))
    except ValueError:
        return None


def parse_injuries(rows: Sequence[dict], game_ids: Dict[Tuple[int, int, str], dict], *, fetched_utc: str,
                   source: str) -> Tuple[List[dict], dict]:
    """`injuries.jsonl` records from `injuries_{season}.csv` rows, and a summary.

    `game_ids` maps (season, week, team) to that team's game record. A row joins to the game
    of its team and week. Duplicate rows for one player and game keep the one with the later
    `date_modified` (ties: the later line). A row that is only "full participation" with no
    game-status designation is not stored and is counted in `dropped_full_participation_only`.
    """
    info = Counter({"rows": len(rows)})
    chosen: Dict[Tuple[str, str], Tuple[tuple, dict]] = {}
    for line, row in enumerate(rows):
        season, week, team = to_int(row.get("season")), to_int(row.get("week")), clean(row.get("team"))
        player_id = clean(row.get("gsis_id"))
        if season is None or week is None or not team or not player_id:
            info["dropped_unreadable"] += 1
            continue
        game = game_ids.get((season, week, team))
        if game is None:
            info["dropped_no_game"] += 1
            continue
        position = clean(row.get("position"))
        modified = _stamp(row.get("date_modified"))
        record = {
            "game_id": game["game_id"], "player_id": player_id,
            "season": season, "week": week, "game_type": game.get("game_type"), "team": team,
            "name": clean(row.get("full_name")),
            "position": position, "position_group": position_group(position),
            "report_status": _report_status(row.get("report_status")),
            "report_injury": clean(row.get("report_primary_injury")),
            "report_injury_2": clean(row.get("report_secondary_injury")),
            "practice_status": _practice_status(row.get("practice_status")),
            "practice_injury": clean(row.get("practice_primary_injury")),
            "practice_injury_2": clean(row.get("practice_secondary_injury")),
            "date_modified": modified,
            "source": source, "fetched_utc": fetched_utc,
        }
        key = (game["game_id"], player_id)
        rank = (modified or "", line)
        if key in chosen:
            info["duplicates"] += 1
            if rank < chosen[key][0]:
                continue
        chosen[key] = (rank, record)
    kept = []
    for _, record in chosen.values():
        if record["report_status"] is None and record["practice_status"] in (None, "full"):
            info["dropped_full_participation_only" if record["practice_status"] == "full" else "dropped_no_status"] += 1
        else:
            kept.append(record)
    info["kept"] = len(kept)
    return kept, dict(info)


def index_games_by_team_week(games: Iterable[dict]) -> Dict[Tuple[int, int, str], dict]:
    """(season, week, team) -> the game that team plays that week (each team plays once a week)."""
    out: Dict[Tuple[int, int, str], dict] = {}
    for game in games:
        for side in ("home_team", "away_team"):
            out[(game["season"], game["week"], game[side])] = game
    return out
