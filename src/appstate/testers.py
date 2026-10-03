"""Early-access testers: the first 20, seven days each, no card, chosen by hand.

THE POLICY THIS MODULE IMPLEMENTS (owner decision, 2026-10-02)
-----------------------------------------------------------------
The first TESTER_LIMIT qualified testers get TESTER_ACCESS_TTL of early
access with no card. Brey decides who is qualified and grants access himself
from the admin page; access is extended only when useful feedback justifies
it. Billing is off in production and stays off -- nothing here touches Stripe,
and a tester is NOT a subscriber: a user with a subscription record (a paying
or formerly paying customer) is refused, because granting them "tester access"
would blur two different relationships.

The product is early access and the performance is not proven. Nothing in this
module, in the admin page that drives it, or in the public copy that
advertises it may promise profit, an edge or winning picks.

WHY A TABLE AND NOT A COLUMN ON `users`
------------------------------------------
Three facts have to outlive a restart and a token's expiry:

  * WHO was ever granted a slot. The cap is "distinct users ever granted", so
    it must not shrink when a token expires, and it must not be derived from
    `tokens` (a user can hold several) or from the events table (events are
    written best-effort and may be lost -- see events.record_event_safe). A
    row per user with the user id as PRIMARY KEY makes "distinct" structural:
    the same person can never occupy two slots.
  * WHEN each grant and each extension happened, and WHY an extension was
    justified. One user can be extended many times, so extensions are rows of
    their own (tester_extensions), not a nullable column that keeps only the
    last reason.
  * The access window, so the admin page can say when it ends.

Same pattern src/appstate/customers.py uses for the billing tables: separate
`CREATE TABLE IF NOT EXISTS` statements against the one app.db, no migration
framework, no change to the `users` table itself.

    testers(user_id PK, granted_at, expires_at)
        expires_at is the expiry of the NEWEST tester token (written at grant,
        moved forward by each extension). Older tokens keep their own expiry in
        `tokens`; they are never revoked here.
    tester_extensions(id PK, user_id, extended_at, expires_at, reason)
        append-only; reason is required free text, what feedback justified it.

HOW THE CAP HOLDS ACROSS RESTARTS AND CONCURRENT GRANTS
----------------------------------------------------------
The count is `SELECT COUNT(*) FROM testers`, read inside the same transaction
that inserts the new row, and that transaction is opened with BEGIN IMMEDIATE:
it takes sqlite's write lock BEFORE the count is read. Two grants racing at 19
therefore serialise -- the second waits (busy_timeout, 5 s), then reads 20 and
is refused. A deferred transaction would let both read 19 and both insert. The
user row, the tester row, the status change and the token are one transaction,
so a refusal or a crash leaves nothing behind: no half-created user, no slot
burned without a token. The count lives in the database file, so a restart
cannot reset it.

SUPPORT PROCEDURE (there is no email sender; Brey sends the token himself)
-----------------------------------------------------------------------------
  1. Admin page, Testers section: type the email, "Grant 7-day tester access".
  2. The raw token is shown ONCE. Send it to the person yourself (email or a
     DM), as a link or as the token to paste into the sign-in page.
  3. It is not stored (only its hash is) and cannot be shown again. If it is
     lost, "Extend 7 days" with a reason issues a fresh one; it does not use a
     second slot.
  4. Never paste a token into a ticket, a log or a chat that persists. The
     events `tester_access_granted` / `tester_access_extended` record that it
     happened, never the token, the email or the reason.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from src.appstate import activation
from src.appstate import attribution
from src.appstate import customers
from src.appstate import events
from src.appstate import users as users_store

# THE TWO NUMBERS OF THE OFFER, in one place. The admin API reports them, the
# admin page displays what the API reports, and tests/test_tester_access.py
# pins that the public pages (web/js/checkout.js, web/landing.html) say the
# same two numbers -- those pages cannot import Python, so a test is the only
# thing keeping the advertised offer and the enforced offer equal.
TESTER_LIMIT = 20
TESTER_ACCESS_TTL = timedelta(days=7)

# An extension's reason is a note to Brey's future self ("replied with three
# specific problems on the card page"), not an essay.
MAX_REASON_LENGTH = 500

# Same bound and the same deliberately simple shape api/signup.py uses: a typo
# guard, not an RFC 5322 validator.
MAX_EMAIL_LENGTH = 254
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TesterRefused(Exception):
    """A request the policy refuses. `code` is a stable machine word the API
    returns as `error`; `status` is the HTTP status the API layer uses; `extra`
    is whatever structured context helps (the current count, for the cap)."""

    def __init__(self, code: str, message: str, *, status: int = 409, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


@dataclass(frozen=True)
class TesterGrant:
    """What a grant or an extension hands back. `token` is the RAW bearer token
    and exists only here; repr=False keeps it out of any accidental log line or
    traceback that prints the object."""
    user_id: int
    email: str
    token: str = field(repr=False)
    granted_at: str
    expires_at: str
    testers_granted: int
    testers_limit: int = TESTER_LIMIT
    # 0 on a grant; on an extension, how many extensions this person now has.
    extension_number: int = 0


def _utc(now: Optional[datetime]) -> datetime:
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """users.py's connection (WAL, busy_timeout, users and tokens ensured),
    plus this module's two tables. Rides on `users_store._connect` so there is
    one place that decides how the app database is opened, and so a test that
    patches `users_store.db_path` redirects this module too."""
    with users_store._connect(path) as conn:
        _ensure_schema(conn)
        yield conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS testers (
            user_id INTEGER PRIMARY KEY,
            granted_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tester_extensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            extended_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            reason TEXT NOT NULL
        )
    """)


def normalise_email(email: str) -> str:
    """Lower-cased, stripped, shape-checked; TesterRefused (400) otherwise."""
    cleaned = (email or "").strip().lower()
    if not cleaned or len(cleaned) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(cleaned):
        raise TesterRefused("invalid_email", "a valid email is required", status=400)
    return cleaned


def count_granted(*, db: Optional[Path] = None) -> int:
    """How many distinct users have EVER been granted tester access. Never
    reduced by expiry; the number the cap is enforced against."""
    with _connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM testers").fetchone()[0]


def _begin_exclusive(conn: sqlite3.Connection) -> None:
    """Take the write lock now, before anything is read -- see the module
    docstring's cap section. Raises if a transaction is already open, which
    would mean the lock is NOT held and the cap check below would be a race."""
    if conn.in_transaction:
        raise RuntimeError("a transaction was already open; the cap check "
                           "would not be atomic")
    conn.execute("BEGIN IMMEDIATE")


def grant_tester(*, email: Optional[str] = None, user_id: Optional[int] = None,
                 now: Optional[datetime] = None,
                 db: Optional[Path] = None) -> TesterGrant:
    """Grant early access to one person and return their RAW token (once).

    Exactly one of `email` or `user_id` (ValueError otherwise; the API layer
    turns that into a 400 before calling). An unknown email creates the user,
    as POST /admin/invites does; an unknown user_id is a refusal (404).

    Refusals, each raised BEFORE anything is written (and the whole transaction
    is rolled back regardless):
      suspended            the account is suspended: a token would not open anything.
      has_subscription     a subscription record exists: a paying or formerly
                           paying customer is not a tester.
      checkout_open        status pending_payment: a checkout is open for this
                           person; granting free access would race it.
      already_a_tester     already granted. Use the extension, which does not
                           take a second slot.
      tester_limit_reached TESTER_LIMIT users have already been granted.

    A `waitlisted` user becomes `invited` (so a repeat signup is told "that
    email already has an account" rather than being put back on the list); an
    `invited` or `active` user keeps their status; a new user starts `invited`.
    Plan is not touched: a tester is not on the beta plan.

    The subscription lookup happens BEFORE the write lock is taken (it goes
    through customers.get_subscription_record, not raw SQL on another module's
    table, and it opens its own connection). The window that leaves is a webhook
    creating a subscription for this very user between the lookup and the grant;
    it is harmless, because api/auth.py's require_paid_access still entitlement-
    checks any user with a subscription record, so the tester token could not
    open anything the subscription does not.
    """
    if (email is None) == (user_id is None):
        raise ValueError("pass exactly one of email or user_id")
    when = _utc(now)
    address = normalise_email(email) if email is not None else None

    if address is not None:
        known = users_store.get_user_by_email(address, db=db)
    else:
        known = users_store.get_user(user_id, db=db)
        if known is None:
            raise TesterRefused("no_such_user", "no such user", status=404)
    if known is not None and customers.get_subscription_record(known.id, db=db) is not None:
        raise TesterRefused(
            "has_subscription",
            "this person has a subscription record; a paying or formerly paying "
            "customer is not a tester")

    with _connect(db) as conn:
        _begin_exclusive(conn)
        granted = conn.execute("SELECT COUNT(*) FROM testers").fetchone()[0]
        # Re-read inside the lock: the status may have changed since the
        # lookup above, and the new-user branch needs to know the email is
        # still free.
        row = (conn.execute("SELECT * FROM users WHERE email = ?", (address,)).fetchone()
               if address is not None else
               conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        if row is None and address is None:
            raise TesterRefused("no_such_user", "no such user", status=404)

        if row is not None:
            if row["status"] == "suspended":
                raise TesterRefused("user_suspended", "this account is suspended")
            if row["status"] == "pending_payment":
                raise TesterRefused(
                    "checkout_open",
                    "a checkout is open for this person (status pending_payment); "
                    "tester access was not granted")
            if conn.execute("SELECT 1 FROM testers WHERE user_id = ?",
                            (row["id"],)).fetchone():
                raise TesterRefused(
                    "already_a_tester",
                    "this person is already a tester; use Extend, which does not "
                    "use another of the slots", testers_granted=granted,
                    testers_limit=TESTER_LIMIT)
        if granted >= TESTER_LIMIT:
            raise TesterRefused(
                "tester_limit_reached",
                f"{granted} of {TESTER_LIMIT} tester slots are already granted; "
                "nothing was written", testers_granted=granted,
                testers_limit=TESTER_LIMIT)

        if row is None:
            cur = conn.execute(
                "INSERT INTO users (email, created_at, status, plan) "
                "VALUES (?, ?, 'invited', 'none')", (address, when.isoformat()))
            uid, mail = cur.lastrowid, address
        else:
            uid, mail = row["id"], row["email"]
            if row["status"] == "waitlisted":
                conn.execute("UPDATE users SET status = 'invited' WHERE id = ?", (uid,))
        expires = when + TESTER_ACCESS_TTL
        conn.execute(
            "INSERT INTO testers (user_id, granted_at, expires_at) VALUES (?, ?, ?)",
            (uid, when.isoformat(), expires.isoformat()))
        raw_token = users_store.insert_token(conn, uid, ttl=TESTER_ACCESS_TTL, now=when)
    return TesterGrant(user_id=uid, email=mail, token=raw_token,
                       granted_at=when.isoformat(), expires_at=expires.isoformat(),
                       testers_granted=granted + 1)


def extend_tester(user_id: int, reason: str, *, now: Optional[datetime] = None,
                  db: Optional[Path] = None) -> TesterGrant:
    """Issue a NEW tester-length token for an existing tester and record why.

    Old tokens are neither revoked nor shortened: each keeps its own expiry, so
    extending can only ever give the person MORE time, never take access away
    mid-test. It does not use another slot (the testers row already exists).
    Refused: an unknown user (404), a user who was never granted (not_a_tester),
    a suspended one, a tester with a subscription record (409 has_subscription,
    the reason grant_tester gives: a paying or formerly paying customer is not a
    tester, and a new tester-length token would be refused by the paid surface
    anyway -- 402 on every page -- so extending would hand back a token that
    opens nothing), and an empty or over-long reason (400) -- the reason is
    the owner's own record of what feedback earned the extension, and an
    extension without one is how "extended only when useful" turns into
    "extended by default".
    """
    why = (reason or "").strip()
    if not why:
        raise TesterRefused(
            "reason_required",
            "say what feedback justified the extension", status=400)
    if len(why) > MAX_REASON_LENGTH:
        raise TesterRefused(
            "reason_too_long",
            f"keep the reason under {MAX_REASON_LENGTH} characters", status=400)
    when = _utc(now)
    # Looked up before the write lock, as grant_tester does (another module's
    # table, its own connection).
    has_subscription = customers.get_subscription_record(user_id, db=db) is not None
    with _connect(db) as conn:
        _begin_exclusive(conn)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise TesterRefused("no_such_user", "no such user", status=404)
        tester = conn.execute("SELECT * FROM testers WHERE user_id = ?",
                              (user_id,)).fetchone()
        if tester is None:
            raise TesterRefused(
                "not_a_tester",
                "this person was never granted tester access; grant it first")
        if row["status"] == "suspended":
            raise TesterRefused("user_suspended", "this account is suspended")
        if has_subscription:
            raise TesterRefused(
                "has_subscription",
                "this person has a subscription record; a paying or formerly paying "
                "customer is not a tester, and a new tester token would not open "
                "anything for them")
        expires = when + TESTER_ACCESS_TTL
        raw_token = users_store.insert_token(conn, user_id, ttl=TESTER_ACCESS_TTL, now=when)
        conn.execute("UPDATE testers SET expires_at = ? WHERE user_id = ?",
                     (expires.isoformat(), user_id))
        conn.execute(
            "INSERT INTO tester_extensions (user_id, extended_at, expires_at, reason) "
            "VALUES (?, ?, ?, ?)", (user_id, when.isoformat(), expires.isoformat(), why))
        granted = conn.execute("SELECT COUNT(*) FROM testers").fetchone()[0]
        number = conn.execute(
            "SELECT COUNT(*) FROM tester_extensions WHERE user_id = ?",
            (user_id,)).fetchone()[0]
    return TesterGrant(user_id=user_id, email=row["email"], token=raw_token,
                       granted_at=tester["granted_at"], expires_at=expires.isoformat(),
                       testers_granted=granted, extension_number=number)


def list_testers(*, db: Optional[Path] = None) -> dict:
    """Every tester, oldest grant first, plus the counts the admin page shows.

    Two different facts, kept apart (src/appstate/activation.py defines both):

      * `first_used_at` / `first_signin_at` is the earliest first use of ANY of
        the person's tokens: they signed in. A person who lost one token and
        was sent another still counts as having signed in. That is NOT
        activation.
      * `activated` means the person has had at least one VALUE ACTION: an
        authenticated request that returned product content (a card, a
        matchup, props, ...). `activated_at` is the first one,
        `hours_signup_to_activation` is account creation to that moment,
        `returning` is a second value action 12 hours or more later, and
        `features` counts value actions per feature label.

    The value-action facts come from one bounded, grouped query over the
    analytics events for these testers' hashes only (activation.py).
    """
    with _connect(db) as conn:
        rows = conn.execute("""
            SELECT t.user_id, t.granted_at, t.expires_at, u.email, u.status,
                   u.created_at,
                   (SELECT MIN(k.first_used_at) FROM tokens k
                     WHERE k.user_id = t.user_id) AS first_used_at
              FROM testers t JOIN users u ON u.id = t.user_id
             ORDER BY t.granted_at ASC, t.user_id ASC
        """).fetchall()
        extensions: Dict[int, List[dict]] = {}
        for ext in conn.execute(
                "SELECT user_id, extended_at, expires_at, reason "
                "FROM tester_extensions ORDER BY id ASC"):
            extensions.setdefault(ext["user_id"], []).append(
                {"extended_at": ext["extended_at"], "expires_at": ext["expires_at"],
                 "reason": ext["reason"]})
    hashes = {r["user_id"]: events.hash_user_id(r["user_id"]) for r in rows}
    stats = activation.value_action_stats(list(hashes.values()), db=db)
    testers = []
    for r in rows:
        activity = activation.user_activity(
            stats.get(hashes[r["user_id"]]), account_created_at=r["created_at"],
            tester_granted_at=r["granted_at"], first_signin_at=r["first_used_at"])
        testers.append({
            "user_id": r["user_id"], "email": r["email"], "status": r["status"],
            "granted_at": r["granted_at"], "expires_at": r["expires_at"],
            "first_used_at": r["first_used_at"],
            **activity,
            "extensions": extensions.get(r["user_id"], []),
        })
    return {"testers": testers, "granted": len(testers), "limit": TESTER_LIMIT,
            "remaining": max(TESTER_LIMIT - len(testers), 0),
            "ttl_days": TESTER_ACCESS_TTL.days}


def activation_report(*, now: Optional[datetime] = None,
                      db: Optional[Path] = None) -> dict:
    """The aggregate behind GET /admin/activation: no emails, no user ids.

    Our own test accounts do not count. A tester whose stored signup
    attribution has utm_source `internal` or `internal-...` (the one rule in
    attribution.is_internal_source, shared with the funnel report) is left out
    of every number and counted in `internal_excluded` instead. A tester with
    no stored attribution is a real tester.
    """
    when = _utc(now)
    rows = list_testers(db=db)["testers"]
    internal = {r["user_id"] for r in rows if attribution.is_internal_source(
        customers.get_signup_attribution(r["user_id"], db=db).get("utm_source"))}
    return activation.summarise(rows, internal_ids=internal, as_of=when)


def tester_marks(*, db: Optional[Path] = None) -> Dict[int, dict]:
    """user_id -> {granted_at, expires_at}, for the /admin/users listing."""
    with _connect(db) as conn:
        return {r["user_id"]: {"granted_at": r["granted_at"], "expires_at": r["expires_at"]}
                for r in conn.execute("SELECT user_id, granted_at, expires_at FROM testers")}
