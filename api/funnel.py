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
import re
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import _require_admin
from src.appstate import attribution as attribution_mod
from src.appstate import events
from src.appstate.ratelimit import FixedWindowLimiter, limiter_dependency

router = APIRouter()

# The only two kinds an unauthenticated POST may ever record -- see module
# docstring. Every other member of events.EVENT_KINDS is refused with a 400.
# CTA_CLICK joined this allowlist 2026-09-10 for the same reason the other
# two are on it: it happens before any authenticated identity exists, so
# there is no server-side moment that could record it instead. It is
# rate-limited and property-validated identically, and its `properties`
# carry the CTA's own data-hook rather than anything the page can invent.
# PUBLIC_PAGE_VIEW joined 2026-10-01: outreach links point at the record page
# and the postseason page, not only landing.html, and those visits left no
# trace. Same reason as the others (no identity exists yet), same rate limit,
# same properties cap; its one extra rule is the `page` label check below.
PUBLIC_FUNNEL_KINDS = frozenset({
    events.LANDING_VIEW, events.SIGNUP_STARTED, events.CTA_CLICK,
    events.PUBLIC_PAGE_VIEW,
})

# `properties.page` of a public_page_view is a short fixed label the page
# itself chose ("record-card", "postseason"), never a URL or free text. A
# public caller that sends anything else is refused rather than stored, so the
# cardinality of that field stays bounded.
PAGE_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

# See module docstring's "WHY A FIXED SENTINEL id" section. Still the id of
# record for a beacon that carries no (or a malformed) `anon_id` -- an older
# cached page, a script -- so those rows stay countable exactly as before.
ANONYMOUS_FUNNEL_USER_ID = "anonymous-funnel-visitor"

# PER-VISITOR ANONYMOUS ID (2026-10-01). Every public funnel event used to hash
# to ONE id, so "distinct visitors" collapsed to 1 and nothing could say how
# many different people reached the signup form, or whether the one who did
# was the one who clicked a CTA. The browser now mints a random id once
# (web/js/attribution.js, localStorage), sends it as `anon_id` with every
# beacon, and the event is recorded under sha256("anon:<id>"). The id is
# random, carries nothing about the person, and is never joined to an email or
# an IP; it exists to count visitors, not to identify them.
ANON_ID_PREFIX = "anon:"

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
    # The browser's random per-visitor id; see ANON_ID_PREFIX.
    anon_id: Optional[str] = None


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
    if body.kind == events.PUBLIC_PAGE_VIEW:
        page = (properties or {}).get("page")
        if not isinstance(page, str) or not PAGE_LABEL_RE.match(page):
            raise HTTPException(status_code=400, detail={
                "error": "page_label_invalid",
                "message": "public_page_view needs properties.page, a short "
                           "label of lowercase letters, digits and hyphens "
                           "(at most 32 characters)"})
    anon_id = attribution_mod.clean_anon_id(body.anon_id)
    identity = f"{ANON_ID_PREFIX}{anon_id}" if anon_id else ANONYMOUS_FUNNEL_USER_ID
    events.record_event_safe(identity, body.kind, properties)
    return {"recorded": True}


# The ordered acquisition funnel, stage by stage. FREE_BET_CHECK sits where
# the product puts it -- a visitor tries the thing before deciding to sign
# up -- and SIGNUP_STARTED/ACCOUNT_CREATED are two rows, not one, since
# 2026-09-01 (see events.ACCOUNT_CREATED's own comment for why the merged
# version was actively wrong rather than merely coarse).
FUNNEL_STEPS: List[str] = [
    events.LANDING_VIEW,
    events.CTA_CLICK,
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
#
# CTA_CLICK is the same kind of branch: a count of button presses on the
# landing page, measured against landing views. It is a raw click count, so a
# visitor who presses two buttons is two clicks and the figure can pass 100%;
# `unique_visitors` on the step is the per-person number.
CONVERSION_BASELINE: Dict[str, str] = {
    events.SIGNUP_STARTED: events.LANDING_VIEW,
    events.CTA_CLICK: events.LANDING_VIEW,
    events.FREE_BET_CHECK: events.LANDING_VIEW,
}

# The label a step's events carry when they came with no utm_source -- a direct
# visit, an untagged link, or an event recorded before attribution existed.
DIRECT_SOURCE = "(direct)"
INVALID_SOURCE = "(invalid)"

# Steps whose events carry the visitor's anonymous id as their hashed user, so
# distinct hashes ARE distinct visitors. (The other steps are per-account.)
UNIQUE_VISITOR_STEPS = frozenset({
    events.LANDING_VIEW, events.CTA_CLICK, events.SIGNUP_STARTED,
})

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

# Kinds that get a COLUMN in `by_source` but are deliberately NOT steps of the
# main funnel. public_page_view is a raw count of record-page / postseason-page
# loads: it is where an outreach lead who never saw landing.html first shows
# up, but it is not a stage between landing_view and signup_started (nobody is
# "converting" from it), and listing it in FUNNEL_STEPS would add a row to the
# funnel table and shift every conversion_from neighbour. It is placed just
# after landing_view in by_source so the two arrival columns sit together.
SOURCE_ONLY_STEPS = (events.PUBLIC_PAGE_VIEW,)

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


def _source_of(event) -> str:
    """The event's utm_source as a short string, or "(direct)".

    The public beacon stores whatever `properties` it is sent (size-checked
    only), so this value is attacker-controlled. A nested object here used to
    become a dict key and turned GET /admin/funnel into a 500 for as long as
    the event stayed in the window. Anything that is not a plain string is
    filed under one fixed label instead."""
    value = (event.properties or {}).get("utm_source")
    if value is None or value == "":
        return DIRECT_SOURCE
    if not isinstance(value, str):
        return INVALID_SOURCE
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()[:64]
    return cleaned or DIRECT_SOURCE


def _window_events(start: str, end: str, *, db=None):
    return [e for e in events.list_events(db=db) if start <= e.at[:10] <= end]


def _unique_visitor_counts(start: str, end: str, *, db=None) -> Dict[str, int]:
    """Distinct visitor ids per public step, in range. A beacon without an
    anon_id shares the one sentinel hash, so every such event counts as one
    visitor in total -- the old collapse, now confined to clients that do not
    send the id instead of being the whole table."""
    seen: Dict[str, set] = {step: set() for step in UNIQUE_VISITOR_STEPS}
    for event in _window_events(start, end, db=db):
        if event.kind in seen:
            seen[event.kind].add(event.user_hash)
    return {kind: len(hashes) for kind, hashes in seen.items()}


def _counts_by_source(start: str, end: str, *, db=None) -> Dict[str, Dict[str, int]]:
    """utm_source -> {step: count} over the funnel steps, in range.

    Every step is attributed by the `utm_source` on its own event: the public
    beacons carry it from the landing page, `account_created`,
    `checkout_started` and `checkout_completed` carry the user's stored first
    touch (api/signup.py, src/appstate/billing.py). Events with none are
    "(direct)". First-occurrence steps (bet_check_run, bet_saved) and
    invite_redeemed carry no attribution and are left out rather than filed
    under "(direct)", which would make direct traffic look like it activates
    better than any campaign."""
    attributed = [step for step in FUNNEL_STEPS
                  if step not in FIRST_OCCURRENCE_STEPS
                  and step != events.INVITE_REDEEMED]
    landing_at = attributed.index(events.LANDING_VIEW) + 1
    attributed[landing_at:landing_at] = list(SOURCE_ONLY_STEPS)
    out: Dict[str, Dict[str, int]] = {}
    for event in _window_events(start, end, db=db):
        if event.kind not in attributed:
            continue
        slot = out.setdefault(_source_of(event), {step: 0 for step in attributed})
        slot[event.kind] += 1
    return dict(sorted(out.items(), key=lambda kv: (
        -kv[1].get(events.LANDING_VIEW, 0), -kv[1].get(events.PUBLIC_PAGE_VIEW, 0), kv[0])))


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
    uniques = _unique_visitor_counts(start, end)
    for step in steps_out:
        if step["kind"] in uniques:
            step["unique_visitors"] = uniques[step["kind"]]
    return {"start": start, "end": end, "steps": steps_out,
            "by_source": _counts_by_source(start, end)}
