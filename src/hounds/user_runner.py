"""One pass of the user-hound engine, run inside the API process.

WHERE USER HOUNDS RUN (decision 2026-10-18, reversible: unset ``HOUNDS_ENGINE``)
------------------------------------------------------------------------------
The capture slot runs in GitHub Actions and has no app database. The hounds users build live in the
production app database on the Fly volume. So the engine runs where the database is: a lightweight
loop in the API process (``api/hounds_engine.py``) that every 15 minutes calls ``run_pass``:

  1. read the RUNNING hounds from the app database (nothing to do when there are none, and then
     the odds store is not touched at all);
  2. ``user_engine.run`` for today's Eastern slate date (and tomorrow's after 20:00 Eastern, so a
     game that starts just after midnight is not missed), against this server's own odds store;
  3. ``user_settle.settle`` for the last ``SETTLE_LOOKBACK_DAYS`` days, against the results store the
     cards use;
  4. if either wrote a row, start one background rebuild of the public stats.

The ledger is written to ``user_engine.ledger_path()``: beside the app database, on the persistent
volume, not in ``evidence/`` (a git-tracked directory baked into the image).

ONE AT A TIME, AND SMALL
------------------------
The pass holds the process-wide build gate (``src.appstate.freshness``), the same one every page
cache build and the hounds' own stats build take, so it is never the second heavy thing running on
the 1 GB machine. It streams the odds store a row at a time (``user_engine.iter_rows``), keeps only
the games of one slate and only the fields the engine reads (``user_engine.build_games``), and holds
no other store whole. ``tests/test_hounds_integration.py`` measures the peak against the real store.

IDEMPOTENT. Re-running a pass, running it late, or two machines running it adds nothing a first run
would not have written: a bet's id is a hash of (hound, game, market) and a board is fixed at the
lock instant (``user_engine`` docstring).

Nothing here talks to a book or suggests a wager. Paper only.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional

logger = logging.getLogger("linehound.hounds.engine")

ENV_FLAG = "HOUNDS_ENGINE"
ENV_INTERVAL = "HOUNDS_ENGINE_INTERVAL_SECONDS"
DEFAULT_INTERVAL_SECONDS = 900.0          # 15 minutes: the capture slot's own cadence near a start
MIN_INTERVAL_SECONDS = 30.0               # a typo must not make this a hot loop
SETTLE_LOOKBACK_DAYS = 14                 # user_settle.DEFAULT_LOOKBACK_DAYS
LATE_EVENING_ET_HOUR = 20                 # from here on, tomorrow's slate can already be locking
WAIT_FOR_WARMUP_SECONDS = 600.0           # never wait longer than this for the cache warm-up

ON_VALUES = ("on", "1", "true", "yes")

STATUS: dict = {"enabled": False, "passes": 0, "running": False, "last_pass_utc": None,
                "last_report": None, "last_error": None}


def enabled(env: Optional[Mapping] = None) -> bool:
    """``HOUNDS_ENGINE=on`` turns the loop on. Anything else, or nothing, leaves it off: a server
    that has not been told to run the engine never starts a thread."""
    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "").strip().lower() in ON_VALUES


def interval_seconds(env: Optional[Mapping] = None) -> float:
    source = env if env is not None else os.environ
    raw = str(source.get(ENV_INTERVAL) or "").strip()
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        return max(MIN_INTERVAL_SECONDS, float(raw))
    except ValueError:
        logger.warning("%s=%r is not a number; using %ss", ENV_INTERVAL, raw,
                       DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def pass_dates(now: datetime) -> list:
    """The Eastern slate dates a pass at ``now`` should run: today, plus tomorrow late in the evening."""
    from src.pipeline import snapshots
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = snapshots.official_date(stamp)
    eastern_hour = int(now.astimezone(snapshots._EASTERN).hour)
    dates = [today]
    if eastern_hour >= LATE_EVENING_ET_HOUR:
        dates.append(snapshots.official_date(
            (now + timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    return dates


def run_pass(*, now: Optional[datetime] = None, ledger: Optional[str] = None,
             multibook_path: Optional[str] = None, hounds: Optional[list] = None,
             settle_kwargs: Optional[dict] = None,
             refresh_stats: Optional[Callable[[], object]] = None) -> dict:
    """One engine-and-settle pass. Returns a small report; raises nothing a caller must handle
    except a bug (the loop catches and logs it).

    ``now`` fixes the clock for the engine's lock checks (tests and the local end-to-end run);
    production leaves it unset. ``hounds`` / ``ledger`` / ``multibook_path`` / ``settle_kwargs`` are
    the injection points for the same reason."""
    from src.appstate import freshness
    from src.hounds import stats, user_engine, user_settle, user_store

    moment = now or _utcnow()
    running = user_store.list_running() if hounds is None else hounds
    report: dict = {"at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "running_hounds": len(running),
                    "engine": [], "settle": None, "wrote": 0, "paper_only": True}
    if not running:
        report["skipped"] = "no running hounds"
        return report

    with freshness._gated_build():
        sports = {s for h in running for s in h["spec"]["sports"]}
        index = user_engine._load_game_pk_index()
        for date in pass_dates(moment):
            rows = user_engine.iter_rows(date, sports, multibook_path=multibook_path)
            out = user_engine.run(date, running, rows, ledger=ledger, now=now,
                                  mode="live", game_pk_index=index)
            report["engine"].append({k: out[k] for k in ("date", "games_seen", "bets_written",
                                                        "skipped")})
            report["wrote"] += out["bets_written"]
        kwargs = dict(settle_kwargs or {})
        kwargs.setdefault("lookback_days", SETTLE_LOOKBACK_DAYS)
        if "postponed_lookup" not in kwargs:
            kwargs["postponed_lookup"] = _postponed_lookup()
        settled = user_settle.settle(ledger=ledger, now=moment, **kwargs)
        report["settle"] = {k: settled[k] for k in ("considered", "graded", "pending")}
        report["wrote"] += settled["graded"]
    if report["wrote"]:
        (refresh_stats or stats.refresh_async)()
    return report


def _postponed_lookup():
    """The schedule lookup for a postponed game (one call per pending bet, only after a long wait)."""
    try:
        from src.pipeline import history
        return lambda pk, day: history.postponed_makeup(pk, day)
    except Exception:  # noqa: BLE001 -- no lookup leaves postponed games pending, never an error
        return None


def pass_safely(**kwargs) -> dict:
    """``run_pass`` that never raises: a failure is logged and recorded for /health."""
    STATUS["running"] = True
    try:
        report = run_pass(**kwargs)
        STATUS["last_report"] = report
        STATUS["last_error"] = None
        logger.info("hounds engine pass: %s", report)
        return report
    except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad pass
        logger.exception("hounds engine pass failed")
        STATUS["last_error"] = repr(exc)
        return {"error": repr(exc)}
    finally:
        STATUS["running"] = False
        STATUS["passes"] += 1
        STATUS["last_pass_utc"] = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def status() -> dict:
    return dict(STATUS)


def start_loop(*, interval_s: Optional[float] = None, ready: Optional[Callable[[], bool]] = None,
               stop_event: Optional[threading.Event] = None,
               env: Optional[Mapping] = None,
               do_pass: Callable[[], object] = pass_safely) -> Optional[threading.Thread]:
    """Start the ONE daemon thread, or return None (starting nothing) unless ``HOUNDS_ENGINE=on``.

    The thread waits for ``ready()`` (the app's first cache warm-up pass, so the two never compete
    on a cold 1 GB machine), runs a pass, then sleeps ``interval_s`` between passes. Passes are
    sequential by construction: one thread, and the build gate inside ``run_pass``."""
    if not enabled(env):
        return None
    interval = interval_s if interval_s is not None else interval_seconds(env)
    event = stop_event if stop_event is not None else threading.Event()
    STATUS["enabled"] = True

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < WAIT_FOR_WARMUP_SECONDS:
            if event.wait(5.0):
                return
            waited += 5.0
        while not event.is_set():
            do_pass()
            if event.wait(interval):
                return

    thread = threading.Thread(target=loop, daemon=True, name="hounds-engine")
    thread.start()
    logger.info("hounds engine loop started, interval=%ss", interval)
    return thread
