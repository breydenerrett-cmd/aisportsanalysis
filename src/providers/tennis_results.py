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

import http.client
import json
import os
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

ENV_PROVIDER = "TENNIS_RESULTS_PROVIDER"
ENV_BALLDONTLIE_KEY = "BALLDONTLIE_API_KEY"


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


# ---------------------------------------------------------------------------
# BALLDONTLIE (ATP/WTA), confirmed against the published spec
# ---------------------------------------------------------------------------
#
# Base URL, paths, params, auth and the match schema below are confirmed from
# https://www.balldontlie.io/openapi/atp.yml and .../openapi/wta.yml (fetched
# 2026-09-14), not guessed. See BallDontLieFeed's docstring for the exact
# endpoints and the one significant gap the spec left unstated.

BALLDONTLIE_API_HOST = "https://api.balldontlie.io"
BALLDONTLIE_USER_AGENT = "aisportsanalysis/0.1 (stdlib urllib)"
BALLDONTLIE_TIMEOUT = 20
BALLDONTLIE_PAGE_CAP = 20
BALLDONTLIE_PER_PAGE = 100
BALLDONTLIE_TOURS = ("atp", "wta")

# ALL-STAR tier rate limit per balldontlie.io's pricing page: 60 requests a
# minute. One second between requests keeps this feed at or under that
# ceiling without needing a token-bucket.
BALLDONTLIE_RATE_LIMIT_SLEEP_SECONDS = 1.0

# match_status values kept by fetch_results -- everything else (in_progress,
# scheduled, suspended, and WTA's "canceled", which ATP's enum does not even
# list) is not a settled result. Confirmed against both specs' ATPMatch/
# WTAMatch.match_status enum, which is nullable and documents exactly:
#   ATP: finished, in_progress, scheduled, suspended, walkover, retired, defaulted
#   WTA: finished, in_progress, scheduled, suspended, canceled, walkover, retired, defaulted
# The four below are the intersection that means "the match produced a result".
STATUS_FINISHED = "finished"
STATUS_RETIRED = "retired"
STATUS_WALKOVER = "walkover"
STATUS_DEFAULTED = "defaulted"
KEPT_MATCH_STATUSES = frozenset(
    {STATUS_FINISHED, STATUS_RETIRED, STATUS_WALKOVER, STATUS_DEFAULTED}
)

# Settlement classification, exported so the settle path applies one rule
# instead of re-deriving it from prose. See retirement_rule_note().
ALWAYS_VOID_STATUSES = frozenset({STATUS_WALKOVER})
ALWAYS_GRADED_STATUSES = frozenset({STATUS_FINISHED, STATUS_DEFAULTED})
VOID_UNLESS_SET_COMPLETED_STATUSES = frozenset({STATUS_RETIRED})


def retirement_rule_note() -> str:
    """The one-sentence settlement rule this repo applies to unfinished matches."""
    return (
        "A match retired before one full set is completed is VOID; a match "
        "retired after at least one completed set counts for the player who "
        "advanced; a walkover is always VOID."
    )


class BallDontLieFeed(ResultsFeed):
    """Tennis results from BALLDONTLIE's ATP and WTA match endpoints.

    CONFIRMED FROM THE SPEC (https://www.balldontlie.io/openapi/atp.yml and
    .../wta.yml, fetched 2026-09-14):

    - Base URL: https://api.balldontlie.io
    - Endpoints: GET /atp/v1/matches and GET /wta/v1/matches, both
      ALL-STAR-tier, cursor-paginated. Query params: cursor (integer),
      per_page (integer, max 100, default 25), tournament_ids (array of
      integers), player_ids[] (array of integers), season (integer, the
      calendar year), round (string), is_live (boolean). Response envelope:
      {"data": [...ATPMatch/WTAMatch...], "meta": {"next_cursor", "prev_cursor",
      "per_page"}}.
    - Auth: securitySchemes.ApiKeyAuth is `type: apiKey, in: header,
      name: Authorization` -- the raw key is the header value; the spec does
      not document a "Bearer " prefix, so none is sent.
    - Match fields used here: player1/player2 (id, full_name, first_name,
      last_name), winner (nullable, same player shape), score (string),
      set_scores (array), match_status (the enum above), tournament
      (id, name, start_date, end_date -- both `format: date`, nullable).

    THE ONE THING THE SPEC DOES NOT STATE: neither ATPMatch nor WTAMatch
    carries any per-match timestamp (no start_time/scheduled_at/played_at/
    completed_at/date field), and /matches has no date query parameter --
    only `season` (year) and `round`. So `fetch_results(date)` cannot ask the
    vendor for "matches on this date" directly. It queries by season (the
    year of the requested date) and keeps only matches whose tournament
    start_date/end_date span contains the requested date -- a tournament-week
    bound, not an exact per-match day, because the spec does not expose one.
    A match whose tournament is missing either date is dropped rather than
    guessed into the window. Because there is no per-match timestamp,
    "completed_utc" is never set on these rows.
    """

    def __init__(self, api_key: str, get_json=None, sleep=None,
                 page_cap: int = BALLDONTLIE_PAGE_CAP,
                 per_page: int = BALLDONTLIE_PER_PAGE,
                 timeout: int = BALLDONTLIE_TIMEOUT):
        super().__init__(name="balldontlie")
        self._api_key = api_key
        self._get_json = get_json or self._default_get_json
        self._sleep = sleep or time.sleep
        self._page_cap = page_cap
        self._per_page = per_page
        self._timeout = timeout

    def _headers(self) -> dict:
        # Raw key value, per the spec's apiKey scheme -- see class docstring.
        return {
            "Authorization": self._api_key,
            "User-Agent": BALLDONTLIE_USER_AGENT,
        }

    def _default_get_json(self, url: str, headers: dict) -> dict:
        """Stdlib transport. Error text never contains the URL or the key."""
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise TennisResultsError(
                f"balldontlie API returned HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise TennisResultsError(
                f"could not reach balldontlie API: {exc.reason}") from None
        except (http.client.HTTPException, ConnectionError, TimeoutError, OSError) as exc:
            raise TennisResultsError(
                f"balldontlie API connection failed: {type(exc).__name__}") from None
        except json.JSONDecodeError:
            raise TennisResultsError("balldontlie API returned invalid JSON") from None

    def fetch_results(self, date: str) -> list[dict]:
        """Fetch ATP and WTA results whose tournament window covers `date`.

        See the class docstring for why this is season+tournament-window
        filtering rather than an exact per-match date filter -- the vendor
        spec does not expose a per-match date.
        """
        try:
            season = int(str(date)[:4])
        except (ValueError, TypeError):
            raise TennisResultsError(
                f"invalid date {date!r}; expected YYYY-MM-DD") from None

        rows: list[dict] = []
        made_a_request = False
        for tour in BALLDONTLIE_TOURS:
            cursor = None
            pages = 0
            while pages < self._page_cap:
                params = {"season": season, "per_page": self._per_page}
                if cursor:
                    params["cursor"] = cursor
                url = (f"{BALLDONTLIE_API_HOST}/{tour}/v1/matches"
                       f"?{urllib.parse.urlencode(params)}")

                # Rate-limit seam: sleep BETWEEN requests, never before the
                # first one of the whole fetch_results call.
                if made_a_request:
                    self._sleep(BALLDONTLIE_RATE_LIMIT_SLEEP_SECONDS)
                made_a_request = True

                payload = self._get_json(url, self._headers()) or {}
                pages += 1

                matches = payload.get("data") or []
                for match in matches:
                    row = _balldontlie_row(match, tour, str(date))
                    if row is not None:
                        rows.append(row)

                meta = payload.get("meta") or {}
                next_cursor = meta.get("next_cursor")
                if not matches or not next_cursor:
                    break
                cursor = next_cursor

        return rows


def _balldontlie_row(match: dict, tour: str, date: str) -> Optional[dict]:
    """One ATPMatch/WTAMatch dict -> a ResultsFeed row, or None to drop it."""
    status = match.get("match_status")
    if status not in KEPT_MATCH_STATUSES:
        return None

    tournament = match.get("tournament") or {}
    start_date = tournament.get("start_date")
    end_date = tournament.get("end_date")
    if not start_date or not end_date or not (start_date <= date <= end_date):
        return None

    player1 = match.get("player1") or {}
    player2 = match.get("player2") or {}
    winner = match.get("winner") or {}
    winner_id = winner.get("id")

    if winner_id is not None and winner_id == player1.get("id"):
        winner_side = "a"
    elif winner_id is not None and winner_id == player2.get("id"):
        winner_side = "b"
    else:
        # No resolvable winner -- never guess which side advanced.
        return None

    match_id = match.get("id")
    return {
        "event_id": str(match_id) if match_id is not None else None,
        "tournament": tournament.get("name"),
        "player_a": _balldontlie_player_name(player1),
        "player_b": _balldontlie_player_name(player2),
        "winner": winner_side,
        "score": match.get("score"),
        "tour": tour,
        "status": status,
        "vendor_match_id": match_id,
    }


def _balldontlie_player_name(player: dict) -> str:
    full_name = player.get("full_name")
    if full_name:
        return full_name
    first = player.get("first_name") or ""
    last = player.get("last_name") or ""
    return f"{first} {last}".strip()


def feed(env: Optional[dict] = None) -> ResultsFeed:
    """Get the configured tennis results feed.

    Args:
        env: Environment dict (defaults to os.environ if None).

    Returns:
        A ResultsFeed instance.

    Raises:
        TennisResultsError: If the provider value is unknown, or if
            TENNIS_RESULTS_PROVIDER="balldontlie" but BALLDONTLIE_API_KEY
            is not set.
    """
    if env is None:
        env = os.environ

    provider = (env.get(ENV_PROVIDER) or "").strip()
    balldontlie_key = (env.get(ENV_BALLDONTLIE_KEY) or "").strip()

    if not provider:
        # No provider named: use BALLDONTLIE automatically once the key
        # shows up, so tennis grading starts working the moment the owner
        # adds the secret -- no config change needed on top of it.
        if balldontlie_key:
            return BallDontLieFeed(balldontlie_key)
        return NoFeed()

    if provider.startswith("fixture:"):
        path = provider[len("fixture:"):]
        return FixtureFeed(path)

    if provider == "balldontlie":
        if not balldontlie_key:
            raise TennisResultsError(f"{ENV_BALLDONTLIE_KEY} is not set")
        return BallDontLieFeed(balldontlie_key)

    # Reject unknown provider without echoing the value beyond the prefix.
    raise TennisResultsError(
        "unknown tennis results provider; known: fixture:<path>, balldontlie")


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
