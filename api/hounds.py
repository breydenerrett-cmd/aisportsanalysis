"""GET /hounds -- the public, paper-only race of betting strategies.

No auth: like the public record, the hounds are the proof, not the product.
Read-only GET routes only (creating a user hound is ``api/hounds_create.py``).
Every payload carries ``paper_only: true`` and the not-advice line
(``src.hounds.contract.envelope``).

    GET /hounds?season=s2|s1|all     the leaderboard (running + benched hounds) for one season (default s2)
    GET /hounds/graveyard            retired hounds, each with its cause
    GET /hounds/digest               the daily Discord post, built by code from the leaderboard
    GET /hounds/stream?page=         newest decisions across all hounds, with
                                     refusals marked as such
    GET /hounds/series?ids=a,b,c     cumulative-units series for line charts (``&season=`` as above)
    GET /hounds/{id}?season=         one hound: summary, series, first page of bets (default s2)
    GET /hounds/{id}/bets?page=      that hound's bets, newest first (``&season=`` filters; absent = all-time)
    GET /hounds/{id}/desk            an AI desk hound's published games (empty before the first publish)
    GET /hounds/{id}/desk/{game}     how the desk argued that game: its transcript and disagreement table

SEASONS (config/seasons.json, src/hounds/seasons.py). A season is a date window over the forward bets: the
record, units, CLV, typical price, last ten and streak a summary carries are worked out from the bets in that
window only (the same ``stats.summarize`` over the windowed bets), while the referee's badge, the status and
the retirement stay all-time. ``?season=`` takes a configured id or ``all``; absent means the newest season
(s2) on every route but ``/bets``, where absent means every bet; anything else is a 422. Each season-aware
payload carries a ``season`` block, and the saved copy is kept per season.

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

A RESTART DOES NOT EMPTY THE RACE FOR A CALLER. The app redeploys hourly, and a once-a-day caller (a
scheduled digest) that landed in the warming window skipped its day. So the leaderboard, graveyard,
stream page 1 and series answer from ``stats.saved_payload`` -- the public payloads the last good build
wrote beside the app db, under 24 h old -- flagged ``stale: true`` with ``as_of`` = when they were built,
while the one rebuild runs. No usable copy: ``warming_up``, as before. The per-hound routes still warm.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from src.hounds import desk_view, digest as digest_mod, seasons, stats, user_view
from src.hounds.contract import (
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, bets_payload, filter_by_status, graveyard_payload,
    hound_payload, leaderboard_payload, paginate, series_payload,
    stream_payload, warming_payload)

router = APIRouter()

_CACHE_HEADER = "public, max-age=60"
_NO_STORE = "no-store"
MAX_SERIES_IDS = 12


def _season(value: Optional[str], default: Optional[str] = None) -> str:
    """The season id ``?season=`` means. Absent: ``default`` (the newest season unless the route says
    otherwise). Not a configured id and not ``all``: 422."""
    if value is None or not value.strip():
        return default if default is not None else seasons.default_id()
    sid = seasons.resolve(value)
    if sid is None:
        raise HTTPException(status_code=422, detail="season must be one of: " + ", ".join(seasons.ids() + [seasons.ALL]))
    return sid


def _book(response: Response):
    """``(book, None)`` or ``(None, warming_flag)``; sets the cache header for what it returns.
    Raises 503 when the first build failed (nothing honest to show)."""
    book, state = stats.get_book_nowait()
    if book is None:
        response.headers["Cache-Control"] = _NO_STORE
        if state == stats.STATE_FAILED and stats.load_snapshot() is None:
            raise HTTPException(status_code=503, detail="the hounds could not be worked out right "
                                                         "now; try again in a minute")
        return None, True
    # A stale book is served for seconds while its rebuild runs: do not let a shared cache keep it.
    response.headers["Cache-Control"] = _CACHE_HEADER if state == stats.STATE_FRESH else _NO_STORE
    return book, False


@router.get("/hounds")
def leaderboard(response: Response, season: Optional[str] = Query(None, max_length=16)):
    sid = _season(season)
    book, warming = _book(response)
    if warming:
        return stats.saved_payload("leaderboard", season=sid) or warming_payload(
            {"hounds": [], "season": seasons.meta(sid)})
    return leaderboard_payload(stats.leaderboard(book, sid), book.as_of, seasons.meta(sid))


@router.get("/hounds/graveyard")
def graveyard(response: Response):
    book, warming = _book(response)
    if warming:
        return stats.saved_payload("graveyard") or warming_payload({"hounds": []})
    return graveyard_payload(stats.graveyard(book), book.as_of)


@router.get("/hounds/digest")
def digest(response: Response):
    """The daily Discord post (src/hounds/digest.py): same book, saved copy and cache headers as
    ``/hounds``, but a caller that cannot be answered gets ``skip: true`` (HTTP 200), never ``warming_up``
    or a 503, because the consumer is a scheduled job that posts whatever ``post`` holds. The live book
    gives last-7-days records; the saved copy has no per-bet rows, so its post uses season records."""
    try:
        book, warming = _book(response)
    except HTTPException:
        return digest_mod.skip_payload()
    coach_line = _coach_digest_line()
    sid = seasons.default_id()      # the post names the dogs of the current season (hot / cold picks use only ranked ones)
    if warming:
        return digest_mod.digest(stats.saved_payload("leaderboard", season=sid), stats.saved_payload("graveyard"),
                                 coach_line=coach_line)
    return digest_mod.digest(leaderboard_payload(stats.leaderboard(book, sid), book.as_of, seasons.meta(sid)),
                             graveyard_payload(stats.graveyard(book), book.as_of),
                             window=digest_mod.week_stats(book.hounds, book.as_of), coach_line=coach_line)


def _coach_digest_line():
    """The coach report card's one digest line, or None before the first tip (or if the ledger cannot be
    read: the digest must still post)."""
    try:
        from src.hounds import coach_report
        return coach_report.digest_line(coach_report.build())
    except Exception:  # noqa: BLE001
        return None


@router.get("/hounds/stream")
def stream(response: Response, page: int = Query(1, ge=1),
           page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
    book, warming = _book(response)
    if warming:
        return stats.saved_payload("stream", page=page, page_size=page_size) or warming_payload(
            {"items": [], "page": page, "page_size": page_size, "total": 0, "pages": 1})
    return stream_payload(paginate(book.stream, page, page_size), book.as_of)


@router.get("/hounds/series")
def series(response: Response, ids: str = Query("", max_length=2000),
           season: Optional[str] = Query(None, max_length=16)):
    sid = _season(season)
    book, warming = _book(response)
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:MAX_SERIES_IDS]
    if warming:
        return stats.saved_payload("series", ids=wanted, season=sid) or warming_payload(
            {"series": {}, "season": seasons.meta(sid)})
    stats.note_series_request([i for i in wanted if i in book.hounds])
    out = {i: book.hounds[i].view(sid).series for i in wanted if i in book.hounds}
    return series_payload(out, book.as_of, seasons.meta(sid))


@router.get("/hounds/{hound_id}")
def hound(hound_id: str, response: Response, season: Optional[str] = Query(None, max_length=16)):
    sid = _season(season)
    book, warming = _book(response)
    if warming:
        return warming_payload({"id": hound_id, "season": seasons.meta(sid)})
    data = book.hounds.get(hound_id)
    if data is None:
        # A user hound created after the cached book was built: the person who made it is sent
        # straight to its page, which must not 404 for the few seconds until the rebuild lands.
        payload = user_view.detail(hound_id, season=sid)
        if payload is None:
            raise HTTPException(status_code=404, detail="no such hound")
        return payload
    view = data.view(sid)
    page = paginate(view.bets, 1, DEFAULT_PAGE_SIZE)
    return hound_payload(view.summary, view.series, page, book.as_of, seasons.meta(sid))


@router.get("/hounds/{hound_id}/bets")
def hound_bets(hound_id: str, response: Response, page: int = Query(1, ge=1),
               page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
               segment: Optional[str] = Query(None, pattern="^(forward|replay)$"),
               status: Optional[str] = Query(None, pattern="^(open|graded)$"),
               season: Optional[str] = Query(None, max_length=16)):
    # Unlike the other routes, no ``season`` here means EVERY bet: a ticket list is a record, and the model
    # page narrows it with a season chip.
    sid = _season(season, default=seasons.ALL)
    book, warming = _book(response)
    if warming:
        return warming_payload({"hound_id": hound_id, "items": [], "page": page,
                                "page_size": page_size, "total": 0, "pages": 1, "season": seasons.meta(sid)})
    data = book.hounds.get(hound_id)
    if data is None:
        payload = user_view.bets_for(hound_id, page=page, page_size=page_size, segment=segment, status=status,
                                     season=sid)
        if payload is None:
            raise HTTPException(status_code=404, detail="no such hound")
        return payload
    view = data.view(sid)
    rows = view.bets if segment is None else [b for b in view.bets if b.segment == segment]
    rows = filter_by_status(rows, status)
    return bets_payload(hound_id, paginate(rows, page, page_size), book.as_of, seasons.meta(sid))


# ---- the AI desk: how it argued ---------------------------------------------------------------------------
#
# Read from the desk's own ledger and per-game folder (src/hounds/desk_view.py), not from the stats book, so
# they answer at once, with or without the book, and before the desk has published anything.

def _desk_hound(hound_id: str) -> None:
    if hound_id not in desk_view.desk_hound_ids():
        raise HTTPException(status_code=404, detail="no such desk hound")


@router.get("/hounds/{hound_id}/desk")
def desk_games(hound_id: str, response: Response):
    _desk_hound(hound_id)
    response.headers["Cache-Control"] = _CACHE_HEADER
    return desk_view.games_for(hound_id)


@router.get("/hounds/{hound_id}/desk/{game_id}")
def desk_game(hound_id: str, game_id: str, response: Response):
    _desk_hound(hound_id)
    payload = desk_view.game_payload(hound_id, game_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="the desk has no such game")
    response.headers["Cache-Control"] = _CACHE_HEADER
    return payload
