"""The UFC dataset on disk: file names, keys, and a read model with indexes.

Writers (schedule, fighters, fightstats, odds, ufccom) produce records in the shapes
fixed by docs/datasvc/UFC_SCHEMA.md and save them through `UfcStore.upsert`.
Readers (features, matchup, the API) load a `UfcStore` once and use its indexes.
Loading is lazy and per dataset, so a reader that needs only fighters never reads
the statistics file.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from src.datasvc import store as jsonl
from src.paths import data_path

DEFAULT_DIR = data_path("datasvc", "ufc")

FILES = {
    "events": "events.jsonl",
    "bouts": "bouts.jsonl",
    "fighters": "fighters.jsonl",
    "fight_stats": "fight_stats.jsonl",
    "odds": "odds.jsonl",
    "ufccom_profiles": "ufccom_profiles.jsonl",
}

KEYS = {
    "events": "event_id",
    "bouts": "bout_id",
    "fighters": "fighter_id",
    "fight_stats": ("bout_id", "fighter_id"),
    "odds": ("bout_id", "provider_id"),
    "ufccom_profiles": "fighter_id",
}

# The date field each dataset's "newest" is read from, for the manifest and /status.
DATE_FIELDS = {
    "events": "date_utc", "bouts": "date_utc", "fight_stats": "date_utc",
    "odds": "fetched_utc", "fighters": "fetched_utc", "ufccom_profiles": "fetched_utc",
}


class UfcStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else DEFAULT_DIR
        self._cache: Dict[str, list] = {}
        self._indexes: Dict[str, object] = {}

    # -- files ---------------------------------------------------------------------

    def path(self, name: str) -> Path:
        return self.root / FILES[name]

    def load(self, name: str) -> list:
        if name not in self._cache:
            self._cache[name] = jsonl.read_jsonl(self.path(name))
        return self._cache[name]

    def upsert(self, name: str, records) -> dict:
        counts = jsonl.upsert(self.path(name), records, key=KEYS[name])
        self._cache.pop(name, None)
        self._indexes.clear()
        return counts

    def write(self, name: str, records) -> int:
        count = jsonl.write_jsonl(self.path(name), records, key=KEYS[name])
        self._cache.pop(name, None)
        self._indexes.clear()
        return count

    def newest(self, name: str) -> Optional[str]:
        field = DATE_FIELDS[name]
        values = [r.get(field) for r in self.load(name) if r.get(field)]
        return max(values) if values else None

    def write_manifest(self, extra: dict = None) -> dict:
        datasets = {FILES[n]: {"records": len(self.load(n)), "newest": self.newest(n)}
                    for n in FILES if self.path(n).exists()}
        return jsonl.write_manifest(self.root, datasets, extra=extra)

    # -- datasets ------------------------------------------------------------------

    @property
    def events(self) -> list:
        return self.load("events")

    @property
    def bouts(self) -> list:
        return self.load("bouts")

    @property
    def fighters(self) -> list:
        return self.load("fighters")

    @property
    def fight_stats(self) -> list:
        return self.load("fight_stats")

    @property
    def odds(self) -> list:
        return self.load("odds")

    @property
    def ufccom_profiles(self) -> list:
        return self.load("ufccom_profiles")

    # -- indexes -------------------------------------------------------------------

    def _index(self, name: str, build):
        if name not in self._indexes:
            self._indexes[name] = build()
        return self._indexes[name]

    def event_by_id(self) -> Dict[str, dict]:
        return self._index("event_by_id", lambda: {r["event_id"]: r for r in self.events})

    def bout_by_id(self) -> Dict[str, dict]:
        return self._index("bout_by_id", lambda: {r["bout_id"]: r for r in self.bouts})

    def fighter_by_id(self) -> Dict[str, dict]:
        return self._index("fighter_by_id", lambda: {r["fighter_id"]: r for r in self.fighters})

    def bouts_by_fighter(self) -> Dict[str, List[dict]]:
        """Each fighter's bouts, oldest first."""
        def build():
            out = defaultdict(list)
            for bout in self.bouts:
                for side in ("fighter_a_id", "fighter_b_id"):
                    if bout.get(side):
                        out[bout[side]].append(bout)
            for lst in out.values():
                lst.sort(key=lambda b: (b.get("date_utc") or "", b["bout_id"]))
            return dict(out)
        return self._index("bouts_by_fighter", build)

    def stats_for(self) -> Dict[tuple, dict]:
        """(bout_id, fighter_id) -> that fighter's statistics row for that bout."""
        return self._index("stats_for", lambda: {(r["bout_id"], r["fighter_id"]): r for r in self.fight_stats})

    def odds_for_bout(self) -> Dict[str, List[dict]]:
        def build():
            out = defaultdict(list)
            for row in self.odds:
                out[row["bout_id"]].append(row)
            return dict(out)
        return self._index("odds_for_bout", build)

    def profile_for(self) -> Dict[str, dict]:
        return self._index("profile_for", lambda: {r["fighter_id"]: r for r in self.ufccom_profiles})
