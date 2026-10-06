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

The early-access tester tables (testers, tester_extensions) are NOT created
here: src/appstate/testers.py owns them, the same way customers.py owns the
billing tables in this same file. A tester's token is an ordinary row in
`tokens` and authenticates exactly like an invite token.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

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


# How many times _set_wal_mode retries a "database is locked" failure
# before giving up, and how long it sleeps between tries. 10 x 20ms = 200ms
# worst case -- generous next to how briefly the WAL-transition lock this
# guards against is actually held (a few microseconds of another
# connection's own PRAGMA journal_mode=WAL call), stingy next to
# busy_timeout's own 5s window, since this is a fallback for a failure mode
# busy_timeout does not cover at all (see _set_wal_mode's docstring) rather
# than a normal lock wait.
_WAL_MODE_RETRY_ATTEMPTS = 10
_WAL_MODE_RETRY_DELAY_S = 0.02


def _set_wal_mode(conn: sqlite3.Connection) -> None:
    """PRAGMA journal_mode=WAL, with a small manual retry on top of
    busy_timeout -- because busy_timeout alone does not cover this one.

    WHY busy_timeout DOES NOT ALREADY HANDLE THIS
    -------------------------------------------------
    busy_timeout (set on this connection before this call -- see
    _connect) makes an ordinary write-lock conflict retry instead of
    raising immediately. The FIRST-EVER transition of a brand-new db file
    into WAL mode is not an ordinary write-lock conflict: it briefly takes
    a special, whole-file exclusive lock through a different internal path
    that does not go through sqlite's normal busy-handler retry mechanism.
    Two connections racing to be the first to open a fresh db file (this
    module's own tokens table on a first-ever request, or
    tests/test_appstate_sqlite_pragmas.py's concurrent-writer smoke test
    starting from an empty temp db) can hit this: one wins, the other's
    identical `PRAGMA journal_mode=WAL` call raises "database is locked"
    INSTANTLY -- not after waiting out busy_timeout's 5s, because the
    busy-handler backing busy_timeout is never invoked for this particular
    lock at all. Reordering busy_timeout before journal_mode (this
    module's other pragma comment) fixes every OTHER lock conflict on this
    connection; it does not fix this one, which is why this function
    exists as a second, narrower guard.

    Retrying by hand here is standard practice for this specific,
    documented sqlite behavior -- once WAL mode is actually established
    (recorded in the db file itself), every future call to this pragma is
    the ordinary, lock-respecting confirmation read the rest of this
    module's comments describe, and returns on the very first try.
    """
    last_exc: Optional[sqlite3.OperationalError] = None
    for _ in range(_WAL_MODE_RETRY_ATTEMPTS):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc):
                raise  # a different failure -- not the race this retries
            last_exc = exc
            time.sleep(_WAL_MODE_RETRY_DELAY_S)
    raise last_exc


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """One connection per call, schema ensured, closed on exit. sqlite3's
    per-call connect is cheap enough at this scale (invite-only alpha) and
    sidesteps holding a long-lived handle open across process lifetimes."""
    resolved = path or db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    # busy_timeout FIRST, journal_mode SECOND -- THE ORDER IS LOAD-BEARING.
    # busy_timeout is a per-CONNECTION setting (unlike journal_mode, it is
    # NOT persisted in the file) and defaults to 0 (fail instantly, no
    # retry) on a brand-new connection. Setting journal_mode=WAL first
    # would run THAT pragma itself with the default zero timeout still in
    # effect for every OTHER lock conflict it might hit. Reversed (as it
    # is here), busy_timeout is in effect for every later statement this
    # connection runs. (_set_wal_mode below covers the one lock conflict
    # busy_timeout can't -- see its own docstring.)
    conn.execute("PRAGMA busy_timeout=5000")
    # WAL (write-ahead log) journal mode lets readers run concurrently with
    # a writer instead of sqlite's default rollback journal, which locks
    # the whole db file for every writer and blocks every reader until it
    # commits. Idempotent: sqlite records the journal mode IN THE DB FILE
    # ITSELF, so setting it on every connect is a cheap no-op after the
    # first time, not a repeated migration.
    _set_wal_mode(conn)
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
    #
    # The check-then-ALTER above is still two separate statements, not one
    # atomic operation -- see src/appstate/savedbets.py's identical comment
    # (tests/test_appstate_sqlite_pragmas.py's concurrent smoke test caught
    # this exact race there first): two connections opening a brand-new db
    # at once can both read "column absent," and the loser's own ALTER then
    # fails with "duplicate column name" once the winner has already added
    # it. Not a real failure -- the column exists either way -- so it is
    # swallowed; anything else still raises.
    existing_token_cols = {row["name"] for row in
                           conn.execute("PRAGMA table_info(tokens)")}
    if "first_used_at" not in existing_token_cols:
        try:
            conn.execute("ALTER TABLE tokens ADD COLUMN first_used_at TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise


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


def insert_token(conn: sqlite3.Connection, user_id: int, *, ttl: timedelta,
                 now: Optional[datetime] = None) -> str:
    """Mint a token ON AN OPEN CONNECTION and return the RAW token; the caller
    owns the transaction.

    Split out of `issue_invite_token` for one reason: src/appstate/testers.py
    must create the tester row and its token in ONE transaction. Two separate
    connections would let a crash between them burn one of the 20 tester slots
    with no token anyone could ever be sent. `issue_invite_token` is now a
    thin wrapper, so there is still exactly one place a token row is written.
    """
    raw_token = secrets.token_urlsafe(32)
    created_at = now or datetime.now(timezone.utc)
    expires_at = created_at + ttl
    conn.execute(
        "INSERT INTO tokens (token_hash, user_id, created_at, expires_at, "
        "revoked_at) VALUES (?, ?, ?, ?, NULL)",
        (_hash_token(raw_token), user_id, created_at.isoformat(),
         expires_at.isoformat()))
    return raw_token


def issue_invite_token(user_id: int, *, ttl: timedelta = DEFAULT_TOKEN_TTL,
                        db: Optional[Path] = None) -> str:
    """Mint a new opaque bearer token for user_id and return the RAW token.

    This is the only function in this module that ever returns a raw
    token -- callers (the admin invite endpoint) hand it to the invited
    user once and never store it themselves. Only the hash is persisted.
    """
    with _connect(db) as conn:
        return insert_token(conn, user_id, ttl=ttl)


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


def _wipe_activation_tokens(conn: sqlite3.Connection, *, user_id: Optional[int] = None,
                            raw_token: Optional[str] = None) -> None:
    """Forget the UNHASHED copy of a revoked credential, on the caller's open
    transaction.

    WHY THIS LIVES HERE. A checkout buyer's token is also stored raw in
    signup_activation_tokens (src/appstate/customers.py) so GET /signup/complete
    can hand it over: unread for up to 72 h, and for 10 minutes after the first
    read. Revoking the token in `tokens` alone left that copy readable, and the
    bridge kept returning a credential that authenticate() rejects -- the page
    then stored it over the buyer's good one (found in review 2026-10-05). Every
    revoke path therefore wipes it in the SAME transaction, so there is no
    instant where the old token is revoked and still being given out.

    `retrieved_at` is stamped like the bridge's own scrub does (customers.
    _scrub_if_expired): a row with no raw token and no retrieved_at would let the
    bridge's atomic claim "win" and hand back a None token. Stamped, a wiped row
    is indistinguishable from an already-used one.

    users.py cannot import customers (customers imports this module), and the
    table only exists once customers has opened the database, so this is plain SQL
    guarded by a table-exists check. Match by user_id (every token of the user) or
    by the exact raw token (one revoked token)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'signup_activation_tokens'").fetchone()
    if exists is None:
        return
    if user_id is not None:
        where, arg = "user_id = ?", user_id
    elif raw_token is not None:
        where, arg = "raw_token = ?", raw_token
    else:
        return
    conn.execute(
        "UPDATE signup_activation_tokens SET raw_token = NULL, "
        "retrieved_at = COALESCE(retrieved_at, ?) "
        f"WHERE {where} AND raw_token IS NOT NULL", (_now_iso(), arg))


def revoke_token(raw_token: str, *, db: Optional[Path] = None) -> bool:
    """Mark a token revoked. Returns True if a matching, not-already-revoked
    token was found. The unhashed copy the checkout activation bridge may still
    hold for it is wiped in the same transaction (`_wipe_activation_tokens`)."""
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE tokens SET revoked_at = ? "
            "WHERE token_hash = ? AND revoked_at IS NULL",
            (_now_iso(), _hash_token(raw_token)))
        _wipe_activation_tokens(conn, raw_token=raw_token)
        return cur.rowcount > 0


def revoke_all_tokens(user_id: int, *, db: Optional[Path] = None) -> int:
    """Revoke every not-yet-revoked token belonging to user_id; returns how
    many were revoked. Used by the support token re-issue (POST
    /admin/users/token): a lost or leaked token must stop working at the
    moment its replacement is minted. No schema change -- `revoked_at` is the
    existing column revoke_token already writes. The raw activation tokens the
    checkout bridge holds for this user are wiped in the same transaction."""
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE tokens SET revoked_at = ? "
            "WHERE user_id = ? AND revoked_at IS NULL",
            (_now_iso(), user_id))
        _wipe_activation_tokens(conn, user_id=user_id)
        return cur.rowcount


def count_unrevoked_tokens(user_id: int, *, db: Optional[Path] = None) -> int:
    """How many of user_id's tokens `revoke_all_tokens` / `reissue_token` would
    revoke right now (expired ones count: they are not revoked). Read first by
    the support re-issue so its audit record can be written BEFORE anything is
    changed -- see api/admin.py reissue_access_token."""
    with _connect(db) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM tokens WHERE user_id = ? AND revoked_at IS NULL",
            (user_id,)).fetchone()[0]


def reissue_token(user_id: int, *, expires_at: datetime,
                  now: Optional[datetime] = None,
                  audit: Optional[Callable[[sqlite3.Connection, int], None]] = None,
                  db: Optional[Path] = None) -> Tuple[str, int]:
    """Replace every token of user_id with ONE new token that ends at exactly
    `expires_at`; returns (RAW token, how many old tokens were revoked).

    The revoke and the insert are one transaction: a crash leaves the person
    with their old tokens, never with none and never with two. `expires_at` is
    the caller's to decide and is the whole point of this function over
    `revoke_all_tokens` + `issue_invite_token`: a re-issue replaces a lost
    credential, it must not move the end of what the person was given. A
    tester's token ends at the tester window (testers.expires_at), a
    subscriber's at the usual subscriber lifetime. A time already in the past
    is allowed on purpose: an EXPIRED tester who lost their token needs one
    that authenticates nothing but still identifies them to
    POST /billing/tester-checkout (src/appstate/tester_upgrade.py).

    The raw activation token the checkout bridge may still hold for the user is
    wiped in the same transaction (`_wipe_activation_tokens`): a replaced
    credential must not be handed out by GET /signup/complete.

    `audit(conn, revoked)` is called on the SAME connection after the revoke and
    the insert, before the commit. The support route writes its audit row there,
    so the row and the change are one transaction: if either fails neither
    stays (a "reissued" row for a re-issue that did not happen was the defect).
    An exception from `audit` rolls everything back and propagates.

    Nothing here touches users.status, testers or any billing table."""
    when = now or datetime.now(timezone.utc)
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE tokens SET revoked_at = ? "
            "WHERE user_id = ? AND revoked_at IS NULL",
            (when.isoformat(), user_id))
        revoked = cur.rowcount
        _wipe_activation_tokens(conn, user_id=user_id)
        raw_token = insert_token(conn, user_id, ttl=expires_at - when, now=when)
        if audit is not None:
            audit(conn, revoked)
    return raw_token, revoked


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
