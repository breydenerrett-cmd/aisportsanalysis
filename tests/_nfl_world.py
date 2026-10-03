"""A small synthetic NFL league for the NFL data tests (features, matchup, API, pipeline).

Four teams with real stadium ids so the travel figures use the real venue table:

    KC  (Kansas City, KAN00, Central)   BUF (Buffalo, BUF00, Eastern)
    SEA (Seattle, SEA00, Pacific)       ARI (Glendale, PHO00, Arizona: no daylight time)

Fifteen games over two seasons, every one chosen so a test can say what each figure must be
by hand. Nothing here is real data. `build_world(root)` writes the four dataset files and
returns the store; `NOW` is the pretend present (after week 7 of 2025, before week 8).

THE GAMES (kickoff Eastern; scores are away - home)

 2024 season
  g01 2024_12_KC_BUF   Sun 2024-11-17 16:25   KC 21 - BUF 30
  g02 2024_18_ARI_SEA  Sun 2025-01-05 16:25   ARI 25 - SEA 30
 2025 season
  g03 2025_01_BUF_KC   Thu 2025-09-04 20:20   BUF 24 - KC 27          (primetime, Thursday)
  g04 2025_01_ARI_SEA  Sun 2025-09-07 16:25   ARI 17 - SEA 21         (divisional)
  g05 2025_02_KC_SEA   Sun 2025-09-14 13:00   KC 20 - SEA 24
  g06 2025_02_ARI_BUF  Sun 2025-09-14 13:00   ARI 10 - BUF 31
  g07 2025_03_SEA_KC   Thu 2025-09-18 20:15   SEA 17 - KC 31          (KC and SEA on four days' rest)
  g08 2025_03_BUF_ARI  Sun 2025-09-21 16:05   BUF 28 - ARI 14
  g09 2025_04_SEA_BUF  Sun 2025-09-28 13:00   SEA 20 - BUF 17         (KC and ARI have the week off)
  g10 2025_05_KC_ARI   Sun 2025-10-05 16:25   KC 30 - ARI 10          (both coming off the bye)
  g11 2025_05_BUF_SEA  Sun 2025-10-05 13:00   BUF 30 - SEA 27         (overtime)
  g12 2025_06_ARI_KC   Sun 2025-10-12 09:30   ARI 13 - KC 20          (neutral site, London)
  g13 2025_07_SEA_BUF  Sun 2025-10-19 09:30   SEA 16 - BUF 19         (neutral, venue named wrongly: unknown)
  g14 2025_08_BUF_KC   Sun 2025-10-26 16:25   scheduled, with a market and projected starters
  g15 2025_08_SEA_ARI  Sun 2025-10-26 16:05   scheduled, no market
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.datasvc.nfl import timeutil
from src.datasvc.nfl.store import NflStore

NOW = "2025-10-20T12:00:00Z"          # the pretend present: after week 7 of 2025, before week 8
FETCHED = NOW                         # every stored row was fetched "now"
TEAMS = {"KC": "KAN00", "BUF": "BUF00", "SEA": "SEA00", "ARI": "PHO00"}
COACH = {"KC": "Coach Chiefs", "BUF": "Coach Bills", "SEA": "Coach Hawks", "ARI": "Coach Cards"}
QB1 = {t: f"00-{t}QB1" for t in TEAMS}
QB2 = {t: f"00-{t}QB2" for t in TEAMS}

# id, season, week, type, gameday, kickoff ET, away, home, away score, home score, extras
SPEC = [
    ("2024_12_KC_BUF", 2024, 12, "REG", "2024-11-17", "16:25", "KC", "BUF", 21, 30, {}),
    ("2024_18_ARI_SEA", 2024, 18, "REG", "2025-01-05", "16:25", "ARI", "SEA", 25, 30, {"div_game": True}),
    ("2025_01_BUF_KC", 2025, 1, "REG", "2025-09-04", "20:20", "BUF", "KC", 24, 27,
     {"spread_line": 3.0, "total_line": 46.5, "home_moneyline": -150, "away_moneyline": 130}),
    ("2025_01_ARI_SEA", 2025, 1, "REG", "2025-09-07", "16:25", "ARI", "SEA", 17, 21, {"div_game": True}),
    ("2025_02_KC_SEA", 2025, 2, "REG", "2025-09-14", "13:00", "KC", "SEA", 20, 24, {"temp_f": 70, "wind_mph": 5}),
    ("2025_02_ARI_BUF", 2025, 2, "REG", "2025-09-14", "13:00", "ARI", "BUF", 10, 31, {}),
    ("2025_03_SEA_KC", 2025, 3, "REG", "2025-09-18", "20:15", "SEA", "KC", 17, 31, {}),
    ("2025_03_BUF_ARI", 2025, 3, "REG", "2025-09-21", "16:05", "BUF", "ARI", 28, 14, {"roof": "closed"}),
    ("2025_04_SEA_BUF", 2025, 4, "REG", "2025-09-28", "13:00", "SEA", "BUF", 20, 17, {}),
    ("2025_05_KC_ARI", 2025, 5, "REG", "2025-10-05", "16:25", "KC", "ARI", 30, 10, {"roof": "closed"}),
    ("2025_05_BUF_SEA", 2025, 5, "REG", "2025-10-05", "13:00", "BUF", "SEA", 30, 27, {"overtime": True}),
    ("2025_06_ARI_KC", 2025, 6, "REG", "2025-10-12", "09:30", "ARI", "KC", 13, 20,
     {"neutral_site": True, "stadium_id": "LON02"}),
    ("2025_07_SEA_BUF", 2025, 7, "REG", "2025-10-19", "09:30", "SEA", "BUF", 16, 19,
     {"neutral_site": True, "stadium_id": "BUF00", "venue_check": "nominal_home_stadium_on_neutral_site"}),
    ("2025_08_BUF_KC", 2025, 8, "REG", "2025-10-26", "16:25", "BUF", "KC", None, None,
     {"spread_line": 3.5, "total_line": 47.5, "home_moneyline": -180, "away_moneyline": 155,
      "home_spread_odds": -110, "away_spread_odds": -110, "over_odds": -105, "under_odds": -115}),
    ("2025_08_SEA_ARI", 2025, 8, "REG", "2025-10-26", "16:05", "SEA", "ARI", None, None, {"div_game": True}),
]

# net yards, plays, giveaways for the (away, home) team of each final game
STATS: Dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {
    "2024_12_KC_BUF": ((310, 61, 1), (400, 63, 0)),
    "2024_18_ARI_SEA": ((300, 60, 1), (330, 62, 1)),
    "2025_01_BUF_KC": ((330, 60, 1), (360, 62, 0)),
    "2025_01_ARI_SEA": ((280, 58, 2), (310, 61, 1)),
    "2025_02_KC_SEA": ((300, 60, 1), (340, 63, 0)),
    "2025_02_ARI_BUF": ((200, 55, 3), (420, 64, 0)),
    "2025_03_SEA_KC": ((250, 57, 2), (400, 65, 1)),
    "2025_03_BUF_ARI": ((380, 62, 1), (240, 58, 1)),
    "2025_04_SEA_BUF": ((330, 60, 0), (300, 59, 2)),
    "2025_05_KC_ARI": ((420, 66, 0), (220, 56, 2)),
    "2025_05_BUF_SEA": ((360, 70, 1), (350, 69, 1)),
    "2025_06_ARI_KC": ((260, 57, 2), (350, 63, 0)),
    "2025_07_SEA_BUF": ((290, 60, 1), (310, 61, 1)),
}

# which quarterback starts, by game and team (default: the team's first). SEA's starter is hurt in weeks 4 and 5.
QB_OVERRIDE = {("2025_04_SEA_BUF", "SEA"): QB2["SEA"], ("2025_05_BUF_SEA", "SEA"): QB2["SEA"],
               ("2025_06_ARI_KC", "ARI"): QB2["ARI"]}
# an interim head coach in Seattle from week 7
COACH_OVERRIDE = {("2025_07_SEA_BUF", "SEA"): "Interim Hawks", ("2025_08_SEA_ARI", "SEA"): "Interim Hawks"}


def eastern(gameday: str, et: str) -> str:
    return timeutil.eastern_to_utc(gameday, et)


def _games() -> List[dict]:
    rows = []
    for gid, season, week, gtype, gameday, et, away, home, away_score, home_score, extra in SPEC:
        final = away_score is not None
        game = {
            "game_id": gid, "season": season, "week": week, "game_type": gtype, "gameday": gameday,
            "weekday": date.fromisoformat(gameday).strftime("%A"), "kickoff_et": et,
            "kickoff_utc": eastern(gameday, et),
            "status": "final" if final else "scheduled",
            "home_team": home, "away_team": away, "home_score": home_score, "away_score": away_score,
            "overtime": (extra.get("overtime", False) if final else None),
            "neutral_site": extra.get("neutral_site", False),
            "stadium_id": extra.get("stadium_id", TEAMS[home]), "stadium": "Somewhere Stadium",
            "venue_check": extra.get("venue_check", "ok"),
            "roof": extra.get("roof", "outdoors"), "surface": "grass",
            "temp_f": extra.get("temp_f"), "wind_mph": extra.get("wind_mph"),
            "div_game": extra.get("div_game", False),
            "home_rest_days": None, "away_rest_days": None,
            "home_coach": COACH_OVERRIDE.get((gid, home), COACH[home]),
            "away_coach": COACH_OVERRIDE.get((gid, away), COACH[away]),
            "referee": "Ref Eree",
            "home_qb_id": QB_OVERRIDE.get((gid, home), QB1[home]), "home_qb_name": f"{home} QB",
            "away_qb_id": QB_OVERRIDE.get((gid, away), QB1[away]), "away_qb_name": f"{away} QB",
            "spread_line": extra.get("spread_line"), "total_line": extra.get("total_line"),
            "home_moneyline": extra.get("home_moneyline"), "away_moneyline": extra.get("away_moneyline"),
            "home_spread_odds": extra.get("home_spread_odds"), "away_spread_odds": extra.get("away_spread_odds"),
            "over_odds": extra.get("over_odds"), "under_odds": extra.get("under_odds"),
            "espn_id": None, "pfr_id": None, "gsis_id": None,
            "source": "nflverse:games.csv", "fetched_utc": FETCHED,
        }
        rows.append(game)
    rest = _rest_days(rows)
    for game in rows:
        game["home_rest_days"] = rest[(game["game_id"], game["home_team"])]
        game["away_rest_days"] = rest[(game["game_id"], game["away_team"])]
    return rows


def _team_games(games: List[dict]) -> List[dict]:
    rows = []
    for game in games:
        stats = STATS.get(game["game_id"])
        for index, side in enumerate(("away", "home")):
            team, opp = game[f"{side}_team"], game["away_team" if side == "home" else "home_team"]
            other = "home" if side == "away" else "away"
            pf, pa = game[f"{side}_score"], game[f"{other}_score"]
            row = {
                "game_id": game["game_id"], "team": team, "opponent": opp, "season": game["season"],
                "week": game["week"], "game_type": game["game_type"], "kickoff_utc": game["kickoff_utc"],
                "status": game["status"], "site": "neutral" if game["neutral_site"] else side,
                "points_for": pf, "points_against": pa,
                "margin": pf - pa if pf is not None else None,
                "result": (("W" if pf > pa else "L" if pf < pa else "T") if pf is not None else None),
                "overtime": game["overtime"], "rest_days_source": game[f"{side}_rest_days"],
                "coach": game[f"{side}_coach"],
                "qb_id": game[f"{side}_qb_id"], "qb_name": game[f"{side}_qb_name"], "has_stats": stats is not None,
                "net_yards": None, "plays": None, "yards_per_play": None, "giveaways": None, "takeaways": None,
                "turnover_margin": None, "source": "nflverse:games.csv", "fetched_utc": FETCHED,
            }
            if stats is not None:
                net, plays, giveaways = stats[index]
                opp_giveaways = stats[1 - index][2]
                row.update({"net_yards": net, "plays": plays, "yards_per_play": round(net / plays, 4),
                            "giveaways": giveaways, "takeaways": opp_giveaways,
                            "turnover_margin": opp_giveaways - giveaways})
            rows.append(row)
    return rows


def _player(game_id: str, player_id: str, team: str, name: str, position: str, group: str, season: int, week: int,
            kickoff: str, opponent: str, **stats) -> dict:
    row = {"game_id": game_id, "player_id": player_id, "season": season, "week": week, "game_type": "REG",
           "kickoff_utc": kickoff, "team": team, "opponent": opponent, "name": name, "position": position,
           "position_group": group, "pass_attempts": 0, "completions": 0, "passing_yards": 0, "passing_tds": 0,
           "interceptions": 0, "sacks_taken": 0, "carries": 0, "rushing_yards": 0, "rushing_tds": 0, "targets": 0,
           "receptions": 0, "receiving_yards": 0, "receiving_tds": 0, "target_share": None, "air_yards_share": None,
           "source": "nflverse:stats_player_week_2025", "fetched_utc": FETCHED}
    row.update(stats)
    return row


# KC's wide receiver: no row in g07 (a game he did not record a stat in)
KC_WR = [  # game id, targets, receptions, yards, tds, target share
    ("2025_01_BUF_KC", 8, 6, 90, 1, 0.25), ("2025_02_KC_SEA", 5, 3, 40, 0, 0.16),
    ("2025_05_KC_ARI", 6, 4, 55, 0, 0.20), ("2025_06_ARI_KC", 9, 6, 70, 1, 0.28)]
KC_QB = [  # game id, attempts, completions, yards, tds, interceptions, carries, rushing yards
    ("2025_01_BUF_KC", 30, 20, 250, 2, 0, 3, 15), ("2025_02_KC_SEA", 35, 22, 280, 1, 1, 2, 5),
    ("2025_03_SEA_KC", 28, 19, 240, 3, 0, 4, 20), ("2025_05_KC_ARI", 33, 24, 300, 2, 0, 1, 3),
    ("2025_06_ARI_KC", 31, 21, 260, 1, 1, 2, 10)]


def _players(games: List[dict]) -> List[dict]:
    by_id = {g["game_id"]: g for g in games}
    out = []

    def make(gid, pid, team, name, position, group, **stats):
        g = by_id[gid]
        opp = g["away_team"] if g["home_team"] == team else g["home_team"]
        out.append(_player(gid, pid, team, name, position, group, g["season"], g["week"], g["kickoff_utc"], opp, **stats))

    for gid, tgt, rec, yds, tds, share in KC_WR:
        make(gid, "00-KCWR1", "KC", "Kay See", "WR", "WR", targets=tgt, receptions=rec, receiving_yards=yds,
             receiving_tds=tds, target_share=share, air_yards_share=share / 2)
    for gid, att, comp, yds, tds, ints, car, ryds in KC_QB:
        make(gid, QB1["KC"], "KC", "Kay See Quarterback", "QB", "QB", pass_attempts=att, completions=comp,
             passing_yards=yds, passing_tds=tds, interceptions=ints, carries=car, rushing_yards=ryds)
    # a tight end with a row of zeros (he has a stat line from special teams) and one real game
    make("2025_01_BUF_KC", "00-KCTE1", "KC", "Kay See Tight", "TE", "TE")
    make("2025_02_KC_SEA", "00-KCTE1", "KC", "Kay See Tight", "TE", "TE", targets=4, receptions=3, receiving_yards=33)
    # a running back traded from Buffalo to Seattle after week 2
    for gid, team, carries, yards in (("2025_01_BUF_KC", "BUF", 12, 50), ("2025_02_ARI_BUF", "BUF", 15, 70),
                                      ("2025_04_SEA_BUF", "SEA", 10, 40), ("2025_05_BUF_SEA", "SEA", 20, 95)):
        make(gid, "00-MOVER1", team, "Moe Ver", "RB", "RB", carries=carries, rushing_yards=yards)
    return out


def _injury(gid: str, game: dict, pid: str, team: str, name: str, position: str, group: str, report: Optional[str],
            practice: Optional[str], modified: Optional[str], injury: str = "Knee") -> dict:
    return {"game_id": gid, "player_id": pid, "season": game["season"], "week": game["week"],
            "game_type": game["game_type"], "team": team, "name": name, "position": position,
            "position_group": group, "report_status": report, "report_injury": injury, "report_injury_2": None,
            "practice_status": practice, "practice_injury": injury, "practice_injury_2": None,
            "date_modified": modified, "source": "nflverse:injuries_2025", "fetched_utc": FETCHED}


def _injuries(games: List[dict]) -> List[dict]:
    by_id = {g["game_id"]: g for g in games}
    g10, g12 = by_id["2025_05_KC_ARI"], by_id["2025_06_ARI_KC"]
    return [
        # week 5, KC game g10 (kickoff 2025-10-05 20:25Z): timestamped reports. The ARI running back's row is stamped
        # AFTER the kickoff, so no as_of up to the kickoff may use it.
        _injury("2025_05_KC_ARI", g10, "00-KCWR1", "KC", "Kay See", "WR", "WR", "out", "dnp", "2025-10-03T20:00:00Z"),
        _injury("2025_05_KC_ARI", g10, QB1["KC"], "KC", "Kay See Quarterback", "QB", "QB", "questionable", "limited",
                "2025-10-03T20:00:00Z", "Shoulder"),
        _injury("2025_05_KC_ARI", g10, "00-KCOL1", "KC", "Kay See Lineman", "T", "OL", "doubtful", "dnp",
                "2025-10-03T20:00:00Z", "Ankle"),
        _injury("2025_05_KC_ARI", g10, "00-KCDB1", "KC", "Kay See Corner", "CB", "DB", None, "limited",
                "2025-10-02T20:00:00Z", "Hamstring"),
        _injury("2025_05_KC_ARI", g10, "00-ARIRB1", "ARI", "Ari Runner", "RB", "RB", "questionable", "limited",
                "2025-10-06T01:00:00Z", "Foot"),
        _injury("2025_05_KC_ARI", g10, "00-ARIDL1", "ARI", "Ari Rusher", "DE", "DL", "out", "dnp",
                "2025-10-03T21:00:00Z", "Back"),
        # week 6, the London game g12 (kickoff 2025-10-12 13:30Z): no timestamps (the 2025 file has none)
        _injury("2025_06_ARI_KC", g12, "00-KCWR1", "KC", "Kay See", "WR", "WR", "questionable", "limited", None),
        _injury("2025_06_ARI_KC", g12, "00-ARIWR1", "ARI", "Ari Wideout", "WR", "WR", "out", "dnp", None, "Hamstring"),
    ]


NFL_FILES = ("games", "team_games", "player_games", "injuries")


def world_rows() -> Dict[str, List[dict]]:
    games = _games()
    return {"games": games, "team_games": _team_games(games), "player_games": _players(games),
            "injuries": _injuries(games)}


def build_world(root) -> NflStore:
    """Write the four dataset files under `root` and return a store over them."""
    store = NflStore(Path(root))
    for name, rows in world_rows().items():
        store.write(name, rows)
    return store


# -- the same league as nflverse's CSV files, for the pipeline tests ---------------------------------------
#
# `source_files()` serves the world in the SOURCE's shape (column names, blanks, 0/1 flags, the
# `Neutral` location, negative sack yards), so a backfill through a fake fetcher must rebuild the
# world's own store rows. Raw team statistics are chosen so the derived figures come out exactly as in
# `STATS`: 20 carries for 100 yards, 2 sacks for 14 yards, the rest passes; interceptions are the giveaways.

import csv
import io

from src.datasvc.nfl import sources as _sources

GAME_COLUMNS = ["game_id", "season", "game_type", "week", "gameday", "weekday", "gametime", "away_team", "away_score",
                "home_team", "home_score", "location", "result", "total", "overtime", "old_game_id", "gsis",
                "nfl_detail_id", "pfr", "pff", "espn", "ftn", "away_rest", "home_rest", "away_moneyline",
                "home_moneyline", "spread_line", "away_spread_odds", "home_spread_odds", "total_line", "under_odds",
                "over_odds", "div_game", "roof", "surface", "temp", "wind", "away_qb_id", "home_qb_id",
                "away_qb_name", "home_qb_name", "away_coach", "home_coach", "referee", "stadium_id", "stadium"]
TEAM_COLUMNS = ["season", "week", "team", "season_type", "game_id", "opponent_team", "completions", "attempts",
                "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered", "sack_yards_lost",
                "carries", "rushing_yards", "rushing_tds", "fumbles_lost_total", "penalties", "penalty_yards",
                "passing_first_downs", "rushing_first_downs", "passing_epa", "rushing_epa", "def_sacks",
                "def_interceptions"]
PLAYER_COLUMNS = ["player_id", "player_name", "player_display_name", "position", "position_group", "season", "week",
                  "season_type", "game_id", "team", "opponent_team", "completions", "attempts", "passing_yards",
                  "passing_tds", "passing_interceptions", "sacks_suffered", "carries", "rushing_yards",
                  "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds", "target_share",
                  "air_yards_share"]
INJURY_COLUMNS = ["season", "game_type", "team", "week", "gsis_id", "position", "full_name", "first_name", "last_name",
                  "report_primary_injury", "report_secondary_injury", "report_status", "practice_primary_injury",
                  "practice_secondary_injury", "practice_status", "date_modified"]


def _csv(columns: List[str], rows: List[dict]) -> str:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(c) is None else row.get(c) for c in columns])
    return out.getvalue()


def _flag(value) -> str:
    return "" if value is None else ("1" if value else "0")


def _rest_days(games: List[dict]) -> Dict[Tuple[str, str], int]:
    """Calendar days since each team's previous game on the schedule (7 for a season's first game)."""
    out, last = {}, {}
    for g in sorted(games, key=lambda x: (x["kickoff_utc"], x["game_id"])):
        for team in (g["home_team"], g["away_team"]):
            prev = last.get(team)
            if prev is None or prev["season"] != g["season"]:
                out[(g["game_id"], team)] = 7
            else:
                out[(g["game_id"], team)] = (date.fromisoformat(g["gameday"]) - date.fromisoformat(prev["gameday"])).days
            last[team] = g
    return out


def games_csv(games: Optional[List[dict]] = None, **override_by_id) -> str:
    games = games if games is not None else _games()
    rest = _rest_days(games)
    rows = []
    for g in games:
        row = {
            "game_id": g["game_id"], "season": g["season"], "game_type": g["game_type"], "week": g["week"],
            "gameday": g["gameday"], "weekday": g["weekday"], "gametime": g["kickoff_et"],
            "away_team": g["away_team"], "away_score": g["away_score"], "home_team": g["home_team"],
            "home_score": g["home_score"], "location": "Neutral" if g["neutral_site"] else "Home",
            "overtime": _flag(g["overtime"]), "away_rest": rest[(g["game_id"], g["away_team"])],
            "home_rest": rest[(g["game_id"], g["home_team"])], "away_moneyline": g["away_moneyline"],
            "home_moneyline": g["home_moneyline"], "spread_line": g["spread_line"],
            "away_spread_odds": g["away_spread_odds"], "home_spread_odds": g["home_spread_odds"],
            "total_line": g["total_line"], "under_odds": g["under_odds"], "over_odds": g["over_odds"],
            "div_game": _flag(g["div_game"]), "roof": g["roof"], "surface": "grass ", "temp": g["temp_f"],
            "wind": g["wind_mph"], "away_qb_id": g["away_qb_id"], "home_qb_id": g["home_qb_id"],
            "away_qb_name": g["away_qb_name"], "home_qb_name": g["home_qb_name"], "away_coach": g["away_coach"],
            "home_coach": g["home_coach"], "referee": g["referee"], "stadium_id": g["stadium_id"],
            "stadium": g["stadium"]}
        row.update(override_by_id.get(g["game_id"], {}))
        rows.append(row)
    return _csv(GAME_COLUMNS, rows)


def team_stats_csv(season: int) -> str:
    rows = []
    for g in _games():
        stats = STATS.get(g["game_id"])
        if g["season"] != season or stats is None:
            continue
        for index, team in enumerate((g["away_team"], g["home_team"])):
            net, plays, giveaways = stats[index]
            attempts = plays - 2 - 20
            rows.append({"season": season, "week": g["week"], "team": team, "season_type": "REG", "game_id": g["game_id"],
                         "opponent_team": g["home_team" if index == 0 else "away_team"], "completions": attempts // 2,
                         "attempts": attempts, "passing_yards": net - 100 + 14, "passing_tds": 1,
                         "passing_interceptions": giveaways, "sacks_suffered": 2, "sack_yards_lost": -14, "carries": 20,
                         "rushing_yards": 100, "rushing_tds": 1, "fumbles_lost_total": 0, "penalties": 5,
                         "penalty_yards": 40, "passing_first_downs": 10, "rushing_first_downs": 5,
                         "passing_epa": "1.23456", "rushing_epa": "-0.5", "def_sacks": 2, "def_interceptions": 0})
    return _csv(TEAM_COLUMNS, rows)


def player_stats_csv(season: int) -> str:
    rows = []
    for p in _players(_games()):
        if p["season"] != season:
            continue
        rows.append({"player_id": p["player_id"], "player_name": p["name"], "player_display_name": p["name"],
                     "position": p["position"], "position_group": p["position_group"], "season": season,
                     "week": p["week"], "season_type": "REG", "game_id": p["game_id"], "team": p["team"],
                     "opponent_team": p["opponent"], "completions": p["completions"], "attempts": p["pass_attempts"],
                     "passing_yards": p["passing_yards"], "passing_tds": p["passing_tds"],
                     "passing_interceptions": p["interceptions"], "sacks_suffered": p["sacks_taken"],
                     "carries": p["carries"], "rushing_yards": p["rushing_yards"], "rushing_tds": p["rushing_tds"],
                     "targets": p["targets"], "receptions": p["receptions"], "receiving_yards": p["receiving_yards"],
                     "receiving_tds": p["receiving_tds"], "target_share": p["target_share"],
                     "air_yards_share": p["air_yards_share"]})
    # rows the parser must not store: a defender with no usage, and a row with no player id
    if season == 2025:
        rows.append({"player_id": "00-KCDB1", "player_name": "K.Corner", "player_display_name": "Kay See Corner",
                     "position": "CB", "position_group": "DB", "season": season, "week": 1, "season_type": "REG",
                     "game_id": "2025_01_BUF_KC", "team": "KC", "opponent_team": "BUF", "attempts": 0, "carries": 0,
                     "targets": 0})
        rows.append({"player_id": "", "player_name": "", "player_display_name": "", "position": "", "season": season,
                     "week": 1, "season_type": "REG", "game_id": "2025_01_BUF_KC", "team": "KC",
                     "opponent_team": "BUF", "attempts": 0, "carries": 0, "targets": 0})
    return _csv(PLAYER_COLUMNS, rows)


_REPORT = {"out": "Out", "doubtful": "Doubtful", "questionable": "Questionable"}
_PRACTICE = {"dnp": "Did Not Participate In Practice", "limited": "Limited Participation in Practice",
             "full": "Full Participation in Practice"}


def injuries_csv(season: int) -> str:
    rows = []
    for r in _injuries(_games()):
        if r["season"] != season:
            continue
        rows.append({"season": season, "game_type": r["game_type"], "team": r["team"], "week": r["week"],
                     "gsis_id": r["player_id"], "position": r["position"], "full_name": r["name"],
                     "report_primary_injury": r["report_injury"], "report_status": _REPORT.get(r["report_status"], ""),
                     "practice_primary_injury": r["practice_injury"], "practice_status": _PRACTICE.get(r["practice_status"], ""),
                     "date_modified": r["date_modified"] or ""})
    if season == 2025:    # a player who is only listed as a full participant: not stored
        rows.append({"season": season, "game_type": "REG", "team": "KC", "week": 5, "gsis_id": "00-KCFULL1",
                     "position": "WR", "full_name": "Kay See Fullback", "practice_status": _PRACTICE["full"]})
    return _csv(INJURY_COLUMNS, rows)


def source_files(seasons=(2024, 2025)) -> Dict[str, str]:
    """{url: CSV text} for every file a backfill of `seasons` asks for."""
    files = {_sources.games_url(): games_csv()}
    for season in seasons:
        files[_sources.team_stats_url(season)] = team_stats_csv(season)
        files[_sources.player_stats_url(season)] = player_stats_csv(season)
        files[_sources.injuries_url(season)] = injuries_csv(season)
    return files


class FakeFetcher:
    """Stands in for `PoliteFetcher`: serves saved text, counts what was asked for, never touches the network.

    `files` maps a URL to text; a URL that is absent answers 404 (`NotFound`). `blocked` and `cap` make it
    raise the source-blocked and request-cap errors after that many requests, like the real one.
    """

    def __init__(self, files: Dict[str, str], *, fetched_utc: str = FETCHED,
                 cap: Optional[int] = None, blocked_after: Optional[int] = None):
        self.files = dict(files)
        self.fetched = fetched_utc
        self.cap = cap
        self.blocked_after = blocked_after
        self.calls: List[Tuple[str, Optional[float]]] = []
        self.stats = {"requests": 0, "cache_hits": 0, "bytes": 0, "not_found": 0, "retries": 0}

    def get_text(self, url, *, use_cache=True, max_age_s=None):
        from src.datasvc.http import NotFound, RequestCapReached, SourceBlocked
        if self.blocked_after is not None and self.stats["requests"] >= self.blocked_after:
            raise SourceBlocked(url, 200, "the source served a browser check, not data")
        if self.cap is not None and self.stats["requests"] >= self.cap:
            raise RequestCapReached(url, None, f"request cap of {self.cap} reached")
        self.stats["requests"] += 1
        self.calls.append((url, max_age_s))
        if url not in self.files:
            self.stats["not_found"] += 1
            raise NotFound(url, 404, "not found")
        self.stats["bytes"] += len(self.files[url])
        return self.files[url]

    def fetched_utc(self, url):
        return self.fetched
