"""GET /hounds/kennels and GET /hounds/kennels/{handle}: every member's public dogs, grouped by owner.

    GET /hounds/kennels             members with at least one public dog: handle, label, dog count, best record
    GET /hounds/kennels/{handle}    one member's public profile and dogs (a dog with no bet yet is listed, flagged "new")
    GET  /me/kennel                 signed in: the caller's kennel name and whether the one-time prompt is still due
    PUT  /me/kennel                 signed in: {"kennel_name"} (2-30 chars, unique) or {"dismiss_prompt": true}
    POST /admin/users/kennel-name   admin: {user_id, kennel_name, reason}: set or clear a member's kennel name
    GET  /me/unit-size              signed in: how the caller reads dollars (a fixed unit, or a percent of bankroll)
    PUT  /me/unit-size              signed in: {"mode", "unit_usd" | "pct" + "start_usd"}, validated (src/hounds/unit_size.py)

Public reads, no auth. The handle is the anonymous owner label ("Handler 3F2A" -> "handler-3f2a"); no email, no
account id and no token is ever in a payload. The logic and the numbers are src/hounds/kennels.py (the
leaderboard's own stats), so this module is wiring.

MOUNT ORDER. ``/hounds/kennels`` is a literal path under ``/hounds/{id}``; this router is mounted BEFORE
api.hounds (api/app.py does, and tests/test_hounds_kennels_api.py pins it).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds import kennels, member_profile, seasons, unit_size, user_defs
from src.hounds.contract import envelope

from api.admin import REISSUE_REASON_MAX, _LOOKS_LIKE_A_TOKEN, _SECRET_HINTS, _account_id
from api.auth import _require_admin, get_current_user

router = APIRouter()

_read_limiter = ratelimit.FixedWindowLimiter(limit=120, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter)


def _season(value: Optional[str]) -> str:
    sid = seasons.resolve(value)
    if sid is None:
        raise HTTPException(status_code=422, detail="season must be one of: " + ", ".join(seasons.ids() + [seasons.ALL]))
    return sid


@router.get("/hounds/kennels")
def kennel_index(response: Response, season: Optional[str] = Query(None, max_length=16),
                 _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = "public, max-age=30"
    return envelope(kennels.kennel_list(_season(season)))


@router.get("/hounds/kennels/mine")
def my_kennel(response: Response, season: Optional[str] = Query(None, max_length=16),
              current_user: users_store.User = Depends(get_current_user), _rl: None = Depends(_rl_read)) -> dict:
    """The signed-in member's own dogs, retired ones flagged. Declared before {handle} so "mine" is never a handle."""
    response.headers["Cache-Control"] = "no-store"
    return envelope(kennels.my_kennel(current_user.id, _season(season)))


@router.get("/hounds/kennels/{handle}")
def kennel_page(handle: str, response: Response, season: Optional[str] = Query(None, max_length=16),
                _rl: None = Depends(_rl_read)) -> dict:
    out = kennels.kennel_detail(handle[:60], _season(season))
    if out is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "no kennel with that name"})
    response.headers["Cache-Control"] = "public, max-age=30"
    return envelope(out)


# ---------------------------------------------------------------------------
# a member names their kennel
# ---------------------------------------------------------------------------

_write_limiter = ratelimit.FixedWindowLimiter(limit=20, window_s=3600.0)
_rl_write = ratelimit.limiter_dependency(_write_limiter, user_dependency=get_current_user)


def _profile_error(exc: member_profile.ProfileError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})


def _me_payload(user_id: int) -> dict:
    """What the signed-in member's own pages need: their kennel name, whether the one-time prompt is still to show
    and the public handle the name gives them. Never the email or the account id."""
    profile = member_profile.get(user_id)
    return {"kennel_name": profile["kennel_name"], "needs_name_prompt": profile["needs_name_prompt"],
            "display": user_defs.owner_display(user_id), "handle": kennels.handle_for(user_id),
            "limits": profile["limits"]}


@router.get("/me/kennel")
def my_kennel_name(response: Response, current_user: users_store.User = Depends(get_current_user),
                   _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return envelope(_me_payload(current_user.id))


class KennelNameRequest(BaseModel):
    kennel_name: Optional[str] = None
    dismiss_prompt: bool = False


@router.put("/me/kennel")
def put_my_kennel_name(body: KennelNameRequest, response: Response,
                       current_user: users_store.User = Depends(get_current_user),
                       _rl: None = Depends(_rl_write)) -> dict:
    """Name the signed-in member's kennel (2 to 30 characters, unique, run through the dog-name text filter), or
    ``{"dismiss_prompt": true}`` for "Not now" on the one-time prompt."""
    response.headers["Cache-Control"] = "no-store"
    try:
        if body.kennel_name is not None:
            member_profile.set_kennel_name(current_user.id, body.kennel_name, actor="owner")
        elif body.dismiss_prompt:
            member_profile.dismiss_prompt(current_user.id)
        else:
            raise member_profile.ProfileError("kennel_name_length", "send a kennel_name")
    except member_profile.ProfileError as exc:
        raise _profile_error(exc)
    return envelope(_me_payload(current_user.id))


def _sizing_payload(user_id: int) -> dict:
    return {"sizing": unit_size.get(user_id).as_dict(), "choices": unit_size.choices(), "paper_only": True}


@router.get("/me/unit-size")
def my_unit_size(response: Response, current_user: users_store.User = Depends(get_current_user),
                 _rl: None = Depends(_rl_read)) -> dict:
    """How the signed-in member reads the money. A VIEWER LENS: stored bets, grades and ranks are in units and never
    move with it; only the dollars a page prints do (docs/BANKROLL.md). The default is a $25 unit."""
    response.headers["Cache-Control"] = "no-store"
    return envelope(_sizing_payload(current_user.id))


class UnitSizeRequest(BaseModel):
    mode: Optional[Any] = None
    unit_usd: Optional[Any] = None
    pct: Optional[Any] = None
    start_usd: Optional[Any] = None


@router.put("/me/unit-size")
def put_my_unit_size(body: UnitSizeRequest, response: Response,
                     current_user: users_store.User = Depends(get_current_user),
                     _rl: None = Depends(_rl_write)) -> dict:
    """Save the member's sizing. ``{"mode": "fixed", "unit_usd": 25}`` (a whole dollar from 1 to 1,000) or
    ``{"mode": "percent", "pct": 2, "start_usd": 5000}`` (0.5 to 5 in half steps; $100 to $100,000). Anything else is
    a 422 with a stable ``error`` code; nothing is rounded or guessed."""
    response.headers["Cache-Control"] = "no-store"
    try:
        unit_size.save(current_user.id, body.model_dump())
    except unit_size.SizingError as exc:
        raise HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})
    return envelope(_sizing_payload(current_user.id))


class AdminKennelNameRequest(BaseModel):
    user_id: Optional[Any] = None
    kennel_name: Optional[str] = None
    reason: Optional[str] = None


def _admin_refusal(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": code, "message": message})


@router.post("/admin/users/kennel-name")
def admin_set_kennel_name(body: AdminKennelNameRequest, _admin: None = Depends(_require_admin)) -> dict:
    """Support sets (or clears, with an empty name) a member's kennel name. The same filter and the same
    uniqueness apply; a reason is required and kept beside the name, never public. The response carries the name
    and the public handle, never the member's email."""
    why = (body.reason or "").strip()
    if not why:
        raise _admin_refusal(400, "reason_required", "say why the name is being set")
    if len(why) > REISSUE_REASON_MAX:
        raise _admin_refusal(400, "reason_too_long", f"keep the reason under {REISSUE_REASON_MAX} characters")
    if _LOOKS_LIKE_A_TOKEN.search(why) or _SECRET_HINTS.search(why):
        raise _admin_refusal(400, "reason_looks_like_a_secret",
                             "the reason is stored in a log; do not paste a token or key into it")
    account_id = _account_id(body.user_id)
    if account_id is None or users_store.get_user(account_id) is None:
        raise _admin_refusal(409, "no_such_member", "no kennel name was set: this request does not match an account")
    if body.kennel_name is None:
        raise _admin_refusal(400, "kennel_name_required", "send kennel_name (empty clears it)")
    try:
        member_profile.set_kennel_name(account_id, body.kennel_name, actor="admin", reason=why)
    except member_profile.ProfileError as exc:
        raise _profile_error(exc)
    return {"ok": True, "user_id": account_id, "kennel_name": member_profile.kennel_name_of(account_id),
            "display": user_defs.owner_display(account_id), "handle": kennels.handle_for(account_id)}
