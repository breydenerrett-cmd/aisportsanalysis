"""My Bets: GET/POST/DELETE for the authed user's saved bets.

Thin wiring over src.appstate.savedbets -- this module does no bet logic
of its own, it only authenticates the caller (api.auth.get_current_user)
and scopes every read/write to that user's id. A user can never see or
delete another user's saved bets: every query below is parameterized on
`current_user.id`, never on a client-supplied user id.
"""

from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from starlette.responses import JSONResponse, Response

from src.appstate import ratelimit
from src.appstate import savedbets
from src.appstate.users import User

from api.auth import get_current_user
from api.betcheck import (MAX_PLAUSIBLE_PRICE_MAGNITUDE,
                           MIN_PLAUSIBLE_PRICE_MAGNITUDE)


def _json_safe_validation_error(exc: RequestValidationError) -> JSONResponse:
    """FastAPI's OWN default handler for this exception echoes each
    error's raw offending value back in `input` and then hands the whole
    thing to Starlette's JSONResponse, which serializes with
    `allow_nan=False` (RFC 8259 is stricter than Python's json module).
    Python's json module accepts the non-standard NaN/Infinity/-Infinity
    literals by default, so a client sending one of those as `price`
    reaches pydantic as a real float, is refused the same way any other
    bad price is (SaveBetRequest._sane_price), and would then crash the
    ERROR RESPONSE ITSELF trying to echo `inf`/`nan` back -- turning what
    should be a 422 into a 500. `ctx.error` (an exception object) is not
    JSON-serialisable at all and is dropped for the same reason; the
    human-readable `msg` above it already carries what it said.
    """
    errors = []
    for err in exc.errors():
        err = dict(err)
        err.pop("ctx", None)
        value = err.get("input")
        if isinstance(value, float) and not math.isfinite(value):
            err["input"] = repr(value)   # "inf" / "nan" / "-inf": always safe
        errors.append(err)
    return JSONResponse(status_code=422, content={"detail": errors})


class _JSONSafeErrorRoute(APIRoute):
    """This router's route class: same behaviour as FastAPI's default for
    every other exception, except RequestValidationError gets the
    NaN/Infinity-safe rendering above. See _json_safe_validation_error."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def custom_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                return _json_safe_validation_error(exc)
        return custom_handler


router = APIRouter(route_class=_JSONSafeErrorRoute)

# Keyed on the authenticated user's id (never their IP) -- every route here
# already requires get_current_user, so there is always a stable identity
# to key on regardless of which network the caller shows up from. Sixty a
# minute is generous for a person saving/checking their own bets and tight
# enough to blunt a script hammering this user's row.
MYBETS_RATE_LIMIT_PER_MIN = 60
_mybets_limiter = ratelimit.FixedWindowLimiter(
    limit=MYBETS_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limited = ratelimit.limiter_dependency(
    _mybets_limiter, user_dependency=get_current_user)

# sqlite stores a 64-bit signed INTEGER; a larger id reaches sqlite3 as a
# Python int it cannot bind and raises OverflowError -- a 500 out of a path
# whose only honest answer is "no such bet". Bounding the id at the route
# turns that into the 422 it always was.
_MAX_SQLITE_INT = 2 ** 63 - 1

# game/side/snapshot_digest are free text a client controls end to end (My
# Bets stores what the customer typed or copied, not a value this codebase
# derives) -- unbounded, any of them is an easy way to push an oversized row
# through an authenticated endpoint into sqlite. The bounds below are
# generous over any real value (the longest real matchup label, a short
# saved description, a hex digest) while refusing an arbitrary blob.
MAX_GAME_LENGTH = 120
MAX_SIDE_LENGTH = 40
MAX_SNAPSHOT_DIGEST_LENGTH = 128


class SaveBetRequest(BaseModel):
    """`price`, when given, is an American price and is held to the same
    plausible-magnitude bound POST /betcheck enforces (a two-digit or
    six-digit number is a mis-typed line/total, not a price) -- and must be
    a finite integer.

    The field is typed `float` here, not `int`, on purpose: pydantic's own
    int coercion refuses a non-finite float during type coercion, before
    any validator below ever runs, with an error object that embeds the raw
    `inf`/`nan` value -- and FastAPI's default JSON error-response encoder
    (`allow_nan=False`) then crashes trying to serialize THAT error, a 500
    one step further than the silent-NULL bug this bound exists to close.
    Accepting `float` first lets `_sane_price` catch a non-finite value
    itself and raise a plain, JSON-safe message instead.
    """
    game: str = Field(max_length=MAX_GAME_LENGTH)
    side: str = Field(max_length=MAX_SIDE_LENGTH)
    price: Optional[float] = None
    snapshot_digest: Optional[str] = Field(
        default=None, max_length=MAX_SNAPSHOT_DIGEST_LENGTH)

    @field_validator("price")
    @classmethod
    def _sane_price(cls, value: Optional[float]) -> Optional[int]:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("price must be a finite number, not NaN or "
                             "Infinity")
        if value != int(value):
            raise ValueError(f"{value!r} is not a whole American price")
        price = int(value)
        magnitude = abs(price)
        if not (MIN_PLAUSIBLE_PRICE_MAGNITUDE <= magnitude
                <= MAX_PLAUSIBLE_PRICE_MAGNITUDE):
            raise ValueError(
                f"{price!r} is not a plausible American price (expected "
                "something like -125 or +140)")
        return price


def _serialize(bet: savedbets.SavedBet) -> dict:
    return {
        "id": bet.id,
        "game": bet.game,
        "side": bet.side,
        "price": bet.price,
        "saved_at": bet.saved_at,
        "snapshot_digest": bet.snapshot_digest,
    }


@router.get("/my-bets")
def list_my_bets(current_user: User = Depends(get_current_user)) -> dict:
    bets = savedbets.list_bets(current_user.id)
    return {"bets": [_serialize(b) for b in bets]}


@router.post("/my-bets")
def create_my_bet(body: SaveBetRequest,
                   current_user: User = Depends(get_current_user),
                   _rate_limit: None = Depends(_rate_limited)) -> dict:
    try:
        bet = savedbets.save_bet(
            current_user.id, body.game, body.side,
            price=body.price, snapshot_digest=body.snapshot_digest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _serialize(bet)


@router.delete("/my-bets/{bet_id}")
def delete_my_bet(bet_id: int = Path(ge=1, le=_MAX_SQLITE_INT),
                   current_user: User = Depends(get_current_user)) -> dict:
    deleted = savedbets.delete_bet(bet_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="bet not found")
    return {"deleted": True, "id": bet_id}
