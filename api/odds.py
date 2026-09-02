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

CACHING: both routes below share the same two I/O calls -- fetch the day's
schedule, then read the multi-book price store. `_build_odds_inputs` caches
that shared (schedule, boards) pair per date (src/appstate/freshness.py),
exactly mirroring api/games.py's `_build_entries`: same TTL, same
single-flight rebuild, same serve-stale-with-flag semantics, same additive
`freshness` key on the response. Only the RAW inputs are cached, never the
built payload -- oddspayload.build_odds_payload/build_game_odds still runs
fresh against a live `now` on every request, so a cache hit never freezes a
board's `age_seconds` or the payload's `generated_at` at whatever instant
the cache entry was built.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException

from src.analysis import oddspayload
from src.analysis import prices as prices_mod
from src.appstate import freshness
from src.providers import mlb

router = APIRouter()

# Same shape check as api/games.py's _validate_date, kept as its own copy
# per that module's rationale for the identical duplication in
# api/today.py: each api/ module owns its own tiny wiring. A malformed date
# used to reach mlb.fetch_games unchecked and surface as this module's own
# 502 -- a client-input problem told as a provider outage. Checked here,
# before any network call, it is the 400 it always was.
_ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Same value and same rationale as api/games.py's ENTRIES_CACHE_TTL_S: long
# enough to absorb a burst of requests for one date, short enough that
# nobody sees a board more than two minutes stale by cache age alone. This
# is independent of FreshnessPolicy's own odds-age check on a board's
# `observed_utc` (DEFAULT_ODDS_MAX_AGE_S, 30 minutes) -- that one flags the
# DATA as stale; this TTL only bounds how long the CACHE ENTRY lives.
ODDS_CACHE_TTL_S = 120.0

# One cache shared by both routes below, keyed by date -- GET /odds/{date}
# and GET /odds/{date}/{away}/{home} both want the identical (games, boards)
# pair, so caching it once here covers both instead of each paying for its
# own schedule fetch and board-store read.
_odds_cache = freshness.SingleFlightTTLCache(ttl_s=ODDS_CACHE_TTL_S)


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


def _newest_boards_odds_observed_utc(games_and_boards: Tuple[list, dict]
                                     ) -> Optional[str]:
    """The freshest board `observed_utc` across a cached (games, boards)
    pair, or None if no board carries one -- feeds
    freshness.SingleFlightTTLCache's odds-age staleness check the same way
    api/games.py's `_newest_entries_odds_observed_utc` does for its own
    cached value, just reading `boards` (prices.boards_by_matchup's raw
    dict-of-boards shape) instead of already-built Dossier entries.
    """
    _games, boards = games_and_boards
    observed = [board.get("observed_utc") for board in boards.values()
                if board and board.get("observed_utc")]
    return max(observed) if observed else None


def _build_odds_inputs(date: str) -> Tuple[list, dict, dict]:
    """One date's (games, boards, freshness_meta), from cache when
    available.

    Mirrors api/games.py's `_build_entries`: caches the two I/O calls this
    route pays for (the schedule fetch and the multi-book store read), not
    the built payload -- see this module's CACHING docstring section.

    Raises HTTPException(502) on an unreachable schedule provider -- the
    same structured-error shape api/games.py already uses for the identical
    failure. This still holds with caching in front: SingleFlightTTLCache
    re-raises the original exception untouched when there is no prior
    successful build to fall back on (see its docstring), so a cold-cache
    provider failure reaches this `except` exactly as it did before caching
    existed. Only a failure *after* a good build exists is absorbed into a
    stale-flagged replay instead of a 502 -- surfaced via the `freshness`
    key both routes attach to their payload. A malformed date is refused as
    a 400 before this ever reaches the cache or the provider -- see
    _validate_date.
    """
    _validate_date(date)
    key = ("odds_inputs", date)

    def _rebuild():
        games = mlb.fetch_games(date)
        boards = prices_mod.boards_by_matchup()
        return games, boards

    try:
        (games, boards), meta = _odds_cache.get(
            key, _rebuild,
            odds_observed_extractor=_newest_boards_odds_observed_utc)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502,
                            detail=f"schedule unavailable for {date}: {exc}")
    return games, boards, meta


@router.get("/odds/{date}")
def get_odds(date: str) -> dict:
    """The whole slate's market board for one date: per game, per market,
    the full book board, best price, market-implied consensus, spread, and
    staleness -- plus a slate-level summary.

    A date with no games scheduled is not an error -- it comes back as an
    honest empty payload, `summary.games_count: 0`, the same rule
    api/games.py uses for /games/{date}.
    """
    games, boards, meta = _build_odds_inputs(date)
    payload = oddspayload.build_odds_payload(games, boards, date=date,
                                             now=datetime.now(timezone.utc))
    payload["freshness"] = meta
    return payload


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
    games, boards, meta = _build_odds_inputs(date)
    away_u, home_u = (away or "").upper(), (home or "").upper()
    matches = [g for g in games
              if (g.get("away_team") or "").upper() == away_u
              and (g.get("home_team") or "").upper() == home_u]
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=(f"no game found for {away}@{home} on {date} -- checked "
                    f"{len(games)} game(s) on that date's schedule"))
    now = datetime.now(timezone.utc)
    game = matches[0]
    key = prices_mod.matchup_key(game.get("away_team"), game.get("home_team"),
                                 game.get("date"))
    payload = oddspayload.build_game_odds(game, boards.get(key), now=now)
    payload["freshness"] = meta
    if len(matches) > 1:
        payload["note"] = (
            f"{len(matches)} games matched {away}@{home} on {date} (a "
            "doubleheader) -- this payload is the earlier-listed game; the "
            "URL scheme has no way to name the second one")
    return payload
