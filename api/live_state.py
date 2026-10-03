"""GET /live/{date}: live game state (status, score, inning, outs) for a slate.

Not the internal-testing /live route in api/live.py (research candidates read
from the local poller's files). This one is the public-facing read behind the
live strip on the Today slate and the game page: a thin wrapper over
src.analysis.livestate, which asks the free MLB Stats API schedule/linescore
feed once per slate per 45 seconds however many visitors there are.

Fail soft by contract: an upstream problem is a 200 with `available: false`
and a reason, never a 5xx -- the pages render fine without live state and say
that it is not available. A malformed date is the one 400, same shape as
api/odds.py.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException

from src.analysis import livestate

router = APIRouter()

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Module-level so tests can patch the upstream without the network.
_fetch_schedule = None


@router.get("/live/{date}")
def get_live_state(date: str) -> dict:
    if not isinstance(date, str) or not _ISO_DATE_RE.match(date):
        raise HTTPException(status_code=400,
                            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400,
                            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}") from exc
    return livestate.get_slate(date, fetch_schedule=_fetch_schedule)
