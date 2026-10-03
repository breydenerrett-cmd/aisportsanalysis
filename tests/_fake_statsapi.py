"""A small fake of the MLB Stats API, installed at the ONE network seam.

Everything the refresh touches reaches the network through
`src.providers.mlb._get_json` (schedule, boxscore, game log, standings, splits,
handedness), so patching that single function exercises the real parsing in
`history`, `bullpen`, `pitchers`, `standings` and `lineups` -- nothing is
stubbed above the wire except the two non-MLB-host fetches (Savant arsenals,
transactions), which the tests patch by name.

The fake keeps a `calls` list so a test can assert what was (and was not)
requested -- "no standings request for a postseason date" is a claim about
calls, not about files.
"""

from __future__ import annotations

from src.providers import mlb

TEAM_IDS = {"NYY": 147, "BOS": 111, "LAD": 119, "SD": 135, "HOU": 117, "SEA": 136,
            "ATL": 144, "PHI": 143, "CLE": 114, "DET": 116}


def raw_game(pk, date, away, home, away_score, home_score, game_type="R",
             final=True, away_sp=None, home_sp=None, hour="23:05:00"):
    def side(abbrev, score, sp):
        out = {"team": {"id": TEAM_IDS[abbrev], "abbreviation": abbrev, "name": abbrev}}
        if score is not None:
            out["score"] = score
        if sp is not None:
            out["probablePitcher"] = {"id": sp, "fullName": f"Pitcher {sp}"}
        return out
    return {
        "gamePk": pk,
        "gameDate": f"{date}T{hour}Z",
        "officialDate": date,
        "gameType": game_type,
        "status": {"codedGameState": "F" if final else "S",
                   "detailedState": "Final" if final else "Scheduled"},
        "teams": {"away": side(away, away_score if final else None, away_sp),
                  "home": side(home, home_score if final else None, home_sp)},
        "venue": {"name": f"Park {home}"},
        "doubleHeader": "N", "gameNumber": 1,
    }


class FakeStatsApi:
    """schedule: {date: [raw_game, ...]}; game_logs: {pitcher_id: [split, ...]}
    where a split is {"date", "gameType", "gs", "ip", "er"}; standings_dates:
    the dates the API will return a table for (anything else is empty, like a
    postseason date)."""

    def __init__(self, schedule, game_logs=None, standings_dates=(), reachable=True):
        self.schedule = schedule
        self.game_logs = game_logs or {}
        self.standings_dates = set(standings_dates)
        self.reachable = reachable
        self.calls = []

    # -- the patched function --------------------------------------------
    def __call__(self, path, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append((path, params))
        if not self.reachable:
            raise mlb.MLBError("network down (fake)")
        if path == "schedule":
            games = self.schedule.get(params.get("date"), [])
            return {"dates": [{"games": games}] if games else []}
        if path.startswith("game/") and path.endswith("/boxscore"):
            return self._boxscore(int(path.split("/")[1]))
        if path.startswith("people/") and path.endswith("/stats"):
            pid = int(path.split("/")[1])
            if params.get("stats") == "statSplits":
                return {"stats": [{"splits": [
                    {"split": {"description": "vs Left"},
                     "stat": {"battersFaced": 100, "inningsPitched": "25.0",
                              "avg": ".250", "ops": ".700"}}]}]}
            return self._game_log(pid, params)
        if path == "people":
            ids = str(params.get("personIds", "")).split(",")
            return {"people": [{"id": int(i), "fullName": f"Batter {i}",
                                "batSide": {"code": "R"}, "pitchHand": {"code": "R"}}
                               for i in ids if i]}
        if path == "standings":
            day = params.get("date")
            if day not in self.standings_dates:
                return {"records": []}
            return {"records": [{
                "division": {"id": 201, "name": "AL East"}, "league": {"id": 103},
                "teamRecords": [
                    {"team": {"id": TEAM_IDS["NYY"], "name": "NYY"}, "season": "2026",
                     "gamesPlayed": 150, "wins": 90, "losses": 60,
                     "winningPercentage": ".600", "divisionRank": "1",
                     "gamesBack": "-", "leagueRank": "1"},
                    {"team": {"id": TEAM_IDS["BOS"], "name": "BOS"}, "season": "2026",
                     "gamesPlayed": 150, "wins": 80, "losses": 70,
                     "winningPercentage": ".533", "divisionRank": "2",
                     "gamesBack": "10.0", "leagueRank": "5"}]}]}
        raise AssertionError(f"unexpected statsapi path {path!r}")

    # -- payloads ---------------------------------------------------------
    def _boxscore(self, pk):
        for games in self.schedule.values():
            for g in games:
                if g["gamePk"] == pk:
                    teams = {}
                    for side in ("away", "home"):
                        abbrev = g["teams"][side]["team"]["abbreviation"]
                        pid = 9000 + pk % 100 + (0 if side == "away" else 1)
                        teams[side] = {
                            "team": {"abbreviation": abbrev},
                            "pitchers": [pid],
                            "players": {f"ID{pid}": {
                                "person": {"fullName": f"Reliever {pid}"},
                                "stats": {"pitching": {
                                    "gamesStarted": 0, "inningsPitched": "1.0",
                                    "numberOfPitches": 15, "battersFaced": 4,
                                    "earnedRuns": 0, "strikeOuts": 1}}}},
                        }
                    return {"teams": teams}
        raise AssertionError(f"boxscore for unknown game {pk}")

    def _game_log(self, pid, params):
        wanted = params.get("gameType")
        types = set(wanted.split(",")) if wanted else {"R"}
        rows = []
        for split in self.game_logs.get(pid, []):
            kind = split["gameType"]
            if kind in types:
                rows.append(split)
            # the real API's aggregate "P" returns every postseason appearance again
            elif kind in {"F", "D", "L", "W"} and "P" in types:
                rows.append({**split, "gameType": "P"})
        return {"stats": [{"splits": [
            {"date": r["date"], "gameType": r["gameType"], "isHome": True,
             "stat": {"gamesStarted": r.get("gs", 1), "inningsPitched": r.get("ip", "6.0"),
                      "earnedRuns": r.get("er", 2), "runs": r.get("er", 2), "hits": 5,
                      "baseOnBalls": 1, "strikeOuts": 6, "homeRuns": 1,
                      "battersFaced": 24, "numberOfPitches": 90}}
            for r in rows]}]} if rows else {"stats": []}
