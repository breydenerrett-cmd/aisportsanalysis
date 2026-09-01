"""POST /funnel/event (public) and GET /admin/funnel (admin): the
acquisition funnel from an anonymous landing-page view through to a
saved bet, per this task's brief.

This module IS wired into app.py: `from api.funnel import router as
funnel_router` / `app.include_router(funnel_router)` both already live
there (corrected 2026-09-01 -- this docstring previously claimed the
opposite, left over from before that wiring landed).

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
page, and a visitor REACHING the signup form. Every other kind stays
server-recorded only, exactly as it already was before this file existed.

That allowlist is deliberately UNCHANGED by the 2026-09-01 signup split:
`signup_started` is still exactly what an anonymous client may post, and
still means "a visitor reached the form". What changed is that it no longer
ALSO means "an account was created" -- that moment is `account_created`,
recorded server-side in api/signup.py and, like every other server-side
kind, refused from this endpoint. Keeping the public contract fixed is what
lets the existing web/ client keep beaconing while the funnel becomes
honest behind it.

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

import json
from datetime import date as date_cls, datetime, timedelta, timezone
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

# Defensive review finding F4: this route has no auth behind it at all (see
# module docstring), so an unbounded `properties` dict would be a free way
# to push an arbitrarily large blob into analytics_events.properties_json --
# src/appstate/events.py enforces no size bound of its own, by design (it
# trusts every wired-in call site to already be event-shaped). 2KB is
# generous over any real landing_view/signup_started property shape (a UTM
# tag, a referrer) while still bounding this public input.
MAX_PROPERTIES_JSON_BYTES = 2048


def _validated_properties(properties: Optional[dict]) -> Optional[dict]:
    """`properties`, or a 400 if it is not JSON-serializable at all (a
    client-controlled dict can hold shapes pydantic's bare `dict` type
    does not reject, e.g. a non-finite float) or serializes past
    MAX_PROPERTIES_JSON_BYTES. Raises rather than truncating -- silently
    dropping part of a caller's payload would record a different event
    than the one they sent, which is worse than refusing it outright."""
    if properties is None:
        return None
    try:
        serialized = json.dumps(properties)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={
            "error": "properties_not_serializable",
            "message": f"properties must be JSON-serializable: {exc}"})
    if len(serialized.encode("utf-8")) > MAX_PROPERTIES_JSON_BYTES:
        raise HTTPException(status_code=400, detail={
            "error": "properties_too_large",
            "message": f"properties must serialize to at most "
                       f"{MAX_PROPERTIES_JSON_BYTES} bytes"})
    return properties


class FunnelEventRequest(BaseModel):
    kind: str
    properties: Optional[dict] = None


@router.post("/funnel/event", dependencies=[Depends(_rate_limit_funnel)])
def post_funnel_event(body: FunnelEventRequest) -> dict:
    """Record one anonymous funnel event. 400s on any kind outside
    PUBLIC_FUNNEL_KINDS -- a public caller does not get to decide it
    completed a bet check or redeemed an invite; those are recorded from
    the server-side action itself, never from a client's say-so. Also
    400s on an oversized/unserializable `properties` -- see
    _validated_properties (defensive review finding F4)."""
    if body.kind not in PUBLIC_FUNNEL_KINDS:
        raise HTTPException(status_code=400, detail={
            "error": "kind_not_public",
            "message": (f"{body.kind!r} is not a public funnel event kind; "
                       f"allowed: {sorted(PUBLIC_FUNNEL_KINDS)}"),
        })
    properties = _validated_properties(body.properties)
    events.record_event_safe(ANONYMOUS_FUNNEL_USER_ID, body.kind, properties)
    return {"recorded": True}


# The ordered acquisition funnel, stage by stage. FREE_BET_CHECK sits where
# the product puts it -- a visitor tries the thing before deciding to sign
# up -- and SIGNUP_STARTED/ACCOUNT_CREATED are two rows, not one, since
# 2026-09-01 (see events.ACCOUNT_CREATED's own comment for why the merged
# version was actively wrong rather than merely coarse).
FUNNEL_STEPS: List[str] = [
    events.LANDING_VIEW,
    events.FREE_BET_CHECK,
    events.SIGNUP_STARTED,
    events.ACCOUNT_CREATED,
    events.CHECKOUT_STARTED,
    events.CHECKOUT_COMPLETED,
    events.INVITE_REDEEMED,
    events.BET_CHECK_RUN,
    events.BET_SAVED,
]

# Which step each step's conversion percentage is measured FROM. Defaults to
# the one immediately before it; this map is the exception list.
#
# Trying the free tier is a BRANCH off the landing page, not a gate in front
# of signup -- plenty of visitors will read the page and sign up without
# ever running a free check. Chaining signup_started off free_bet_check
# (which is what a plain neighbour-to-neighbour walk does once free_bet_check
# is inserted) would report those visitors as a conversion loss and could
# even read over 100%. Both steps therefore measure off landing_view, and
# the response says so in `conversion_from` rather than leaving a reader to
# assume the neighbour.
CONVERSION_BASELINE: Dict[str, str] = {
    events.SIGNUP_STARTED: events.LANDING_VIEW,
}

# BET_CHECK_RUN and BET_SAVED can fire many times for the same user; the
# funnel step this task names is "first bet_check_run" / "first bet_saved",
# an activation milestone, not a running tally of every check a returning
# user makes. Everything else in FUNNEL_STEPS is counted as raw events in
# range instead -- LANDING_VIEW/SIGNUP_STARTED share one anonymous sentinel
# hash, so "distinct users" would collapse them to one no matter how many
# visitors there really were, and INVITE_REDEEMED/CHECKOUT_* already fire at
# most once per token/session by construction (see their own call sites).
# FREE_BET_CHECK is counted raw as well, and that is the useful number here:
# each free identity may run up to three, and "how much of the free budget
# is actually being spent" is what says whether the offer is landing. Its
# user_hash IS per-identity (unlike the landing sentinel), so the
# distinct-visitor version stays recoverable from the same rows if it is
# ever wanted -- it is just not the launch question.
FIRST_OCCURRENCE_STEPS = frozenset({events.BET_CHECK_RUN, events.BET_SAVED})

FUNNEL_DEFAULT_WINDOW_DAYS = 30


def _default_range(today: Optional[date_cls] = None) -> tuple:
    """Default window: the trailing FUNNEL_DEFAULT_WINDOW_DAYS days ending
    TODAY IN UTC -- deliberately not `date.today()`, which reads the host's
    LOCAL date.

    Every event this module counts is stamped by
    src.appstate.events with `datetime.now(timezone.utc).isoformat()`, and
    _step_counts compares those stamps as `event.at[:10]` -- a UTC calendar
    date. A local `date.today()` on any host west of UTC (Brey's machine is
    UTC-7) is BEHIND that date for the whole evening, so every event
    recorded after 17:00 local landed on a UTC day strictly after the
    window's `end` and was silently dropped: the funnel rendered all-zero
    for exactly the hours the app was being used. Comparing a UTC-derived
    window against UTC-stamped events keeps both sides in one frame.
    """
    end = today or datetime.now(timezone.utc).date()
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
    (never a fabricated 0 or 100) whenever the baseline step's count is
    itself 0 -- there is no honest percentage of zero. Each step also names
    the step its percentage is measured from in `conversion_from` (`None`
    for the first step, which has nothing to convert from): usually the
    step immediately before, except where CONVERSION_BASELINE says
    otherwise, and a reader should not have to guess which.
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
    for index, kind in enumerate(FUNNEL_STEPS):
        count = counts[kind]
        baseline_kind = CONVERSION_BASELINE.get(kind)
        if baseline_kind is None and index > 0:
            baseline_kind = FUNNEL_STEPS[index - 1]
        baseline_count = counts.get(baseline_kind) if baseline_kind else None
        conversion_pct_from_previous = None
        if baseline_count:
            conversion_pct_from_previous = round(100.0 * count / baseline_count, 1)
        steps_out.append({
            "kind": kind,
            "count": count,
            "conversion_from": baseline_kind,
            "conversion_pct_from_previous": conversion_pct_from_previous,
        })
    return {"start": start, "end": end, "steps": steps_out}
