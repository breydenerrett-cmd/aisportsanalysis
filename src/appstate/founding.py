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
                   `holds_until` plus HOLD_GRACE_SECONDS, and then stops counting on its own;
                   nothing has to clean it up.
  state `ended`    the founding subscription finished (cancelled, unpaid, deleted), or a pending
                   hold was given back. The seat is free again for anyone, including the person
                   who held it.

THE RESERVATION WINDOW. RESERVATION_MINUTES (30) is the owner's number and Stripe's minimum Checkout
Session lifetime. The session is created with `expires_at` = the instant the reservation lapses
(plus SESSION_SLACK_SECONDS, because Stripe refuses an `expires_at` closer than 30 minutes to the
moment it receives the request, so the request is made for 30 minutes and a minute), so a session
that can still be PAID always still holds a reservation: nobody can pay for seat 50 after losing it.
`checkout.session.expired` releases the reservation early; without that event it simply times out.

THE GRACE AFTER THE WINDOW. A buyer who pays in the last seconds of the session gets their seat from
a WEBHOOK that can land minutes later (Stripe retries for days). Without a tail, the hold lapsed at
`holds_until`, a second buyer was offered the same seat in the gap, and both paid: 51 taken. So a
pending hold keeps COUNTING for HOLD_GRACE_SECONDS (15 minutes) after `holds_until`, which is far
longer than a healthy webhook takes. It is only the count that is extended: a new click after
`holds_until` still opens a new session, because the old one can no longer be paid. A webhook that is
later than the grace still makes the seat real (it can only take a seat, never be refused), so the
cap is a promise about the checkout, not about a webhook outage.

WHICH RESERVATION A RELEASE MEANS. A reservation is identified by its `reserved_at`, strictly
increasing per user, which is also stamped on the Checkout Session's metadata and baked into its
Idempotency-Key (so one reservation is exactly one Stripe session). Every release names that
reference: a late `checkout.session.expired` for an OLD session must not free the NEW session's seat,
and a failed request must give back only a hold it created itself, never one a double click or a
concurrent request is still using.

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

WHAT ENDS A SEAT. Only a subscription that is really over: `canceled` (which is also what a deleted
subscription reports), `unpaid` and `incomplete_expired`. `past_due` does NOT: it is a card that
failed while Stripe is still retrying, the same subscription (and so the same locked price) comes
back the moment the card is fixed, and freeing the seat there sold it to someone else while the
member was still entitled to take it back (51 taken, reproduced). `past_due`, `incomplete` and
`paused` (and any status we do not know) therefore change nothing at all, neither taking nor freeing
a seat; the entitlement side (src.appstate.customers.has_paid_access) is a separate decision and is
untouched by this. The statuses reach this module RAW, not through billing's
_normalize_subscription_status, which folds past_due into `canceled` for entitlement and would end
the seat.

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
# How long a pending hold keeps counting after its session can no longer be paid: the webhook for a
# payment made in the window's last seconds lands after it (see THE GRACE AFTER THE WINDOW above).
HOLD_GRACE_SECONDS = 15 * 60

STATE_PENDING = "pending"
STATE_ACTIVE = "active"
STATE_ENDED = "ended"

# Raw Stripe subscription statuses, by what they say about a SEAT. Anything in neither set (past_due,
# incomplete, paused, a status Stripe adds later) changes nothing: see WHAT ENDS A SEAT above.
_LIVE_STATUSES = frozenset({"active", "trialing"})
_ENDING_STATUSES = frozenset({"canceled", "unpaid", "incomplete_expired"})

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
    # A hold counts until HOLD_GRACE_SECONDS after its session could last be paid.
    held = conn.execute(
        "SELECT COUNT(*) FROM founding_seats WHERE state = ? AND holds_until + ? > ? "
        "AND user_id != ?",
        (STATE_PENDING, HOLD_GRACE_SECONDS, now, -1 if excluding_user is None else excluding_user)
    ).fetchone()[0]
    return taken, held


def seat_counts(*, now: Optional[int] = None, db: Optional[Path] = None) -> dict:
    """{"taken": n, "reserved": m}: `taken` is seats backed by a live founding subscription (the number
    shown to the public), `reserved` is checkouts in progress that currently hold a seat, including
    the HOLD_GRACE_SECONDS after their session ended (never shown as taken)."""
    when = _now(now)
    with _connect(db) as conn:
        taken, held = _counts(conn, when)
    return {"taken": taken, "reserved": held}


@dataclass(frozen=True)
class Reservation:
    """`reserved_at` doubles as the reservation's reference (see WHICH RESERVATION A RELEASE MEANS).
    `created` is True only for the call that wrote the hold: a double click or a retry that is handed
    the live hold back gets False, and so must not give it back if its own request then fails."""
    user_id: int
    reserved_at: int
    holds_until: int
    already_member: bool = False
    created: bool = False

    @property
    def session_expires_at(self) -> int:
        """The `expires_at` to give Stripe for the Checkout Session this reservation backs."""
        return self.holds_until


def try_reserve(user_id: int, *, cap: int = FOUNDING_SEAT_CAP, now: Optional[int] = None,
                db: Optional[Path] = None) -> Optional[Reservation]:
    """Reserve a founding seat for `user_id`'s checkout, or None when every seat is taken or held.

    Idempotent for a live reservation: a second call while the first is still held returns the SAME
    reservation (same instants, `created` False), so a double click opens the same Stripe session
    instead of reserving two seats. A user who already holds an ACTIVE seat is returned as
    `already_member` without changing anything."""
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
        # Strictly later than this user's previous reservation, even inside the same second, so a
        # reference never names two sessions (a hold released and re-made at once is a NEW session).
        previous = (existing or {}).get("reserved_at")
        reserved_at = when if previous is None else max(when, previous + 1)
        conn.execute("""
            INSERT INTO founding_seats (user_id, state, reserved_at, holds_until, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state = excluded.state, reserved_at = excluded.reserved_at,
                holds_until = excluded.holds_until, updated_at = excluded.updated_at
        """, (user_id, STATE_PENDING, reserved_at, holds_until, when))
        return Reservation(user_id, reserved_at, holds_until, created=True)


def release_reservation(user_id: int, *, reserved_at: int, now: Optional[int] = None,
                        db: Optional[Path] = None) -> bool:
    """Give back the PENDING reservation `reserved_at` names, now, and say whether one was released.

    `reserved_at` is required on purpose: a release that names no reservation is how a late
    `checkout.session.expired` for an OLD session freed the NEW session's seat, and how a failed
    duplicate request freed the hold of the request that was still opening it. A different
    reference, an active seat, an ended row or no row at all is left exactly as it is. The row
    becomes `ended` (not just shortened), so the grace after the window does not keep it counted."""
    when = _now(now)
    with _connect(db) as conn:
        cursor = conn.execute(
            "UPDATE founding_seats SET state = ?, holds_until = ?, updated_at = ? "
            "WHERE user_id = ? AND state = ? AND reserved_at = ?",
            (STATE_ENDED, when, when, user_id, STATE_PENDING, reserved_at))
        return cursor.rowcount > 0


def _not_older(at: Optional[int], stamp: Optional[int]) -> bool:
    return at is None or stamp is None or at >= stamp


def record_subscription(user_id: int, subscription_id: str, status: Optional[str], at: Optional[int], *,
                        now: Optional[int] = None, db: Optional[Path] = None) -> None:
    """Apply one founding subscription event. `status` is the RAW Stripe subscription status (`canceled`
    for a deleted subscription): only `active`/`trialing` take a seat and only `canceled`, `unpaid` and
    `incomplete_expired` free one; anything else, `past_due` above all, changes nothing. See the module
    docstring for the ordering rules."""
    when = _now(now)
    live = status in _LIVE_STATUSES
    if not live and status not in _ENDING_STATUSES:
        return                  # says nothing about whether the subscription is over
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
