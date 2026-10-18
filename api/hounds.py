"""GET /hounds -- the public, paper-only race of betting strategies.

No auth: like the public record, the hounds are the proof, not the product.
Read-only GET routes only (creating a user hound is ``api/hounds_create.py``).
Every payload carries ``paper_only: true`` and the not-advice line
(``src.hounds.contract.envelope``).

    GET /hounds                      the leaderboard (running + benched hounds)
    GET /hounds/graveyard            retired hounds, each with its cause
    GET /hounds/stream?page=         newest decisions across all hounds, with
                                     refusals marked as such
    GET /hounds/series?ids=a,b,c     cumulative-units series for line charts
    GET /hounds/{id}                 one hound: summary, series, first page of bets
    GET /hounds/{id}/bets?page=      that hound's bets, newest first

Static paths are declared before ``/hounds/{id}`` so ``stream``, ``graveyard``
and ``series`` are never read as hound ids. In the real app
``api/hounds_create.py`` is mounted first and owns ``/hounds/menu`` and
``/hounds/mine`` (tests/test_hounds_routes.py pins the order).

NO REQUEST EVER WAITS FOR A BUILD. Every route asks
``stats.get_book_nowait()``: the cached book if there is one (fresh, or stale
while one background rebuild runs), else a ``warming_up`` payload within a
second (``contract.warming_payload``) while ONE build, serialised with the
app's other cache builds, runs in the background. A cold build streams about
a million odds rows (5 to 10 s on a laptop, more on the 1 GB machine): the
first visitor must not wait for it, and startup must not carry it
(docs/HOUNDS_INTEGRATION.md).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from src.hounds import stats, user_view
from src.hounds.contract import (
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, bets_payload, graveyard_payload,
    hound_payload, leaderboard_payload, paginate, series_payload,
    stream_payload, warming_payload)

router = APIRouter()

_CACHE_HEADER = "public, max-age=60"
_NO_STORE = "no-store"
MAX_SERIES_IDS = 12


def _book(response: Response):
    """``(book, None)`` or ``(None, warming_flag)``; sets the cache header for what it returns.
    Raises 503 when the first build failed (nothing honest to show)."""
    book, state = stats.get_book_nowait()
    if book is None:
        response.headers["Cache-Control"] = _NO_STORE
        if state == stats.STATE_FAILED:
            raise HTTPException(status_code=503, detail="the hounds could not be worked out right "
                                                         "now; try again in a minute")
        return None, True
    # A stale book is served for seconds while its rebuild runs: do not let a shared cache keep it.
    response.headers["Cache-Control"] = _CACHE_HEADER if state == stats.STATE_FRESH else _NO_STORE
    return book, False


@router.get("/hounds")
def leaderboard(response: Response):
    book, warming = _book(response)
    if warming:
        return warming_payload({"hounds": []})
    return leaderboard_payload(stats.leaderboard(book), book.as_of)


@router.get("/hounds/graveyard")
def graveyard(response: Response):
    book, warming = _book(response)
    if warming:
        return warming_payload({"hounds": []})
    return graveyard_payload(stats.graveyard(book), book.as_of)


@router.get("/hounds/stream")
def stream(response: Response, page: int = Query(1, ge=1),
           page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
    book, warming = _book(response)
    if warming:
        return warming_payload({"items": [], "page": page, "page_size": page_size,
                                "total": 0, "pages": 1})
    return stream_payload(paginate(book.stream, page, page_size), book.as_of)


@router.get("/hounds/series")
def series(response: Response, ids: str = Query("", max_length=2000)):
    book, warming = _book(response)
    if warming:
        return warming_payload({"series": {}})
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:MAX_SERIES_IDS]
    out = {i: book.hounds[i].series for i in wanted if i in book.hounds}
    return series_payload(out, book.as_of)


@router.get("/hounds/{hound_id}")
def hound(hound_id: str, response: Response):
    book, warming = _book(response)
    if warming:
        return warming_payload({"id": hound_id})
    data = book.hounds.get(hound_id)
    if data is None:
        # A user hound created after the cached book was built: the person who made it is sent
        # straight to its page, which must not 404 for the few seconds until the rebuild lands.
        payload = user_view.detail(hound_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="no such hound")
        return payload
    page = paginate(data.bets, 1, DEFAULT_PAGE_SIZE)
    return hound_payload(data.summary, data.series, page, book.as_of)


@router.get("/hounds/{hound_id}/bets")
def hound_bets(hound_id: str, response: Response, page: int = Query(1, ge=1),
               page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
               segment: Optional[str] = Query(None, pattern="^(forward|replay)$")):
    book, warming = _book(response)
    if warming:
        return warming_payload({"hound_id": hound_id, "items": [], "page": page,
                                "page_size": page_size, "total": 0, "pages": 1})
    data = book.hounds.get(hound_id)
    if data is None:
        payload = user_view.bets_for(hound_id, page=page, page_size=page_size, segment=segment)
        if payload is None:
            raise HTTPException(status_code=404, detail="no such hound")
        return payload
    rows = data.bets if segment is None else [b for b in data.bets if b.segment == segment]
    return bets_payload(hound_id, paginate(rows, page, page_size), book.as_of)
