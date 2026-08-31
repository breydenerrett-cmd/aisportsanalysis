"""The api/ package's FastAPI app: one read-only endpoint, today's slate as JSON.

DEV-ONLY, network-touching wiring lives here so api/today.py's build function
stays importable and testable without FastAPI, without a store on disk, and
without network access. Nothing in src/ knows this file exists.

Not started as a long-running process by anything in this repo's tests or
tooling -- `uvicorn api.app:app` is a human/ops action, not a test fixture.
"""

from __future__ import annotations

from datetime import date as date_cls

from fastapi import FastAPI, HTTPException

from src.pipeline import history
from src.providers import mlb

from api.auth import router as auth_router
from api.betcheck import router as betcheck_router
from api.games import router as games_router
from api.mybets import router as mybets_router
from api.today import build_today_payload

app = FastAPI(title="aisportsanalysis api", description=(
    "Read-only. JSON only -- no HTML, no styling. The design gate covers "
    "visuals, not this."))

# /games/{date}, /game/{date}/{away}/{home}, /changed/{date} -- api/games.py
# owns the fetch-and-build wiring for those three; this file only mounts it,
# the same separation /today keeps between app.py (network) and today.py
# (payload assembly).
app.include_router(games_router)

# auth_router carries the admin invite endpoint (disabled unless
# APP_ADMIN_TOKEN is set -- see api/auth.py); mybets_router requires a
# valid bearer token on every route (api.auth.get_current_user).
app.include_router(auth_router)
app.include_router(mybets_router)

# POST /betcheck -- the paid-beta core loop; api/betcheck.py owns the
# fetch-and-build wiring, same separation as the routers above.
app.include_router(betcheck_router)


@app.get("/today")
def get_today() -> dict:
    """Today's slate, as JSON, from the real domain path.

    Odds-age metadata rides along on every entry (see api/today.py). This
    endpoint does not compute anything the domain layer does not already
    compute -- it only fetches today's games, loads the historical store,
    and hands both to build_today_payload.
    """
    today = date_cls.today().isoformat()
    try:
        games = mlb.fetch_games(today)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502, detail=f"schedule unavailable: {exc}")
    store = history.read_results()
    return build_today_payload(games, store, date=today)
