"""The api/ package's FastAPI app: one read-only endpoint, today's slate as JSON.

DEV-ONLY, network-touching wiring lives here so api/today.py's build function
stays importable and testable without FastAPI, without a store on disk, and
without network access. Nothing in src/ knows this file exists.

Not started as a long-running process by anything in this repo's tests or
tooling -- `uvicorn api.app:app` is a human/ops action, not a test fixture.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import date as date_cls

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.appstate import reqlog
from src.pipeline import history
from src.providers import mlb

from api.admin import router as admin_router
from api.auth import get_current_user, require_paid_access, router as auth_router
from fastapi import Depends
from api.billing import router as billing_router
from api.onboarding import router as onboarding_router
from api.signup import router as signup_router
from api.support import router as support_router
from api.betcheck import free_router as free_betcheck_router, router as betcheck_router
from api.daily import router as daily_router
from api.games import router as games_router
from api.card import router as card_router
from api.opportunities import router as opportunities_router
from api.performance import router as performance_router
from api.props import router as props_router
from api.meta import router as meta_router
from api.web import router as web_router
from api.odds import router as odds_router
from api.health import router as health_router
from api.mybets import router as mybets_router
from api.digest import router as digest_router
from api.funnel import router as funnel_router
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
# Private alpha: the whole game surface requires auth (red-team finding 2,
# 2026-09-01). /health and /meta stay open; revisit if a free tier is decided.
_authed = [Depends(get_current_user)]
# The paid surface carries a SECOND gate on top of auth: a subscription
# customer whose paid period has ended gets a 402 here, while an
# invite-token beta user (no subscription record at all) is untouched --
# see api/auth.py's require_paid_access. Deliberately narrow: /billing/*,
# /support, signup and the funnel beacon stay reachable so an expired
# customer can actually reactivate or re-subscribe.
#
# PUBLIC DEMO MODE (APP_PUBLIC_DEMO=1, owner decision 2026-09-07): the
# READ-ONLY game surface (/today, /games, /game, /changed, /odds), Bet Check
# and the performance/opportunities routes are served with NO bearer token
# so the hosted demo can be opened by anyone holding the staging URL.
# Default OFF -- unset or anything but 1/true/yes keeps red-team finding 2's
# private-alpha gate exactly as it was, and every test that pins a 401 on
# this surface runs with the variable unset. Personal routes (/my-bets,
# /digest, /onboarding, admin, billing) never loosen: they carry `_authed`
# or their own guards regardless of this flag. Flip it in
# deploy/fly.staging.toml's [env]; it is not a secret.
ENV_PUBLIC_DEMO = "APP_PUBLIC_DEMO"
PUBLIC_DEMO = (os.environ.get(ENV_PUBLIC_DEMO) or "").strip().lower() in (
    "1", "true", "yes")
_authed_paid = [] if PUBLIC_DEMO else [Depends(require_paid_access)]
app.include_router(games_router, dependencies=_authed_paid)
# /opportunities/{date}, /opportunities -- Task B2's Top Opportunities
# surface, same paid-demo gate as the rest of the read-only game surface.
app.include_router(opportunities_router, dependencies=_authed_paid)
# /card/{date}, /card -- THE CARD, the three-to-five bets the front page
# leads with. Paid, like every other read-only game surface: it is the
# product, and the free surface is Bet Check.
app.include_router(card_router, dependencies=_authed_paid)
# /performance -- Task B3's Paper / Research Performance surface, same
# paid-demo gate as the rest of the read-only game surface.
app.include_router(performance_router, dependencies=_authed_paid)
# /props/{date}, /props -- the player-prop board. Paid, like every other
# read-only game surface. It is a BOARD and not a card: ranked by how likely
# each outcome is, never by the gap against its price, because selecting on
# that gap was measured at -13.4% against a -9.1% control.
app.include_router(props_router, dependencies=_authed_paid)
# /daily, /daily/{date}, /record -- Task C1's Frozen Pregame Record surface,
# same paid-demo gate as the rest of the read-only game surface.
app.include_router(daily_router, dependencies=_authed_paid)
app.include_router(meta_router)
app.include_router(web_router)
app.include_router(odds_router, dependencies=_authed_paid)

# auth_router carries the admin invite endpoint (disabled unless
# APP_ADMIN_TOKEN is set -- see api/auth.py); mybets_router requires a
# valid bearer token on every route (api.auth.get_current_user).
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(billing_router)
# support mounts WITHOUT the authed dependency: POST /support accepts
# anonymous-with-email by design; its /admin routes carry their own guard.
app.include_router(support_router)
# signup is public by design (pre-account); its own rate limits apply.
app.include_router(signup_router)
app.include_router(funnel_router)
app.include_router(onboarding_router, dependencies=_authed)
app.include_router(mybets_router)
# GET /digest -- authed, same as the game surface (private alpha, red-team
# finding 2, 2026-09-01): a personal digest is at least as sensitive as the
# slate itself.
app.include_router(digest_router, dependencies=_authed)

# POST /betcheck -- the paid-beta core loop; api/betcheck.py owns the
# fetch-and-build wiring, same separation as the routers above.
app.include_router(betcheck_router, dependencies=_authed_paid)

# POST /betcheck/free -- deliberately mounted with NO auth dependency: it is
# the landing page's "3 Bet Checks, no card required" offer, which cannot be
# honoured behind the login wall the rest of the game surface sits behind.
# It is not a hole in red-team finding 2's decision: the free route serves
# one game's check per call, is capped at three per server-minted anonymous
# identity for life (src/appstate/freechecks.py), and carries its own tight
# per-IP hourly limiter -- none of which lets it become the bulk slate/odds
# surface that finding was about.
app.include_router(free_betcheck_router)


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


# -- customer entry points -------------------------------------------------
#
# api/web.py serves the client under the /web prefix, which is a deployment
# detail no visitor can be expected to type: the bare origin answered with
# the default JSON 404 (found on linehound-staging, 2026-09-01). These two
# routes are the human-facing doors onto that mount.
#
# REDIRECT, NEVER A FileResponse AT "/". web/landing.html references its
# css/js by RELATIVE path, so serving its bytes at the root would resolve
# every asset URL against "/" instead of "/web/" and silently break the
# whole page. A redirect moves the browser's base URL, which is the thing
# those relative paths actually depend on. 307 (not 301/302) so the method
# is preserved and nothing is cached permanently while these paths are
# still moving.
@app.get("/", include_in_schema=False)
def root_redirect(request: Request) -> RedirectResponse:
    """The bare origin -> the marketing landing page. No auth: this is the
    first thing a prospective customer ever hits.

    THE QUERY STRING IS CARRIED ACROSS, and that is load-bearing. Every
    campaign link anyone will ever share points at the bare origin with
    UTM parameters on it -- linehound.app/?utm_source=reddit -- and this
    redirect used to drop them, so web/js/landing.js read an empty
    `window.location.search` and recorded an unattributed landing view.
    Found 2026-09-10 by sending a real UTM link at a running server and
    reading the row it wrote: `properties_json` came back `{}`.

    The whole attribution feature would have shipped, passed its tests,
    and silently measured nothing -- every visitor an organic one, on the
    exact metric the outreach plan is meant to be steered by."""
    query = request.url.query
    target = "/web/landing.html" + (f"?{query}" if query else "")
    return RedirectResponse(url=target, status_code=307)


@app.get("/app", include_in_schema=False)
def app_shell_redirect() -> RedirectResponse:
    """The signed-in shell -> api/web.py's directory entry point, which
    serves web/index.html. Same no-auth reasoning api/web.py's own module
    docstring gives: the token-entry form has to be reachable without a
    token, or nobody could ever enter one.

    TRAILING SLASH, ALWAYS. web/index.html loads css/js by RELATIVE path
    (same as landing.html, see root_redirect above). At `/web` the browser
    resolves those against `/`, every asset 404s and the page is a blank
    wordmark -- found on linehound-staging 2026-09-07. At `/web/` they
    resolve under `/web/` and the shell renders."""
    return RedirectResponse(url="/web/", status_code=307)


@app.get("/today", dependencies=_authed_paid)
def get_today(request: Request) -> dict:
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
                                        read_store=history.read_results,
                                        user_id=getattr(request.state, "user_id", None))
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502, detail=f"schedule unavailable: {exc}")
