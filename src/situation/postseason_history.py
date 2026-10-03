"""A display-only store of earlier postseasons, from MLB's free Stats API.

WHAT IT IS FOR, AND WHAT IT MUST NEVER BECOME
---------------------------------------------
The results store (`data/historical/mlb_results.csv`) starts on 2023-03-30, so a postseason
fact older than that ("first series win since 2019", how the bye teams of 2016 did in the
Division Series) is not in it. This module fetches the postseasons before it, 2015 on, into a
store of its own so those facts can be stated honestly and the first factor test
(`rest_vs_rhythm.py`) can cover eleven Octobers instead of three.

IT IS A DISPLAY AND RESEARCH STORE, NEVER A TRAINING POPULATION. The reasons are the repo's own
(`mlb.TRAINING_GAME_TYPES`, `features.build_training_table`'s default): a postseason game is a
different, selected population (the best clubs, aces on short rest, no regular-season fatigue)
and a model fitted on it would learn October from a handful of games. So:

  * it lives in `data/research/postseason_history/`, not in `data/historical/`, and nothing in
    `src/pipeline` imports it (a test reads the pipeline's source to prove it);
  * the games are postseason only (types F, D, L, W); the regular seasons enter only as one
    final record per club (wins and losses from the standings), used to set a club's postseason
    against its regular season, never as games;
  * `ingest` writes only into its own directory and never into the results store or its manifest.

WHAT IS FETCHED
---------------
For each season, one schedule request for the postseason window (late September to mid
November) and one standings request as of the day before the first postseason game, which is
the club's final regular-season record. Both are cached on disk (`data/raw/`, ignored) so a
re-run costs nothing, with a pause between real requests. `get_json` is the one network seam, so
tests inject canned responses and make no request.

EACH GAME CARRIES, besides the results store's own columns: `series_game_number`,
`games_in_series` and `series_description` (the feed's own statement of which game of which
series it is, used to check the rebuilt series), `season`, `source_url` and `fetched_utc`.
`probables` are the starters the schedule listed, as everywhere in this layer.

Stdlib only. Network only through `get_json`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Optional, Sequence

from src import paths
from src.data import parks
from src.providers import mlb

DIR_NAME = ("research", "postseason_history")
GAMES_FILE = "games.jsonl"
RECORDS_FILE = "season_records.jsonl"
MANIFEST_FILE = "MANIFEST.json"

POSTSEASON_TYPES = ("F", "D", "L", "W")
FIRST_SEASON = 2015
# The window each season's schedule request covers: after the regular season's last day in every
# season since 2015 (the latest, 2022, ended October 5) and before the Series ends.
WINDOW_START, WINDOW_END = "09-15", "11-20"
POLITE_DELAY_S = 1.0
TIMEOUT_S = 30

LABEL = ("Display and research only. Never a training population: postseason games are a "
         "selected population, and nothing that fits or prices a model may read this store.")


def default_root() -> Path:
    return paths.data_path(*DIR_NAME)


def cache_root() -> Path:
    return paths.raw_path("postseason_history")


@dataclass
class History:
    games: List[dict] = field(default_factory=list)
    season_records: dict = field(default_factory=dict)      # {(season, club): {"wins", "losses"}}
    manifest: dict = field(default_factory=dict)

    def seasons(self) -> List[int]:
        return sorted({int(str(g["date"])[:4]) for g in self.games if g.get("date")})


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue            # a truncated last line costs one row, never the store
    return out


def load(root: Optional[Path] = None) -> History:
    """The store as plain data: empty (never an error) when it has not been fetched yet."""
    base = Path(root) if root is not None else default_root()
    games = _read_jsonl(base / GAMES_FILE)
    records = {}
    for row in _read_jsonl(base / RECORDS_FILE):
        if row.get("season") is None or not row.get("team"):
            continue
        records[(int(row["season"]), str(row["team"]))] = {
            "wins": row.get("wins"), "losses": row.get("losses"), "as_of": row.get("as_of")}
    manifest = {}
    target = base / MANIFEST_FILE
    if target.exists():
        try:
            manifest = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    return History(games=games, season_records=records, manifest=manifest)


# ---------------------------------------------------------------------------
# fetching (pure parsing over raw payloads; the network is `get_json`)
# ---------------------------------------------------------------------------

def schedule_params(season: int) -> dict:
    return {"sportId": mlb.SPORT_ID, "startDate": f"{season}-{WINDOW_START}",
            "endDate": f"{season}-{WINDOW_END}", "gameType": ",".join(POSTSEASON_TYPES),
            "hydrate": "probablePitcher,team,linescore"}


def parse_schedule(season: int, payload: Mapping, *, fetched_utc: str, source_url: str) -> list:
    """Final postseason games of a season from a raw schedule payload, as store rows.

    Only games the feed marks final, of the four postseason types, with both scores. A game of
    another type (the window also holds the last regular-season days) is ignored whatever the
    request asked for: the filter is here as well as in the query, so a feed that ignores the query
    cannot put a regular-season game in this store.
    """
    out = []
    for entry in payload.get("dates") or []:
        for raw in entry.get("games") or []:
            if raw.get("gameType") not in POSTSEASON_TYPES:
                continue
            parsed = mlb.parse_game(raw)
            if parsed.get("state") != "final" or parsed.get("game_pk") is None:
                continue
            row = {c: parsed.get(c) for c in (
                "game_pk", "date", "start_time_utc", "venue", "game_type", "away_team", "home_team",
                "away_team_id", "home_team_id", "away_probable", "home_probable", "away_probable_id",
                "home_probable_id", "away_score", "home_score", "winner", "home_won", "total_runs",
                "run_differential", "double_header", "game_number")}
            row.update(season=season, series_game_number=raw.get("seriesGameNumber"),
                       games_in_series=raw.get("gamesInSeries"),
                       series_description=raw.get("seriesDescription"),
                       source_url=source_url, fetched_utc=fetched_utc)
            out.append(row)
    out.sort(key=lambda r: (r["date"] or "", str(r["game_pk"])))
    return out


def parse_standings(season: int, payload: Mapping, *, as_of: str, fetched_utc: str, source_url: str) -> list:
    """One final regular-season record per club from a raw standings payload."""
    out = []
    for row in mlb.parse_standings(payload.get("records") or []):
        abbrev, wins, losses = row.get("team_abbrev"), row.get("wins"), row.get("losses")
        if not abbrev or wins is None or losses is None:
            continue
        out.append({"season": season, "team": parks.canonical_team(abbrev), "team_id": row.get("team_id"),
                    "wins": wins, "losses": losses, "as_of": as_of, "source_url": source_url,
                    "fetched_utc": fetched_utc})
    out.sort(key=lambda r: r["team"])
    return out


def _url(path: str, params: Mapping) -> str:
    from urllib.parse import urlencode
    return f"{mlb.API_HOST}/{path}?{urlencode(params)}"


def _cached(cache: Optional[Path], name: str, fetch: Callable, sleep: Callable, delay: float, refresh: bool):
    """The raw payload for `name`: from the cache when it is there, else fetched (after a polite
    pause) and cached. Returns (payload, fetched_now)."""
    target = None if cache is None else cache / name
    if target is not None and target.exists() and not refresh:
        return json.loads(target.read_text(encoding="utf-8")), False
    sleep(delay)
    payload = fetch()
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload, True


def fetch_season(season: int, *, get_json: Callable = mlb._get_json, fetched_utc: str,
                 cache: Optional[Path] = None, sleep: Callable = time.sleep,
                 delay: float = POLITE_DELAY_S, refresh: bool = False) -> tuple:
    """`(games, records)` for one season. Two requests at most (none when both are cached):
    the postseason schedule, then the season's final standings.

    The standings are asked for WITHOUT a date. Standings count regular-season games only, so a
    finished season's table is its final regular-season record whatever day is asked, and asking for
    "the day before the first postseason game" is worse than useless: on an off day (the regular
    season ended 2019-09-29 and the Wild Card game was 10-01) the feed answers with no divisions at
    all, which is how the first run of this ingest came back with a record for 2018 and for no other
    season. `tests/test_situation_history.py` pins that the request carries no date."""
    params = schedule_params(season)
    payload, _ = _cached(cache, f"{season}_schedule.json",
                         lambda: get_json("schedule", params, TIMEOUT_S), sleep, delay, refresh)
    games = parse_schedule(season, payload, fetched_utc=fetched_utc, source_url=_url("schedule", params))
    records: list = []
    if games:
        sparams = {"leagueId": f"{mlb.LEAGUE_ID_AL},{mlb.LEAGUE_ID_NL}", "season": season,
                   "hydrate": "division"}
        spayload, _ = _cached(cache, f"{season}_standings.json",
                              lambda: get_json("standings", sparams, TIMEOUT_S), sleep, delay, refresh)
        records = parse_standings(season, spayload, as_of="final regular season", fetched_utc=fetched_utc,
                                  source_url=_url("standings", sparams))
    return games, records


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: Iterable[Mapping]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    tmp.replace(path)


def write(root: Path, games: Sequence[Mapping], records: Sequence[Mapping], *, seasons: Sequence[int],
          fetched_utc: str) -> dict:
    """Write the three files. The games are keyed by game_pk and the records by (season, club),
    so a re-run replaces in place and never duplicates."""
    base = Path(root)
    by_pk = {str(g["game_pk"]): dict(g) for g in games}
    by_team = {(int(r["season"]), r["team"]): dict(r) for r in records}
    ordered_games = sorted(by_pk.values(), key=lambda r: (r["date"] or "", str(r["game_pk"])))
    ordered_records = [by_team[k] for k in sorted(by_team)]
    _write_jsonl(base / GAMES_FILE, ordered_games)
    _write_jsonl(base / RECORDS_FILE, ordered_records)
    manifest = {
        "label": LABEL, "never_a_training_population": True,
        "source": "MLB Stats API (statsapi.mlb.com), free and keyless",
        "seasons": sorted(set(int(s) for s in seasons)), "games": len(ordered_games),
        "season_records": len(ordered_records), "fetched_utc": fetched_utc,
        "game_types": list(POSTSEASON_TYPES),
        "note": ("games are postseason games only; a season record is a club's final regular-season "
                 "record from the standings, one row per club, never games"),
    }
    (base / MANIFEST_FILE).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def ingest(seasons: Sequence[int], root: Optional[Path] = None, *, get_json: Callable = mlb._get_json,
           cache: Optional[Path] = None, sleep: Callable = time.sleep, delay: float = POLITE_DELAY_S,
           refresh: bool = False, now: Optional[datetime] = None,
           on_season: Optional[Callable] = None) -> dict:
    """Fetch `seasons` into the store at `root` (merged with what is already there) and return the
    manifest. A season that fails is reported in `errors` and skipped; the rest still land."""
    root = Path(root) if root is not None else default_root()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    held = load(root)
    games = {str(g["game_pk"]): g for g in held.games}
    records = {(s, t): dict(season=s, team=t, **{k: v for k, v in r.items()})
               for (s, t), r in held.season_records.items()}
    errors: list = []
    done: list = []
    for season in seasons:
        try:
            g, r = fetch_season(season, get_json=get_json, fetched_utc=stamp, cache=cache, sleep=sleep,
                                delay=delay, refresh=refresh)
        except mlb.MLBError as exc:
            errors.append({"season": season, "error": str(exc)})
            continue
        for row in g:
            games[str(row["game_pk"])] = row
        for row in r:
            records[(int(row["season"]), row["team"])] = row
        done.append(season)
        if on_season:
            on_season(season, len(g), len(r))
    seasons_held = sorted({int(str(g["date"])[:4]) for g in games.values() if g.get("date")} | set(done))
    manifest = write(root, list(games.values()), list(records.values()), seasons=seasons_held, fetched_utc=stamp)
    manifest["errors"] = errors
    return manifest
