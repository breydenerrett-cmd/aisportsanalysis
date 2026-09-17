"""Live in-play window runner. Polls, evaluates rules, captures odds, records candidates.

WHY THIS EXISTS
---------------
Live betting requires frequent polling as games progress. This module orchestrates
one complete window: poll state, identify state changes, fetch in-play odds on
change, evaluate pre-registered rules, and record candidates. Every external call
is injectable (clock, sleep, fetch functions) for testability and flexibility.
The module never raises out of the loop and commits state every few minutes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.paths import data_path
from src.pipeline import live_odds, livefeed_mlb, livefeed_nfl
from src.analysis import live_rules
from src.appstate import live_ledger
from src.board import gamekey
from src.pipeline import snapshots

LOG = logging.getLogger(__name__)


def pregame_context(sport, date=None, *, rows=None, games=None, event_map=None) -> dict:
    """Pregame context (favourite + event_id) for live rules evaluation.

    Args:
        sport: "mlb" or "nfl".
        date: ET date (YYYY-MM-DD), defaults to today.
        rows: Pre-game odds rows (h2h snapshots) for this date.
        games: Schedule games for this date.
        event_map: event_id -> game_id/game_pk mapping (gamekey.load_map output).

    Returns:
        Dict {game_id/game_pk -> pregame dict} with favourite and favorite_prob
        from the de-vigged consensus (prices.snapshot).
    """
    # Lazy imports
    if rows is None:
        from src.pipeline import snapshots as snapshots_mod
        from src.paths import processed_path
        try:
            all_rows = []
            for line in Path(processed_path("odds_multibook.jsonl")).read_text().splitlines():
                if line.strip():
                    try:
                        all_rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            rows = [r for r in all_rows if r.get("sport", "mlb") == sport
                   and snapshots_mod.official_date(r.get("commence_time")) == date]
        except Exception:
            rows = []

    if games is None:
        try:
            if sport == "mlb":
                from src.providers import mlb as mlb_provider
                games = mlb_provider.fetch_games(date) if date else []
            elif sport == "nfl":
                from src.providers import nfl as nfl_provider
                games = nfl_provider.schedule_for_date(date) if date else []
            else:
                games = []
        except Exception:
            games = []

    if event_map is None:
        try:
            event_map = gamekey.load_map()
        except Exception:
            event_map = {}

    # Build context per game
    context = {}

    # For MLB: one implementation, in livefeed_mlb.build_pregame_context.
    # This block used to rebuild the consensus by hand and read a
    # "home_prob" key that prices.snapshot() does not produce, which is why
    # docs/LIVE_BETTING_SYSTEM.md D1 and D2 record a favourite of None for
    # 10 of 10 games on 2026-09-14. The builder reads
    # sides.home.consensus_probability directly, keys every game by a string
    # game_pk, and takes each book's newest quote strictly before
    # commence_time.
    if sport == "mlb" and games:
        context.update(livefeed_mlb.build_pregame_context(
            games, rows, event_map))

    # For NFL
    elif sport == "nfl" and games:
        for game in games:
            game_id = str(game.get("game_id"))
            if not game_id:
                continue

            home_team = game.get("home")
            away_team = game.get("away")
            start_utc = game.get("start_utc")

            # Get favourite from pre-game quotes
            game_rows = [r for r in (rows or [])
                        if r.get("home_team") == home_team
                        and r.get("away_team") == away_team]
            if game_rows:
                try:
                    from src.analysis import prices as prices_mod
                    consensus = prices_mod.snapshot(game_rows)
                    if consensus:
                        favorite = "home" if consensus.get("home_prob", 0.5) > 0.5 else "away"
                        favorite_prob = max(consensus.get("home_prob", 0.5),
                                           1 - consensus.get("home_prob", 0.5))
                    else:
                        favorite = None
                        favorite_prob = None
                except Exception:
                    favorite = None
                    favorite_prob = None
            else:
                favorite = None
                favorite_prob = None

            # For NFL, event_id is looked up from the gamekey map
            event_id = gamekey.game_id_for_event(None, event_map) if event_map else None

            context[game_id] = {
                "sport": "nfl",
                "game_id": game_id,
                "home_team": home_team,
                "away_team": away_team,
                "favorite": favorite,
                "favorite_prob": favorite_prob,
                "starter_ids": None,
                "kickoff_utc": start_utc,
                "event_id": event_id,
            }

    return context


def tick(sport, *, state, clock=None, deps=None) -> dict:
    """One iteration: poll state, check registered triggers, capture odds
    ONLY on a registered trigger (never on any change -- R16-L5), evaluate
    rules against fresh prices, record candidates.

    Trigger tracking lives in `state["trigger_state"]`, keyed by
    `(game_id, rule_id)`, across ticks for the life of the window (3.1: "one
    trigger per rule per game" -- a key already present is never
    re-registered). Each tracked trigger is retried at T0, T0+45s, T0+90s
    (`live_odds.due_capture`) until it prices (>= 3 fresh books,
    `live_rules.fresh_median_price`/`live_odds.fresh_quotes`) or the ladder
    is exhausted, plus exactly one descriptive follow-up capture at T0+5
    minutes that is NEVER recorded as a candidate (3.1: "never a gate").

    Time-based triggers (the NFL halftime proxy) fire from this same check
    on every poll for every live game, not only ones whose state changed
    (fixes D5) -- `live_rules.check_all_triggers` has no notion of "changed"
    at all, it just asks "does the condition hold right now".

    Args:
        sport: "mlb" or "nfl".
        state: {"prev_states": dict, "pregame": dict, "date": str,
                "trigger_state": dict (created here if absent)}.
        clock: Callable returning UTC datetime.
        deps: Injected dependencies (poll, capture, check_triggers,
              evaluate_all, record, registry_status, env).

    Returns:
        {"polled": int, "changed": int, "captured": int, "candidates_new": int, "errors": int}
        "changed" counts newly-registered triggers this poll (not raw state
        changes -- the "any change" design this replaced is gone).
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    deps = deps or {}

    # Injected functions
    poll_fn = deps.get("poll")
    capture_fn = deps.get("capture", live_odds.capture_inplay)
    check_triggers_fn = deps.get("check_triggers", live_rules.check_all_triggers)
    evaluate_all_fn = deps.get("evaluate", live_rules.evaluate_all)
    record_fn = deps.get("record", live_ledger.record_candidate)
    registry_status = deps.get("registry_status")

    # Default poll function
    if poll_fn is None:
        if sport == "mlb":
            poll_fn = lambda: livefeed_mlb.poll(clock=clock)
        elif sport == "nfl":
            poll_fn = lambda: livefeed_nfl.poll(force=True, clock=clock)
        else:
            return {"polled": 0, "changed": 0, "captured": 0, "candidates_new": 0, "errors": 1}

    # Poll state
    try:
        poll_result = poll_fn()
        polled = poll_result.get("live_games", 0) if sport == "mlb" else poll_result.get("in_play", 0)
    except Exception as exc:
        LOG.exception("poll failed: %s", exc)
        return {"polled": 0, "changed": 0, "captured": 0, "candidates_new": 0, "errors": 1}

    # Read new states
    date_str = state.get("date") or (clock().strftime("%Y-%m-%d") if sport == "nfl"
                                     else datetime.now(timezone.utc).astimezone(livefeed_mlb._EASTERN).strftime("%Y-%m-%d"))
    if sport == "mlb":
        new_states = livefeed_mlb.latest_states(date_str)
    elif sport == "nfl":
        new_states = livefeed_nfl.latest_states(date_str)
    else:
        new_states = {}

    now = clock()
    pregame_context = state.get("pregame", {})
    trigger_state = state.setdefault("trigger_state", {})

    # Window-evidence bookkeeping (the fix for the 2026-09-16 defect: a
    # window that evaluates hundreds of ticks and reports a bare
    # `candidates_new: 0` is indistinguishable from one that evaluated
    # nothing). Registry status is resolved once per tick, for every rule
    # this sport runs -- including a rule whose trigger condition is never
    # checked below because it is not registered, which `check_all_triggers`
    # alone would never surface.
    evidence = state.setdefault("evidence", {})
    registry_status_map = live_rules.registry_status_for_sport(sport, registry_status)

    # 1. Check every registered trigger for every game THIS poll (D5: time-
    #    based triggers included, unconditionally -- there is no "changed"
    #    filter here at all). A key already tracked is never re-registered
    #    (one trigger per rule per game, 3.1).
    newly_registered = 0
    for game_id, new_state_row in (new_states or {}).items():
        pgame = pregame_context.get(game_id)

        # Evidence: record whether a pregame context exists (and why not),
        # then -- for every applicable rule -- the closest this state row
        # came to firing, whether or not it actually did. Runs for EVERY
        # game seen this poll, not gated on a trigger, because a
        # "closest miss" can only be known if every tick is looked at.
        game_evidence = evidence.setdefault(game_id, {
            "pregame_built": pgame is not None and pgame.get("usable", True),
            "pregame_reason": None if pgame is None else pgame.get("reason"),
            "ticks_seen": 0,
            "rules": {},
        })
        game_evidence["ticks_seen"] += 1
        if pgame is not None:
            for rule_id in registry_status_map:
                rule_ev = game_evidence["rules"].setdefault(rule_id, {
                    "registry_status": registry_status_map.get(rule_id, live_rules.UNREGISTERED_STATUS),
                    "closest_miss": None,
                })
                diag = live_rules.rule_diagnostic(rule_id, pregame=pgame, state=new_state_row)
                if diag is not None:
                    best = rule_ev["closest_miss"]
                    if best is None or diag["distance"] < best["distance"]:
                        rule_ev["closest_miss"] = diag

        if pgame is None:
            continue

        # D12 fix (docs/LIVE_BETTING_SYSTEM.md 2.3, live_rules.py's own
        # docstring on `_mlb_starter_pulled_early`): the rule's registered
        # text means the pitcher actually observed on the mound, not the
        # pregame probable. The first live state row that shows the
        # favourite on defence with a real pitcher_id overwrites
        # `pregame["starter_ids"][favorite_side]` with that OBSERVED id --
        # once, never again for this game (a later pitching change is
        # exactly what the rule is trying to detect, so the observed
        # starter must stay fixed after this first sighting). Before that
        # first sighting, `starter_ids` still holds the probable, same as
        # `livefeed_mlb.build_pregame_context` seeds it -- there is nothing
        # else to compare against yet.
        if sport == "mlb":
            favorite_side = pgame.get("favorite")
            if favorite_side in ("home", "away"):
                observed_flag_key = f"_starter_observed_{favorite_side}"
                defensive_half = "top" if favorite_side == "home" else "bottom"
                if (not pgame.get(observed_flag_key)
                        and new_state_row.get("half") == defensive_half):
                    observed_pitcher_id = new_state_row.get("pitcher_id")
                    if observed_pitcher_id is not None:
                        starter_ids = pgame.get("starter_ids")
                        if not isinstance(starter_ids, dict):
                            starter_ids = {}
                            pgame["starter_ids"] = starter_ids
                        starter_ids[favorite_side] = observed_pitcher_id
                        pgame[observed_flag_key] = True

        try:
            fired = check_triggers_fn(pregame=pgame, state=new_state_row,
                                      registry_status=registry_status)
        except Exception as exc:
            LOG.exception("trigger check failed for %s: %s", game_id, exc)
            continue
        for rule_id, trigger_info in fired.items():
            key = (game_id, rule_id)
            if key in trigger_state:
                continue
            t0_utc = new_state_row.get("observed_utc") or now.isoformat()
            record = live_odds.new_trigger_record(t0_utc, trigger_info)
            record["game_id"] = game_id
            record["rule_id"] = rule_id
            record["pregame"] = pgame
            record["state_at_trigger"] = new_state_row
            trigger_state[key] = record
            newly_registered += 1

    # 2. Decide which tracked triggers are due for a capture attempt now.
    due = [(key, live_odds.due_capture(record, now))
           for key, record in trigger_state.items()]
    due = [(key, reason) for key, reason in due if reason]

    captured = 0
    candidates_new = 0
    if due:
        try:
            now_utc = now.isoformat()
            state_snapshot_id = hashlib.sha1(
                f"{sport}|{now_utc}".encode()).hexdigest()[:16]

            # One capture call covers every due trigger in this sport (a
            # featured /odds call returns every live game at no extra cost,
            # 3.1), so it is billed and fetched exactly once per poll no
            # matter how many triggers are due.
            capture_result = capture_fn(
                sport, state_snapshot_id=state_snapshot_id,
                reason="; ".join(f"{gid}:{rid}:{reason}"
                                 for (gid, rid), reason in due),
                env=deps.get("env"))
            captured = capture_result.get("captured", 0)
        except Exception as exc:
            LOG.exception("capture_inplay failed: %s", exc)

        try:
            inplay_rows = live_odds.read_inplay(sport=sport)
        except Exception:
            inplay_rows = []

        for key, reason in due:
            record = trigger_state[key]
            game_id, rule_id = key
            pgame = record["pregame"]
            quote = live_odds.latest_inplay_quote(inplay_rows, pgame.get("event_id"))
            current_state = new_states.get(game_id, record["state_at_trigger"])

            if reason == live_odds.FOLLOWUP_REASON:
                # 3.1: "a follow-up capture five minutes after the trigger
                # (descriptive price-reaction data, never a gate)". Taken
                # once, never recorded as a candidate, never restarts the
                # retry ladder.
                record["followup_done"] = True
                continue

            # A gating retry: only counts toward PRICED (stops the ladder)
            # when at least MIN_FRESH_BOOKS books are fresh as of THIS
            # capture (3.1's fresh-price rule).
            quotes = (quote or {}).get("quotes")
            captured_utc = (quote or {}).get("observed_utc")
            fresh = (live_odds.fresh_quotes(
                quotes, t0_utc=record["t0_utc"], captured_utc=captured_utc)
                if quotes and captured_utc else [])

            record["next_retry_idx"] = record.get("next_retry_idx", 0) + 1
            # Evidence: the price-gate diagnostics a "state condition met,
            # price gate refused" row needs (item 2 of the observability
            # fix) -- overwritten each attempt so the artifact always shows
            # the LAST attempt's numbers, not the first.
            record["last_fresh_count"] = len(fresh)
            record["last_quotes_seen"] = len(quotes) if quotes else 0
            record["last_capture_utc"] = captured_utc

            if len(fresh) < live_rules.MIN_FRESH_BOOKS:
                continue  # UNPRICED this attempt; the ladder will retry

            try:
                candidates = evaluate_all_fn(
                    pregame=pgame, state=current_state,
                    quote={"observed_utc": captured_utc, "quotes": fresh},
                    registry_status=registry_status)
            except Exception:
                LOG.exception("rule evaluation failed for %s", key)
                candidates = []

            for candidate in candidates:
                if candidate.get("rule_id") != rule_id:
                    continue
                try:
                    result = record_fn(candidate)
                    if result is not None:
                        candidates_new += 1
                        record["priced"] = True
                except Exception as exc:
                    LOG.exception("record_candidate failed: %s", exc)

    return {
        "polled": polled,
        "changed": newly_registered,
        "captured": captured,
        "candidates_new": candidates_new,
        "errors": 0,
    }


def _parse_iso(value):
    if not value or not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


DEFAULT_WINDOW_GAP_TOLERANCE = 1.5


def compute_window_gaps(previous_last_by_game: dict, current_first_by_game: dict,
                        *, poll_interval_s: float,
                        tolerance: float = DEFAULT_WINDOW_GAP_TOLERANCE) -> list:
    """R16-L5 (3.2, "Window handoffs"): a live minute no window covers must
    be COUNTED, never silently skipped. For each game whose state was
    tracked before this window started (`previous_last_by_game`, from the
    ending window's last state row for it) and is tracked again now
    (`current_first_by_game`, this window's first state row for it), a gap
    longer than `tolerance` poll intervals is one WINDOW_GAP entry -- never
    invented for a game with no prior row (new to the slate) or no real
    gap.

    Args:
        previous_last_by_game: {game_id: observed_utc} for the LAST state
            row seen for each game before this window started.
        current_first_by_game: {game_id: observed_utc} for the FIRST state
            row THIS window recorded for each game.
        poll_interval_s: this sport's poll cadence (20 for MLB, 300 for NFL).

    Returns:
        A list of {"kind": "WINDOW_GAP", "game_id", "start_utc", "end_utc",
        "gap_seconds", "reason"} dicts, oldest first.
    """
    gaps = []
    for game_id, prev_utc in (previous_last_by_game or {}).items():
        new_utc = (current_first_by_game or {}).get(game_id)
        if not new_utc or not prev_utc:
            continue
        prev_dt = _parse_iso(prev_utc)
        new_dt = _parse_iso(new_utc)
        if prev_dt is None or new_dt is None:
            continue
        gap_s = (new_dt - prev_dt).total_seconds()
        if gap_s > poll_interval_s * tolerance:
            gaps.append({
                "kind": "WINDOW_GAP",
                "game_id": game_id,
                "start_utc": prev_utc,
                "end_utc": new_utc,
                "gap_seconds": gap_s,
                "reason": "no live window covered this span",
            })
    return gaps


def record_window_gaps(sport, gaps: list, *, path=None) -> int:
    """Append each gap in `gaps` to `data/live/<sport>/window_gaps.jsonl`
    (or `path`), one JSON row per line. Returns the count written.

    SEAM NOTE: these rows arguably belong in the hash-chained live ledger
    next to candidate rows, for the same audit trail -- but
    `src/appstate/live_ledger.py` is owned by a different agent this pass
    (see the task's file-ownership split), so this writes its own small
    append-only store instead of reaching into that module. If the ledger
    agent wants WINDOW_GAP rows unified into the chain, that is the seam to
    wire next, not a defect in this file.
    """
    if not gaps:
        return 0
    target = Path(path) if path is not None else Path(data_path("live", sport, "window_gaps.jsonl"))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for gap in gaps:
            handle.write(json.dumps(gap, sort_keys=True) + "\n")
    return len(gaps)


def build_window_evidence(sport, *, date, ticks, window_start_utc, window_end_utc,
                          evidence: dict, trigger_state: dict, stopped_reason: str) -> dict:
    """Assemble the end-of-window evidence artifact -- the fix this task
    exists to build (see the module docstring's WHY and
    docs/LIVE_BETTING_SYSTEM.md 3.1). Written by `run()` on EVERY exit path,
    including a zero-candidate one, so a reader can answer "did the
    evaluator run, and what did it see" without the CI job.

    For every game seen this window and every rule applicable to this
    sport, classifies the outcome into exactly one of:
      - "unregistered": the rule's registry status was not
        registered/forward-testing this window -- it was never even
        trigger-checked.
      - "priced_candidate_recorded": the trigger fired and
        `live_ledger.record_candidate` (or whatever `record` dep) accepted
        it.
      - "state_condition_met_price_refused": the trigger fired (its state
        condition held) but no candidate was ever recorded -- the price
        gate refused every attempt (fewer than `live_rules.MIN_FRESH_BOOKS`
        fresh books) before the window ended. Distinct from "never came
        close": this game DID meet the state condition.
      - "state_condition_not_met": the trigger never fired this window.
        `closest_miss` names the nearest any tick came, with the actual
        observed values (never a placeholder) -- `null` only if this rule
        was never diagnosable for this game (e.g. no pregame context).

    Every value under `closest_miss` and the price-gate fields is a STATE
    value or a gate reason -- never an outcome, per
    docs/LIVE_BETTING_SYSTEM.md 3.1's counts-only discipline. No win, loss,
    or unit figure is ever written by this function.
    """
    games_out = {}
    for game_id, game_ev in (evidence or {}).items():
        rules_out = {}
        for rule_id, rule_ev in (game_ev.get("rules") or {}).items():
            status = rule_ev.get("registry_status", live_rules.UNREGISTERED_STATUS)

            if status not in live_rules.ALLOWED_RULE_STATUSES:
                rules_out[rule_id] = {
                    "registry_status": status,
                    "outcome": "unregistered",
                }
                continue

            trig = (trigger_state or {}).get((game_id, rule_id))
            if trig is not None:
                outcome = ("priced_candidate_recorded" if trig.get("priced")
                          else "state_condition_met_price_refused")
                rules_out[rule_id] = {
                    "registry_status": status,
                    "outcome": outcome,
                    "trigger_values": trig.get("trigger_info"),
                    "t0_utc": trig.get("t0_utc"),
                    "retries_attempted": trig.get("next_retry_idx", 0),
                    "min_fresh_books_required": live_rules.MIN_FRESH_BOOKS,
                    "last_fresh_count": trig.get("last_fresh_count"),
                    "last_quotes_seen": trig.get("last_quotes_seen"),
                    "last_capture_utc": trig.get("last_capture_utc"),
                }
            else:
                rules_out[rule_id] = {
                    "registry_status": status,
                    "outcome": "state_condition_not_met",
                    "closest_miss": rule_ev.get("closest_miss"),
                }

        games_out[game_id] = {
            "pregame_built": game_ev.get("pregame_built"),
            "pregame_reason": game_ev.get("pregame_reason"),
            "ticks_seen": game_ev.get("ticks_seen", 0),
            "rules": rules_out,
        }

    return {
        "kind": "WINDOW_EVIDENCE",
        "sport": sport,
        "date": date,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "ticks": ticks,
        "stopped_reason": stopped_reason,
        "games": games_out,
    }


def record_window_evidence(sport, artifact: dict, *, path=None) -> bool:
    """Append the end-of-window evidence artifact to
    `data/live/<sport>/window_evidence.jsonl`, one JSON line per window --
    same append-only store convention as `record_window_gaps` (SEAM NOTE
    there applies here too: this is a small store of its own rather than a
    reach into `src/appstate/live_ledger.py`, owned elsewhere this pass).

    Never raises: a failed evidence write must not stop `run()` from
    returning its result. Returns True on success, False on any failure.
    """
    target = Path(path) if path is not None else Path(data_path("live", sport, "window_evidence.jsonl"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(artifact, sort_keys=True) + "\n")
        return True
    except Exception as exc:
        LOG.exception("record_window_evidence failed: %s", exc)
        return False


def run(sport, *, max_minutes=330, clock=None, sleep=None, deps=None,
        commit=None, commit_every_minutes=5) -> dict:
    """Main loop: poll, evaluate, capture until max_minutes or no live games nearby.

    Args:
        sport: "mlb" or "nfl".
        max_minutes: Max runtime.
        clock: Callable returning UTC datetime.
        sleep: Callable(seconds).
        deps: Injected dependencies.
        commit: Callable() to commit state.
        commit_every_minutes: Commit interval.

    Returns:
        {"sport", "ticks", "candidates_new", "credits", "stopped_reason"}.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    sleep = sleep or __import__("time").sleep
    deps = deps or {}

    start_time = clock()
    start_epoch = start_time.timestamp()
    last_commit_epoch = start_epoch

    # Cadence. MLB polls every 20 seconds (R16-L5, docs/LIVE_BETTING_SYSTEM.md
    # 3.2) -- the Stats API publishes no rate limit and the schedule call
    # already hydrates the linescore (see livefeed_mlb.poll), so a 20-second
    # poll stays well under the "1 a second" ceiling that section sets.
    cadence_seconds = 20 if sport == "mlb" else 300

    # Get today's date
    if sport == "mlb":
        et_tz = livefeed_mlb._EASTERN
        date_str = start_time.astimezone(et_tz).strftime("%Y-%m-%d")
    else:
        et_tz = livefeed_nfl._EASTERN
        date_str = start_time.astimezone(et_tz).strftime("%Y-%m-%d")

    # Load pregame context
    pregame = pregame_context(sport, date_str)

    # R16-L5 (3.2 "Window handoffs"): snapshot the LAST state row this
    # sport/date has on disk for every game BEFORE this window polls
    # anything itself. If a prior window (or this one, restarted) left
    # rows, and this window's own first poll picks the same games up later
    # than one poll interval after that, the gap between them is a real,
    # uncovered span of live minutes -- recorded once, right after the
    # first tick, rather than silently absent from the record.
    if sport == "mlb":
        previous_last_states = livefeed_mlb.latest_states(date_str)
    elif sport == "nfl":
        previous_last_states = livefeed_nfl.latest_states(date_str)
    else:
        previous_last_states = {}
    previous_last_by_game = {
        game_id: row.get("observed_utc")
        for game_id, row in (previous_last_states or {}).items()
    }
    window_gap_recorded = not previous_last_by_game  # nothing to compare
    record_window_gaps_fn = deps.get("record_window_gaps", record_window_gaps)
    record_window_evidence_fn = deps.get("record_window_evidence", record_window_evidence)

    # Initialize state
    state = {
        "date": date_str,
        "prev_states": {},
        "prev_inplay": [],
        "pregame": pregame,
    }

    ticks = 0
    candidates_new = 0
    credits_spent = 0

    def _finish(reason: str) -> dict:
        """Build the result dict AND write the end-of-window evidence
        artifact, on every exit path -- including the trivial one where
        `max_minutes` is already elapsed before a single tick runs (`state`
        then has no "evidence"/"trigger_state" keys yet; `.get(..., {})`
        below still produces a valid, empty-games artifact rather than
        skipping the write). This is the fix itself: a window that emits
        zero candidates must still leave a record of what it evaluated.
        """
        result = {
            "sport": sport,
            "ticks": ticks,
            "candidates_new": candidates_new,
            "credits": credits_spent,
            "stopped_reason": reason,
        }
        try:
            artifact = build_window_evidence(
                sport, date=date_str, ticks=ticks,
                window_start_utc=start_time.isoformat(),
                window_end_utc=clock().isoformat(),
                evidence=state.get("evidence", {}),
                trigger_state=state.get("trigger_state", {}),
                stopped_reason=reason)
            record_window_evidence_fn(sport, artifact)
        except Exception as exc:
            LOG.exception("window evidence build/record failed: %s", exc)
        return result

    window_marker = Path(data_path("live", sport, "window.lock"))
    try:
        while True:
            now = clock()
            elapsed = (now.timestamp() - start_epoch) / 60
            if elapsed > max_minutes:
                return _finish(f"max_minutes ({max_minutes}) elapsed")

            # Write/refresh window marker
            try:
                window_marker.parent.mkdir(parents=True, exist_ok=True)
                expiry = (now + timedelta(minutes=30)).isoformat()
                window_marker.write_text(expiry, encoding="utf-8")
            except Exception as exc:
                LOG.warning("failed to write window marker: %s", exc)

            # One tick
            result = tick(sport, state=state, clock=clock, deps=deps)
            ticks += 1
            candidates_new += result.get("candidates_new", 0)

            # Window-gap check: only once, right after the first tick that
            # actually saw state (a WINDOW_GAP is about the span BEFORE this
            # window started polling, not anything that happens later).
            if not window_gap_recorded:
                current_first_states = (
                    livefeed_mlb.latest_states(date_str) if sport == "mlb"
                    else livefeed_nfl.latest_states(date_str) if sport == "nfl"
                    else {}
                )
                current_first_by_game = {
                    game_id: row.get("observed_utc")
                    for game_id, row in (current_first_states or {}).items()
                }
                if current_first_by_game:
                    gaps = compute_window_gaps(
                        previous_last_by_game, current_first_by_game,
                        poll_interval_s=cadence_seconds)
                    try:
                        record_window_gaps_fn(sport, gaps)
                    except Exception as exc:
                        LOG.exception("record_window_gaps failed: %s", exc)
                    window_gap_recorded = True

            # Commit if interval elapsed
            now_epoch = clock().timestamp()
            if commit and (now_epoch - last_commit_epoch) > commit_every_minutes * 60:
                try:
                    commit()
                    last_commit_epoch = now_epoch
                except Exception as exc:
                    LOG.exception("commit failed: %s", exc)

            # Check if anything is live or starting soon
            polled = result.get("polled", 0)
            if polled == 0:
                # Check if any game starts within 30 minutes
                game_starting_soon = False
                try:
                    if sport == "mlb":
                        # D8: use the same "live or starting soon" definition
                        # as should_dispatch -- a past start alone is not
                        # live, and only a future start counts toward the
                        # 30-minute window.
                        from src.providers import mlb as mlb_provider
                        games = mlb_provider.fetch_games(date_str) or []
                        game_starting_soon, _reason = _mlb_live_or_soon(games, now)
                    elif sport == "nfl":
                        if not livefeed_nfl.in_window(now):
                            return _finish("outside NFL broadcast window")
                        from src.providers import nfl as nfl_provider
                        games = nfl_provider.schedule_for_date(date_str) or []
                        for game in games:
                            start = game.get("start_utc")
                            if start:
                                try:
                                    start_dt = datetime.fromisoformat(
                                        start.replace("Z", "+00:00"))
                                    if start_dt.tzinfo is None:
                                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                                    if (start_dt - now).total_seconds() < 30 * 60:
                                        game_starting_soon = True
                                        break
                                except Exception:
                                    pass
                except Exception as exc:
                    LOG.exception("game check failed: %s", exc)

                if not game_starting_soon:
                    return _finish("no live games and nothing starts within 30 minutes")

            # Update state for next iteration
            if sport == "mlb":
                state["prev_states"] = livefeed_mlb.latest_states(date_str)
            elif sport == "nfl":
                state["prev_states"] = livefeed_nfl.latest_states(date_str)

            # Sleep
            sleep(cadence_seconds)

    finally:
        # Clean up window marker
        try:
            window_marker.unlink(missing_ok=True)
        except Exception:
            pass


def _local_window_marker_active(sport, now) -> bool:
    """Whether THIS process's own window-marker file says a window is active.

    Only ever true on the same runner that is (or recently was) actually
    running the window loop -- it writes and refreshes this file itself
    (see `run`, above). A different job's fresh checkout never has it, so
    this alone cannot detect a real window running on another runner; see
    `_gh_run_active` for that.
    """
    window_marker = Path(data_path("live", sport, "window.lock"))
    if not window_marker.exists():
        return False
    try:
        expiry_str = window_marker.read_text(encoding="utf-8").strip()
        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        return expiry_dt > now
    except Exception:
        return False


_GH_RUN_ACTIVE_STATUSES = frozenset(
    {"queued", "in_progress", "waiting", "pending", "requested"}
)


def _gh_run_active(sport, *, workflow="live-window.yml", run_cli=None) -> bool:
    """Best-effort check, via `gh`, for an already-active live-window run for this sport.

    Exists because the window-marker file above is local to the runner that
    wrote it: a *different* job (e.g. the forward-capture chain calling
    --should-dispatch every ~13 minutes) can never see it and would
    otherwise redispatch a doomed duplicate for the entire life of every
    real window. `live-window.yml` sets `run-name: live-window-<sport>`
    precisely so this can tell sports apart from `gh run list` output,
    which does not otherwise expose workflow_dispatch inputs.

    Fails open (False, i.e. "not running") on any error -- a missed
    detection costs one more wasted dispatch this cycle, which the
    workflow's own concurrency group (cancel-in-progress: false) safely
    cancels without ever touching a real in-progress run.
    """
    run_cli = run_cli or _gh_run_list
    try:
        runs = json.loads(run_cli(workflow))
    except Exception:
        return False
    prefix = f"live-window-{sport}"
    return any(
        isinstance(run, dict)
        and run.get("status") in _GH_RUN_ACTIVE_STATUSES
        and str(run.get("displayTitle", "")).startswith(prefix)
        for run in runs
    )


def _gh_run_list(workflow) -> str:
    result = subprocess.run(
        [
            "gh", "run", "list",
            "--workflow", workflow,
            "--json", "status,displayTitle",
            "--limit", "20",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout


def _mlb_live_or_soon(games, now) -> tuple[bool, str]:
    """D8 fix: whether any MLB game is live right now, or starts within 30 min.

    `games` are `mlb.parse_game()`-shaped records (what `mlb.fetch_games()`
    returns), each carrying `state` -- `mlb.game_state()`'s own coarse
    classification, which (per its docstring and `is_final`/`is_cancelled`)
    returns ONLY "final", "cancelled" or "pending"; there is no "live" value.
    So "live" here is derived, not read off a field: a game's start time is
    in the past AND its state is neither "final" nor "cancelled" (i.e.
    "pending" while already underway -- the API leaves a game "pending"
    through the whole in-progress span, only flipping to "final" at the
    end). A past start with state "final"/"cancelled" is correctly NOT live.
    Only a FUTURE start counts toward the 30-minute window: the old code
    treated any past start time as "starts within 30 minutes", which kept
    windows dispatching and running long after every game had ended
    (docs/LIVE_BETTING_SYSTEM.md D8).
    """
    for game in games or []:
        start = game.get("start_time_utc")
        state = game.get("state")
        start_dt = None
        if start:
            try:
                start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                start_dt = None

        if start_dt is not None and start_dt <= now:
            if state not in ("final", "cancelled"):
                return (True, "MLB game is live")
            continue

        if start_dt is not None and (start_dt - now).total_seconds() < 30 * 60:
            return (True, "MLB game starts within 30 minutes")

    return (False, "no live games and nothing starts within 30 minutes")


def should_dispatch(sport, *, now=None, schedule=None, running=None) -> tuple[bool, str]:
    """Check if this sport's live window should run right now.

    Args:
        sport: "mlb" or "nfl".
        now: Current UTC datetime.
        schedule: Callable for fetching schedule.
        running: Callable checking if window is already running (reads marker file).

    Returns:
        (bool, str): (should_run, reason).
    """
    now = now or datetime.now(timezone.utc)

    # Check NFL window
    if sport == "nfl":
        if not livefeed_nfl.in_window(now):
            return (False, "outside NFL broadcast window (Thu 19-23, Sun 12-23, Mon 19-23 ET)")

    # Check if already running
    if running is None:
        def _check_running():
            return _local_window_marker_active(sport, now) or _gh_run_active(sport)
        running = _check_running

    if running():
        return (False, "window already running")

    # Check if game is live or starts within 30 minutes
    try:
        if sport == "mlb":
            from src.providers import mlb as mlb_provider
            if schedule is None:
                schedule = mlb_provider.fetch_games
            # Get today's date in ET
            et_tz = livefeed_mlb._EASTERN
            et_now = now.astimezone(et_tz)
            date_str = et_now.strftime("%Y-%m-%d")
            games = schedule(date_str) or []
        elif sport == "nfl":
            from src.providers import nfl as nfl_provider
            if schedule is None:
                schedule = nfl_provider.schedule_for_date
            et_tz = livefeed_nfl._EASTERN
            et_now = now.astimezone(et_tz)
            date_str = et_now.strftime("%Y-%m-%d")
            games = schedule(date_str) or []
        else:
            return (False, f"unknown sport {sport!r}")

        if sport == "mlb":
            # D8: live means start time in the past AND game_state() is
            # neither "final" nor "cancelled"; only a future start counts as
            # "within 30 minutes". See _mlb_live_or_soon.
            return _mlb_live_or_soon(games, now)

        for game in games:
            if sport == "nfl":
                # For NFL, check start_utc
                start = game.get("start_utc")
                if start:
                    try:
                        start_dt = datetime.fromisoformat(
                            start.replace("Z", "+00:00"))
                        if start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                        # Check if game started or will start
                        if start_dt <= now:
                            return (True, "NFL game is in progress or completed")
                    except Exception:
                        pass

            # Check if game starts within 30 minutes
            start = game.get("start_utc")

            if start:
                try:
                    start_dt = datetime.fromisoformat(
                        start.replace("Z", "+00:00"))
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    if (start_dt - now).total_seconds() < 30 * 60:
                        return (True, f"{sport.upper()} game starts within 30 minutes")
                except Exception:
                    pass

        return (False, "no live games and nothing starts within 30 minutes")

    except Exception as exc:
        return (False, f"schedule check failed: {exc}")


def settle(date, *, results=None) -> dict:
    """Settle live candidates for a date against final results.

    Args:
        date: ET date (YYYY-MM-DD).
        results: {game_id: {home_score, away_score}} or None (auto-read).

    Returns:
        Result from live_ledger.settle().
    """
    if results is None:
        results = {}
        # MLB finals
        try:
            mlb_states = livefeed_mlb.read_states(date)
            for row in mlb_states:
                if row.get("status") == "Final":
                    game_pk = row.get("game_pk")
                    if game_pk:
                        results[str(game_pk)] = {
                            "home_score": row.get("home_runs"),
                            "away_score": row.get("away_runs"),
                        }
        except Exception as exc:
            LOG.warning("MLB final read failed: %s", exc)

        # NFL finals
        try:
            nfl_states = livefeed_nfl.read_states(date)
            for row in nfl_states:
                if row.get("completed"):
                    event_id = row.get("event_id")
                    if event_id:
                        results[event_id] = {
                            "home_score": row.get("home_score"),
                            "away_score": row.get("away_score"),
                        }
        except Exception as exc:
            LOG.warning("NFL final read failed: %s", exc)

    return live_ledger.settle(date, results)


def main(argv):
    """Command-line entry point.

    Usage:
        --sport mlb|nfl
        --max-minutes N (default 330)
        --should-dispatch (print DISPATCH or HOLD <reason>, exit 0)
        --settle --date YYYY-MM-DD (settle candidates, exit 0)
    """
    import argparse

    parser = argparse.ArgumentParser(description="Live window runner")
    # --sport is required to RUN a window or check dispatch, not to settle:
    # settle grades every sport's candidates for the date. The daily loop
    # calls `--settle --date D` with no sport, and a required flag failed
    # that step every morning.
    parser.add_argument("--sport", required=False, choices=["mlb", "nfl"])
    parser.add_argument("--max-minutes", type=int, default=330)
    parser.add_argument("--should-dispatch", action="store_true")
    parser.add_argument("--settle", action="store_true")
    parser.add_argument("--date", default=None)

    args = parser.parse_args(argv[1:])

    if not args.settle and not args.sport:
        parser.error("--sport is required unless --settle is given")

    if args.should_dispatch:
        can_run, reason = should_dispatch(args.sport)
        print("DISPATCH" if can_run else f"HOLD {reason}")
        return 0

    if args.settle:
        if not args.date:
            print("ERROR: --settle requires --date", file=sys.stderr)
            return 1
        result = settle(args.date)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("No unsettled candidates for this date")
        return 0

    # Main loop
    def _commit():
        """Stage, commit AND PUSH the live stores.

        The first version committed and stopped. On the Actions runner a
        commit that is never pushed is deleted with the job, so every live
        row of the night would have been lost while the log said
        "committed". Same discipline as scripts/capture_slot.sh: identity
        set on the runner, rebase onto whatever the capture chain pushed
        meanwhile, push, three attempts.
        """
        import subprocess

        def _git(*argv, check=False):
            return subprocess.run(["git", *argv], capture_output=True,
                                  text=True, check=check)

        if not _git("config", "--get", "user.email").stdout.strip():
            _git("config", "user.name", "live-window-bot")
            _git("config", "user.email", "actions@users.noreply.github.com")
        # R16-L4 (D7): stage only data/live (which now holds this window's
        # own credit_log_live.jsonl, see live_odds.DEFAULT_CREDIT_LOG_PATH)
        # and the live ledger. NEVER data/processed/credit_log.jsonl -- the
        # forward-capture chain commits and pushes that file on its own
        # ~13-minute cadence, and staging it here is exactly the two-writer
        # conflict D7 describes (both runners racing `pull --rebase` on the
        # same path).
        _git("add", "data/live", "evidence/live_candidates_v1.jsonl")
        if _git("diff", "--cached", "--quiet").returncode == 0:
            return True  # nothing new since the last commit
        stamp = datetime.now(timezone.utc).strftime("%H:%MZ")
        committed = _git("commit", "-q", "-m",
                         f"Live window {args.sport} {stamp} (external)")
        if committed.returncode != 0:
            LOG.error("live_window: git commit failed: %s", committed.stderr.strip())
            return False
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
        for attempt in range(3):
            pulled = _git("pull", "-q", "--rebase", "--autostash", "origin", branch)
            if pulled.returncode != 0:
                _git("rebase", "--abort")
                LOG.error("live_window: rebase failed (attempt %d): %s",
                          attempt + 1, pulled.stderr.strip())
                continue
            pushed = _git("push", "-q", "origin", branch)
            if pushed.returncode == 0:
                return True
            LOG.error("live_window: push failed (attempt %d): %s",
                      attempt + 1, pushed.stderr.strip())
        return False

    commit_fn = _commit if os.environ.get("LIVE_WINDOW_COMMIT") == "1" else None

    result = run(args.sport, max_minutes=args.max_minutes, commit=commit_fn)
    if commit_fn is not None:
        # The rows written since the last five-minute commit, and the
        # window marker's removal, go out with the job -- not with the next one.
        commit_fn()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
