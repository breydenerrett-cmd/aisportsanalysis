"""The game-level API vertical slice: slate list, one game's quick and
advanced views, and the What Changed band.

Same division of labour as api/today.py: the real domain path
(src.pipeline.briefing.build_slate) does every computation, and the
functions here only fetch inputs, run the domain path once, and hand the
resulting entries to src.analysis.gamepayload's pure builders. Nothing in
this file re-derives a number the domain layer already computed.

DEV-ONLY, network-touching wiring lives here for the same reason it lives in
api/today.py: src.analysis.gamepayload stays importable and testable without
FastAPI, without a store on disk, and without network access.

CACHING: all three endpoints below share one expensive step -- fetch the
day's schedule, then run it through build_slate. `_build_entries` caches
that shared step per date (src/appstate/freshness.py, ~120s TTL,
single-flight) so three back-to-back requests for the same date (e.g. a
client loading /games/{date} then /changed/{date}) rebuild once, not three
times. The cache sits inside `_build_entries` itself -- every endpoint
already funnels through it -- so no endpoint function below needed to
change to pick up caching; only their response shapes gained the additive
`freshness` key documented on each route.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException

from src.analysis import gamepayload
from src.appstate import freshness
from src.pipeline import briefing, history
from src.providers import mlb

router = APIRouter()

# Same rationale as api/today.py's TODAY_CACHE_TTL_S: long enough to
# absorb a burst of requests for one date, short enough that nobody sees a
# slate more than two minutes stale by cache age alone.
ENTRIES_CACHE_TTL_S = 120.0

# One cache shared by all three routes below, keyed by date -- they all
# want the identical (entries, notes) pair, so caching it once here covers
# get_games, get_game, and get_changed together rather than each keeping
# its own copy.
_entries_cache = freshness.SingleFlightTTLCache(ttl_s=ENTRIES_CACHE_TTL_S)


def _newest_entries_odds_observed_utc(entries_and_notes: Tuple[list, list]
                                      ) -> Optional[str]:
    """The freshest board `observed_utc` across a built entries list, or
    None if no entry carries a priced board -- mirrors
    api/today.py's _newest_odds_observed_utc, but reads the raw entry
    dicts (Dossier objects, pre-serialisation) these routes deal in rather
    than the already-serialised odds_meta today.py produces.
    """
    entries, _notes = entries_and_notes
    observed = []
    for entry in entries:
        dossier = entry.get("dossier")
        if dossier is None:
            continue
        board = dossier.get("price_improvement") or dossier.get("multibook_board")
        ts = (board or {}).get("observed_utc")
        if ts:
            observed.append(ts)
    return max(observed) if observed else None


def _build_entries(date: str, **build_slate_kwargs) -> list:
    """One date's (entries, notes), from cache when available.

    Raises HTTPException(502) on an unreachable schedule provider -- the
    same structured-error shape api/today.py already uses for the identical
    failure, so a client sees one error contract across every endpoint.
    This still holds with caching in front: freshness.SingleFlightTTLCache
    re-raises the original exception untouched when there is no prior
    successful build to fall back on (see its docstring), so a cold-cache
    provider failure reaches this `except` exactly as it did before caching
    existed. Only a failure *after* a good build exists is absorbed into a
    stale-flagged replay instead of a 502 -- see get_games/get_game/
    get_changed for how the `freshness` metadata surfaces that to callers.
    """
    key = ("games_entries", date)

    def _rebuild():
        games = mlb.fetch_games(date)
        store = history.read_results()
        slate = briefing.build_slate(games, store, **build_slate_kwargs)
        return slate["games"], slate.get("notes", [])

    try:
        (entries, notes), meta = _entries_cache.get(
            key, _rebuild,
            odds_observed_extractor=_newest_entries_odds_observed_utc)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502,
                            detail=f"schedule unavailable for {date}: {exc}")
    return entries, notes, meta


@router.get("/games/{date}")
def get_games(date: str) -> dict:
    """The slate list for one date: identity, first pitch, market-implied
    consensus, board summary and data-quality flags per game.

    A date with no games scheduled (an off day, or a date too far in the
    past/future for the provider to know about) is not an error -- it comes
    back as an honest empty slate, `checked_games: 0`, exactly like the
    zero-games case build_slate already handles for /today.
    """
    entries, notes, meta = _build_entries(date)
    payload = gamepayload.build_slate_list(entries, date=date, notes=notes)
    payload["freshness"] = meta
    return payload


@router.get("/game/{date}/{away}/{home}")
def get_game(date: str, away: str, home: str) -> dict:
    """One game's quick view (top findings, price) and advanced view (every
    dossier section, verbatim) together.

    Unknown date/game is a structured 404, naming what was searched for
    rather than a bare framework error. A doubleheader -- the one case the
    away/home/date URL cannot disambiguate on its own -- returns the
    earlier-listed game and says so, rather than silently picking one with
    no signal that a second game exists.
    """
    entries, _, meta = _build_entries(date)
    matches = gamepayload.find_entries(entries, away, home)
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=(f"no game found for {away}@{home} on {date} -- checked "
                    f"{len(entries)} game(s) on that date's schedule"))
    now = datetime.now(timezone.utc)
    entry = matches[0]
    payload = {
        "quick": gamepayload.build_quick_view(entry, now=now),
        "advanced": gamepayload.build_advanced_view(entry, now=now),
        "freshness": meta,
    }
    if len(matches) > 1:
        payload["note"] = (
            f"{len(matches)} games matched {away}@{home} on {date} (a "
            "doubleheader) -- this payload is the earlier-listed game; the "
            "URL scheme has no way to name the second one")
    return payload


@router.get("/changed/{date}")
def get_changed(date: str) -> dict:
    """The What Changed band for one date's whole slate."""
    entries, _, meta = _build_entries(date)
    payload = gamepayload.build_changed_items(entries, date=date)
    payload["freshness"] = meta
    return payload
