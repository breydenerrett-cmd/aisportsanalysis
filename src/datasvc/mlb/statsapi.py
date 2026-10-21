"""MLB statsapi box scores and player game logs, forward only, with the sealed window enforced.

Source: statsapi.mlb.com (unofficial, no key). TERMS: MLBAM's notice (http://gdx.mlb.com/components/copyright.txt,
printed in every response) permits only individual, non-commercial, non-bulk use and requires written
authorization for anything else. The project already depends on the statsapi schedule; this layer adds one
schedule request per day and one box-score request per finished game (about 15-30 requests a day in season)
and stays internal. Treat it as a risk to settle with the owner before it backs a paid surface.

WHAT IS FETCHED. For each open day from `FORWARD_FROM` on: `schedule?sportId=1&date=D&hydrate=linescore,decisions`
(games, scores, innings, winning/losing pitcher) and, for each game that finished, `game/<pk>/boxscore` (team
totals and every player's line for THAT game). The box score is the player game log: a player's log is his
lines across the games stored, so the season-wide `people/<id>/stats?stats=gameLog` endpoint (it returns every
game of the season, sealed ones included) is never called. See `seal.py`.

WHAT IS STORED (data/datasvc/mlb/, versioned and append-only like the ESPN layers; rows carry observed_utc):
  games_<season>         game_id (gamePk), date, date_utc, state, completed, scores, innings, per-inning runs ...
  team_games_<season>    game_id, team_id: `stats` {"bat.hits": 7, "pit.earnedRuns": 3, "fld.errors": 0 ...}
  player_games_<season>  game_id, player_id: `stats` {"batting": {...}, "pitching": {...}, "fielding": {...}}
  teams                  team_id, abbreviation, names (static)
Only integer counting stats of the game itself are kept. Rate fields (avg, era, whip ...) and everything under
`seasonStats` are season-to-date and include sealed games, so they are dropped, as are team records and decision
notes. Innings pitched is kept as `outs` (6.1 IP = 19), because "6.1" averages wrongly as a decimal.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from src import paths
from src.datasvc.espn import leagues as lg
from src.datasvc.espn.pipeline import SETTLE, Runner, _Stop, _changed, _finish, _iso, _new_summary, _parse_iso
from src.datasvc.espn.store import EspnStore, utc_now
from src.datasvc.http import PoliteFetcher
from src.datasvc.mlb import seal
from src.datasvc.mlb.seal import SealedWindowError

SITE = "https://statsapi.mlb.com/api/v1/"
ATTRIBUTION = ("Schedules, scores, box scores and player game lines: MLB Advanced Media statsapi "
               "(statsapi.mlb.com), observed by LineHound. Individual, non-commercial use per MLBAM's notice; "
               "internal analysis only.")

#: the league object the shared pipeline machinery needs; not in the ESPN registry (it is not ESPN-fed)
LEAGUE = lg.League("mlb", "baseball/mlb", "MLB (statsapi box scores)", "baseball", injuries=False, pbp=False)

_GAME_TYPE_SEASON = {"R": 2, "F": 3, "D": 3, "L": 3, "W": 3, "P": 3, "S": 1, "E": 1, "A": 1}
_DROP_INT_KEYS = frozenset({"gamesPlayed"})
_STATE = {"Preview": "pre", "Live": "in", "Final": "post"}


class MlbBoxStore(EspnStore):
    """Same versioned store as the ESPN layers, MLB datasets, and a sealed-window guard on write and read."""

    datasets = {"teams": (("team_id",), False),
                "games": (("game_id",), True),
                "team_games": (("game_id", "team_id"), True),
                "player_games": (("game_id", "player_id"), True)}
    default_dir = paths.data_path("datasvc")          # league dir = data/datasvc/mlb
    attribution = ATTRIBUTION

    def append(self, league: str, dataset: str, rows: Iterable[dict]) -> dict:
        rows = list(rows)
        for r in rows:
            for field in ("date", "date_utc"):
                if r.get(field):
                    seal.assert_open(r[field], f"{dataset} row {r.get('game_id', '')} {field}")
        return super().append(league, dataset, rows)

    def versions(self, league: str, dataset: str, season=None) -> List[dict]:
        rows = super().versions(league, dataset, season)
        return seal.drop_sealed(rows) if dataset != "teams" else rows


# -- parsers (pure) ---------------------------------------------------------------------------------------------

def _s(value) -> Optional[str]:
    return None if value in (None, "") else str(value)


def _put(row: dict, **fields) -> dict:
    row.update({k: v for k, v in fields.items() if v is not None})
    return row


def _ts(text) -> Optional[str]:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2}))?", str(text or ""))
    return f"{m.group(1)}T{m.group(2)}:{m.group(3) or '00'}Z" if m else None


def _ints(stats: dict) -> Dict[str, int]:
    """Integer-valued fields only: counting stats of the game. Strings are rates, notes and summaries."""
    return {k: v for k, v in (stats or {}).items()
            if isinstance(v, int) and not isinstance(v, bool) and k not in _DROP_INT_KEYS}


def _outs(ip) -> Optional[int]:
    """'6.1' innings pitched -> 19 outs."""
    m = re.match(r"^(\d+)(?:\.([012]))?$", str(ip or ""))
    return int(m.group(1)) * 3 + int(m.group(2) or 0) if m else None


def teams(payload: dict, observed_utc: str) -> List[dict]:
    out = []
    for t in payload.get("teams") or []:
        if not t.get("id") or (t.get("sport") or {}).get("id") not in (None, 1):
            continue
        out.append(_put({"league": "mlb", "team_id": str(t["id"]), "observed_utc": observed_utc},
                        abbreviation=_s(t.get("abbreviation")), name=_s(t.get("teamName")),
                        display_name=_s(t.get("name")), short_name=_s(t.get("shortName")),
                        location=_s(t.get("locationName")), club_name=_s(t.get("clubName")),
                        is_active=t.get("active"), league_id=(t.get("league") or {}).get("id"),
                        division=_s((t.get("division") or {}).get("name"))))
    return out


def schedule(payload: dict, observed_utc: str) -> List[dict]:
    """One row per game of the days in `payload`. Cumulative fields (team records) are not read. A game dated
    inside the sealed window raises SealedWindowError."""
    out = []
    for d in payload.get("dates") or []:
        for g in d.get("games") or []:
            day = _s(g.get("officialDate")) or _s(d.get("date"))
            seal.assert_open(day, f"game {g.get('gamePk')}")
            seal.assert_open(_s(g.get("gameDate")), f"game {g.get('gamePk')} gameDate")
            teams_ = g.get("teams") or {}
            home, away = teams_.get("home") or {}, teams_.get("away") or {}
            ht, at = home.get("team") or {}, away.get("team") or {}
            if not g.get("gamePk") or not ht.get("id") or not at.get("id"):
                continue
            status = g.get("status") or {}
            abstract = status.get("abstractGameState")
            state = _STATE.get(abstract, "unknown")
            completed = state == "post" and status.get("codedGameState") in ("F", "O", "FT", "FR", "FG")
            line = g.get("linescore") or {}
            innings = line.get("innings") or []
            started = state in ("in", "post")
            row = {"league": "mlb", "game_id": str(g["gamePk"]), "observed_utc": observed_utc, "date": day,
                   "date_utc": _ts(g.get("gameDate")), "scoreboard_date": day, "state": state,
                   "completed": bool(completed),
                   "status": _s(status.get("detailedState")), "home_id": str(ht["id"]), "away_id": str(at["id"])}
            _put(row, season=int(g["season"]) if str(g.get("season", "")).isdigit() else None,
                 season_type=_GAME_TYPE_SEASON.get(g.get("gameType")), game_type=_s(g.get("gameType")),
                 home_name=_s(ht.get("name")), away_name=_s(at.get("name")),
                 home_score=home.get("score") if started else None, away_score=away.get("score") if started else None,
                 home_winner=home.get("isWinner") if completed else None,
                 away_winner=away.get("isWinner") if completed else None,
                 venue=_s((g.get("venue") or {}).get("name")), venue_id=(g.get("venue") or {}).get("id"),
                 day_night=_s(g.get("dayNight")), double_header=_s(g.get("doubleHeader")),
                 game_number=g.get("gameNumber"), scheduled_innings=g.get("scheduledInnings"),
                 series_description=_s(g.get("seriesDescription")), description=_s(g.get("description")),
                 period=line.get("currentInning") if started else None)
            if innings and started:
                row["home_line"] = [(i.get("home") or {}).get("runs") for i in innings]
                row["away_line"] = [(i.get("away") or {}).get("runs") for i in innings]
                lt = line.get("teams") or {}
                _put(row, home_hits=(lt.get("home") or {}).get("hits"), away_hits=(lt.get("away") or {}).get("hits"),
                     home_errors=(lt.get("home") or {}).get("errors"), away_errors=(lt.get("away") or {}).get("errors"))
            dec = g.get("decisions") or {}
            if completed and dec:
                _put(row, winning_pitcher_id=_s((dec.get("winner") or {}).get("id")),
                     losing_pitcher_id=_s((dec.get("loser") or {}).get("id")),
                     save_pitcher_id=_s((dec.get("save") or {}).get("id")))
            out.append(row)
    return out


def team_games(box: dict, game: dict, observed_utc: str) -> List[dict]:
    """One row per side: team batting, pitching and fielding totals of THIS game, prefixed bat./pit./fld."""
    out = []
    for side in ("home", "away"):
        t = (box.get("teams") or {}).get(side) or {}
        tid = _s((t.get("team") or {}).get("id"))
        if not tid:
            continue
        ts = t.get("teamStats") or {}
        stats: Dict[str, int] = {}
        for prefix, group in (("bat", "batting"), ("pit", "pitching"), ("fld", "fielding")):
            for k, v in _ints(ts.get(group)).items():
                stats[f"{prefix}.{k}"] = v
        outs = _outs((ts.get("pitching") or {}).get("inningsPitched"))
        if outs is not None:
            stats["pit.outs"] = outs
        is_home = side == "home"
        out.append(_put({"league": "mlb", "game_id": game["game_id"], "team_id": tid, "observed_utc": observed_utc,
                         "date_utc": game.get("date_utc"), "date": game.get("date"), "stats": stats,
                         "home_away": side},
                        season=game.get("season"),
                        opponent_id=game.get("away_id") if is_home else game.get("home_id"),
                        points=game.get("home_score") if is_home else game.get("away_score"),
                        points_against=game.get("away_score") if is_home else game.get("home_score")))
    return out


def player_games(box: dict, game: dict, observed_utc: str) -> List[dict]:
    """One row per player who has a line in the game: `stats` {batting|pitching|fielding: {key: int}}.
    `seasonStats`, notes and rate strings are never read."""
    out = []
    for side in ("home", "away"):
        t = (box.get("teams") or {}).get(side) or {}
        tid = _s((t.get("team") or {}).get("id"))
        for key, p in (t.get("players") or {}).items():
            person = p.get("person") or {}
            pid = _s(person.get("id"))
            if not tid or not pid:
                continue
            st = p.get("stats") or {}
            groups = {}
            for name in ("batting", "pitching", "fielding"):
                vals = _ints(st.get(name))
                if name == "pitching" and vals:
                    outs = _outs((st.get("pitching") or {}).get("inningsPitched"))
                    if outs is not None:
                        vals["outs"] = outs
                if name == "fielding":
                    vals = {k: v for k, v in vals.items() if k in ("assists", "putOuts", "errors", "chances", "gamesStarted")}
                if vals:
                    groups[name] = vals
            if not groups or not (groups.get("batting") or groups.get("pitching")):
                continue                       # on the roster, no plate appearance and no pitch: no line
            order = _s(p.get("battingOrder"))
            started = (order is not None and order.endswith("00")) or (groups.get("pitching") or {}).get("gamesStarted") == 1
            out.append(_put({"league": "mlb", "game_id": game["game_id"], "player_id": pid, "team_id": tid,
                             "observed_utc": observed_utc, "date_utc": game.get("date_utc"), "date": game.get("date"),
                             "stats": groups, "starter": bool(started)},
                            season=game.get("season"), player_name=_s(person.get("fullName")),
                            position=_s((p.get("position") or {}).get("abbreviation")),
                            batting_order=_s(order), jersey=_s(p.get("jerseyNumber"))))
    return out


# -- the guarded fetcher -------------------------------------------------------------------------------------------

class SealedFetcher:
    """A PoliteFetcher that refuses every URL the sealed-window guard does not allow, before any request."""

    def __init__(self, fetcher: PoliteFetcher):
        self._f = fetcher
        self.listed: Set[str] = set()

    @property
    def stats(self):
        return self._f.stats

    def get_json(self, url: str, **kw):
        seal.check_url(url, self.listed)
        return self._f.get_json(url, **kw)

    def get_text(self, url: str, **kw):
        seal.check_url(url, self.listed)
        return self._f.get_text(url, **kw)

    def fetched_utc(self, url: str):
        return self._f.fetched_utc(url)


# -- the runner ----------------------------------------------------------------------------------------------------

class MlbRunner(Runner):
    def __init__(self, *, store: MlbBoxStore, fetcher: SealedFetcher, now: Optional[Callable[[], datetime]] = None):
        super().__init__(LEAGUE, store=store, fetcher=fetcher, now=now)
        self.guard: SealedFetcher = fetcher
        self.listed_dates: Dict[str, str] = {}

    def teams_(self, summary: dict, *, force: bool = False) -> None:
        newest = max((r["observed_utc"] for r in self.store.versions("mlb", "teams")), default=None)
        if not force and newest and _parse_iso(newest) and self._now() - _parse_iso(newest) < timedelta(days=30):
            return
        payload = self._get(f"{SITE}teams?sportId=1", summary, live=True)
        if payload:
            rows = teams(payload, self.last_observed)
            summary["teams"] += _changed(self.store.append("mlb", "teams", rows))

    def schedule_day(self, day: date, summary: dict) -> List[dict]:
        seal.assert_open(day, "schedule day")
        url = f"{SITE}schedule?sportId=1&date={day.isoformat()}&hydrate=linescore,decisions"
        now = self._now()
        settled = datetime(day.year, day.month, day.day) + timedelta(days=2)
        payload = self._get(url, summary, settled_at=settled, live=now < settled)
        if payload is None:
            return []
        observed = self.fetcher.fetched_utc(url) or self.stamp()
        rows = schedule(payload, observed)
        for r in rows:
            self.guard.listed.add(r["game_id"])
        summary["scoreboards"] += 1
        summary["games"] += _changed(self.store.append("mlb", "games", rows))
        return rows

    def box_scores_(self, game_rows: Iterable[dict], summary: dict) -> None:
        now = self._now()
        have = {k[0]: v["observed_utc"] for k, v in self.store.latest("mlb", "team_games").items()}
        for g in game_rows:
            if not (g.get("completed") and g.get("state") == "post"):
                continue
            seal.assert_open(g.get("date"), f"box score of game {g['game_id']}")
            date_utc = _parse_iso(g.get("date_utc")) or now
            settled = date_utc + SETTLE
            first = have.get(g["game_id"])
            if first is not None and (first >= _iso(settled) or now < settled):
                continue
            url = f"{SITE}game/{g['game_id']}/boxscore"
            payload = self._get(url, summary, settled_at=settled if now >= settled else None)
            if payload is None:
                continue
            observed = self.fetcher.fetched_utc(url) or self.stamp()
            tg = team_games(payload, g, observed)
            if not tg:
                continue
            summary["box_scores"] += 1
            summary["team_games"] += _changed(self.store.append("mlb", "team_games", tg))
            summary["player_games"] += _changed(self.store.append("mlb", "player_games", player_games(payload, g, observed)))


def refresh(*, store: Optional[MlbBoxStore] = None, fetcher: Optional[PoliteFetcher] = None,
            today: Optional[date] = None, days_back: int = 1, days_ahead: int = 1,
            floor: date = seal.FORWARD_FROM, min_age_minutes: float = 0, force: bool = False,
            now: Optional[Callable[[], datetime]] = None) -> dict:
    """Schedules for [today - days_back, today + days_ahead] and box scores for what finished. Days before `floor`
    (default `FORWARD_FROM`, the brief's "forward from today only") are skipped; days inside the sealed window are
    skipped whatever `floor` is, and the guard refuses them again at the fetch."""
    store = store or MlbBoxStore()
    guard = SealedFetcher(fetcher or PoliteFetcher())
    runner = MlbRunner(store=store, fetcher=guard, now=now)
    summary = _new_summary("refresh", "mlb", utc_now())
    summary.update(skipped_sealed=[], skipped_before_floor=[])
    manifest = store.read_manifest("mlb") or {}
    last = _parse_iso(manifest.get("refreshed_utc"))
    if not force and min_age_minutes and last and runner._now() - last < timedelta(minutes=min_age_minutes):
        summary["skipped"] = f"refreshed {manifest['refreshed_utc']} (< {min_age_minutes:g} min ago)"
        return summary
    today = today or runner._now().date()
    try:
        runner.teams_(summary)
        game_rows: List[dict] = []
        for offset in range(-days_back, days_ahead + 1):
            day = today + timedelta(days=offset)
            if seal.is_sealed(day):
                summary["skipped_sealed"].append(day.isoformat())
                continue
            if day < floor:
                summary["skipped_before_floor"].append(day.isoformat())
                continue
            game_rows.extend(runner.schedule_day(day, summary))
        runner.box_scores_(game_rows, summary)
    except _Stop:
        pass
    except (SealedWindowError, seal.UnsupportedUrl) as exc:
        summary["stopped"] = f"sealed window guard: {exc}"
    return _finish(runner, summary, store)


def status(store: Optional[MlbBoxStore] = None) -> dict:
    store = store or MlbBoxStore()
    m = store.read_manifest("mlb")
    if not m:
        return {}
    return {"refreshed_utc": m.get("refreshed_utc"), "generated_utc": m.get("generated_utc"),
            "files": {n: f.get("records") for n, f in sorted((m.get("files") or {}).items())}}


def check(store: Optional[MlbBoxStore] = None) -> dict:
    """Parity on disk: every box-score row resolves to a game, a final game with a box has two team rows, no
    stored row is dated inside the sealed window."""
    store = store or MlbBoxStore()
    problems: List[str] = []
    games = store.latest("mlb", "games")
    gids = {k[0] for k in games}
    per_game: Dict[str, int] = {}
    for (gid, _t) in store.latest("mlb", "team_games"):
        per_game[gid] = per_game.get(gid, 0) + 1
        if gid not in gids:
            problems.append(f"team_games row for unknown game {gid}")
    for gid, n in per_game.items():
        if n != 2:
            problems.append(f"game {gid} has {n} team_games rows")
    for (gid, _p) in store.latest("mlb", "player_games"):
        if gid not in gids:
            problems.append(f"player_games row for unknown game {gid}")
    raw = EspnStore.versions
    for ds in ("games", "team_games", "player_games"):
        for r in raw(store, "mlb", ds):
            if seal.is_sealed(r.get("date")) or seal.is_sealed(r.get("date_utc")):
                problems.append(f"{ds} row {r.get('game_id')} is dated inside the sealed window")
    return {"ok": not problems, "problems": problems[:50]}
