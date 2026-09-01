"""api/betcheck.py: POST /betcheck -- the paid-beta core loop, as JSON.

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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.analysis import betcheck as betcheck_mod
from src.analysis import gamepayload
from src.appstate import ratelimit
from src.pipeline import briefing, history
from src.providers import mlb

router = APIRouter()

# No auth dependency guards this route (Bet Check is the unauthenticated
# paid-beta core loop today -- see the module docstring), so there is no
# user id to key on; the limiter falls back to the caller's IP.
# Thirty a minute is generous for one real customer typing bets one at a
# time and tight enough to blunt a scripted hammering of the one endpoint
# that runs the full domain path on every call.
BETCHECK_RATE_LIMIT_PER_MIN = 30
_betcheck_limiter = ratelimit.FixedWindowLimiter(
    limit=BETCHECK_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limited = ratelimit.limiter_dependency(_betcheck_limiter)

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


@router.post("/betcheck")
def post_betcheck(body: BetCheckRequest,
                  _rate_limit: None = Depends(_rate_limited)) -> dict:
    """Check one stated bet against the real domain path for its game.

    Unknown game is a structured 404 naming exactly what was searched for.
    A doubleheader -- the one case a date+club pair cannot disambiguate --
    checks the earlier-listed game and says so in a `note`, matching
    GET /game/{date}/{away}/{home}'s identical rule.
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
