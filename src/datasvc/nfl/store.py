"""The NFL dataset on disk: file names, keys, and a read model with indexes.

Writers (`pipeline`, through `sources`) produce records in the shapes fixed by
docs/datasvc/NFL_SCHEMA.md and save them through `NflStore.upsert`. Readers (features,
matchup, the API) load an `NflStore` once and use its indexes. Loading is lazy and per
dataset, so a reader that needs only the schedule never reads the player file.

`upsert` here differs from the foundation's in one way on purpose: a row whose content is
unchanged is left exactly as stored (its `fetched_utc` too), and a call that changes nothing
does not write at all. The nflverse season files are replaced whole every day, so the
foundation's "a newer record replaces the older one" would rewrite every row of the season
daily (a megabyte of git churn for no new fact) and bump the file's modification time, which
makes the API swap in a fresh store. `fetched_utc` therefore means "when this exact content
was first fetched".
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from src.datasvc import store as jsonl
from src.paths import data_path

DEFAULT_DIR = data_path("datasvc", "nfl")

FILES = {
    "games": "games.jsonl",
    "team_games": "team_games.jsonl",
    "player_games": "player_games.jsonl",
    "injuries": "injuries.jsonl",
}

KEYS = {
    "games": "game_id",
    "team_games": ("game_id", "team"),
    "player_games": ("game_id", "player_id"),
    "injuries": ("game_id", "player_id"),
}

# The date field each dataset's "newest" is read from, for the manifest and /status.
DATE_FIELDS = {
    "games": "kickoff_utc", "team_games": "kickoff_utc", "player_games": "kickoff_utc",
    "injuries": "fetched_utc",
}

# For games and team games "newest" is the newest game that was PLAYED: a booked, removed or
# unresolved game's date is a schedule, not data (the same reasoning as the UFC store).
SCHEDULED_DATASETS = ("games", "team_games")

ATTRIBUTION = ("Schedule, team and player statistics and injury reports: nflverse "
               "(github.com/nflverse/nflverse-data), CC BY 4.0.")

# The source's positions, grouped. The same table groups the stats and the injury report so
# a count by position means one thing in both.
POSITION_GROUPS = {
    "QB": "QB",
    "RB": "RB", "FB": "RB", "HB": "RB",
    "WR": "WR",
    "TE": "TE",
    "OT": "OL", "T": "OL", "G": "OL", "OG": "OL", "C": "OL", "OL": "OL",
    "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL",
    "LB": "LB", "OLB": "LB", "ILB": "LB", "MLB": "LB",
    "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB", "SAF": "DB", "DB": "DB",
    "K": "ST", "P": "ST", "LS": "ST", "PK": "ST",
}
POSITION_GROUP_ORDER = ("QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST", "OTHER")
# The groups the source's own `position_group` uses that differ from ours.
_SOURCE_GROUPS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "OL": "OL", "DL": "DL",
                  "LB": "LB", "DB": "DB", "SPEC": "ST"}


def position_group(position: Optional[str], source_group: Optional[str] = None) -> str:
    """QB, RB, WR, TE, OL, DL, LB, DB, ST or OTHER for a position as the source spells it."""
    if position:
        found = POSITION_GROUPS.get(str(position).strip().upper())
        if found:
            return found
    if source_group:
        found = _SOURCE_GROUPS.get(str(source_group).strip().upper())
        if found:
            return found
    return "OTHER"


def content_of(record: dict) -> str:
    """A record's identity for change detection: everything except its fetch time."""
    return json.dumps({k: v for k, v in record.items() if k != "fetched_utc"},
                      ensure_ascii=False, sort_keys=True)


def counts_toward_newest(name: str, row: dict) -> bool:
    """False for a game or team game that has not been played (scheduled, removed, no result)."""
    return name not in SCHEDULED_DATASETS or row.get("status") == "final"


def _instant(value) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def compact(rows: List[dict]) -> List[dict]:
    """The same rows with every equal key and every equal short string or int stored once.

    `json.loads` makes a fresh copy of every key and every value of every line, so 18,000 injury
    rows hold 18,000 copies of "report_status" and of "KC". Read whole, the four NFL files took
    about 103 MB of Python objects; sharing the repeats takes a bit over half of that away, which
    matters because the API keeps one store in memory for the life of the process. A bool is never
    shared through the table (True and 1 hash alike), and a long or unique string is left alone.
    """
    shared: Dict[object, object] = {}
    for i, row in enumerate(rows):               # in place: each original row is freed as its copy replaces it
        rows[i] = {shared.setdefault(k, k): (shared.setdefault(v, v) if type(v) is int or (type(v) is str and len(v) <= 64) else v)
                   for k, v in row.items()}
    return rows


def game_sort_key(game: dict) -> Tuple[str, str]:
    """Chronological order of games: kickoff, else the end of the Eastern gameday, then id."""
    return (game.get("kickoff_utc") or f"{game.get('gameday') or '9999-12-31'}T23:59:59Z", game["game_id"])


class NflStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else DEFAULT_DIR
        self._cache: Dict[str, list] = {}
        self._indexes: Dict[str, object] = {}

    # -- files ---------------------------------------------------------------------

    def path(self, name: str) -> Path:
        return self.root / FILES[name]

    def load(self, name: str) -> list:
        if name not in self._cache:
            self._cache[name] = compact(jsonl.read_jsonl(self.path(name)))
        return self._cache[name]

    def upsert(self, name: str, records: Iterable[dict]) -> dict:
        """Merge `records` by key. Only new or changed rows are written (module docstring).

        Returns added, updated (content changed), unchanged and total. Nothing is deleted.
        """
        key = KEYS[name]
        incoming: Dict[tuple, dict] = {}
        for row in records:
            incoming[jsonl.key_of(row, key)] = row          # a key repeated in one batch: the last wins
        existing = {jsonl.key_of(r, key): r for r in self.load(name)}
        added = updated = 0
        merged = dict(existing)
        for k, row in incoming.items():
            old = existing.get(k)
            if old is None:
                added += 1
            elif content_of(old) != content_of(row):
                updated += 1
            else:
                continue                                      # unchanged: keep the stored row as it is
            merged[k] = row
        if added or updated:
            jsonl.write_jsonl(self.path(name), merged.values(), key=key)
            self._cache.pop(name, None)
            self._indexes.clear()
        return {"added": added, "updated": updated, "unchanged": len(incoming) - added - updated,
                "total": len(merged)}

    def write(self, name: str, records: Iterable[dict]) -> int:
        count = jsonl.write_jsonl(self.path(name), records, key=KEYS[name])
        self._cache.pop(name, None)
        self._indexes.clear()
        return count

    def newest(self, name: str) -> Optional[str]:
        """The newest date in a dataset; for games and team games, the newest played."""
        field = DATE_FIELDS[name]
        values = [r.get(field) for r in self.load(name) if r.get(field) and counts_toward_newest(name, r)]
        return max(values) if values else None

    def next_scheduled(self, name: str, after: Optional[datetime] = None) -> Optional[str]:
        """The soonest booked kickoff in games or team_games, later than `after` when given."""
        if name not in SCHEDULED_DATASETS:
            return None
        booked = []
        for row in self.load(name):
            when = _instant(row.get("kickoff_utc")) if row.get("status") == "scheduled" else None
            if when is not None and (after is None or when > after):
                booked.append((when, row["kickoff_utc"]))
        return min(booked)[1] if booked else None

    def write_manifest(self, extra: dict = None) -> dict:
        datasets = {FILES[n]: {"records": len(self.load(n)), "newest": self.newest(n)}
                    for n in FILES if self.path(n).exists()}
        base = {"attribution": ATTRIBUTION}
        base.update(extra or {})
        self.root.mkdir(parents=True, exist_ok=True)      # a run that wrote no dataset still records itself
        return jsonl.write_manifest(self.root, datasets, extra=base)

    # -- datasets ------------------------------------------------------------------

    @property
    def games(self) -> list:
        return self.load("games")

    @property
    def team_games(self) -> list:
        return self.load("team_games")

    @property
    def player_games(self) -> list:
        return self.load("player_games")

    @property
    def injuries(self) -> list:
        return self.load("injuries")

    # -- indexes -------------------------------------------------------------------

    def _index(self, name: str, build):
        if name not in self._indexes:
            self._indexes[name] = build()
        return self._indexes[name]

    def game_by_id(self) -> Dict[str, dict]:
        return self._index("game_by_id", lambda: {g["game_id"]: g for g in self.games})

    def games_sorted(self) -> List[dict]:
        """Every game in chronological order."""
        return self._index("games_sorted", lambda: sorted(self.games, key=game_sort_key))

    def games_by_team(self) -> Dict[str, List[dict]]:
        """Each team's games (home and away, played or not), oldest first."""
        def build():
            out = defaultdict(list)
            for game in self.games_sorted():
                for side in ("home_team", "away_team"):
                    if game.get(side):
                        out[game[side]].append(game)
            return dict(out)
        return self._index("games_by_team", build)

    def team_game_by_key(self) -> Dict[Tuple[str, str], dict]:
        """(game_id, team) -> that team's row for that game."""
        return self._index("team_game_by_key", lambda: {(r["game_id"], r["team"]): r for r in self.team_games})

    def player_games_by_player(self) -> Dict[str, List[dict]]:
        """Each player's rows, oldest first."""
        def build():
            out = defaultdict(list)
            for row in self.player_games:
                out[row["player_id"]].append(row)
            for rows in out.values():
                rows.sort(key=lambda r: (r.get("kickoff_utc") or "", r["game_id"]))
            return dict(out)
        return self._index("player_games_by_player", build)

    def player_games_by_game(self) -> Dict[str, List[dict]]:
        def build():
            out = defaultdict(list)
            for row in self.player_games:
                out[row["game_id"]].append(row)
            return dict(out)
        return self._index("player_games_by_game", build)

    def player_names(self) -> Dict[str, str]:
        """player_id -> the name on the player's newest row."""
        def build():
            return {pid: rows[-1].get("name") or pid for pid, rows in self.player_games_by_player().items()}
        return self._index("player_names", build)

    def injuries_by_game_team(self) -> Dict[Tuple[str, str], List[dict]]:
        def build():
            out = defaultdict(list)
            for row in self.injuries:
                out[(row["game_id"], row["team"])].append(row)
            return dict(out)
        return self._index("injuries_by_game_team", build)

    def injury_weeks(self) -> set:
        """(season, week) pairs that have at least one injury row in the store."""
        return self._index("injury_weeks", lambda: {(r["season"], r["week"]) for r in self.injuries})

    def qb_starts(self) -> Dict[str, List[Tuple[str, str, str]]]:
        """qb_id -> [(kickoff_utc, game_id, team)] over games that are final, oldest first."""
        def build():
            out = defaultdict(list)
            for game in self.games_sorted():
                if game.get("status") != "final":
                    continue
                for side in ("home", "away"):
                    qb = game.get(f"{side}_qb_id")
                    if qb:
                        out[qb].append((game.get("kickoff_utc") or "", game["game_id"], game[f"{side}_team"]))
            return dict(out)
        return self._index("qb_starts", build)

    def home_stadiums(self) -> Dict[Tuple[str, int], str]:
        """(team, season) -> the stadium id the team used for most of that season's home games."""
        from src.datasvc.nfl import venues
        return self._index("home_stadiums", lambda: venues.home_stadium_ids(self.games))

    def seasons(self) -> List[int]:
        return sorted({g["season"] for g in self.games})
