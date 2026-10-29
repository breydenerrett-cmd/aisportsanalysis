"""Single-use password-reset tokens, stdlib-only (owner ask 2026-10-29).

WHY: the only recovery was the admin clearing a password and re-issuing an
access code by hand (docs/support/FREE_MEMBERS.md). A member who forgot a
password, or whose account never had one (a comp or tester created by the
admin), now asks for a reset link themselves; api/passwords.py holds the routes.

THE TOKEN. 32 random bytes, url-safe. Only its sha256 is stored (the same
reasoning as users.py's session tokens: a database copy or a backup must not
contain anything that can be replayed). It is single-use (``used_at`` is set by
one atomic UPDATE, so two parallel requests cannot both win) and ends
``TOKEN_TTL`` after it is made. Asking again replaces the earlier unused link,
so at most ONE live link exists per account.

WHAT IS NEVER HERE: the raw token after ``create_token`` returns it, a password,
or a decision about whether an address has an account (the API layer keeps
that from the caller). A used or expired row is deleted on the next create.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.appstate import users as users_store

TOKEN_TTL = timedelta(minutes=30)

# Forgot-password limits: (window seconds, attempts). Tighter than sign-in's:
# each accepted request can cost an email, and no person needs more than a few.
FORGOT_LIMITS = ((60 * 60, 3), (24 * 60 * 60, 8))
FORGOT_IP_LIMITS = ((60 * 60, 10), (24 * 60 * 60, 40))
SCOPE_FORGOT_EMAIL = "forgot_email"
SCOPE_FORGOT_IP = "forgot_ip"
SCOPE_RESET_IP = "reset_ip"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            via TEXT NOT NULL DEFAULT 'email'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS password_reset_user "
                 "ON password_reset_tokens (user_id)")


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def create_token(user_id: int, *, via: str = "email", now: Optional[datetime] = None,
                 conn: Optional[sqlite3.Connection] = None,
                 db: Optional[Path] = None) -> "tuple[str, datetime]":
    """Mint a link token for user_id; returns (RAW token, expires_at). Replaces
    any earlier unused token of the same account. Pass ``conn`` to do it inside
    the caller's transaction (the admin route audits in the same one)."""
    when = _aware(now or datetime.now(timezone.utc))
    raw = secrets.token_urlsafe(32)
    ends = when + TOKEN_TTL

    def write(c: sqlite3.Connection) -> None:
        ensure_schema(c)
        c.execute("DELETE FROM password_reset_tokens WHERE user_id = ? OR expires_at < ?",
                  (user_id, (when - timedelta(days=1)).isoformat()))
        c.execute("INSERT INTO password_reset_tokens (token_hash, user_id, created_at, expires_at, used_at, via) "
                  "VALUES (?, ?, ?, ?, NULL, ?)",
                  (hash_token(raw), user_id, when.isoformat(), ends.isoformat(), via))

    if conn is not None:
        write(conn)
    else:
        with users_store._connect(db) as c:
            write(c)
    return raw, ends


def consume_token(raw: object, *, now: Optional[datetime] = None,
                  db: Optional[Path] = None) -> Optional[int]:
    """Spend a token: the account id if it was live and unused (now marked
    used), else None. One UPDATE decides, so a token works exactly once."""
    if not isinstance(raw, str) or not raw or len(raw) > 200:
        return None
    when = _aware(now or datetime.now(timezone.utc))
    with users_store._connect(db) as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT user_id, expires_at FROM password_reset_tokens "
                           "WHERE token_hash = ? AND used_at IS NULL", (hash_token(raw),)).fetchone()
        if row is None:
            return None
        try:
            if _aware(datetime.fromisoformat(row["expires_at"])) <= when:
                return None
        except ValueError:
            return None
        cur = conn.execute("UPDATE password_reset_tokens SET used_at = ? "
                           "WHERE token_hash = ? AND used_at IS NULL", (when.isoformat(), hash_token(raw)))
        return int(row["user_id"]) if cur.rowcount == 1 else None


def live_owner(raw: object, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> Optional[int]:
    """The account a token belongs to if it could still be spent, else None.
    Does not spend it (the reset route checks the password rules first, so a
    weak password never burns the link)."""
    if not isinstance(raw, str) or not raw or len(raw) > 200:
        return None
    when = _aware(now or datetime.now(timezone.utc))
    with users_store._connect(db) as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT user_id, expires_at FROM password_reset_tokens "
                           "WHERE token_hash = ? AND used_at IS NULL", (hash_token(raw),)).fetchone()
    if row is None:
        return None
    try:
        return int(row["user_id"]) if _aware(datetime.fromisoformat(row["expires_at"])) > when else None
    except ValueError:
        return None
