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

import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

from src.analysis import gamepayload
from src.analysis import priceverdict
from src.appstate import events, freshness
from src.pipeline import briefing, history
from src.providers import mlb
from src.report import engine_bridge

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

# Red-team round: a malformed {date} path segment used to reach
# mlb.fetch_games unchecked, where src.providers.mlb's own _validate_date
# raised MLBError -- caught below as a 502, telling the client the SCHEDULE
# PROVIDER failed when the client's own input was the problem. Checking the
# shape here, before any network call, turns that into the 400 it always
# was; a well-formed date that the provider genuinely cannot serve still
# reaches the `except mlb.MLBError` below unchanged.
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
    _validate_date(date)
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


# The engine-bridge join reads the whole decisions ledger (~2.3 MB), the
# wagers ledger and the multi-book event index on every call -- about 400 ms,
# and it was being paid per request by BOTH `/opportunities/{date}` and every
# `/game/...` view (measured 2026-09-07). The result only changes when the
# slate runs, so it caches on the same terms as the entries above.
_engine_cache = freshness.SingleFlightTTLCache(ttl_s=ENTRIES_CACHE_TTL_S)


def engine_decisions_for_date(date: str) -> dict:
    """`engine_bridge.decisions_for_date`, cached per date and shared by
    every api/ caller. Returns an empty mapping rather than raising if the
    ledgers are unreadable -- the bridge already degrades that way and a
    missing engine join must never take a page down."""
    def _rebuild():
        return engine_bridge.decisions_for_date(date)

    try:
        value, _meta = _engine_cache.get(("engine_decisions", date), _rebuild)
    except Exception:  # noqa: BLE001 -- see docstring
        return {}
    return value


def _price_verdicts_for_entry(dossier, *, now: datetime) -> dict:
    """`{"away": PriceVerdict-dict, "home": PriceVerdict-dict}` from this
    game's own `price_improvement` board -- the same de-vigged-consensus-
    vs-best-price comparison `src.analysis.opportunities` builds for the
    Top Opportunities surface, computed here per game rather than joined
    from there. A side with no priceable quote (or a game with no board at
    all) gets `build_price_verdict`'s own INSUFFICIENT DATA dict, never an
    absent key.
    """
    section = dossier.get("price_improvement")
    sides = (section or {}).get("sides") or {}
    dispersion = (section or {}).get("dispersion") or {}
    books = dispersion.get("books")
    observed_utc = (section or {}).get("observed_utc")
    out = {}
    for side in ("away", "home"):
        detail = sides.get(side) or {}
        if (not section or section.get("skipped") or detail.get("skipped")
                or detail.get("best_price") is None):
            out[side] = priceverdict.build_price_verdict(
                american_price=None, consensus_probability=None,
                books=None, observed_utc=None, now=now)
            continue
        best_price = detail.get("best_price")
        best_book = detail.get("best_book")
        out[side] = priceverdict.build_price_verdict(
            american_price=best_price,
            consensus_probability=detail.get("consensus_probability"),
            books=books, observed_utc=observed_utc, now=now,
            best_price=best_price, best_book=best_book)
    return out


def _engine_summary_for_entry(dossier, date: str) -> Optional[dict]:
    """This game's `engine_bridge.summarize_game` rollup, or `None` when no
    engine decision joins to it -- never a zero-filled rollup standing in
    for "no data joined"."""
    game = dossier.game
    # Canonical abbreviations (ATH -> OAK, AZ -> ARI): the schedule and the
    # odds feed spell those clubs differently -- see engine_bridge.game_key.
    key = engine_bridge.game_key(game.get("away_team"), game.get("home_team"),
                                 game.get("date") or date)
    by_key = engine_decisions_for_date(date)
    summaries = by_key.get(key)
    return engine_bridge.summarize_game(summaries) if summaries else None


def _record_page_view(request: Optional[Request], route: str, date: str) -> None:
    """Analytics page_view on a successful GET, keyed to the caller
    api.auth.get_current_user already resolved and stashed on
    `request.state.user_id` -- the router-level auth dependency
    (api/app.py's `dependencies=_authed`) has always run by the time a
    route function's own body executes, so that attribute is set on any
    real, authenticated HTTP request that reaches here.

    `request` defaults to None (like api/auth.py's own `request` parameter)
    so every existing direct-call test in tests/test_api_games.py -- which
    calls these functions with positional args and no Request -- keeps
    working exactly as before, just unauthenticated-and-uninstrumented; only
    traffic through the real ASGI app carries a populated Request. Delegates
    to events.record_event_safe, so a broken events db costs a missing data
    point here too, never this response.
    """
    if request is None:
        return
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return
    events.record_event_safe(user_id, events.PAGE_VIEW,
                             {"route": route, "date": date})


@router.get("/games/{date}")
def get_games(date: str, request: Request = None) -> dict:
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
    _record_page_view(request, "/games/{date}", date)
    return payload


@router.get("/game/{date}/{away}/{home}")
def get_game(date: str, away: str, home: str, request: Request = None) -> dict:
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
        "engine": _engine_summary_for_entry(entry["dossier"], date),
        "price_verdicts": _price_verdicts_for_entry(entry["dossier"], now=now),
    }
    if len(matches) > 1:
        payload["note"] = (
            f"{len(matches)} games matched {away}@{home} on {date} (a "
            "doubleheader) -- this payload is the earlier-listed game; the "
            "URL scheme has no way to name the second one")
    _record_page_view(request, "/game/{date}/{away}/{home}", date)
    return payload


@router.get("/changed/{date}")
def get_changed(date: str, request: Request = None) -> dict:
    """The What Changed band for one date's whole slate."""
    entries, _, meta = _build_entries(date)
    payload = gamepayload.build_changed_items(entries, date=date)
    payload["freshness"] = meta
    _record_page_view(request, "/changed/{date}", date)
    return payload
