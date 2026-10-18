"""Feeds and briefs a Zapier Zap reads (docs/ZAPS.md). Public, read-only, no auth.

    GET /feeds/kennel.rss     kennel news as RSS 2.0, newest first, at most 30 items (src/hounds/kennel_feed.py)
    GET /feeds/alerts.rss     operator alerts as RSS 2.0; EMPTY while the site is healthy (src/appstate/alert_feed.py)
    GET /hounds/coach-brief   JSON for the weekly coach Zap: the tunable hounds a proposal could reach today,
                              plus the fixed instructions (src/hounds/learning/coach_brief.py)

WHY FEEDS. Zapier counts a task per ACTION run and polling triggers are free, so an event-style Zap polls an
RSS feed and spends a task only when a new ``guid`` appears. Both feeds therefore give every item a stable guid
and the event's own recorded time, never "now".

MOUNT ORDER. ``/hounds/coach-brief`` is a literal path under ``/hounds/{id}``: this router is mounted AFTER
``api.hounds_create`` and ``api.hounds_learning`` and BEFORE ``api.hounds`` (api/app.py does; the tests pin
it), or "coach-brief" would be read as a hound id and answer 404 "no such hound".

NO REQUEST WAITS FOR A BUILD. The kennel feed and the brief read the cached stats book
(``stats.get_book_nowait``). With no book yet they answer 503 with ``Retry-After`` rather than a partial
feed: a Zap that sees a feed missing items would fire them as "new" later, a polling trigger that gets a 503
simply tries again. Nothing here writes. Every payload that is JSON says paper only; the feeds' descriptions
end with the not-advice line.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from src.appstate import alert_feed, apphealth, ratelimit
from src.hounds import kennel_feed, stats
from src.hounds.learning import coach_brief
from src.hounds import rss

router = APIRouter()

_CACHE = "public, max-age=300"
_NO_STORE = "no-store"
RETRY_AFTER_S = "30"

# A Zap polls every few minutes at the fastest. 60 a minute per client is far above that and low enough to
# blunt a script. Keyed on the client address (no sign-in on these routes).
READ_RATE_LIMIT_PER_MIN = 60
_limiter = ratelimit.FixedWindowLimiter(limit=READ_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit = ratelimit.limiter_dependency(_limiter)


def _book_or_503():
    book, _state = stats.get_book_nowait()
    if book is None:
        raise HTTPException(status_code=503, detail="the hounds are warming up; try again in a minute",
                            headers={"Retry-After": RETRY_AFTER_S, "Cache-Control": _NO_STORE})
    return book


def _xml(body: str) -> Response:
    return Response(content=body, media_type=rss.CONTENT_TYPE, headers={"Cache-Control": _CACHE})


@router.get("/feeds/kennel.rss")
def kennel_rss(_rl=Depends(_rate_limit)):
    book = _book_or_503()
    return _xml(kennel_feed.render_feed(kennel_feed.collect(book)))


@router.get("/feeds/alerts.rss")
def alerts_rss(_rl=Depends(_rate_limit)):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    health, error = None, None
    try:
        health = apphealth.report(now=now)
    except Exception as exc:  # noqa: BLE001 -- the alert feed must say the check failed, not 500
        error = f"{type(exc).__name__}"
    alerts = alert_feed.collect(health, alert_feed.pause_facts(), now=now, health_error=error)
    return _xml(alert_feed.render_feed(alerts))


@router.get("/hounds/coach-brief")
def coach_brief_route(response: Response, _rl=Depends(_rate_limit)):
    book = _book_or_503()
    response.headers["Cache-Control"] = _NO_STORE
    return coach_brief.build(book)
