"""The api/ package's FastAPI app: one read-only endpoint, today's slate as JSON.

DEV-ONLY, network-touching wiring lives here so api/today.py's build function
stays importable and testable without FastAPI, without a store on disk, and
without network access. Nothing in src/ knows this file exists.

Not started as a long-running process by anything in this repo's tests or
tooling -- `uvicorn api.app:app` is a human/ops action, not a test fixture.
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import date as date_cls

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from src.appstate import reqlog
from src.pipeline import history
from src.providers import mlb

from api.auth import router as auth_router
from api.billing import router as billing_router
from api.betcheck import router as betcheck_router
from api.games import router as games_router
from api.meta import router as meta_router
from api.odds import router as odds_router
from api.health import router as health_router
from api.mybets import router as mybets_router
from api.today import get_today_payload_cached

app = FastAPI(title="aisportsanalysis api", description=(
    "Read-only. JSON only -- no HTML, no styling. The design gate covers "
    "visuals, not this."))

# GET /health -- no auth, mounted first so it is never shadowed by a
# same-named route added to another router later.
app.include_router(health_router)

# /games/{date}, /game/{date}/{away}/{home}, /changed/{date} -- api/games.py
# owns the fetch-and-build wiring for those three; this file only mounts it,
# the same separation /today keeps between app.py (network) and today.py
# (payload assembly).
app.include_router(games_router)
app.include_router(meta_router)
app.include_router(odds_router)

# auth_router carries the admin invite endpoint (disabled unless
# APP_ADMIN_TOKEN is set -- see api/auth.py); mybets_router requires a
# valid bearer token on every route (api.auth.get_current_user).
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(mybets_router)

# POST /betcheck -- the paid-beta core loop; api/betcheck.py owns the
# fetch-and-build wiring, same separation as the routers above.
app.include_router(betcheck_router)


# -- request logging + structured 500s -------------------------------------
#
# One middleware does both jobs (a per-request log line, and turning an
# unhandled exception into a safe response) rather than splitting them
# across a middleware and a separate app.exception_handler(Exception): by
# the time an exception handler registered on `app` would run, FastAPI's
# own ExceptionMiddleware has already converted every HTTPException this
# codebase raises (401s, 404s, 502s, 400s -- see api/auth.py, api/games.py,
# api/betcheck.py) into its response, so the only thing that can still
# reach this middleware's `except` clause is a genuinely unhandled bug.
# That is exactly the case that must never leak a traceback to the client
# while still being loud on the server -- one error id ties the safe
# client response to the one server-side log line that carries the real
# exception.
@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 -- see comment above
        error_id = uuid.uuid4().hex
        latency_ms = (time.monotonic() - started) * 1000
        print(reqlog.format_line(
            method=request.method, path_template=_route_template(request),
            status=500, latency_ms=latency_ms,
            user_id=getattr(request.state, "user_id", None),
            error_id=error_id),
            file=sys.stderr, flush=True)
        print(f"error_id={error_id} unhandled_exception={exc!r}",
              file=sys.stderr, flush=True)
        return JSONResponse(status_code=500, content={
            "error": "internal_error",
            "error_id": error_id,
            "message": "an unexpected error occurred; this has been logged",
        })
    latency_ms = (time.monotonic() - started) * 1000
    print(reqlog.format_line(
        method=request.method, path_template=_route_template(request),
        status=response.status_code, latency_ms=latency_ms,
        user_id=getattr(request.state, "user_id", None)),
        file=sys.stderr, flush=True)
    return response


def _route_template(request: Request) -> str:
    """The matched route's path pattern (e.g. `/game/{date}/{away}/{home}`),
    never the raw URL -- see src/appstate/reqlog.py's module docstring for
    why. Routing runs inside `call_next`, so `request.scope["route"]` is
    only populated once that has returned; a request that matched no route
    at all (a genuine 404) has none, and falls back to the raw path since
    there is no template to report.
    """
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path


@app.get("/today")
def get_today() -> dict:
    """Today's slate, as JSON, from the real domain path.

    Odds-age metadata rides along on every entry (see api/today.py). Served
    through the freshness cache (120s TTL): a cold-cache provider failure is
    still a 502, but once a good build exists a later failure is absorbed
    into a stale-flagged 200 rather than an outage -- the flag, never a
    silent replay, is the contract.
    """
    today = date_cls.today().isoformat()
    try:
        return get_today_payload_cached(today, fetch_games=mlb.fetch_games,
                                        read_store=history.read_results)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502, detail=f"schedule unavailable: {exc}")
