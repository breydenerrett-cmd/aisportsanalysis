"""Live research candidates ledger. Hash-chained, append-only.

WHY THIS EXISTS
---------------
These are research candidates, never picks. They never appear on the card or
payoff record. A hash-chained ledger records every candidate and every
settlement, so the forward research plan can be audited and verified.

This module is isolated from card_ledger: no imports, no shared code paths.
The profit arithmetic is copied from card_ledger for this live context only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.ledger.chain import HashChainLedger
from src.paths import evidence_path

LIVE_STORE = os.path.join("evidence", "live_candidates_v1.jsonl")

KIND_CANDIDATE = "live_candidate"
KIND_SETTLED = "live_settled"

RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_PUSH = "PUSH"
RESULT_VOID = "VOID"


class LiveLedgerError(RuntimeError):
    pass


def _ledger(path: Optional[str] = None) -> HashChainLedger:
    return HashChainLedger(path or LIVE_STORE)


def _american_to_decimal(price: float) -> float:
    """Convert American odds to decimal odds.

    Positive price (underdog): decimal = 1.0 + (price / 100.0)
    Negative price (favorite): decimal = 1.0 + (100.0 / abs(price))
    """
    if price > 0:
        return 1.0 + (price / 100.0)
    return 1.0 + (100.0 / abs(price))


def _profit_at_price(price: int, won: bool) -> float:
    """Compute flat one-unit profit at American odds.

    Args:
        price: American odds (int).
        won: True if the bet won, False if lost.

    Returns:
        Profit in units: decimal - 1.0 if won, -1.0 if lost.
    """
    if won:
        try:
            return round(_american_to_decimal(price) - 1.0, 4)
        except (TypeError, ValueError):
            return 0.0
    return -1.0


def _et_date(utc_str: Optional[str]) -> str:
    """ET date (YYYY-MM-DD) from a UTC timestamp string.

    Uses fixed -4:00 offset for baseball season (DST is always in effect).
    """
    if not utc_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert to ET (fixed -4:00 for baseball season, DST always in effect)
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("America/New_York")
        except Exception:
            from datetime import timedelta
            et = timezone(timedelta(hours=-4))

        et_dt = dt.astimezone(et)
        return et_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record_candidate(candidate: Mapping, *, now: Optional[str] = None,
                    path: Optional[str] = None) -> Optional[dict]:
    """Record a live research candidate. Deduplicated per (rule_id, sport, game_id).

    Args:
        candidate: {"rule_id", "sport", "game_id", "side", "team", "bet",
                    "price", "books", "state_id", "observed_utc", "trigger"}.
        now: Recording timestamp (defaults to now).
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        The full row (payload + chain fields), or None if this (rule_id,
        sport, game_id) already exists in the ledger.
    """
    rule_id = candidate.get("rule_id")
    sport = candidate.get("sport")
    game_id = candidate.get("game_id")

    # Check for existing candidate with same (rule_id, sport, game_id)
    ledger = _ledger(path)
    for row in ledger.read():
        if (row.get("kind") == KIND_CANDIDATE and
            row.get("rule_id") == rule_id and
            row.get("sport") == sport and
            row.get("game_id") == game_id):
            return None  # Already recorded

    # Build and append new candidate
    observed_utc = candidate.get("observed_utc")
    date = _et_date(observed_utc)

    payload = {
        "kind": KIND_CANDIDATE,
        "recorded_utc": now or datetime.now(timezone.utc).isoformat(),
        "date": date,
        "rule_id": rule_id,
        "sport": sport,
        "game_id": game_id,
        "side": candidate.get("side"),
        "team": candidate.get("team"),
        "bet": candidate.get("bet"),
        "price": candidate.get("price"),
        "books": candidate.get("books"),
        "state_id": candidate.get("state_id"),
        "observed_utc": observed_utc,
        "trigger": candidate.get("trigger"),
    }

    return ledger.append(payload)


def candidates(*, date: Optional[str] = None,
              path: Optional[str] = None) -> list[dict]:
    """List all recorded candidates, optionally filtered by ET date.

    Args:
        date: ET date filter (YYYY-MM-DD), or None for all.
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        List of candidate rows (kind == KIND_CANDIDATE).
    """
    ledger = _ledger(path)
    result = []
    for row in ledger.read():
        if row.get("kind") != KIND_CANDIDATE:
            continue
        if date is not None and row.get("date") != date:
            continue
        result.append(row)
    return result


def unsettled(*, date: Optional[str] = None,
             path: Optional[str] = None) -> list[dict]:
    """List unsettled candidates for a date.

    Args:
        date: ET date (YYYY-MM-DD).
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        List of candidates with no corresponding settlement row.
    """
    if not date:
        return []

    ledger = _ledger(path)
    settled_keys = set()
    for row in ledger.read():
        if row.get("kind") == KIND_SETTLED and row.get("date") == date:
            key = (row.get("rule_id"), row.get("sport"), row.get("game_id"))
            settled_keys.add(key)

    result = []
    for row in ledger.read():
        if row.get("kind") != KIND_CANDIDATE or row.get("date") != date:
            continue
        key = (row.get("rule_id"), row.get("sport"), row.get("game_id"))
        if key not in settled_keys:
            result.append(row)
    return result


def settle(date: str, results_by_game_id: Mapping, *,
          now: Optional[str] = None, path: Optional[str] = None) -> Optional[dict]:
    """Settle candidates for a date. Grade each against results.

    Args:
        date: ET date (YYYY-MM-DD).
        results_by_game_id: {game_id or str(game_id): {"home_score", "away_score"}}.
        now: Settlement timestamp (defaults to now).
        path: Ledger path (defaults to LIVE_STORE).

    Returns:
        Summary dict: {date, graded, wins, losses, pushes, voids, units, by_rule},
        or None if no unsettled candidates.
    """
    unsettled_list = unsettled(date=date, path=path)
    if not unsettled_list:
        return None

    ledger = _ledger(path)
    graded = []
    wins = losses = pushes = voids = 0
    units = 0.0
    by_rule = {}

    for candidate in unsettled_list:
        game_id = candidate.get("game_id")
        result = (results_by_game_id.get(game_id) or
                 results_by_game_id.get(str(game_id)) or {})

        home_score = result.get("home_score")
        away_score = result.get("away_score")

        # Check for valid scores
        try:
            home = int(home_score) if home_score is not None else None
            away = int(away_score) if away_score is not None else None
        except (TypeError, ValueError):
            home = away = None

        side = candidate.get("side")
        price = candidate.get("price")

        # Grade: determine result and profit
        if home is None or away is None:
            result_code = RESULT_VOID
            profit = 0.0
            reason = "no final score"
        else:
            # Determine winner: did the candidate side win?
            if side == "home":
                won = home > away
            elif side == "away":
                won = away > home
            else:
                result_code = RESULT_VOID
                profit = 0.0
                reason = f"unknown side {side!r}"

            if home == away:
                result_code = RESULT_PUSH
                profit = 0.0
                reason = "game ended in tie"
            else:
                result_code = RESULT_WIN if won else RESULT_LOSS
                profit = _profit_at_price(price, won)

        # Record settlement
        settled_row = ledger.append({
            "kind": KIND_SETTLED,
            "settled_utc": now or datetime.now(timezone.utc).isoformat(),
            "date": date,
            "rule_id": candidate.get("rule_id"),
            "sport": candidate.get("sport"),
            "game_id": game_id,
            "side": candidate.get("side"),
            "price": price,
            "result": result_code,
            "profit_units": profit,
        })

        graded.append(settled_row)

        # Tally
        if result_code == RESULT_WIN:
            wins += 1
            units += profit
        elif result_code == RESULT_LOSS:
            losses += 1
            units += profit
        elif result_code == RESULT_PUSH:
            pushes += 1
        elif result_code == RESULT_VOID:
            voids += 1

        # By rule
        rule_id = candidate.get("rule_id")
        if rule_id not in by_rule:
            by_rule[rule_id] = {"wins": 0, "losses": 0, "pushes": 0, "voids": 0, "units": 0.0}
        slot = by_rule[rule_id]
        if result_code == RESULT_WIN:
            slot["wins"] += 1
            slot["units"] += profit
        elif result_code == RESULT_LOSS:
            slot["losses"] += 1
            slot["units"] += profit
        elif result_code == RESULT_PUSH:
            slot["pushes"] += 1
        elif result_code == RESULT_VOID:
            slot["voids"] += 1

    for slot in by_rule.values():
        slot["units"] = round(slot["units"], 4)

    return {
        "date": date,
        "graded": len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "units": round(units, 4),
        "by_rule": by_rule,
    }


def record(*, path: Optional[str] = None) -> dict:
    """Full record: all candidates, all settlements, summary stats.

    Returns:
        {"candidates", "settled", "wins", "losses", "pushes", "voids",
         "units", "by_rule": {rule_id: {...counts...}}}.
    """
    ledger = _ledger(path)

    candidates_list = []
    settled_list = []

    for row in ledger.read():
        if row.get("kind") == KIND_CANDIDATE:
            candidates_list.append(row)
        elif row.get("kind") == KIND_SETTLED:
            settled_list.append(row)

    wins = losses = pushes = voids = 0
    units = 0.0
    by_rule = {}

    for row in settled_list:
        result = row.get("result")
        profit = row.get("profit_units", 0.0)
        rule_id = row.get("rule_id")

        if result == RESULT_WIN:
            wins += 1
            units += profit
        elif result == RESULT_LOSS:
            losses += 1
            units += profit
        elif result == RESULT_PUSH:
            pushes += 1
        elif result == RESULT_VOID:
            voids += 1

        if rule_id not in by_rule:
            by_rule[rule_id] = {"wins": 0, "losses": 0, "pushes": 0, "voids": 0, "units": 0.0}
        slot = by_rule[rule_id]
        if result == RESULT_WIN:
            slot["wins"] += 1
            slot["units"] += profit
        elif result == RESULT_LOSS:
            slot["losses"] += 1
            slot["units"] += profit
        elif result == RESULT_PUSH:
            slot["pushes"] += 1
        elif result == RESULT_VOID:
            slot["voids"] += 1

    for slot in by_rule.values():
        slot["units"] = round(slot["units"], 4)

    return {
        "candidates": len(candidates_list),
        "settled": len(settled_list),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "units": round(units, 4),
        "by_rule": by_rule,
    }


def history(*, path: Optional[str] = None, limit: int = 50) -> list[dict]:
    """All candidates, newest first, with settlement if available.

    Args:
        path: Ledger path (defaults to LIVE_STORE).
        limit: Maximum results (default 50).

    Returns:
        List of candidates with 'settlement' field (dict or None), newest first.
    """
    ledger = _ledger(path)

    settled_by_key = {}
    for row in ledger.read():
        if row.get("kind") == KIND_SETTLED:
            key = (row.get("rule_id"), row.get("sport"), row.get("game_id"))
            settled_by_key[key] = row

    candidates_list = []
    for row in ledger.read():
        if row.get("kind") == KIND_CANDIDATE:
            candidates_list.append(row)

    # Sort newest first
    candidates_list.sort(key=lambda r: r.get("observed_utc") or "", reverse=True)

    result = []
    for candidate in candidates_list[:limit]:
        key = (candidate.get("rule_id"), candidate.get("sport"), candidate.get("game_id"))
        settlement = settled_by_key.get(key)
        result.append({
            **candidate,
            "settlement": settlement,
        })

    return result


def verify(*, path: Optional[str] = None):
    """Verify the chain integrity.

    Returns:
        VerifyResult from HashChainLedger.verify().
    """
    return _ledger(path).verify()
