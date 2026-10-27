"""GET /me/access: is the signed-in member's full access about to end, and what would upgrading cost?

Read at every member page load by web/js/access-ending.js (the banner). The decision is
src/appstate/access_ending.py's; this file only authenticates and adds the public offer.

    {show_warning, kind, ends_at, days_left, ends_today, ends_on,
     founding: {price_cents, left, cap} | null, standard_price_cents}

`founding` is present only while a founding seat can really be had (the same rule GET /billing/offer
states); otherwise only the standard price is given. No email, token or billing identifier is returned.
401 without a token, like every member route.
"""

from __future__ import annotations

import sys

from fastapi import APIRouter, Depends, Response

from src.appstate import access_ending, billing, ratelimit
from src.appstate import users as users_store

from api.auth import get_current_user

router = APIRouter()

_rl = ratelimit.limiter_dependency(ratelimit.FixedWindowLimiter(limit=240, window_s=60.0),
                                   user_dependency=get_current_user)


def offer_for_banner() -> dict:
    """The price the upgrade button would charge, never raising (an unreadable seat table is no founding offer)."""
    try:
        offer = billing.founding_offer()
    except Exception as exc:  # noqa: BLE001
        print(f"me/access: offer unreadable: {exc!r}", file=sys.stderr, flush=True)
        offer = {"founding": None, "standard": {"price_cents": billing.BETA_PLAN_PRICE_CENTS}}
    f = offer.get("founding")
    founding = ({"price_cents": f["price_cents"], "left": f["left"], "cap": f["cap"]}
                if f and f.get("available") and f.get("left", 0) > 0 else None)
    return {"founding": founding, "standard_price_cents": offer["standard"]["price_cents"]}


@router.get("/me/access")
def my_access(response: Response, current_user: users_store.User = Depends(get_current_user),
              _rate_limit: None = Depends(_rl)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    body = access_ending.ending_notice(current_user)
    if body["show_warning"]:
        body.update(offer_for_banner())
    return body
