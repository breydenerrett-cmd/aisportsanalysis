"""GET /data/v1/...: the data service's HTTP surface (UFC, then NFL).

This file only serves what the files hold. Every number a route returns is either a
stored record or comes from `src.datasvc.ufc.features` / `matchup` (UFC) or
`src.datasvc.nfl.features` / `matchup` (NFL), which own the leakage rule; nothing here
derives a figure. Same division of labour as api/props.py. The NFL routes
(`/data/v1/nfl/...`, docs/datasvc/NFL_FEATURES.md) share this router, its sign-in, its error
shape and its pagination; each sport has its own store holder, so one sport's files changing
or failing never swaps out or breaks the other's.

THREE THINGS THAT MUST STAY TRUE
--------------------------------
1. The files are never read per request. Production has run out of memory from
   whole-store reads per request before (the same pattern behind the /odds, /games and
   /props fixes). One `UfcStore` is loaded per process by `StoreHolder`; each request
   costs a `stat()` of the six dataset files, and only a changed modification time (or
   size) swaps in a fresh store, which then loads each dataset lazily, once, under a
   lock. A request that began before a swap finishes on the store it started with, so a
   response is always one consistent version of the files. /status reads the
   MANIFEST.json (cached by its own modification time) and falls back to one streaming
   pass per changed file, never one per request.

2. One error shape under /data/v1, whoever raised it: {"error": {"code", "message"}}
   (plus an optional "details" object). That includes the 401/402 raised by the shared
   auth dependency, a validation failure, an unknown path (404), a wrong method (405) and
   an unhandled bug (500, logged with an error id and never a traceback). FastAPI's
   exception handlers are app-wide and api/app.py is not ours to edit, so the router
   uses a route class (`DataRoute`) that converts exceptions raised anywhere inside
   its routes, dependencies included.

3. The same sign-in as the product's other signed-in content routes, ALWAYS. The router
   depends on `require_paid_access` (a valid bearer token, and a 402 for a subscription
   customer whose paid period ended). Unlike /games, /today and /odds it is NOT dropped
   by APP_PUBLIC_DEMO: those are the demo's read-only product surface, and this is the
   bulk data surface the red-team finding 2 gate (2026-09-01) exists to keep behind a
   login. Mounted in api/app.py with one `include_router`.

THE SEAM FOR KEYS AND TIERS (not built yet, on purpose)
-------------------------------------------------------
`data_access` is the only place that decides who may use the data API and with what
limits. It returns a `DataCaller` (who, which tier, how they authenticated) and stores
it on `request.state.data_caller`. The routes read exactly one thing from it today: the
tier's `max_limit`, the page size cap. When API keys and paid tiers arrive, change
`data_access` alone: accept an `X-Api-Key` header ahead of the bearer token, look the
key up, return a `DataCaller` with that key's tier (more datasets, bigger pages, a
quota), and raise the same error shape for a bad key or an exhausted quota. No route
changes. Rate limiting belongs in the same function.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.auth import require_paid_access
from src.datasvc import client
from src.datasvc.client import (  # noqa: F401 -- re-exported: other modules and tests reach these as `datasvc.X`
    DEFAULT_LIMIT, EVENT_STATUSES, GAME_STATUSES, GAME_TYPES, UPCOMING_GRACE, DataUnavailable, NflStoreHolder,
    StoreHolder, _date_key, _query_sig, decode_cursor, encode_cursor, holder, nfl_holder, paginate)
from src.datasvc.client import DataError as ApiError
from src.datasvc.mlb import service as mlb_service
from src.datasvc.nfl import store as nfl_store
from src.datasvc.ufc import features as features_mod
from src.datasvc.ufc import store as ufc_store

API_VERSION = "v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# The holders live in src/datasvc/client.py (the in-process client shares them); this module's clock is
# what tests pin, so the holders follow it, late-bound.
holder.clock = nfl_holder.clock = lambda: _now()


# -- errors -------------------------------------------------------------------------

_DEFAULT_CODES = {400: "bad_request", 401: "unauthorized", 402: "payment_required", 403: "forbidden",
                  404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "invalid_parameter",
                  429: "rate_limited", 500: "internal_error", 503: "unavailable"}


def error_response(status: int, code: str, message: str, details: Optional[dict] = None,
                   headers: Optional[dict] = None) -> JSONResponse:
    body: Dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(status_code=status, content={"error": body}, headers=headers)


def _from_http_exception(exc: StarletteHTTPException) -> JSONResponse:
    """The shared auth dependency raises HTTPException(detail={"error", "message", ...})."""
    detail = exc.detail
    code = _DEFAULT_CODES.get(exc.status_code, "error")
    details = None
    if isinstance(detail, dict):
        code = detail["error"] if isinstance(detail.get("error"), str) else code
        message = detail.get("message") or code.replace("_", " ")
        extra = {k: v for k, v in detail.items() if k not in ("error", "message")}
        details = extra or None
    else:
        message = str(detail) if detail else code.replace("_", " ")
    return error_response(exc.status_code, code, message, details, dict(exc.headers or {}) or None)


def _from_validation_error(exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ())]
        errors.append({"in": loc[0] if loc else None, "param": loc[-1] if loc else None,
                       "message": str(err.get("msg", "invalid"))})
    first = errors[0] if errors else {"param": "request", "message": "invalid"}
    return error_response(422, "invalid_parameter", f"invalid parameter '{first['param']}': {first['message']}",
                          {"errors": errors})


class DataRoute(APIRoute):
    """Every route of this router answers errors in the one shape (module docstring, point 2)."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except ApiError as exc:
                return error_response(exc.status, exc.code, exc.message, exc.details)
            except RequestValidationError as exc:
                return _from_validation_error(exc)
            except StarletteHTTPException as exc:
                return _from_http_exception(exc)
            except DataUnavailable as exc:
                print(f"data api: dataset {exc.dataset!r} could not be read: {exc.__cause__!r}",
                      file=sys.stderr, flush=True)
                return error_response(503, "data_unavailable",
                                      f"the {exc.dataset} dataset is not readable right now; this has been logged")
            except Exception as exc:  # noqa: BLE001 -- surfaced as a safe 500 with an id, never a traceback
                error_id = uuid.uuid4().hex
                print(f"error_id={error_id} data_api_unhandled_exception={exc!r}", file=sys.stderr, flush=True)
                return error_response(500, "internal_error",
                                      f"an unexpected error occurred (error_id={error_id}); this has been logged")

        return handler


# -- who is calling, and the seam for keys and tiers ----------------------------------------

@dataclass(frozen=True)
class Tier:
    name: str
    max_limit: int           # the largest page this tier may ask for


TIERS = {"signed_in": Tier("signed_in", max_limit=100)}
DEFAULT_TIER = "signed_in"


@dataclass(frozen=True)
class DataCaller:
    user_id: Optional[int]
    tier: Tier
    via: str                 # "bearer_token" today; "api_key" when keys exist


def data_access(request: Request, user=Depends(require_paid_access)) -> DataCaller:
    """THE seam: who may use the data API and with what limits (module docstring)."""
    caller = DataCaller(user_id=getattr(user, "id", None), tier=TIERS[DEFAULT_TIER], via="bearer_token")
    request.state.data_caller = caller
    return caller


# -- the store, loaded once ---------------------------------------------------------------------
#
# `holder` and `nfl_holder` are imported from src/datasvc/client.py above (the in-process client shares
# the very same objects, so a process holds each store once).

def use_data_dir(path: Optional[Path]) -> None:
    """Point the API at another directory (tests, or a deployment that keeps the files elsewhere)."""
    holder.set_root(path)


def use_nfl_data_dir(path: Optional[Path]) -> None:
    """Point the NFL routes at another directory (tests, or a deployment that keeps the files elsewhere)."""
    nfl_holder.set_root(path)


def use_mlb_service(service: Optional[mlb_service.MlbService]) -> None:
    """Point the MLB routes at another service (tests), or back at the process's own with None."""
    mlb_service.set_default_service(service)


def _store():
    return holder.store()


def _nfl():
    return nfl_holder.store()


# -- pagination ------------------------------------------------------------------------------

def _page_response(items, key_fn, caller: DataCaller, limit: int, cursor: Optional[str],
                   sig: str, *, descending: bool, render: Callable[[Any], dict]) -> dict:
    return client.page_response(items, key_fn, caller.tier.max_limit, limit, cursor, sig,
                                descending=descending, render=render)


_order = client.order_is_descending
_parse_as_of = client.parse_as_of


router = APIRouter(prefix=f"/data/{API_VERSION}", dependencies=[Depends(data_access)], route_class=DataRoute)


# -- /status ---------------------------------------------------------------------------------------

def _nfl_status(now: datetime) -> dict:
    """The NFL datasets for /status. Fail-soft: an unreadable NFL file is reported in its own entry
    and never turns the UFC half of /status into a 503."""
    datasets = {}
    for name in nfl_store.FILES:
        try:
            datasets[name] = nfl_holder.dataset_status(name, now)
        except DataUnavailable as exc:
            print(f"data api: nfl dataset {name!r} could not be read for /status: {exc.__cause__!r}",
                  file=sys.stderr, flush=True)
            datasets[name] = {"file": nfl_store.FILES[name], "newest_field": nfl_store.DATE_FIELDS.get(name),
                              "present": True, "readable": False, "records": None, "newest": None,
                              "age_seconds": None, "age_days": None, "source": None}
    return {"datasets": datasets, "manifest_generated_utc": nfl_holder.manifest_generated_utc(),
            "coverage": nfl_holder.manifest_extra("coverage"), "attribution": nfl_store.ATTRIBUTION,
            "service": nfl_holder.info(),
            "note": ("For games and team_games `newest` is the newest game that was played (a booked game does "
                     "not count); for player_games it is the newest game with a stat line; for injuries it is the "
                     "time a changed report row was first fetched.")}


def _mlb_status(now: datetime) -> dict:
    """The MLB datasets for /status, from the existing freshness module (src/pipeline/store_freshness.py).
    Fail-soft like the NFL half: a store that cannot be read is reported, and never turns /status into a 503."""
    try:
        return _mlb().status(now)
    except Exception as exc:  # noqa: BLE001 -- /status stays up when one sport's files are broken
        print(f"data api: the mlb datasets could not be measured for /status: {exc!r}", file=sys.stderr, flush=True)
        return {"datasets": None, "readable": False,
                "note": "the MLB datasets could not be measured right now; this has been logged"}


def _mlb() -> mlb_service.MlbService:
    return mlb_service.default_service()


def _http_client() -> client.DataClient:
    """The client the matchup routes build their packet through: strict, so a lookup failure is the route's
    own 404, 409 or 422 and not an `available: false`, and on the API's clock."""
    return client.DataClient(ufc=holder, nfl=nfl_holder, mlb=_mlb(), clock=lambda: _now(), strict=True)


@router.get("/status", summary="Each dataset's record count, newest date and age")
def get_status() -> dict:
    now = _now()
    datasets = {name: holder.dataset_status(name, now) for name in ufc_store.FILES}
    return {"data": {
        "generated_utc": features_mod.iso_utc(now),
        "datasets": datasets,
        "manifest_generated_utc": holder.manifest_generated_utc(),
        "service": holder.info(),
        "note": ("age_seconds is now minus `newest`. For events and bouts `newest` is the newest card or bout "
                 "that took place: booked, postponed and cancelled ones do not count (/data/v1/ufc/upcoming "
                 "lists the booked ones). For odds, fighters and ufccom_profiles `newest` is a fetch time."),
        "nfl": _nfl_status(now),
        "mlb": _mlb_status(now),
    }}


# -- events ------------------------------------------------------------------------------------------

@router.get("/ufc/events", summary="Events, newest first; filter by year and status")
def list_events(year: Optional[int] = Query(None, ge=1990, le=2100), status: Optional[str] = Query(None),
                order: str = Query("desc"), limit: int = Query(DEFAULT_LIMIT, ge=1),
                cursor: Optional[str] = Query(None, max_length=1024),
                caller: DataCaller = Depends(data_access)) -> dict:
    items = client.ufc_events(_store(), year, status)
    descending = _order(order)
    sig = _query_sig(route="events", year=year, status=status, order=order)
    return _page_response(items, client.event_sort_key, caller, limit, cursor, sig, descending=descending,
                          render=client.event_summary)


@router.get("/ufc/events/{event_id}", summary="One event with its bouts")
def get_event(event_id: str) -> dict:
    return {"data": client.ufc_event_detail(_store(), event_id)}


@router.get("/ufc/bouts/{bout_id}", summary="One bout with its fighters, result, statistics rows and odds")
def get_bout(bout_id: str) -> dict:
    return {"data": client.ufc_bout_detail(_store(), bout_id)}


# -- fighters ------------------------------------------------------------------------------------------

@router.get("/ufc/fighters", summary="Search fighters by name, or list them")
def list_fighters(search: Optional[str] = Query(None, min_length=1, max_length=100),
                  limit: int = Query(DEFAULT_LIMIT, ge=1), cursor: Optional[str] = Query(None, max_length=1024),
                  caller: DataCaller = Depends(data_access)) -> dict:
    """With `search`: the best match (200), or 409 listing the candidates when two fit equally well,
    or 404. Without it: a page of every fighter by name."""
    store = _store()
    if search is not None:
        return {"data": client.ufc_fighter_search(store, search)}
    return _page_response(client.ufc_fighters_by_name(store), client.fighter_sort_key, caller,
                          limit, cursor, _query_sig(route="fighters"), descending=False,
                          render=client.fighter_summary)


@router.get("/ufc/fighters/{fighter_id}", summary="One fighter (and the UFC.com profile when there is one)")
def get_fighter(fighter_id: str) -> dict:
    return {"data": client.ufc_fighter_detail(_store(), fighter_id)}


@router.get("/ufc/fighters/{fighter_id}/fights", summary="A fighter's bouts, newest first, upcoming ones included")
def get_fighter_fights(fighter_id: str, limit: int = Query(DEFAULT_LIMIT, ge=1),
                       cursor: Optional[str] = Query(None, max_length=1024),
                       caller: DataCaller = Depends(data_access)) -> dict:
    store = _store()
    bouts = client.ufc_fighter_bouts(store, fighter_id)
    return _page_response(bouts, client.bout_sort_key, caller, limit, cursor,
                          _query_sig(route="fights", fighter=fighter_id), descending=True,
                          render=lambda b: client.fight_item(store, fighter_id, b))


@router.get("/ufc/fighters/{fighter_id}/features", summary="A fighter's leakage-free features as of a moment")
def get_fighter_features(fighter_id: str, as_of: Optional[str] = Query(None, max_length=64)) -> dict:
    cutoff = _parse_as_of(as_of) or _now()
    return {"data": client.ufc_fighter_features(_store(), fighter_id, cutoff)}


# -- matchup and upcoming -------------------------------------------------------------------------------

@router.get("/ufc/matchup", summary="The fact sheet for two fighters (ids or names)")
def get_matchup(a: str = Query(..., min_length=1, max_length=100), b: str = Query(..., min_length=1, max_length=100),
                as_of: Optional[str] = Query(None, max_length=64)) -> dict:
    """`data` is the fact sheet; `meta` carries the ids and provider id mapping, units, sources, coverage,
    missing reasons, `data_version` and how each dataset's history was obtained (docs/datasvc/CLIENT.md)."""
    packet = _http_client().matchup("ufc", a=a, b=b, as_of=as_of)
    return {"data": packet["data"], "meta": packet["meta"]}


@router.get("/ufc/upcoming", summary="Scheduled events with their bouts and current odds, soonest first")
def get_upcoming(days: Optional[int] = Query(None, ge=1, le=365), limit: int = Query(DEFAULT_LIMIT, ge=1),
                 cursor: Optional[str] = Query(None, max_length=1024),
                 caller: DataCaller = Depends(data_access)) -> dict:
    now = _now()
    store = _store()
    items = client.ufc_upcoming_events(store, now, days)
    return _page_response(items, client.event_sort_key, caller, limit, cursor,
                          _query_sig(route="upcoming", days=days), descending=False,
                          render=lambda e: client.upcoming_event(store, e))


# -- NFL ------------------------------------------------------------------------------------------------
#
# Same router, same sign-in, same error shape, same cursor pagination as the UFC routes above.
# Every number is a stored record or comes from `src.datasvc.nfl.features` / `matchup`, which own the
# leakage rule. The NFL files are loaded by their own holder (`nfl_holder`), once per process, and swapped
# in only when one of them changes on disk. Contract: docs/datasvc/NFL_SCHEMA.md and NFL_FEATURES.md.

@router.get("/nfl/games", summary="NFL games, newest first; filter by season, week, team, type and status")
def nfl_list_games(season: Optional[int] = Query(None, ge=1999, le=2100), week: Optional[int] = Query(None, ge=1, le=30),
                   team: Optional[str] = Query(None, max_length=60), game_type: Optional[str] = Query(None, max_length=8),
                   status: Optional[str] = Query(None, max_length=20), order: str = Query("desc"),
                   limit: int = Query(DEFAULT_LIMIT, ge=1), cursor: Optional[str] = Query(None, max_length=1024),
                   caller: DataCaller = Depends(data_access)) -> dict:
    """The stored game records (docs/datasvc/NFL_SCHEMA.md), played and scheduled, chronological order."""
    items = client.nfl_games(_nfl(), season=season, week=week, team=team, game_type=game_type, status=status)
    descending = _order(order)
    sig = _query_sig(route="nfl_games", season=season, week=week, team=client.team_param(team, "team"),
                     game_type=game_type, status=status, order=order)
    return _page_response(items, nfl_store.game_sort_key, caller, limit, cursor, sig, descending=descending,
                          render=lambda g: g)


@router.get("/nfl/games/{game_id}", summary="One NFL game with both teams' rows")
def nfl_get_game(game_id: str) -> dict:
    return {"data": client.nfl_game_detail(_nfl(), game_id)}


@router.get("/nfl/team-games", summary="One row per team per game, newest first")
def nfl_list_team_games(team: Optional[str] = Query(None, max_length=60),
                        season: Optional[int] = Query(None, ge=1999, le=2100), week: Optional[int] = Query(None, ge=1, le=30),
                        game_type: Optional[str] = Query(None, max_length=8), status: Optional[str] = Query(None, max_length=20),
                        order: str = Query("desc"), limit: int = Query(DEFAULT_LIMIT, ge=1),
                        cursor: Optional[str] = Query(None, max_length=1024),
                        caller: DataCaller = Depends(data_access)) -> dict:
    items = client.nfl_team_games(_nfl(), team=team, season=season, week=week, game_type=game_type, status=status)
    descending = _order(order)
    sig = _query_sig(route="nfl_team_games", team=client.team_param(team, "team"), season=season, week=week,
                     game_type=game_type, status=status, order=order)
    return _page_response(items, client.tg_key, caller, limit, cursor, sig, descending=descending, render=lambda r: r)


@router.get("/nfl/player-games", summary="Offensive usage and production per player per game, newest first")
def nfl_list_player_games(player: Optional[str] = Query(None, min_length=1, max_length=100),
                          team: Optional[str] = Query(None, max_length=60), game_id: Optional[str] = Query(None, max_length=40),
                          season: Optional[int] = Query(None, ge=1999, le=2100), week: Optional[int] = Query(None, ge=1, le=30),
                          position_group: Optional[str] = Query(None, max_length=8), order: str = Query("desc"),
                          limit: int = Query(DEFAULT_LIMIT, ge=1), cursor: Optional[str] = Query(None, max_length=1024),
                          caller: DataCaller = Depends(data_access)) -> dict:
    """`player` is a player id or a name (an id wins; two equally good name matches are a 409)."""
    code = client.team_param(team, "team")
    client.choice(position_group, "position_group", nfl_store.POSITION_GROUP_ORDER)
    descending = _order(order)
    items, pid = client.nfl_player_games(_nfl(), player=player, team=team, game_id=game_id, season=season, week=week,
                                         position_group=position_group)
    sig = _query_sig(route="nfl_player_games", player=pid, team=code, game_id=game_id, season=season, week=week,
                     position_group=position_group, order=order)
    return _page_response(items, client.pg_key, caller, limit, cursor, sig, descending=descending, render=lambda r: r)


@router.get("/nfl/injuries", summary="Injury report rows (designated or limited players), newest first")
def nfl_list_injuries(game_id: Optional[str] = Query(None, max_length=40), team: Optional[str] = Query(None, max_length=60),
                      season: Optional[int] = Query(None, ge=1999, le=2100), week: Optional[int] = Query(None, ge=1, le=30),
                      player_id: Optional[str] = Query(None, max_length=20),
                      position_group: Optional[str] = Query(None, max_length=8),
                      report_status: Optional[str] = Query(None, max_length=20), order: str = Query("desc"),
                      limit: int = Query(DEFAULT_LIMIT, ge=1), cursor: Optional[str] = Query(None, max_length=1024),
                      caller: DataCaller = Depends(data_access)) -> dict:
    code = client.team_param(team, "team")
    descending = _order(order)
    items = client.nfl_injuries(_nfl(), game_id=game_id, team=team, season=season, week=week, player_id=player_id,
                                position_group=position_group, report_status=report_status)
    sig = _query_sig(route="nfl_injuries", game_id=game_id, team=code, season=season, week=week, player_id=player_id,
                     position_group=position_group, report_status=report_status, order=order)
    return _page_response(items, client.inj_key, caller, limit, cursor, sig, descending=descending, render=lambda r: r)


@router.get("/nfl/matchup", summary="The fact sheet for one game (a game id, or two teams)")
def nfl_get_matchup(game_id: Optional[str] = Query(None, max_length=40), a: Optional[str] = Query(None, max_length=60),
                    b: Optional[str] = Query(None, max_length=60), season: Optional[int] = Query(None, ge=1999, le=2100),
                    week: Optional[int] = Query(None, ge=1, le=30), as_of: Optional[str] = Query(None, max_length=64)) -> dict:
    """`game_id`, or `a` and `b` (team codes or names, either of them home): the next game between them that
    has not kicked off, else the latest (`season` and `week` pick one). `as_of` defaults to the kickoff and
    may not be later than it. `meta` as for /ufc/matchup."""
    packet = _http_client().matchup("nfl", game_id=game_id, a=a, b=b, season=season, week=week, as_of=as_of)
    return {"data": packet["data"], "meta": packet["meta"]}


@router.get("/nfl/teams/{team}/features", summary="A team's leakage-free form as of a moment")
def nfl_team_features(team: str, as_of: Optional[str] = Query(None, max_length=64),
                      season: Optional[int] = Query(None, ge=1999, le=2100)) -> dict:
    cutoff = _parse_as_of(as_of) or _now()
    return {"data": client.nfl_team_features_as_of(_nfl(), team, cutoff, season=season)}


@router.get("/nfl/players/{player}/features",
            summary="A player's recent usage and production over his last 3 and 5 games, as of a moment")
def nfl_player_features(player: str, as_of: Optional[str] = Query(None, max_length=64)) -> dict:
    """`player` is a player id or a name."""
    cutoff = _parse_as_of(as_of) or _now()
    return {"data": client.nfl_player_features_as_of(_nfl(), player, cutoff)}


# -- MLB: the existing services through the same door --------------------------------------------------------
#
# Wrappers only (src/datasvc/mlb/service.py): the schedule and results, and the analyst's evidence packet as
# `src/analyst/packet.py` builds it. Read-only: serving a packet publishes nothing and calls no model. Keeps MLB's
# own shapes; the envelope (`meta`) is the same as UFC and NFL.

_REFUSAL_STATUS = {"not_found": 404, "ambiguous": 409, "no_data": 404, "unavailable": 503}
_REFUSAL_CODE = {"not_found": "not_found", "ambiguous": "ambiguous_game", "no_data": "not_found",
                 "unavailable": "data_unavailable"}


def _refusal(result: dict) -> ApiError:
    """An `available: false` answer from the MLB service as the one error shape."""
    first = (result.get("missing") or [{}])[0]
    code = first.get("code", "unavailable")
    return ApiError(_REFUSAL_STATUS.get(code, 503), _REFUSAL_CODE.get(code, "data_unavailable"),
                    first.get("reason") or "no data", {"missing": result.get("missing")})


@router.get("/mlb/games", summary="MLB games for a date, results for final games")
def mlb_list_games(date: str = Query(..., min_length=10, max_length=10), limit: int = Query(DEFAULT_LIMIT, ge=1),
                   cursor: Optional[str] = Query(None, max_length=1024),
                   caller: DataCaller = Depends(data_access)) -> dict:
    """`data` is the day's games in schedule order with MLB's own shape; `meta` says when the schedule was read,
    that a played game's probable starter is retroactive, how fresh each store is, and what is missing."""
    result = _mlb().games(date, now=_now())
    if not result["available"]:
        raise _refusal(result)
    page = _page_response(result["data"], lambda r: (r["start_time_utc"] or "", str(r["game_pk"])), caller, limit,
                          cursor, _query_sig(route="mlb_games", date=date), descending=False, render=lambda r: r)
    page["meta"] = result["meta"]
    return page


@router.get("/mlb/games/{date}/{away}/{home}/packet",
            summary="The analyst's frozen evidence packet for one game (read-only, never published)")
def mlb_get_packet(date: str, away: str, home: str) -> dict:
    """`data` is the packet exactly as `src/analyst/packet.py` builds it (its `packet_hash` is in `meta`); `meta`
    carries the ids and provider id mapping, units, each source's identity and basis (observed at the time or
    reconstructed later), coverage, missing reasons and the `data_version`."""
    result = _mlb().packet(date, away, home, now=_now())
    if not result["available"]:
        raise _refusal(result)
    return {"data": result["data"], "meta": result["meta"]}


# -- anything else under /data/v1 -------------------------------------------------------------------------

@router.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                  include_in_schema=False)
def no_such_route(request: Request, path: str) -> dict:
    """404 for an unknown path, 405 (with Allow) when the path exists under other methods."""
    allowed = set()
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path != f"/data/{API_VERSION}/{{path:path}}" \
                and route.path_regex.match(request.url.path):
            allowed |= set(route.methods or ())
    if allowed:
        raise StarletteHTTPException(status_code=405, detail="method not allowed",
                                     headers={"Allow": ", ".join(sorted(allowed))})
    raise ApiError(404, "not_found", f"no such route: {request.url.path}")
