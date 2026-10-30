"""The in-process loop that keeps the live NHL and tennis state fresh (the ``src/sports/live_feed.py`` pattern).

ONE daemon thread started from api/app.py. Every ``INTERVAL_SECONDS`` (30) a pass runs:

  * NHL: the day's score read (one request), then the boxscore and play-by-play of the live games that are due (see
    nhl.py for the cadence and the per-pass request cap). When nothing is live and nothing starts within 25 minutes the next
    NHL pass waits five minutes instead of thirty seconds;
  * tennis: the ATP and WTA scoreboards, but ONLY while the board has a tennis match in play or inside its read window
    (tennis.needed): there is always some tennis on, and a pass nobody reads is a request for nothing;
  * the snapshot log: every live game whose signature changed since it was last logged gets one line (store.log_change).

A pass is bounded: the request caps in nhl.py and tennis.py, and ``PASS_BUDGET_SECONDS`` of wall clock after which no more
detail reads start (a slow API must not stretch a pass into the next one). A pass never raises out of the loop.

No Odds API call is made anywhere in this package and no credit is spent; no bet is placed or implied. ``LIVE_STATE=off``
disables everything, and the loop never starts under pytest (a test that wants a pass calls ``run_pass`` with its own
``fetch_json`` and clock).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from src.hounds import live_scores as ls
from src.sports import live_feed
from src.sports.live_state import nhl, store, tennis

logger = logging.getLogger("linehound.sports.live_state")

ENV_FLAG = "LIVE_STATE"
INTERVAL_SECONDS = 30.0
WAIT_FOR_WARMUP_SECONDS = 600.0
PASS_BUDGET_SECONDS = 25.0
OFF_VALUES = ("off", "0", "false", "no")

_SCHEDULE: dict = {"NHL": None}          # the earliest time the next NHL pass may run


def enabled(env: Optional[Mapping] = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "on").strip().lower() not in OFF_VALUES


def reset_schedule() -> None:
    _SCHEDULE["NHL"] = None


def log_changes(now: datetime, directory: Optional[Path] = None) -> int:
    """Append a snapshot line for every live game whose signature changed. Returns how many lines were written."""
    written = 0
    for sport, module in (("NHL", nhl), ("TENNIS", tennis)):
        for view in store.fresh_games(sport, now):
            row = module.log_row(view)
            if store.log_change(sport, view["game_id"], row, module.signature(row), now, directory=directory,
                                seen_live=module.is_live_row):
                written += 1
    return written


def run_pass(events_provider: Callable[[], Iterable[Mapping]], *, now: Optional[datetime] = None,
             fetch_json: Optional[Callable[[str], dict]] = None, log_dir: Optional[Path] = None,
             schedule: Optional[dict] = None, memory: Optional[tennis.ServerMemory] = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    fetch = fetch_json or live_feed.default_fetch_json
    sched = schedule if schedule is not None else _SCHEDULE
    began = time.monotonic()

    def budget_left() -> bool:
        return time.monotonic() - began < PASS_BUDGET_SECONDS

    report: dict = {}
    due = sched.get("NHL")
    if due is None or moment >= due:
        rep = nhl.fetch_and_store(moment, fetch, budget_left=budget_left)
        report["nhl"] = rep
        quiet = not rep["active"] and not rep["error"]
        sched["NHL"] = moment + timedelta(seconds=nhl.IDLE_EVERY_SECONDS if quiet else nhl.SCORE_EVERY_SECONDS)
        if rep["error"]:
            store.STATUS["last_error"] = f"nhl: {rep['error']}"
    try:
        events = list(events_provider() or [])
    except Exception as exc:  # noqa: BLE001 -- no board events means no tennis read this pass, not a dead loop
        events = []
        store.STATUS["last_error"] = f"events: {type(exc).__name__}"
    if tennis.needed(events, moment) and budget_left():
        rep = tennis.fetch_and_store(moment, fetch, memory=memory or tennis.MEMORY)
        report["tennis"] = rep
        if rep["error"]:
            store.STATUS["last_error"] = f"tennis: {rep['error']}"
    report["logged"] = log_changes(moment, log_dir)
    store.prune(moment)
    store.STATUS["passes"] += 1
    store.STATUS["last_pass_utc"] = ls.iso(moment)
    return report


def start_loop(events_provider: Callable[[], Iterable[Mapping]], *, interval_s: float = INTERVAL_SECONDS,
               ready: Optional[Callable[[], bool]] = None, stop_event: Optional[threading.Event] = None,
               env: Optional[Mapping] = None, fetch_json: Optional[Callable[[str], dict]] = None,
               log_dir: Optional[Path] = None) -> Optional[threading.Thread]:
    """ONE daemon thread, or None when LIVE_STATE=off or under pytest. A pass never raises out of the loop."""
    if not enabled(env) or (env is None and os.environ.get("PYTEST_CURRENT_TEST")):
        return None
    event = stop_event if stop_event is not None else threading.Event()
    store.STATUS["enabled"] = True

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < WAIT_FOR_WARMUP_SECONDS:
            if event.wait(5.0):
                return
            waited += 5.0
        while not event.is_set():
            try:
                run_pass(events_provider, fetch_json=fetch_json, log_dir=log_dir)
            except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad pass
                store.STATUS["last_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                logger.exception("live state pass failed")
            if event.wait(interval_s):
                return

    thread = threading.Thread(target=loop, daemon=True, name="live-state")
    thread.start()
    return thread
