"""Player props for NBA, NFL, NHL and NCAAF, bought from The Odds API's per-event odds endpoint.

WHY THIS EXISTS
---------------
The Odds API plan is paid for by the month and credits that are not spent when the quota resets are worth nothing
(docs/RESOURCE_POLICY.md). The MLB prop store (`batter_props.py`) proved the shape; every other sport's player
props were un-captured, and a prop line can never be bought back after the game. This module captures each sport's
main prop markets for every game, three times before the start, into an append-only store the grader
(`allsports_props_grade.grade_prop`) and later research read.

WHAT ONE RUN DOES (one tick of the scheduled capture, a step in scripts/capture_slot.sh)
------------------------------------------------------------------------------------------
 1. LIST EVENTS (free). `/sports/{key}/events` for each of the four families in `config/sports_catalog.json` that
    names `props_markets`. A family with no game inside the look-ahead is not listed again until it could matter
    (a "peek" row in the done store says when), so a quiet league costs a few free calls a day.
 2. PLAN. Per game, three phases before the start: t6h, t2h, t30m (config `capture.props_phases_minutes`). A phase is
    the WINDOW the clock is in (t6h from six hours out until t2h opens, and so on), so a game gets at most one
    snapshot per window. A window that closes with no purchase is recorded as `missed`, never filled later. The
    plan is soonest-start first, so a cap or a floor starves the games that still have later windows.
 3. SPEND, under the caps. One call per game buys every configured market (`markets x regions` credits). Each call
    is gated by `budget.can_spend_allsports_props` (the absolute 5,000-credit floor, failing closed on an unreadable
    quota, then the band's own daily cap `capture.props_daily_cap_credits`, default 1,200) and logged through
    `creditlog` in the `allsports_props` band with the vendor's own `x-requests-last`. A refusal stops spending.
 4. WRITE. Rows go to `data/processed/allsports_props.jsonl` in the MLB prop store's row shape
    (`batter_props._project`), one per (market, book, player, side, line), each with `observed_utc` and the book's
    own `book_last_update`, plus `sport` and `league` because this store holds four sports. Every snapshot is
    written whole (no de-duplication against an earlier phase): "what was the price at t30m" must be one query.

A GAME WITH NO PROPS
--------------------
Many college games never get a prop board. A game whose calls return no prop rows twice in a row
(`props_dark_after_empty_calls`) is not bought again; the skip is written as a `missed` phase with its reason.

APPEND-ONLY, RESUMABLE, FAIL-CLOSED
-----------------------------------
`data/processed/allsports_props_done.jsonl` (phases bought or missed, one `call` marker per billed fetch, errors,
peeks) and the rows file are only ever appended to; a killed run resumes from the done store. A fetch error is
recorded and retried (at most `props_max_attempts_per_phase` times), a 422 from the vendor (a market key the sport
does not serve) bills nothing and is surfaced in the summary line. The rows file is a registered rotatable store
(`store_archive.ROTATABLE_STORES["allsports_props"]`), so it can never reach GitHub's 100 MB file limit; readers use
`iter_rows`, which reads the archive segments and the hot file as one store.

KILL SWITCH: `ALLSPORTS_PROPS=0` in the environment (or `ALLSPORTS_CAPTURE=0`, the all-sports master switch, or
`capture.props_enabled=false` in the config). Paper only: this module places no bet and recommends nothing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Callable, Iterator, Optional

from src.capture import budget
from src.paths import processed_path
from src.pipeline import creditlog, prop_listing, store_archive
from src.pipeline.allsports_capture import _append_rows, _iso, _now, _parse, _read_rows
from src.providers import odds as odds_provider
from src.sports import catalog

LOG = logging.getLogger(__name__)

DEFAULT_ROWS_PATH = processed_path("allsports_props.jsonl")
DEFAULT_DONE_PATH = processed_path("allsports_props_done.jsonl")
CALLER_PREFIX = "allsports_props"
ENV_SWITCH = "ALLSPORTS_PROPS"
MASTER_SWITCH = "ALLSPORTS_CAPTURE"
OFF_VALUES = ("0", "false", "off", "no")

# The row fields of the MLB prop store (batter_props._project) plus the two this four-sport store needs.
ROW_FIELDS = ("event_id", "game_date", "commence_time", "home_team", "away_team", "market", "selection", "player",
              "side", "line", "price", "book", "book_last_update", "observed_utc", "capture_phase", "sport", "league")


# ---------------------------------------------------------------------------
# switches
# ---------------------------------------------------------------------------

def switched_off(env=None) -> bool:
    """True when ALLSPORTS_PROPS (or the all-sports master switch ALLSPORTS_CAPTURE) says 0/false/off/no."""
    source = os.environ if env is None else env
    return any(str(source.get(name, "")).strip().lower() in OFF_VALUES for name in (ENV_SWITCH, MASTER_SWITCH))


# ---------------------------------------------------------------------------
# the done store
# ---------------------------------------------------------------------------

class State:
    """What the append-only done store says: phases done or missed, errors, empty calls, quiet-league peeks."""

    def __init__(self, rows: list):
        self.phase_done: set = set()            # (sport_key, event_id, phase) bought or recorded as missed
        self.attempts: dict = {}                # (sport_key, event_id, phase) -> fetch errors so far
        self.empty_streak: dict = {}            # (sport_key, event_id) -> consecutive calls with no prop rows
        self.peek: dict = {}                    # sport_key -> next_check datetime
        for row in rows:
            kind, key, event = row.get("kind"), row.get("sport_key"), row.get("event_id")
            if kind == "phase" and key and event and row.get("phase"):
                self.phase_done.add((key, event, row["phase"]))
            elif kind == "error" and key and event and row.get("phase"):
                triple = (key, event, row["phase"])
                self.attempts[triple] = self.attempts.get(triple, 0) + 1
            elif kind == "call" and key and event:
                pair = (key, event)
                self.empty_streak[pair] = 0 if (row.get("stored") or 0) > 0 else self.empty_streak.get(pair, 0) + 1
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

def _phases(cap: dict) -> list:
    """[(name, minutes)] longest lead first: t6h, t2h, t30m."""
    return sorted(((str(k), float(v)) for k, v in dict(cap["props_phases_minutes"]).items()), key=lambda p: -p[1])


def current_phase(start: datetime, now: datetime, phases: list) -> tuple:
    """(phase the clock is in | None, [earlier phases whose window has closed]) for a game that has not started.

    The phase is the SHORTEST lead whose window has opened (t2h from two hours out, not t6h). Phases with a longer
    lead are over. None when even the longest has not opened."""
    opened = [(name, minutes) for name, minutes in phases if now >= start - timedelta(minutes=minutes)]
    if not opened:
        return None, []
    current = opened[-1][0]
    return current, [name for name, _ in opened[:-1]]


def build_plan(listings: dict, state: State, now: datetime, cap: dict, config: Optional[dict] = None) -> tuple:
    """(calls to make this run, `missed` phase rows to record). `listings` = {sport_key: (family, events)}.

    A call is one game at its current window. Games that started, whose phase is already done or missed, or that
    are dark (no props twice running) are not calls; a window that closed unbought becomes a `missed` row."""
    phases = _phases(cap)
    regions = list(cap["props_regions"])
    dark_after = int(cap["props_dark_after_empty_calls"])
    max_attempts = int(cap["props_max_attempts_per_phase"])
    families = catalog.props_families(config)
    calls, missed = [], []
    for sport_key, (code, events) in listings.items():
        markets = [m for m in families.get(code, {}).get("markets", []) if odds_provider.valid_prop_market(m)]
        if not markets:
            continue
        for event in events or []:
            event_id, start = event.get("id"), _parse(event.get("commence_time"))
            if not event_id or start is None or now >= start:
                continue
            phase, closed = current_phase(start, now, phases)
            if phase is None:
                continue
            for name in closed:
                if (sport_key, event_id, name) not in state.phase_done:
                    missed.append(_phase_row(sport_key, event_id, name, now, start, "missed",
                                             reason="window closed with no purchase"))
                    state.phase_done.add((sport_key, event_id, name))
            if (sport_key, event_id, phase) in state.phase_done:
                continue
            if state.attempts.get((sport_key, event_id, phase), 0) >= max_attempts:
                missed.append(_phase_row(sport_key, event_id, phase, now, start, "missed",
                                         reason=f"{max_attempts} fetch errors"))
                state.phase_done.add((sport_key, event_id, phase))
                continue
            if state.empty_streak.get((sport_key, event_id), 0) >= dark_after:
                missed.append(_phase_row(sport_key, event_id, phase, now, start, "missed",
                                         reason=f"dark: {dark_after} calls returned no props"))
                state.phase_done.add((sport_key, event_id, phase))
                continue
            calls.append({"sport_key": sport_key, "family": code, "event_id": event_id, "phase": phase,
                          "markets": markets, "regions": regions, "est_credits": len(markets) * len(regions),
                          "starts_in": start - now, "commence_time": event.get("commence_time"),
                          "home_team": event.get("home_team"), "away_team": event.get("away_team")})
    calls.sort(key=lambda c: (c["starts_in"], c["sport_key"], c["event_id"]))
    return calls, missed


def _phase_row(sport_key, event_id, phase, now, start, status, *, reason=None, rows=None) -> dict:
    row = {"kind": "phase", "status": status, "sport_key": sport_key, "event_id": event_id, "phase": phase,
           "observed_utc": _iso(now), "commence_utc": _iso(start)}
    if reason:
        row["reason"] = reason
    if rows is not None:
        row["rows"] = rows
    return row


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def project(payload: dict, observed: str, phase: str, family: str, sport_key: str, markets,
            event: Optional[dict] = None) -> list:
    """One row per (market, book, player, side, line) of a per-event odds payload, in the MLB prop store's shape.

    Only markets that were requested are kept (a payload echoing something else is not projected) and only
    outcomes naming a player (`description`). `line` is the point as a string, or None for a market with no point
    (anytime scorer). `selection` is `<player id or name>:<side>`, the project's selection identity."""
    event = event or {}
    wanted = set(markets)
    event_id = payload.get("id") or event.get("id") or event.get("event_id")
    commence = payload.get("commence_time") or event.get("commence_time")
    home = payload.get("home_team") or event.get("home_team")
    away = payload.get("away_team") or event.get("away_team")
    start = _parse(commence)
    game_date = prop_listing._slate_date(start) if start is not None else None
    sport = catalog.row_sport(family)
    rows = []
    for book in payload.get("bookmakers") or []:
        for market in book.get("markets") or []:
            market_key = market.get("key")
            if market_key not in wanted:
                continue
            for outcome in market.get("outcomes") or []:
                player = outcome.get("description")
                if not player:
                    continue
                side = outcome.get("name")
                player_id = outcome.get("participant_id") or outcome.get("description_id") or player
                point = outcome.get("point")
                rows.append({
                    "event_id": event_id, "game_date": game_date, "commence_time": commence,
                    "home_team": home, "away_team": away, "market": market_key,
                    "selection": f"{player_id}:{side}", "player": player, "side": side,
                    "line": None if point is None else str(point), "price": outcome.get("price"),
                    "book": book.get("key"), "book_last_update": market.get("last_update"),
                    "observed_utc": observed, "capture_phase": phase, "sport": sport, "league": sport_key,
                })
    return rows


def iter_rows(path=DEFAULT_ROWS_PATH, *, since: Optional[str] = None) -> Iterator[dict]:
    """Every stored prop row, oldest first: archive segments, then the hot file (the logical store).

    A line that is not valid JSON (an interrupted append) is skipped. `since` (YYYY-MM-DD) skips whole archive
    segments that end before it; the caller still filters rows."""
    for line in store_archive.iter_lines(path, since=since):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            LOG.warning("allsports_props: skipped a line that is not valid JSON in %s", path)


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def run(*, now=None, env=None, config: Optional[dict] = None,
        list_events: Optional[Callable] = None, fetch_event_odds: Optional[Callable] = None,
        quota: Optional[Callable] = None, record_credit: Optional[Callable] = None,
        spend_guard: Optional[Callable] = None, rows_path=DEFAULT_ROWS_PATH, done_path=DEFAULT_DONE_PATH,
        credit_store=None, plan_only: bool = False) -> dict:
    """One tick. See the module docstring. Every seam is injectable (tests never touch the network or a real
    store); with no injection the defaults are the real provider, the real stores and the real credit log.

    plan_only=True lists events (free) and returns the plan WITHOUT spending or writing anything."""
    clock = _now(now)
    cap = catalog.capture_config(config)
    result = {"observed_utc": _iso(clock), "families": [], "listed": 0, "planned": 0, "calls": [], "credits": 0,
              "rows": 0, "skipped": {}, "errors": [], "missed": 0, "halt": None, "plan_only": plan_only}
    if not cap.get("enabled", True) or not cap.get("props_enabled", True) or switched_off(env):
        result["disabled"] = True
        result["halt"] = "disabled"
        return result
    if not odds_provider.is_configured(env):
        result["configured"] = False
        result["halt"] = "odds provider not configured"
        return result

    list_events = list_events or (lambda key: odds_provider.fetch_sport_events(key, env=env))
    if fetch_event_odds is None:
        fetch_event_odds = lambda key, event_id, markets, regions: (  # noqa: E731
            odds_provider.fetch_sport_event_odds_with_usage(key, event_id, markets, regions, env=env))
    real_provider = quota is None
    if quota is None:
        quota = lambda: odds_provider.quota(env)  # noqa: E731
    if record_credit is None:
        record_credit = lambda remaining, used, caller: creditlog.log(  # noqa: E731
            remaining, used, caller, store=credit_store or creditlog.DEFAULT_STORE, now=clock,
            budget_band=budget.ALLSPORTS_PROPS)

    # 1. events (free), only for leagues that could matter
    families = catalog.props_families(config)
    result["families"] = list(families)
    state = State.load(done_path)
    lookahead = timedelta(hours=float(cap["props_events_lookahead_hours"]))
    idle = timedelta(hours=float(cap["props_events_idle_recheck_hours"]))
    listings: dict = {}
    peeks = []
    for code, fam in families.items():
        sport_key = fam["sport_key"]
        due_at = state.peek.get(sport_key)
        if due_at is not None and clock < due_at and not plan_only:
            continue
        try:
            events = list_events(sport_key) or []
        except Exception as exc:  # noqa: BLE001 -- listing is free; one league failing must not stop the others
            result["skipped"][sport_key] = f"events: {exc}"
            continue
        listings[sport_key] = (code, events)
        starts = sorted(s for s in (_parse(e.get("commence_time")) for e in events) if s is not None and s > clock)
        if not any(s - clock <= lookahead for s in starts):
            nxt = min(clock + idle, (starts[0] - lookahead) if starts else clock + idle)
            nxt = max(nxt, clock + timedelta(minutes=30))
            peeks.append({"kind": "peek", "sport_key": sport_key, "observed_utc": _iso(clock),
                          "next_check_utc": _iso(nxt), "events": len(events)})
    result["listed"] = len(listings)
    if peeks and not plan_only:
        _append_rows(done_path, peeks)

    # 2. plan
    plan, missed = build_plan(listings, state, clock, cap, config)
    result["planned"] = len(plan)
    result["missed"] = len(missed)
    result["plan"] = [{"sport_key": c["sport_key"], "family": c["family"], "event_id": c["event_id"],
                       "phase": c["phase"], "markets": c["markets"], "regions": c["regions"],
                       "est_credits": c["est_credits"]} for c in plan]
    result["est_credits"] = sum(c["est_credits"] for c in plan)
    if plan_only:
        return result
    if missed:
        _append_rows(done_path, missed)
    if not plan:
        return result

    # 3. spend, under the floor and the band's own cap
    remaining = None
    try:
        q = quota()
        remaining = q.get("remaining") if isinstance(q, dict) else None
    except Exception as exc:  # noqa: BLE001 -- an unreadable quota fails CLOSED below
        LOG.warning("allsports_props: quota unreadable: %s", exc)
    if remaining is None and real_provider:
        remaining = budget.remaining_today(now=clock, store=credit_store)
    if spend_guard is None:
        def spend_guard(est, unlogged):  # noqa: E306
            return budget.can_spend_allsports_props(est + unlogged, now=clock, store=credit_store,
                                                    remaining=remaining, config=config)
    unlogged = 0
    calls_made = 0
    for call in plan:
        tag = f"{call['sport_key']}/{call['event_id']}/{call['phase']}"
        if calls_made >= int(cap["props_max_calls_per_run"]):
            result["skipped"][tag] = "max_calls_per_run"
            continue
        decision = spend_guard(call["est_credits"], unlogged)
        if not decision.allowed:
            result["skipped"][tag] = decision.reason
            if "credit floor" in decision.reason or "daily cap" in decision.reason \
                    or "quota unreadable" in decision.reason:
                result["halt"] = decision.reason       # stop spending; nothing works around a floor or a cap
                break
            continue
        caller = f"{CALLER_PREFIX}.{call['phase']}"
        try:
            payload, usage = fetch_event_odds(call["sport_key"], call["event_id"], call["markets"], call["regions"])
        except Exception as exc:  # noqa: BLE001 -- one game failing must not stop the others
            message = str(exc)
            result["errors"].append(f"{tag}: {message}")
            _append_rows(done_path, [{"kind": "error", "sport_key": call["sport_key"], "event_id": call["event_id"],
                                      "phase": call["phase"], "observed_utc": _iso(clock), "error": message[:300]}])
            state.attempts[(call["sport_key"], call["event_id"], call["phase"])] = \
                state.attempts.get((call["sport_key"], call["event_id"], call["phase"]), 0) + 1
            if "quota exhausted" in message:
                result["halt"] = message
                break
            continue
        calls_made += 1
        usage = usage or {}
        billed = usage.get("last")
        if billed is None:
            billed = call["est_credits"]
        # The spend is a fact the moment the fetch returns: log it before anything that could fail.
        logged = record_credit(usage.get("remaining"), billed, caller)
        if logged is False:
            unlogged += int(billed or 0)
        if usage.get("remaining") is not None:
            remaining = usage["remaining"]
        observed = _iso(clock)
        rows = project(payload if isinstance(payload, dict) else {}, observed, call["phase"], call["family"],
                       call["sport_key"], call["markets"], event=call)
        written = _append_rows(rows_path, rows)
        books = len({r["book"] for r in rows})
        _append_rows(done_path, [
            _phase_row(call["sport_key"], call["event_id"], call["phase"], clock,
                       _parse(call["commence_time"]) or clock, "done", rows=written),
            {"kind": "call", "sport_key": call["sport_key"], "event_id": call["event_id"], "family": call["family"],
             "phase": call["phase"], "observed_utc": observed, "regions": call["regions"],
             "markets": call["markets"], "books": books, "stored": written, "credits": billed,
             "remaining": usage.get("remaining")}])
        state.phase_done.add((call["sport_key"], call["event_id"], call["phase"]))
        pair = (call["sport_key"], call["event_id"])
        state.empty_streak[pair] = 0 if written else state.empty_streak.get(pair, 0) + 1
        result["credits"] += int(billed or 0)
        result["rows"] += written
        result["calls"].append({"sport_key": call["sport_key"], "family": call["family"],
                                "event_id": call["event_id"], "phase": call["phase"], "credits": billed,
                                "rows": written, "books": books})
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def summary_lines(result: dict) -> list:
    if result.get("disabled"):
        return ["  allsports props: disabled (config, ALLSPORTS_PROPS=0 or ALLSPORTS_CAPTURE=0)"]
    if result.get("configured") is False:
        return ["  allsports props: odds provider not configured"]
    lines = [f"  allsports props: {result.get('listed', 0)} league(s) listed, {result.get('planned', 0)} call(s) planned"
             f" (~{result.get('est_credits', 0)} credit(s)), {len(result.get('calls') or [])} made, "
             f"{result.get('credits', 0)} credit(s), {result.get('rows', 0)} row(s), {result.get('missed', 0)} phase(s) missed"]
    if result.get("halt"):
        lines.append(f"    halt: {result['halt']}")
    for message in result.get("errors") or []:
        lines.append(f"    error {message}")
        if "422" in message:
            lines.append("    ESCALATE: the vendor rejected a prop market key (HTTP 422, nothing billed): "
                         "check props_markets in config/sports_catalog.json against the sport's market list")
    for tag, why in sorted((result.get("skipped") or {}).items()):
        lines.append(f"    skipped {tag}: {why}")
    return lines


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.pipeline.allsports_props")
    parser.add_argument("--plan", action="store_true",
                        help="list events (free) and print the plan; spend nothing and write nothing")
    args = parser.parse_args(argv)
    result = run(plan_only=args.plan)
    for line in summary_lines(result):
        print(line)
    if args.plan:
        for call in result.get("plan") or []:
            print(f"    plan {call['sport_key']} {call['event_id']} {call['phase']} {call['markets']} "
                  f"{call['regions']} ~{call['est_credits']} credit(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
