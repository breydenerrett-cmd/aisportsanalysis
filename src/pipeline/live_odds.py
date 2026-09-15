"""Event-driven in-play odds capture triggered by game state changes.

WHY THIS EXISTS
---------------
In-play prices are the most time-sensitive data this project collects. A game
state changes (score, inning, pitcher) every few minutes; capturing on every
change keeps the ledger accurate and spends credits only when new information
exists. A credit cap of 300/day per sports prevents runaway spend on a feature
still being researched; a kill switch env variable (`LIVE_ODDS`) defaults to
OFF, protecting the main capture envelope from a feature flag left on by mistake.

Design: `should_capture()` is a pure state-change detector (MBA, inning, pitcher,
score); `changed_games()` batches it across a slate; `capture_inplay()` enforces
budget guards, fetches normalized odds, filters to commence_time <= now, writes
rows, and logs credits exactly once per capture moment.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.paths import data_path
from src.pipeline import creditlog

LOG = logging.getLogger(__name__)

DEFAULT_INPLAY_PATH = data_path("live", "odds_inplay.jsonl")
CALLER = "live_odds.capture_inplay"
BAND = "live_odds"
DEFAULT_MARKETS = ("h2h",)


def should_capture(prev, new) -> tuple[bool, str]:
    """Pure. Decide whether to fetch odds given a state transition.

    Captures on:
    - First observation (prev is None)
    - Final/completed status
    - MLB: score, inning, half-inning, pitcher change
    - NFL: score, game completed
    - Otherwise: no capture

    Returns (allowed, reason) where allowed is bool and reason is descriptive.
    """
    if new is None:
        return (False, "new state is None")

    sport = new.get("sport", "mlb")

    # Check if game is final/completed
    if sport == "mlb":
        if new.get("status") == "final":
            return (False, "final")
    elif sport == "nfl":
        if new.get("completed"):
            return (False, "completed")

    # First observation
    if prev is None:
        return (True, "first observation")

    # No changes possible from here
    if prev is None or new is None:
        return (False, "missing state")

    # Compare states by sport
    if sport == "mlb":
        # Score change
        prev_home_runs = prev.get("home_runs")
        new_home_runs = new.get("home_runs")
        prev_away_runs = prev.get("away_runs")
        new_away_runs = new.get("away_runs")

        if prev_home_runs != new_home_runs or prev_away_runs != new_away_runs:
            return (True, "score")

        # Inning change
        if prev.get("inning") != new.get("inning"):
            return (True, "inning")

        # Half-inning change (top/bottom)
        if prev.get("half") != new.get("half"):
            return (True, "half")

        # Pitcher change
        if prev.get("pitcher_id") != new.get("pitcher_id"):
            return (True, "pitching change")

    elif sport == "nfl":
        # Score change
        prev_home_score = prev.get("home_score")
        new_home_score = new.get("home_score")
        prev_away_score = prev.get("away_score")
        new_away_score = new.get("away_score")

        if prev_home_score != new_home_score or prev_away_score != new_away_score:
            return (True, "score")

    return (False, "no change")


def changed_games(prev_states: dict, new_states: dict) -> list[tuple]:
    """Find all games that changed between two state snapshots.

    prev_states and new_states are dicts keyed by game_id mapping to state rows.
    Returns list of (game_id, reason) tuples for games where should_capture()
    returns True.
    """
    result = []

    # Check all games in new_states
    for game_id, new_state in (new_states or {}).items():
        prev_state = (prev_states or {}).get(game_id)
        should_cap, reason = should_capture(prev_state, new_state)
        if should_cap:
            result.append((game_id, reason))

    return result


def capture_inplay(sport, *, state_snapshot_id, reason, env=None,
                   markets=DEFAULT_MARKETS, fetch_normalized=None,
                   spend_guard=None, quota=None, record_credit=None,
                   clock=None, path=DEFAULT_INPLAY_PATH) -> dict:
    """Capture in-play odds for active games, subject to budget constraints.

    Budget guard (spend_guard) is checked first: if it refuses, nothing is
    fetched and the function returns {"captured": 0, "refused": reason, "credits": 0}.

    If allowed, fetch_normalized is called (default: lazy import of
    odds_provider.fetch_normalized) to get normalized odds. Only events with
    commence_time <= now are kept (in-play filter). For each h2h quote in
    all_books, one row is written:
        {observed_utc, sport, event_id, commence_time, home_team, away_team,
         market "h2h", book, home_price, away_price, in_play True,
         state_snapshot_id, trigger: reason}

    Credits are logged once via record_credit (default: lazy import of
    creditlog.log) with budget_band=BAND and caller=CALLER.

    Returns {"captured": count, "events_in_play": n, "credits": est,
             "path": str} on success, or {"captured": 0, "refused": reason,
             "credits": 0} if spend_guard refused.
    """
    now = (clock or datetime.now)(timezone.utc) if callable(clock) else datetime.now(timezone.utc)

    # Default spend_guard: lazy import of can_spend_live_odds
    if spend_guard is None:
        try:
            from src.capture import budget as budget_module
            est = len(markets)
            spend_guard_result = budget_module.can_spend_live_odds(
                est, now=now, env=env)
            if not spend_guard_result.allowed:
                return {
                    "captured": 0,
                    "refused": spend_guard_result.reason,
                    "credits": 0
                }
        except (ImportError, AttributeError):
            return {
                "captured": 0,
                "refused": "live odds budget unavailable",
                "credits": 0
            }

    # Check spend_guard if it was provided
    if spend_guard is not None:
        # spend_guard should be a Decision-like object with allowed/reason
        if hasattr(spend_guard, 'allowed'):
            if not spend_guard.allowed:
                return {
                    "captured": 0,
                    "refused": spend_guard.reason,
                    "credits": 0
                }
        else:
            # If it's a callable, call it
            guard_decision = spend_guard()
            if not guard_decision.allowed:
                return {
                    "captured": 0,
                    "refused": guard_decision.reason,
                    "credits": 0
                }

    # Default fetch_normalized: lazy import
    if fetch_normalized is None:
        try:
            from src.providers import odds as odds_provider
            fetch_normalized = odds_provider.fetch_normalized
        except (ImportError, AttributeError):
            return {
                "captured": 0,
                "refused": "odds provider fetch unavailable",
                "credits": 0
            }

    # Fetch odds
    try:
        response = fetch_normalized(markets=list(markets), env=env, sport=sport)
    except Exception as exc:
        LOG.debug("live_odds.capture_inplay: fetch failed: %s", exc)
        return {
            "captured": 0,
            "refused": f"fetch failed: {exc}",
            "credits": 0
        }

    events = response.get("events") or []
    observed_utc = (response.get("fetched_utc") or
                   now.isoformat()).replace("+00:00", "Z")

    # Filter to in-play events (commence_time <= now)
    rows_to_write = []
    events_in_play = 0

    for event in events:
        commence_time = event.get("commence_time")
        if not commence_time:
            continue

        # Parse commence_time
        try:
            commence_dt = datetime.fromisoformat(
                str(commence_time).replace("Z", "+00:00"))
            if commence_dt.tzinfo is None:
                commence_dt = commence_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        # Check if in-play (commenced already)
        if commence_dt > now:
            continue

        events_in_play += 1
        event_id = event.get("event_id")
        home_team = event.get("home_team")
        away_team = event.get("away_team")

        # Extract h2h quotes from all_books
        h2h_books = event.get("all_books", {}).get("h2h", [])
        for quote in h2h_books:
            row = {
                "observed_utc": observed_utc,
                "sport": sport,
                "event_id": event_id,
                "commence_time": commence_time,
                "home_team": home_team,
                "away_team": away_team,
                "market": "h2h",
                "book": quote.get("book"),
                "home_price": quote.get("home_price"),
                "away_price": quote.get("away_price"),
                "in_play": True,
                "state_snapshot_id": state_snapshot_id,
                "trigger": reason,
            }
            rows_to_write.append(row)

    # Write rows
    captured = 0
    if rows_to_write:
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                for row in rows_to_write:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
            captured = len(rows_to_write)
        except Exception as exc:
            LOG.debug("live_odds.capture_inplay: write failed: %s", exc)

    # Log credits
    est = len(markets)
    if record_credit is None:
        # Lazy import creditlog.log
        record_credit = creditlog.log

    try:
        # Get remaining from quota if available, else None
        remaining = None
        if quota is not None:
            remaining = quota.get("remaining") if isinstance(quota, dict) else None

        record_credit(remaining, None, CALLER, budget_band=BAND)
    except Exception as exc:
        LOG.debug("live_odds.capture_inplay: credit log failed: %s", exc)

    return {
        "captured": captured,
        "events_in_play": events_in_play,
        "credits": est,
        "path": str(path)
    }


def read_inplay(path=DEFAULT_INPLAY_PATH, *, sport=None, event_id=None) -> list:
    """Read stored in-play odds, optionally filtered by sport and/or event_id."""
    target = Path(path)
    if not target.exists():
        return []

    rows = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                # Apply filters
                if sport is not None and row.get("sport") != sport:
                    continue
                if event_id is not None and row.get("event_id") != event_id:
                    continue
                rows.append(row)
            except json.JSONDecodeError:
                LOG.warning("read_inplay: malformed JSON at %s", target)
    except Exception as exc:
        LOG.warning("read_inplay: failed to read %s: %s", target, exc)

    return rows


def latest_inplay_quote(rows, event_id) -> Optional[dict]:
    """Return the newest batch of h2h quotes for an event.

    Groups rows by observed_utc, returns the dict with newest observed_utc
    and a "quotes" key containing all book quotes from that batch.
    """
    if not rows:
        return None

    # Filter to matching event_id
    matching = [r for r in rows if r.get("event_id") == event_id]
    if not matching:
        return None

    # Group by observed_utc, sort descending (newest first)
    by_utc = {}
    for row in matching:
        utc = row.get("observed_utc")
        if utc not in by_utc:
            by_utc[utc] = []
        by_utc[utc].append(row)

    # Get the newest
    newest_utc = max(by_utc.keys())
    newest_batch = by_utc[newest_utc]

    # Extract just the quotes
    quotes = []
    for row in newest_batch:
        quote = {
            "book": row.get("book"),
            "home_price": row.get("home_price"),
            "away_price": row.get("away_price"),
        }
        quotes.append(quote)

    return {
        "observed_utc": newest_utc,
        "quotes": quotes
    }
