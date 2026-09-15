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

    # For MLB
    if sport == "mlb" and games:
        for game in games:
            game_pk = str(game.get("game_pk"))
            if not game_pk:
                continue

            home_team = (game.get("teams", {}).get("home", {}).get("team", {}).get("name"))
            away_team = (game.get("teams", {}).get("away", {}).get("team", {}).get("name"))
            start_utc = game.get("start_time_utc")

            # Get probable pitcher IDs
            starter_ids = {}
            home_prob = game.get("teams", {}).get("home", {}).get("probablePitcher")
            away_prob = game.get("teams", {}).get("away", {}).get("probablePitcher")
            if home_prob and home_prob.get("id"):
                starter_ids["home"] = home_prob.get("id")
            if away_prob and away_prob.get("id"):
                starter_ids["away"] = away_prob.get("id")

            # Get favourite from pre-game quotes for this game
            game_rows = [r for r in (rows or [])
                        if r.get("home_team") == home_team
                        and r.get("away_team") == away_team]
            if game_rows:
                # Use newest row for this game
                newest_row = max(game_rows, key=lambda r: r.get("observed_utc", ""))
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

            # Find event_id for this game
            event_id = None
            for eid, mapping in (event_map or {}).items():
                mapped_pk = mapping.get("game_pk")
                if mapped_pk == game_pk:
                    event_id = eid
                    break
                try:
                    if mapped_pk == int(game_pk):
                        event_id = eid
                        break
                except (ValueError, TypeError):
                    pass

            context[game_pk] = {
                "sport": "mlb",
                "game_id": game_pk,
                "home_team": home_team,
                "away_team": away_team,
                "favorite": favorite,
                "favorite_prob": favorite_prob,
                "starter_ids": starter_ids,
                "kickoff_utc": start_utc,
                "event_id": event_id,
            }

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
    """One iteration: poll state, capture odds on change, evaluate rules, record candidates.

    Args:
        sport: "mlb" or "nfl".
        state: {"prev_states": dict, "prev_inplay": dict, "pregame": dict, "date": str}.
        clock: Callable returning UTC datetime.
        deps: Injected dependencies (poll, capture, evaluate, record functions).

    Returns:
        {"polled": int, "changed": int, "captured": int, "candidates_new": int, "errors": int}
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    deps = deps or {}

    # Injected functions
    poll_fn = deps.get("poll")
    capture_fn = deps.get("capture", live_odds.capture_inplay)
    evaluate_fn = deps.get("evaluate", live_rules.evaluate_all)
    record_fn = deps.get("record", live_ledger.record_candidate)

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

    # Detect changed games
    changed = []
    if new_states:
        try:
            for game_id, new_state in new_states.items():
                prev_state = state.get("prev_states", {}).get(game_id)
                should_cap, reason = live_odds.should_capture(prev_state, new_state)
                if should_cap:
                    changed.append((game_id, reason, new_state))
        except Exception as exc:
            LOG.exception("change detection failed: %s", exc)

    # Capture odds for changed games (one call covers all changed games)
    captured = 0
    if changed:
        try:
            # Create a state_snapshot_id from the current time
            now_utc = clock().isoformat()
            state_snapshot_id = hashlib.sha1(
                f"{sport}|{now_utc}".encode()).hexdigest()[:16]

            # Call capture_inplay once per tick with all changes
            capture_result = capture_fn(
                sport, state_snapshot_id=state_snapshot_id,
                reason="; ".join(r[1] for r in changed),
                env=deps.get("env"))
            captured = capture_result.get("captured", 0)
        except Exception as exc:
            LOG.exception("capture_inplay failed: %s", exc)

    # Read in-play quotes and evaluate rules
    candidates_new = 0
    try:
        inplay_rows = live_odds.read_inplay(sport=sport)
        pregame_context = state.get("pregame", {})

        for game_id, reason, new_state in changed:
            if game_id not in pregame_context:
                continue

            pgame = pregame_context[game_id]
            quote = live_odds.latest_inplay_quote(inplay_rows, pgame.get("event_id"))

            # Evaluate rules
            candidates = evaluate_fn(pregame=pgame, state=new_state, quote=quote)
            for candidate in candidates:
                try:
                    result = record_fn(candidate)
                    if result is not None:
                        candidates_new += 1
                except Exception as exc:
                    LOG.exception("record_candidate failed: %s", exc)

    except Exception as exc:
        LOG.exception("rule evaluation failed: %s", exc)

    return {
        "polled": polled,
        "changed": len(changed),
        "captured": captured,
        "candidates_new": candidates_new,
        "errors": 0,
    }


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

    # Cadence
    cadence_seconds = 60 if sport == "mlb" else 300

    # Get today's date
    if sport == "mlb":
        et_tz = livefeed_mlb._EASTERN
        date_str = start_time.astimezone(et_tz).strftime("%Y-%m-%d")
    else:
        et_tz = livefeed_nfl._EASTERN
        date_str = start_time.astimezone(et_tz).strftime("%Y-%m-%d")

    # Load pregame context
    pregame = pregame_context(sport, date_str)

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

    window_marker = Path(data_path("live", sport, "window.lock"))
    try:
        while True:
            now = clock()
            elapsed = (now.timestamp() - start_epoch) / 60
            if elapsed > max_minutes:
                return {
                    "sport": sport,
                    "ticks": ticks,
                    "candidates_new": candidates_new,
                    "credits": credits_spent,
                    "stopped_reason": f"max_minutes ({max_minutes}) elapsed",
                }

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
                        from src.providers import mlb as mlb_provider
                        games = mlb_provider.fetch_games(date_str) or []
                        for game in games:
                            start = game.get("start_time_utc")
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
                    elif sport == "nfl":
                        if not livefeed_nfl.in_window(now):
                            return {
                                "sport": sport,
                                "ticks": ticks,
                                "candidates_new": candidates_new,
                                "credits": credits_spent,
                                "stopped_reason": "outside NFL broadcast window",
                            }
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
                    return {
                        "sport": sport,
                        "ticks": ticks,
                        "candidates_new": candidates_new,
                        "credits": credits_spent,
                        "stopped_reason": "no live games and nothing starts within 30 minutes",
                    }

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

        for game in games:
            # Check if game is live
            if sport == "mlb":
                status = (game.get("status") or {}).get("abstractGameState")
                if status in ("Live", "Final"):
                    return (True, f"MLB game is {status}")
            elif sport == "nfl":
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
            if sport == "mlb":
                start = game.get("start_time_utc")
            else:
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
        _git("add", "data/live", "evidence/live_candidates_v1.jsonl",
             "data/processed/credit_log.jsonl")
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
