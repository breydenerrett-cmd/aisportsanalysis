"""The Odds tab: GET /odds/{date} (the whole slate's market board) and
GET /odds/{date}/{away}/{home} (one game's).

Same division of labour as api/games.py: this file fetches the schedule,
reads the multi-book store once, and hands both to
src.analysis.oddspayload's pure builders. Nothing here re-derives a price,
a consensus, or a spread that oddspayload/prices already computed.

DEV-ONLY, network-touching wiring lives here for the same reason it lives in
api/games.py and api/today.py: src.analysis.oddspayload stays importable and
testable without FastAPI, without a store on disk, and without network
access.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src.analysis import oddspayload
from src.analysis import prices as prices_mod
from src.providers import mlb

router = APIRouter()

# Same shape check as api/games.py's _validate_date, kept as its own copy
# per that module's rationale for the identical duplication in
# api/today.py: each api/ module owns its own tiny wiring. A malformed date
# used to reach mlb.fetch_games unchecked and surface as this module's own
# 502 -- a client-input problem told as a provider outage. Checked here,
# before any network call, it is the 400 it always was.
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


def _fetch_schedule(date: str) -> list:
    """One date's schedule, or a structured 502 on an unreachable provider --
    the same error contract api/games.py and api/today.py already use for the
    identical failure. A malformed date is refused as a 400 before this ever
    reaches the provider -- see _validate_date."""
    _validate_date(date)
    try:
        return mlb.fetch_games(date)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502,
                            detail=f"schedule unavailable for {date}: {exc}")


@router.get("/odds/{date}")
def get_odds(date: str) -> dict:
    """The whole slate's market board for one date: per game, per market,
    the full book board, best price, market-implied consensus, spread, and
    staleness -- plus a slate-level summary.

    A date with no games scheduled is not an error -- it comes back as an
    honest empty payload, `summary.games_count: 0`, the same rule
    api/games.py uses for /games/{date}.
    """
    games = _fetch_schedule(date)
    boards = prices_mod.boards_by_matchup()
    return oddspayload.build_odds_payload(games, boards, date=date,
                                          now=datetime.now(timezone.utc))


@router.get("/odds/{date}/{away}/{home}")
def get_odds_game(date: str, away: str, home: str) -> dict:
    """One game's odds payload.

    Unknown date/game is a structured 404, naming what was searched for
    rather than a bare framework error -- same shape as api/games.py's
    GET /game/{date}/{away}/{home}. A doubleheader -- the one case the
    away/home/date URL cannot disambiguate on its own -- returns the
    earlier-listed game and says so, rather than silently picking one with
    no signal that a second game exists.
    """
    games = _fetch_schedule(date)
    away_u, home_u = (away or "").upper(), (home or "").upper()
    matches = [g for g in games
              if (g.get("away_team") or "").upper() == away_u
              and (g.get("home_team") or "").upper() == home_u]
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=(f"no game found for {away}@{home} on {date} -- checked "
                    f"{len(games)} game(s) on that date's schedule"))
    boards = prices_mod.boards_by_matchup()
    now = datetime.now(timezone.utc)
    game = matches[0]
    key = prices_mod.matchup_key(game.get("away_team"), game.get("home_team"),
                                 game.get("date"))
    payload = oddspayload.build_game_odds(game, boards.get(key), now=now)
    if len(matches) > 1:
        payload["note"] = (
            f"{len(matches)} games matched {away}@{home} on {date} (a "
            "doubleheader) -- this payload is the earlier-listed game; the "
            "URL scheme has no way to name the second one")
    return payload
