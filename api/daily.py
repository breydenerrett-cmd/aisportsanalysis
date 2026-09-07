"""GET /daily, GET /daily/{date}, GET /record: Task C1's FROZEN PREGAME
RECORD surface.

Same division of labour as api/performance.py: this file only validates the
request, stamps `generated_at`, and hands everything else to the pure
builders in `src.report.daily_record`. Nothing here re-derives a number the
report layer already computed, and nothing here reads a clock except the
one legitimate use -- `GET /record`'s `today` (`src.report.daily_record`
itself never calls `date.today()`, by design; see that module's docstring).

CACHING: same pattern as api/performance.py and api/today.py -- each route
scans the decision/wager/account ledgers on every call, real filesystem
work for a surface that changes only as fast as a slate settles. Cached
60s via `src.appstate.freshness.SingleFlightTTLCache`, one cache instance
per route so a burst of `/daily/{date}` requests for different dates does
not evict `GET /daily`'s own cached index (or vice versa).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src.appstate import freshness
from src.report import daily_record

router = APIRouter()

DAILY_INDEX_CACHE_TTL_S = 60.0
DAILY_RECORD_CACHE_TTL_S = 60.0
RECORD_STRIP_CACHE_TTL_S = 60.0

# One cache per route -- same rationale as api/games.py's shared
# `_entries_cache`, split three ways here since the three routes key on
# different things (a limit, a date, nothing) and share no rebuild step.
_daily_index_cache = freshness.SingleFlightTTLCache(ttl_s=DAILY_INDEX_CACHE_TTL_S)
_daily_record_cache = freshness.SingleFlightTTLCache(ttl_s=DAILY_RECORD_CACHE_TTL_S)
_record_strip_cache = freshness.SingleFlightTTLCache(ttl_s=RECORD_STRIP_CACHE_TTL_S)

MIN_LIMIT, MAX_LIMIT = 1, 200

# Same shape/rationale as api/games.py's _ISO_DATE_RE / _validate_date: a
# malformed {date} path segment gets a 400 here, before it ever reaches a
# report-layer function that would otherwise just silently match nothing.
_ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _validate_date(date: str) -> None:
    if not isinstance(date, str) or not _ISO_DATE_RE.match(date):
        raise HTTPException(
            status_code=400,
            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}") from exc


def _stamped(payload: dict) -> dict:
    payload = dict(payload)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


@router.get("/daily")
def get_daily_index(limit: int = 30) -> dict:
    """Newest-first daily-recap gallery: one row per date with at least one
    engine decision or paper wager, up to `limit` dates.

    `limit` is validated here, not left to FastAPI's `Query(ge=..., le=...)`
    alone -- same reasoning as api/performance.py's own `get_performance`:
    a direct function call (this codebase's own test style) never runs
    FastAPI's request-parsing layer at all.
    """
    if not (MIN_LIMIT <= limit <= MAX_LIMIT):
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between {MIN_LIMIT} and {MAX_LIMIT} "
                   f"(got {limit!r})")
    rows, _meta = _daily_index_cache.get(
        ("daily_index", limit),
        lambda: daily_record.day_index(limit=limit),
    )
    return _stamped({"days": rows})


@router.get("/daily/{date}")
def get_daily_record(date: str) -> dict:
    """One day's FROZEN PREGAME RECORD -- see src.report.daily_record.day_record."""
    _validate_date(date)
    payload, _meta = _daily_record_cache.get(
        ("daily_record", date),
        lambda: daily_record.day_record(date),
    )
    return _stamped(payload)


@router.get("/record")
def get_record_strip() -> dict:
    """TODAY / LAST 7 DAYS / LAST 30 DAYS units-net tiles.

    `today` is read from the wall clock HERE -- the one legitimate clock
    read for this whole surface (src.report.daily_record itself never
    calls date.today(); see that module's docstring) -- and passed in as a
    plain ISO date, UTC, same convention api/opportunities.py's
    `get_opportunities_today` already uses for "today".
    """
    today = datetime.now(timezone.utc).date().isoformat()
    payload, _meta = _record_strip_cache.get(
        ("record_strip", today),
        lambda: daily_record.record_strip(today=today),
    )
    return _stamped(payload)
