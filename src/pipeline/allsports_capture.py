"""All-sports capture: pre-game and in-play prices for every sport The Odds API is pricing.

WHY THIS EXISTS
---------------
User-built dogs bet only MLB and NFL because those were the only sports whose odds the program stored.
The owner wants a dog to be able to bet ANY sport The Odds API prices, overnight and live ones included
(tennis, cricket, soccer, NBA, NHL, college football, Euroleague ...). This module buys those prices and
writes them into the SAME multibook store MLB and NFL rows live in, in the same row shape, so
`user_engine.load_rows/iter_rows` and `snapshots.window_for_date` read them unchanged.

WHAT ONE RUN DOES (one tick of the scheduled capture, like nfl_capture / tennis_capture)
----------------------------------------------------------------------------------------
 1. DISCOVER (free). `fetch_sports(all_sports=True)` lists every sport key; the active, non-outright keys
    whose family is bought by this module are kept (MLB, NFL and MMA are bought by their own pipelines and
    are skipped; outrights and futures have no home and away side and are skipped by name).
 2. LIST EVENTS (free). `/sports/{key}/events` per key, so the paid call is made only when something is
    due. A key with nothing inside the look-ahead is not listed again until it could matter (a "peek" row
    in the done store says when), which keeps a quiet key to a few free calls a day.
 3. PLAN. Pre-game phases t24h, t6h, t2h, t30m (like nfl_capture): when ANY event of a key reaches a phase,
    ONE call for the key buys every event of the key, and every due (event, phase) is marked done. Events
    that are live get a cheap h2h-only in-play snapshot on a cadence (default 30 minutes per key).
 4. SPEND, under the caps. Each call is gated by `budget.can_spend_allsports` (credit floor; the daily cap
    in config/sports_catalog.json; sub-caps for in-play) and logged through `creditlog` in the
    `allsports_capture` band with the vendor's own x-requests-last. A refusal stops spending; a missed
    window is gone and is recorded, never filled.
 5. WRITE. Rows go to the multibook store: `sport` = the lower-case family code, plus `league` (the Odds API
    sport key) and `league_title`; `in_play: true` on every row observed at or after the start; a
    `draw_price` on a three-way h2h row. Only events inside the store horizon (36 hours) or live are
    written, so a call that returns a week of fixtures does not bloat the store.

COVERAGE, AND A KEY THAT NEVER PRICES
-------------------------------------
Each family buys the `us` region unless its catalog entry has a `region_ladder` (soccer: us then eu;
cricket: us, au, uk ...). A key whose calls on a region return events but ZERO bookmaker rows twice in a
row is "dark" on that region: the next rung of the ladder is tried, and a key dark on every rung is left
alone for 24 hours, so a sport the books do not price costs a handful of credits, not 96 a day.

APPEND-ONLY, RESUMABLE
----------------------
`data/processed/allsports_capture_done.jsonl` is appended to after every call (phase rows, one call row,
peek rows) and never rewritten; a killed run resumes from it. Nothing here edits the multibook store
except by appending to it.

Paper only; this module places no bet and recommends nothing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.capture import budget
from src.paths import processed_path
from src.pipeline import creditlog, snapshots
from src.providers import odds as odds_provider
from src.sports import catalog

LOG = logging.getLogger(__name__)

DEFAULT_DONE_PATH = processed_path("allsports_capture_done.jsonl")
DEFAULT_SPORTS_PATH = processed_path("allsports_sports.jsonl")
CALLER_PREGAME = "allsports_capture.pregame"
CALLER_INPLAY = "allsports_capture.inplay"
ENV_SWITCH = "ALLSPORTS_CAPTURE"
OFF_VALUES = ("0", "false", "off", "no")
DISCOVERY_REWRITE_HOURS = 6      # an unchanged key set is re-recorded at most this often


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _now(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("the clock must return a timezone-aware datetime")
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def switched_off(env=None) -> bool:
    source = os.environ if env is None else env
    return str(source.get(ENV_SWITCH, "")).strip().lower() in OFF_VALUES


def _append_rows(path, rows: list) -> int:
    if not rows:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if snapshots._ends_ragged(target):
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def _read_rows(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    out = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("allsports_capture: %s:%s is not valid JSON (interrupted append); skipped", target, number)
    return out


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def eligible_keys(sports: list, config: Optional[dict] = None) -> tuple:
    """(eligible, skipped) from a /sports listing.

    eligible: [{key, title, group, family}] for active keys with an event board this module buys.
    skipped: {key: reason} for every ACTIVE key that is not bought (outrights, not an event sport, or a
    family another pipeline already buys)."""
    eligible, skipped = [], {}
    for entry in sports or []:
        if not isinstance(entry, dict) or not entry.get("key") or not entry.get("active"):
            continue
        key = str(entry["key"])
        if not odds_provider.valid_sport_key(key):
            skipped[key] = "invalid_key"
            continue
        why = catalog.is_skipped_key(key, entry, config)
        if why:
            skipped[key] = why
            continue
        code = catalog.family_for_key(key, config)
        if catalog.is_dedicated(code, config):
            skipped[key] = f"bought_elsewhere:{code}"
            continue
        eligible.append({"key": key, "title": entry.get("title") or key, "group": entry.get("group"),
                         "family": code})
    return eligible, skipped


def record_discovery(eligible: list, skipped: dict, now: datetime, path=DEFAULT_SPORTS_PATH) -> bool:
    """Append one discovery row when the eligible key set changed (or the last row is old). The row is the
    program's record of which sports were being priced when."""
    keys = sorted(e["key"] for e in eligible)
    rows = _read_rows(path)
    last = rows[-1] if rows else None
    if last is not None and last.get("keys") == keys:
        stamp = _parse(last.get("observed_utc"))
        if stamp is not None and now - stamp < timedelta(hours=DISCOVERY_REWRITE_HOURS):
            return False
    families: dict = {}
    for e in eligible:
        families[e["family"]] = families.get(e["family"], 0) + 1
    _append_rows(path, [{"observed_utc": _iso(now), "keys": keys, "n_keys": len(keys),
                         "families": dict(sorted(families.items())), "n_skipped": len(skipped)}])
    return True


# ---------------------------------------------------------------------------
# the done store
# ---------------------------------------------------------------------------

class State:
    """What the append-only done store says: phases done, the last capture and coverage per key."""

    def __init__(self, rows: list):
        self.phase_done: set = set()            # (sport_key, event_id, phase)
        self.last_capture: dict = {}            # sport_key -> datetime of the newest paid call
        self.calls: dict = {}                   # sport_key -> [call rows, chronological]
        self.peek: dict = {}                    # sport_key -> next_check datetime
        for row in rows:
            kind = row.get("kind")
            key = row.get("sport_key")
            if kind == "phase" and key and row.get("event_id") and row.get("phase"):
                self.phase_done.add((key, row["event_id"], row["phase"]))
            elif kind == "call" and key:
                self.calls.setdefault(key, []).append(row)
                stamp = _parse(row.get("observed_utc"))
                if stamp is not None and (key not in self.last_capture or stamp > self.last_capture[key]):
                    self.last_capture[key] = stamp
            elif kind == "peek" and key:
                stamp = _parse(row.get("next_check_utc"))
                if stamp is not None:
                    self.peek[key] = stamp

    @classmethod
    def load(cls, path=DEFAULT_DONE_PATH) -> "State":
        return cls(_read_rows(path))


# ---------------------------------------------------------------------------
# phases and the plan
# ---------------------------------------------------------------------------

def due_pairs(key: str, events: list, state: State, now: datetime, phases: dict) -> list:
    """(event_id, phase) pairs due now: the event has not started, the phase window has opened, and the
    (key, event, phase) is not done. Events that have started are never due (in-play has its own path)."""
    due = []
    for event in events:
        event_id, start = event.get("id"), _parse(event.get("commence_time"))
        if not event_id or start is None or now >= start:
            continue
        for phase, minutes in phases.items():
            if (key, event_id, phase) in state.phase_done:
                continue
            if now >= start - timedelta(minutes=minutes):
                due.append((event_id, phase))
    return due


def live_events(events: list, now: datetime, window_hours: float) -> list:
    """Events that have started and are still inside the family's live window."""
    out = []
    for event in events:
        start = _parse(event.get("commence_time"))
        if start is not None and start <= now < start + timedelta(hours=window_hours):
            out.append(event)
    return out


def choose_regions(key: str, family_code: str, state: State, now: datetime, cap: dict,
                   config: Optional[dict] = None) -> tuple:
    """(regions | None, note). Walks the family's region ladder (default: the capture config's regions) and
    returns the first rung that is not dark; a key dark on every rung is skipped until the retry time."""
    fam = catalog.family(family_code, config) or {}
    ladder = list(fam.get("region_ladder") or cap["regions"])
    need = int(cap["dark_after_empty_captures"])
    calls = state.calls.get(key, [])
    for rung in ladder:
        recent = [c for c in calls if c.get("regions") == [rung]][-need:]
        dark = len(recent) >= need and all((c.get("events") or 0) > 0 and (c.get("rows") or 0) == 0
                                           for c in recent)
        if not dark:
            return [rung], None
    last = _parse(calls[-1].get("observed_utc")) if calls else None
    if last is None or now - last >= timedelta(hours=float(cap["dark_retry_hours"])):
        return [ladder[0]], "dark_retry"
    return None, "dark_on_every_region"


def build_plan(eligible: list, listings: dict, state: State, now: datetime, cap: dict,
               config: Optional[dict] = None) -> list:
    """Calls to make this run, in priority order: pre-game first (soonest start first), then in-play."""
    phases = dict(cap["phases_minutes"])
    pregame, inplay = [], []
    for item in eligible:
        key, code = item["key"], item["family"]
        events = listings.get(key)
        if not events:
            continue
        regions, note = choose_regions(key, code, state, now, cap, config)
        if regions is None:
            continue
        markets = [m for m in catalog.markets_for(code, config) if m in odds_provider.ALLSPORTS_MARKETS]
        pairs = due_pairs(key, events, state, now, phases)
        if pairs:
            starts = [_parse(e.get("commence_time")) for e in events
                      if e.get("id") in {p[0] for p in pairs}]
            soonest = min(s for s in starts if s is not None)
            pregame.append({"kind": "pregame", "sport_key": key, "family": code, "title": item["title"],
                            "markets": markets, "regions": regions, "pairs": pairs,
                            "est_credits": len(markets) * len(regions), "starts_in": (soonest - now),
                            "note": note})
            continue
        live = live_events(events, now, catalog.live_window_hours(code, config))
        if live:
            last = state.last_capture.get(key)
            if last is not None and now - last < timedelta(minutes=float(cap["inplay_cadence_minutes"])):
                continue
            ip_markets = [m for m in cap["inplay_markets"] if m in markets] or ["h2h"]
            inplay.append({"kind": "inplay", "sport_key": key, "family": code, "title": item["title"],
                           "markets": ip_markets, "regions": regions, "pairs": [], "n_live": len(live),
                           "est_credits": len(ip_markets) * len(regions), "note": note})
    pregame.sort(key=lambda c: (c["starts_in"], c["sport_key"]))
    inplay.sort(key=lambda c: (-c["n_live"], c["sport_key"]))
    return pregame + inplay


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def _draw_prices(event: dict) -> dict:
    """{book key: price} of the Draw outcome in each book's h2h market (three-way markets)."""
    out = {}
    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes") or []:
                if str(outcome.get("name")).strip().lower() == "draw" and outcome.get("price") is not None:
                    out[book.get("key")] = outcome["price"]
    return out


def build_rows(observed: str, now: datetime, events_raw: list, sport_key: str, title: str, family_code: str,
               cap: dict, config: Optional[dict] = None) -> tuple:
    """(rows to store, bookmaker rows seen, events returned) for one /odds response.

    Rows are produced by `snapshots.multibook_rows` from the provider's own normalised events, so their
    shape is the MLB/NFL shape exactly; this adds `league`, `league_title`, `in_play` and `draw_price`.
    Only events inside the store horizon, or live inside the family's live window, are kept."""
    row_sport = catalog.row_sport(family_code)
    horizon = timedelta(hours=float(cap["store_horizon_hours"]))
    live_window = timedelta(hours=catalog.live_window_hours(family_code, config))
    kept_events, draws = [], {}
    for raw in events_raw or []:
        if not isinstance(raw, dict):
            continue
        start = _parse(raw.get("commence_time"))
        if start is None:
            continue
        if start > now + horizon or now > start + live_window:
            continue
        kept_events.append(odds_provider.normalize_event(raw, sport=row_sport))
        draws[raw.get("id")] = _draw_prices(raw)
    seen_rows = 0
    for raw in events_raw or []:
        for book in (raw.get("bookmakers") or []) if isinstance(raw, dict) else []:
            seen_rows += len(book.get("markets") or [])
    rows = snapshots.multibook_rows(observed, kept_events, sport=row_sport)
    for row in rows:
        row["league"] = sport_key
        row["league_title"] = title
        start = _parse(row.get("commence_time"))
        if start is not None and now >= start:
            row["in_play"] = True
        if row.get("market") in (None, "h2h"):
            draw = draws.get(row.get("event_id"), {}).get(row.get("book"))
            if draw is not None:
                row["draw_price"] = draw
    return rows, seen_rows, len(events_raw or [])


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def run(*, now=None, env=None, config: Optional[dict] = None,
        fetch_sports: Optional[Callable] = None, list_events: Optional[Callable] = None,
        fetch_odds: Optional[Callable] = None, quota: Optional[Callable] = None,
        record_credit: Optional[Callable] = None, spend_guard: Optional[Callable] = None,
        done_path=DEFAULT_DONE_PATH, sports_path=DEFAULT_SPORTS_PATH, multibook_path=None,
        credit_store=None, plan_only: bool = False) -> dict:
    """One tick. See the module docstring. Every seam is injectable (tests never touch the network or the
    real stores); with no injection the defaults are the real provider, the real stores and the real
    credit log.

    plan_only=True does discovery and event listing (both free) and returns the plan WITHOUT spending."""
    clock = _now(now)
    cap = catalog.capture_config(config)
    result = {"observed_utc": _iso(clock), "discovered": 0, "eligible": 0, "listed": 0, "planned": 0,
              "calls": [], "credits": 0, "rows": 0, "skipped": {}, "halt": None, "plan_only": plan_only}
    if not cap.get("enabled", True) or switched_off(env):
        result["disabled"] = True
        result["halt"] = "disabled"
        return result
    if not odds_provider.is_configured(env):
        result["configured"] = False
        result["halt"] = "odds provider not configured"
        return result

    fetch_sports = fetch_sports or (lambda: odds_provider.fetch_sports(all_sports=True, env=env))
    list_events = list_events or (lambda key: odds_provider.fetch_sport_events(key, env=env))
    if fetch_odds is None:
        fetch_odds = lambda key, markets, regions: odds_provider.fetch_sport_odds_with_usage(  # noqa: E731
            key, markets, regions, env=env)
    real_provider = quota is None
    if quota is None:
        quota = lambda: odds_provider.quota(env)  # noqa: E731
    if record_credit is None:
        record_credit = lambda remaining, used, caller: creditlog.log(  # noqa: E731
            remaining, used, caller, store=credit_store or creditlog.DEFAULT_STORE, now=clock,
            budget_band=budget.ALLSPORTS)
    if multibook_path is None:
        multibook_path = snapshots.DEFAULT_MULTIBOOK_PATH

    # 1. discovery (free)
    try:
        sports = fetch_sports()
    except Exception as exc:  # noqa: BLE001 -- discovery failing costs nothing and spends nothing
        result["halt"] = f"discovery failed: {exc}"
        return result
    eligible, skipped = eligible_keys(sports, config)
    result["discovered"] = sum(1 for s in sports or [] if isinstance(s, dict) and s.get("active"))
    result["eligible"] = len(eligible)
    result["skipped"] = skipped
    by_family: dict = {}
    for e in eligible:
        by_family[e["family"]] = by_family.get(e["family"], 0) + 1
    result["families"] = dict(sorted(by_family.items()))
    if not plan_only:
        record_discovery(eligible, skipped, clock, sports_path)

    # 2. events (free), only for keys that could matter
    state = State.load(done_path)
    lookahead = timedelta(hours=float(cap["events_lookahead_hours"]))
    idle = timedelta(hours=float(cap["events_idle_recheck_hours"]))
    listings: dict = {}
    peeks = []
    for item in eligible:
        key = item["key"]
        due_at = state.peek.get(key)
        if due_at is not None and clock < due_at and not plan_only:
            continue
        try:
            events = list_events(key) or []
        except Exception as exc:  # noqa: BLE001
            result["skipped"][key] = f"events: {exc}"
            continue
        listings[key] = events
        starts = sorted(s for s in (_parse(e.get("commence_time")) for e in events) if s is not None)
        live_window = timedelta(hours=catalog.live_window_hours(item["family"], config))
        active = any(s - clock <= lookahead and clock < s + live_window for s in starts)
        if not active:
            upcoming = [s for s in starts if s > clock]
            nxt = min(clock + idle, (upcoming[0] - lookahead) if upcoming else clock + idle)
            nxt = max(nxt, clock + timedelta(minutes=30))
            peeks.append({"kind": "peek", "sport_key": key, "observed_utc": _iso(clock),
                          "next_check_utc": _iso(nxt), "events": len(events)})
    result["listed"] = len(listings)
    if peeks and not plan_only:
        _append_rows(done_path, peeks)

    # 3. plan
    plan = build_plan(eligible, listings, state, clock, cap, config)
    result["planned"] = len(plan)
    result["plan"] = [{"kind": c["kind"], "sport_key": c["sport_key"], "family": c["family"],
                       "markets": c["markets"], "regions": c["regions"], "est_credits": c["est_credits"],
                       "pairs": len(c["pairs"])} for c in plan]
    if plan_only or not plan:
        return result

    # 4. spend, under the caps
    remaining = None
    try:
        q = quota()
        remaining = q.get("remaining") if isinstance(q, dict) else None
    except Exception as exc:  # noqa: BLE001 -- unreadable quota fails CLOSED below
        LOG.warning("allsports_capture: quota unreadable: %s", exc)
    if remaining is None and real_provider:
        remaining = budget.remaining_today(now=clock, store=credit_store)
    if spend_guard is None:
        def spend_guard(est, caller_prefix, sub_cap, unlogged):  # noqa: E306
            return budget.can_spend_allsports(est + unlogged, now=clock, store=credit_store,
                                              remaining=remaining, config=config, sub_cap=sub_cap,
                                              caller_prefix=caller_prefix)
    unlogged = 0
    calls_made = 0
    for call in plan:
        if calls_made >= int(cap["max_calls_per_run"]):
            result["skipped"][call["sport_key"]] = "max_calls_per_run"
            continue
        caller = CALLER_INPLAY if call["kind"] == "inplay" else CALLER_PREGAME
        sub_cap = int(cap["inplay_daily_cap_credits"]) if call["kind"] == "inplay" else None
        decision = spend_guard(call["est_credits"], caller if sub_cap is not None else None, sub_cap, unlogged)
        if not decision.allowed:
            result["skipped"][call["sport_key"]] = decision.reason
            if "credit floor" in decision.reason or "daily cap" in decision.reason \
                    or "quota unreadable" in decision.reason:
                result["halt"] = decision.reason       # stop spending; nothing works around a floor or a cap
                break
            continue                                    # an in-play sub-cap only skips in-play calls
        try:
            events_raw, usage = fetch_odds(call["sport_key"], call["markets"], call["regions"])
        except Exception as exc:  # noqa: BLE001 -- one key failing must not stop the others
            result["skipped"][call["sport_key"]] = f"fetch error: {exc}"
            if "quota exhausted" in str(exc):
                result["halt"] = str(exc)
                break
            continue
        calls_made += 1
        usage = usage or {}
        billed = usage.get("last")
        if billed is None:
            billed = call["est_credits"]
        observed = snapshots._timestamp(clock)
        rows, rows_seen, n_events = build_rows(observed, clock, events_raw, call["sport_key"], call["title"],
                                               call["family"], cap, config)
        written = snapshots.append(rows, path=multibook_path)
        phase_rows = [{"kind": "phase", "sport_key": call["sport_key"], "event_id": eid, "phase": ph,
                       "observed_utc": _iso(clock), "commence_utc": _commence_of(listings[call["sport_key"]], eid),
                       "rows": sum(1 for r in rows if r.get("event_id") == eid)}
                      for eid, ph in call["pairs"]]
        call_row = {"kind": "call", "sport_key": call["sport_key"], "call_kind": call["kind"],
                    "observed_utc": _iso(clock), "regions": call["regions"], "markets": call["markets"],
                    "events": n_events, "rows": rows_seen, "stored": written, "credits": billed}
        if call["kind"] == "inplay":
            call_row["events_live"] = call.get("n_live")
        _append_rows(done_path, phase_rows + [call_row])
        state.last_capture[call["sport_key"]] = clock
        state.calls.setdefault(call["sport_key"], []).append(call_row)
        for eid, ph in call["pairs"]:
            state.phase_done.add((call["sport_key"], eid, ph))
        logged = record_credit(usage.get("remaining"), billed, caller)
        if logged is False:
            unlogged += int(billed or 0)
        if usage.get("remaining") is not None:
            remaining = usage["remaining"]
        result["credits"] += int(billed or 0)
        result["rows"] += written
        result["calls"].append({"kind": call["kind"], "sport_key": call["sport_key"], "family": call["family"],
                                "credits": billed, "events": n_events, "rows": written,
                                "phases_marked": len(phase_rows)})
    return result


def _commence_of(events: list, event_id) -> Optional[str]:
    for event in events or []:
        if event.get("id") == event_id:
            return event.get("commence_time")
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def summary_lines(result: dict) -> list:
    lines = []
    if result.get("disabled"):
        return ["  allsports capture: disabled (config or ALLSPORTS_CAPTURE=0)"]
    if result.get("configured") is False:
        return ["  allsports capture: odds provider not configured"]
    lines.append(f"  allsports capture: {result.get('discovered', 0)} active sport keys, "
                 f"{result.get('eligible', 0)} bought here, {result.get('listed', 0)} listed, "
                 f"{result.get('planned', 0)} call(s) planned, {len(result.get('calls') or [])} made, "
                 f"{result.get('credits', 0)} credit(s), {result.get('rows', 0)} row(s)")
    if result.get("families"):
        lines.append("    families: " + ", ".join(f"{k}={v}" for k, v in result["families"].items()))
    if result.get("halt"):
        lines.append(f"    halt: {result['halt']}")
    for key, why in sorted((result.get("skipped") or {}).items()):
        if why.startswith(("outrights", "not_an_event", "bought_elsewhere", "invalid")):
            continue
        lines.append(f"    skipped {key}: {why}")
    return lines


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.pipeline.allsports_capture")
    parser.add_argument("--plan", action="store_true",
                        help="discover and list events (free) and print the plan; spend nothing")
    args = parser.parse_args(argv)
    result = run(plan_only=args.plan)
    for line in summary_lines(result):
        print(line)
    if args.plan:
        for call in result.get("plan") or []:
            print(f"    plan {call['kind']:8s} {call['sport_key']} {call['markets']} {call['regions']} "
                  f"~{call['est_credits']} credit(s), {call['pairs']} phase(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
