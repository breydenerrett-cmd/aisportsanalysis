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

THE SUPERVISED-SESSION PILOT. Until the analyst has an API key, briefs are written in a supervised
Claude session and published by the same pipeline into their own ledger (`src/analyst/pilot.py`,
`evidence/analyst_pilot_v1.jsonl`). A game is served from the main ledger when it has a row there; only
when it has none is the pilot's row served, with the pilot's label (`PILOT_LABEL`: who wrote it and
how), never the main one, and `provenance: "session_assisted"` in the analysis. `/analyst/record`
carries the pilot's record as a separate `pilot` block and never adds it to the main counts. The
public one-game sample is `api/sample.py`, which reads the same pilot rows.

THE LEDGER IS READ ONCE PER CHANGE. Each request used to be a full read of an
append-only file that only grows. `_load` keeps the parsed rows of BOTH
ledgers keyed by the two files' sizes and modification times, so a grading or a new publication in
either is picked up on the next request and nothing is served from a stale file.
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src.analyst import LABEL, PILOT_LABEL, config as config_mod, ledger, pilot as pilot_mod
from src.appstate import ratelimit
from src.paths import repo_root

router = APIRouter()
public_router = APIRouter()

PUBLIC_RATE_LIMIT_PER_MIN = 60
_limiter = ratelimit.FixedWindowLimiter(limit=PUBLIC_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit = ratelimit.limiter_dependency(_limiter)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_lock = threading.Lock()
_cache: dict = {"sig": None, "rows": [], "pilot": []}
_NO_FILE = (None, None)


def _stat(target) -> tuple:
    try:
        st = os.stat(target)
    except OSError:
        return _NO_FILE
    return (st.st_size, st.st_mtime_ns)


def _signature() -> tuple:
    """(main ledger, pilot ledger), each as (size, mtime) or (None, None) when absent: the cache
    is stale when EITHER file changed."""
    return (_stat(repo_root() / ledger.STORE), _stat(pilot_mod.store_paths()["store"]))


def _load() -> tuple:
    """(main rows, pilot rows), re-read only when a file changed. A missing file reads as no rows."""
    sig = _signature()
    with _lock:
        if _cache["sig"] == sig and sig != (_NO_FILE, _NO_FILE):
            return _cache["rows"], _cache["pilot"]
    rows = ledger.rows() if sig[0] != _NO_FILE else []
    pilot = ledger.rows(pilot_mod.store_paths()["store"]) if sig[1] != _NO_FILE else []
    with _lock:
        _cache["sig"], _cache["rows"], _cache["pilot"] = sig, rows, pilot
    return rows, pilot


def _rows() -> list:
    return _load()[0]


def _pilot_rows() -> list:
    return _load()[1]


def reset_cache_for_tests() -> None:
    with _lock:
        _cache["sig"], _cache["rows"], _cache["pilot"] = None, [], []


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
    if view is not None:
        return {"available": True, "label": LABEL, "analysis": view, "reason": None}
    # No API-written analysis: the supervised-session pilot's row for this game, if there is one.
    # It carries its own label and `provenance`; the page prints the label the server sends.
    view = pilot_view(date, away, home)
    if view is not None:
        return {"available": True, "label": PILOT_LABEL, "analysis": view, "reason": None}
    return {"available": False, "label": LABEL, "analysis": None,
            "reason": "No analysis has been published for this game."}


def pilot_view(date: str, away: str, home: str) -> Optional[dict]:
    """One game's supervised-session analysis (with its grade), or None. Shared with api/sample.py."""
    return ledger.game_view(date, away, home, all_rows=_pilot_rows())


@public_router.get("/analyst/record", dependencies=[Depends(_rate_limit)])
def get_record() -> dict:
    """The analyst's record by market family. Public. Counts always; a win
    rate or a return only once a family has 30 graded calls."""
    min_graded = config_mod.load()["min_graded_for_rates"]
    out = ledger.record(all_rows=_rows(), min_graded=min_graded)
    pilot_rows = _pilot_rows()
    # A separate block, never merged into the counts above: a session-written brief is not the API
    # analyst. Absent (None) until the pilot has published a game.
    out["pilot"] = (dict(ledger.record(all_rows=pilot_rows, min_graded=min_graded), label=PILOT_LABEL)
                    if pilot_rows else None)
    return out
