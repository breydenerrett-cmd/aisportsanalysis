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
  tester       a `testers` row and no subscription record, window still open: the
               window's end (testers.expires_at).
  free         (ruling 2026-10-27) the same person once the window has ENDED: a
               FREE member with a FREE_TOKEN_TTL token, who keeps their kennel.
               is_free_only reads them as a member, so the paid board still
               refuses them; the token still identifies them to POST
               /billing/tester-checkout (any token of a tester does). A support
               re-issue (api/admin.py `_reissue_plan`) follows the same rule. A
               tester who never set a password reaches it with their ENDED
               access code through `continue_as_free` (POST /auth/continue-free).
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
# The `kind` of a session token for a free member (the built-in "free" source's name).
LEVEL_FREE_KIND = "free"

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
    ends = _aware(ends)
    if ends <= when:
        # The window is over and nothing else entitles them (no paid access, no
        # subscription record: both were refused above). Owner ruling 2026-10-27:
        # they drop to a FREE member and keep their kennel, not a dead token.
        # is_free_only agrees, so every gate reads this token as a member's.
        return LEVEL_FREE_KIND, when + FREE_TOKEN_TTL
    return "tester", ends


# How long after its expiry an ended tester's access code may still be traded for a
# free-member session. The code is a 256-bit secret and only the person it was sent
# to holds it, so this is not about guessing; it bounds how long a code that leaked
# (an old screenshot, a forwarded message) stays a key. 90 days is a full quarter
# after the week ended: long enough for a tester who comes back after a holiday,
# short enough that a year-old code is not still a door. Past it the person signs
# in by support re-issue (which now also yields a free token).
CONTINUE_FREE_MAX_AGE = timedelta(days=90)


def continue_as_free(raw_token: str, *, now: Optional[datetime] = None):
    """Trade an ENDED tester's access code for a fresh free-member session token.

    Owner ruling 2026-10-27: an ended tester becomes a free member and keeps their
    kennel. Email + password login already does that; this is the door for the
    tester who only ever had the access code, whose own token died with the window.

    Returns (new raw token, ends_at, user_id) or None. None for EVERY refusal, so the caller can
    answer one generic 401 (it must not say which rule failed): an unknown token;
    a REVOKED one (support re-issue and logout revoke on purpose); one that has not
    expired yet (it still works as itself; nothing to trade); one expired more than
    CONTINUE_FREE_MAX_AGE ago; a suspended account; a user who is not an ended
    tester right now (an open window, a subscriber, a lapsed subscriber, an
    admin-invited beta user). The rule is `access_token_end` returning kind "free"
    AND `_ended_tester`, so this can never grant anything sign-in would not.

    The presented token is revoked and the new one inserted in ONE transaction, and
    the revoke must actually flip a row: two requests racing with the same code
    cannot both be issued a token. Other tokens of the account are left alone."""
    if not raw_token or not isinstance(raw_token, str):
        return None
    when = _aware(now) if now is not None else datetime.now(timezone.utc)
    ended = tester_upgrade.expired_token_window(raw_token, now=when)
    if ended is None:  # unknown, revoked, unexpired, suspended, not a tester, paying
        return None
    with users_store._connect() as conn:
        row = conn.execute("SELECT user_id, expires_at FROM tokens WHERE token_hash = ?",
                           (users_store._hash_token(raw_token),)).fetchone()
    if row is None:
        return None
    try:
        token_end = _aware(datetime.fromisoformat(row["expires_at"]))
    except (TypeError, ValueError):
        return None
    if when - token_end > CONTINUE_FREE_MAX_AGE:
        return None
    user = users_store.get_user(row["user_id"])
    plan = access_token_end(user, now=when)
    if plan is None or plan[0] != LEVEL_FREE_KIND or not _ended_tester(user, when):
        return None
    _kind, ends_at = plan
    with users_store._connect() as conn:
        cur = conn.execute(
            "UPDATE tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (when.isoformat(), users_store._hash_token(raw_token)))
        if cur.rowcount != 1:
            return None
        users_store._wipe_activation_tokens(conn, raw_token=raw_token)
        new_token = users_store.insert_token(conn, user.id, ttl=ends_at - when, now=when)
    return new_token, ends_at, user.id


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


def _ended_tester(user: users_store.User, when: datetime) -> bool:
    """True for an invited tester whose window is OVER and whom nothing else
    entitles: no paid access, no subscription record (a lapsed subscriber is a
    different case, refused at sign-in), not an admin-invited beta user (plan
    "beta"). Owner ruling 2026-10-27: such a person is a FREE member and keeps
    their kennel. Their `plan` stays "none" (no ledger rewrite), so the level has
    to be derived here, in the same place the "free" plan is."""
    if user.plan == "beta":
        return False
    window = tester_upgrade.tester_window(user.id)
    try:
        ends = datetime.fromisoformat(window["expires_at"]) if window else None
    except (TypeError, ValueError):
        ends = None
    if ends is None or _aware(ends) > when:
        return False
    if customers.has_paid_access(user.id, when):
        return False
    return customers.get_subscription_record(user.id) is None


def is_free_only(user: Optional[users_store.User], *,
                 now: Optional[datetime] = None) -> bool:
    """True for a free account that nothing entitles to the paid surface right now:
    a self-serve plan-"free" account, or an invited tester whose window has ended.
    See the module docstring's TWO LEVELS section."""
    if user is None:
        return False
    when = _aware(now) if now is not None else datetime.now(timezone.utc)
    if user.plan != FREE_PLAN:
        return _ended_tester(user, when)
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
