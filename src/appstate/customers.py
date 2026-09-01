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
                      current_period_end, updated_at)
    The last subscription status this app has SEEN via a *verified*
    webhook (src.appstate.billing.apply_stripe_webhook_event) -- never a
    live Stripe API call. This is what lets api/billing.py's GET
    /billing/status answer instantly from local state instead of calling
    out to Stripe on every page load, and what has_paid_access() decides
    entitlement from (`current_period_end` is the paid-through timestamp
    the cancellation policy turns on).
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
    is why it exists for exactly one read: take_activation_token() deletes
    the row it returns, so a session id (visible in the browser's own
    success-page URL) is good for exactly one retrieval, never a replay.
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
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

from src.appstate import users as users_store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


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
    # added to the table that is already there, guarded by PRAGMA
    # table_info so re-running this on a db that already has it doesn't
    # raise OperationalError.
    existing_sub_cols = {row["name"] for row in
                        conn.execute("PRAGMA table_info(billing_subscriptions)")}
    if "cancel_at" not in existing_sub_cols:
        conn.execute("ALTER TABLE billing_subscriptions ADD COLUMN cancel_at TEXT")
    if "current_period_end" not in existing_sub_cols:
        # Added for the cancellation policy (docs/LAUNCH_DECISIONS.md: cancel
        # stops renewal, paid access runs to the end of the period already
        # paid for). Without this column there is no honest way to answer
        # "is this canceled customer still entitled?" without a live Stripe
        # call on every request -- see has_paid_access below.
        conn.execute("ALTER TABLE billing_subscriptions ADD COLUMN current_period_end TEXT")
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


def upsert_subscription(user_id: int, stripe_subscription_id: str, status: str, *,
                         cancel_at: Optional[str] = None,
                         current_period_end: Optional[str] = None,
                         db: Optional[Path] = None) -> None:
    """Overwrite the locally-recorded subscription state for user_id.
    Called only from a verified webhook event -- see
    src.appstate.billing.apply_stripe_webhook_event -- or from
    api/billing.py's POST /billing/cancel proactively updating local state
    right after a successful provider.cancel() call, rather than waiting on
    Stripe's own (not guaranteed-immediate, especially in test mode)
    `customer.subscription.deleted` webhook -- never speculatively beyond
    those two call sites, since this table is the only thing GET
    /billing/status reads.

    `cancel_at` is Stripe's own "scheduled to cancel at period end"
    timestamp (ISO-8601 UTC string, already converted from Stripe's unix
    epoch by the caller) -- None whenever the webhook/cancel call carried
    none, which also means ON CONFLICT correctly clears a stale value once
    a subscription is no longer scheduled to cancel.

    `current_period_end` is Stripe's end of the period the customer has
    ALREADY PAID FOR -- the single fact the cancellation policy turns on
    (cancel stops renewal; access runs to that timestamp). Same
    ISO-8601-or-None contract as `cancel_at`, and the same
    clear-on-None ON CONFLICT behavior: a caller that does not know the
    period end must not leave a stale one behind pretending it does.
    Callers that merely re-confirm an existing subscription (a redelivered
    checkout.session.completed) pass the value they already have on record
    rather than None -- see src.appstate.billing.apply_stripe_webhook_event.
    """
    with _connect(db) as conn:
        conn.execute("""
            INSERT INTO billing_subscriptions
                (user_id, stripe_subscription_id, status, cancel_at,
                 current_period_end, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                stripe_subscription_id = excluded.stripe_subscription_id,
                status = excluded.status,
                cancel_at = excluded.cancel_at,
                current_period_end = excluded.current_period_end,
                updated_at = excluded.updated_at
        """, (user_id, stripe_subscription_id, status, cancel_at,
              current_period_end, _now_iso()))


def get_subscription_record(user_id: int, *, db: Optional[Path] = None) -> Optional[dict]:
    """The last webhook-reported (or cancel-endpoint-updated) subscription
    state for user_id, or None if none has ever arrived. Returns a plain
    dict (not a billing.Subscription) since this is a narrower,
    storage-shaped read, not a provider-protocol call."""
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT stripe_subscription_id, status, cancel_at, "
            "current_period_end, updated_at "
            "FROM billing_subscriptions WHERE user_id = ?",
            (user_id,)).fetchone()
        if not row:
            return None
        return {"stripe_subscription_id": row["stripe_subscription_id"],
                "status": row["status"], "cancel_at": row["cancel_at"],
                "current_period_end": row["current_period_end"],
                "updated_at": row["updated_at"]}


# The subscription statuses that mean "this customer is currently paying"
# -- Stripe's own vocabulary. A subscription SCHEDULED to cancel at period
# end is still "active" to Stripe (only `cancel_at_period_end` flips), which
# is exactly the state the cancellation policy has to keep serving.
PAID_STATUSES = frozenset({"active", "trialing"})


def has_paid_access(user_id: int, now: Optional[datetime] = None, *,
                     db: Optional[Path] = None) -> bool:
    """Whether user_id is entitled to the PAID surface right now.

    THE POLICY, IN ONE FUNCTION (docs/LAUNCH_DECISIONS.md, LINEHOUND paid
    beta): cancelling stops renewal, it does not revoke what was already
    paid for. So a customer keeps access through `current_period_end` and
    loses it after that timestamp unless they reactivate before it.

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

    A canceled subscription with NO recorded `current_period_end` is False,
    never a guess: absent data is absent, and guessing here would mean
    either serving a lapsed customer forever or cutting a paid one off
    early. `now` is injectable for deterministic tests, the same pattern
    src.appstate.users.authenticate uses for token expiry.
    """
    record = get_subscription_record(user_id, db=db)
    if record is None:
        return False
    now = now or datetime.now(timezone.utc)
    period_end = _parse_iso(record.get("current_period_end"))
    if record["status"] in PAID_STATUSES:
        # Scheduled-cancel case: Stripe still says "active", so the only
        # thing that can end entitlement is the period end actually passing
        # before the `customer.subscription.deleted` webhook lands. With no
        # cancellation scheduled there is nothing to expire.
        if record.get("cancel_at") and period_end is not None and now > period_end:
            return False
        return True
    return period_end is not None and now <= period_end


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


def take_activation_token(stripe_session_id: str, *,
                           db: Optional[Path] = None) -> Optional[dict]:
    """One-time retrieval: returns {"user_id", "raw_token"} and WIPES the
    raw_token column (setting retrieved_at) on the one call that finds an
    unretrieved row; None on every call after (already retrieved), and
    None for a session that never completed payment (no row was ever
    inserted) -- the same shape either way, so GET /signup/complete can
    never distinguish "already used" from "never happened" for an outside
    caller, which is the honest, safe answer for an endpoint reachable
    with nothing but a session id from a URL.

    Deliberately keeps the ROW (unlike a delete) after wiping the secret --
    see has_activation_token's docstring for why the row's continued
    existence is load-bearing for webhook-redelivery idempotency, not just
    an incidental audit trail.

    ATOMIC CLAIM, NOT SELECT-THEN-UPDATE: the retrieval is a single guarded
    UPDATE (WHERE retrieved_at IS NULL) so that two concurrent
    GET /signup/complete calls for the same session id -- a double-click, or
    an attacker racing the legitimate browser for a session id visible in
    the success-page URL -- can never both come away with the raw token.
    A prior SELECT-then-UPDATE let both callers read an unretrieved row
    before either wrote the retrieved_at marker, handing the same one-time
    bearer token out twice. Only the ONE caller whose UPDATE actually
    matches the still-unretrieved row (RETURNING gives it the token before
    the follow-up wipe) gets a result; every racing caller matches zero
    rows and gets None, the same as a replay.
    """
    with _connect(db) as conn:
        # F5's TTL scrub runs first, on this same row -- if it fires (row
        # older than users_store.DEFAULT_TOKEN_TTL and never retrieved), it
        # sets retrieved_at itself, so the claim UPDATE just below finds no
        # unretrieved row to match and this function returns None, same as
        # any other already-used session id. See _scrub_if_expired's
        # docstring.
        _scrub_if_expired(conn, stripe_session_id)
        # Claim the row first (sets retrieved_at, still holding raw_token so
        # RETURNING can hand it back). The WHERE guard is the whole race
        # defense: at most one connection's UPDATE can match the
        # retrieved_at IS NULL row, since the write lock serializes them and
        # the loser re-reads a now-non-NULL retrieved_at.
        row = conn.execute(
            "UPDATE signup_activation_tokens SET retrieved_at = ? "
            "WHERE stripe_session_id = ? AND retrieved_at IS NULL "
            "RETURNING user_id, raw_token",
            (_now_iso(), stripe_session_id)).fetchone()
        if row is None:
            return None
        # Won the claim -- now wipe the raw secret (kept out of the claim
        # UPDATE only so RETURNING above could carry it back). Same
        # connection/transaction, so the wipe commits atomically with the
        # claim.
        conn.execute(
            "UPDATE signup_activation_tokens SET raw_token = NULL "
            "WHERE stripe_session_id = ?", (stripe_session_id,))
        return {"user_id": row["user_id"], "raw_token": row["raw_token"]}


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
