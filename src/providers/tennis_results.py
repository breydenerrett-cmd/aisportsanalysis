"""Results-feed adapter interface for tennis.

WHY THIS EXISTS
---------------
Tennis results are not bundled with any free odds API. The product will eventually
buy a results feed from a commercial provider. Until that feed is connected, tennis
shows only as research and never grades a tennis pick. This module makes the future
feed a plug-in: a feed writer implements the ResultsFeed interface, the harness
picks it up from TENNIS_RESULTS_PROVIDER, and the rest of the system can call
results_for() without knowing which source is live.

POINT-IN-TIME BY CONSTRUCTION
-----------------------------
Every result row carries a completed_utc timestamp. A date filter then becomes a
simple substring check, making point-in-time queries replay-safe: what we see on
September 14 must be exactly what was visible on September 14, regardless of when
we ask. This is the same design that mlb_news.py uses.
"""

from __future__ import annotations

import json
import os
import unicodedata
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

ENV_PROVIDER = "TENNIS_RESULTS_PROVIDER"


class TennisResultsError(RuntimeError):
    """Raised when tennis results configuration or retrieval fails."""


class ResultsFeed(ABC):
    """Base interface for a tennis results feed.

    Each feed implementation has a name (for logging and debugging) and an optional
    reason (why results are unavailable, if they are). The fetch_results method
    retrieves rows for a given date in ISO format (YYYY-MM-DD).
    """

    def __init__(self, name: str, reason: Optional[str] = None):
        self.name = name
        self.reason = reason

    @abstractmethod
    def fetch_results(self, date: str) -> list[dict]:
        """Fetch tennis results for a given date.

        Args:
            date: ISO date string (YYYY-MM-DD).

        Returns:
            List of result rows. Each row has shape:
            {
                "event_id": str or None,
                "tournament": str,
                "player_a": str,
                "player_b": str,
                "winner": "a" or "b",
                "score": str,
                "completed_utc": ISO str (e.g. "2025-09-14T14:30:00Z")
            }
        """
        raise NotImplementedError


class NoFeed(ResultsFeed):
    """Placeholder feed when no results source is configured."""

    def __init__(self):
        super().__init__(
            name="none",
            reason="no tennis results feed configured (TENNIS_RESULTS_PROVIDER is not set)",
        )

    def fetch_results(self, date: str) -> list[dict]:
        """Return an empty list."""
        return []


class FixtureFeed(ResultsFeed):
    """Test and dry-run feed backed by a JSONL file.

    Each line in the file is a result row. The feed filters to rows whose
    completed_utc starts with the requested date (ISO prefix match).
    """

    def __init__(self, path: str):
        self.path = Path(path)
        super().__init__(name="fixture")

    def fetch_results(self, date: str) -> list[dict]:
        """Fetch rows from the fixture file, filtering by date prefix."""
        if not self.path.exists():
            return []

        results = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    # Filter by date: completed_utc must start with the date string
                    if row.get("completed_utc", "").startswith(date):
                        results.append(row)
        except (IOError, json.JSONDecodeError):
            # Silently return what we've read so far if there's an error
            pass

        return results


def feed(env: Optional[dict] = None) -> ResultsFeed:
    """Get the configured tennis results feed.

    Args:
        env: Environment dict (defaults to os.environ if None).

    Returns:
        A ResultsFeed instance.

    Raises:
        TennisResultsError: If the provider value is unknown.
    """
    if env is None:
        env = os.environ

    provider = (env.get(ENV_PROVIDER) or "").strip()

    if not provider:
        return NoFeed()

    if provider.startswith("fixture:"):
        path = provider[len("fixture:"):]
        return FixtureFeed(path)

    # Reject unknown provider without echoing the value beyond the prefix.
    raise TennisResultsError("unknown tennis results provider; known: fixture:<path>")


def results_for(date: str, env: Optional[dict] = None) -> dict:
    """Fetch tennis results for a date and include provider metadata.

    Args:
        date: ISO date string (YYYY-MM-DD).
        env: Environment dict (defaults to os.environ if None).

    Returns:
        A dict with keys:
        - "rows": list of result rows
        - "provider": name of the feed
        - "reason": reason for unavailability (None if available)
    """
    f = feed(env)
    return {
        "rows": f.fetch_results(date),
        "provider": f.name,
        "reason": f.reason,
    }


def normalize_name(name: str) -> str:
    """Normalize a player name for matching.

    Steps:
    1. Lowercase.
    2. Strip accents using NFKD decomposition.
    3. Replace punctuation with spaces.
    4. Collapse whitespace.

    Args:
        name: A player name (e.g., "Iga Świątek").

    Returns:
        Normalized name (e.g., "iga swiatek").
    """
    # Lowercase
    name = name.lower()

    # Strip accents using NFKD
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")

    # Replace punctuation with spaces (so "O'Brien-Smith" becomes "O Brien Smith")
    name = "".join(c if c.isalnum() or c.isspace() else " " for c in name)

    # Collapse multiple spaces into single space
    name = " ".join(name.split())

    return name


def surname(name: str) -> str:
    """Extract the surname from a normalized name.

    Returns the last token of normalize_name(name).

    Args:
        name: A player name.

    Returns:
        The surname (last token after normalization).
    """
    normalized = normalize_name(name)
    tokens = normalized.split()
    return tokens[-1] if tokens else ""


def match_winner(
    row: dict,
    home_name: str,
    away_name: str,
) -> Optional[str]:
    """Determine which of home or away won based on the result row.

    Compares the surname of the result row's winner to the surnames of
    home_name and away_name. Returns "home", "away", or None if there is
    no match or the match is ambiguous.

    Args:
        row: A result row with "winner" ("a" or "b") and the corresponding
             winner's name ("player_a" or "player_b").
        home_name: The home player's name.
        away_name: The away player's name.

    Returns:
        "home", "away", or None.
    """
    winner_key = "player_a" if row.get("winner") == "a" else "player_b"
    winner_full_name = row.get(winner_key, "")

    if not winner_full_name:
        return None

    winner_surname = surname(winner_full_name)
    home_surname = surname(home_name)
    away_surname = surname(away_name)

    if not winner_surname:
        return None

    matches = []
    if winner_surname == home_surname:
        matches.append("home")
    if winner_surname == away_surname:
        matches.append("away")

    # Return only if there is exactly one match (no ambiguity).
    if len(matches) == 1:
        return matches[0]

    return None
