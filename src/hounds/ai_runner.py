"""Run the AI hounds in the API process: one pass every 15 minutes, off unless ``AI_HOUNDS=on``.

    python -m src.hounds.ai_runner status        # what the admin panel shows, as JSON
    python -m src.hounds.ai_runner once          # one pass now (needs AI_HOUNDS=on, or --force)

WHERE THIS RUNS, AND WHY NOT IN THE CAPTURE SLOT. The house pack's rule hounds run in the capture slot
(``scripts/capture_slot.sh``, GitHub Actions) because they need only the stores. An AI hound needs an API key,
and the keys live on Fly (``docs/owner/AI_KEYS.md``), so the calls happen where the keys are: in the API
process, on the same 15-minute daemon-thread pattern the user hounds' engine uses (``user_runner``,
``api/app.py``), under the same one-build-at-a-time gate. The ledger therefore lives on the Fly volume beside
the app database (``ai_defs.ledger_path``), not in ``evidence/``, and the public reader is pointed at it
(``ledgers.Sources.default``) so the AI hounds sit in the same public race, graded the same way (units at the
board-average price, CLV against the close).

THE KILL SWITCH. ``AI_HOUNDS=on`` turns the loop on; anything else, or nothing, starts no thread and makes no
call. It is off by default and the production config leaves it off until the owner has set a key
(``docs/owner/AI_KEYS.md``). With the loop on but no provider usable (no key, a cap reached, cooling down),
every game that locks is a logged PASS, never a guess.

ONE PASS
--------
  1. the Eastern slate dates (today, and tomorrow late in the evening: ``user_runner.pass_dates``);
  2. the stores for those dates, loaded once under the build gate (a few days of odds, never the whole store),
     for every family the AI hounds cover: the catalog's dog menu, not only MLB and NFL;
  3. ``pack_run.run`` forward over the AI hounds: for every game whose lock has passed and whose start has not,
     each hound is asked once, the decision is logged, and an eligible bet is written with its provider and
     model (rules: ``pack_run`` docstring; -200 never, 3 a day, one per game);
  4. ``pack_settle.settle`` over the AI bets ledger: grade what is final, with the close and CLV. MLB and NFL
     from their result stores; every other family from the all-sports scores store (the Odds API ``/scores``
     for most, the free ESPN feeds for tennis and MMA), the same path the member dogs use.

Never replays: ``pack_run.run(replay=True)`` refuses a ``forward_only`` hound, and the CLI refuses ``--replay``.
Paper only. Nothing here can place a bet anywhere.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from src.hounds import ai_defs

logger = logging.getLogger("linehound.hounds.ai")

ENV_FLAG = "AI_HOUNDS"
ENV_INTERVAL = "AI_HOUNDS_INTERVAL_SECONDS"
DEFAULT_INTERVAL_SECONDS = 900.0          # 15 minutes: a game's 60-minute lock window gets four passes
MIN_INTERVAL_SECONDS = 60.0
WAIT_FOR_WARMUP_SECONDS = 600.0
STORE_LOOKBACK_DAYS = 3                   # odds rows loaded before the earliest slate date (open boards, closes)
ON_VALUES = ("on", "1", "true", "yes")

STATUS: dict = {"enabled": False, "passes": 0, "running": False, "last_pass_utc": None, "last_report": None,
                "last_error": None}


def enabled(env: Optional[Mapping] = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "").strip().lower() in ON_VALUES


def gematria_on(env: Optional[Mapping] = None) -> bool:
    """The Gematria Hound is in the pass unless ``GEMATRIA_HOUND=off`` (default ON in code)."""
    from src.hounds.gematria import runtime as gem_rt

    return gem_rt.enabled(env)


def loop_enabled(env: Optional[Mapping] = None) -> bool:
    """Whether the API process starts the loop: ``AI_HOUNDS=on`` (the AI hounds) or ``GEMATRIA_HOUND=on`` set explicitly.
    The Gematria Hound is on by default INSIDE a pass, but production only runs passes when the owner has switched one of
    the two on, so a laptop, a test client and staging start nothing."""
    from src.hounds.gematria import runtime as gem_rt

    return enabled(env) or gem_rt.explicitly_on(env)


def interval_seconds(env: Optional[Mapping] = None) -> float:
    source = env if env is not None else os.environ
    raw = str(source.get(ENV_INTERVAL) or "").strip()
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        return max(MIN_INTERVAL_SECONDS, float(raw))
    except ValueError:
        logger.warning("%s=%r is not a number; using %ss", ENV_INTERVAL, raw, DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_pass(*, now: Optional[datetime] = None, router=None, stores=None, ledger: Optional[str] = None,
             decisions: Optional[str] = None, news_fn=None, hounds_config: Optional[Path] = None,
             refresh_stats: Optional[Callable[[], object]] = None, settle: bool = True,
             gem_enabled: Optional[bool] = None) -> dict:
    """One pass. Returns a small report; raises nothing a caller must handle except a bug (the loop catches it).

    ``now``, ``router``, ``stores``, ``ledger``, ``decisions`` and ``news_fn`` are the injection points tests use;
    production leaves them unset."""
    from src.ai.router import default_router
    from src.appstate import freshness
    from src.hounds import pack_run, pack_settle, user_runner
    from src.hounds.gematria import runtime as gem_rt
    from src.hounds.pack import ai_hounds, base, gematria_hound
    from src.ledger.chain import HashChainLedger

    moment = now or _utcnow()
    router = router or default_router()
    ledger_file = ai_defs.ledger_path(ledger)
    report: dict = {"at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "paper_only": True, "forward_only": True,
                    "dates": [], "run": None, "settle": None, "wrote": 0}
    ai_on = bool(router.enabled_providers())
    gem_entry = ai_defs.entry_for(gematria_hound.HOUND_ID, hounds_config)
    gem_on = bool(gem_entry) and gem_entry.get("enabled") is not False and (gematria_on() if gem_enabled is None else gem_enabled)
    if not ai_on:
        report["skipped"] = "no AI provider is enabled (no key, or switched off in config/ai_providers.json)"
    if not ai_on and not gem_on and not Path(ledger_file).exists():
        return report
    with freshness._gated_build():
        dates = user_runner.pass_dates(moment)
        report["dates"] = dates
        if stores is None:
            since = max(base.SEAL_FLOOR, base.day_before(min(dates), STORE_LOOKBACK_DAYS))
            until = (date.fromisoformat(max(dates)) + timedelta(days=2)).isoformat()
            # Every family any enabled AI hound covers (the catalog's dog menu), not just MLB and NFL. The rule
            # hounds' own runs (capture slot) call load_stores with no list and still see MLB/NFL only.
            stores = base.load_stores(since=since, until=until, sports=ai_defs.all_sports(hounds_config) or None)
        hounds: list = []
        if ai_on:
            runtime = ai_hounds.AIRuntime(router, HashChainLedger(ai_defs.decisions_path(decisions)),
                                          now_fn=lambda: moment, news_fn=news_fn).bind(stores)
            hounds.extend(ai_hounds.build_hounds(runtime, hounds_config))
        if gem_on:
            # No model, no key, no cost: a fixed rule over the lock board and the stored results.
            gem_runtime = gem_rt.GematriaRuntime(ledger=HashChainLedger(gem_rt.decisions_path(ledger_file)),
                                                 now_fn=lambda: moment)
            hounds.append(gematria_hound.GematriaHound(gem_entry, gem_runtime))
        if not hounds:
            report["skipped"] = "no AI hound is enabled in config/ai_hounds.json"
        else:
            if gem_on:
                report["gematria"] = True
            counts = pack_run.run(stores, dates, replay=False, now=moment, path=ledger_file, hounds=hounds,
                                  out=lambda *_a, **_k: None)
            report["run"] = counts
            report["wrote"] += int(counts.get("written", 0))
        if settle and Path(ledger_file).exists():
            settled = pack_settle.settle(stores, now=moment, path=ledger_file)
            report["settle"] = settled
            report["wrote"] += int(settled.get("graded", 0))
    if report["wrote"]:
        if refresh_stats is None:
            from src.hounds import stats

            refresh_stats = stats.refresh_async
        refresh_stats()
    return report


def pass_safely(**kwargs) -> dict:
    """``run_pass`` that never raises: a failure is logged and recorded for the admin panel."""
    STATUS["running"] = True
    try:
        report = run_pass(**kwargs)
        STATUS["last_report"] = report
        STATUS["last_error"] = None
        logger.info("ai hounds pass: %s", report)
        return report
    except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad pass
        logger.exception("ai hounds pass failed")
        STATUS["last_error"] = repr(exc)
        return {"error": repr(exc)}
    finally:
        STATUS["running"] = False
        STATUS["passes"] += 1
        STATUS["last_pass_utc"] = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def start_loop(*, interval_s: Optional[float] = None, ready: Optional[Callable[[], bool]] = None,
               stop_event: Optional[threading.Event] = None, env: Optional[Mapping] = None,
               do_pass: Callable[[], object] = pass_safely) -> Optional[threading.Thread]:
    """Start the ONE daemon thread, or return None (starting nothing) unless ``AI_HOUNDS=on``."""
    if not loop_enabled(env):
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

    thread = threading.Thread(target=loop, daemon=True, name="ai-hounds")
    thread.start()
    logger.info("ai hounds loop started, interval=%ss", interval)
    return thread


# ---------------------------------------------------------------------------
# the admin panel
# ---------------------------------------------------------------------------

def _ledger_summary(ledger: Optional[str], decisions: Optional[str], today: str) -> dict:
    from src.hounds.pack_run import KIND_BET, KIND_GRADED
    from src.ledger.chain import HashChainLedger

    bets = graded = 0
    for row in HashChainLedger(ai_defs.ledger_path(ledger)).iter_rows():
        if row.get("kind") == KIND_BET:
            bets += 1
        elif row.get("kind") == KIND_GRADED:
            graded += 1
    by_code: dict = {}
    today_n = 0
    for row in HashChainLedger(ai_defs.decisions_path(decisions)).iter_rows():
        if row.get("kind") != "ai_decision":
            continue
        if str(row.get("written_utc") or "")[:10] == today:
            today_n += 1
            by_code[row.get("code")] = by_code.get(row.get("code"), 0) + 1
    return {"bets": bets, "graded": graded, "decisions_today": today_n, "decisions_today_by_code": by_code}


def build_status(*, router=None, env: Optional[Mapping] = None, ledger: Optional[str] = None,
                 decisions: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """What GET /admin/ai/status returns: the switch, each provider's state and today's usage, the month's paid
    spend against the cap, the last errors, the hounds, and the runner's last pass. No secret appears in it."""
    from src.ai.router import default_router

    router = router or default_router()
    source = env if env is not None else os.environ
    now = now or _utcnow()
    try:
        ledgers = _ledger_summary(ledger, decisions, now.date().isoformat())
    except Exception as exc:  # noqa: BLE001 -- a bad ledger must not hide the rest of the panel
        ledgers = {"error": repr(exc)}
    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "switch": {"env": ENV_FLAG, "value": str(source.get(ENV_FLAG) or "").strip().lower() or None,
                   "on": enabled(source), "interval_seconds": interval_seconds(source)},
        "router": router.status(),
        "runner": dict(STATUS),
        "hounds": [{"id": e["id"], "name": e.get("name"), "enabled": e.get("enabled") is not False,
                    "providers": e.get("providers")} for e in ai_defs.entries(include_parked=True)],
        "ledger": ledgers,
        "forward_only": True, "paper_only": True,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.ai_runner", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("status", "once"))
    ap.add_argument("--force", action="store_true", help="run `once` even when AI_HOUNDS is not on")
    ap.add_argument("--replay", action="store_true", help="refused: AI hounds are forward-only")
    args = ap.parse_args(argv)
    if args.replay:
        print(f"refused: {ai_defs.FORWARD_ONLY_MESSAGE}")
        return 2
    if args.command == "status":
        print(json.dumps(build_status(), indent=2, sort_keys=True))
        return 0
    if not (enabled() or args.force):
        print(f"{ENV_FLAG} is not on; nothing run (use --force to run one pass anyway)")
        return 0
    print(json.dumps(pass_safely(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
