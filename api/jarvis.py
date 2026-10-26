"""Owner-only Jarvis briefing: the paper-only pre-game briefing (src/jarvis/), behind the admin token.

    GET  /admin/jarvis/brief?date=YYYY-MM-DD    the latest saved briefing for that date (404 when none yet)
    POST /admin/jarvis/brief  {date, as_of?}    build it now from the stored files, save it, file every pick

Same gate as every other owner route (``api.auth._require_admin``: 404 when no admin token is configured, 401 on a
wrong one). The logic lives in ``src.jarvis`` (importable without FastAPI, which is where it is tested). Building
reads stored files only: no network, no paid API, no model call; a POST is rate limited because it reads the odds
stores. ``as_of`` may not be in the future, and the publish time filed with each pick is always the real clock.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import _require_admin
from src.appstate import ratelimit
from src.jarvis import board, brief

router = APIRouter()
BUILDS_PER_HOUR = 12
_build_limit = ratelimit.limiter_dependency(ratelimit.FixedWindowLimiter(limit=BUILDS_PER_HOUR, window_s=3600.0))


class BriefBody(BaseModel):
    date: str
    as_of: Optional[str] = None
    sport: str = "mlb"


def _valid_date(value: str) -> str:
    try:
        date_cls.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    return value


@router.get("/admin/jarvis/brief")
def get_brief(date: str, _admin: None = Depends(_require_admin)) -> dict:
    found = brief.load_latest(_valid_date(date))
    if found is None:
        raise HTTPException(status_code=404, detail="no briefing has been built for that date yet")
    return found


@router.post("/admin/jarvis/brief")
def post_brief(body: BriefBody, _admin: None = Depends(_require_admin), _limit: None = Depends(_build_limit)) -> dict:
    _valid_date(body.date)
    as_of = None
    if body.as_of:
        as_of = board.parse_time(body.as_of)
        if as_of is None:
            raise HTTPException(status_code=422, detail="as_of must be an ISO time with a zone")
    now = datetime.now(timezone.utc)
    try:
        result = brief.build_briefing(body.date, as_of, sport=body.sport, now=now)
        brief.file_picks(result, now=now)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    brief.save(result)
    return result
