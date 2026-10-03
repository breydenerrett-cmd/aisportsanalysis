"""When each probable starter last pitched, counting every game he pitched in.

DISPLAY ONLY, ATTACHED BESIDE THE DOSSIER, NEVER INSIDE IT (the rule
`store_freshness.coverage_for_game` states). The dossier's `starters` section
is a model and ledger input read from the regular season only
(`pitchers.regular_season_logs`), so in October its days of rest count from a
starter's last REGULAR-SEASON outing: a pitcher who started a Wild Card game
on Sept 30 showed 14 days (the cap) before a Division Series start on Oct 4.
This reads the whole store, postseason rows included, and answers the
reader's question instead: when did he last pitch, in what kind of game, and
how many days before this one. It feeds no model, price, pick or analyst
packet; `api/games.py` attaches it as `advanced.starter_rest`.

The store is read once per version of the file (size and modification time)
into a compact per-pitcher list of the four fields used here, so a request
costs one `stat` call, not a 25,000-line parse.
"""

from __future__ import annotations

import json
import threading
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src import paths

# MLB's postseason game types (src/providers/mlb.py DECISIVE_GAME_TYPES) in words.
ROUND_WORDS = {"F": "Wild Card", "D": "Division Series", "L": "League Championship Series", "W": "World Series"}

# person_id -> [(date, game_type, started, innings)], oldest first
_Index = Dict[str, List[Tuple[_date, str, bool, Optional[float]]]]
_cache: Dict[str, object] = {"sig": None, "index": {}}
_lock = threading.Lock()


def _signature(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def _build_index(path: Path) -> _Index:
    index: _Index = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue                  # a truncated final line costs one appearance
            person, day = row.get("person_id"), row.get("date")
            if person is None or not day or row.get("empty"):
                continue                  # bookkeeping markers carry no date
            try:
                when = _date.fromisoformat(str(day)[:10])
            except ValueError:
                continue
            index.setdefault(str(person), []).append(
                (when, row.get("game_type") or "R", bool(row.get("games_started")), row.get("innings_pitched")))
    for rows in index.values():
        rows.sort(key=lambda r: r[0])
    return index


def _index(path: Optional[Path] = None) -> _Index:
    # Resolved per call, not at import, so a test (or AISPORTS_DATA_DIR) moving the data root moves this too.
    target = Path(path) if path is not None else paths.historical_path("pitcher_logs.jsonl")
    sig = _signature(target)
    if sig is None:
        return {}
    with _lock:
        if _cache["sig"] != sig:
            _cache["index"] = _build_index(target)
            _cache["sig"] = sig
        return _cache["index"]           # type: ignore[return-value]


def last_outing(rows, before: _date) -> Optional[dict]:
    """The latest appearance strictly before `before`, in words a page can print; None if none."""
    latest = None
    for row in rows or ():
        if row[0] < before:
            latest = row
        else:
            break
    if latest is None:
        return None
    when, game_type, started, innings = latest
    return {
        "date": when.isoformat(),
        "days_before": (before - when).days,
        "game_type": game_type,
        "postseason": game_type in ROUND_WORDS,
        "round": ROUND_WORDS.get(game_type),
        "started": started,
        "innings": innings,
    }


def starter_rest(game: dict, game_date: str, path: Optional[Path] = None) -> dict:
    """{"away": outing or None, "home": outing or None} for one game's listed probables."""
    before = _date.fromisoformat(str(game_date)[:10])
    index = _index(path)
    out = {}
    for side in ("away", "home"):
        pid = (game or {}).get(f"{side}_probable_id")
        out[side] = last_outing(index.get(str(pid)), before) if pid not in (None, "") else None
    return out
