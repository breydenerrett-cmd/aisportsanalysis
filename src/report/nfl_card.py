"""The NFL card: published picks and their settlement record.

WHY THIS EXISTS
---------------
The card is the published opinion on a slate of games. It is read from either
the frozen ledger (historical) or from the live analysis (today). A card with
no picks is a real state -- see _empty_reason -- but nothing empty is frozen.
A frozen card is evidence and cannot be edited; a published version replaces
an older one only when the picks themselves change, never when just the
timestamp changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import nfl_card
from src.appstate import card_ledger
from src.pipeline import nfl_slate


def _empty_reason(entries: Optional[list]) -> str:
    """Why the card has no picks."""
    if not entries:
        return "No NFL games on this date."
    return "No NFL game cleared the bar for this date."


def card_for_date(date_str: str, *, now: Optional[datetime] = None,
                  entries: Optional[list] = None,
                  prefer_frozen: bool = True,
                  path: Optional[str] = None) -> dict:
    """The NFL card payload for one date, frozen or live.

    A frozen card comes from the ledger (historical data). A live card is
    built from entries and the current selection rule.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        entries: Live entry dicts (default: lazy nfl_slate.entries_for_date).
        prefer_frozen: Return frozen card if one exists (default: True).
        path: Card ledger path (default: sport-specific path).

    Returns:
        Card payload dict with date, sport, rule, picks, count, reason,
        experimental, notice, frozen, published_utc, generated_utc, week,
        games_considered.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Try frozen first if preferred
    if prefer_frozen:
        frozen = card_ledger.published_row(date_str, sport="nfl", path=path)
        if frozen:
            picks = frozen.get("picks") or []
            return {
                "date": date_str,
                "sport": "nfl",
                "rule": "NFL_CARD_V1",
                "picks": picks,
                "count": len(picks),
                "reason": None,
                "experimental": True,
                "notice": "Experimental selections. Performance is still being evaluated.",
                "frozen": True,
                "published_utc": frozen.get("published_utc"),
                "generated_utc": frozen.get("published_utc"),  # Same as published
                "week": frozen.get("week"),
                "games_considered": frozen.get("games_on_slate"),
            }

    # Build live card from entries
    if entries is None:
        entries = nfl_slate.entries_for_date(date_str, now=now)

    # Select picks
    picks = nfl_card.select(entries, now=now)

    # Determine week and games_considered from entries
    week = None
    games_considered = len(entries)
    if entries:
        week = entries[0].get("week")

    if picks:
        return {
            "date": date_str,
            "sport": "nfl",
            "rule": "NFL_CARD_V1",
            "picks": picks,
            "count": len(picks),
            "reason": None,
            "experimental": True,
            "notice": "Experimental selections. Performance is still being evaluated.",
            "frozen": False,
            "published_utc": None,
            "generated_utc": now.isoformat(),
            "week": week,
            "games_considered": games_considered,
        }
    else:
        return {
            "date": date_str,
            "sport": "nfl",
            "rule": "NFL_CARD_V1",
            "picks": [],
            "count": 0,
            "reason": _empty_reason(entries),
            "experimental": True,
            "notice": "Experimental selections. Performance is still being evaluated.",
            "frozen": False,
            "published_utc": None,
            "generated_utc": now.isoformat(),
            "week": week,
            "games_considered": games_considered,
        }


def publish_for_date(date_str: str, *, now: Optional[datetime] = None,
                     entries: Optional[list] = None,
                     path: Optional[str] = None) -> dict:
    """Publish one date's card to the ledger.

    An empty card is never published -- nothing empty is evidence. Returns
    {"published": False, "reason": ...} when the card has no picks.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        entries: Live entry dicts (default: lazy nfl_slate.entries_for_date).
        path: Card ledger path (default: sport-specific path).

    Returns:
        Published row if picks exist, or {"published": False, "reason": ...}.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    card = card_for_date(date_str, now=now, entries=entries,
                         prefer_frozen=False, path=path)

    if not card.get("picks"):
        return {
            "published": False,
            "reason": card.get("reason"),
        }

    # Publish to ledger
    row = card_ledger.publish(
        card, now=now.isoformat(), path=path, sport="nfl")

    return row


def settle_for_date(date_str: str, *, now: Optional[datetime] = None,
                    results: Optional[dict] = None,
                    path: Optional[str] = None) -> dict:
    """Settle one date's card with final results.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        results: {game_id: {home_score, away_score, completed}, ...}
                 (default: lazy nfl_slate.results_for_date).
        path: Card ledger path (default: sport-specific path).

    Returns:
        Settled row from card_ledger.settle().
    """
    # NOTHING TO GRADE, NOTHING TO FETCH. The scores endpoint costs credits
    # (2 with daysFrom) and the daily loop runs this every morning of the
    # year; without this check it bought scores on every day no NFL card was
    # published -- most days.
    if card_ledger.published_row(date_str, sport="nfl", path=path) is None:
        return None
    if card_ledger.settled_row(date_str, sport="nfl", path=path) is not None:
        return None

    if results is None:
        results = nfl_slate.results_for_date(date_str)

    # card_ledger.settle() writes `now` verbatim as the settled_utc field of
    # a hash-chained, JSON-serialized ledger row -- it only falls back to
    # datetime.now(timezone.utc).isoformat() itself when `now` is falsy, so a
    # raw datetime object (this function's own parameter type) reaches
    # json.dumps() unconverted and raises TypeError. publish_for_date already
    # stringifies before crossing this same boundary; settle_for_date must
    # too, for every caller that passes an explicit (e.g. fake/injected)
    # clock rather than relying on the default.
    return card_ledger.settle(date_str, results, sport="nfl",
                             now=now.isoformat() if now is not None else None,
                             path=path)
