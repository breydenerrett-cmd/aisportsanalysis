"""Refresh and backfill: ESPN's public JSON, read politely, into the append-only EspnStore.

    refresh   teams (weekly), scoreboards for a window around today, box scores for games that went final,
              standings and injuries (snapshots), rosters (weekly), then the manifest. Gated by the
              manifest's `refreshed_utc` so the 15-minute capture slot can call it every time and it
              does network work only every `min_age_minutes`.
    backfill  scoreboards day by day over a date range, and the box scores they reveal.

Point-in-time: every row is stamped with the instant WE fetched it (`observed_utc`). A scoreboard cached
while games were live is never reused once the day is over (`_usable_cache`), and a box score taken within
a day of the game is fetched once more after that day, because stat corrections land overnight.

A browser check or a request cap stops the whole run; a failed single page is recorded and skipped.
Nothing here tries to pass a block (src/datasvc/http.py raises SourceBlocked and we stop).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional

from src.datasvc.espn import leagues as lg, parse
from src.datasvc.espn.store import EspnStore, utc_now
from src.datasvc.http import FetchError, NotFound, PoliteFetcher, RequestCapReached, SourceBlocked

LIVE_MAX_AGE_S = 600.0
ROSTER_REFRESH_DAYS = 7
TEAMS_REFRESH_DAYS = 7
SETTLE = timedelta(days=1)     # box scores and scoreboards are final-ish this long after the game


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def _new_summary(kind: str, league: str, now: str) -> dict:
    return {"kind": kind, "league": league, "started_utc": now, "requests": 0, "scoreboards": 0, "games": 0,
            "box_scores": 0, "team_games": 0, "player_games": 0, "standings": 0, "injuries": 0, "teams": 0,
            "players": 0, "skipped": None, "errors": [], "stopped": None}


def _err(summary: dict, where: str, exc: Exception) -> None:
    if len(summary["errors"]) < 100:
        summary["errors"].append(f"{where}: {exc}")


def _changed(c: dict) -> int:
    return c["added"] + c["versioned"]


class _Stop(Exception):
    pass


class Runner:
    def __init__(self, league: lg.League, *, store: EspnStore, fetcher: PoliteFetcher,
                 now: Optional[Callable[[], datetime]] = None):
        self.league, self.store, self.fetcher = league, store, fetcher
        self.last_observed = _iso(datetime.now(timezone.utc).replace(tzinfo=None))
        self._now = now or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def stamp(self) -> str:
        """The observation time for rows built from a page fetched right now."""
        return _iso(self._now())

    # -- fetching ----------------------------------------------------------------------------------------

    def _usable_cache(self, url: str, settled_at: Optional[datetime]) -> bool:
        """A cached page is reusable when it was fetched at/after the moment its subject settled."""
        got = _parse_iso(self.fetcher.fetched_utc(url))
        if got is None:
            return False
        return settled_at is None or got >= settled_at

    def _get(self, url: str, summary: dict, *, settled_at: Optional[datetime] = None, live: bool = False):
        """JSON for `url` or None when it is missing; raises _Stop on a block or the request cap."""
        try:
            if live:
                got = self.fetcher.get_json(url, max_age_s=LIVE_MAX_AGE_S)
            else:
                got = self.fetcher.get_json(url, use_cache=self._usable_cache(url, settled_at))
            self.last_observed = self.fetcher.fetched_utc(url) or self.stamp()
            return got
        except NotFound:
            return None
        except SourceBlocked as exc:
            summary["stopped"] = f"source blocked: {exc}"
            raise _Stop() from None
        except RequestCapReached as exc:
            summary["stopped"] = f"request cap: {exc}"
            raise _Stop() from None
        except FetchError as exc:
            _err(summary, url, exc)
            return None

    def _scoreboard_url(self, day: date) -> str:
        L = self.league
        url = f"{lg.SITE}{L.path}/scoreboard?dates={day.strftime('%Y%m%d')}&limit={L.limit}"
        return url + (f"&groups={L.groups}" if L.groups else "")

    # -- datasets ----------------------------------------------------------------------------------------

    def scoreboard(self, day: date, summary: dict) -> List[dict]:
        url = self._scoreboard_url(day)
        now = self._now()
        settled = datetime(day.year, day.month, day.day) + timedelta(days=2)
        recent = now < settled
        payload = self._get(url, summary, settled_at=settled, live=recent)
        if payload is None:
            return []
        observed = self.fetcher.fetched_utc(url) or self.stamp()
        rows = parse.games(payload, self.league.code, observed, day.isoformat())
        summary["scoreboards"] += 1
        summary["games"] += _changed(self.store.append(self.league.code, "games", rows))
        return rows

    def box_scores(self, game_rows: Iterable[dict], summary: dict) -> None:
        L, now = self.league, self._now()
        have = {k[0]: v["observed_utc"] for k, v in self.store.latest(L.code, "team_games").items()}
        for g in game_rows:
            if not (g.get("completed") and g["state"] == "post"):
                continue
            date_utc = _parse_iso(g.get("date_utc")) or now
            settled = date_utc + SETTLE
            first = have.get(g["game_id"])
            if first is not None and (first >= _iso(settled) or now < settled):
                continue                 # already have a settled copy (or too early to improve on it)
            url = f"{lg.SITE}{L.path}/summary?event={g['game_id']}"
            payload = self._get(url, summary, settled_at=settled if now >= settled else None)
            if payload is None:
                continue
            observed = self.fetcher.fetched_utc(url) or self.stamp()
            tg = parse.team_games(payload, g, observed)
            if not tg:
                continue
            summary["box_scores"] += 1
            summary["team_games"] += _changed(self.store.append(L.code, "team_games", tg))
            if L.players:
                summary["player_games"] += _changed(
                    self.store.append(L.code, "player_games", parse.player_games(payload, g, observed)))

    def teams(self, summary: dict, *, force: bool = False) -> None:
        L = self.league
        newest = max((r["observed_utc"] for r in self.store.versions(L.code, "teams")), default=None)
        if not force and newest and _parse_iso(newest) and self._now() - _parse_iso(newest) < timedelta(days=TEAMS_REFRESH_DAYS):
            return
        payload = self._get(f"{lg.SITE}{L.path}/teams?limit={L.teams_limit}", summary, live=True)
        if payload:
            rows = parse.teams(payload, L.code, self.last_observed)
            summary["teams"] += _changed(self.store.append(L.code, "teams", rows))

    def standings(self, summary: dict) -> None:
        L = self.league
        payload = self._get(f"{lg.V2}{L.path}/standings", summary, live=True)
        if payload:
            rows = parse.standings(payload, L.code, self.last_observed)
            summary["standings"] += _changed(self.store.append(L.code, "standings", rows))

    def injuries(self, summary: dict) -> None:
        L = self.league
        if not L.injuries:
            return
        payload = self._get(f"{lg.SITE}{L.path}/injuries", summary, live=True)
        if not payload:
            return
        observed = self.last_observed
        rows = parse.injuries(payload, L.code, observed)
        teams_in_feed = {str(g.get("id")) for g in payload.get("injuries") or [] if g.get("id")}
        if rows:
            # a player who left the report is recorded as Cleared, so history shows when he did
            now_keys = {(r["team_id"], r["player_id"]) for r in rows}
            for (tid, pid), old in self.store.latest(L.code, "injuries").items():
                if tid in teams_in_feed and (tid, pid) not in now_keys and old.get("status") != "Cleared":
                    rows.append({"league": L.code, "team_id": tid, "player_id": pid, "observed_utc": observed,
                                 "status": "Cleared", **({"player_name": old["player_name"]} if old.get("player_name") else {})})
        summary["injuries"] += _changed(self.store.append(L.code, "injuries", rows))

    def rosters(self, summary: dict, *, force: bool = False) -> None:
        L = self.league
        if not L.players:
            return
        newest = max((r["observed_utc"] for r in self.store.versions(L.code, "players")), default=None)
        if not force and newest and _parse_iso(newest) and self._now() - _parse_iso(newest) < timedelta(days=ROSTER_REFRESH_DAYS):
            return
        for (tid,), team in sorted(self.store.latest(L.code, "teams").items()):
            if team.get("is_active") is False:
                continue
            payload = self._get(f"{lg.SITE}{L.path}/teams/{tid}/roster", summary, live=True)
            if payload:
                rows = parse.roster(payload, L.code, tid, self.last_observed)
                summary["players"] += _changed(self.store.append(L.code, "players", rows))


# -- entry points -----------------------------------------------------------------------------------------------

def _finish(runner: Runner, summary: dict, store: EspnStore, *, touched_manifest: bool = True) -> dict:
    summary["requests"] = runner.fetcher.stats["requests"]
    summary["finished_utc"] = runner.stamp()
    extra = {"title": runner.league.title}
    if summary["kind"] == "refresh" and not summary["stopped"]:
        extra["refreshed_utc"] = summary["finished_utc"]
    elif store.read_manifest(runner.league.code):
        extra["refreshed_utc"] = store.read_manifest(runner.league.code).get("refreshed_utc")
    if touched_manifest and store.league_dir(runner.league.code).exists():
        store.write_manifest(runner.league.code, extra={k: v for k, v in extra.items() if v})
    return summary


def refresh(code: str, *, store: Optional[EspnStore] = None, fetcher: Optional[PoliteFetcher] = None,
            today: Optional[date] = None, days_back: int = 2, days_ahead: int = 2,
            min_age_minutes: float = 0, force: bool = False, rosters: Optional[bool] = None,
            now: Optional[Callable[[], datetime]] = None) -> dict:
    L = lg.get(code)
    store = store or EspnStore()
    fetcher = fetcher or PoliteFetcher()
    runner = Runner(L, store=store, fetcher=fetcher, now=now)
    summary = _new_summary("refresh", L.code, utc_now())
    manifest = store.read_manifest(L.code) or {}
    last = _parse_iso(manifest.get("refreshed_utc"))
    if not force and min_age_minutes and last and runner._now() - last < timedelta(minutes=min_age_minutes):
        summary["skipped"] = f"refreshed {manifest['refreshed_utc']} (< {min_age_minutes:g} min ago)"
        return summary
    today = today or runner._now().date()
    try:
        runner.teams(summary)
        game_rows: List[dict] = []
        for offset in range(-days_back, days_ahead + 1):
            game_rows.extend(runner.scoreboard(today + timedelta(days=offset), summary))
        runner.box_scores(game_rows, summary)
        runner.standings(summary)
        runner.injuries(summary)
        if rosters is None or rosters:
            runner.rosters(summary, force=bool(rosters))
    except _Stop:
        pass
    return _finish(runner, summary, store)


def backfill(code: str, start: date, end: date, *, store: Optional[EspnStore] = None,
             fetcher: Optional[PoliteFetcher] = None, box: bool = True,
             now: Optional[Callable[[], datetime]] = None) -> dict:
    L = lg.get(code)
    store = store or EspnStore()
    fetcher = fetcher or PoliteFetcher()
    runner = Runner(L, store=store, fetcher=fetcher, now=now)
    summary = _new_summary("backfill", L.code, utc_now())
    try:
        runner.teams(summary)
        day = start
        while day <= end:
            rows = runner.scoreboard(day, summary)
            if box:
                runner.box_scores(rows, summary)
            day += timedelta(days=1)
    except _Stop:
        pass
    return _finish(runner, summary, store)


def status(store: Optional[EspnStore] = None, codes: Optional[Iterable[str]] = None) -> dict:
    """Record counts and freshness per league, from the manifests (no network)."""
    store = store or EspnStore()
    out: Dict[str, dict] = {}
    for code in codes or sorted(lg.LEAGUES):
        manifest = store.read_manifest(code)
        if not manifest:
            continue
        out[code] = {"refreshed_utc": manifest.get("refreshed_utc"), "generated_utc": manifest.get("generated_utc"),
                     "files": {n: f.get("records") for n, f in sorted((manifest.get("files") or {}).items())}}
    return out


def check(store: Optional[EspnStore] = None, codes: Optional[Iterable[str]] = None) -> dict:
    """Parity over what is on disk (no network): every box-score row resolves to a game, and every game
    that is final with box scores has both teams' rows."""
    store = store or EspnStore()
    problems: List[str] = []
    for code in codes or sorted(lg.LEAGUES):
        if not store.league_dir(code).exists():
            continue
        games = store.latest(code, "games")
        gids = {k[0] for k in games}
        tg = store.latest(code, "team_games")
        per_game: Dict[str, int] = {}
        for (gid, _tid) in tg:
            per_game[gid] = per_game.get(gid, 0) + 1
            if gid not in gids:
                problems.append(f"{code}: team_games row for unknown game {gid}")
        for gid, n in per_game.items():
            if n != 2:
                problems.append(f"{code}: game {gid} has {n} team_games rows")
        for (gid, pid), r in store.latest(code, "player_games").items():
            if gid not in gids:
                problems.append(f"{code}: player_games row for unknown game {gid}")
    return {"ok": not problems, "problems": problems[:50]}
