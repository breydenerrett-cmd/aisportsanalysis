"""Read API over the football-data store: matches with their open and closing odds, joined to ESPN game ids."""

from __future__ import annotations

from typing import Any, List, Optional

from src.datasvc.client import unavailable
from src.datasvc.soccer import footballdata as fd


class SoccerHistoryService:
    def __init__(self, store: Optional[fd.FootballDataStore] = None):
        self.store = store or fd.FootballDataStore()

    def _ok(self, kind: str, data: Any, rows: List[dict], **meta) -> dict:
        newest = max((r.get("observed_utc") or "" for r in rows), default="") or None
        m = {"source": "football-data.co.uk", "attribution": fd.ATTRIBUTION,
             "terms": "private use only; see src/datasvc/soccer/footballdata.py", "newest_observed_utc": newest}
        m.update(meta)
        return {"available": True, "sport": "soccer", "kind": kind, "data": data, "meta": m}

    def matches(self, league: str, *, season: Optional[int] = None, date: Optional[str] = None,
                team: Optional[str] = None, odds: bool = True) -> dict:
        if league not in fd.LEAGUES:
            return unavailable(("league", f"no football-data league {league!r}; known: {', '.join(fd.LEAGUES)}"))
        rows = list(self.store.latest(league, "matches", season).values())
        if not rows:
            return unavailable(("matches", f"the {league} football-data store holds no matches"
                                           + (f" for season {season}" if season is not None else "")))
        if date:
            rows = [r for r in rows if r["date"] == date]
        if team:
            t = team.lower()
            rows = [r for r in rows if t in r["home"].lower() or t in r["away"].lower()]
        rows.sort(key=lambda r: (r["date"], r["match_id"]))
        data = rows if odds else [{k: v for k, v in r.items() if k != "odds"} for r in rows]
        return self._ok("matches", data, rows, league=league)

    def for_game(self, league: str, game_id: str) -> dict:
        """The football-data match joined to an ESPN game id, with open and closing odds."""
        joined = [j for j in self.store.latest(league, "joins").values() if j["game_id"] == str(game_id)]
        if not joined:
            return unavailable(("join", f"no football-data match is joined to ESPN {league} game {game_id}"))
        j = joined[0]
        match = self.store.latest(league, "matches", j["season"]).get((league, j["match_id"]))
        if match is None:
            return unavailable(("matches", f"joined match {j['match_id']} is not in the store"))
        return self._ok("game_odds", {"join": j, "match": match}, [match, j], league=league)
