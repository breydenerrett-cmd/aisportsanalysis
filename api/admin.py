"""api/admin.py: read-only ops surface for Brey -- account counts, invite
backlog, analytics rollups, and store health, gated by the same
X-Admin-Token api/auth.py's invite endpoint already uses.

WHY THIS REUSES api.auth._require_admin RATHER THAN A SEPARATE ADMIN AUTH
----------------------------------------------------------------------------
Two independent admin gates (one per module) is two places a change to the
token comparison, or to what "absent APP_ADMIN_TOKEN" means, can drift out
of sync -- see api/auth.py's own ADMIN INVITE ENDPOINT docstring for why
absent-means-404 (the endpoint does not exist) rather than absent-means-open.
Importing the one function keeps that contract in one place; this module has
zero admin-auth logic of its own.

WHY GET /admin/users IS THE ONE PLACE EMAILS APPEAR
------------------------------------------------------
Every other response in this codebase (My Bets, Bet Check, analytics
events) is scoped to sha256 hashes or to the caller's own data -- see
src/appstate/events.py's WHY THE USER ID IS HASHED docstring section. An
admin needs the real email to actually run the beta (who to email, who to
suspend, who asked for an invite and never redeemed it); that need is real,
so this one endpoint is the deliberate exception, gated by the same admin
token as invite creation and reachable no other way.

TWO KINDS OF WRITE
-------------------
Everything else here is a GET, apart from the writes below.

POST /admin/users/token is the lost-token recovery, because the token is a
subscriber's only login and there is no email sender: without it a paying
customer who loses their token is locked out with no route back. Suspending,
plan changes and the invite flow keep their own homes (api/auth.py,
src/appstate/users.py).

POST /admin/testers and POST /admin/testers/extend are the early-access offer
(src/appstate/testers.py holds the policy and the reasons): the first 20
testers, 7 days each, no card, granted by the owner alone from the admin page.
GET /admin/testers lists them, and GET /admin/activation is the aggregate of
what they actually did (src/appstate/activation.py defines "activated" and
"returning"). They reuse this module's one admin gate, return a raw token exactly
once, and never put a token, an email or a reason into an event.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import _require_admin
from api.meta import APP_VERSION
from src.appstate import apphealth
from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import tester_upgrade
from src.appstate import testers
from src.appstate import users as users_store

router = APIRouter()

# How many trailing calendar days of daily_counts_by_kind ride along in the
# overview -- long enough to see a week-plus trend at a glance, short enough
# that a growing events table never makes this one payload balloon (that
# function itself scans the whole table -- see its own scale note in
# src/appstate/events.py).
OVERVIEW_EVENT_WINDOW_DAYS = 14


def _users_summary() -> Dict[str, object]:
    """Counts by status and by plan, plus the total -- never the users
    themselves (see module docstring for why GET /admin/users, not this
    function, is the one place an email appears)."""
    all_users = users_store.list_users()
    return {
        "total": len(all_users),
        "by_status": dict(Counter(u.status for u in all_users)),
        "by_plan": dict(Counter(u.plan for u in all_users)),
    }


def _recent_daily_counts(days: int = OVERVIEW_EVENT_WINDOW_DAYS) -> Dict[str, dict]:
    """The last `days` calendar days of daily_counts_by_kind, oldest first.

    daily_counts_by_kind() itself returns every day the events table has
    ever seen -- fine for that function's own small-table scope (see its
    docstring), but an overview page wants a bounded recent window, not the
    whole history growing every day this beta runs.
    """
    all_counts = events.daily_counts_by_kind()
    recent_days = sorted(all_counts.keys())[-days:] if days > 0 else []
    return {day: all_counts[day] for day in recent_days}


@router.get("/admin/overview")
def get_overview(_admin: None = Depends(_require_admin)) -> dict:
    """Account counts, invite backlog, a 14-day analytics rollup, store
    health, and the running version -- one page for "how is the beta doing
    right now", gated by X-Admin-Token (404 if APP_ADMIN_TOKEN is unset,
    401 on a wrong token -- see api.auth._require_admin)."""
    return {
        "users": _users_summary(),
        "invites_outstanding": users_store.count_outstanding_invites(),
        "events": {"daily_counts_by_kind": _recent_daily_counts()},
        "store_health": apphealth.report(),
        "version": APP_VERSION,
    }


DIRECT_SOURCE = "(direct)"


@router.get("/admin/revenue")
def get_revenue(_admin: None = Depends(_require_admin)) -> dict:
    """Who is paying, who is trialing, what that is worth a month, and which
    channel each signup came from -- the answer to "is the funnel making
    money", from the app's own tables, never a live Stripe call.

    Reads `billing_subscriptions` (what verified webhooks have reported) and
    the first-touch `signup_attribution` rows, and nothing else.

      paying          subscriptions in status `active` -- billed this period.
      trialing        status `trialing` -- inside the free trial, not yet billed.
      cancel_scheduled  active or trialing subscriptions set to stop renewing
                      (they still count in `paying`/`trialing` until the
                      period ends, and are NOT in `mrr_cents` going forward).
      canceled        status `canceled`.
      unpaid          status `active`/`trialing` but not entitled: nothing is
                      paid through yet, or the paid-through (plus the renewal
                      grace) has passed. Not counted in `paying`, `trialing`
                      or any MRR figure.
      mrr_cents       `paying` minus `cancel_scheduled` actives, times the
                      plan price (billing.BETA_PLAN_PRICE_CENTS = 1999).
                      Trialing is never counted: nothing has been charged.
                      `mrr_gross_cents` is the figure without the cancel
                      subtraction.

    A checkout that just completed is recorded `active` with nothing paid
    through until the paid invoice (or the trial's `customer.subscription
    .created`) arrives moments later (see
    src.appstate.billing.apply_stripe_webhook_event); until then it is
    `unpaid`, not paying. The reconciled number is what the Stripe dashboard
    shows, this is the app's own view.

    `signups_by_source` counts every user by the utm_source of their first
    touch ("(direct)" when they have none); `paying_by_source` and
    `trialing_by_source` are the same split for subscriptions.
    """
    price = billing.BETA_PLAN_PRICE_CENTS
    attribution = customers.all_signup_attribution()

    def source_of(user_id: int) -> str:
        return (attribution.get(user_id) or {}).get("utm_source") or DIRECT_SOURCE

    counts = Counter()
    paying_by_source: Counter = Counter()
    trialing_by_source: Counter = Counter()
    cancel_scheduled = 0
    active_not_canceling = 0
    now = datetime.now(timezone.utc)
    unpaid = 0
    for row in customers.list_subscription_rows():
        status = row["status"]
        scheduled = bool(row.get("cancel_at"))
        if status in customers.PAID_STATUSES:
            # The status word is not revenue: a row counts as paying or
            # trialing only while it is actually entitled (paid through a
            # future instant, plus the renewal grace). An `active` row nothing
            # has been paid for yet (a completed session whose invoice has not
            # arrived) or whose paid-through has passed (a renewal never paid,
            # or the invoice events not subscribed) is `unpaid`, not MRR.
            end = customers.entitled_through(status, row.get("cancel_at"),
                                             row.get("paid_through"),
                                             row.get("grace_blocked"))
            if end is None or now > end:
                unpaid += 1
                continue
        if status == "active":
            counts["paying"] += 1
            paying_by_source[source_of(row["user_id"])] += 1
            if scheduled:
                cancel_scheduled += 1
            else:
                active_not_canceling += 1
        elif status == "trialing":
            counts["trialing"] += 1
            trialing_by_source[source_of(row["user_id"])] += 1
            if scheduled:
                cancel_scheduled += 1
        else:
            counts["canceled"] += 1

    all_users = users_store.list_users()
    signups_by_source = Counter(source_of(u.id) for u in all_users)
    return {
        "price_cents": price,
        "paying": counts["paying"],
        "trialing": counts["trialing"],
        "cancel_scheduled": cancel_scheduled,
        "canceled": counts["canceled"],
        "unpaid": unpaid,
        "mrr_cents": active_not_canceling * price,
        "mrr_gross_cents": counts["paying"] * price,
        "mrr_usd": round(active_not_canceling * price / 100.0, 2),
        "signups_total": len(all_users),
        "signups_by_source": dict(signups_by_source.most_common()),
        "paying_by_source": dict(paying_by_source.most_common()),
        "trialing_by_source": dict(trialing_by_source.most_common()),
    }


@router.get("/admin/users")
def get_users(_admin: None = Depends(_require_admin)) -> dict:
    """id, email, status, plan, created_at for every user, plus whether they
    are an early-access tester and when that access was granted and (the
    newest token) ends. The one place in this API an email appears -- see
    module docstring."""
    marks = testers.tester_marks()
    return {"users": [
        {"id": u.id, "email": u.email, "status": u.status, "plan": u.plan,
         "created_at": u.created_at, "tester": u.id in marks,
         "tester_granted_at": (marks.get(u.id) or {}).get("granted_at"),
         "tester_expires_at": (marks.get(u.id) or {}).get("expires_at")}
        for u in users_store.list_users()
    ]}


class ReissueTokenRequest(BaseModel):
    """Exactly one of `email` or `user_id`."""
    email: Optional[str] = None
    user_id: Optional[int] = None


@router.post("/admin/users/token")
def reissue_subscriber_token(body: ReissueTokenRequest,
                             _admin: None = Depends(_require_admin)) -> dict:
    """Mint a fresh subscriber token for a paying user who lost theirs.

    SUPPORT PROCEDURE (token is the only login; no email sender exists):
      1. Confirm the person owns the account email (reply from it, or the
         Stripe receipt email) -- never reissue on a bare request.
      2. POST /admin/users/token with X-Admin-Token and {"email": "..."}.
      3. 409 means no paid access (lapsed or never paid): do not work around it.
      4. The response carries the raw token ONCE; send it over the same channel
         the person wrote from. Every older token for that user is revoked now.
      5. Never paste the token into a ticket, a log or a chat that persists.
      6. The event `support_token_reissued` records that it happened, not it.

    Paid access is customers.has_paid_access (trialing counts); the token
    lives billing.SUBSCRIBER_TOKEN_TTL. The token is never logged here.

    SUPERSEDED for support recovery by POST /admin/users/reissue (below): that
    route also covers testers, requires a reason and writes it to the audit
    log. This one is kept unchanged for the callers and tests that already
    use it; docs/billing/RECOVERY_PROCEDURE.md names only the newer route."""
    if (body.email is None) == (body.user_id is None):
        raise HTTPException(status_code=400,
                            detail="send exactly one of email or user_id")
    if body.email is not None:
        # Signup stores the address lower-cased; support will paste it as written.
        user = users_store.get_user_by_email(body.email.strip().lower())
    else:
        user = users_store.get_user(body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="no such user")
    if not customers.has_paid_access(user.id):
        raise HTTPException(
            status_code=409,
            detail="this user has no paid access, so no subscriber token was issued")
    revoked = users_store.revoke_all_tokens(user.id)
    raw_token = users_store.issue_invite_token(
        user.id, ttl=billing.SUBSCRIBER_TOKEN_TTL)
    events.record_event_safe(user.id, events.SUPPORT_TOKEN_REISSUED,
                             {"revoked_tokens": revoked})
    return {"user_id": user.id, "email": user.email, "token": raw_token,
            "revoked_tokens": revoked}


class ReissueAccessRequest(BaseModel):
    """Exactly one of `email` or `user_id`, and a `reason` (always)."""
    email: Optional[str] = None
    # Any, not int: a value that is not a real account id (a string, a float, a
    # list, 2**70) is the same 409 as an unknown account, not a 422 or a 500.
    # See _account_id.
    user_id: Optional[Any] = None
    reason: Optional[str] = None


# A reason is a note ("verified by reply from the account mailbox, ticket 41"),
# not an essay and not a place to paste the credential it is about.
REISSUE_REASON_MAX = 500
# What counts as "a token in the reason". The product's access tokens are
# secrets.token_urlsafe(32): 43 characters of [A-Za-z0-9_-] (src/appstate/users.py
# insert_token), so any 32-character run of that alphabet is refused wherever it
# sits in the sentence. The rest are the ways a token is usually pasted with
# something around it: an Authorization header, a token= or session_id= query
# parameter, an admin header, a Stripe checkout session id (which is itself the
# key to the activation bridge). A plain "lost bearer token" is fine.
_LOOKS_LIKE_A_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,}")
_SECRET_HINTS = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|token\s*=\s*\S"
    r"|session_id\s*="
    r"|x-admin-token"
    r"|\bcs_(?:test|live)_[A-Za-z0-9]{8,}",
    re.IGNORECASE)

# ONE refusal for every reason a re-issue cannot happen -- no such account, a
# waitlisted signup, a lapsed subscriber, a suspended user, a tester with a
# subscription record. The admin is the caller, but what an admin reads out in
# a chat or a ticket must never tell the asker whether an address has an
# account. The admin page shows the real state; this answer does not.
REISSUE_REFUSED = {"error": "reissue_refused",
                   "message": "no token was issued: this request does not match an "
                              "account that can be given one"}


# SQLite stores an integer in 8 bytes; a bigger one raises OverflowError the
# moment it is bound to a query. An account id is a positive row id.
_MAX_ACCOUNT_ID = 2 ** 63 - 1


def _account_id(value: Any) -> Optional[int]:
    """`value` if it can be the id of an account, else None -- a bool, a string,
    a float, a list, zero, a negative number or anything past SQLite's integer
    range. The caller treats None exactly like an unknown account (the one 409),
    so a probe with 2**70 learns nothing a probe with 99999 would not."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= _MAX_ACCOUNT_ID else None


def _reissue_plan(user: Optional[users_store.User]):
    """(kind, token end) for an account support may re-issue for, else None.

    subscriber: customers.has_paid_access (trialing counts), the usual
        subscriber token lifetime. The subscription record is never written.
    tester: a `testers` row, no subscription record, not suspended. The token
        ends exactly where the tester window ends (testers.expires_at): a
        re-issue replaces a lost credential, it does not grant the week again
        (that is POST /admin/testers/extend, which needs feedback to justify
        it). An ENDED window yields a token already past its end, which opens
        nothing but identifies the person to POST /billing/tester-checkout, the
        door an expired tester converts through.
    Anything else (a lapsed subscriber, a waitlisted signup, a suspended
    account) is None: the same stance as POST /admin/users/token, "do not work
    around it"."""
    if user is None or user.status == "suspended":
        return None
    now = datetime.now(timezone.utc)
    if customers.has_paid_access(user.id, now):
        return "subscriber", now + billing.SUBSCRIBER_TOKEN_TTL
    if customers.get_subscription_record(user.id) is not None:
        return None
    window = tester_upgrade.tester_window(user.id)
    try:
        ends = datetime.fromisoformat(window["expires_at"]) if window else None
    except (TypeError, ValueError):
        ends = None
    if ends is None:
        return None
    return "tester", (ends if ends.tzinfo else ends.replace(tzinfo=timezone.utc))


def _write_reissue_audit(conn, user_id: int, properties: dict) -> None:
    """The `support_token_reissued` row, written on the caller's open transaction.

    events.record_event opens its own connection, which cannot be part of
    users.reissue_token's transaction (a second writer would wait out the first's
    lock), so the one INSERT is repeated here: same table, same columns, same
    hashed user, same JSON, with the schema ensured on the shared connection."""
    events._ensure_schema(conn)
    conn.execute(
        "INSERT INTO analytics_events (user_hash, kind, properties_json, at) "
        "VALUES (?, ?, ?, ?)",
        (events.hash_user_id(user_id), events.SUPPORT_TOKEN_REISSUED,
         json.dumps(properties, sort_keys=True), events._now_iso()))


def _record_failed_reissue(user_id: int, kind: str, reason: str, stage: str) -> None:
    """After a re-issue was rolled back, say so in the audit log: one
    `support_token_reissued` row with action `reissue_failed` (never `reissue`),
    the reason and the stage that failed. Best effort: if the database is what
    failed, this write fails too and the stderr line is what is left. Never
    raises; the 503 the caller is about to send is the answer."""
    try:
        events.record_event(
            events.hash_user_id(user_id), events.SUPPORT_TOKEN_REISSUED,
            {"action": "reissue_failed", "kind": kind, "reason": reason, "stage": stage},
            db=users_store.db_path())
    except Exception as exc:  # noqa: BLE001
        print(f"admin: could not record the failed reissue: {exc!r}",
              file=sys.stderr, flush=True)


@router.post("/admin/users/reissue")
def reissue_access_token(body: ReissueAccessRequest,
                         _admin: None = Depends(_require_admin)) -> dict:
    """SUPPORT RECOVERY, NOT SELF-SERVICE: replace the access token of a paying
    subscriber or an early-access tester who has lost theirs. There is no email
    sender, so this is the only way back for a buyer who closed the checkout tab
    before the token was read, let the 10-minute re-read window pass, or opens
    the product on another device (docs/billing/RECOVERY_PROCEDURE.md).

    SUPPORT PROCEDURE (the one-page version; the full one is that document):
      1. Ownership is proven by the MAILBOX: write to the address on the account
         and call this ONLY after a reply arrives FROM that mailbox confirming
         the request. The Get help form proves nothing (its email field is typed,
         anyone can type a victim's address), so nothing is revoked before the
         reply; the answer goes ONLY to that address. An email, a checkout id or
         a name in a chat or DM proves nothing either.
      2. POST here with X-Admin-Token and {"email" | "user_id", "reason"}. The
         reason is required (what was verified, which ticket) and is written to
         the audit log.
      3. 409 `reissue_refused` is one answer for every kind of "no": do not work
         around it and do not tell the asker which kind it was.
      4. The response carries the raw token ONCE. Send it to the account's
         address; never paste it into a ticket, a chat or a log.
      5. Every earlier token of that user is revoked in the same transaction as
         the new one is minted. Neither the tester window nor paid_through is
         touched.

    AUDIT: one `support_token_reissued` event in the events table (the existing
    log, keyed by the user's hash) carrying `action: "reissue"`, `reason`, `kind`,
    `revoked_tokens`, never a token or an email. It is written in the SAME
    transaction as the revoke and the new token: a failure of either (503) leaves
    the accounts exactly as they were and no "reissue" row behind, so an unlogged
    issue and a logged non-issue are both impossible. A re-issue that failed is
    then recorded as `action: "reissue_failed"` (best effort). The reason is
    checked before any account is looked up, so a missing reason says nothing
    about whether the account exists, and it may not contain a token.
    """
    if (body.email is None) == (body.user_id is None):
        raise HTTPException(status_code=400,
                            detail="send exactly one of email or user_id")
    why = (body.reason or "").strip()
    if not why:
        raise HTTPException(status_code=400, detail={
            "error": "reason_required",
            "message": "say what was verified and for which ticket"})
    if len(why) > REISSUE_REASON_MAX:
        raise HTTPException(status_code=400, detail={
            "error": "reason_too_long",
            "message": f"keep the reason under {REISSUE_REASON_MAX} characters"})
    if _LOOKS_LIKE_A_TOKEN.search(why) or _SECRET_HINTS.search(why):
        raise HTTPException(status_code=400, detail={
            "error": "reason_looks_like_a_secret",
            "message": "the reason is stored in a log; do not paste a token or key into it"})
    if body.email is not None:
        user = users_store.get_user_by_email(body.email.strip().lower())
    else:
        account_id = _account_id(body.user_id)
        user = users_store.get_user(account_id) if account_id is not None else None
    plan = _reissue_plan(user)
    if plan is None:
        raise HTTPException(status_code=409, detail=dict(REISSUE_REFUSED))
    kind, ends_at = plan
    # The audit row is written INSIDE the token change's transaction, so the row
    # and the change stand or fall together: no "reissue" row for a re-issue that
    # did not happen, and no re-issue without its row.
    audit_failed = False

    def write_audit(conn, revoked: int) -> None:
        nonlocal audit_failed
        try:
            _write_reissue_audit(conn, user.id, {
                "action": "reissue", "kind": kind, "reason": why,
                "revoked_tokens": revoked})
        except Exception:  # noqa: BLE001 -- noted, then re-raised to roll back
            audit_failed = True
            raise

    try:
        raw_token, revoked = users_store.reissue_token(
            user.id, expires_at=ends_at, audit=write_audit)
    except Exception as exc:  # noqa: BLE001 -- fail closed: nothing was changed
        stage = "audit_write" if audit_failed else "token_change"
        print(f"admin: reissue failed at {stage}, nothing changed: {exc!r}",
              file=sys.stderr, flush=True)
        _record_failed_reissue(user.id, kind, why, stage)
        if audit_failed:
            raise HTTPException(status_code=503, detail={
                "error": "audit_log_unavailable",
                "message": "the audit log could not be written, so nothing was issued"})
        raise HTTPException(status_code=503, detail={
            "error": "reissue_failed",
            "message": "the token could not be changed; nothing was issued or revoked"})
    return {"user_id": user.id, "email": user.email, "token": raw_token, "kind": kind,
            "expires_at": ends_at.isoformat(), "revoked_tokens": revoked}


# ---------------------------------------------------------------------------
# Early-access testers (src/appstate/testers.py holds the policy)
# ---------------------------------------------------------------------------

class TesterGrantRequest(BaseModel):
    """Exactly one of `email` or `user_id`."""
    email: Optional[str] = None
    user_id: Optional[int] = None


class TesterExtendRequest(BaseModel):
    user_id: Optional[int] = None
    reason: Optional[str] = None


def _refusal(exc: testers.TesterRefused) -> HTTPException:
    """The policy's refusals as this API's structured error shape: the same
    {"error", "message"} detail api/auth.py's 401s use, plus any context the
    refusal carries (the count, for the cap)."""
    detail = {"error": exc.code, "message": exc.message}
    detail.update(exc.extra)
    return HTTPException(status_code=exc.status, detail=detail)


def _stored_attribution(user_id: int) -> dict:
    """The user's first-touch attribution for the grant event, or {} if it
    cannot be read. Never raises: by the time this runs the grant has committed
    and the response must still carry the one copy of the token that will ever
    exist -- failing here would burn a slot and lose it."""
    try:
        return customers.get_signup_attribution(user_id)
    except Exception as exc:  # noqa: BLE001
        print(f"admin: could not read attribution for user_id={user_id}: {exc!r}",
              file=sys.stderr, flush=True)
        return {}


@router.post("/admin/testers")
def grant_tester_access(body: TesterGrantRequest,
                        _admin: None = Depends(_require_admin)) -> dict:
    """Grant early access to one person: a new 7-day token and a slot of the 20.

    Send exactly one of `email` (a new email creates the user) or `user_id`.
    The response carries the RAW token ONCE -- the owner sends it himself;
    nothing is stored but its hash. 409 with a structured `error` and nothing
    written when the 20 slots are used (`tester_limit_reached`), the account is
    suspended (`user_suspended`), a subscription record exists
    (`has_subscription`), a checkout is open (`checkout_open`) or the person is
    already a tester (`already_a_tester`). The event `tester_access_granted`
    records the user's stored signup attribution, never the token or the email.
    """
    if (body.email is None) == (body.user_id is None):
        raise HTTPException(status_code=400,
                            detail="send exactly one of email or user_id")
    try:
        grant = testers.grant_tester(email=body.email, user_id=body.user_id)
    except testers.TesterRefused as exc:
        raise _refusal(exc)
    events.record_event_safe(grant.user_id, events.TESTER_ACCESS_GRANTED,
                             _stored_attribution(grant.user_id))
    return {"user_id": grant.user_id, "email": grant.email, "token": grant.token,
            "expires_at": grant.expires_at, "testers_granted": grant.testers_granted,
            "testers_limit": grant.testers_limit}


@router.post("/admin/testers/extend")
def extend_tester_access(body: TesterExtendRequest,
                         _admin: None = Depends(_require_admin)) -> dict:
    """Another 7 days for an existing tester, with the reason it was earned.

    NOT the lost-token door: a tester who only lost the token is re-issued one
    with POST /admin/users/reissue, which keeps the window and revokes the lost
    token. Extending is for feedback that earned more time.

    Issues a NEW token; older tokens keep their own expiry (nothing is revoked)
    and no further slot is used. `reason` is required: what feedback justified
    it. 409 `not_a_tester` for anyone never granted, 409 `user_suspended`, and
    409 `has_subscription` for a person with a subscription record (a paying or
    formerly paying customer is not a tester; the new token would open nothing).
    The event `tester_access_extended` records a counter, never the token or the
    reason.
    """
    if body.user_id is None:
        raise HTTPException(status_code=400, detail="send a user_id")
    try:
        grant = testers.extend_tester(body.user_id, body.reason or "")
    except testers.TesterRefused as exc:
        raise _refusal(exc)
    events.record_event_safe(grant.user_id, events.TESTER_ACCESS_EXTENDED,
                             {"extension_number": grant.extension_number})
    return {"user_id": grant.user_id, "email": grant.email, "token": grant.token,
            "expires_at": grant.expires_at, "testers_granted": grant.testers_granted,
            "testers_limit": grant.testers_limit,
            "extension_number": grant.extension_number}


@router.get("/admin/testers")
def get_testers(_admin: None = Depends(_require_admin)) -> dict:
    """Every tester (user_id, email, granted_at, expires_at of their newest
    token, each extension with its reason, and what they did) plus `granted`,
    `limit` and `remaining` of the 20. Never a token.

    `first_used_at` / `first_signin_at` is when a token was first used: a
    sign-in. `activated` is NOT that: it means a value action (an authenticated
    request that returned product content), with `activated_at`,
    `hours_signup_to_activation`, `last_active_at`, `active_days`, `returning`
    and `features` (label to count). See src/appstate/activation.py."""
    return testers.list_testers()


@router.get("/admin/activation")
def get_activation(_admin: None = Depends(_require_admin)) -> dict:
    """The tester activity aggregate: how many were granted, are inside their
    window, activated, returning, the median hours from signup to activation,
    and how many distinct testers used each feature. No emails and no user ids,
    so it can be pasted into a dashboard file as it is. Our own test accounts
    (signup source `internal` or `internal-...`) are left out and counted in
    `internal_excluded`. `unmeasured_features` lists labels no route can record
    yet, so a zero there is not read as "nobody used it"."""
    return testers.activation_report()
