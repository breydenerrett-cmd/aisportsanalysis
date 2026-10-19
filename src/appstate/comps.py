"""Complimentary ("comp") members: free access, forever, chosen by hand.

THE POLICY THIS MODULE IMPLEMENTS (owner decision, 2026-10-19)
-----------------------------------------------------------------
The owner can make a person a free member from the admin page: full access, no
card, no end date, until the owner takes it away. The first case was a person who
signed up for early access, sat on the waitlist, and whom the owner wanted in.
Nothing else in the product could do that: a tester token lasts 7 days and uses
one of 20 slots, and a subscriber token needs a subscription.

A comp is NOT a tester and NOT a subscriber. It does not use a tester slot, it is
not counted as revenue (the admin revenue view reads subscriptions only), and it
touches no Stripe object. The product is still early access and performance is
unproven: nothing here, in the admin page or in the member's billing page may
promise profit, an edge or winning picks. "Free member" is the whole label.

WHAT A COMP IS
---------------
    comps(user_id PK, granted_at, reason, granted_by, revoked_at, revoked_reason)
        created by src/appstate/customers.py (the entitlement check reads it).

  * Access. customers.has_paid_access answers True for a user with an unrevoked
    row whose account is not suspended. That is the one check the paid routes
    ask (api/auth.py require_paid_access), so a comp is honoured everywhere,
    including for a former subscriber whose lapsed record would be a 402.
  * One token. A grant revokes every older token of the person and mints ONE
    token that ends COMP_TOKEN_TTL (10 years) from now. There is no email sender,
    so the owner sends it himself; it is returned once and only its hash is kept.
    There is no "forever" token because the token table has a required expiry; 10
    years is forever for this product, and a re-issue mints another (POST
    /admin/users/reissue handles comps, with the same far-future end).
  * Status. The account becomes `active`. A new email creates the user; a
    waitlisted signup, an expired tester and an existing invited or active user
    keep their row and their history.
  * Revoking. Stamps `revoked_at` and `revoked_reason` and revokes every token, in
    one transaction. The row stays (who ever had it, and why). A later grant for
    the same person overwrites the same row.

WHO IS REFUSED (409, structured, nothing written)
---------------------------------------------------
  user_suspended   a human put the account there; a free token would open nothing
                   and granting would read as lifting a suspension.
  has_subscription a subscription that entitles them now, or one that is active or
                   trialing with nothing paid through yet (they are paying this
                   minute). Comping a paying customer would leave the owner
                   billing someone he just said is free. A LAPSED or cancelled
                   subscriber is not refused: they are no longer a customer.
  checkout_open    status pending_payment, the tester policy's refusal too: a
                   checkout is open for this person and could complete after the
                   grant. Let it finish or lapse first.
  already_comp     already a free member: re-issue their token instead.

THE AUDIT AND THE EVENT
-------------------------
A grant and a revoke write one `analytics_events` row each (`comp_access_granted`
/ `comp_access_revoked`, keyed by the user's HASH) in the SAME transaction as the
change, the way the support re-issue does: a grant with no audit row, or an audit
row for a grant that did not happen, cannot exist. The row carries the action,
what the account was before (new_email, waitlisted, tester, existing) and how many
tokens were revoked. It carries no token, no email and no reason: the reason is
free text and lives in the `comps` row, which only the admin routes read.

THE REASON
-----------
Required (400 reason_required), at most MAX_REASON_LENGTH characters, and it may
not look like a credential: the same check the support re-issue uses, kept here as
the one definition (api/admin.py imports it). It is a note to the owner's future
self ("early-access signup, friend of the project"), not a place to paste the
token it is about.

HOW IT STAYS ATOMIC
--------------------
The user row, the status change, the revoke, the new token, the comp row and the
audit event are one transaction opened with BEGIN IMMEDIATE (the write lock is
taken before anything is read), so a refusal or a crash leaves nothing behind and
two grants for one person serialise. The subscription lookup happens on that same
connection, so a webhook cannot slip a subscription in between the check and the
grant.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional

from src.appstate import customers
from src.appstate import events
from src.appstate import testers
from src.appstate import users as users_store

# How long a free member's token lasts. The tokens table requires an expiry
# (users.py), so "forever" is this long: ten years, re-issued on request.
COMP_TOKEN_TTL = timedelta(days=3650)

# Who granted it. Only the admin routes can, and there is one admin credential;
# the column exists so a second grantor later does not need a migration.
COMP_GRANTED_BY = "admin"

# A reason is a note, not an essay and not a place to paste the credential it is
# about (the support re-issue's bound, 500, for the same reason).
MAX_REASON_LENGTH = 500

# What counts as "a token in the reason". The product's access tokens are
# secrets.token_urlsafe(32): 43 characters of [A-Za-z0-9_-] (users.py
# insert_token), so any 32-character run of that alphabet is refused wherever it
# sits in the sentence. SECRET_HINTS are the ways a token is usually pasted with
# something around it: an Authorization header, a token= or session_id= query
# parameter, an admin header, a Stripe checkout session id (itself the key to the
# activation bridge). A plain "lost bearer token" is fine. MOVED here from
# api/admin.py unchanged so the support re-issue and the comp grant refuse
# exactly the same strings; api/admin.py keeps its old names as aliases.
LOOKS_LIKE_A_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,}")
SECRET_HINTS = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|token\s*=\s*\S"
    r"|session_id\s*="
    r"|x-admin-token"
    r"|\bcs_(?:test|live)_[A-Za-z0-9]{8,}",
    re.IGNORECASE)


class CompRefused(Exception):
    """A request the policy refuses. `code` is a stable machine word the API
    returns as `error`; `status` is the HTTP status the API layer uses."""

    def __init__(self, code: str, message: str, *, status: int = 409, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


@dataclass(frozen=True)
class CompGrant:
    """What a grant hands back. `token` is the RAW bearer token and exists only
    here; repr=False keeps it out of any accidental log line or traceback."""
    user_id: int
    email: str
    token: str = field(repr=False)
    granted_at: str
    expires_at: str
    # What the account was before: new_email | waitlisted | tester | existing.
    kind: str
    revoked_tokens: int


def _utc(now: Optional[datetime]) -> datetime:
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """The customers connection (WAL, busy_timeout, the billing tables and
    `comps` ensured) plus the users, tokens and testers tables, so one
    connection can hold the whole grant. Rides on customers._connect, which
    resolves the path through users_store.db_path at call time: a test that
    patches that redirects this module too."""
    with customers._connect(path) as conn:
        users_store._ensure_schema(conn)
        testers._ensure_schema(conn)
        yield conn


def check_reason(reason: Optional[str]) -> str:
    """The reason, stripped; CompRefused (400) when it is missing, too long or
    looks like it holds a token or key."""
    why = (reason or "").strip()
    if not why:
        raise CompRefused("reason_required",
                          "say why this person is getting free access", status=400)
    if len(why) > MAX_REASON_LENGTH:
        raise CompRefused("reason_too_long",
                          f"keep the reason under {MAX_REASON_LENGTH} characters", status=400)
    if LOOKS_LIKE_A_TOKEN.search(why) or SECRET_HINTS.search(why):
        raise CompRefused(
            "reason_looks_like_a_secret",
            "the reason is stored; do not paste a token or key into it", status=400)
    return why


def _audit(conn: sqlite3.Connection, user_id: int, kind: str, properties: dict,
           when: datetime) -> None:
    """One analytics_events row, written on the caller's open transaction.
    events.record_event opens its own connection, which cannot join this one (a
    second writer would wait out the first's lock), so the INSERT is repeated:
    same table, same columns, same hashed user, same JSON -- the support
    re-issue's pattern (api/admin.py _write_reissue_audit)."""
    if kind not in events.EVENT_KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    events._ensure_schema(conn)
    conn.execute(
        "INSERT INTO analytics_events (user_hash, kind, properties_json, at) "
        "VALUES (?, ?, ?, ?)",
        (events.hash_user_id(user_id), kind, json.dumps(properties, sort_keys=True),
         when.isoformat()))


def _find_user(conn: sqlite3.Connection, *, address: Optional[str],
               user_id: Optional[int]):
    if address is not None:
        return conn.execute("SELECT * FROM users WHERE email = ?", (address,)).fetchone()
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def grant_comp(*, email: Optional[str] = None, user_id: Optional[int] = None,
               reason: Optional[str] = None, now: Optional[datetime] = None,
               db: Optional[Path] = None) -> CompGrant:
    """Make one person a free member and return their RAW token (once).

    Exactly one of `email` or `user_id` (ValueError otherwise; the API layer
    answers 400 before calling). An unknown email creates the user; an unknown
    user_id is a refusal (404 no_such_user). See the module docstring for the
    refusals; every one is raised before anything is written, and the whole
    transaction is rolled back regardless.
    """
    if (email is None) == (user_id is None):
        raise ValueError("pass exactly one of email or user_id")
    why = check_reason(reason)
    when = _utc(now)
    address = None
    if email is not None:
        try:
            address = testers.normalise_email(email)
        except testers.TesterRefused as exc:
            raise CompRefused(exc.code, exc.message, status=exc.status) from None

    with _connect(db) as conn:
        testers._begin_exclusive(conn)
        row = _find_user(conn, address=address, user_id=user_id)
        if row is None and address is None:
            raise CompRefused("no_such_user", "no such user", status=404)

        kind = "new_email"
        existing_comp = None
        if row is not None:
            if row["status"] == "suspended":
                raise CompRefused("user_suspended", "this account is suspended")
            if row["status"] == "pending_payment":
                raise CompRefused(
                    "checkout_open",
                    "a checkout is open for this person (status pending_payment); "
                    "free access was not granted")
            if customers.subscription_is_live(customers._read_record(conn, row["id"]), when):
                raise CompRefused(
                    "has_subscription",
                    "this person has a live paid subscription; free access was not "
                    "granted")
            existing_comp = conn.execute(
                "SELECT revoked_at FROM comps WHERE user_id = ?", (row["id"],)).fetchone()
            if existing_comp is not None and existing_comp["revoked_at"] is None:
                raise CompRefused(
                    "already_comp",
                    "this person is already a free member; re-issue their token instead")
            if conn.execute("SELECT 1 FROM testers WHERE user_id = ?",
                            (row["id"],)).fetchone():
                kind = "tester"
            elif row["status"] == "waitlisted":
                kind = "waitlisted"
            else:
                kind = "existing"

        if row is None:
            cur = conn.execute(
                "INSERT INTO users (email, created_at, status, plan) "
                "VALUES (?, ?, 'active', 'none')", (address, when.isoformat()))
            uid, mail = cur.lastrowid, address
        else:
            uid, mail = row["id"], row["email"]
            if row["status"] != "active":
                conn.execute("UPDATE users SET status = 'active' WHERE id = ?", (uid,))

        revoked = users_store.revoke_tokens_on(conn, uid, when=when)
        raw_token = users_store.insert_token(conn, uid, ttl=COMP_TOKEN_TTL, now=when)
        if existing_comp is None:
            conn.execute(
                "INSERT INTO comps (user_id, granted_at, reason, granted_by) "
                "VALUES (?, ?, ?, ?)", (uid, when.isoformat(), why, COMP_GRANTED_BY))
        else:
            conn.execute(
                "UPDATE comps SET granted_at = ?, reason = ?, granted_by = ?, "
                "revoked_at = NULL, revoked_reason = NULL WHERE user_id = ?",
                (when.isoformat(), why, COMP_GRANTED_BY, uid))
        _audit(conn, uid, events.COMP_ACCESS_GRANTED,
               {"action": "grant", "kind": kind, "revoked_tokens": revoked}, when)
    return CompGrant(user_id=uid, email=mail, token=raw_token,
                     granted_at=when.isoformat(),
                     expires_at=(when + COMP_TOKEN_TTL).isoformat(),
                     kind=kind, revoked_tokens=revoked)


def revoke_comp(user_id: Optional[int], reason: Optional[str], *,
                now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """Take a free member's access away: stamp the row revoked and revoke every
    token of the person, in one transaction. 404 no_such_user for an unknown id,
    409 not_a_comp for a person who is not (or is no longer) a free member.
    Returns {"user_id", "email", "revoked_tokens", "revoked_at"}; the account's
    status is left as it is (it is not the comp's to rewrite)."""
    why = check_reason(reason)
    when = _utc(now)
    with _connect(db) as conn:
        testers._begin_exclusive(conn)
        row = (conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
               if user_id is not None else None)
        if row is None:
            raise CompRefused("no_such_user", "no such user", status=404)
        comp = conn.execute("SELECT revoked_at FROM comps WHERE user_id = ?",
                            (row["id"],)).fetchone()
        if comp is None or comp["revoked_at"] is not None:
            raise CompRefused("not_a_comp", "this person is not a free member")
        conn.execute(
            "UPDATE comps SET revoked_at = ?, revoked_reason = ? WHERE user_id = ?",
            (when.isoformat(), why, row["id"]))
        revoked = users_store.revoke_tokens_on(conn, row["id"], when=when)
        _audit(conn, row["id"], events.COMP_ACCESS_REVOKED,
               {"action": "revoke", "revoked_tokens": revoked}, when)
    return {"user_id": row["id"], "email": row["email"], "revoked_tokens": revoked,
            "revoked_at": when.isoformat()}


def list_comps(*, db: Optional[Path] = None) -> dict:
    """Every free member ever granted, oldest grant first, with `active` (in
    force right now: not revoked and the account not suspended) and
    `first_used_at` (the earliest sign-in on any of their tokens). Never a
    token."""
    with _connect(db) as conn:
        rows = conn.execute("""
            SELECT c.user_id, c.granted_at, c.reason, c.granted_by, c.revoked_at,
                   c.revoked_reason, u.email, u.status,
                   (SELECT MIN(k.first_used_at) FROM tokens k
                     WHERE k.user_id = c.user_id) AS first_used_at
              FROM comps c JOIN users u ON u.id = c.user_id
             ORDER BY c.granted_at ASC, c.user_id ASC
        """).fetchall()
    comps = [{
        "user_id": r["user_id"], "email": r["email"], "status": r["status"],
        "granted_at": r["granted_at"], "reason": r["reason"],
        "granted_by": r["granted_by"], "revoked_at": r["revoked_at"],
        "revoked_reason": r["revoked_reason"], "first_used_at": r["first_used_at"],
        "active": r["revoked_at"] is None and r["status"] != "suspended",
    } for r in rows]
    return {"comps": comps, "active": sum(1 for c in comps if c["active"]),
            "token_years": COMP_TOKEN_TTL.days // 365}


def comp_marks(*, db: Optional[Path] = None) -> Dict[int, dict]:
    """user_id -> {granted_at, revoked_at}, for the /admin/users listing."""
    with _connect(db) as conn:
        return {r["user_id"]: {"granted_at": r["granted_at"], "revoked_at": r["revoked_at"]}
                for r in conn.execute("SELECT user_id, granted_at, revoked_at FROM comps")}
