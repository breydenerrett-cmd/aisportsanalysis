"""From early-access tester to paying subscriber, on the SAME account.

THE DEAD END THIS CLOSES
--------------------------
`testers.grant_tester` leaves the person as an `invited` user with a seven day
token. When the week ended the token stopped working, and if they then typed
their email into the signup form `api/signup.py` answered `invited` -- the
status it keeps for a comped invite, "not this endpoint's business to move" --
and no checkout was ever started. Nothing in the product could turn that
person into a paying customer: a permanent dead end for exactly the people the
owner chose to let in first.

WHAT THIS MODULE DECIDES
--------------------------
Two questions, both read from tables that already exist (no schema change):

  * `upgrade_state(user)`: may this person start a checkout from the public
    signup form, and what is true about their access right now? A TESTER (a row
    in `testers`, which is never deleted) who is not currently entitled by a
    subscription. `tester_expired` once their window has ended, `tester_active`
    while it is still open (they want to pay early). Anyone else gets None and
    keeps exactly the behaviour they had: a comped `invited` user is not a
    tester, and a paying customer is already paid.
  * `expired_token_window(raw_token)`: is this bearer token an EXPIRED tester
    token, and when did that person's access end? Lets the sign-in page say
    "your early access ended on <date>" instead of the same words it uses for a
    mistyped token.

WHAT IS DELIBERATELY NOT HERE
--------------------------------
Nothing deletes or rewrites a tester row, a token, a saved bet or an event: the
history is the point of keeping the same user id. Entitlement is not decided
here either. `customers.has_paid_access` is the one place that answers "has
this person paid", and a tester who pays is governed by it exactly like anyone
else (api/auth.py `require_paid_access`): the tester window is never consulted
once a subscription record exists.

stdlib only, like the rest of src/ (tests/test_api_boundary.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.appstate import customers
from src.appstate import testers
from src.appstate import users as users_store

# The two states a tester can be in when billing cannot take their payment.
# They are the `status` api/signup.py returns, and the words the pages key on.
TESTER_ACTIVE = "tester_active"
TESTER_EXPIRED = "tester_expired"

# `detail.error` of the 401 an expired tester token gets (api/auth.py).
TESTER_ACCESS_EXPIRED_ERROR = "tester_access_expired"


def _parse(value: Optional[str]) -> Optional[datetime]:
    """An ISO-8601 string from the testers/tokens tables as an aware UTC
    datetime, or None for anything absent or unreadable. Never raises: a
    timestamp this module cannot read must degrade to "not a tester window",
    not turn the public signup route into a 500."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            ).astimezone(timezone.utc)


def _utc(now: Optional[datetime]) -> datetime:
    when = now or datetime.now(timezone.utc)
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            ).astimezone(timezone.utc)


def tester_window(user_id: int, *, db: Optional[Path] = None) -> Optional[dict]:
    """{"granted_at", "expires_at"} for a tester, or None for anyone never
    granted. `expires_at` is the expiry of the NEWEST tester token
    (testers.py: written at grant, moved forward by every extension)."""
    with testers._connect(db) as conn:
        row = conn.execute(
            "SELECT granted_at, expires_at FROM testers WHERE user_id = ?",
            (user_id,)).fetchone()
    return {"granted_at": row["granted_at"], "expires_at": row["expires_at"]} if row else None


def is_tester(user_id: int, *, db: Optional[Path] = None) -> bool:
    """Whether user_id was EVER granted tester access. Never reduced by expiry:
    the row is the permanent record that this account began as an early-access
    one."""
    return tester_window(user_id, db=db) is not None


def upgrade_state(user: users_store.User, *, now: Optional[datetime] = None,
                  db: Optional[Path] = None) -> Optional[dict]:
    """None unless `user` is a tester who may start a checkout.

    Otherwise {"state": TESTER_EXPIRED | TESTER_ACTIVE, "expires_at": <iso>}.
    The comparison is `now >= expires_at` = expired, the same boundary
    users_store.authenticate uses for the token itself, so "your access ended"
    and "your token stopped working" can never disagree by an instant.

    None (so the caller's old behaviour applies untouched) for:
      * anyone who is not in `testers` -- a comped `invited` user, an admin
        invite, a stranger;
      * a suspended account -- a human put it there, signup does not undo it;
      * a person a subscription currently entitles. They are already paid: a
        second checkout would be a second subscription on one account.
    A tester whose subscription has LAPSED (cancelled, period over) is not
    entitled, so they qualify again: that is the "come back" path on the same
    user id.
    """
    if user.status == "suspended":
        return None
    window = tester_window(user.id, db=db)
    if window is None:
        return None
    when = _utc(now)
    if customers.has_paid_access(user.id, when, db=db):
        return None
    ends = _parse(window["expires_at"])
    if ends is None:
        # An unreadable window is not "still active": say the access is over
        # rather than promise time nobody can prove is left. No date, because
        # there is no date to state.
        return {"state": TESTER_EXPIRED, "expires_at": None}
    state = TESTER_EXPIRED if when >= ends else TESTER_ACTIVE
    return {"state": state, "expires_at": ends.isoformat()}


def expired_token_window(raw_token: str, *, now: Optional[datetime] = None,
                         db: Optional[Path] = None) -> Optional[str]:
    """When a tester's access ended (ISO string), if `raw_token` is an EXPIRED
    tester token -- otherwise None, which the caller leaves as the ordinary
    "missing, invalid, expired, or revoked token" 401.

    It answers only for someone who already holds the whole 256-bit token, so
    it is not an oracle for guessing: there is no email in this path, and an
    unknown token is indistinguishable from every other wrong token. None for:
      * an unknown token, or a REVOKED one (support's token re-issue revokes
        every older token on purpose; that is not "your access ended");
      * a token that has not expired yet (it would have authenticated);
      * a user who is not a tester, or is suspended;
      * a tester whose access window is still open on a NEWER token (an
        extension) -- they are not out of time, they pasted an old token;
      * a person a subscription currently entitles -- they are not out of
        access, and "subscribe" would be the wrong thing to say to them.
    The date reported is the end of the tester window (the newest token's
    expiry), not this one token's, so a person who was extended is told when
    their access really ended.
    """
    if not raw_token:
        return None
    when = _utc(now)
    with testers._connect(db) as conn:
        row = conn.execute(
            "SELECT k.user_id AS user_id, k.expires_at AS token_end, "
            "       k.revoked_at AS revoked_at, t.expires_at AS window_end, "
            "       u.status AS status "
            "  FROM tokens k "
            "  JOIN testers t ON t.user_id = k.user_id "
            "  JOIN users u ON u.id = k.user_id "
            " WHERE k.token_hash = ?",
            (users_store._hash_token(raw_token),)).fetchone()
    if row is None or row["revoked_at"] is not None or row["status"] == "suspended":
        return None
    token_end = _parse(row["token_end"])
    window_end = _parse(row["window_end"])
    if token_end is None or window_end is None:
        return None
    if when < token_end or when < window_end:
        return None
    if customers.has_paid_access(row["user_id"], when, db=db):
        return None
    return window_end.isoformat()
