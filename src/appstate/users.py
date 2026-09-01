"""User store + invite-token auth, stdlib-only (sqlite3, secrets, hashlib).

WHY INVITE TOKENS, NOT PASSWORDS
---------------------------------
The private alpha (docs/LAUNCH_DECISIONS.md, Decision 1) has no chosen auth
provider yet -- that decision needs Brey's sign-off (Clerk is the current
recommendation) and is not this task's to make. Building a password system
in the meantime would mean shipping and then throwing away a real-but-
throwaway credential store. Invite-token auth avoids that: Brey issues an
opaque token per invited user, the user presents it as a bearer token, and
the whole thing is replaced wholesale (not migrated field-by-field) once a
real provider is chosen. No password hashing, no reset flow, no password
strength policy to get wrong in a first pass.

WHY TOKENS ARE HASHED AT REST
------------------------------
The raw token is a bearer credential -- anyone who reads it out of the
database could authenticate as that user forever (until revoked). Storing
only sha256(token) means a database read (backup, dump, accidental log)
never yields a usable credential; verifying a presented token means
hashing it and comparing hashes, never storing or logging the raw value.
This mirrors how the rest of the repo treats forward evidence and prices
as append-only, immutable facts (src/paths.py's evidence_path docstring) --
here the invariant is "the raw secret exists in exactly one place: the
message that was sent to the invited user," and this module must never be
the second place.

SCHEMA
------
users(id, email, created_at, status, plan)
    status: invited | active | suspended
    plan:   none | beta
tokens(token_hash, user_id, created_at, expires_at, revoked_at, first_used_at)
    opaque secrets.token_urlsafe() value, sha256-hashed before storage.
    expires_at is a required ISO-8601 UTC string (invite tokens are not
    forever-lived); revoked_at is NULL until revoke_token() is called.
    first_used_at is NULL until mark_token_first_used() writes it exactly
    once -- see that function's docstring for why it exists (the
    invite_redeemed analytics event, api/auth.py).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from src import paths

ENV_DB_PATH = "APP_DB_PATH"

# Invite tokens default to a 14-day window -- long enough to cover the
# private-alpha signup lag (someone invited on day 1 who doesn't get to it
# until day 10), short enough that a leaked, unused invite doesn't stay
# live indefinitely. Callers may pass an explicit ttl to override.
DEFAULT_TOKEN_TTL = timedelta(days=14)

VALID_STATUSES = ("invited", "active", "suspended",
                  # Self-serve signup states (api/signup.py), added
                  # alongside the invite-only states above -- no ALTER
                  # needed, since status is a validated Python tuple, not
                  # a SQL CHECK constraint (see _ensure_schema).
                  # pending_payment: a signup that has a real Stripe
                  # checkout session open (or about to). waitlisted: a
                  # signup taken while billing wasn't configured (no
                  # STRIPE_API_KEY / no beta price id yet) -- honest
                  # non-answer, not a silently-dropped signup.
                  "pending_payment", "waitlisted")
VALID_PLANS = ("none", "beta")


def db_path() -> Path:
    """Where the sqlite file lives. APP_DB_PATH overrides; default is
    data/app/app.db, anchored to the repo root the same way src/paths.py
    anchors every other data path (never the process cwd)."""
    override = (os.environ.get(ENV_DB_PATH) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return paths.repo_root() / "data" / "app" / "app.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(raw_token: str) -> str:
    """sha256 hex digest of a raw token. The ONLY form of a token that ever
    touches disk -- see module docstring."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """One connection per call, schema ensured, closed on exit. sqlite3's
    per-call connect is cheap enough at this scale (invite-only alpha) and
    sidesteps holding a long-lived handle open across process lifetimes."""
    resolved = path or db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            plan TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    # MIGRATION-SAFE ALTER, not a table rebuild -- same reasoning and same
    # pattern src/appstate/savedbets.py uses for its settlement columns: an
    # existing app.db already has real invite tokens in it, so the new
    # column is added to the table that is already there, guarded by
    # PRAGMA table_info so re-running the ALTER on a db that already has it
    # doesn't raise OperationalError and break every future _connect().
    existing_token_cols = {row["name"] for row in
                           conn.execute("PRAGMA table_info(tokens)")}
    if "first_used_at" not in existing_token_cols:
        conn.execute("ALTER TABLE tokens ADD COLUMN first_used_at TEXT")


@dataclass(frozen=True)
class User:
    id: int
    email: str
    created_at: str
    status: str
    plan: str


def _row_to_user(row: sqlite3.Row) -> User:
    return User(id=row["id"], email=row["email"], created_at=row["created_at"],
                status=row["status"], plan=row["plan"])


def create_user(email: str, *, status: str = "invited", plan: str = "none",
                db: Optional[Path] = None) -> User:
    """Create a user record. Raises ValueError on an unknown status/plan or
    a duplicate email -- both are caller bugs, not runtime conditions to
    swallow."""
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    if plan not in VALID_PLANS:
        raise ValueError(f"unknown plan: {plan!r}")
    email = email.strip().lower()
    if not email:
        raise ValueError("email must not be empty")
    created_at = _now_iso()
    with _connect(db) as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, created_at, status, plan) "
                "VALUES (?, ?, ?, ?)",
                (email, created_at, status, plan))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"user already exists: {email!r}") from exc
        return User(id=cur.lastrowid, email=email, created_at=created_at,
                    status=status, plan=plan)


def get_user(user_id: int, *, db: Optional[Path] = None) -> Optional[User]:
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None


def get_user_by_email(email: str, *, db: Optional[Path] = None) -> Optional[User]:
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),)).fetchone()
        return _row_to_user(row) if row else None


def list_users(*, db: Optional[Path] = None) -> List[User]:
    """Every user, oldest-created first -- the admin listing's one query.

    No pagination: a private beta's whole user table is small enough that
    a plain SELECT * is the honest scope for now, the same "not optimising
    for a scale this product does not have yet" call
    src/appstate/events.py's daily_counts_by_kind makes for the identical
    reason.
    """
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
        return [_row_to_user(r) for r in rows]


def count_outstanding_invites(*, db: Optional[Path] = None,
                              now: Optional[datetime] = None) -> int:
    """How many invite tokens are still redeemable right now: not revoked,
    not expired. A token that already expired or was revoked is not
    something Brey is waiting on anyone to redeem, so it does not count as
    "outstanding" for the admin overview.
    """
    now = now or datetime.now(timezone.utc)
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT expires_at FROM tokens WHERE revoked_at IS NULL").fetchall()
    count = 0
    for row in rows:
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now.astimezone(timezone.utc) < expires_at:
            count += 1
    return count


def set_user_status(user_id: int, status: str, *, db: Optional[Path] = None) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    with _connect(db) as conn:
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))


def set_user_plan(user_id: int, plan: str, *, db: Optional[Path] = None) -> None:
    if plan not in VALID_PLANS:
        raise ValueError(f"unknown plan: {plan!r}")
    with _connect(db) as conn:
        conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))


def issue_invite_token(user_id: int, *, ttl: timedelta = DEFAULT_TOKEN_TTL,
                        db: Optional[Path] = None) -> str:
    """Mint a new opaque bearer token for user_id and return the RAW token.

    This is the only function in this module that ever returns a raw
    token -- callers (the admin invite endpoint) hand it to the invited
    user once and never store it themselves. Only the hash is persisted.
    """
    raw_token = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + ttl
    with _connect(db) as conn:
        conn.execute(
            "INSERT INTO tokens (token_hash, user_id, created_at, expires_at, "
            "revoked_at) VALUES (?, ?, ?, ?, NULL)",
            (_hash_token(raw_token), user_id, created_at.isoformat(),
             expires_at.isoformat()))
    return raw_token


def mark_token_first_used(raw_token: str, *, at: Optional[str] = None,
                          db: Optional[Path] = None) -> bool:
    """Write-once first-use marker for a token: sets `first_used_at` and
    returns True on the ONE call that transitions it from NULL, False on
    every call after (including calls on an unknown, revoked, or expired
    token hash -- rowcount 0 there too).

    WHY THIS IS SEPARATE FROM `authenticate`
    ------------------------------------------
    `authenticate` answers "is this token currently good" and is called on
    every single authed request; this answers a narrower, one-time
    question ("has this token EVER been used before"), for
    api/auth.py's `get_current_user` to emit `events.INVITE_REDEEMED`
    exactly once per token -- the actual invite-redemption moment, not
    every page load after it. Folding this into `authenticate` would mean
    every caller of `authenticate` (including tests that don't care about
    analytics) pays for and has to reason about the write; kept separate,
    `authenticate` stays a pure read and this stays the one write path.

    Deliberately does NOT re-check revocation/expiry itself -- the caller
    (get_current_user) only reaches this after `authenticate` has already
    said the token is currently good, so a second check here would just be
    dead code paying for another query. Calling this with a token that
    never authenticates (unknown hash, or a hash from a different auth
    provider such as a future Clerk JWT) is harmless: the UPDATE simply
    matches zero rows and returns False.
    """
    at = at or _now_iso()
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE tokens SET first_used_at = ? "
            "WHERE token_hash = ? AND first_used_at IS NULL",
            (at, _hash_token(raw_token)))
        return cur.rowcount > 0


def revoke_token(raw_token: str, *, db: Optional[Path] = None) -> bool:
    """Mark a token revoked. Returns True if a matching, not-already-revoked
    token was found."""
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE tokens SET revoked_at = ? "
            "WHERE token_hash = ? AND revoked_at IS NULL",
            (_now_iso(), _hash_token(raw_token)))
        return cur.rowcount > 0


def authenticate(raw_token: str, *, db: Optional[Path] = None,
                  now: Optional[datetime] = None) -> Optional[User]:
    """Resolve a raw bearer token to its User, or None if the token is
    unknown, expired, or revoked. `now` is injectable for deterministic
    expiry tests -- no sleeping in tests to prove expiry works."""
    now = now or datetime.now(timezone.utc)
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM tokens WHERE token_hash = ?",
            (_hash_token(raw_token),)).fetchone()
        if row is None:
            return None
        if row["revoked_at"] is not None:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now.astimezone(timezone.utc) >= expires_at:
            return None
        user_row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        return _row_to_user(user_row) if user_row else None
