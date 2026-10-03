"""The AI analyst over HTTP: one game's published analysis, and the public record.

    GET /analyst/{date}/{away}/{home}   PAID, the same gate as GET /game/...
    GET /analyst/record                 PUBLIC, counts by market family

THESE ROUTES NEVER CALL THE MODEL. They read `evidence/analyst_v1.jsonl`, the
ledger the daily job writes, and nothing else. A page view cannot spend a cent
and cannot change what was published: the analysis a reader sees is the frozen
row, the same one the record grades. A game with no published row answers
`available: false` with a plain reason, never an error, so a game page for a
game the analyst skipped (started before the run, no prices) still renders.

TWO ROUTERS, ONE PREFIX. `public_router` is mounted before the paid one in
api/app.py so "record" is never captured as a `{date}` (the same arrangement
api/card.py uses for /card/record). The public route carries counts and the
most recent graded calls of finished games only; it never serves a pick for a
game that has not been settled, so it cannot be a free way to read the day's
analysis.

THE LEDGER IS READ ONCE PER CHANGE. Each request used to be a full read of an
append-only file that only grows. `_rows` keeps the parsed rows keyed by the
file's size and modification time, so a grading or a new publication is picked
up on the next request and nothing is served from a stale file.
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from src.analyst import LABEL, config as config_mod, ledger
from src.appstate import ratelimit
from src.paths import repo_root

router = APIRouter()
public_router = APIRouter()

PUBLIC_RATE_LIMIT_PER_MIN = 60
_limiter = ratelimit.FixedWindowLimiter(limit=PUBLIC_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit = ratelimit.limiter_dependency(_limiter)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_lock = threading.Lock()
_cache: dict = {"sig": None, "rows": []}


def _signature() -> tuple:
    target = repo_root() / ledger.STORE
    try:
        st = os.stat(target)
    except OSError:
        return (None, None)
    return (st.st_size, st.st_mtime_ns)


def _rows() -> list:
    sig = _signature()
    with _lock:
        if _cache["sig"] == sig and sig != (None, None):
            return _cache["rows"]
    rows = ledger.rows() if sig != (None, None) else []
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


@router.get("/analyst/{date}/{away}/{home}")
def get_analysis(date: str, away: str, home: str) -> dict:
    """One game's published analysis and its grade, or `available: false`."""
    _validate_date(date)
    view = ledger.game_view(date, away, home, all_rows=_rows())
    if view is None:
        return {"available": False, "label": LABEL, "analysis": None,
                "reason": "No analysis has been published for this game."}
    return {"available": True, "label": LABEL, "analysis": view, "reason": None}


@public_router.get("/analyst/record", dependencies=[Depends(_rate_limit)])
def get_record() -> dict:
    """The analyst's record by market family. Public. Counts always; a win
    rate or a return only once a family has 30 graded calls."""
    min_graded = config_mod.load()["min_graded_for_rates"]
    return ledger.record(all_rows=_rows(), min_graded=min_graded)
