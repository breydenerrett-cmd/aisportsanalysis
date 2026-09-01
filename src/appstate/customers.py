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
billing_subscriptions(user_id PK, stripe_subscription_id, status, updated_at)
    The last subscription status this app has SEEN via a *verified*
    webhook (src.appstate.billing.apply_stripe_webhook_event) -- never a
    live Stripe API call. This is what lets api/billing.py's GET
    /billing/status answer instantly from local state instead of calling
    out to Stripe on every page load.
billing_checkout_idempotency(user_id, plan_id PK, idempotency_key, created_at)
    Keyed on (user_id, plan_id): a client retrying a failed/timed-out
    checkout attempt for the same plan reuses the same Idempotency-Key
    instead of Stripe treating the retry as a brand-new attempt.

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS billing_checkout_idempotency (
            user_id INTEGER NOT NULL,
            plan_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, plan_id)
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
                         db: Optional[Path] = None) -> None:
    """Overwrite the locally-recorded subscription state for user_id.
    Called only from a verified webhook event -- see
    src.appstate.billing.apply_stripe_webhook_event -- never speculatively,
    since this table is the only thing GET /billing/status reads."""
    with _connect(db) as conn:
        conn.execute("""
            INSERT INTO billing_subscriptions (user_id, stripe_subscription_id, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                stripe_subscription_id = excluded.stripe_subscription_id,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, (user_id, stripe_subscription_id, status, _now_iso()))


def get_subscription_record(user_id: int, *, db: Optional[Path] = None) -> Optional[dict]:
    """The last webhook-reported subscription state for user_id, or None
    if none has ever arrived. Returns a plain dict (not a
    billing.Subscription) since this is a narrower, storage-shaped read,
    not a provider-protocol call."""
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT stripe_subscription_id, status, updated_at "
            "FROM billing_subscriptions WHERE user_id = ?",
            (user_id,)).fetchone()
        if not row:
            return None
        return {"stripe_subscription_id": row["stripe_subscription_id"],
                "status": row["status"], "updated_at": row["updated_at"]}


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
