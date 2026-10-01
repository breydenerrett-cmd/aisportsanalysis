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

ONE MUTATION ENDPOINT: POST /admin/users/token
-------------------------------------------------
Everything else here is a GET. The one write is the lost-token recovery below,
because the token is a subscriber's only login and there is no email sender:
without it a paying customer who loses their token is locked out with no
route back. Suspending, plan changes and the invite flow keep their own homes
(api/auth.py, src/appstate/users.py).
"""

from __future__ import annotations

from collections import Counter
from typing import Dict

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import _require_admin
from api.meta import APP_VERSION
from src.appstate import apphealth
from src.appstate import billing
from src.appstate import customers
from src.appstate import events
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
      mrr_cents       `paying` minus `cancel_scheduled` actives, times the
                      plan price (billing.BETA_PLAN_PRICE_CENTS = 1999).
                      Trialing is never counted: nothing has been charged.
                      `mrr_gross_cents` is the figure without the cancel
                      subtraction.

    A checkout that just completed is recorded `active` until Stripe's
    `customer.subscription.created` arrives moments later and corrects it to
    `trialing` (see src.appstate.billing.apply_stripe_webhook_event), so a
    fresh trial can read as paying for a short window when the checkout event
    is processed first. If the subscription event arrives first the row is
    already `trialing` and the checkout event keeps it. The reconciled number
    is what the Stripe dashboard shows, this is the app's own view.

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
    for row in customers.list_subscription_rows():
        status = row["status"]
        scheduled = bool(row.get("cancel_at"))
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
    """id, email, status, plan, created_at for every user. The one place in
    this API an email appears -- see module docstring."""
    return {"users": [
        {"id": u.id, "email": u.email, "status": u.status, "plan": u.plan,
         "created_at": u.created_at}
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
    lives billing.SUBSCRIBER_TOKEN_TTL. The token is never logged here."""
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
