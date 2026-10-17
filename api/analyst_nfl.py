"""The NFL analyst over HTTP: one game's published brief.

    GET /analyst/nfl/{date}/{away}/{home}   PAID, the same gate as GET /analyst/{date}/{away}/{home}

THESE ROUTES NEVER CALL THE MODEL. They read `evidence/analyst_pilot_nfl_v1.jsonl`, the ledger the
NFL supervised-session pilot writes (`src/analyst/nfl_pilot.py`), and nothing else. A page view
cannot spend a cent and cannot change what was published: the brief a reader sees is the frozen row,
the same one the record grades. A game with no published row answers `available: false` with a plain
reason, never an error.

EVERY NFL BRIEF IS A SUPERVISED-SESSION BRIEF. There is no API-written NFL analyst, so the label is
always `PILOT_LABEL` (who wrote it and how) and the analysis carries `provenance: "session_assisted"`,
the same words as an MLB pilot row. The page prints the label the server sends.

`date` is the game's Eastern calendar date (the schedule's `gameday`), `away` and `home` are the
nflverse club codes ("HOU", "JAX", "LA" for the Rams); "LAR" and "WSH" are read as their codes.

This is the MLB route module (api/analyst.py) for another sport, in its own file so neither can break
the other's paths: the MLB module declares exactly two routes and a test says so. The path has four
segments, so it can never be captured by the MLB route's three or the UFC route's two.

THE LEDGER IS READ ONCE PER CHANGE. `_rows` keeps the parsed rows keyed by the file's size and
modification time, so a new publication or a grading is picked up on the next request.
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException

from src.analyst import PILOT_LABEL, ledger, nfl_pilot
from src.paths import repo_root
from src.sports import nfl_teams

router = APIRouter()

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_lock = threading.Lock()
_cache: dict = {"sig": None, "rows": []}
_NO_FILE = (None, None)


def _signature() -> tuple:
    try:
        st = os.stat(repo_root() / nfl_pilot.STORE)
    except OSError:
        return _NO_FILE
    return (st.st_size, st.st_mtime_ns)


def _rows() -> list:
    sig = _signature()
    with _lock:
        if _cache["sig"] == sig and sig != _NO_FILE:
            return _cache["rows"]
    rows = ledger.rows(nfl_pilot.store_paths()["store"]) if sig != _NO_FILE else []
    with _lock:
        _cache["sig"], _cache["rows"] = sig, rows
    return rows


def reset_cache_for_tests() -> None:
    with _lock:
        _cache["sig"], _cache["rows"] = None, []


def _validate_date(date: str) -> None:
    ok = isinstance(date, str) and _ISO_DATE.match(date)
    if ok:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            ok = False
    if not ok:
        raise HTTPException(status_code=400,
                            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}")


def _code(club: str) -> Optional[str]:
    """A club code from what the URL carries (any spelling `nfl_teams.abbrev` reads), or None."""
    return nfl_teams.abbrev(club) if isinstance(club, str) and len(club) <= 24 else None


def nfl_view(date: str, away: str, home: str) -> Optional[dict]:
    """One NFL game's pilot brief (with its grade), or None. Shared with api/sample.py."""
    a, h = _code(away), _code(home)
    if a is None or h is None:
        return None
    view = ledger.game_view(date, a, h, all_rows=_rows())
    return None if view is None else dict(view, sport="nfl")


@router.get("/analyst/nfl/{date}/{away}/{home}")
def get_nfl_analysis(date: str, away: str, home: str) -> dict:
    """One NFL game's published brief and its grade, or `available: false`."""
    _validate_date(date)
    if _code(away) is None or _code(home) is None:
        raise HTTPException(status_code=400,
                            detail=f"away and home must be NFL club codes (for example HOU and JAX), "
                                   f"got {away!r} and {home!r}")
    view = nfl_view(date, away, home)
    if view is None:
        return {"available": False, "label": PILOT_LABEL, "analysis": None,
                "reason": "No analysis has been published for this game."}
    return {"available": True, "label": PILOT_LABEL, "analysis": view, "reason": None}
