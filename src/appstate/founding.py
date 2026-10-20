"""Founding-member seats: a real, webhook-maintained counter with a hard cap.

OWNER DECISION 2026-10-20: the first FOUNDING_SEAT_CAP (50) members pay the founding price
($14.99/mo) and keep it for as long as they stay subscribed; everyone after pays the standard
price ($19.99/mo). Nothing about the price depends on results, a clock or a count of anything but
seats. docs/marketing/GROWTH_PLAYBOOK.md section 3.2: "the founding cap is a real database counter
enforced at checkout; there is no clock". This module is that counter.

WHAT A SEAT IS
--------------
One row per user in `founding_seats` (same app.db as every other billing table, additive,
`CREATE TABLE IF NOT EXISTS`):

  state `active`   the user holds an ACTIVE or TRIALING founding subscription, as the verified
                   Stripe webhooks last reported it. THIS is a taken seat, and the only thing the
                   public number counts. A seat that is not backed by a live subscription is not
                   counted, so the number on the pricing page can never be padded.
  state `pending`  the user opened a founding Checkout and has not paid yet. It RESERVES a seat
                   (so seat 50 cannot be sold twice to two people who are both mid-checkout) until
                   `holds_until`, and then stops counting on its own; nothing has to clean it up.
  state `ended`    the founding subscription finished (cancelled, unpaid, deleted). The seat is
                   free again for anyone, including the person who held it.

THE RESERVATION WINDOW. RESERVATION_MINUTES (30) is the owner's number and Stripe's minimum Checkout
Session lifetime. The session is created with `expires_at` = the instant the reservation lapses
(plus SESSION_SLACK_SECONDS, because Stripe refuses an `expires_at` closer than 30 minutes to the
moment it receives the request, so the request is made for 30 minutes and a minute), so a session
that can still be PAID always still holds a reservation: nobody can pay for seat 50 after losing it.
`checkout.session.expired` releases the reservation early; without that event it simply times out.

RACE AT SEAT 50. `try_reserve` counts and inserts inside one BEGIN IMMEDIATE transaction (the same
write lock the rest of customers.py relies on), so two simultaneous checkouts cannot both read
"49 taken, none held" and both take the last seat; the second one reads the first one's pending
row and is sent to the standard price instead.

"LOCKED FOR LIFE" MEANS CONTINUOUSLY SUBSCRIBED. The price is a property of the Stripe subscription,
so it stays exactly as long as that subscription does: renewals, a failed card that is fixed in
time, and cancelling then reactivating before the period ends (same subscription) all keep it. Once
the subscription has actually ENDED the seat is released, and coming back later is a new purchase:
that person gets the founding price only if a seat is free then, like anyone else, and the standard
price otherwise. This is the only reading under which the cap is true (a former member who kept a
claim on seat 31 forever would make "50 seats" mean "50 seats plus everyone who ever left") and it
is what the pricing copy says.

WHAT THE WEBHOOK DOES. `record_subscription` is called from src.appstate.billing's webhook handler
for every customer.subscription.* event that is for a founding subscription (the founding Price id,
or the `plan_tier=founding` metadata our own Checkout stamps on it), and `record_checkout_paid` for
the matching checkout.session.completed. Stripe does not order events, so a status change older than
the one stored (by the event's own `created`) changes nothing, and an event for a subscription other
than the one on the seat can only move the seat if it is live and newer.

NOT A GATE. This module decides which PRICE a checkout is offered. What a paying customer may then
USE is src.appstate.customers.has_paid_access, exactly as before; a founding member and a standard
member are the same to every access check.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from src.appstate import customers

FOUNDING_SEAT_CAP = 50
RESERVATION_MINUTES = 30
RESERVATION_SECONDS = RESERVATION_MINUTES * 60
SESSION_SLACK_SECONDS = 60

STATE_PENDING = "pending"
STATE_ACTIVE = "active"
STATE_ENDED = "ended"

_LIVE_STATUSES = frozenset({"active", "trialing"})

_TABLE = """
    CREATE TABLE IF NOT EXISTS founding_seats (
        user_id INTEGER PRIMARY KEY,
        state TEXT NOT NULL,
        reserved_at INTEGER,
        holds_until INTEGER,
        stripe_subscription_id TEXT,
        status_at INTEGER,
        updated_at INTEGER NOT NULL
    )
"""


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator:
    with customers._connect(db) as conn:
        conn.execute(_TABLE)
        yield conn


def _now(now: Optional[int]) -> int:
    return int(time.time()) if now is None else int(now)


def _row(conn, user_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM founding_seats WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def _counts(conn, now: int, *, excluding_user: Optional[int] = None) -> tuple:
    taken = conn.execute("SELECT COUNT(*) FROM founding_seats WHERE state = ?",
                         (STATE_ACTIVE,)).fetchone()[0]
    held = conn.execute(
        "SELECT COUNT(*) FROM founding_seats WHERE state = ? AND holds_until > ? "
        "AND user_id != ?", (STATE_PENDING, now, -1 if excluding_user is None else excluding_user)
    ).fetchone()[0]
    return taken, held


def seat_counts(*, now: Optional[int] = None, db: Optional[Path] = None) -> dict:
    """{"taken": n, "reserved": m}: `taken` is seats backed by a live founding subscription (the number
    shown to the public), `reserved` is checkouts in progress that currently hold a seat (never
    shown as taken)."""
    when = _now(now)
    with _connect(db) as conn:
        taken, held = _counts(conn, when)
    return {"taken": taken, "reserved": held}


@dataclass(frozen=True)
class Reservation:
    user_id: int
    reserved_at: int
    holds_until: int
    already_member: bool = False

    @property
    def session_expires_at(self) -> int:
        """The `expires_at` to give Stripe for the Checkout Session this reservation backs."""
        return self.holds_until


def try_reserve(user_id: int, *, cap: int = FOUNDING_SEAT_CAP, now: Optional[int] = None,
                db: Optional[Path] = None) -> Optional[Reservation]:
    """Reserve a founding seat for `user_id`'s checkout, or None when every seat is taken or held.

    Idempotent for a live reservation: a second call while the first is still held returns the SAME
    reservation (same instants), so a double click opens the same Stripe session instead of
    reserving two seats. A user who already holds an ACTIVE seat is returned as `already_member`
    without changing anything."""
    when = _now(now)
    with _connect(db) as conn:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        existing = _row(conn, user_id)
        if existing and existing["state"] == STATE_ACTIVE:
            return Reservation(user_id, existing["reserved_at"] or when, existing["holds_until"] or when,
                               already_member=True)
        if existing and existing["state"] == STATE_PENDING and (existing["holds_until"] or 0) > when:
            return Reservation(user_id, existing["reserved_at"], existing["holds_until"])
        taken, held = _counts(conn, when, excluding_user=user_id)
        if taken + held >= cap:
            return None
        holds_until = when + RESERVATION_SECONDS + SESSION_SLACK_SECONDS
        conn.execute("""
            INSERT INTO founding_seats (user_id, state, reserved_at, holds_until, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state = excluded.state, reserved_at = excluded.reserved_at,
                holds_until = excluded.holds_until, updated_at = excluded.updated_at
        """, (user_id, STATE_PENDING, when, holds_until, when))
        return Reservation(user_id, when, holds_until)


def release_reservation(user_id: int, *, now: Optional[int] = None, db: Optional[Path] = None) -> None:
    """Give back a PENDING reservation now (the checkout never opened, or Stripe said the session
    expired). An active seat is never touched."""
    when = _now(now)
    with _connect(db) as conn:
        conn.execute("UPDATE founding_seats SET holds_until = ?, updated_at = ? "
                     "WHERE user_id = ? AND state = ?", (when, when, user_id, STATE_PENDING))


def _not_older(at: Optional[int], stamp: Optional[int]) -> bool:
    return at is None or stamp is None or at >= stamp


def record_subscription(user_id: int, subscription_id: str, status: str, at: Optional[int], *,
                        now: Optional[int] = None, db: Optional[Path] = None) -> None:
    """Apply one founding subscription event (`status` is the app's normalized word: `active`,
    `trialing`, or anything else for "not paying"). See the module docstring for the ordering rules."""
    when = _now(now)
    live = status in _LIVE_STATUSES
    with _connect(db) as conn:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn, user_id)
        if row is None:
            conn.execute(
                "INSERT INTO founding_seats (user_id, state, stripe_subscription_id, status_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, STATE_ACTIVE if live else STATE_ENDED, subscription_id, at, when))
            return
        same = row["stripe_subscription_id"] == subscription_id
        if not _not_older(at, row["status_at"]):
            return
        if not same and not live:
            return              # a dead event for some other subscription says nothing about this seat
        state = STATE_ACTIVE if live else STATE_ENDED
        conn.execute(
            "UPDATE founding_seats SET state = ?, stripe_subscription_id = ?, status_at = ?, "
            "holds_until = ?, updated_at = ? WHERE user_id = ?",
            (state, subscription_id, at if at is not None else row["status_at"],
             row["holds_until"] if state != STATE_ACTIVE else None, when, user_id))


def record_checkout_paid(user_id: int, subscription_id: Optional[str], at: Optional[int], *,
                         now: Optional[int] = None, db: Optional[Path] = None) -> None:
    """A founding Checkout Session completed with its first payment settled (or a trial started):
    the seat is taken. The subscription event that follows confirms it; this makes the seat real
    the moment the buyer has paid even if that event is late."""
    if subscription_id:
        record_subscription(user_id, subscription_id, "active", at, now=now, db=db)


def active_user_ids(*, db: Optional[Path] = None) -> List[int]:
    with _connect(db) as conn:
        return [r[0] for r in conn.execute(
            "SELECT user_id FROM founding_seats WHERE state = ? ORDER BY user_id", (STATE_ACTIVE,))]


def is_member(user_id: int, *, db: Optional[Path] = None) -> bool:
    with _connect(db) as conn:
        row = _row(conn, user_id)
    return bool(row and row["state"] == STATE_ACTIVE)
