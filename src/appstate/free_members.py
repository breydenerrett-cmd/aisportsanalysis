"""Self-serve FREE accounts: the storage half of POST /auth/signup (api/free_signup.py).

THE POLICY THIS MODULE IMPLEMENTS (owner decision "yes open signups", 2026-10-19)
-----------------------------------------------------------------------------------
Until today a new visitor pressed "Request early access", was waitlisted, and the
owner approved them by hand. Now a visitor gives an email and a password and is IN:
an `active` user whose plan is "free" (src/appstate/access.py, TWO LEVELS), a
password, and a 30-day session token, all written in ONE transaction, so there is no
half-made account (a user with no password, a token for a user that was never saved).

A free account is a MEMBER. It opens the dog surface and never the paid board; that
split is access.access_level and api/auth.py, not this file. Nothing here touches
billing, a tester slot or a comp.

WHAT IS NEVER STORED OR RETURNED
-----------------------------------
No raw password (the caller hashes it with src/appstate/passwords.py before this
module sees it; this module only stores the record). No email in the event or the
rate-limit table (the table holds sha256 hashes of an address and a fixed scope
word; the email is only in `users`, where every account already has it). The
`signup_free_created` event carries the new member's HASHED id and one boolean.

RATE LIMITS, IN THE DATABASE
-------------------------------
Rows in the same `login_attempts` table the sign-in limiter uses (so a redeploy,
which happens hourly, does not reset them), with their own scopes:

    per hashed client address   5 an hour
    all addresses together      30 an hour and 100 a day

The global ceilings are the owner's "global 100 a day", plus an hourly one so a burst
cannot spend the whole day's allowance in a minute. The honest cost: someone who
wants to deny signups to everyone can spend the allowance (100 requests over a day
from 20 addresses). That is the price of an unauthenticated write with no email
verification, and it is bounded: the people already signed up are unaffected, and
the ceiling is one constant.

Every ATTEMPT that reaches the limiter is counted, an existing email's included, so
the limiter is also what bounds how fast anyone can probe which addresses already
have an account (api/free_signup.py explains the one thing a successful signup shows
that a repeat does not). A request refused by the cheap checks (bad email, a password
the rules reject, the honeypot) is not counted: those cost nothing to refuse and an
honest visitor who mistyped should not burn their five.

THE KENNEL NAME
-----------------
The visitor may give a kennel name on the form. Whether the product can store one
is another feature's business: this module owns only a REGISTRY, the way
access.register_access_source works. The default is src/hounds/member_profile.set_kennel_name
(registered at the bottom of this file); a test or another store can replace it with
`register_kennel_name_store`, and `None` leaves the name validated and dropped. A store that raises is logged to stderr and never fails the
signup (a name is a nicety; the account is the point).

Standard library only (no FastAPI), so the module loads where the app does not.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.appstate import access
from src.appstate import events
from src.appstate import passwords
from src.appstate import users as users_store

# Rate limits: (window in seconds, attempts allowed in that window). See the module
# docstring for why these numbers and why the global ones exist.
IP_LIMITS: Tuple[Tuple[int, int], ...] = ((60 * 60, 5),)
GLOBAL_LIMITS: Tuple[Tuple[int, int], ...] = ((60 * 60, 30), (24 * 60 * 60, 100))
SCOPE_SIGNUP_IP = "signup_ip"
SCOPE_SIGNUP_ALL = "signup_all"
_GLOBAL_IDENTITY = "all"

# A kennel name is a label on a page, not a document.
MAX_KENNEL_NAME_LENGTH = 40


class KennelNameRejected(ValueError):
    """`str(exc)` is the plain sentence the visitor is shown."""


def clean_kennel_name(raw) -> Optional[str]:
    """The kennel name to keep, or None when none was given.

    Whitespace is collapsed, control and format characters are refused (a name
    carrying them would render as something other than what was typed), and a name
    over MAX_KENNEL_NAME_LENGTH is refused rather than silently cut, so the visitor
    sees what will be kept."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise KennelNameRejected("Use plain text for the kennel name.")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") and ch not in " \t"
           for ch in raw):
        raise KennelNameRejected("The kennel name has a character that cannot be shown.")
    name = re.sub(r"\s+", " ", raw).strip()
    if not name:
        return None
    if len(name) > MAX_KENNEL_NAME_LENGTH:
        raise KennelNameRejected(f"Keep the kennel name to {MAX_KENNEL_NAME_LENGTH} characters or fewer.")
    return name


_kennel_name_store: Optional[Callable[[int, str], None]] = None


def register_kennel_name_store(fn: Optional[Callable[[int, str], None]]) -> None:
    """Plug in (or, with None, remove) the function that keeps a new member's kennel
    name. See the module docstring."""
    global _kennel_name_store
    _kennel_name_store = fn


def _member_profile_store(user_id: int, name: str) -> None:
    """The product's own kennel-name store (src/hounds/member_profile.py), the default. Its rules are stricter than
    clean_kennel_name's (3 to 24 characters, no claims, no reserved or taken names), and a name it refuses is simply not
    kept: the member is asked for one again on My kennel, where the refusal is shown in words. Imported here, not at
    module top, so this stdlib module loads where src/hounds does not."""
    from src.hounds import member_profile
    try:
        member_profile.set_kennel_name(user_id, name, actor="owner")
    except member_profile.ProfileError:
        return


register_kennel_name_store(_member_profile_store)


def keep_kennel_name(user_id: int, name: Optional[str]) -> bool:
    """Hand `name` to the registered store. True if a store accepted it; False if there
    is none, no name, or the store failed (logged, never raised)."""
    if not name or _kennel_name_store is None:
        return False
    try:
        _kennel_name_store(user_id, name)
    except Exception as exc:  # noqa: BLE001 -- a name must never fail a signup
        print(f"free signup: kennel name not kept for user_id={user_id}: {exc!r}",
              file=sys.stderr, flush=True)
        return False
    return True


# ---------------------------------------------------------------------------
# Rate limiting, in the database.
# ---------------------------------------------------------------------------

def check_and_record_signup(ip: str, *, now: Optional[float] = None,
                            db: Optional[Path] = None) -> Optional[float]:
    """Count one signup attempt against this address and against everyone, atomically.

    None if allowed (recorded against both); otherwise the seconds until the blocking
    window frees a slot, with nothing recorded (a refused attempt does not lengthen
    its own lockout). `now` is epoch seconds, injectable so tests never sleep. The
    same shape and the same single BEGIN IMMEDIATE transaction as
    passwords.check_and_record_attempt, on the same table."""
    when = time.time() if now is None else float(now)
    checks = [(SCOPE_SIGNUP_IP, passwords._key_hash(SCOPE_SIGNUP_IP, ip or ""), IP_LIMITS),
              (SCOPE_SIGNUP_ALL, passwords._key_hash(SCOPE_SIGNUP_ALL, _GLOBAL_IDENTITY), GLOBAL_LIMITS)]
    with passwords._connect(db) as conn:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM login_attempts WHERE at < ?", (when - passwords._PRUNE_AFTER_S,))
        worst: Optional[float] = None
        for scope, key, limits in checks:
            for window, limit in limits:
                rows = conn.execute(
                    "SELECT at FROM login_attempts WHERE scope = ? AND key_hash = ? "
                    "AND at > ? ORDER BY at ASC", (scope, key, when - window)).fetchall()
                if len(rows) >= limit:
                    frees = rows[len(rows) - limit]["at"] + window - when
                    worst = max(worst if worst is not None else 0.0, frees)
        if worst is not None:
            conn.commit()
            return max(worst, 1.0)
        conn.executemany("INSERT INTO login_attempts (scope, key_hash, at) VALUES (?, ?, ?)",
                         [(scope, key, when) for scope, key, _ in checks])
    return None


# ---------------------------------------------------------------------------
# The account.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FreeMember:
    """What a signup made. repr=False on the token keeps it out of a traceback."""
    user: users_store.User
    token: str = ""
    expires_at: Optional[datetime] = None

    def __repr__(self) -> str:  # never print the token
        return f"FreeMember(user_id={self.user.id})"


def create_free_member(email: str, record: passwords.PasswordRecord, *,
                       has_kennel_name: bool = False,
                       age_attested: bool = False,
                       now: Optional[datetime] = None,
                       db: Optional[Path] = None) -> Optional[FreeMember]:
    """Create the account, its password and its session token in one transaction.

    Returns None, writing nothing, when `email` already has an account of ANY kind (a
    waitlisted signup, a tester, a subscriber, a comp: a signup form is never a way
    to touch an existing account). `email` is already lower-cased by the caller, and
    the UNIQUE index on users.email settles a race: the loser's INSERT fails, the
    transaction rolls back, and it too gets None.

    `age_attested` is True when the visitor ticked "I am 21 or older"; the moment is
    stored on the user row (users.age_attested_at) in the same transaction, so there is
    never an account that says it was attested with no time, or the reverse.

    `record` is a hash made by passwords.hash_password BEFORE this call, so the
    scrypt (about 50 ms) runs outside the write lock."""
    when = now or datetime.now(timezone.utc)
    try:
        with passwords._connect(db) as conn:
            if conn.in_transaction:
                conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                conn.rollback()
                return None
            cur = conn.execute(
                "INSERT INTO users (email, created_at, status, plan, age_attested_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (email, when.isoformat(), "active", access.FREE_PLAN,
                 when.isoformat() if age_attested else None))
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO user_passwords (user_id, hash, salt, params, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, record.hash, record.salt, record.params, when.isoformat()))
            token = users_store.insert_token(conn, user_id, ttl=access.FREE_TOKEN_TTL, now=when)
            events._ensure_schema(conn)
            conn.execute(
                "INSERT INTO analytics_events (user_hash, kind, properties_json, at) "
                "VALUES (?, ?, ?, ?)",
                (events.hash_user_id(user_id), events.SIGNUP_FREE_CREATED,
                 json.dumps({"has_kennel_name": bool(has_kennel_name)}, sort_keys=True),
                 when.isoformat()))
    except Exception as exc:  # noqa: BLE001
        if "UNIQUE" in str(exc).upper():
            return None
        raise
    user = users_store.User(id=user_id, email=email, created_at=when.isoformat(),
                            status="active", plan=access.FREE_PLAN)
    return FreeMember(user=user, token=token, expires_at=when + access.FREE_TOKEN_TTL)
