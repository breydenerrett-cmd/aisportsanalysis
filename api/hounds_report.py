"""The Analyze report (owner decision 2026-10-29: a free teaser, the full report for paid members).

    GET /hounds/{id}/report    what a member hound is picking, why its record looks the way it does, and what could be done about it
                               (src/hounds/analyze_report.py). `/hounds/{id}/analysis` is the Gematria read and is not this.

WHO GETS WHAT
  * The TEASER goes to anyone, signed in or not, for any member hound: the headline, the "hot hand or hot dice?" block and the ticket
    timeline with its grades. A member hound's bets are already public on its record page, so none of this is new to a visitor. The
    answer carries ``locked`` (the sections left out) and an ``upgrade`` line.
  * The FULL report (drivers, the case for changing nothing, ways to expand, the coach's read, and a hindsight line under a ticket
    when a review exists) goes only to the hound's OWNER while the owner is on a paid plan (``entitlements.has_paid_dog_tool``). A free
    owner and a lapsed subscriber get the teaser with the owner's upgrade line, never a 402: the page has something to show either way.
    Hindsight reviews of a member hound are the owner's alone (api/hounds_postmortems.py), so a teaser never carries one.
  * A house hound (the pack, the AI hounds, the baselines) is refused with 422 ``not_a_member_dog``; a hound nobody knows is 404.

No model is asked for a teaser, and the coach's read is cached per hound, version and settled count, so a visitor cannot spend the
$5 cap. The owner's view is ``Cache-Control: no-store``. An anonymous teaser may be cached for half a minute; any request that carries
a sign-in is never stored. A report is built from the cached stats book and the ledger; with neither ready the route answers 503
``warming_up`` with a Retry-After, like the other record routes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds import analyze_report
from src.hounds.contract import envelope
from src.hounds.interact import common

from api import auth as auth_mod
from api import entitlements

router = APIRouter()

_NO_STORE = "no-store"
_ANON_TEASER_CACHE = "public, max-age=30"
READ_PER_MIN = 60
_limiter = ratelimit.FixedWindowLimiter(limit=READ_PER_MIN, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_limiter)


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": code, "message": message, **extra})


def _viewer(authorization: Optional[str]) -> Optional[users_store.User]:
    """The signed-in caller, or None. Never raises: a bad token is just a visitor on a public read."""
    viewer_id = auth_mod.optional_user_id(authorization)
    if viewer_id is None:
        return None
    try:
        return users_store.get_user(viewer_id)
    except Exception:  # noqa: BLE001 -- a user row that cannot be read is a visitor
        return None


@router.get("/hounds/{hound_id}/report")
def hound_report(hound_id: str, response: Response, authorization: Optional[str] = Header(default=None),
                 _rl: None = Depends(_rl_read)) -> dict:
    dog = common.resolve(hound_id)
    if dog is None:
        raise _err(404, "not_found", "no such hound")
    if dog.kind != common.KIND_USER:
        raise _err(422, "not_a_member_dog", "The Analyze report is for hounds a member built.")
    viewer = _viewer(authorization)
    owner = viewer is not None and viewer.id == dog.owner_user_id
    full = owner and entitlements.has_paid_dog_tool(viewer, entitlements.FEATURE_ANALYZE)
    if viewer is None:
        response.headers["Cache-Control"] = _ANON_TEASER_CACHE
        response.headers["Vary"] = "Authorization"
    else:
        response.headers["Cache-Control"] = _NO_STORE
    report = analyze_report.load_report(dog, full=full, owner=owner)
    if report is None:
        response.headers["Cache-Control"] = _NO_STORE
        response.headers["Retry-After"] = "5"
        raise _err(503, "warming_up", "The record is still being worked out. Try again in a few seconds.")
    out = envelope(report)
    out["viewer"] = {"signed_in": viewer is not None, "is_owner": owner, "full": full}
    return out
