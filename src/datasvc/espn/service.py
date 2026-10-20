"""The unified read API over the ESPN-fed stores: `EspnService`, also reachable as `DataClient.league(code)`.

Every capability answers one of the two shapes the rest of the data service uses:

    {"available": True,  "sport": <league>, "kind", "data", "meta"}
    {"available": False, "missing": [{"item", "reason"}, ...]}

Point-in-time: pass `as_of` (an ISO instant) and every row is read as the newest version WE had observed
at or before it. A game first fetched after `as_of` does not exist for that read; a score that only
arrived later is not shown. Without `as_of` the newest version is used. `meta` carries the newest
`observed_utc` of the rows read and says that the basis is OBSERVED (forward capture) for the day the
store began and RECONSTRUCTED for a backfill (`observed_utc` is then the backfill time, not the game time).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.datasvc import names
from src.datasvc.client import unavailable
from src.datasvc.espn import leagues as lg
from src.datasvc.espn.store import ATTRIBUTION, EspnStore

CAPABILITIES = {
    "teams": "teams of the league (ids, abbreviations, names)",
    "players": "rosters (weekly snapshots) for pro leagues; search by name",
    "schedule": "games by date, season, team or status, with scores",
    "game": "one game with both teams' box score totals and, where stored, every player's line",
    "team_history": "a team's games, newest first, with its box-score totals",
    "player_history": "a player's box-score lines, newest first (pro leagues)",
    "standings": "standings snapshots by season and group",
    "injuries": "the injury report; as_of reads it as it stood then",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _newest(rows: Sequence[dict]) -> Optional[str]:
    return max((r.get("observed_utc") or "" for r in rows), default="") or None


class EspnService:
    def __init__(self, store: Optional[EspnStore] = None, *, clock: Optional[Callable[[], str]] = None):
        self.store = store or EspnStore()
        self._clock = clock or _now_iso

    # -- plumbing ----------------------------------------------------------------------------------------

    def leagues(self) -> List[dict]:
        return [{"code": l.code, "title": l.title, "family": l.family, "has_players": l.players,
                 "has_injuries": l.injuries, "stored": self.store.league_dir(l.code).exists()}
                for l in lg.LEAGUES.values()]

    def capabilities(self, league: str) -> dict:
        L = lg.get(league)
        caps = {k: {"available": True, "via": v} for k, v in CAPABILITIES.items()}
        if not L.players:
            for k in ("players", "player_history"):
                caps[k] = {"available": False, "reason": f"player lines are not stored for {L.title} "
                                                         "(a season of them is ~100 MB); team totals are"}
        if not L.injuries:
            caps["injuries"] = {"available": False, "reason": f"ESPN publishes no injury report for {L.title}"}
        return caps

    def _ok(self, league: str, kind: str, data: Any, rows: Sequence[dict], as_of: Optional[str], **meta) -> dict:
        m = {"source": "ESPN public site JSON", "attribution": ATTRIBUTION, "basis": "observed_utc is when LineHound "
             "fetched the row; a backfilled row's observed_utc is the backfill time", "built_utc": self._clock(),
             "as_of": as_of, "newest_observed_utc": _newest(rows)}
        m.update(meta)
        return {"available": True, "sport": league, "kind": kind, "data": data, "meta": m}

    def _league(self, league: str) -> lg.League:
        return lg.get(league)

    def _need(self, league: str, dataset: str, season=None) -> Optional[dict]:
        if not self.store.versions(league, dataset, season):
            return unavailable((dataset, f"the {league} {dataset} store holds no records"
                                         + (f" for season {season}" if season is not None else "")))
        return None

    def _team_id(self, league: str, value: str, as_of: Optional[str] = None) -> Tuple[Optional[str], Optional[dict]]:
        teams = {k[0]: v for k, v in self.store.latest(league, "teams", as_of=as_of).items()}
        v = str(value).strip()
        if v in teams:
            return v, None
        for tid, t in teams.items():
            if v.lower() == str(t.get("abbreviation", "")).lower():
                return tid, None
        people = {tid: [t.get("display_name"), t.get("name"), t.get("short_name"), t.get("location"),
                        f"{t.get('location', '')} {t.get('name', '')}"] for tid, t in teams.items()}
        res = names.match(v, {k: [n for n in ns if n] for k, ns in people.items()})
        if res.best:
            return res.best, None
        if res.ambiguous:
            return None, unavailable(("team", f"{value!r} fits several teams"),
                                     extra_items=[{"item": "candidates", "reason": "pass an id or abbreviation",
                                                   "candidates": [c[0] for c in res.candidates]}])
        return None, unavailable(("team", f"no {league} team matches {value!r}"))

    # -- capabilities --------------------------------------------------------------------------------------

    def teams(self, league: str, *, as_of: Optional[str] = None) -> dict:
        self._league(league)
        miss = self._need(league, "teams")
        if miss:
            return miss
        rows = sorted(self.store.latest(league, "teams", as_of=as_of).values(), key=lambda r: r.get("display_name") or "")
        return self._ok(league, "teams", rows, rows, as_of)

    def players(self, league: str, *, team: Optional[str] = None, search: Optional[str] = None,
                as_of: Optional[str] = None) -> dict:
        L = self._league(league)
        if not L.players:
            return unavailable(("players", self.capabilities(league)["players"]["reason"]))
        miss = self._need(league, "players")
        if miss:
            return miss
        rows = list(self.store.latest(league, "players", as_of=as_of).values())
        if team:
            tid, bad = self._team_id(league, team, as_of)
            if bad:
                return bad
            rows = [r for r in rows if r["team_id"] == tid]
        if search:
            res = names.match(search, {r["player_id"]: [r.get("name") or ""] for r in rows})
            keep = {c[0] for c in res.candidates}
            rows = [r for r in rows if r["player_id"] in keep]
        rows.sort(key=lambda r: (r["team_id"], r.get("name") or ""))
        return self._ok(league, "players", rows, rows, as_of)

    def schedule(self, league: str, *, date: Optional[str] = None, season: Optional[int] = None,
                 team: Optional[str] = None, status: Optional[str] = None, as_of: Optional[str] = None) -> dict:
        self._league(league)
        miss = self._need(league, "games", season)
        if miss:
            return miss
        rows = list(self.store.latest(league, "games", season, as_of).values())
        if date:
            rows = [r for r in rows if (r.get("scoreboard_date") or (r.get("date_utc") or "")[:10]) == date]
        if team:
            tid, bad = self._team_id(league, team, as_of)
            if bad:
                return bad
            rows = [r for r in rows if tid in (r["home_id"], r["away_id"])]
        if status:
            rows = [r for r in rows if r["state"] == status or r.get("status") == status]
        rows.sort(key=lambda r: (r.get("date_utc") or "", r["game_id"]))
        return self._ok(league, "schedule", rows, rows, as_of)

    def game(self, league: str, game_id: str, *, as_of: Optional[str] = None) -> dict:
        self._league(league)
        games = {k[0]: v for k, v in self.store.latest(league, "games", None, as_of).items()}
        g = games.get(str(game_id))
        if g is None:
            return unavailable(("game", f"no {league} game {game_id} observed" + (f" by {as_of}" if as_of else "")))
        season = g.get("season")
        tg = [r for k, r in self.store.latest(league, "team_games", season, as_of).items() if k[0] == g["game_id"]]
        pg = [r for k, r in self.store.latest(league, "player_games", season, as_of).items() if k[0] == g["game_id"]]
        missing = []
        if not tg:
            missing.append({"item": "team_games", "reason": "no box score observed yet"
                            + ("" if g["state"] == "post" else f" (game state: {g['state']})")})
        if not pg and self._league(league).players and tg:
            missing.append({"item": "player_games", "reason": "no player lines in the box score"})
        data = {"game": g, "team_games": sorted(tg, key=lambda r: r.get("home_away") or ""),
                "player_games": sorted(pg, key=lambda r: (r["team_id"], r.get("player_name") or ""))}
        out = self._ok(league, "game", data, [g] + tg + pg, as_of)
        if missing:
            out["meta"]["missing"] = missing
        return out

    def team_history(self, league: str, team: str, *, limit: int = 20, before: Optional[str] = None,
                     as_of: Optional[str] = None) -> dict:
        self._league(league)
        tid, bad = self._team_id(league, team, as_of)
        if bad:
            return bad
        games = {k[0]: v for k, v in self.store.latest(league, "games", None, as_of).items()}
        rows = []
        for (gid, t), r in self.store.latest(league, "team_games", None, as_of).items():
            if t != tid or gid not in games:
                continue
            if before and (r.get("date_utc") or "") >= before:
                continue
            rows.append(dict(r, game_state=games[gid]["state"]))
        rows.sort(key=lambda r: (r.get("date_utc") or "", r["game_id"]), reverse=True)
        if not rows:
            return unavailable(("team_games", f"no box scores observed for team {tid}"))
        return self._ok(league, "team_history", rows[:limit], rows, as_of, team_id=tid)

    def player_history(self, league: str, player_id: str, *, limit: int = 20, before: Optional[str] = None,
                       as_of: Optional[str] = None) -> dict:
        L = self._league(league)
        if not L.players:
            return unavailable(("player_games", self.capabilities(league)["player_history"]["reason"]))
        rows = [r for (gid, pid), r in self.store.latest(league, "player_games", None, as_of).items()
                if pid == str(player_id) and not (before and (r.get("date_utc") or "") >= before)]
        rows.sort(key=lambda r: (r.get("date_utc") or "", r["game_id"]), reverse=True)
        if not rows:
            return unavailable(("player_games", f"no lines observed for player {player_id}"))
        return self._ok(league, "player_history", rows[:limit], rows, as_of, player_id=str(player_id))

    def standings(self, league: str, *, season: Optional[int] = None, as_of: Optional[str] = None) -> dict:
        self._league(league)
        seasons = self.store.seasons(league, "standings")
        if not seasons:
            return unavailable(("standings", f"the {league} standings store holds no records"))
        pick = str(season) if season is not None else seasons[-1]
        if pick not in seasons:
            return unavailable(("standings", f"no standings stored for season {pick}"))
        allv = self.store.latest(league, "standings", pick, as_of)
        rows = sorted(allv.values(), key=lambda r: (r["group"], r.get("team_name") or "", r["team_id"]))
        if not rows:
            return unavailable(("standings", f"no standings observed for {pick}" + (f" by {as_of}" if as_of else "")))
        return self._ok(league, "standings", rows, rows, as_of, season=pick)

    def injuries(self, league: str, *, team: Optional[str] = None, as_of: Optional[str] = None,
                 include_cleared: bool = False) -> dict:
        L = self._league(league)
        if not L.injuries:
            return unavailable(("injuries", self.capabilities(league)["injuries"]["reason"]))
        miss = self._need(league, "injuries")
        if miss:
            return miss
        rows = list(self.store.latest(league, "injuries", None, as_of).values())
        if not include_cleared:
            rows = [r for r in rows if r.get("status") != "Cleared"]
        if team:
            tid, bad = self._team_id(league, team, as_of)
            if bad:
                return bad
            rows = [r for r in rows if r["team_id"] == tid]
        rows.sort(key=lambda r: (r["team_id"], r.get("player_name") or ""))
        return self._ok(league, "injuries", rows, rows, as_of)
