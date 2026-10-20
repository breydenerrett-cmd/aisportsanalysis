"""The ESPN-fed datasets on disk: append-only and versioned, so every read can be point-in-time.

A row is never rewritten or removed. Each row carries `observed_utc` (when WE fetched the fact). A fact
that later changes (a game goes final, a player's injury status moves) is appended as a NEW row with a
later `observed_utc`; a re-fetch that finds the same content appends nothing and writes nothing. The file
key is therefore (dataset key fields, observed_utc), and "the current row" is the newest version of the
key, "the row as of T" the newest version observed at or before T.

Files: <root>/<league>/<dataset>.jsonl, or <dataset>_<season>.jsonl for the season-partitioned datasets
(games, team_games, player_games, standings), so a reader loads only the seasons it needs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from src.datasvc import store as jsonl
from src.paths import data_path

DEFAULT_DIR = data_path("datasvc", "espn")

#: dataset -> (key fields, partitioned by season)
DATASETS: Dict[str, Tuple[Tuple[str, ...], bool]] = {
    "teams": (("team_id",), False),
    "players": (("team_id", "player_id"), False),
    "games": (("game_id",), True),
    "team_games": (("game_id", "team_id"), True),
    "player_games": (("game_id", "player_id"), True),
    "standings": (("season", "group", "team_id"), True),
    "injuries": (("team_id", "player_id"), False),
}

ATTRIBUTION = ("Teams, schedules, scores, box scores, standings, injury reports and rosters: ESPN's public "
               "site JSON (site.api.espn.com), observed by LineHound. Not redistributed by ESPN; "
               "for internal analysis.")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content(row: dict) -> str:
    return json.dumps({k: v for k, v in row.items() if k != "observed_utc"}, ensure_ascii=False, sort_keys=True)


class EspnStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else DEFAULT_DIR

    # -- paths ---------------------------------------------------------------------------------------

    def league_dir(self, league: str) -> Path:
        return self.root / league

    def path(self, league: str, dataset: str, season=None) -> Path:
        if dataset not in DATASETS:
            raise KeyError(f"unknown dataset {dataset!r}")
        name = f"{dataset}_{season}" if DATASETS[dataset][1] else dataset
        return self.league_dir(league) / f"{name}.jsonl"

    def seasons(self, league: str, dataset: str) -> List[str]:
        if not DATASETS[dataset][1]:
            return []
        prefix = dataset + "_"
        return sorted(p.stem[len(prefix):] for p in self.league_dir(league).glob(f"{prefix}*.jsonl"))

    # -- writing ---------------------------------------------------------------------------------------

    def append(self, league: str, dataset: str, rows: Iterable[dict]) -> dict:
        """Append the rows whose content differs from their key's newest stored version. Returns
        {added, versioned, unchanged, total}; writes nothing when nothing changed."""
        key, partitioned = DATASETS[dataset]
        by_season: Dict[str, List[dict]] = {}
        for row in rows:
            part = str(row.get("season", "unknown")) if partitioned else ""
            by_season.setdefault(part, []).append(row)
        counts = {"added": 0, "versioned": 0, "unchanged": 0, "total": 0}
        for part, batch in sorted(by_season.items()):
            path = self.path(league, dataset, part if partitioned else None)
            existing = jsonl.read_jsonl(path)
            newest: Dict[tuple, dict] = {}
            seen = set()
            for r in existing:
                k = jsonl.key_of(r, key)
                seen.add(k + (r["observed_utc"],))
                if k not in newest or r["observed_utc"] >= newest[k]["observed_utc"]:
                    newest[k] = r
            fresh = []
            for row in batch:
                k = jsonl.key_of(row, key)
                old = newest.get(k)
                if old is not None and _content(old) == _content(row):
                    counts["unchanged"] += 1
                    continue
                if k + (row["observed_utc"],) in seen:
                    counts["unchanged"] += 1      # same key, same second: already recorded this instant
                    continue
                counts["versioned" if old is not None else "added"] += 1
                seen.add(k + (row["observed_utc"],))
                newest[k] = row
                fresh.append(row)
            if fresh:
                jsonl.write_jsonl(path, existing + fresh, key=key + ("observed_utc",))
            counts["total"] += len(existing) + len(fresh)
        return counts

    # -- reading -----------------------------------------------------------------------------------------

    def versions(self, league: str, dataset: str, season=None) -> List[dict]:
        """Every stored version. Season-partitioned datasets: one season, or all when `season` is None."""
        if DATASETS[dataset][1]:
            seasons = [str(season)] if season is not None else self.seasons(league, dataset)
            out: List[dict] = []
            for s in seasons:
                out.extend(jsonl.read_jsonl(self.path(league, dataset, s)))
            return out
        return jsonl.read_jsonl(self.path(league, dataset))

    def latest(self, league: str, dataset: str, season=None, as_of: Optional[str] = None) -> Dict[tuple, dict]:
        """key -> the newest version observed at or before `as_of` (default: newest of all)."""
        key = DATASETS[dataset][0]
        out: Dict[tuple, dict] = {}
        for r in self.versions(league, dataset, season):
            if as_of is not None and r["observed_utc"] > as_of:
                continue
            k = jsonl.key_of(r, key)
            if k not in out or r["observed_utc"] >= out[k]["observed_utc"]:
                out[k] = r
        return out

    # -- manifest ------------------------------------------------------------------------------------------

    def write_manifest(self, league: str, *, extra: Optional[dict] = None) -> dict:
        directory = self.league_dir(league)
        datasets = {}
        for p in sorted(directory.glob("*.jsonl")):
            rows = jsonl.read_jsonl(p)
            newest = max((r.get("observed_utc") or "" for r in rows), default="") or None
            datasets[p.name] = {"records": len(rows), "newest": newest}
        info = {"league": league, "attribution": ATTRIBUTION}
        info.update(extra or {})
        return jsonl.write_manifest(directory, datasets, extra=info)

    def read_manifest(self, league: str) -> Optional[dict]:
        try:
            return json.loads((self.league_dir(league) / "MANIFEST.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
