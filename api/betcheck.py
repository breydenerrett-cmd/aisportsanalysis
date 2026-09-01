"""api/betcheck.py: POST /betcheck (authed+paid) and POST /betcheck/free
(anonymous, lifetime-capped) -- the core loop, as JSON.

Same division of labour as api/games.py: the real domain path
(src.pipeline.briefing.build_slate) locates the game and produces its
findings and multi-book board; src.analysis.betcheck.build_contract turns
those into the fixed BetCheckContract skeleton
(docs/SAAS_APPLICATION_ARCHITECTURE.md section 4.13, src/analysis/contracts.py).
This file only fetches the day's schedule, matches the requested game, and
shapes the HTTP response. Unknown game (wrong date, wrong club pair, or a
date with no games) is a structured 404 naming exactly what was searched
for -- the same shape GET /game/{date}/{away}/{home} already uses for the
identical failure, so a client sees one error contract across every
game-scoped endpoint.

TWO ROUTES, ONE ANALYSIS
---------------------------
`POST /betcheck` is mounted with api/app.py's `_authed_paid` dependency (an
authenticated caller whose paid period has not lapsed, or an invite-token
beta user). `POST /betcheck/free` is mounted on its own router with NO auth
dependency at all, because the landing page's top-of-funnel offer -- three
introductory Bet Checks, no card -- cannot be honoured behind a login wall.
Both call the identical `_build_betcheck_payload`: the free tier is the
REAL Bet Check (mandatory counterargument lines, `recommendation`
permanently null, the same 400/404/502 contracts, the same honest
unavailability when the stores are empty), never a degraded preview. A
teaser here would be worse than no free tier at all -- the whole thing the
offer is meant to prove is what the product actually does.

What the free route adds on top is a lifetime budget of three, counted
server-side in src/appstate/freechecks.py against a server-minted anonymous
token; see that module for the identity design and, importantly, for what
it does and does not defend against.

DEV-ONLY, network-touching wiring lives here for the same reason it lives
in api/today.py and api/games.py: src.analysis.betcheck stays importable
and testable without FastAPI, without a store on disk, and without network
access. Nothing in src/ knows this file exists (tests/test_api_boundary.py
enforces the one-way boundary for all of src/).
"""

from __future__ import annotations

import json
import re
from typing import Literal
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.analysis import betcheck as betcheck_mod
from src.analysis import gamepayload
from src.appstate import events, freechecks, ratelimit
from src.pipeline import briefing, history
from src.providers import mlb

router = APIRouter()
# The free tier rides a SEPARATE router purely so api/app.py can mount it
# without the `_authed_paid` dependency the paid router carries -- a
# router-level dependency applies to every route on it, and there is no way
# to opt one route out.
free_router = APIRouter()

# POST /betcheck is mounted under api/app.py's `_authed_paid`, so the
# request does carry an authenticated user -- but the limiter here still
# keys on IP: it is constructed at import time with no `user_dependency`,
# and IP is the stricter fallback (an attacker with two tokens from one
# host shares one counter). Thirty a minute is generous for one real
# customer typing bets one at a time and tight enough to blunt a scripted
# hammering of the one endpoint that runs the full domain path on every call.
BETCHECK_RATE_LIMIT_PER_MIN = 30
_betcheck_limiter = ratelimit.FixedWindowLimiter(
    limit=BETCHECK_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limited = ratelimit.limiter_dependency(_betcheck_limiter)

# The free route is the one bet-check surface reachable with no credential
# of any kind, so its limiter is an order of magnitude tighter and hourly,
# not per-minute -- the same shape api/signup.py and api/support.py use for
# their own anonymous paths. Three lifetime checks means a genuine visitor
# needs at most a handful of requests ever; ten an hour per IP leaves room
# for retries and a couple of people behind one NAT while making it
# pointless to farm this route for odds data one game at a time.
FREE_BETCHECK_RATE_LIMIT_PER_HOUR = 10
_free_betcheck_limiter = ratelimit.FixedWindowLimiter(
    limit=FREE_BETCHECK_RATE_LIMIT_PER_HOUR, window_s=3600.0)
_free_rate_limited = ratelimit.limiter_dependency(_free_betcheck_limiter)

# The header a returning free visitor presents to be recognised as the same
# anonymous identity. The raw token also rides back in every free response's
# `free_check.token` so a static client (no cookie-setting backend) can hold
# and replay it -- see src/appstate/freechecks.py's identity design.
FREE_CHECK_TOKEN_HEADER = "X-Free-Check-Token"

# What a free check's analytics row is keyed on: the grant's token HASH,
# never the raw token (which is a live credential) and never a user id
# (there is no user). Prefixed so the value can never collide with a real
# user id passed to events.hash_user_id from any other call site.
FREE_CHECK_EVENT_IDENTITY_PREFIX = "free-check:"

# American odds below this magnitude are not a plausible moneyline price --
# a two- or one-digit number is almost certainly a mis-typed line or total,
# not a price, and Bet Check must refuse it as a bad request rather than
# price it anyway. The upper bound catches the same class of typo the other
# direction (an extra digit).
MIN_PLAUSIBLE_PRICE_MAGNITUDE = 100
MAX_PLAUSIBLE_PRICE_MAGNITUDE = 100000

# Club abbreviations/names are short by construction (three-letter codes up
# through a full club name); 40 is generous headroom over the longest real
# one while still refusing a client trying to stuff an arbitrary blob into
# a field that only ever needs to name a team. Reflected verbatim into a 404
# detail below, so bounding it here also bounds what that detail can grow to.
MAX_CLUB_NAME_LENGTH = 40

# Same shape check as api/games.py's _validate_date, kept as its own copy
# for the reason that module's docstring gives for the identical pattern in
# api/today.py: each api/ module owns its own tiny wiring rather than
# importing it from a sibling. A malformed date used to reach mlb.fetch_games
# unchecked and surface as an opaque 502 from the schedule provider's own
# validation; checked here, before any network call, it is the 400 it always
# was for a client input problem.
_ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _validate_date(date: str) -> None:
    if not isinstance(date, str) or not _ISO_DATE_RE.match(date):
        raise HTTPException(
            status_code=400,
            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}") from exc


class BetCheckRequest(BaseModel):
    """The validated shape of a Bet Check request.

    `side` is restricted to {away, home} at the schema level -- resolving a
    team NAME to a side is the client's (or a future lookup endpoint's) job,
    never something this module guesses at, same as the free-text parser in
    src.analysis.betcheck refuses to guess a team.
    """
    date: str
    away: str = Field(max_length=MAX_CLUB_NAME_LENGTH)
    home: str = Field(max_length=MAX_CLUB_NAME_LENGTH)
    side: Literal["away", "home"]
    american_price: int

    @field_validator("american_price")
    @classmethod
    def _sane_price(cls, value: int) -> int:
        magnitude = abs(value)
        if not (MIN_PLAUSIBLE_PRICE_MAGNITUDE <= magnitude
                <= MAX_PLAUSIBLE_PRICE_MAGNITUDE):
            raise ValueError(
                f"{value!r} is not a plausible American price (expected "
                "something like -125 or +140)")
        return value


def _fetch_entries(date: str) -> list:
    """Fetch one date's schedule and run it through the real domain path.

    Identical shape to api/games.py's `_build_entries`, kept as its own copy
    for the reason that module's docstring already gives for the same
    pattern in api/today.py: each api/ module owns its own tiny
    fetch-and-build wiring rather than importing it from a sibling.
    """
    _validate_date(date)
    try:
        games = mlb.fetch_games(date)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502,
                            detail=f"schedule unavailable for {date}: {exc}")
    store = history.read_results()
    slate = briefing.build_slate(games, store)
    return slate["games"]


def _build_betcheck_payload(body: BetCheckRequest) -> dict:
    """The Bet Check itself, identical for the paid and the free route.

    Unknown game is a structured 404 naming exactly what was searched for.
    A doubleheader -- the one case a date+club pair cannot disambiguate --
    checks the earlier-listed game and says so in a `note`, matching
    GET /game/{date}/{away}/{home}'s identical rule.

    Extracted from post_betcheck when the free tier landed, so there is
    exactly ONE definition of what a Bet Check is. A second, "lighter"
    builder for the free route is the thing this factoring exists to make
    impossible: the free three checks are the product's own promise of what
    it does, and a degraded version of them would be a lie told at the top
    of the funnel.
    """
    entries = _fetch_entries(body.date)
    matches = gamepayload.find_entries(entries, body.away, body.home)
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=(f"no game found for {body.away}@{body.home} on "
                    f"{body.date} -- checked {len(entries)} game(s) on that "
                    "date's schedule"))
    entry = matches[0]
    dossier = entry["dossier"]
    game = dossier.game
    try:
        contract = betcheck_mod.build_contract(
            body.date, body.away, body.home, body.side, body.american_price,
            board=dossier.get("multibook_board"),
            findings=entry.get("findings"),
            what_changed=(dossier.get("what_changed") or {}).get("events"),
            game_pk=game.get("game_pk"), game_number=game.get("game_number"),
            venue=game.get("venue"), start_time_utc=game.get("start_time_utc"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = json.loads(contract.to_json())
    if len(matches) > 1:
        payload["note"] = (
            f"{len(matches)} games matched {body.away}@{body.home} on "
            f"{body.date} (a doubleheader) -- this result checks the "
            "earlier-listed game; the request has no way to name the "
            "second one")
    return payload


@router.post("/betcheck")
def post_betcheck(body: BetCheckRequest, request: Request = None,
                  _rate_limit: None = Depends(_rate_limited)) -> dict:
    """Check one stated bet, for an authenticated paid/beta caller.

    Records a bet_check_run analytics event on success only (never on the
    404/400/502 paths `_build_betcheck_payload` raises -- those are not a
    completed check), keyed to `request.state.user_id` the same way
    api/games.py's `_record_page_view` reads it: the router-level auth
    dependency (api/app.py's `dependencies=_authed_paid`) has already
    resolved and stashed it by the time this function's body runs on a real
    request. `request` defaults to None so tests/test_api_betcheck.py's
    direct, positional-only calls keep working exactly as before.
    """
    payload = _build_betcheck_payload(body)
    if request is not None:
        user_id = getattr(request.state, "user_id", None)
        if user_id is not None:
            events.record_event_safe(user_id, events.BET_CHECK_RUN,
                                     {"date": body.date})
    return payload


def _free_check_block(raw_token: str, grant: freechecks.FreeCheckGrant) -> dict:
    """The `free_check` block every free response carries: the identity to
    replay, and the honest remaining count. `limit` rides along so a client
    can render "1 of 3 used" without hard-coding the offer."""
    return {"token": raw_token,
            "limit": freechecks.FREE_CHECK_LIFETIME_LIMIT,
            "used": grant.checks_used,
            "remaining": grant.remaining}


def _exhausted(raw_token: str) -> HTTPException:
    """The structured refusal a fourth free check gets: 402 Payment
    Required, which is literally what this is -- the visitor has spent the
    free tier and the next check costs money. Carries `remaining: 0` and
    the same token back, so the client keeps its identity (a client that
    dropped it and asked again would just be a new visitor with three fresh
    checks -- see src/appstate/freechecks.py on why that leak is accepted).
    """
    return HTTPException(status_code=402, detail={
        "error": "free_checks_exhausted",
        "remaining": 0,
        "limit": freechecks.FREE_CHECK_LIFETIME_LIMIT,
        "free_check_token": raw_token,
        "message": (
            f"you have used all {freechecks.FREE_CHECK_LIFETIME_LIMIT} "
            "introductory Bet Checks -- sign up at /signup to keep checking "
            "bets"),
    })


@free_router.post("/betcheck/free")
def post_betcheck_free(body: BetCheckRequest,
                       free_check_token: str = Header(
                           None, alias=FREE_CHECK_TOKEN_HEADER),
                       _rate_limit: None = Depends(_free_rate_limited)) -> dict:
    """The same Bet Check as POST /betcheck, for an anonymous visitor, three
    times in their life.

    ORDER MATTERS HERE, in two places. First: an already-exhausted identity
    is refused BEFORE any analysis runs, so a spent visitor cannot use this
    route to keep pulling the domain path. Second: the budget is spent only
    AFTER a successful payload -- a 400/404/502 (bad date, unknown game,
    schedule provider down) is not a Bet Check the visitor received, and
    charging one of their three for it would be taking something for
    nothing.

    A grant is also only MINTED once a check has actually succeeded, so a
    visitor whose first request 404s leaves no orphan row behind and no
    quietly-started budget.
    """
    # Not a str when FastAPI is bypassed (tests call this function directly
    # and get the Header() default object) -- normalise rather than trusting
    # the annotation, the same defensive shape `request: Request = None`
    # above already uses for direct calls.
    if not isinstance(free_check_token, str):
        free_check_token = None

    grant = freechecks.get_grant(free_check_token)
    if grant is not None and grant.exhausted:
        raise _exhausted(free_check_token)

    payload = _build_betcheck_payload(body)

    raw_token = free_check_token
    if grant is None:
        raw_token, grant = freechecks.issue_grant()
    spent = freechecks.consume_check(raw_token)
    if spent is None:
        # The budget went to zero between the check above and this write
        # (two concurrent requests on one token) -- freechecks.consume_check
        # makes that a None rather than a fourth check, and the caller gets
        # the same refusal they would have got a millisecond earlier.
        raise _exhausted(raw_token)

    events.record_event_safe(
        FREE_CHECK_EVENT_IDENTITY_PREFIX + spent.token_hash,
        events.FREE_BET_CHECK, {"date": body.date})
    payload["free_check"] = _free_check_block(raw_token, spent)
    return payload
