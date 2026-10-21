"""api/entitlements.py: what a FREE account may not do with a member dog, and the one refusal it gets.

OWNER DECISION 2026-10-20. Free: one active dog. Paid: up to five active dogs, every sport, Live
"send a dog", Backtest and Ask. This module is the server-side half of that sentence for the three
paid dog tools; the dog-count limit is api/hounds_create.py + src/hounds/user_store.py (so it holds
inside the creating transaction).

WHO IS "PAID" HERE. Exactly src/appstate/access.py's level, asked through api/auth.py's is_free_member
(auth.py is the one module allowed to read it): "paid" is every
account with a session that is not a free-only account, which includes a subscriber paid through, a
free-forever COMP member (customers.has_paid_access answers True for a comp, so they are not free-only),
an early-access tester inside the window and an admin-invited beta user. A lapsed subscriber is held
to api/auth.py require_paid_access (402 `subscription_expired`), the same refusal the board gives. So
this module invents no second definition of "paid": it asks the one that already exists.

WHICH DOGS. Only MEMBER (builder) dogs. The house pack's public pages keep what they had: anyone may
read a house dog's Ask answers, run its drill and ask what it would pick, signed in or not. The gate is
on the CALLER (a free account is refused on any builder dog, its own included), because the cost the
paid tier covers, the replay engine and the per-game live read, is the same whoever owns the dog.

THE REFUSAL. 402, error `upgrade_required`, with `feature` naming the tool. 402 and not 403 because the
credential is good and the account is in good standing; what is missing is a payment, which is what
402 says. The web pages (web/js/upgrade.js) turn it into an upgrade prompt; they read `error` and
`feature`, never the sentence. A signed-out caller is a plain 401, because the fix for them is signing
in, not paying.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from src.appstate import users as users_store

from api import auth as auth_mod

UPGRADE_ERROR = "upgrade_required"

FEATURE_LIVE_SEND = "live_send"
FEATURE_BACKTEST = "backtest"
FEATURE_ASK = "ask"
FEATURE_MORE_DOGS = "more_dogs"

_FEATURE_WORDS = {
    FEATURE_LIVE_SEND: "Sending a hound at a live game",
    FEATURE_BACKTEST: "Backtest",
    FEATURE_ASK: "Ask",
}


def upgrade_refusal(feature: str, message: Optional[str] = None) -> HTTPException:
    """The one 402 a free account gets for a paid dog tool."""
    words = _FEATURE_WORDS.get(feature, "That")
    return HTTPException(status_code=402, detail={
        "error": UPGRADE_ERROR, "feature": feature,
        "message": message or f"{words} is part of the member plan. A free account keeps one hound; "
                              "members run up to five, in every sport, with Live, Backtest and Ask."})


def require_paid_dog_tool(user: users_store.User, feature: str) -> users_store.User:
    """Return `user` if they may use a paid dog tool, else raise the 402 (free account) or the
    subscription gate's own refusal (lapsed subscriber)."""
    if auth_mod.is_free_member(user):
        raise upgrade_refusal(feature)
    return auth_mod.require_paid_access(current_user=user)


def paid_dog_tool_for(authorization: Optional[str], request, feature: str) -> users_store.User:
    """The signed-in caller, held to require_paid_dog_tool. A missing or bad token is the usual 401."""
    # `request` only carries the user id to the request log; a caller without one (a direct call) is fine.
    user = auth_mod.get_current_user(authorization, request if hasattr(request, "state") else None)
    return require_paid_dog_tool(user, feature)
