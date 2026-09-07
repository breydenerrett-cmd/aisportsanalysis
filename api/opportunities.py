"""GET /opportunities/{date} and GET /opportunities: Task B2's Top
Opportunities surface.

Same division of labour as api/games.py: this file only fetches inputs
(the cached slate build, `api.games._build_entries`, plus the engine-bridge
join, `src.report.engine_bridge.decisions_for_date`) and hands them to the
pure builder, `src.analysis.opportunities.build_opportunities`. Nothing
here re-derives a number the domain layer already computed.

DATE HANDLING: `GET /opportunities/{date}` validates and builds for that
date (via `_build_entries`, which raises the same 400/502 api/games.py's
routes do). `GET /opportunities` uses UTC-today, the same rule
`api/app.py`'s `GET /today` applies (`date.today().isoformat()`).
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request

from api.games import (_build_entries, _record_page_view,
                       engine_decisions_for_date)
from src.analysis import opportunities as opportunities_mod

router = APIRouter()


def _build_payload(date: str, request: Optional[Request], route: str) -> dict:
    entries, _notes, meta = _build_entries(date)
    engine_by_key = engine_decisions_for_date(date)
    payload = opportunities_mod.build_opportunities(
        entries, date=date, now=datetime.now(timezone.utc),
        engine_by_key=engine_by_key)
    payload["freshness"] = meta
    _record_page_view(request, route, date)
    return payload


@router.get("/opportunities/{date}")
def get_opportunities_for_date(date: str, request: Request = None) -> dict:
    """Top Opportunities for one explicit date."""
    return _build_payload(date, request, "/opportunities/{date}")


@router.get("/opportunities")
def get_opportunities_today(request: Request = None) -> dict:
    """Top Opportunities for UTC-today -- same rule `GET /today` uses."""
    today = date_cls.today().isoformat()
    return _build_payload(today, request, "/opportunities")
