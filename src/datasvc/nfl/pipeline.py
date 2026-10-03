"""The NFL backfill and the daily update: the nflverse files, read in order, into the store.

    backfill   the schedule once (every season in one file), then for each season, newest
               first: the team statistics (building `team_games`), the player statistics and
               the injury reports.
    update     the same for the current season only, and the schedule: the weeks that have
               been played since the last run arrive as changed rows; nothing else is written.

Both are idempotent. A row whose content is unchanged is not rewritten (`NflStore.upsert`),
so a second run in a row changes no file, and a daily run changes only what is new. Progress
is saved after every season, so a run that stops (a request cap, a network failure, a browser
check) keeps everything it finished and the fetcher's cache makes the next run skip what it
already has. A browser check stops the whole run at once: nothing here works around it.

`check` is the parity report over what is on disk (no network): row counts that must agree,
every foreign key that must resolve, every played game that must have its statistics.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from typing import Callable, Iterable, List, Optional

from src.datasvc import store as jsonl
from src.datasvc.http import FetchError, PoliteFetcher, RequestCapReached, SourceBlocked
from src.datasvc.nfl import sources, timeutil
from src.datasvc.nfl.store import FILES, NflStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_season(today: Optional[date] = None) -> int:
    """The NFL season in progress on `today` (March to February, named for the year it starts)."""
    return timeutil.season_of(today or datetime.now(timezone.utc).date())


def _new_summary(kind: str) -> dict:
    return {"kind": kind, "started_utc": _now_iso(), "seasons": [], "games": 0, "team_games": 0,
            "player_games": 0, "injuries": 0, "missing_files": [], "per_season": {},
            "errors": [], "stopped": None}


def _record_error(summary: dict, where: str, exc: Exception) -> None:
    if len(summary["errors"]) < 200:
        summary["errors"].append(f"{where}: {exc}")


def _changed(counts: dict) -> int:
    """Rows an upsert wrote: new plus changed."""
    return counts["added"] + counts["updated"]


# -- the schedule -----------------------------------------------------------------------------

def _refresh_games(fetcher, store: NflStore, seasons: Iterable[int], summary: dict, *, log) -> bool:
    """Fetch games.csv, upsert the given seasons' games, mark vanished unplayed games `removed`.

    Returns False when the file could not be had (it is the one file everything else joins to).
    """
    text, fetched = sources.fetch_csv(fetcher, sources.games_url(), live=True)
    if text is None:
        summary["missing_files"].append(sources.games_url())
        log("the schedule file answered 404; nothing can be joined without it")
        return False
    fetched = fetched or _now_iso()
    wanted = {int(s) for s in seasons}
    rows = sources.read_csv(text)
    if not rows or "game_id" not in rows[0] or "gameday" not in rows[0]:
        # an error page, an empty body, a different file: nothing here may be trusted, least of all to
        # decide that stored games have vanished
        _record_error(summary, "schedule", FetchError(sources.games_url(), 200, "the file is not a schedule (no game_id and gameday columns)"))
        log("the schedule file did not look like a schedule; nothing was changed")
        return False
    games, info = sources.parse_games(rows, fetched_utc=fetched, seasons=wanted)
    counts = store.upsert("games", games)
    summary["games"] += _changed(counts)
    summary["schedule"] = {"rows_read": info["rows"], "games_in_seasons": info["games"],
                           "skipped_rows": info["skipped_rows"], "venue_check": info["venue_check"]}
    fresh = {g["game_id"] for g in games}
    vanished = [g for g in store.games if g["season"] in wanted and g["game_id"] not in fresh
                and g.get("status") not in ("final", "removed")]
    if vanished and info["skipped_rows"]:
        # a stored game may be among the rows that could not be read: do not call it removed on that evidence
        summary["schedule"]["removal_skipped"] = (f"{info['skipped_rows']} schedule row(s) could not be read, "
                                                  f"so {len(vanished)} stored game(s) absent from the file were left alone")
        log(summary["schedule"]["removal_skipped"])
        vanished = []
    if vanished:
        store.upsert("games", [dict(g, status="removed", fetched_utc=fetched) for g in vanished])
        rows = store.team_game_by_key()
        store.upsert("team_games", [dict(rows[(g["game_id"], t)], status="removed", fetched_utc=fetched)
                                    for g in vanished for t in (g["home_team"], g["away_team"])
                                    if (g["game_id"], t) in rows])
        summary["schedule"]["removed"] = sorted(g["game_id"] for g in vanished)
        log(f"{len(vanished)} stored game(s) are no longer in the schedule: marked removed")
    log(f"games: {info['games']} in {sorted(wanted)} ({counts['added']} new, {counts['updated']} changed)")
    return True


# -- one season -------------------------------------------------------------------------------

def _ingest_season(fetcher, store: NflStore, season: int, current: int, summary: dict, *, log,
                   player_since: Optional[int] = None) -> None:
    live = sources.is_live(season, current)
    season_games = [g for g in store.games if g["season"] == season]
    per = summary["per_season"].setdefault(str(season), {})
    if not season_games:
        per["note"] = "no games in the schedule for this season; nothing fetched"
        log(f"{season}: no games in the schedule, skipped")
        return
    game_ids = {g["game_id"] for g in season_games}

    # team statistics -> team_games (rows exist for every game, statistics or not)
    url = sources.team_stats_url(season)
    text, fetched = sources.fetch_csv(fetcher, url, live=live)
    stats, source = {}, None
    if text is None:
        summary["missing_files"].append(url)
    else:
        stats, info = sources.parse_team_stats(sources.read_csv(text))
        source = sources.team_stats_source(season)
        per["team_stats_rows"] = info["rows"]
        per["team_stats_unmatched"] = sorted({g for g, _ in stats if g not in game_ids})[:20]
    rows = sources.build_team_games(season_games, stats, fetched_utc=fetched or _now_iso(), stats_source=source)
    # Never downgrade: a statistics file that is missing for a moment (nflverse replaces its release assets), empty
    # or partial must not null out statistics the store already holds.
    held = store.team_game_by_key()
    kept_back = [r for r in rows if not r["has_stats"] and held.get((r["game_id"], r["team"]), {}).get("has_stats")]
    if kept_back:
        per["team_rows_kept_with_their_stored_statistics"] = len(kept_back)
        rows = [r for r in rows if r["has_stats"] or not held.get((r["game_id"], r["team"]), {}).get("has_stats")]
    counts = store.upsert("team_games", rows)
    summary["team_games"] += _changed(counts)
    per["team_games"] = len(rows)
    log(f"{season} team games: {len(rows)} rows, {counts['added']} new, {counts['updated']} changed")

    # player statistics -> player_games (the largest file: optionally only from `player_since`)
    url = sources.player_stats_url(season)
    if player_since is not None and season < player_since:
        per["player_stats"] = {"skipped": f"before player_since {player_since}"}
        text, fetched = None, None
        log(f"{season} player games: skipped (before {player_since})")
    else:
        text, fetched = sources.fetch_csv(fetcher, url, live=live)
        if text is None:
            summary["missing_files"].append(url)
    if text is not None:
        records, info = sources.parse_player_stats(
            sources.read_csv(text), {g["game_id"]: g for g in season_games},
            fetched_utc=fetched or _now_iso(), source=sources.player_stats_source(season))
        counts = store.upsert("player_games", records)
        summary["player_games"] += _changed(counts)
        per["player_stats"] = info
        log(f"{season} player games: {info['kept']} kept of {info['rows']} rows, "
            f"{counts['added']} new, {counts['updated']} changed")

    # injury reports -> injuries
    url = sources.injuries_url(season)
    text, fetched = sources.fetch_csv(fetcher, url, live=live)
    if text is None:
        summary["missing_files"].append(url)
    else:
        records, info = sources.parse_injuries(
            sources.read_csv(text), sources.index_games_by_team_week(season_games),
            fetched_utc=fetched or _now_iso(), source=sources.injuries_source(season))
        counts = store.upsert("injuries", records)
        summary["injuries"] += _changed(counts)
        per["injuries"] = info
        log(f"{season} injuries: {info['kept']} kept of {info['rows']} rows, "
            f"{counts['added']} new, {counts['updated']} changed")


def _previous_player_since(store: NflStore) -> Optional[int]:
    """The `player_games_since` the last backfill recorded, so a daily update does not lose it."""
    try:
        manifest = json.loads((store.root / "MANIFEST.json").read_text(encoding="utf-8"))
        value = (manifest.get("coverage") or {}).get("player_games_since")
        return int(value) if value is not None else None
    except (OSError, ValueError, TypeError):
        return None


def _finish(store: NflStore, summary: dict, fetcher) -> dict:
    summary["finished_utc"] = _now_iso()
    summary["requests"] = dict(getattr(fetcher, "stats", {}) or {})
    seasons = store.seasons()
    coverage = {"seasons": [seasons[0], seasons[-1]] if seasons else None,
                "player_games_seasons": sorted({r["season"] for r in store.player_games}),
                "injuries_seasons": sorted({r["season"] for r in store.injuries})}
    since = summary.get("player_since")
    since = since if since is not None else _previous_player_since(store)
    if since is not None:
        coverage["player_games_since"] = since
    store.write_manifest(extra={
        "coverage": coverage,
        "sources": {"games": sources.GAMES_URL, "team_stats": sources.TEAM_STATS_TEMPLATE,
                    "player_stats": sources.PLAYER_STATS_TEMPLATE, "injuries": sources.INJURIES_TEMPLATE},
        "last_run": {k: summary[k] for k in (
            "kind", "started_utc", "finished_utc", "seasons", "player_since", "games", "team_games",
            "player_games", "injuries", "missing_files", "per_season", "stopped") if k in summary},
        "last_run_errors": len(summary["errors"])})
    return summary


def _guard(summary: dict, log, work: Callable[[], None]) -> None:
    try:
        work()
    except SourceBlocked as exc:
        summary["stopped"] = f"source blocked: {exc}"
        log(f"STOPPED: {summary['stopped']}")
    except RequestCapReached as exc:
        summary["stopped"] = f"request cap reached ({exc}); run again to continue"
        log(f"STOPPED: {summary['stopped']}")


# -- the two entry points ---------------------------------------------------------------------

def backfill(seasons: Iterable[int], *, fetcher: Optional[PoliteFetcher] = None,
             store: Optional[NflStore] = None, today: Optional[date] = None,
             player_since: Optional[int] = None, log: Callable[[str], None] = print) -> dict:
    """Every given season, newest first. Safe to run again: it only adds what is missing or changed.

    `player_since` keeps the player file (the largest) to seasons from that year on; the
    other three datasets always cover every given season.
    """
    fetcher = fetcher or PoliteFetcher()
    store = store or NflStore()
    wanted = sorted({int(s) for s in seasons}, reverse=True)
    current = current_season(today)
    summary = _new_summary("backfill")
    summary["seasons"] = wanted
    summary["player_since"] = player_since

    def work() -> None:
        if not _refresh_games(fetcher, store, wanted, summary, log=log):
            return
        for season in wanted:
            try:
                _ingest_season(fetcher, store, season, current, summary, log=log, player_since=player_since)
            except (SourceBlocked, RequestCapReached):
                raise
            except FetchError as exc:
                _record_error(summary, f"season {season}", exc)
            _finish(store, summary, fetcher)          # progress is on disk and in the manifest after every season

    _guard(summary, log, work)
    return _finish(store, summary, fetcher)


def update(today: Optional[date] = None, *, fetcher: Optional[PoliteFetcher] = None,
           store: Optional[NflStore] = None, log: Callable[[str], None] = print) -> dict:
    """The current season's new weeks, and the schedule for every season the store holds."""
    fetcher = fetcher or PoliteFetcher()
    store = store or NflStore()
    current = current_season(today)
    held = set(store.seasons())
    summary = _new_summary("update")
    summary["seasons"] = [current]

    def work() -> None:
        if not _refresh_games(fetcher, store, held | {current}, summary, log=log):
            return
        _ingest_season(fetcher, store, current, current, summary, log=log)

    _guard(summary, log, work)
    return _finish(store, summary, fetcher)


# -- status and the parity report -------------------------------------------------------------

def status(store: Optional[NflStore] = None, now: Optional[datetime] = None) -> dict:
    """Each dataset's record count, newest date and age in hours, and for games and team games
    the soonest booked kickoff after now. A booked game never counts as the newest data."""
    store = store or NflStore()
    now = now or datetime.now(timezone.utc)
    out = {}
    for name in FILES:
        if not store.path(name).exists():
            out[name] = {"records": 0, "newest": None, "age_hours": None, "next_scheduled": None}
            continue
        newest = store.newest(name)
        age = None
        if newest:
            try:
                stamp = datetime.fromisoformat(newest.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                age = round((now - stamp).total_seconds() / 3600, 1)
            except ValueError:
                age = None
        out[name] = {"records": len(store.load(name)), "newest": newest, "age_hours": age,
                     "next_scheduled": store.next_scheduled(name, after=now)}
    return out


def _first(items: List, n: int = 5) -> List:
    return items[:n]


def check(store: Optional[NflStore] = None) -> dict:
    """Parity and referential checks over the files on disk. `ok` is true only if every check passed.

    Each check is {"name", "ok", "detail"} with up to five offending keys when it fails.
    """
    store = store or NflStore()
    games = store.game_by_id()
    checks = []

    def add(name: str, bad: List, detail: str = "") -> None:
        checks.append({"name": name, "ok": not bad, "detail": detail if not bad else f"{len(bad)} offending: {_first(bad)}"})

    team_rows = store.team_game_by_key()
    per_game = Counter(r["game_id"] for r in store.team_games)
    add("every game has exactly two team rows", [g for g in games if per_game.get(g) != 2],
        f"{len(games)} games, {len(store.team_games)} team rows")
    add("every team row belongs to a game and one of its teams",
        [k for k in team_rows if k[0] not in games or k[1] not in (games[k[0]]["home_team"], games[k[0]]["away_team"])])
    final = [g for g in games.values() if g.get("status") == "final"]
    add("every final game has both scores and a kickoff",
        [g["game_id"] for g in final if g.get("home_score") is None or g.get("away_score") is None or not g.get("kickoff_utc")],
        f"{len(final)} final games")
    add("every final game has team statistics for both teams",
        [g["game_id"] for g in final
         if not all(team_rows.get((g["game_id"], t), {}).get("has_stats") for t in (g["home_team"], g["away_team"]))])
    add("a game's two turnover margins sum to zero",
        [g["game_id"] for g in final
         if (lambda a, b: a is not None and b is not None and a + b != 0)(
             team_rows.get((g["game_id"], g["home_team"]), {}).get("turnover_margin"),
             team_rows.get((g["game_id"], g["away_team"]), {}).get("turnover_margin"))])
    add("every player row belongs to a final game and one of its teams",
        [(r["game_id"], r["player_id"]) for r in store.player_games
         if r["game_id"] not in games or r["team"] not in (games[r["game_id"]]["home_team"], games[r["game_id"]]["away_team"])
         or games[r["game_id"]].get("status") != "final"], f"{len(store.player_games)} player rows")
    add("every injury row belongs to a game and one of its teams",
        [(r["game_id"], r["player_id"]) for r in store.injuries
         if r["game_id"] not in games or r["team"] not in (games[r["game_id"]]["home_team"], games[r["game_id"]]["away_team"])],
        f"{len(store.injuries)} injury rows")
    manifest = {}
    try:
        manifest = json.loads((store.root / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    since = (manifest.get("coverage") or {}).get("player_games_since")
    played_seasons = {g["season"] for g in final if since is None or g["season"] >= int(since)}
    add("every season with played games (from player_games_since, when set) has player rows",
        sorted(played_seasons - {r["season"] for r in store.player_games}))
    manifest_bad = []
    try:
        if not manifest:
            raise ValueError("no manifest")
        for fname, info in (manifest.get("files") or {}).items():
            path = store.root / fname
            if not path.exists() or path.stat().st_size != info.get("bytes") or jsonl.file_sha256(path) != info.get("sha256"):
                manifest_bad.append(fname)
    except (OSError, ValueError):
        manifest_bad.append("MANIFEST.json")
    add("the manifest describes the files on disk", manifest_bad)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
