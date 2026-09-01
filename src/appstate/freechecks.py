"""Lifetime free Bet Check budget for anonymous visitors, stdlib sqlite3,
same db file as src/appstate/users.py.

WHY THIS EXISTS
---------------
web/landing.html sells "3 introductory Bet Checks, no card required" as the
top-of-funnel offer, but every bet-check route requires an authenticated,
paid (or invite-token) caller -- red-team finding 2, 2026-09-01, mounted at
api/app.py's `_authed_paid`. That mismatch is a launch blocker: the first
real visitor who takes the landing page at its word gets a 401. This table
is the honest version of that offer -- a SERVER-side lifetime counter, so
the promise is enforced where it cannot be edited by whoever is holding the
other end of the connection.

THE IDENTITY: A SERVER-MINTED OPAQUE TOKEN, STORED ONLY AS ITS HASH
----------------------------------------------------------------------
`issue_grant()` mints a 256-bit `secrets.token_urlsafe` value, hands the raw
string back exactly once, and stores only `sha256(raw)` -- the same
never-store-the-raw-credential rule src/appstate/users.py applies to bearer
tokens. A caller proves which free identity it is by presenting the raw
token back; anything else is not that identity.

Deliberately NOT an HMAC-signed self-describing token. A signed token would
need a server secret to exist, be configured, be rotated, and never leak,
and would still have to be checked against this table to know how many
checks it had already spent (a self-describing count is exactly the thing a
client must not get to assert). An unguessable random whose hash is the
primary key gets the same property with no secret at all: an unknown token
is simply not a row, and a forged or tampered one is indistinguishable from
a first-time visitor -- it gets a FRESH budget, never someone else's
remaining checks and never extra checks of its own.

WHAT THIS DEFENDS AGAINST, AND WHAT IT DOES NOT
--------------------------------------------------
Defends against: a client claiming its own remaining count (the count lives
here, never in the token); a client replaying a fourth check (the UPDATE is
conditional and atomic); a process restart resetting the budget (this is
sqlite on disk, not memory); one visitor's token spending another's budget
(the token is 256 bits of randomness).

Does NOT defend against: a visitor who clears the stored token and asks for
three more. That is accepted for the beta, on purpose. The alternatives --
keying on IP (shared: one office, one campus, one carrier NAT would burn
each other's free checks, and the landing page's promise would be broken
for real people), or a device fingerprint (a tracking apparatus this
product does not want and has no consent flow for) -- are each worse than
the leak they close. What bounds the damage instead is the SHAPE of what a
free check returns: one game's Bet Check for one stated price, at a tight
per-IP rate limit (api/betcheck.py's own free-route limiter), with no bulk
or slate-wide odds data reachable from it. Farming it is strictly slower
than reading the same numbers off any sportsbook.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Tuple

from src.appstate import users as users_store

# The offer the landing page makes, in one place. LIFETIME per free
# identity -- not per day, not per session: three checks, then the signup
# wall. Named here rather than inlined at the route so the number the
# marketing copy promises and the number the server enforces are one
# constant, and a change to the offer is a one-line change here.
FREE_CHECK_LIFETIME_LIMIT = 3

# 32 bytes of os.urandom, urlsafe-encoded. Same order of magnitude as
# src/appstate/users.py's invite tokens: unguessable is the whole security
# property this identity has, so it does not get a shorter value for the
# sake of a tidier URL (it never appears in one).
_TOKEN_BYTES = 32


@dataclass(frozen=True)
class FreeCheckGrant:
    """One anonymous free identity's ledger row. `token_hash`, never the
    raw token -- this dataclass is what every read returns, and it must be
    safe to log, so the raw credential is not in it."""
    token_hash: str
    checks_used: int
    created_at: str
    updated_at: str

    @property
    def remaining(self) -> int:
        """Never negative, even if the limit is ever lowered under a grant
        that already spent more than the new limit -- a negative "remaining"
        is not a thing a client can render honestly."""
        return max(FREE_CHECK_LIFETIME_LIMIT - self.checks_used, 0)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_token(raw_token: str) -> str:
    """The only form of a free-check token this module stores or compares --
    sha256 hex, same hashing rule src/appstate/users.py states for bearer
    tokens. Callers pass the RAW token here; nothing else in the codebase
    should hand-roll this."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """One connection per call, schema ensured, closed on exit -- the same
    shape src.appstate.customers._connect uses, deliberately: this table
    lives in the same db file and must behave identically under concurrent
    and test use."""
    resolved = path or users_store.db_path()
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
        CREATE TABLE IF NOT EXISTS free_check_grants (
            token_hash TEXT PRIMARY KEY,
            checks_used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)


def _row_to_grant(row: sqlite3.Row) -> FreeCheckGrant:
    return FreeCheckGrant(token_hash=row["token_hash"],
                          checks_used=row["checks_used"],
                          created_at=row["created_at"],
                          updated_at=row["updated_at"])


def issue_grant(*, db: Optional[Path] = None) -> Tuple[str, FreeCheckGrant]:
    """Mint a brand-new free identity: returns `(raw_token, grant)`.

    The raw token is returned HERE AND NOWHERE ELSE -- only its hash is
    stored, so a caller that loses it cannot recover it (they get a new
    identity with a fresh budget instead, which is the accepted beta
    trade-off this module's docstring names).
    """
    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = _now_iso()
    with _connect(db) as conn:
        conn.execute(
            "INSERT INTO free_check_grants (token_hash, checks_used, "
            "created_at, updated_at) VALUES (?, 0, ?, ?)",
            (hash_token(raw_token), now, now))
    return raw_token, FreeCheckGrant(token_hash=hash_token(raw_token),
                                     checks_used=0, created_at=now,
                                     updated_at=now)


def get_grant(raw_token: Optional[str], *,
              db: Optional[Path] = None) -> Optional[FreeCheckGrant]:
    """The grant `raw_token` names, or None for an absent, empty, unknown,
    forged or tampered token -- all five are the same answer on purpose
    (see the module docstring): the caller is simply not an identity this
    server has ever issued, and the route's job is then to mint one, not to
    grant extra checks or to guess which existing row was meant."""
    if not raw_token or not isinstance(raw_token, str):
        return None
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM free_check_grants WHERE token_hash = ?",
            (hash_token(raw_token),)).fetchone()
        return _row_to_grant(row) if row else None


def consume_check(raw_token: str, *,
                  db: Optional[Path] = None) -> Optional[FreeCheckGrant]:
    """Spend one free check for `raw_token`; the updated grant, or None if
    the token is unknown OR already at the limit.

    The increment is a single conditional UPDATE (`WHERE checks_used <
    limit`), not a read-then-write: two concurrent requests holding the same
    token on a grant with one check left must not both succeed, and sqlite's
    own row-level atomicity is what makes that true here rather than a lock
    this module would have to get right itself. A None return is therefore
    "the budget was already spent", which the route renders as the same
    structured refusal an up-front exhausted check does.
    """
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE free_check_grants SET checks_used = checks_used + 1, "
            "updated_at = ? WHERE token_hash = ? AND checks_used < ?",
            (_now_iso(), token_hash, FREE_CHECK_LIFETIME_LIMIT))
        if cur.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM free_check_grants WHERE token_hash = ?",
            (token_hash,)).fetchone()
        return _row_to_grant(row) if row else None
