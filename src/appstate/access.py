"""Where a member's access ends, in one function: `access_token_end(user)`.

WHY THIS EXISTS
-----------------
Email + password login (src/appstate/passwords.py, api/passwords.py) hands a
member a NEW session token, and that token must end exactly where the access the
member was given ends, never later. Before this, that rule lived only in
api/admin.py's `_reissue_plan` (support re-issue). Login needs the same answer,
so it is asked here, once, and POST /auth/login is the first caller.
(`_reissue_plan` still carries its own copy of these rules: it is the support
path and its refusals are pinned by its own tests. When it is next touched it
should call this function instead; the two must always agree.)

THE ANSWER
------------
`access_token_end(user)` returns `(kind, ends_at)` or None.

  subscriber   customers.has_paid_access (a trial counts): the usual subscriber
               token lifetime, billing.SUBSCRIBER_TOKEN_TTL.
  <a source>   a registered access source (below), e.g. a free "comp" member, or
               the built-in "free" source: a self-serve FREE account.
  tester       a `testers` row and no subscription record: the tester window's
               end (testers.expires_at). An ENDED window is returned as it is,
               in the past: the token it produces opens nothing, but it
               identifies the person to POST /billing/tester-checkout, the door
               an expired tester converts through. Exactly what a support
               re-issue does for an expired tester.
  None         a suspended account, a waitlisted or pending signup, a lapsed
               subscriber, an admin-invited beta user, anyone with no access.
               "None" means no session is started; the API says so in plain words.

An admin-invited beta user (an `invited` row with an invite token but no
tester, comp or subscription record) gets None on purpose. Their access is the
token Brey issued, with the lifetime Brey chose; letting a password mint a fresh
fourteen-day token every login would turn that into indefinite access nobody
granted. A free member who should be able to sign in is a COMP, not an invite.

TWO LEVELS: MEMBER AND PAID (owner decision "yes open signups", 2026-10-19)
------------------------------------------------------------------------------
A self-serve free account (POST /auth/signup, api/free_signup.py) is a user whose
`plan` is "free". It is a MEMBER: it may use everything built around the dogs
(kennels, building, editing and backtesting its own dogs, Ask, the locker room,
unleashing a dog, sending it to training or taking it out back, fan tips, following) and nothing on the PAID member board
(Gameday, Matchups, Props and the other daily-picks routes).

`access_level(user)` is the one answer: "paid", "member" or None. A user is a
MEMBER (and only a member) when their plan is "free" AND nothing entitles them to
the paid surface right now: no subscription paid through a future instant, no
comp, no OPEN tester window. Everyone else who has a session is "paid", which is
exactly what they were before this level existed (an admin-invited beta user, a
tester inside the week, a comp, a subscriber), so nobody who had access lost any.
api/auth.py's require_paid_access refuses a "member" with a 403; its sibling
require_member_access lets a member and a paid user through. Those two are the
ONLY places the level is read. Giving a free account tester, comp or subscriber
access is how it is upgraded; none of those changes its plan, and none needs to.

The check is cheap for everyone else: a user whose plan is not "free" returns at
the first line without a database read.

THE BUILT-IN "free" SOURCE
-----------------------------
Registered at the bottom of this file. A plan-"free", `active` user is given a
session token that lasts FREE_TOKEN_TTL (30 days) from now; a sign-in (POST
/auth/login) mints a fresh one, so an account in use never lapses. It is asked
after the paid check and before the tester rule, so a free account whose tester
week is open signs in with a 30-day token and the tester week still opens the
paid board only until it ends; afterwards the same token is a member's.

PLUGGING IN THE FREE-MEMBER ("COMP") TABLE
----------------------------------------------
The comp worker's code registers ONE function at import time:

    from src.appstate import access

    def _comp_access_end(user, now):          # -> datetime | None
        ...                                    # None = not a comp, or comp revoked
    access.register_access_source("comp", _comp_access_end)

A source is asked after the paid check and before the lapsed-subscription and
tester rules, in registration order. Returning a datetime means "this person has
access until then" (use a far-future date for free-forever; keep it finite, a
token needs an end, e.g. now + billing.SUBSCRIBER_TOKEN_TTL, since a member signs
in again and gets a fresh one). Returning None means "not mine". A source that
raises is treated as None and logged to stderr, never as access: a broken source
must fail closed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple

from src.appstate import billing
from src.appstate import customers
from src.appstate import tester_upgrade
from src.appstate import users as users_store

# The plan a self-serve account carries (users.VALID_PLANS), the level it gets, and how
# long its session token lasts. 30 days: long enough that a visitor who comes back
# monthly is still signed in, short enough that a token left on a lost laptop ends.
FREE_PLAN = "free"
LEVEL_MEMBER = "member"
LEVEL_PAID = "paid"
FREE_TOKEN_TTL = timedelta(days=30)

# name -> fn(user, now) -> Optional[datetime]. A dict keeps registration order and
# makes registering the same name twice a replacement, not a duplicate.
_SOURCES: Dict[str, Callable[[users_store.User, datetime], Optional[datetime]]] = {}


def register_access_source(name: str,
                           fn: Callable[[users_store.User, datetime], Optional[datetime]]) -> None:
    """Add (or replace) a named source of access. See the module docstring."""
    if not name or not callable(fn):
        raise ValueError("an access source needs a name and a callable")
    _SOURCES[name] = fn


def unregister_access_source(name: str) -> None:
    _SOURCES.pop(name, None)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def access_token_end(user: Optional[users_store.User], *,
                     now: Optional[datetime] = None) -> Optional[Tuple[str, datetime]]:
    """(kind, ends_at) for the session token this user may be given, else None.
    `now` is injectable for tests."""
    if user is None or user.status == "suspended":
        return None
    when = _aware(now) if now is not None else datetime.now(timezone.utc)
    if customers.has_paid_access(user.id, when):
        return "subscriber", when + billing.SUBSCRIBER_TOKEN_TTL
    for name, source in list(_SOURCES.items()):
        try:
            ends = source(user, when)
        except Exception as exc:  # noqa: BLE001 -- fail closed, see docstring
            print(f"access: source {name!r} failed: {exc!r}", file=sys.stderr, flush=True)
            continue
        if ends is not None:
            return name, _aware(ends)
    if customers.get_subscription_record(user.id) is not None:
        return None
    window = tester_upgrade.tester_window(user.id)
    try:
        ends = datetime.fromisoformat(window["expires_at"]) if window else None
    except (TypeError, ValueError):
        ends = None
    if ends is None:
        return None
    return "tester", _aware(ends)


def _free_access_end(user: users_store.User, now: datetime) -> Optional[datetime]:
    """The built-in "free" source: a plan-"free" account that is `active` has access
    for FREE_TOKEN_TTL from now. Anything else (a waitlisted or pending person; a
    suspended one was already refused by the caller) is not this source's."""
    if user.plan == FREE_PLAN and user.status == "active":
        return now + FREE_TOKEN_TTL
    return None


register_access_source("free", _free_access_end)


def _tester_window_open(user_id: int, when: datetime) -> bool:
    window = tester_upgrade.tester_window(user_id)
    try:
        ends = datetime.fromisoformat(window["expires_at"]) if window else None
    except (TypeError, ValueError):
        ends = None
    return ends is not None and _aware(ends) > when


def is_free_only(user: Optional[users_store.User], *,
                 now: Optional[datetime] = None) -> bool:
    """True for a self-serve free account that nothing entitles to the paid surface
    right now. See the module docstring's TWO LEVELS section."""
    if user is None or user.plan != FREE_PLAN:
        return False
    when = _aware(now) if now is not None else datetime.now(timezone.utc)
    if customers.has_paid_access(user.id, when):
        return False
    return not _tester_window_open(user.id, when)


def access_level(user: Optional[users_store.User], *,
                 now: Optional[datetime] = None) -> Optional[str]:
    """"member" for a free-only account, "paid" for every other user with a session,
    None for no user or a suspended one."""
    if user is None or user.status == "suspended":
        return None
    return LEVEL_MEMBER if is_free_only(user, now=now) else LEVEL_PAID
