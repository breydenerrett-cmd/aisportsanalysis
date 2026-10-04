"""User <-> Stripe customer/subscription persistence, stdlib sqlite3, same
db file as src/appstate/users.py.

WHY THIS EXISTS
---------------
src/appstate/billing.py's StripeBillingProvider docstring flagged two gaps
before this file existed: `customer_ref_lookup` had no backing store (so
subscription_status/cancel reported "not_configured" for every user
forever, even one with a live subscription), and create_checkout minted a
brand-new Idempotency-Key on every call, so a client retrying a
timed-out/failed checkout request would open a second, disjoint Stripe
checkout session instead of resuming the one already in flight. Both are
billing-correctness bugs, not missing features: a mis-mapped or duplicated
customer is real money moving against the wrong account.

SCHEMA
------
billing_customers(user_id PK, stripe_customer_id UNIQUE, created_at)
    One Stripe customer per local user, created once (in
    StripeBillingProvider._ensure_customer) and reused forever after.
billing_subscriptions(user_id PK, stripe_subscription_id, status, cancel_at,
                      current_period_end, paid_through, sub_created_at,
                      snapshot_at, paid_at, grace_blocked, updated_at)
    The last subscription status this app has SEEN via a *verified*
    webhook (src.appstate.billing.apply_stripe_webhook_event) -- never a
    live Stripe API call. This is what lets api/billing.py's GET
    /billing/status answer instantly from local state instead of calling
    out to Stripe on every page load.

    `paid_through` is what has_paid_access() decides entitlement from: the
    instant the customer has EVIDENCE of payment (or of a free trial) for.
    `current_period_end` is only what Stripe last ANNOUNCED for the
    subscription -- a renewal's new end appears there the moment the period
    rolls over, before (and whether or not) the invoice is paid -- so it is
    kept for display and never grants anything. The three INTEGER columns
    are Stripe-side unix times used to order events (Stripe does not
    deliver in order): `sub_created_at` when the recorded subscription was
    created, `snapshot_at` the newest subscription event applied,
    `paid_at` the newest payment evidence applied. NULL means "unknown",
    which falls back to arrival order for that comparison.
    `grace_blocked` is 1 once a failed payment or a deletion has been applied
    and no payment newer than it has arrived: it withholds the renewal grace
    (RENEWAL_GRACE_SECONDS) even if a later bare `active` event flips the
    status word back, because that event is an announcement, not payment.
billing_checkout_idempotency(user_id, plan_id PK, idempotency_key, created_at)
    Keyed on (user_id, plan_id): a client retrying a failed/timed-out
    checkout attempt for the same plan reuses the same Idempotency-Key
    instead of Stripe treating the retry as a brand-new attempt.
signup_activation_tokens(stripe_session_id PK, user_id, raw_token, created_at)
    The no-email-sender activation bridge (docs for api/signup.py's GET
    /signup/complete): src.appstate.billing.apply_stripe_webhook_event
    mints a fresh access token the moment a verified checkout.session
    .completed activates a pending_payment signup, and stores it here --
    the only table in this file that ever holds a RAW bearer token, which
    is why it is short-lived: take_activation_token() wipes the raw token,
    so a session id (visible in the browser's own success-page URL) stops
    working for good -- immediately by default, or once the
    ACTIVATION_REREAD_WINDOW (10 minutes after the FIRST read) has closed
    when GET /signup/complete asks for the re-read window its polling page
    needs. Never a replay later.
    This is a deliberate, temporary exception to src/appstate/users.py's
    "hash at rest" rule -- the token has nowhere else to wait between the
    webhook call and the browser's own follow-up GET, since there is no
    email sender yet to hand it to the user directly.

Uses the same db file as src/appstate/users.py (APP_DB_PATH env override,
default data/app/app.db) -- separate `CREATE TABLE IF NOT EXISTS` calls
against one sqlite file, the same pattern users.py itself uses for `users`
and `tokens`. db_path is resolved through `users_store.db_path()` at call
time (not imported by value) so tests that monkeypatch
`users_store.db_path` -- see tests/test_api_billing.py -- redirect this
module's writes too, into the same temp db.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Mapping, Optional

from src.appstate import users as users_store

# Same two constants, same values, same rationale as
# src.appstate.users._WAL_MODE_RETRY_ATTEMPTS/_WAL_MODE_RETRY_DELAY_S.
_WAL_MODE_RETRY_ATTEMPTS = 10
_WAL_MODE_RETRY_DELAY_S = 0.02


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_wal_mode(conn: sqlite3.Connection) -> None:
    """PRAGMA journal_mode=WAL, with a small manual retry -- same helper,
    same reasoning as src.appstate.users._set_wal_mode: busy_timeout does
    not cover the special exclusive lock a brand-new db file's FIRST-EVER
    transition into WAL mode takes, so two connections racing to be first
    to open this module's own db file need this narrower retry on top of
    it. See that function's docstring for the full explanation."""
    last_exc: Optional[sqlite3.OperationalError] = None
    for _ in range(_WAL_MODE_RETRY_ATTEMPTS):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            last_exc = exc
            time.sleep(_WAL_MODE_RETRY_DELAY_S)
    raise last_exc


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """One connection per call, schema ensured, closed on exit -- same
    shape as src.appstate.users._connect, deliberately: this module's
    tables live in the same db file and should behave identically under
    concurrent/test use."""
    resolved = path or users_store.db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    # busy_timeout BEFORE journal_mode -- same two pragmas, same order,
    # same rationale as src.appstate.users._connect (this module shares
    # that db file and must behave identically under concurrent access).
    # The order is load-bearing, not stylistic -- see that module's
    # comment for why setting journal_mode first can itself raise
    # "database is locked" with no retry.
    conn.execute("PRAGMA busy_timeout=5000")
    _set_wal_mode(conn)
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str,
                            ddl: str) -> None:
    """ALTER TABLE ADD COLUMN, guarded twice over: PRAGMA table_info first
    (so re-running on a db that already has the column is a no-op, not an
    OperationalError), and a duplicate-column race guard on the ALTER
    itself.

    The two-part guard exists because the check-then-ALTER is NOT one
    atomic operation -- PRAGMA table_info is a plain read needing no write
    lock, so two connections opening a brand-new db at the same instant
    (tests/test_appstate_sqlite_pragmas.py's concurrent-writer smoke test
    caught exactly this, once WAL made the race easy to hit) can both read
    "column absent" before either's ALTER commits; the loser's own ALTER
    then fails with "duplicate column name" once it finally gets the write
    lock, because the winner already added it. That is not a real failure
    -- the column exists either way, which is all this function ever
    promised -- so it is swallowed; any other OperationalError (a
    genuinely broken db, a permissions issue) is a different shape and
    still raises.
    """
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise


def _add_paid_through_columns(conn: sqlite3.Connection) -> None:
    """The 2026-10-04 billing-order migration: `paid_through` plus the three
    event-ordering stamps, added to the table that is already there.

    ADDITIVE AND IDEMPOTENT. Every column is ALTER ... ADD COLUMN on a
    nullable column, so an existing app.db keeps every row and every old
    reader keeps working.

    THE BACKFILL RUNS EXACTLY ONCE, IN THE SAME TRANSACTION AS THE ALTER.
    Before this change `current_period_end` was what access ran to, so a
    customer already recorded with an end keeps that end as their
    paid-through instant -- no one loses access on deploy. The backfill must
    not be repeatable: once the column exists, a NULL `paid_through` beside an
    announced `current_period_end` is a meaningful state (a period was
    announced and nothing was paid), and copying it over on the next
    connection would hand out exactly the access this change withholds. So
    the column's creation and the copy are one BEGIN IMMEDIATE ... COMMIT:
    either both happened or neither did, and a second connection racing this
    one waits on the write lock, re-reads the columns and finds nothing to
    do. A row with NO recorded end gets no paid-through: absent stays absent.
    """
    def present() -> set:
        return {row["name"] for row in conn.execute("PRAGMA table_info(billing_subscriptions)")}

    for column in ("sub_created_at", "snapshot_at", "paid_at", "grace_blocked"):
        _add_column_if_missing(conn, "billing_subscriptions", column, "INTEGER")
    if "paid_through" in present():
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if "paid_through" not in present():
            conn.execute("ALTER TABLE billing_subscriptions ADD COLUMN paid_through TEXT")
            conn.execute("UPDATE billing_subscriptions SET paid_through = current_period_end "
                         "WHERE current_period_end IS NOT NULL")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS billing_customers (
            user_id INTEGER PRIMARY KEY,
            stripe_customer_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS billing_subscriptions (
            user_id INTEGER PRIMARY KEY,
            stripe_subscription_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # MIGRATION-SAFE ALTER, not a table rebuild -- same pattern
    # src/appstate/users.py uses for tokens.first_used_at: an existing
    # app.db already has real subscription rows, so the new column is
    # added to the table that is already there. See _add_column_if_missing
    # for why the guard is two-part (PRAGMA table_info AND a race guard on
    # the ALTER itself), not just the PRAGMA check.
    _add_column_if_missing(conn, "billing_subscriptions", "cancel_at", "TEXT")
    # current_period_end: added for the cancellation policy
    # (docs/LAUNCH_DECISIONS.md: cancel stops renewal, paid access runs to
    # the end of the period already paid for). Without this column there
    # is no honest way to answer "is this canceled customer still
    # entitled?" without a live Stripe call on every request -- see
    # has_paid_access below.
    _add_column_if_missing(conn, "billing_subscriptions", "current_period_end", "TEXT")
    _add_paid_through_columns(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS billing_checkout_idempotency (
            user_id INTEGER NOT NULL,
            plan_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, plan_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signup_activation_tokens (
            stripe_session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            raw_token TEXT,
            created_at TEXT NOT NULL,
            retrieved_at TEXT
        )
    """)
    # First-touch attribution, one row per user (see record_signup_attribution).
    # Raw user_id like every other table in this file; the analytics events
    # table stays hash-only and carries the same values as event properties.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signup_attribution (
            user_id INTEGER PRIMARY KEY,
            utm_source TEXT,
            utm_medium TEXT,
            utm_campaign TEXT,
            utm_content TEXT,
            utm_term TEXT,
            referrer_host TEXT,
            anon_id TEXT,
            created_at TEXT NOT NULL
        )
    """)


def upsert_customer(user_id: int, stripe_customer_id: str, *, db: Optional[Path] = None) -> None:
    """Record (or confirm) that user_id maps to stripe_customer_id.
    Idempotent -- safe to call on every checkout attempt regardless of
    whether a row already exists, which is exactly how
    StripeBillingProvider._ensure_customer uses it."""
    with _connect(db) as conn:
        conn.execute("""
            INSERT INTO billing_customers (user_id, stripe_customer_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET stripe_customer_id = excluded.stripe_customer_id
        """, (user_id, stripe_customer_id, _now_iso()))


def get_customer_ref(user_id: int, *, db: Optional[Path] = None) -> Optional[str]:
    """The Stripe customer id for user_id, or None if no mapping exists
    yet -- the honest default StripeBillingProvider falls back to when no
    lookup at all is injected."""
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = ?",
            (user_id,)).fetchone()
        return row["stripe_customer_id"] if row else None


def get_user_id_by_customer_ref(stripe_customer_id: str, *, db: Optional[Path] = None) -> Optional[int]:
    """Reverse lookup used by the webhook handler: a `customer.subscription.*`
    event carries Stripe's customer id, never this app's local user id."""
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT user_id FROM billing_customers WHERE stripe_customer_id = ?",
            (stripe_customer_id,)).fetchone()
        return row["user_id"] if row else None


_UNSET = object()

# Every column of a subscription row the webhook handler decides, in the
# order mutate_subscription's `decide` callback returns them.
_STATE_FIELDS = ("stripe_subscription_id", "status", "cancel_at", "current_period_end",
                 "paid_through", "sub_created_at", "snapshot_at", "paid_at",
                 "grace_blocked")


def _read_record(conn: sqlite3.Connection, user_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT stripe_subscription_id, status, cancel_at, current_period_end, "
        "paid_through, sub_created_at, snapshot_at, paid_at, grace_blocked, updated_at "
        "FROM billing_subscriptions WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def _write_record(conn: sqlite3.Connection, user_id: int, state: dict) -> None:
    conn.execute("""
        INSERT INTO billing_subscriptions
            (user_id, stripe_subscription_id, status, cancel_at, current_period_end,
             paid_through, sub_created_at, snapshot_at, paid_at, grace_blocked,
             updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            stripe_subscription_id = excluded.stripe_subscription_id,
            status = excluded.status,
            cancel_at = excluded.cancel_at,
            current_period_end = excluded.current_period_end,
            paid_through = excluded.paid_through,
            sub_created_at = excluded.sub_created_at,
            snapshot_at = excluded.snapshot_at,
            paid_at = excluded.paid_at,
            grace_blocked = excluded.grace_blocked,
            updated_at = excluded.updated_at
    """, (user_id, *(state[name] for name in _STATE_FIELDS), _now_iso()))


def upsert_subscription(user_id: int, stripe_subscription_id: str, status: str, *,
                         cancel_at: Optional[str] = None,
                         current_period_end: Optional[str] = None,
                         paid_through=_UNSET, sub_created_at=_UNSET,
                         snapshot_at=_UNSET, paid_at=_UNSET, grace_blocked=_UNSET,
                         db: Optional[Path] = None) -> None:
    """Overwrite the locally-recorded subscription state for user_id -- the
    DIRECT write: an operator, a test fixture, or api/billing.py's POST
    /billing/cancel recording what the provider just answered. The Stripe
    webhook does NOT use this; it goes through mutate_subscription so its
    read-decide-write is one transaction (src.appstate.billing).

    `cancel_at` is Stripe's own "scheduled to cancel at period end"
    timestamp (ISO-8601 UTC string, already converted from Stripe's unix
    epoch by the caller) -- None whenever the caller carried none, which
    also means ON CONFLICT correctly clears a stale value once a
    subscription is no longer scheduled to cancel.

    `current_period_end` is the end of the period Stripe last announced:
    display only (see the module docstring). `paid_through` is the instant
    access runs to. Left unset it is taken from `current_period_end`, which
    is exactly what a direct caller who names an end means by it; a caller
    that must NOT hand out access (the cancel endpoint, which only learned
    of an announcement) passes the paid-through it already has, or None.

    The three ordering stamps are kept as stored when unset and the row is
    the same subscription (a direct write has no event time to compare, so
    it must not erase one), and cleared when the row switches to another.
    """
    with _connect(db) as conn:
        existing = _read_record(conn, user_id) or {}
        same = existing.get("stripe_subscription_id") == stripe_subscription_id

        def stamp(value, name):
            if value is not _UNSET:
                return value
            return existing.get(name) if same else None

        _write_record(conn, user_id, {
            "stripe_subscription_id": stripe_subscription_id, "status": status,
            "cancel_at": cancel_at, "current_period_end": current_period_end,
            "paid_through": current_period_end if paid_through is _UNSET else paid_through,
            "sub_created_at": stamp(sub_created_at, "sub_created_at"),
            "snapshot_at": stamp(snapshot_at, "snapshot_at"),
            "paid_at": stamp(paid_at, "paid_at"),
            "grace_blocked": stamp(grace_blocked, "grace_blocked")})


def mutate_subscription(user_id: int, decide: Callable[[Optional[dict]], Optional[dict]], *,
                         db: Optional[Path] = None) -> Optional[dict]:
    """Read user_id's subscription row, let `decide(record_or_None)` return
    the new state (a dict with every key of _STATE_FIELDS) or None for "no
    change", and write it -- all under one write lock (BEGIN IMMEDIATE), so
    two webhook deliveries for one customer cannot both read the old state
    and each write over the other. Stripe delivers concurrently and out of
    order; the ordering decisions in src.appstate.billing are only as good as
    the state they were made against.

    A decision equal to what is stored writes nothing: a duplicate delivery
    leaves the row, and its `updated_at`, exactly as it was. Returns the row
    as it stands afterwards (None if there is none)."""
    with _connect(db) as conn:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        record = _read_record(conn, user_id)
        state = decide(dict(record) if record else None)
        if state is not None and (
                record is None or any(record[name] != state[name] for name in _STATE_FIELDS)):
            _write_record(conn, user_id, state)
            record = _read_record(conn, user_id)
        return record


def get_subscription_record(user_id: int, *, db: Optional[Path] = None) -> Optional[dict]:
    """The last webhook-reported (or cancel-endpoint-updated) subscription
    state for user_id, or None if none has ever arrived. Returns a plain
    dict (not a billing.Subscription) since this is a narrower,
    storage-shaped read, not a provider-protocol call. `paid_through` is
    what access runs to; `current_period_end` is only what Stripe last
    announced."""
    with _connect(db) as conn:
        return _read_record(conn, user_id)


# The subscription statuses that mean "this customer is currently paying"
# -- Stripe's own vocabulary. A subscription SCHEDULED to cancel at period
# end is still "active" to Stripe (only `cancel_at_period_end` flips), which
# is exactly the state the cancellation policy has to keep serving.
PAID_STATUSES = frozenset({"active", "trialing"})

# A bounded grace past `paid_through` for exactly one state: a subscription
# still `active`/`trialing`, not scheduled to cancel, with no failed payment
# recorded -- i.e. a customer who is renewing. Stripe creates the renewal
# invoice AT the period boundary and finalizes and charges it about an hour
# later, so without this every renewing customer is refused from the boundary
# until `invoice.paid` arrives: an hour or more out of every paid month, with
# "your paid access ended" for someone whose card is about to be charged. Six
# hours is several times Stripe's hour (a retried first attempt still fits)
# and short enough that a renewal that is NEVER paid costs at most six hours.
# A scheduled cancel, past_due / unpaid / incomplete (recorded as `canceled`)
# and deleted subscriptions get none: for them the paid-through instant is the
# end. Owner decision, 2026-10-04: set this to 0 to have no grace at all.
RENEWAL_GRACE_SECONDS = 6 * 3600


def carry_grace_block(record: Optional[dict]) -> int:
    """The `grace_blocked` a row inherits when a NEW subscription replaces
    `record` and takes its paid-through with it: 1 unless the old row was
    itself renewing, so a deleted, failed or cancelling subscription's
    remainder does not pick up a renewal grace just because a new (not yet
    paid) subscription now carries it. Payment on the new subscription clears
    it (src.appstate.billing)."""
    if not record:
        return 0
    renewing = (record["status"] in PAID_STATUSES and not record["cancel_at"]
                and not record.get("grace_blocked"))
    return 0 if renewing else 1


def entitled_through(status: Optional[str], cancel_at: Optional[str],
                     paid_through: Optional[str],
                     grace_blocked: object = None) -> Optional[datetime]:
    """The last instant a subscription row entitles its customer to the paid
    surface: `paid_through`, plus RENEWAL_GRACE_SECONDS for a renewing
    customer (see above: paid status, no cancel scheduled, no failed payment
    or deletion applied since the last payment). None when nothing has been paid for (no
    `paid_through`). The ONE place the grace is applied; has_paid_access and
    the admin revenue view both read it, so they cannot disagree."""
    end = _parse_iso(paid_through)
    if end is None:
        return None
    if status in PAID_STATUSES and not cancel_at and not grace_blocked:
        end += timedelta(seconds=RENEWAL_GRACE_SECONDS)
    return end


def has_paid_access(user_id: int, now: Optional[datetime] = None, *,
                     db: Optional[Path] = None) -> bool:
    """Whether user_id is entitled to the PAID surface right now.

    THE POLICY, IN ONE FUNCTION: access runs to the PAID-THROUGH instant and
    to nothing else. `paid_through` is moved only by evidence -- a paid
    invoice's period end, a trial's `trial_end`, the first period of a new
    subscription (src.appstate.billing's module docstring has the full
    rules) -- so a period Stripe merely ANNOUNCED, a failed charge for the
    period it tried to bill, and the order events happen to arrive in can
    none of them grant or take away anything.

    The status string does not decide WHETHER access exists, on purpose, and
    that is the cancellation policy: cancelling stops renewal and does not
    revoke what was already paid for (a scheduled cancel is still "active"; a
    deleted or past-due subscription is "canceled"), so all of them keep
    access through `paid_through` and lose it after that instant unless a
    paid renewal arrives. The status only decides the grace below. A
    subscription that is "active" well past its paid-through instant with no
    payment on record has NOT been paid for, so it is not entitled: the old
    rule ("active with no cancel scheduled never expires") is what turned a
    period announcement into a free month.

    Callers that need "is this even a subscription customer?" ask
    get_subscription_record first: THIS function answers False for a user
    with no subscription row at all, which is the right answer for
    entitlement but NOT the right answer for gating -- invite-token beta
    users have no billing rows and must keep their access (see
    api/auth.py's require_paid_access).

    Purely a local-table read, never a live Stripe call: the same reason
    api/billing.py's GET /billing/status reads locally (it is hit on every
    page load, and Stripe's rate limits are real). The table is at most as
    fresh as the last verified webhook, which is an honest lag rather than
    a fabricated up-to-the-second answer.

    GRACE: a customer who is renewing (status active/trialing, no cancel
    scheduled, no failed payment recorded) keeps access for
    RENEWAL_GRACE_SECONDS past `paid_through`, to cover the hour Stripe waits
    before it charges a renewal. A scheduled cancel, a failed payment and a
    deleted subscription get none.

    No recorded `paid_through` is False, never a guess: absent data is
    absent, and guessing here would mean either serving an unpaid customer
    or cutting a paid one off early. `now` is injectable for deterministic
    tests, the same pattern src.appstate.users.authenticate uses for token
    expiry.
    """
    record = get_subscription_record(user_id, db=db)
    if record is None:
        return False
    end = entitled_through(record["status"], record.get("cancel_at"),
                           record.get("paid_through"), record.get("grace_blocked"))
    if end is None:
        return False
    return (now or datetime.now(timezone.utc)) <= end


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """An ISO-8601 UTC string from this module's own tables as an aware
    datetime, or None for anything absent/unparsable. Never raises: an
    unreadable timestamp must degrade to "unknown" (which has_paid_access
    treats as not-entitled for a canceled sub), not crash a request."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _scrub_if_expired(conn: sqlite3.Connection, stripe_session_id: str) -> None:
    """Treat an unretrieved activation-token row as expired once it has
    outlived users_store.DEFAULT_TOKEN_TTL -- the same TTL
    issue_invite_token uses for every other bearer token this app mints
    (src/appstate/users.py). Defensive review finding F5: without this, a
    paying user who never opens the success tab (or opens it long after
    paying) leaves a raw bearer token sitting in this table in the clear
    indefinitely -- this module's own docstring calls that table's
    raw-token window "temporary", which an unbounded wait does not honor.

    Marks the row exactly as a genuine retrieval would --
    `raw_token = NULL`, `retrieved_at` set -- so an expired row is
    indistinguishable from an already-used one to every caller (GET
    /signup/complete's own docstring already promises "already used" and
    "never happened" look the same from outside; "expired" folds into that
    same honest non-answer rather than adding a fourth, distinguishable
    case). `has_activation_token` stays True afterward, the same
    idempotency guarantee an actually-retrieved row gives against a
    redelivered webhook.

    Called at the top of has_activation_token/take_activation_token
    (never on its own), scoped to the ONE row being touched -- this table
    is small and read on exactly those two call sites, so a targeted
    UPDATE on the row already being queried costs nothing extra and needs
    no separate background sweep job. Deliberately leaves
    take_activation_token's own atomic claim UPDATE untouched (BOUNDARIES)
    -- this only ever runs BEFORE it, on a row that UPDATE has not yet
    seen.
    """
    row = conn.execute(
        "SELECT created_at FROM signup_activation_tokens WHERE "
        "stripe_session_id = ? AND raw_token IS NOT NULL AND retrieved_at IS NULL",
        (stripe_session_id,)).fetchone()
    if row is None:
        return
    try:
        created_at = datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError):
        # An unparsable created_at is not this function's problem to
        # raise on -- every row this module itself writes uses _now_iso(),
        # so this should never happen; if it somehow does, leaving the row
        # alone is the safe default, not a crash on a public-ish read path.
        return
    if datetime.now(timezone.utc) - created_at <= users_store.DEFAULT_TOKEN_TTL:
        return
    conn.execute(
        "UPDATE signup_activation_tokens SET raw_token = NULL, retrieved_at = ? "
        "WHERE stripe_session_id = ?",
        (_now_iso(), stripe_session_id))


def has_activation_token(stripe_session_id: str, *, db: Optional[Path] = None) -> bool:
    """Whether a signup activation token has EVER been minted for this
    Stripe checkout session -- the idempotency gate
    src.appstate.billing.apply_stripe_webhook_event checks before minting
    one, so a retried webhook delivery (Stripe does not guarantee
    exactly-once) never mints a second bearer token for the same signup.

    Stays True even after take_activation_token has already retrieved (and
    wiped) the raw token -- the row itself is kept forever specifically so
    this check keeps working after retrieval; only the raw secret is ever
    erased. Without that, a webhook redelivered after the browser already
    fetched its token would look exactly like a fresh signup and mint (and
    silently invalidate the already-issued) a second one.
    """
    with _connect(db) as conn:
        _scrub_if_expired(conn, stripe_session_id)
        _wipe_stale_rereads(conn)
        row = conn.execute(
            "SELECT 1 FROM signup_activation_tokens WHERE stripe_session_id = ?",
            (stripe_session_id,)).fetchone()
        return row is not None


def record_activation_token(stripe_session_id: str, user_id: int, raw_token: str, *,
                             db: Optional[Path] = None) -> None:
    """Store the RAW token minted for stripe_session_id -- see this
    module's docstring for why this table (uniquely, and only until
    take_activation_token's first successful call) holds one unhashed.
    ON CONFLICT DO NOTHING: a caller should already have checked
    has_activation_token first, but a duplicate INSERT (e.g. a race
    between two webhook deliveries) must never overwrite an
    already-recorded token with a second, different one that would
    silently invalidate whichever token a browser is about to fetch."""
    with _connect(db) as conn:
        conn.execute("""
            INSERT INTO signup_activation_tokens
                (stripe_session_id, user_id, raw_token, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stripe_session_id) DO NOTHING
        """, (stripe_session_id, user_id, raw_token, _now_iso()))


# HOW LONG A SESSION ID KEEPS WORKING AFTER THE FIRST SUCCESSFUL READ.
#
# The success page polls GET /signup/complete (the webhook that mints the
# token can land after the browser does), and a buyer who reloads the page, or
# whose first response was lost on a mobile connection, makes a second read
# for the same session id. With a strictly one-shot token that second read
# was a 404 and a paying customer was locked out of what they had just paid
# for, with no email and no recovery path to fall back on.
#
# So the raw token is kept for this long after the FIRST read and then wiped
# for good. The property the one-shot design protected is preserved in the
# part that matters: a session id seen in a browser URL, a history file or a
# log is useless to anyone who finds it later than this. Inside the window
# the session id is as good as the token itself, which is why the window is
# short.
ACTIVATION_REREAD_WINDOW = timedelta(minutes=10)


# HOW LONG AN UNREAD RAW TOKEN MAY SIT IN THE TABLE.
#
# A buyer who pays but never opens the completion page leaves the 366-day
# subscriber token in cleartext here. _scrub_if_expired only ever looks at the
# one session id being asked about, so on its own an unread row could wait for
# its 14-day invite TTL (or forever, if nobody asks). 72 hours is long enough
# to cover a buyer who pays on a phone and opens the page on a laptop over a
# weekend, and short enough that the table is not a standing vault of live
# logins. Wiping the raw value costs the SUBSCRIPTION nothing: the hashed token
# in `tokens` is untouched, so anyone who did read theirs keeps working access
# and paid access is decided from the subscription row, not from this table.
# An unread token is simply no longer recoverable from here (support re-mints
# one: POST /admin/users/token).
UNREAD_ACTIVATION_TTL = timedelta(hours=72)


def _wipe_stale_rereads(conn: sqlite3.Connection) -> None:
    """Erase every raw token that has no business still being here:

      * a READ token whose re-read window (ACTIVATION_REREAD_WINDOW) closed,
      * an UNREAD token older than UNREAD_ACTIVATION_TTL.

    Runs on every token read and on every webhook idempotency check, so no
    token sits in the table in the clear waiting for someone to ask for it;
    no background sweep exists to rely on.

    The unread case stamps `retrieved_at` the way _scrub_if_expired does, for
    the same reason: a row with no raw token and no retrieved_at would let the
    atomic claim in take_activation_token "win" and hand back a None token.
    Stamped, an expired row is indistinguishable from a used one."""
    now = datetime.now(timezone.utc)
    cutoff = (now - ACTIVATION_REREAD_WINDOW).isoformat()
    conn.execute(
        "UPDATE signup_activation_tokens SET raw_token = NULL "
        "WHERE raw_token IS NOT NULL AND retrieved_at IS NOT NULL "
        "AND retrieved_at < ?", (cutoff,))
    unread_cutoff = (now - UNREAD_ACTIVATION_TTL).isoformat()
    conn.execute(
        "UPDATE signup_activation_tokens SET raw_token = NULL, retrieved_at = ? "
        "WHERE raw_token IS NOT NULL AND retrieved_at IS NULL "
        "AND created_at < ?", (now.isoformat(), unread_cutoff))


def take_activation_token(stripe_session_id: str, *,
                           reread_window: Optional[timedelta] = None,
                           db: Optional[Path] = None) -> Optional[dict]:
    """Retrieve the signup token: {"user_id", "raw_token"}, or None.

    `reread_window` is how long after the FIRST successful read the same
    session id may read the token again. The default (None / zero) is the
    original strict one-time behaviour -- the first call returns the token
    and wipes it, every later call is None. GET /signup/complete passes
    ACTIVATION_REREAD_WINDOW so its polling page and a reload both work; see
    that constant for why. After the window the raw token is wiped and the
    session id is dead, exactly as under the strict rule.

    None for a session that never completed payment (no row was ever
    inserted), for one already past its window, and for one whose token
    expired unread -- the same shape every time, so GET /signup/complete can
    never distinguish "already used" from "never happened" for an outside
    caller, which is the honest, safe answer for an endpoint reachable with
    nothing but a session id from a URL.

    Deliberately keeps the ROW (unlike a delete) after wiping the secret --
    see has_activation_token's docstring for why the row's continued
    existence is load-bearing for webhook-redelivery idempotency, not just
    an incidental audit trail.

    ATOMIC CLAIM, NOT SELECT-THEN-UPDATE: the FIRST retrieval is a single
    guarded UPDATE (WHERE retrieved_at IS NULL) so that two concurrent calls
    for the same session id -- a double-click, or an attacker racing the
    legitimate browser for a session id visible in the success-page URL --
    can never both be treated as "the first". Only the ONE caller whose
    UPDATE matches the still-unretrieved row wins the claim; the window then
    bounds how long the others (and the buyer's own retries) may keep
    reading. `retrieved_at` is stamped once, by the winner, and is what the
    window is measured from, so re-reads never extend it.
    """
    window = reread_window if reread_window is not None else timedelta(0)
    if window > ACTIVATION_REREAD_WINDOW:
        window = ACTIVATION_REREAD_WINDOW
    with _connect(db) as conn:
        _scrub_if_expired(conn, stripe_session_id)
        _wipe_stale_rereads(conn)
        row = conn.execute(
            "UPDATE signup_activation_tokens SET retrieved_at = ? "
            "WHERE stripe_session_id = ? AND retrieved_at IS NULL "
            "RETURNING user_id, raw_token",
            (_now_iso(), stripe_session_id)).fetchone()
        if row is not None:
            if window <= timedelta(0):
                # Strict one-time: wipe the secret in the same transaction
                # as the claim.
                conn.execute(
                    "UPDATE signup_activation_tokens SET raw_token = NULL "
                    "WHERE stripe_session_id = ?", (stripe_session_id,))
            return {"user_id": row["user_id"], "raw_token": row["raw_token"]}
        if window <= timedelta(0):
            return None
        prior = conn.execute(
            "SELECT user_id, raw_token, retrieved_at FROM signup_activation_tokens "
            "WHERE stripe_session_id = ?", (stripe_session_id,)).fetchone()
        if prior is None or prior["raw_token"] is None:
            return None
        retrieved_at = _parse_iso(prior["retrieved_at"])
        if retrieved_at is None or datetime.now(timezone.utc) - retrieved_at > window:
            conn.execute(
                "UPDATE signup_activation_tokens SET raw_token = NULL "
                "WHERE stripe_session_id = ?", (stripe_session_id,))
            return None
        return {"user_id": prior["user_id"], "raw_token": prior["raw_token"]}


# -- first-touch attribution -------------------------------------------------

ATTRIBUTION_COLUMNS = ("utm_source", "utm_medium", "utm_campaign",
                       "utm_content", "utm_term", "referrer_host", "anon_id")


def record_signup_attribution(user_id: int, attribution: Mapping, *,
                               db: Optional[Path] = None) -> bool:
    """Store how this user first arrived. FIRST TOUCH WINS: a user who signs
    up again (or a pending signup retried from another campaign link) keeps
    the row they already have, so one person is never credited to two
    sources. Returns True only when a row was written. An empty mapping
    writes nothing -- a direct visit is the absence of a row, not a row of
    blanks, which is what lets 'signups by source' call it "(direct)"."""
    values = {col: (attribution or {}).get(col) for col in ATTRIBUTION_COLUMNS}
    if not any(values.values()):
        return False
    with _connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO signup_attribution (user_id, utm_source, utm_medium, "
            "utm_campaign, utm_content, utm_term, referrer_host, anon_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id, *[values[c] for c in ATTRIBUTION_COLUMNS], _now_iso()))
        return cur.rowcount > 0


def get_signup_attribution(user_id: int, *, db: Optional[Path] = None) -> Dict[str, str]:
    """The user's first-touch attribution, only the keys that have a value
    ({} when none) -- the shape that rides on events and Stripe metadata."""
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM signup_attribution WHERE user_id = ?",
            (user_id,)).fetchone()
    if row is None:
        return {}
    return {col: row[col] for col in ATTRIBUTION_COLUMNS if row[col]}


def all_signup_attribution(*, db: Optional[Path] = None) -> Dict[int, Dict[str, str]]:
    """user_id -> attribution, for the admin revenue report."""
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM signup_attribution").fetchall()
    return {r["user_id"]: {c: r[c] for c in ATTRIBUTION_COLUMNS if r[c]}
            for r in rows}


def list_subscription_rows(*, db: Optional[Path] = None) -> List[dict]:
    """Every subscription this app has seen a verified webhook for -- the
    admin revenue report's one read. Small table, plain SELECT."""
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT user_id, status, cancel_at, current_period_end, paid_through, "
            "grace_blocked "
            "FROM billing_subscriptions ORDER BY user_id").fetchall()
    return [dict(r) for r in rows]


def get_or_create_idempotency_key(user_id: int, plan_id: str,
                                   generator: Callable[[], str], *,
                                   db: Optional[Path] = None) -> str:
    """Return the Idempotency-Key stored for (user_id, plan_id) if a prior
    checkout attempt already recorded one; otherwise mint one via
    `generator()` and store it before returning it. This is what makes a
    client's retried checkout call for the same plan resume the same
    Stripe attempt instead of Stripe seeing an unrelated new one each
    time -- the exact gap flagged in StripeBillingProvider's docstring.

    `generator` is injected (rather than this module minting its own
    uuid4) so callers control the key's shape/prefix; billing.py's
    default generator matches the one it used before this table existed,
    so behavior for a first attempt is unchanged.
    """
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT idempotency_key FROM billing_checkout_idempotency "
            "WHERE user_id = ? AND plan_id = ?",
            (user_id, plan_id)).fetchone()
        if row:
            return row["idempotency_key"]
        key = generator()
        conn.execute("""
            INSERT INTO billing_checkout_idempotency
                (user_id, plan_id, idempotency_key, created_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, plan_id, key, _now_iso()))
        return key
