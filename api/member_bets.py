"""Log a bet: a member's own bet log (docs/plans/MEMBER_BET_LOG.md).

Thin wiring over src/hounds/member_bets.py. Every route needs a signed-in member (free or paid) and is scoped
to ``current_user.id``: a member can only ever read or remove their own bets, and nothing here is public.
The old My Bets router (api/mybets.py) is untouched.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from src.appstate import ratelimit
from src.appstate.users import User
from src.hounds import member_bets

from api.auth import get_current_user

router = APIRouter()

# Same pattern and size as /my-bets: keyed on the signed-in member, sixty a minute.
MEMBER_BETS_RATE_LIMIT_PER_MIN = 60
_limiter = ratelimit.FixedWindowLimiter(limit=MEMBER_BETS_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limited = ratelimit.limiter_dependency(_limiter, user_dependency=get_current_user)


class PlaceBetRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    market: str = Field(max_length=20)
    side: str = Field(max_length=20)
    line: Optional[float] = None
    price: Optional[float] = None
    stake_units: float
    note: Optional[str] = Field(default=None, max_length=400)


class ManualBetRequest(BaseModel):
    sport: str = Field(max_length=20)
    game_text: str = Field(max_length=400)
    side_text: str = Field(max_length=400)
    price: Optional[float] = None
    stake_units: float
    note: Optional[str] = Field(default=None, max_length=400)


def _refuse(exc: member_bets.BetError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/me/bets")
def list_member_bets(current_user: User = Depends(get_current_user)) -> dict:
    return member_bets.member_view(current_user.id)


@router.get("/me/bets/price")
def member_bet_price(event_id: str = Query(min_length=1, max_length=120), market: str = Query(max_length=20),
                     side: str = Query(max_length=20), current_user: User = Depends(get_current_user),
                     _rate_limit: None = Depends(_rate_limited)) -> dict:
    """What the form pre-fills: the board's current average price for a side, or ``price: null``."""
    return member_bets.current_price(event_id, market, side)


@router.post("/me/bets")
def place_member_bet(body: PlaceBetRequest, current_user: User = Depends(get_current_user),
                     _rate_limit: None = Depends(_rate_limited)) -> dict:
    try:
        row = member_bets.place_bet(current_user.id, event_id=body.event_id, market=body.market, side=body.side,
                                    line=body.line, price=body.price, stake_units=body.stake_units, note=body.note)
    except member_bets.BetError as exc:
        raise _refuse(exc)
    return _one(current_user.id, row["bet_id"])


@router.post("/me/bets/manual")
def place_manual_member_bet(body: ManualBetRequest, current_user: User = Depends(get_current_user),
                            _rate_limit: None = Depends(_rate_limited)) -> dict:
    try:
        row = member_bets.place_manual(current_user.id, sport=body.sport, game_text=body.game_text,
                                       side_text=body.side_text, price=body.price,
                                       stake_units=body.stake_units, note=body.note)
    except member_bets.BetError as exc:
        raise _refuse(exc)
    return _one(current_user.id, row["bet_id"])


@router.delete("/me/bets/{bet_id}")
def void_member_bet(bet_id: str = Path(min_length=1, max_length=64),
                    current_user: User = Depends(get_current_user),
                    _rate_limit: None = Depends(_rate_limited)) -> dict:
    try:
        member_bets.void_bet(current_user.id, bet_id)
    except member_bets.BetError as exc:
        raise _refuse(exc)
    return _one(current_user.id, bet_id)


def _one(owner_id, bet_id: str) -> dict:
    return next(b for b in member_bets.member_view(owner_id)["bets"] if b["id"] == bet_id)
