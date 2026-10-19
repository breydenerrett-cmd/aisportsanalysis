"""Seasons: a date window over the forward bets, so a model that started on Oct 18 is not ranked against one
that started on Aug 31.

``config/seasons.json`` is a list of ``{id, label, start, end}`` (dates are the slate dates every bet already
carries, ``Bet.date``, which is MLB's official date of the game: the EASTERN calendar date of first pitch,
``snapshots.official_date`` / ``pack.base.eastern_date``; not UTC, not Pacific; ``end: null`` is the open season). A season is a VIEW: nothing is deleted, no ledger is
touched, every bet stays in the all-time view (``ALL``). Both ends are inclusive.

  * ``DEFAULT_SEASON`` ("s2") is what every route answers when ``?season=`` is absent.
  * ``MIN_RANKED_BETS`` (10) is the number of SETTLED bets (win, loss or push in the view) a model needs to be
    ranked in that view. Below it a model is "warming up": its record so far is shown, it is never ranked.
  * The referee's verdict badge is NOT windowed: it stays all-time (stats.summarize_window keeps it).

Standard library only (no FastAPI), so the module loads where the app does not.
"""

from __future__ import annotations

import json
import os
from datetime import date as date_cls
from pathlib import Path
from typing import Optional

from src.paths import repo_root

ALL = "all"
DEFAULT_SEASON = "s2"
MIN_RANKED_BETS = 10

#: what is used if the config file is missing or unreadable (the owner's 2026-10-19 decision)
_FALLBACK = (
    {"id": "s1", "label": "Season 1", "start": "2026-08-31", "end": "2026-10-17"},
    {"id": "s2", "label": "Season 2", "start": "2026-10-18", "end": None},
)

_CACHE: dict = {"key": None, "seasons": None}


def config_path() -> Path:
    return repo_root() / "config" / "seasons.json"


def _clean_day(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value)[:10]
    try:
        return date_cls.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _parse(raw) -> list:
    out = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] == ALL:
            continue
        start = _clean_day(row.get("start"))
        if start is None:
            continue
        out.append({"id": row["id"], "label": str(row.get("label") or row["id"]), "start": start,
                    "end": _clean_day(row.get("end"))})
    return out


def load() -> list:
    """The configured seasons, oldest first. Re-read when the file's size or mtime changes."""
    path = config_path()
    try:
        st = os.stat(path)
        key = (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        key = (str(path), None, None)
    if _CACHE["key"] == key and _CACHE["seasons"] is not None:
        return _CACHE["seasons"]
    seasons: list = []
    try:
        seasons = _parse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seasons = []
    if not seasons:
        seasons = _parse(list(_FALLBACK))
    seasons.sort(key=lambda s: s["start"])
    _CACHE["key"], _CACHE["seasons"] = key, seasons
    return seasons


def ids() -> list:
    return [s["id"] for s in load()]


def get(season_id: str) -> Optional[dict]:
    return next((s for s in load() if s["id"] == season_id), None)


def default_id() -> str:
    """``DEFAULT_SEASON`` if it is configured, else the newest configured season."""
    return DEFAULT_SEASON if get(DEFAULT_SEASON) else load()[-1]["id"]


def resolve(value) -> Optional[str]:
    """The season id a ``?season=`` value means: absent or empty is the default; ``all`` or a configured id is
    itself; anything else is None (the route answers 422)."""
    text = str(value).strip().lower() if value is not None else ""
    if not text:
        return default_id()
    if text == ALL or get(text):
        return text
    return None


def in_window(day, season_id: str) -> bool:
    """Is the slate date ``day`` inside the season (``all`` takes every date)? Both ends inclusive. A bet with
    no readable date is in no season window (it stays in the all-time view)."""
    if season_id == ALL:
        return True
    season = get(season_id)
    text = str(day or "")[:10]
    if season is None or len(text) != 10:
        return False
    return text >= season["start"] and (season["end"] is None or text <= season["end"])


def meta(season_id: str) -> dict:
    """The ``season`` block every season-aware payload carries."""
    season = get(season_id)
    return {"id": season_id,
            "label": "All-time" if season_id == ALL else (season or {}).get("label", season_id),
            "start": season["start"] if season else None, "end": season["end"] if season else None,
            "all_time": season_id == ALL, "default": default_id(), "min_ranked_bets": MIN_RANKED_BETS,
            "available": [{"id": s["id"], "label": s["label"], "start": s["start"], "end": s["end"]} for s in load()]
            + [{"id": ALL, "label": "All-time", "start": None, "end": None}]}
