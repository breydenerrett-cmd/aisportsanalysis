"""POST /funnel/event (public) and GET /admin/funnel (admin): the
acquisition funnel from an anonymous landing-page view through to a
saved bet, per this task's brief.

REPORT BACK includes this file's own `from api.funnel import router as
funnel_router` / `app.include_router(funnel_router)` lines for whoever owns
api/app.py to add -- this module is never wired into app.py here (BOUNDARIES).

WHY THE PUBLIC ENDPOINT ONLY ACCEPTS TWO KINDS
------------------------------------------------
`events.EVENT_KINDS` (src/appstate/events.py) is the full set this app ever
records, but most of those kinds are recorded server-side from an action
that already happened under authentication (a completed bet check, a saved
bet, a redeemed invite, a completed checkout webhook) -- letting an
anonymous POST claim any of those would let anyone inflate "bet_saved" or
"checkout_completed" counts with events that never happened.
`PUBLIC_FUNNEL_KINDS` is the narrow allowlist of the two kinds that
genuinely have no authenticated identity yet: a page view of the landing
page, and a visitor beginning the signup form. Every other kind stays
server-recorded only, exactly as it already was before this file existed.

WHY A FIXED SENTINEL id, NOT THE CALLER'S IP
------------------------------------------------
`events.hash_user_id` refuses `None` but its own docstring names the
sanctioned way to record an event with no real identity: "use a fixed
sentinel string for anonymous events if one is ever needed". This is that
need. Hashing the caller's IP instead would look like real per-visitor
identity in the events table without actually being one (IPs are shared,
rotate, and sit behind NATs/VPNs) -- a fixed sentinel is honest that these
rows are unattributed counts, not a cohort of distinguishable visitors.

WHY 60/HR/IP
------------------------------------------------
Same shape as api/support.py's rate limiter (an hour-long fixed window,
keyed on IP via `ratelimit.limiter_dependency` with no `user_dependency`,
since there is no authenticated caller to key on here). 60/hr is generous
for a real visitor loading the landing page and starting the signup form a
few times in a sitting, while still bounding how cheaply a script can pad
landing_view counts.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import _require_admin
from src.appstate import events
from src.appstate.ratelimit import FixedWindowLimiter, limiter_dependency

router = APIRouter()

# The only two kinds an unauthenticated POST may ever record -- see module
# docstring. Every other member of events.EVENT_KINDS is refused with a 400.
PUBLIC_FUNNEL_KINDS = frozenset({events.LANDING_VIEW, events.SIGNUP_STARTED})

# See module docstring's "WHY A FIXED SENTINEL id" section.
ANONYMOUS_FUNNEL_USER_ID = "anonymous-funnel-visitor"

FUNNEL_RATE_LIMIT_PER_HOUR = 60
_funnel_limiter = FixedWindowLimiter(limit=FUNNEL_RATE_LIMIT_PER_HOUR, window_s=3600.0)
_rate_limit_funnel = limiter_dependency(_funnel_limiter)


class FunnelEventRequest(BaseModel):
    kind: str
    properties: Optional[dict] = None


@router.post("/funnel/event", dependencies=[Depends(_rate_limit_funnel)])
def post_funnel_event(body: FunnelEventRequest) -> dict:
    """Record one anonymous funnel event. 400s on any kind outside
    PUBLIC_FUNNEL_KINDS -- a public caller does not get to decide it
    completed a bet check or redeemed an invite; those are recorded from
    the server-side action itself, never from a client's say-so."""
    if body.kind not in PUBLIC_FUNNEL_KINDS:
        raise HTTPException(status_code=400, detail={
            "error": "kind_not_public",
            "message": (f"{body.kind!r} is not a public funnel event kind; "
                       f"allowed: {sorted(PUBLIC_FUNNEL_KINDS)}"),
        })
    events.record_event_safe(ANONYMOUS_FUNNEL_USER_ID, body.kind, body.properties)
    return {"recorded": True}


# The ordered acquisition funnel this task's brief names, stage by stage.
# CHECKOUT_STARTED/CHECKOUT_COMPLETED have no call site in this codebase yet
# (api/signup.py / api/billing.py, a concurrent lane's files) -- until they
# are wired, those two steps are an honest zero, never omitted or faked.
FUNNEL_STEPS: List[str] = [
    events.LANDING_VIEW,
    events.SIGNUP_STARTED,
    events.CHECKOUT_STARTED,
    events.CHECKOUT_COMPLETED,
    events.INVITE_REDEEMED,
    events.BET_CHECK_RUN,
    events.BET_SAVED,
]

# BET_CHECK_RUN and BET_SAVED can fire many times for the same user; the
# funnel step this task names is "first bet_check_run" / "first bet_saved",
# an activation milestone, not a running tally of every check a returning
# user makes. Everything else in FUNNEL_STEPS is counted as raw events in
# range instead -- LANDING_VIEW/SIGNUP_STARTED share one anonymous sentinel
# hash, so "distinct users" would collapse them to one no matter how many
# visitors there really were, and INVITE_REDEEMED/CHECKOUT_* already fire at
# most once per token/session by construction (see their own call sites).
FIRST_OCCURRENCE_STEPS = frozenset({events.BET_CHECK_RUN, events.BET_SAVED})

FUNNEL_DEFAULT_WINDOW_DAYS = 30


def _default_range(today: Optional[date_cls] = None) -> tuple:
    end = today or date_cls.today()
    start = end - timedelta(days=FUNNEL_DEFAULT_WINDOW_DAYS - 1)
    return start.isoformat(), end.isoformat()


def _parse_date(value: str, *, param: str) -> date_cls:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{param} must be YYYY-MM-DD, got {value!r}")


def _first_occurrence_days(all_events, kind: str) -> Dict[str, str]:
    """user_hash -> ISO date of that user's EARLIEST event of `kind`, across
    all recorded history (not just the report window) -- a user's first
    bet check from three months ago still belongs to the day it actually
    happened, not to whatever window happens to be requested today."""
    first: Dict[str, str] = {}
    for event in all_events:
        if event.kind != kind:
            continue
        day = event.at[:10]
        if event.user_hash not in first or day < first[event.user_hash]:
            first[event.user_hash] = day
    return first


def _step_counts(start: str, end: str, *, db=None) -> Dict[str, int]:
    """Each FUNNEL_STEPS kind's count within [start, end] inclusive --
    a raw event count for most steps, a distinct-first-occurrence count for
    FIRST_OCCURRENCE_STEPS (see that set's docstring)."""
    all_events = events.list_events(db=db)
    counts = {step: 0 for step in FUNNEL_STEPS}
    for step in FUNNEL_STEPS:
        if step in FIRST_OCCURRENCE_STEPS:
            first_days = _first_occurrence_days(all_events, step)
            counts[step] = sum(1 for day in first_days.values() if start <= day <= end)
        else:
            counts[step] = sum(
                1 for event in all_events
                if event.kind == step and start <= event.at[:10] <= end)
    return counts


@router.get("/admin/funnel")
def get_admin_funnel(start: Optional[str] = None, end: Optional[str] = None,
                     _admin: None = Depends(_require_admin)) -> dict:
    """Step counts across the whole acquisition funnel for [start, end]
    (both YYYY-MM-DD, inclusive; default: the trailing
    FUNNEL_DEFAULT_WINDOW_DAYS days ending today), with each step's
    conversion percentage from the step immediately before it.

    A step with zero events renders as count 0, never omitted -- "nobody
    reached checkout_started yet" is real information for a beta this
    early, not a hole in the data. `conversion_pct_from_previous` is `None`
    (never a fabricated 0 or 100) whenever the previous step's count is
    itself 0 -- there is no honest percentage of zero.
    """
    default_start, default_end = _default_range()
    start = start or default_start
    end = end or default_end
    start_d = _parse_date(start, param="start")
    end_d = _parse_date(end, param="end")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must not be before start")

    counts = _step_counts(start, end)
    steps_out = []
    previous_count: Optional[int] = None
    for kind in FUNNEL_STEPS:
        count = counts[kind]
        conversion_pct_from_previous = None
        if previous_count:
            conversion_pct_from_previous = round(100.0 * count / previous_count, 1)
        steps_out.append({
            "kind": kind,
            "count": count,
            "conversion_pct_from_previous": conversion_pct_from_previous,
        })
        previous_count = count
    return {"start": start, "end": end, "steps": steps_out}
