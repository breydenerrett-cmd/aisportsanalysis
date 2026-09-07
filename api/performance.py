"""GET /performance: Task B3's PAPER / RESEARCH PERFORMANCE surface.

Same division of labour as api/opportunities.py: this file only validates
the request and hands it to the pure builder,
`src.report.paper_performance.build_performance_payload`. Nothing here
re-derives a number the report layer already computed.

CACHING: `build_performance_payload` scans every system's paper-account
ledger plus the shared evidence ledgers (wagers, reviews, scorecards) on
every call -- file-system work, not network, but real work all the same
for a surface that does not change faster than a slate settles. Cached
60s via `src.appstate.freshness.SingleFlightTTLCache`, same pattern
api/today.py uses for its own rebuild.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.appstate import freshness
from src.report import paper_performance

router = APIRouter()

# 60s: long enough to absorb a burst of dashboard refreshes, short enough
# that a newly-settled slate shows up within a minute of `engine settle`
# actually running.
PERFORMANCE_CACHE_TTL_S = 60.0

# Module-level so every request shares one cache rather than each call
# building a fresh (and therefore useless) one.
_performance_cache = freshness.SingleFlightTTLCache(ttl_s=PERFORMANCE_CACHE_TTL_S)

MIN_LIMIT, MAX_LIMIT = 1, 200


@router.get("/performance")
def get_performance(limit: int = 50) -> dict:
    """Paper-account standings, class rollups, recent picks and the
    reasoning-outcome split -- `limit` bounds only `recent_picks`.

    Validated here (a plain 400, same as api/games.py's malformed-date
    check) rather than left to FastAPI's `Query(ge=..., le=...)` alone:
    that automatic validation only fires when a request actually reaches
    this route over ASGI, which would make `limit` unverifiable from a
    direct function call the way every other route in this codebase's
    test suite is exercised (tests/test_api_opportunities.py's own
    malformed-date test does the same manual check for the same reason).
    """
    if not (MIN_LIMIT <= limit <= MAX_LIMIT):
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between {MIN_LIMIT} and {MAX_LIMIT} "
                   f"(got {limit!r})")
    payload, _meta = _performance_cache.get(
        ("performance", limit),
        lambda: paper_performance.build_performance_payload(limit=limit),
    )
    return payload
