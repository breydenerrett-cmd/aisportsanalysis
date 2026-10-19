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
  <a source>   a registered access source (below), e.g. a free "comp" member.
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
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

from src.appstate import billing
from src.appstate import customers
from src.appstate import tester_upgrade
from src.appstate import users as users_store

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
