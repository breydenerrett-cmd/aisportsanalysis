"""Product-analytics event scaffold, stdlib-only (sqlite3, hashlib).

WIRED-IN CALL SITES
--------------------
`record_event()` (via `record_event_safe()`, see below) is called from:
  - api/games.py       -> kind=PAGE_VIEW, on a successful GET /games/{date},
                           GET /game/{date}/{away}/{home}, GET /changed/{date}
  - api/betcheck.py     -> kind=BET_CHECK_RUN, on a successful POST /betcheck
                           (never on the 400/404/502 error paths -- those are
                           not a completed check)
  - api/mybets.py       -> kind=BET_SAVED, on a successful POST /my-bets
                           (never on the 400 validation-error path)
  - api/auth.py         -> kind=INVITE_REDEEMED, from get_current_user, on
                           the request that transitions a token's
                           first_used_at from NULL to set (src/appstate/
                           users.py's mark_token_first_used) -- exactly once
                           per token, never on a later request with the same
                           already-used token.
  - api/digest.py       -> kind=DIGEST_VIEWED, on a successful GET /digest,
                           `properties={"date": <slate date>}`. Also read
                           back (via `latest_event`, below) BEFORE recording
                           the new one, to find the timestamp of the user's
                           previous digest -- see src/analysis/digest.py's
                           "SINCE LAST DIGEST" section for why that read has
                           to happen first.
  - api/signup.py        -> kind=SIGNUP_STARTED, on every new self-serve
                           signup (POST /signup creating a fresh user row);
                           kind=CHECKOUT_STARTED, whenever a real Stripe
                           checkout URL was actually handed back (never on
                           the honest "waitlisted" branch, since no checkout
                           started).
  - api/funnel.py       -> kind=LANDING_VIEW, from the PUBLIC POST
                           /funnel/event beacon -- the one funnel kind an
                           unauthenticated visitor may record before
                           anything else in the funnel has happened (see
                           that module's PUBLIC_FUNNEL_KINDS). SIGNUP_STARTED
                           is also in that allowlist, recorded on the same
                           beacon when the visitor is not yet a real user
                           row (api/signup.py's own SIGNUP_STARTED call site
                           covers the authenticated/self-serve case above;
                           the two are the same kind, recorded from whichever
                           side of the signup form the visitor is on).
                           Recorded under a fixed anonymous sentinel id
                           (ANONYMOUS_FUNNEL_USER_ID in api/funnel.py), never
                           a real user id, since there is no authenticated
                           identity at that point in the funnel.
  - src/appstate/billing.py -> kind=CHECKOUT_COMPLETED, from
                           apply_stripe_webhook_event on the checkout.session
                           .completed event that activates a pending_payment
                           signup -- the one place this app knows a real
                           Stripe payment happened, since it can only be
                           called after api/billing.py verifies the webhook
                           signature.
  - api/billing.py       -> kind=SUBSCRIPTION_CANCELLED, from POST
                           /billing/cancel, on an explicit user-initiated
                           cancellation only (never from a webhook-only
                           cancellation, to avoid double-counting the same
                           cancellation from two sources).
`api/today.py`'s `get_today_payload_cached` accepts an optional `user_id`
and records PAGE_VIEW when given one, but `GET /today` itself is wired
directly in api/app.py, which this task's BOUNDARIES forbid touching beyond
one admin include_router line -- so that one call site stays inert until a
future one-line app.py change passes `user_id=` through.
`user_hash` at each call site is `hash_user_id(current_user.id)` (or
whatever raw id the caller has -- `request.state.user_id` for the router-
level-authed GET routes) -- never the raw id, and never anything from the
request body.

WHY THE USER ID IS HASHED, NEVER STORED RAW
----------------------------------------------
Same rule src/appstate/users.py states for bearer tokens and
src/appstate/reqlog.py states for log lines, applied a third time here: an
analytics table is the piece of this system most likely to end up in a
BI tool, a CSV export, or a dashboard with looser access control than the
users table itself. Storing only sha256(user_id) means none of those
downstream copies can be joined back to an email or a real identity without
also having the raw id -- which this module never receives. `hash_user_id`
takes the raw id so this module is the ONE place that computation happens
consistently; nothing else in the codebase should hand-roll it.

WHAT NEVER GOES IN `properties_json`
----------------------------------------
No emails, no raw auth tokens, no bet amounts or stakes. `properties_json`
exists for event-shape context that is safe to aggregate across users
(e.g. {"date": "2026-08-31"} on a page_view, {"market": "h2h"} on a
bet_check_run) -- never anything that identifies a person or their money.
This module does not and cannot enforce that at the type level (a caller
can pass any JSON-serialisable dict), so the boundary is a documented
contract for every future call site, the same way src/appstate/savedbets.py
documents its append-only contract in prose rather than code.

SCHEMA
------
analytics_events(id, user_hash, kind, properties_json, at)
    kind: page_view | bet_check_run | bet_saved | invite_redeemed |
          landing_view | signup_started | checkout_started |
          checkout_completed | subscription_cancelled | digest_viewed
    at:   required ISO-8601 UTC string, the instant the event happened.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from src import paths

ENV_DB_PATH = "APP_DB_PATH"  # shared with src.appstate.users/savedbets -- one app db

# The only kinds this table accepts. Enumerated (not free text) so a typo'd
# kind fails loud at record time instead of silently fragmenting an
# aggregate query later -- the same reasoning src/analysis/contracts.py
# gives for refusing an unknown evidence label rather than storing it.
PAGE_VIEW = "page_view"
BET_CHECK_RUN = "bet_check_run"
BET_SAVED = "bet_saved"
INVITE_REDEEMED = "invite_redeemed"
SIGNUP_STARTED = "signup_started"
CHECKOUT_STARTED = "checkout_started"
CHECKOUT_COMPLETED = "checkout_completed"
SUBSCRIPTION_CANCELLED = "subscription_cancelled"
DIGEST_VIEWED = "digest_viewed"
# The one funnel kind with no authenticated identity behind it at all --
# see api/funnel.py's PUBLIC_FUNNEL_KINDS and module docstring above.
LANDING_VIEW = "landing_view"

EVENT_KINDS = frozenset({
    PAGE_VIEW, BET_CHECK_RUN, BET_SAVED, INVITE_REDEEMED,
    SIGNUP_STARTED, CHECKOUT_STARTED, CHECKOUT_COMPLETED, SUBSCRIPTION_CANCELLED,
    DIGEST_VIEWED, LANDING_VIEW,
})


def db_path() -> Path:
    override = (os.environ.get(ENV_DB_PATH) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return paths.repo_root() / "data" / "app" / "app.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_user_id(user_id) -> str:
    """The only form of a user identity this module ever stores or accepts.

    Takes whatever raw identifier a caller has on hand (an int user id, a
    string, ...) and returns its full sha256 hex digest -- irreversible in
    practice, same guarantee src/appstate/reqlog.py's `user_ref` relies on
    for log-line correlation. Callers pass the RAW id here and use the
    result everywhere else; this function is the one and only place the raw
    value is allowed to exist as an argument.
    """
    if user_id is None:
        raise ValueError("an event needs a user to hash -- pass the raw id, "
                          "not None (use a fixed sentinel string for "
                          "anonymous events if one is ever needed)")
    return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
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
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_hash TEXT NOT NULL,
            kind TEXT NOT NULL,
            properties_json TEXT,
            at TEXT NOT NULL
        )
    """)


@dataclass(frozen=True)
class AnalyticsEvent:
    id: int
    user_hash: str
    kind: str
    properties: dict
    at: str


def _row_to_event(row: sqlite3.Row) -> AnalyticsEvent:
    raw = row["properties_json"]
    return AnalyticsEvent(id=row["id"], user_hash=row["user_hash"],
                          kind=row["kind"],
                          properties=json.loads(raw) if raw else {},
                          at=row["at"])


def record_event(user_hash: str, kind: str, properties: Optional[dict] = None,
                 *, at: Optional[str] = None,
                 db: Optional[Path] = None) -> AnalyticsEvent:
    """Append one analytics event. Never updates or deletes -- an event log
    that can be rewritten in place is not a log, same append-only reasoning
    src/appstate/savedbets.py gives for saved bets.

    `user_hash` MUST already be a hash (call `hash_user_id` first) -- this
    function refuses anything that is not a 64-char hex sha256 digest, so a
    raw id passed by mistake fails loud here rather than landing in the
    database once and being unrecoverable without a full-table scrub.
    """
    if kind not in EVENT_KINDS:
        raise ValueError(
            f"unknown event kind {kind!r}; must be one of {sorted(EVENT_KINDS)}")
    if not user_hash or len(user_hash) != 64 or \
            any(ch not in "0123456789abcdef" for ch in user_hash.lower()):
        raise ValueError(
            "user_hash must be a sha256 hex digest (call hash_user_id() on "
            "the raw id first) -- record_event never accepts a raw id")
    at = at or _now_iso()
    properties_json = json.dumps(properties or {}, sort_keys=True)
    with _connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO analytics_events (user_hash, kind, properties_json, at) "
            "VALUES (?, ?, ?, ?)",
            (user_hash, kind, properties_json, at))
        return AnalyticsEvent(id=cur.lastrowid, user_hash=user_hash, kind=kind,
                              properties=properties or {}, at=at)


def record_event_safe(user_id, kind: str, properties: Optional[dict] = None, *,
                      at: Optional[str] = None, db: Optional[Path] = None) -> None:
    """`record_event`, but analytics can never fail or slow down the request
    that triggered it.

    Every caller wired into api/ (games.py, betcheck.py, mybets.py) calls
    this, not `record_event` directly: by the time a caller is ready to
    record a page_view or a completed bet check, it has already fetched the
    game, run the domain path, and built a good response for the client. A
    full disk, a locked sqlite file, or a bug in this module must cost one
    missing data point, never that response -- so every exception is
    swallowed here and printed to stderr (the same channel
    src/appstate/reqlog.py's request-log line uses) instead of raised.
    Takes the RAW user id (hashes it internally) so every call site stays a
    one-line, un-try/except-wrapped call.
    """
    try:
        record_event(hash_user_id(user_id), kind, properties, at=at, db=db)
    except Exception as exc:  # noqa: BLE001 -- see docstring: must never raise
        print(f"analytics: record_event_safe failed for kind={kind!r}: {exc!r}",
              file=sys.stderr, flush=True)


def list_events(*, db: Optional[Path] = None) -> List[AnalyticsEvent]:
    """Every recorded event, oldest first. Small-table debugging/testing
    helper -- the admin view wants `daily_counts_by_kind`, not this."""
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT * FROM analytics_events ORDER BY at ASC").fetchall()
        return [_row_to_event(r) for r in rows]


def latest_event(user_hash: str, kind: str, *,
                 db: Optional[Path] = None) -> Optional[AnalyticsEvent]:
    """The single most recent event of `kind` for `user_hash`, or None if
    that user has none yet.

    A real SQL WHERE/ORDER BY/LIMIT query, unlike `daily_counts_by_kind`'s
    Python aggregation over the whole table -- this one is looked up on
    every request to a per-user route (api/digest.py, once per GET /digest,
    to find a user's PREVIOUS digest before recording their new one), not
    once for an admin view, so it earns an index-friendly query the way a
    small, occasional admin report does not need to.
    """
    if kind not in EVENT_KINDS:
        raise ValueError(
            f"unknown event kind {kind!r}; must be one of {sorted(EVENT_KINDS)}")
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM analytics_events WHERE user_hash = ? AND kind = ? "
            "ORDER BY at DESC LIMIT 1", (user_hash, kind)).fetchone()
        return _row_to_event(row) if row else None


def daily_counts_by_kind(*, db: Optional[Path] = None) -> Dict[str, Dict[str, int]]:
    """Aggregate for a future admin view: {date_iso: {kind: count}}.

    Computed in Python over `list_events()` rather than a SQL GROUP BY on a
    sliced `at` string -- this table is small (a private beta, not a
    high-volume product) and a plain dict is trivial to unit-test and to
    hand to a template without a second SQL dialect to get right. If this
    table ever needs to aggregate millions of rows, move the grouping into
    SQL then; doing it now would be optimising for a scale this product
    does not have yet.
    """
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in list_events(db=db):
        day = event.at[:10]  # ISO-8601 date prefix, valid for any at we wrote
        out[day][event.kind] += 1
    return {day: dict(kinds) for day, kinds in out.items()}
