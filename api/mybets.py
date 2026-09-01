"""My Bets: GET/POST/DELETE for the authed user's saved bets.

Thin wiring over src.appstate.savedbets -- this module does no bet logic
of its own, it only authenticates the caller (api.auth.get_current_user)
and scopes every read/write to that user's id. A user can never see or
delete another user's saved bets: every query below is parameterized on
`current_user.id`, never on a client-supplied user id.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from src.appstate import savedbets
from src.appstate.users import User

from api.auth import get_current_user

router = APIRouter()

# sqlite stores a 64-bit signed INTEGER; a larger id reaches sqlite3 as a
# Python int it cannot bind and raises OverflowError -- a 500 out of a path
# whose only honest answer is "no such bet". Bounding the id at the route
# turns that into the 422 it always was.
_MAX_SQLITE_INT = 2 ** 63 - 1


class SaveBetRequest(BaseModel):
    game: str
    side: str
    price: Optional[float] = None
    snapshot_digest: Optional[str] = None


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
                   current_user: User = Depends(get_current_user)) -> dict:
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
