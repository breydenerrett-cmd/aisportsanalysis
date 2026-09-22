"""Background cache warm-up for the paid-beta API's cold-cache routes.

THE PROBLEM, MEASURED ON STAGING 2026-09-21
--------------------------------------------
Every date-keyed cache in this app (src/appstate/freshness.py's
SingleFlightTTLCache, one per route -- see api/card.py, api/props.py,
api/tennis.py, api/odds.py, api/games.py, api/today.py) is empty on a cold
key: the schedule fetch, store reads and slate build all happen inline, on
the first request's thread, before anything is returned. Measured cold vs.
warm:

    /card/<today>                10.9s cold,  fast warm
    /card/<today>?sport=mma      13.5s cold (one run 502'd), 0.1s warm
    /props/<today>                12s  cold
    /tennis/board                 10s  cold
    /card/<today>?sport=nfl       3.3s cold
    /odds, /games                 ~0.15s (already fast)

The server restarts on every deploy (several a day) and every route's cache
key rolls to a new date at midnight, so the FIRST real visitor after either
event eats a 10-13s wait, or -- if the rebuild takes long enough to blow a
platform-level request timeout, as the mma card did once -- a 502. Auth
(api/auth.py's require_paid_access) means an HTTP self-request to warm these
routes would just get a 401, so the only way in is calling the underlying
cached builder functions directly, off the request path, the way this
module does.

WHAT THIS MODULE DOES
----------------------
On FastAPI startup, `start_background_warmup` starts ONE daemon thread
(never blocks startup or /health -- `thread.start()` returns immediately)
that calls `run_warmup_pass` immediately, then again every
WARM_INTERVAL_SECONDS (env-overridable, default 600; 0 or a non-positive
value disables warm-up entirely -- no thread is even started).

Each pass warms today's and tomorrow's date, in BOTH UTC and America/New_York
terms (deduped -- see `warm_dates`), for every route in `_default_items`:
the MLB, NFL and UFC/MMA card, /props, /tennis/board, /odds, /games and
/today. Each item is called through the SAME cached function its route
calls, so the route's own cache entry is what gets populated -- never a
parallel warm-only cache that could drift from what a real request sees.
api/card.py had no cache at all for `sport=nfl`; a small
SingleFlightTTLCache was added there (`_nfl_card_cache`, same class, same
120s TTL as every sibling cache) so this module has a real cache to warm,
same as api/card.py's existing `_mma_card_cache`.

Items run SEQUENTIALLY, not in parallel -- deliberately, to keep memory flat
on the 1-CPU, 512MB-1GB VM this deploys to (docs note the same constraint
behind SingleFlightTTLCache's serve-stale-with-flag design). A warm-up pass
paying full latency once per item, once per date, is the accepted cost; N
builders running at once, each holding their own store reads in memory, is
not.

FAILURE HANDLING: `run_warmup_pass` wraps every item in its own try/except
and logs one line (ok or failed) per (item, date). A single builder's
exception never stops the rest of the pass, never crashes the warm-up
thread, and never reaches the app -- there is no request to fail.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger("linehound.warmup")

ENV_WARM_INTERVAL_SECONDS = "WARM_INTERVAL_SECONDS"
DEFAULT_WARM_INTERVAL_SECONDS = 600.0

# One name per warm item, in the order `_default_items` returns them --
# exposed so a caller (or a test) can report the warm list without importing
# every api/* module this file lazily imports.
WARM_ITEM_NAMES = (
    "mlb_card", "nfl_card", "mma_card", "props", "tennis_board", "odds",
    "games", "today",
)

WarmBuilder = Callable[[str], None]
WarmItem = Tuple[str, WarmBuilder]


def _eastern():
    """MLB's official timezone; a fixed -04:00 when no zone database exists.

    Same fallback, same reasoning, as src/pipeline/prop_listing.py's
    `_eastern` -- this module needs "today" in the same date terms a
    baseball slate uses, and a machine with no tzdata package installed
    (this repo carries none as a dependency) must still produce a sane
    Eastern date rather than raise on every warm-up pass.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def warm_dates(now: Optional[datetime] = None) -> List[str]:
    """Today and tomorrow, in both UTC and America/New_York date terms,
    deduped and returned sorted.

    Four candidate dates collapse to two most of the year (UTC and Eastern
    agree on "today" for all but the evening hours the two zones disagree),
    and to three or four right around midnight in either zone -- exactly the
    rollover window this module exists to cover, so no de-duplication is
    skipped even though it usually does nothing.
    """
    now = (now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    utc_today = now.astimezone(timezone.utc).date()
    ny_today = now.astimezone(_EASTERN).date()
    dates = {
        utc_today, utc_today + timedelta(days=1),
        ny_today, ny_today + timedelta(days=1),
    }
    return sorted(d.isoformat() for d in dates)


def _default_items() -> List[WarmItem]:
    """The production warm list: one (name, builder) pair per route, each
    builder calling the exact cached function its route calls.

    Imported lazily (inside this function, not at module load) so importing
    api/warmup.py -- e.g. from a test that only wants `warm_dates` or
    `run_warmup_pass` with fake items -- never pulls in FastAPI, the
    providers or the pipeline. api/app.py already follows this "import
    heavy api/* wiring where it's used, not at module top" pattern (see
    api/card.py's inline `from src.report import nfl_card` etc.).
    """
    from api import card, games, odds, props, tennis
    from api import today as today_mod
    from src.pipeline import history
    from src.providers import mlb

    def warm_mlb_card(date: str) -> None:
        card.get_card_for_date(date, request=None, sport="mlb")

    def warm_nfl_card(date: str) -> None:
        card.get_card_for_date(date, request=None, sport="nfl")

    def warm_mma_card(date: str) -> None:
        card.get_card_for_date(date, request=None, sport="mma")

    def warm_props(date: str) -> None:
        # NOT api.props.get_props_for_date: its `limit` parameter defaults
        # to a FastAPI `Query(...)` sentinel object that only resolves to a
        # real int when the ASGI framework calls it. Calling it directly
        # would hand that sentinel to `props_mod.board_for_date(limit=...)`
        # instead of an int. `_board` is the actual cached function behind
        # the route -- calling it with the same default the route declares
        # (`props_mod.DEFAULT_LIMIT`) reaches the identical cache key a real
        # `GET /props/{date}` request (no `?limit=`) would.
        props._board(date, props.props_mod.DEFAULT_LIMIT)

    def warm_tennis(date: str) -> None:
        tennis.get_tennis_board(date=date)

    def warm_odds(date: str) -> None:
        odds.get_odds(date)

    def warm_games(date: str) -> None:
        games.get_games(date, request=None, sport="mlb")

    def warm_today(date: str) -> None:
        # The exact call api/app.py's `GET /today` makes (see its handler),
        # minus the Request object -- get_today_payload_cached only reads
        # `user_id` off it for an analytics event, which a warm-up pass is
        # not.
        today_mod.get_today_payload_cached(
            date, fetch_games=mlb.fetch_games, read_store=history.read_results)

    builders = (
        warm_mlb_card, warm_nfl_card, warm_mma_card, warm_props, warm_tennis,
        warm_odds, warm_games, warm_today,
    )
    return list(zip(WARM_ITEM_NAMES, builders))


def run_warmup_pass(items: Sequence[WarmItem], dates: Sequence[str], *,
                    log: logging.Logger = logger) -> None:
    """Run every (name, builder) in `items` for every date in `dates`,
    sequentially, each call wrapped so one failure never stops the rest.

    This is the function tests call with injected fake items/dates -- it
    does no threading, no sleeping, no env reads, and no imports of its
    own, so it is fast and deterministic to exercise directly.
    """
    for date in dates:
        for name, builder in items:
            try:
                builder(date)
            except Exception as exc:  # noqa: BLE001 -- a warm failure must
                # never crash the pass, the thread, or the app; there is no
                # request here for the exception to become a response to.
                log.warning("warmup item=%s date=%s failed: %r", name, date, exc)
            else:
                log.info("warmup item=%s date=%s ok", name, date)


def warm_interval_seconds(env: Optional[dict] = None) -> float:
    """WARM_INTERVAL_SECONDS from the environment (default 600.0). A blank,
    missing, or unparseable value falls back to the default rather than
    raising -- a warm-up misconfiguration must never be the thing that
    crashes startup. 0 or negative disables warm-up entirely; the caller
    (`start_background_warmup`) is the one that acts on that."""
    source = env if env is not None else os.environ
    raw = (source.get(ENV_WARM_INTERVAL_SECONDS) or "").strip()
    if not raw:
        return DEFAULT_WARM_INTERVAL_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "WARM_INTERVAL_SECONDS=%r is not a number; using default %ss",
            raw, DEFAULT_WARM_INTERVAL_SECONDS)
        return DEFAULT_WARM_INTERVAL_SECONDS


def _warmup_loop(*, items_factory: Callable[[], List[WarmItem]],
                 interval_s: float, stop_event: threading.Event,
                 dates_fn: Callable[[], List[str]] = warm_dates,
                 log: logging.Logger = logger) -> None:
    """The thread body: warm immediately, then every `interval_s` until
    `stop_event` is set. `stop_event.wait(interval_s)` is both the sleep and
    the shutdown signal -- it returns True (and the loop exits) the instant
    the event is set, rather than blocking a full interval past a shutdown
    request.

    `items_factory`/`dates_fn` are called fresh each pass (not captured
    once) so a date rollover mid-run is picked up by the very next pass
    without restarting the thread.
    """
    while not stop_event.is_set():
        try:
            items = items_factory()
            dates = dates_fn()
            run_warmup_pass(items, dates, log=log)
        except Exception:  # noqa: BLE001 -- the loop itself must outlive
            # any surprise here (e.g. items_factory's imports failing) --
            # log it and try again next interval rather than let the daemon
            # thread die silently.
            log.exception("warmup pass crashed")
        if stop_event.wait(interval_s):
            break


def start_background_warmup(*, interval_s: Optional[float] = None,
                            items_factory: Callable[[], List[WarmItem]] = _default_items,
                            stop_event: Optional[threading.Event] = None
                            ) -> Optional[threading.Thread]:
    """Start the one daemon warm-up thread. Called from api/app.py's
    FastAPI startup handler.

    Returns the started Thread, or None if warm-up is disabled
    (`interval_s <= 0`) -- in which case NO thread is created at all, per
    the WARM_INTERVAL_SECONDS=0-disables contract.

    `thread.start()` returns as soon as the OS has scheduled the thread; it
    does not wait for the first pass, so this function -- and therefore
    FastAPI startup -- never blocks on a rebuild.
    """
    resolved_interval = interval_s if interval_s is not None else warm_interval_seconds()
    if resolved_interval <= 0:
        logger.info("cache warm-up disabled (WARM_INTERVAL_SECONDS<=0)")
        return None
    event = stop_event if stop_event is not None else threading.Event()
    thread = threading.Thread(
        target=_warmup_loop,
        kwargs=dict(items_factory=items_factory, interval_s=resolved_interval,
                   stop_event=event),
        daemon=True, name="cache-warmup")
    thread.start()
    logger.info("cache warm-up thread started, interval=%ss", resolved_interval)
    return thread
