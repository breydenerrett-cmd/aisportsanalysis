"""The UFC analyst over HTTP: one event's published analysis, and the public record.

    GET /analyst/ufc/{event_id}   PAID, the same gate as GET /game/... and GET /analyst/...
    GET /analyst/ufc/record       PUBLIC, counts by market family

THESE ROUTES NEVER CALL THE MODEL. They read `evidence/analyst_ufc_v1.jsonl`, the ledger the
UFC analyst writes, and nothing else. A page view cannot spend a cent and cannot change what
was published: the analysis a reader sees is the frozen row, the same one the record grades.
An event with no published row answers `available: false` with a plain reason, never an
error, so a fight-night page for an event the analyst skipped (started before the run, no
prices, fighters not named in the store yet) still renders.

This is the MLB analyst's route module (api/analyst.py) for another sport, in its own file
so neither can break the other's paths: the MLB module declares exactly two routes and a
test says so.

TWO ROUTERS, ONE PREFIX. `public_router` is mounted before the paid one in api/app.py so
"record" is never captured as an `{event_id}`. The public route carries counts and the most
recent graded calls of settled bouts only; it never serves a pick for a bout that has not
been settled, so it cannot be a free way to read the card's analysis.

THE LEDGER IS READ ONCE PER CHANGE. `_rows` keeps the parsed rows keyed by the file's size
and modification time, so a grading or a new publication is picked up on the next request
and nothing is served from a stale file.
"""

from __future__ import annotations

import os
import re
import threading

from fastapi import APIRouter, Depends, HTTPException

from src.analyst import LABEL, config as config_mod, ufc_ledger
from src.appstate import ratelimit
from src.paths import repo_root

router = APIRouter()
public_router = APIRouter()

PUBLIC_RATE_LIMIT_PER_MIN = 60
_limiter = ratelimit.FixedWindowLimiter(limit=PUBLIC_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit = ratelimit.limiter_dependency(_limiter)

# ESPN's event ids are digit strings; letters, digits, dashes and underscores are all a real
# id could need, and nothing else is let through to the ledger lookup.
_EVENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_lock = threading.Lock()
_cache: dict = {"sig": None, "rows": []}


def _signature() -> tuple:
    target = repo_root() / ufc_ledger.STORE
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
    rows = ufc_ledger.rows() if sig != (None, None) else []
    with _lock:
        _cache["sig"], _cache["rows"] = sig, rows
    return rows


def reset_cache_for_tests() -> None:
    with _lock:
        _cache["sig"], _cache["rows"] = None, []


@router.get("/analyst/ufc/{event_id}")
def get_event_analysis(event_id: str) -> dict:
    """One event's published analysis, every bout in card order with its grades, or
    `available: false`."""
    if not isinstance(event_id, str) or not _EVENT_ID.match(event_id):
        raise HTTPException(status_code=400, detail=f"event id is not valid, got {event_id!r}")
    view = ufc_ledger.event_view(event_id, all_rows=_rows())
    if view is None:
        return {"available": False, "label": LABEL, "analysis": None,
                "reason": "No analysis has been published for this event."}
    return {"available": True, "label": LABEL, "analysis": view, "reason": None}


@public_router.get("/analyst/ufc/record", dependencies=[Depends(_rate_limit)])
def get_record() -> dict:
    """The UFC analyst's record by market family. Public. Counts always; a win rate or a
    return only once a family has 30 graded calls. Kept apart from the MLB analyst's record
    and from every card record."""
    min_graded = config_mod.load()["min_graded_for_rates"]
    return ufc_ledger.record(all_rows=_rows(), min_graded=min_graded)
