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

NO MUTATION ENDPOINTS HERE
-----------------------------
Both routes below are GET. Suspending a user, revoking a token, changing a
plan -- anything that writes -- already has its own home (api/auth.py's
invite endpoint, src/appstate/users.py's setters) or does not exist yet;
this module is a read surface and stays one, per this task's own scope.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict

from fastapi import APIRouter, Depends

from api.auth import _require_admin
from api.meta import APP_VERSION
from src.appstate import apphealth
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


@router.get("/admin/users")
def get_users(_admin: None = Depends(_require_admin)) -> dict:
    """id, email, status, plan, created_at for every user. The one place in
    this API an email appears -- see module docstring."""
    return {"users": [
        {"id": u.id, "email": u.email, "status": u.status, "plan": u.plan,
         "created_at": u.created_at}
        for u in users_store.list_users()
    ]}
