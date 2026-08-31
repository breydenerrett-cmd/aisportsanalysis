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
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src.analysis import gamepayload
from src.pipeline import briefing, history
from src.providers import mlb

router = APIRouter()


def _build_entries(date: str, **build_slate_kwargs) -> list:
    """Fetch one date's schedule and run it through the real domain path.

    Raises HTTPException(502) on an unreachable schedule provider -- the
    same structured-error shape api/today.py already uses for the identical
    failure, so a client sees one error contract across every endpoint.
    """
    try:
        games = mlb.fetch_games(date)
    except mlb.MLBError as exc:
        raise HTTPException(status_code=502,
                            detail=f"schedule unavailable for {date}: {exc}")
    store = history.read_results()
    slate = briefing.build_slate(games, store, **build_slate_kwargs)
    return slate["games"], slate.get("notes", [])


@router.get("/games/{date}")
def get_games(date: str) -> dict:
    """The slate list for one date: identity, first pitch, market-implied
    consensus, board summary and data-quality flags per game.

    A date with no games scheduled (an off day, or a date too far in the
    past/future for the provider to know about) is not an error -- it comes
    back as an honest empty slate, `checked_games: 0`, exactly like the
    zero-games case build_slate already handles for /today.
    """
    entries, notes = _build_entries(date)
    return gamepayload.build_slate_list(entries, date=date, notes=notes)


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
    entries, _ = _build_entries(date)
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
    entries, _ = _build_entries(date)
    return gamepayload.build_changed_items(entries, date=date)
