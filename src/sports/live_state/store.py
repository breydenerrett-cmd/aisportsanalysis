"""The in-memory cache of live game states, the stale guard, and the append-only snapshot log.

THE CACHE
---------
One entry per (sport, game id). An entry has two layers because the NHL needs two cadences:

  * ``base``  -- score, period, clock, shots: read for every game in one request every 30 seconds;
  * ``detail`` -- strength, goalies, skaters, goals by period: three more requests per live game, at most every 60 seconds.

Each layer carries the time it was READ. A reader (``get`` / ``fresh_games``) never sees a layer older than
``STALE_AFTER_SECONDS`` (180: three missed passes, the same guard ``src/sports/live_feed.py`` uses for scores). An old
BASE hides the whole game; an old DETAIL hides only its own keys (they come back as None, never as the last value), so a
game whose box score failed to load still shows its score and clock but claims no power play and names no goalie.
A wrong state is worse than none: the later phases of the live hounds put a bet decision on top of this.

THE SNAPSHOT LOG
----------------
``log_change`` appends one compact JSON line to ``live_state/YYYY-MM-DD.jsonl`` ONLY when the game's SIGNATURE changed
(the signature leaves out the clock and time on ice, which change every read; a shot, a goal, a power play, a goalie
change, a point or a new game of tennis do change it). The directory is BESIDE THE HOUNDS LEDGER, on the persistent
volume in production (``user_engine.ledger_path()``'s parent, the same rule that keeps the ledger itself across deploys);
the image's git-tracked ``evidence/`` would be replaced at the next deploy. The log is append-only: nothing here rewrites,
truncates or deletes a line. A write that fails is counted and swallowed; the log is a record, never a reason to stop.
Dated by the UTC day of the read, so one file is one UTC day.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.hounds import live_scores as ls

logger = logging.getLogger("linehound.sports.live_state")

STALE_AFTER_SECONDS = 180.0
LOG_DIR_NAME = "live_state"
#: The keys the detail layer owns, per sport: what an old detail layer turns back into None.
DETAIL_KEYS = {"NHL": ("strength", "goalies", "skaters", "goals_by_period")}

_lock = threading.Lock()
_GAMES: dict = {}                      # (sport, game id) -> {"base", "base_at", "detail", "detail_at", "names"}
_LAST_SIG: dict = {}                   # (sport, game id) -> (signature, state)
STATUS: dict = {"enabled": False, "passes": 0, "last_pass_utc": None, "last_error": None, "log_rows": 0,
                "log_errors": 0, "last_log_utc": None, "nhl_last_read_utc": None, "tennis_last_read_utc": None}


def clear() -> None:
    with _lock:
        _GAMES.clear()
        _LAST_SIG.clear()


def _age(at: Optional[datetime], now: datetime) -> Optional[float]:
    return None if at is None else (now - at).total_seconds()


def _fresh(at: Optional[datetime], now: datetime) -> bool:
    age = _age(at, now)
    return age is not None and -5.0 <= age <= STALE_AFTER_SECONDS


def put_base(sport: str, game_id, base: Mapping, at: datetime, *, names: Optional[Mapping] = None) -> None:
    key = (sport, str(game_id))
    with _lock:
        held = _GAMES.get(key) or {"detail": None, "detail_at": None, "names": {}}
        merged_names = dict(held.get("names") or {})
        for side, value in (names or {}).items():                  # the score read's names are a fallback: never over a boxscore's
            if value and not merged_names.get(side):
                merged_names[side] = value
        _GAMES[key] = {"base": dict(base), "base_at": at, "detail": held["detail"], "detail_at": held["detail_at"],
                       "names": merged_names}


def put_detail(sport: str, game_id, detail: Mapping, at: datetime, *, names: Optional[Mapping] = None) -> None:
    key = (sport, str(game_id))
    with _lock:
        held = _GAMES.get(key) or {"base": None, "base_at": None, "names": {}}
        merged_names = dict(held.get("names") or {})
        merged_names.update({k: v for k, v in (names or {}).items() if v})
        held.update({"detail": dict(detail), "detail_at": at, "names": merged_names})
        _GAMES[key] = held


def detail_age(sport: str, game_id, now: datetime) -> Optional[float]:
    """Seconds since this game's detail layer was read, or None when it never was."""
    with _lock:
        held = _GAMES.get((sport, str(game_id)))
    return None if not held else _age(held.get("detail_at"), now)


def known_ids(sport: str) -> list:
    with _lock:
        return [gid for (sp, gid) in _GAMES if sp == sport]


def _view(sport: str, held: Mapping, now: datetime) -> Optional[dict]:
    if not held or held.get("base") is None or not _fresh(held.get("base_at"), now):
        return None
    view = dict(held["base"])
    names = held.get("names") or {}
    for side in ("home", "away"):
        if isinstance(view.get(side), dict):
            view[side] = dict(view[side])
            if names.get(side):
                view[side]["name"] = names[side]
    view["as_of"] = ls.iso(held["base_at"])
    if sport in DETAIL_KEYS:
        if held.get("detail") and _fresh(held.get("detail_at"), now):
            view.update(held["detail"])
            view["detail_as_of"] = ls.iso(held["detail_at"])
        else:
            view.update({k: None for k in DETAIL_KEYS[sport]})
            view["detail_as_of"] = None
    return view


def get(sport: str, game_id, now: datetime) -> Optional[dict]:
    """One game's state with the stale guard applied, or None when the game is unknown or its base layer is too old."""
    with _lock:
        held = _GAMES.get((sport, str(game_id)))
    return _view(sport, held, now) if held else None


def fresh_games(sport: str, now: datetime) -> list:
    """Every game of `sport` whose base layer is inside the stale guard, as views (copies: safe to modify)."""
    with _lock:
        items = [(k, dict(v)) for k, v in _GAMES.items() if k[0] == sport]
    out = []
    for _key, held in items:
        view = _view(sport, held, now)
        if view is not None:
            out.append(view)
    return out


def prune(now: datetime, *, keep: timedelta = timedelta(hours=6)) -> int:
    """Drop entries whose base layer is older than `keep` (a finished game is not kept for ever). Returns how many."""
    cut = now - keep
    with _lock:
        dead = [k for k, v in _GAMES.items() if v.get("base_at") is None or v["base_at"] < cut]
        for key in dead:
            _GAMES.pop(key, None)
            _LAST_SIG.pop(key, None)
    return len(dead)


def summary(now: datetime) -> dict:
    """Counts for /health: how many games of each sport are cached, and how many of those are live and fresh."""
    out = {}
    for sport in ("NHL", "TENNIS"):
        games = fresh_games(sport, now)
        out[sport.lower()] = {"fresh": len(games), "live": sum(1 for g in games if g.get("state") == "live")}
    return out


# ---------------------------------------------------------------------------
# the append-only snapshot log
# ---------------------------------------------------------------------------

def default_log_dir() -> Path:
    """live_state/ beside the hounds ledger (the persistent volume in production)."""
    from src.hounds import user_engine
    return Path(user_engine.ledger_path()).parent / LOG_DIR_NAME


def log_path(directory: Path, moment: datetime) -> Path:
    return Path(directory) / f"{moment.astimezone(timezone.utc).strftime('%Y-%m-%d')}.jsonl"


def log_change(sport: str, game_id, row: Mapping, signature, now: datetime, *,
               directory: Optional[Path] = None, seen_live: Optional[Callable[[Mapping], bool]] = None) -> bool:
    """Append `row` for this game when `signature` differs from the one last logged for it. Returns True when a line was written.

    A game first met already FINAL (a restart after the game ended) is not logged: `seen_live(row)` says whether a row is
    a live one, and a non-live row is written only for a game this process has already logged live. That is what keeps the
    log from re-listing the whole day's finals at every deploy."""
    key = (sport, str(game_id))
    with _lock:
        previous = _LAST_SIG.get(key)
    if previous is not None and previous[0] == signature:
        return False
    live_now = True if seen_live is None else bool(seen_live(row))
    if not live_now and (previous is None or not previous[1]):
        return False
    try:
        target = log_path(directory if directory is not None else default_log_dir(), now)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        with open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        STATUS["log_errors"] += 1
        STATUS["last_error"] = f"log: {type(exc).__name__}"
        logger.warning("live state log write failed: %s", str(exc)[:120])
        return False
    with _lock:
        _LAST_SIG[key] = (signature, live_now)
    STATUS["log_rows"] += 1
    STATUS["last_log_utc"] = ls.iso(now)
    return True
