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
and ``series`` are never read as hound ids.

CACHING. Every route reads ``src.hounds.stats.get_book()``, which rebuilds only
when an input ledger changes size or mtime (a few ``stat`` calls per request)
and never reads a ledger otherwise. The first request after a change pays the
rebuild (a few seconds on the real ledgers); ``stats.warm()`` at process start
moves that off the first visitor.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from src.hounds import stats
from src.hounds.contract import (
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, bets_payload, graveyard_payload,
    hound_payload, leaderboard_payload, paginate, series_payload,
    stream_payload)

router = APIRouter()

_CACHE_HEADER = "public, max-age=60"
MAX_SERIES_IDS = 12


def _book(response: Response):
    response.headers["Cache-Control"] = _CACHE_HEADER
    return stats.get_book()


@router.get("/hounds")
def leaderboard(response: Response):
    book = _book(response)
    return leaderboard_payload(stats.leaderboard(book), book.as_of)


@router.get("/hounds/graveyard")
def graveyard(response: Response):
    book = _book(response)
    return graveyard_payload(stats.graveyard(book), book.as_of)


@router.get("/hounds/stream")
def stream(response: Response, page: int = Query(1, ge=1),
           page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
    book = _book(response)
    return stream_payload(paginate(book.stream, page, page_size), book.as_of)


@router.get("/hounds/series")
def series(response: Response, ids: str = Query("", max_length=2000)):
    book = _book(response)
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:MAX_SERIES_IDS]
    out = {i: book.hounds[i].series for i in wanted if i in book.hounds}
    return series_payload(out, book.as_of)


@router.get("/hounds/{hound_id}")
def hound(hound_id: str, response: Response):
    book = _book(response)
    data = book.hounds.get(hound_id)
    if data is None:
        raise HTTPException(status_code=404, detail="no such hound")
    page = paginate(data.bets, 1, DEFAULT_PAGE_SIZE)
    return hound_payload(data.summary, data.series, page, book.as_of)


@router.get("/hounds/{hound_id}/bets")
def hound_bets(hound_id: str, response: Response, page: int = Query(1, ge=1),
               page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
               segment: Optional[str] = Query(None, pattern="^(forward|replay)$")):
    book = _book(response)
    data = book.hounds.get(hound_id)
    if data is None:
        raise HTTPException(status_code=404, detail="no such hound")
    rows = data.bets if segment is None else [b for b in data.bets if b.segment == segment]
    return bets_payload(hound_id, paginate(rows, page, page_size), book.as_of)
