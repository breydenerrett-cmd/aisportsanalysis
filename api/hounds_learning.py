"""The learning loop's public, read-only routes (docs/PREREG_LEARNING_LOOP.md).

    GET /hounds/learning               the system scorecard: promotion hit rate, champions against the
                                       random controls on the same games, activity and the
                                       false-discovery budget, the pause state and why
    GET /hounds/learning/lessons       every ended challenger's lesson, newest first (?hound=&category=)
    GET /hounds/coach/report           the coach report card: tips made and refused, the live verdicts, and
                                       the last 20 tips with both grades (src/hounds/coach_report.py)
    GET /hounds/{id}/lineage           a hound's versions (each with its own record), its live
                                       challengers, the tried-and-failed list and its lessons

No auth, like the rest of the race: the record is the proof. Nothing here writes, and nothing here is
computed on the request: the scorecard is the day's stored event, the lessons and challengers are small
hash-chained files, the versions come from the cached stats book (``stats.get_book_nowait``, which never
waits for a build).

MOUNT ORDER. ``/hounds/learning`` and ``/hounds/coach/report`` are literal paths under ``/hounds/{id}``: this
router is mounted BEFORE ``api.hounds`` (api/app.py does; a test pins it), or "learning" and "coach" would be read as hound ids. ``/hounds/{id}/lineage`` has
a different shape and cannot collide with it.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from src.hounds import stats, user_defs
from src.hounds.contract import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, warming_payload
from src.hounds.learning import views

router = APIRouter()

_CACHE = "public, max-age=60"
_NO_STORE = "no-store"


@router.get("/hounds/learning")
def learning(response: Response):
    response.headers["Cache-Control"] = _CACHE
    return views.learning_payload()


@router.get("/hounds/learning/lessons")
def learning_lessons(response: Response, hound: Optional[str] = Query(None, max_length=80),
                     category: Optional[str] = Query(None, max_length=40), page: int = Query(1, ge=1),
                     page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
    response.headers["Cache-Control"] = _CACHE
    return views.lessons_payload(None, hound=hound, category=category, page=page, page_size=page_size)


@router.get("/hounds/coach/report")
def coach_report_route(response: Response):
    """Read from the report-card ledger on disk, never from the stores; an absent ledger is a calm
    "the coach has not made a suggestion yet" payload, not a 404."""
    from src.hounds import coach_report
    from src.hounds.learning import coach_brief
    response.headers["Cache-Control"] = _CACHE
    return coach_report.build(coach_on=coach_brief.coach_switch_on())


def _user_versions(hound_id: str) -> list:
    if not user_defs.db_exists():
        return []
    from src.hounds import user_store
    try:
        return user_store.lineage(hound_id)
    except Exception:  # noqa: BLE001 -- an unreadable app database means "not a user hound" here
        return []


@router.get("/hounds/{hound_id}/lineage")
def lineage(hound_id: str, response: Response):
    book, state = stats.get_book_nowait()
    user_versions = _user_versions(hound_id)
    if book is None:
        response.headers["Cache-Control"] = _NO_STORE
        if state == stats.STATE_FAILED:
            raise HTTPException(status_code=503, detail="the hounds could not be worked out right now")
        return warming_payload({"hound_id": hound_id, "versions": [], "live_challengers": [],
                                "tried_and_failed": [], "closed_undecided": [], "promoted": [], "lessons": []})
    known = hound_id in book.hounds or any(i.startswith(hound_id + "@v") for i in book.hounds) or user_versions
    if not known:
        raise HTTPException(status_code=404, detail="no such hound")
    response.headers["Cache-Control"] = _CACHE if state == stats.STATE_FRESH else _NO_STORE
    return views.lineage_view(hound_id, book, user_versions=user_versions)
