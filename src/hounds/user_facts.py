"""The point-in-time facts a user hound's conditions may consult.

ONE RULE: A FACT EXISTED AT LOCK, OR IT IS NOT A FACT
-----------------------------------------------------
Every method takes the game's Eastern slate date and its lock instant and returns what was knowable
then, or None. Team history is games dated STRICTLY BEFORE the slate date that also started at least
`FINISH_LAG` before the lock (so a late game from last night that was still being played at the lock
is not counted). Player history is box scores dated strictly before the slate date. Weather is the
newest forecast observed at or before the lock. None always means "we do not know", never zero: the
rule engine treats it as "condition not met" and counts it by name.

THE SAME READERS AS THE HOUSE PACK
----------------------------------
Results come through `src.hounds.pack.base` (`read_mlb_results`, `read_boxscore_finals`,
`read_nfl_games`), which already enforce the sealed 2026 window (nothing before 2026-08-28 is read)
and normalise club codes. A user hound therefore sees exactly the same history the house pack does,
and a "rest days" or "winning streak" cannot disagree between the two.

LAZY, SMALL, INJECTABLE
-----------------------
Each store is read on first use, so a hound with no conditions reads none of them, and kept in a
trimmed form (a pass holds a few MB, not a store). Tests build a `FactBook` straight from rows.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

FINISH_LAG = {"MLB": timedelta(hours=5), "NFL": timedelta(hours=6)}   # the pack's own lags
MIN_STARTER_OUTS = 9            # a pitcher line of 3+ innings counts as a start


def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _root() -> str:
    from src import paths
    return str(paths.repo_root())


class FactBook:
    """Point-in-time facts. Construct with rows in hand (tests) or with `FactBook.from_stores`."""

    def __init__(self, *, mlb_games: Optional[Iterable] = None, nfl_games: Optional[Iterable] = None,
                 box_rows: Optional[Iterable] = None, weather_rows: Optional[Iterable] = None,
                 loaders: Optional[Mapping[str, Callable[[], Iterable]]] = None):
        self._raw = {"mlb": mlb_games, "nfl": nfl_games, "box": box_rows, "weather": weather_rows}
        self._loaders = dict(loaders or {})
        self._team: dict = {}           # sport -> {code -> [entry]}
        self._players: Optional[dict] = None
        self._wx: Optional[dict] = None
        self._teams_of_player: dict = {}

    # ---- loading ------------------------------------------------------------------------------

    def _rows(self, key: str) -> Iterable:
        if self._raw.get(key) is None:
            loader = self._loaders.get(key)
            self._raw[key] = list(loader()) if loader else []
        return self._raw[key]

    def _team_index(self, sport: str) -> dict:
        if sport in self._team:
            return self._team[sport]
        index: dict = defaultdict(list)
        for g in self._rows("mlb" if sport == "MLB" else "nfl"):
            hs, as_ = g.get("home_score"), g.get("away_score")
            home, away = g.get("home"), g.get("away")
            if hs is None or as_ is None or not home or not away:
                continue
            start = _utc(g.get("start_utc"))
            for code, mine, theirs, at_home, opp in ((home, hs, as_, True, away), (away, as_, hs, False, home)):
                index[code].append({"date": g["date"], "start": start, "won": mine > theirs,
                                    "tied": mine == theirs, "home": at_home, "park": home, "opp": opp})
        for entries in index.values():
            entries.sort(key=lambda e: (e["date"], e["start"] or datetime.min.replace(tzinfo=timezone.utc)))
        self._team[sport] = index
        return index

    def _prior(self, sport: str, code: Optional[str], date: str, lock: Any) -> list:
        """The club's games that were over and dated before `date`, oldest first."""
        if not code or not date:
            return []
        cutoff = (_utc(lock) - FINISH_LAG[sport]) if _utc(lock) else None
        out = []
        for e in self._team_index(sport).get(code, ()):
            if e["date"] >= date:
                continue
            if cutoff is not None and e["start"] is not None and e["start"] > cutoff:
                continue
            out.append(e)
        return out

    # ---- team facts ---------------------------------------------------------------------------

    def rest_days(self, sport: str, code: str, date: str, lock: Any) -> Optional[int]:
        """MLB: days OFF since the last game (played yesterday = 0). NFL: days between games (a normal
        week = 7). None when the club has no earlier game on file."""
        prior = self._prior(sport, code, date, lock)
        if not prior:
            return None
        gap = (date_cls.fromisoformat(date) - date_cls.fromisoformat(prior[-1]["date"])).days
        return gap - 1 if sport == "MLB" else gap

    def streak(self, sport: str, code: str, date: str, lock: Any) -> Optional[int]:
        """+n for an n-game winning streak, -n for a losing one; None with no games; 0 after a tie."""
        prior = self._prior(sport, code, date, lock)
        if not prior:
            return None
        n = 0
        for e in reversed(prior):
            if e["tied"]:
                break
            if n == 0:
                n = 1 if e["won"] else -1
            elif (n > 0) == e["won"]:
                n += 1 if n > 0 else -1
            else:
                break
        return n

    def last_n_wins(self, sport: str, code: str, n: int, date: str, lock: Any) -> Optional[int]:
        prior = self._prior(sport, code, date, lock)
        if len(prior) < n:
            return None
        return sum(1 for e in prior[-n:] if e["won"])

    def split(self, sport: str, code: str, at_home: bool, date: str, lock: Any) -> Optional[tuple]:
        """(wins, games) in earlier games played at home (or on the road)."""
        prior = [e for e in self._prior(sport, code, date, lock) if e["home"] == at_home]
        if not prior:
            return None
        return sum(1 for e in prior if e["won"]), len(prior)

    def travel_miles(self, sport: str, code: str, today_park: Optional[str], date: str,
                     lock: Any) -> Optional[float]:
        """Miles between the park of the club's previous game and today's park."""
        if sport != "MLB" or not today_park:
            return None
        prior = self._prior(sport, code, date, lock)
        if not prior:
            return None
        try:
            from src.data import parks
            from src.pipeline import travel
            return float(travel.great_circle_miles(parks.coordinates(prior[-1]["park"]),
                                                   parks.coordinates(today_park)))
        except Exception:  # noqa: BLE001 -- an unknown park is "unknown", not zero miles
            return None

    # ---- players ------------------------------------------------------------------------------

    def _player_index(self) -> dict:
        if self._players is None:
            from src.hounds.user_rules import fold_player
            idx: dict = {"batter": defaultdict(list), "pitcher": defaultdict(list)}
            teams: dict = {}
            for r in self._rows("box"):
                kind = r.get("type")
                if kind not in ("batter", "pitcher") or not r.get("player_name") or not r.get("date"):
                    continue
                if kind == "pitcher" and (r.get("outs") or 0) < MIN_STARTER_OUTS:
                    continue
                if kind == "batter" and not (r.get("pa") or r.get("ab")):
                    continue
                key = fold_player(r["player_name"])
                idx[kind][key].append((r["date"], str(r.get("game_pk")), r))
                teams[key] = (r["date"], r.get("team_name"))
            for kind in idx:
                for rows in idx[kind].values():
                    rows.sort(key=lambda t: (t[0], t[1]))
            self._players = idx
            self._teams_of_player = teams
        return self._players

    def player_series(self, name: str, kind: str, key: str, date: str) -> Optional[list]:
        """Per-game values of box-score field `key` (chronological) for games before `date`; None
        when the player has no games on file."""
        from src.hounds.user_rules import fold_player
        rows = [r for d, _pk, r in self._player_index()[kind].get(fold_player(name), ()) if d < date]
        if not rows:
            return None
        return [float(r.get(key) or 0) for r in rows]

    def player_known(self, name: str) -> bool:
        from src.hounds.user_rules import fold_player
        k = fold_player(name)
        idx = self._player_index()
        return k in idx["batter"] or k in idx["pitcher"]

    def player_team(self, name: str) -> Optional[str]:
        """The MLB club code on the player's most recent box score, or None."""
        from src.hounds.user_rules import fold_player
        self._player_index()
        got = self._teams_of_player.get(fold_player(name))
        if not got or not got[1]:
            return None
        from src.pipeline.slate import team_abbrev_from_name
        from src.hounds.pack.base import mlb_code
        abbrev = team_abbrev_from_name(got[1])
        return mlb_code(abbrev) if abbrev else None

    # ---- weather ------------------------------------------------------------------------------

    def weather(self, game_pk: Optional[str], lock: Any, start: Any) -> Optional[dict]:
        """The newest forecast for the game's first-pitch hour observed at or before the lock."""
        if game_pk is None:
            return None
        if self._wx is None:
            wx: dict = defaultdict(list)
            for r in self._rows("weather"):
                if r.get("game_pk") is not None:
                    wx[str(r["game_pk"])].append(r)
            self._wx = wx
        lock_dt = _utc(lock)
        best = None
        for r in self._wx.get(str(game_pk), ()):
            obs = _utc(r.get("observed_utc"))
            if obs is None or (lock_dt is not None and obs > lock_dt):
                continue
            offset = abs(r.get("forecast_hour_offset_hours") if r.get("forecast_hour_offset_hours") is not None else 99)
            key = (offset, -(obs.timestamp()))
            if best is None or key < best[0]:
                best = (key, r)
        if best is None or best[0][0] > 1.0:       # no forecast for the first-pitch hour itself
            return None
        r = best[1]
        return {"temp_f": r.get("temp_f"), "wind_mph": r.get("wind_mph"), "wind_from_deg": r.get("wind_from_deg"),
                "roof": r.get("roof"), "precip_probability_pct": r.get("precip_probability_pct")}

    def wind_direction(self, home_code: Optional[str], wx: Mapping) -> Optional[str]:
        """'out' | 'in' | 'cross' from the park's verified bearing, or None (unverified park, roof)."""
        if not home_code or wx.get("wind_from_deg") is None:
            return None
        try:
            from src.data import parks
            roof = wx.get("roof")
            effect = parks.wind_effect(home_code, wx["wind_from_deg"], wx.get("wind_mph"),
                                       roof_closed=True if roof == "fixed" else (None if roof == "retractable" else False))
            return effect.get("direction")
        except Exception:  # noqa: BLE001
            return None

    # ---- the real stores -----------------------------------------------------------------------

    @classmethod
    def from_stores(cls, date: str, *, root: Optional[str] = None) -> "FactBook":
        base = root or _root()
        proc = os.path.join(base, "data", "processed")

        def mlb():
            from src.hounds.pack import base as pack
            games = pack.read_mlb_results(os.path.join(base, "data", "historical", "mlb_results.csv"))
            have = {g["game_pk"] for g in games}
            games += pack.read_boxscore_finals(os.path.join(proc, "boxscores_2026.jsonl"), skip_pks=have,
                                               start_by_pk={})
            return games

        def nfl():
            from src.hounds.pack import base as pack
            out = []
            for g in pack.read_nfl_games(os.path.join(base, "data", "datasvc", "nfl", "games.jsonl")):
                if g.get("status") not in (None, "final") or g.get("home_score") is None:
                    continue
                out.append({"date": g.get("gameday") or str(g.get("kickoff_utc"))[:10], "start_utc": g.get("kickoff_utc"),
                            "home": g.get("home_team"), "away": g.get("away_team"),
                            "home_score": g.get("home_score"), "away_score": g.get("away_score")})
            return out

        def box():
            path = os.path.join(proc, "boxscores_2026.jsonl")
            if not os.path.exists(path):
                return []
            keep = ("type", "date", "game_pk", "player_name", "team_name", "pa", "ab", "h", "hr", "rbi", "r",
                    "total_bases", "hits_runs_rbi", "k", "outs")
            out = []
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if '"type": "batter"' not in line and '"type": "pitcher"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    out.append({k: r.get(k) for k in keep})
            return out

        def weather():
            path = os.path.join(proc, "weather_forecast.jsonl")
            if not os.path.exists(path):
                return []
            d = date_cls.fromisoformat(date)
            wanted = {(d + timedelta(days=i)).isoformat() for i in (-1, 0, 1)}
            keep = ("game_pk", "observed_utc", "forecast_hour_offset_hours", "temp_f", "wind_mph",
                    "wind_from_deg", "roof", "precip_probability_pct")
            out = []
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if not any(f'"game_date": "{w}"' in line for w in wanted):
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    out.append({k: r.get(k) for k in keep})
            return out

        return cls(loaders={"mlb": mlb, "nfl": nfl, "box": box, "weather": weather})


# ---------------------------------------------------------------------------
# who is a player we know
# ---------------------------------------------------------------------------

_known_cache: dict = {}


def known_player_keys(root: Optional[str] = None) -> frozenset:
    """Folded names (`user_rules.fold_player`) of every player in the box-score store, read with a real
    JSON parse so accented names ('Jose Ramirez') match. Cached on the file's size and mtime. Empty when
    the store is absent, in which case callers accept a well-formed name rather than refuse everyone."""
    from src.hounds.user_rules import fold_player
    path = os.path.join(root or _root(), "data", "processed", "boxscores_2026.jsonl")
    try:
        stat = os.stat(path)
    except OSError:
        return frozenset()
    stamp = (path, stat.st_size, stat.st_mtime_ns)
    hit = _known_cache.get("v")
    if hit and hit[0] == stamp:
        return hit[1]
    names = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if '"player_name"' not in line:
                continue
            try:
                name = json.loads(line).get("player_name")
            except ValueError:
                continue
            if isinstance(name, str):
                key = fold_player(name)
                if key:
                    names.add(key)
    result = frozenset(names)
    _known_cache["v"] = (stamp, result)
    return result
