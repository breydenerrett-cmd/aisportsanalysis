"""API-Tennis Business client: fixtures, live scores, live odds, odds.

WHY THIS EXISTS
----------------
docs/TENNIS_FEED_DECISION_2026-09-15.md says the live tennis rules (favourite
loses the first set, break of serve against the favourite, favourite down a
break in the deciding set) need three things BALLDONTLIE does not have: a
point-by-point log, in-play odds, and a flag for when a book suspends a
market. API-Tennis Business claims all three on a 14-day trial that must be
measured, not assumed, before a dollar is paid (see
scripts/api_tennis_trial.py). This module is the small stdlib client that
trial script drives.

Built in the shape of src/providers/balldontlie.py: one injectable transport
seam, a paced request loop (token-bucket, same shape as balldontlie's
pacer), and retries that wrap transport errors in one error type. Unlike
balldontlie, this vendor documents no 429/rate-limit response headers to
adapt from (confirmed by reading https://api-tennis.com/documentation via
WebFetch, 2026-09-16) -- there is no `_adapt_pacer_after_429` here because
there is nothing in the response to adapt from; a 429 is retried with the
same bounded exponential backoff as a 5xx.

TRANSPORT ERRORS
-----------------
src/providers/mlb.py's _get_json originally let a bare TimeoutError escape
because urllib.request.urlopen's read-timeout path raises TimeoutError (an
OSError subclass), not a urllib.error.URLError -- that caused a real outage.
This client's transport wrapping therefore catches OSError and
http.client.HTTPException explicitly (not just urllib.error.URLError) and
wraps every one of them in ApiTennisError, so no bare transport exception
can ever reach a caller.

ENDPOINTS (confirmed via WebFetch against https://api-tennis.com/documentation
on 2026-09-16; method names and parameter shapes below are read directly off
that page, not guessed)
-------------------------------------------------------------------------
Base URL: https://api.api-tennis.com/tennis/
Auth: API key as a query parameter, `APIkey=<key>` (the vendor's documented
scheme has no header option). Because the key can only travel as a query
param, this module NEVER logs, returns, or raises a full URL -- every error
and every return value from this module carries at most the bare `method`
name, never a query string. `_build_url` is the single place the key is
concatenated into a request URL, and its result is handed straight to the
transport, never stored on the client or echoed back to a caller.

  method=get_fixtures    -- fixtures; "pointbypoint, scores and statistics inline"
  method=get_livescore   -- live matches with point-by-point and statistics
  method=get_odds        -- pre-match/set-level markets ("Set Betting": 2:0 etc.)
  method=get_live_odds   -- live odds with a "suspended": "Yes"/"No" flag per market
  method=get_H2H         -- head-to-head history
  method=get_standings   -- ATP/WTA rankings
  method=get_players      -- player profiles
  method=get_events      -- supported tournament types in the subscription
  method=get_tournaments -- available tournaments
  method=get_draw        -- tournament bracket, match status

SECURITY
--------
The API key is read only from the environment variable named by ENV_API_KEY
(client_from_env). It is never logged, never included in an exception
message, and never returned in any value read back from this module's
public functions. Response bodies are returned as parsed JSON: this module
does not scan them for the key (the vendor could echo request params back,
in principle), so callers displaying raw API-Tennis payloads should treat
that as the vendor's responsibility, not this client's -- this client's own
code path never places the key anywhere but the outgoing request URL.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

ENV_API_KEY = "API_TENNIS_KEY"
DEFAULT_HOST = "https://api.api-tennis.com/tennis/"
DEFAULT_USER_AGENT = "aisportsanalysis/0.1 (stdlib urllib)"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_RATE_PER_MINUTE = 60
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 60.0

_RETRYABLE_STATUSES = frozenset({429}) | frozenset(range(500, 600))

# Methods, named exactly as the vendor's docs spell them (method=<name>).
METHOD_GET_EVENTS = "get_events"
METHOD_GET_TOURNAMENTS = "get_tournaments"
METHOD_GET_FIXTURES = "get_fixtures"
METHOD_GET_LIVESCORE = "get_livescore"
METHOD_GET_H2H = "get_H2H"
METHOD_GET_STANDINGS = "get_standings"
METHOD_GET_PLAYERS = "get_players"
METHOD_GET_ODDS = "get_odds"
METHOD_GET_LIVE_ODDS = "get_live_odds"
METHOD_GET_DRAW = "get_draw"


class ApiTennisError(RuntimeError):
    """Raised for API-Tennis failures. Never carries the key or a query string."""


class ApiTennisHTTPError(ApiTennisError):
    """A terminal HTTP-status failure after retries were exhausted (or
    immediately, for a non-retryable status). Carries only the bare method
    name and status -- never a URL or query string."""

    def __init__(self, status: int, method: str):
        self.status = status
        self.method = method
        super().__init__(f"api-tennis API returned HTTP {status} for method={method}")


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class _TokenBucketPacer:
    """Minimum-interval pacer with an injectable clock and sleep -- same
    shape as balldontlie.Client's pacer, deliberately: acquire() never
    returns less than 60/rate_per_minute seconds after the previous
    acquire() returned, so "never exceeds the configured rate" is a simple
    property to test with a fake clock."""

    def __init__(self, rate_per_minute: float, clock: Callable[[], float],
                 sleep: Callable[[float], None]):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self._rate_per_second = rate_per_minute / 60.0
        self._clock = clock
        self._sleep = sleep
        self._tokens = 1.0
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(1.0, self._tokens + elapsed * self._rate_per_second)

    def acquire(self) -> None:
        self._refill()
        if self._tokens < 1.0:
            deficit = 1.0 - self._tokens
            self._sleep(deficit / self._rate_per_second)
            self._refill()
        self._tokens -= 1.0


@dataclass
class ClientConfig:
    host: str = DEFAULT_HOST
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    rate_per_minute: float = DEFAULT_RATE_PER_MINUTE
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_cap: float = DEFAULT_BACKOFF_CAP_SECONDS
    user_agent: str = DEFAULT_USER_AGENT


class Client:
    """Thin API-Tennis HTTP client: one transport seam, a pacer, bounded retries.

    `transport` is the single injectable seam: a callable
    `(method: str, params: dict) -> (status_code, raw_body)`. The client
    builds the full URL (including the APIkey query param) itself and hands
    only `method`/`params` to the seam's caller-visible signature so a test
    can assert on the outgoing params without ever having to construct a
    URL containing the key; the real (default) transport is the only place
    the key-bearing URL is actually built and it is never returned or
    logged.
    """

    def __init__(self, api_key: str, *, transport: Optional[Callable[[str, dict], tuple]] = None,
                 clock: Optional[Callable[[], float]] = None,
                 sleep: Optional[Callable[[float], None]] = None,
                 config: Optional[ClientConfig] = None):
        if not api_key:
            raise ApiTennisError(f"{ENV_API_KEY} is not set")
        self._api_key = api_key
        self._config = config or ClientConfig()
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._transport = transport or self._default_transport
        self._pacer = _TokenBucketPacer(
            rate_per_minute=self._config.rate_per_minute,
            clock=self._clock, sleep=self._sleep,
        )

    # -- transport ---------------------------------------------------

    def _build_url(self, method: str, params: dict) -> str:
        """The one place the API key is concatenated into a URL. Callers of
        this client never see the result -- it goes straight to urlopen."""
        query = dict(params)
        query["method"] = method
        query["APIkey"] = self._api_key
        return f"{self._config.host}?{urllib.parse.urlencode(query, doseq=True)}"

    def _default_transport(self, method: str, params: dict) -> tuple:
        url = self._build_url(method, params)
        request = urllib.request.Request(
            url, headers={"User-Agent": self._config.user_agent, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read()
            except Exception:
                body = b""
            return exc.code, body
        except urllib.error.URLError as exc:
            # exc.reason may embed exc.filename (the URL, which carries the
            # key) on some URLError subclasses -- never format the exception
            # itself into the message, only its type.
            raise ApiTennisError(
                f"could not reach api-tennis API for method={method}: "
                f"{type(exc.reason).__name__ if exc.reason else 'connection failed'}"
            ) from None
        except (http.client.HTTPException, ConnectionError, TimeoutError, OSError) as exc:
            # Same lesson as src/providers/mlb.py's outage: urlopen's own
            # read-timeout path raises a bare TimeoutError (an OSError
            # subclass), never wrapped in URLError, so it must be caught
            # here explicitly or it escapes uncaught.
            raise ApiTennisError(
                f"api-tennis API connection failed for method={method}: "
                f"{type(exc).__name__}"
            ) from None

    # -- public API ----------------------------------------------------

    def get(self, method: str, params: Optional[dict] = None) -> dict:
        """One paced, retried request. Returns the parsed JSON body.

        Retries 429 and 5xx with bounded exponential backoff
        (config.max_retries); any other non-2xx status raises
        ApiTennisHTTPError immediately. Every exception this raises carries
        only the bare `method` name -- never `params`, a query string, or
        the key.
        """
        params = dict(params or {})
        attempt = 0
        while True:
            self._pacer.acquire()
            status, body = self._transport(method, params)

            if 200 <= status < 300:
                try:
                    text = body.decode("utf-8") if isinstance(body, bytes) else body
                    return json.loads(text) if text else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise ApiTennisError(
                        f"api-tennis API returned invalid JSON for method={method}") from None

            if status in _RETRYABLE_STATUSES:
                attempt += 1
                if attempt > self._config.max_retries:
                    raise ApiTennisHTTPError(status, method)
                delay = min(self._config.backoff_cap,
                            self._config.backoff_base * (2 ** (attempt - 1)))
                self._sleep(delay)
                continue

            raise ApiTennisHTTPError(status, method)

    # -- endpoint helpers (thin, named after the vendor's own method names) --

    def get_fixtures(self, date_start: str, date_stop: str, **params) -> dict:
        """Fixtures with point-by-point, scores and statistics inline."""
        return self.get(METHOD_GET_FIXTURES,
                         {"date_start": date_start, "date_stop": date_stop, **params})

    def get_livescore(self, **params) -> dict:
        """Live matches with point-by-point and statistics."""
        return self.get(METHOD_GET_LIVESCORE, params)

    def get_odds(self, **params) -> dict:
        """Set-level markets ("Set Betting": 2:0, 2:1, 0:2, 1:2, ...)."""
        return self.get(METHOD_GET_ODDS, params)

    def get_live_odds(self, **params) -> dict:
        """Live odds with a per-market suspension flag ("suspended": "Yes"/"No")."""
        return self.get(METHOD_GET_LIVE_ODDS, params)

    def get_h2h(self, first_player_key, second_player_key) -> dict:
        return self.get(METHOD_GET_H2H, {
            "first_player_key": first_player_key,
            "second_player_key": second_player_key,
        })

    def get_standings(self, event_type: str) -> dict:
        return self.get(METHOD_GET_STANDINGS, {"event_type": event_type})

    def get_players(self, player_key, **params) -> dict:
        return self.get(METHOD_GET_PLAYERS, {"player_key": player_key, **params})

    def get_events(self) -> dict:
        return self.get(METHOD_GET_EVENTS, {})

    def get_tournaments(self) -> dict:
        return self.get(METHOD_GET_TOURNAMENTS, {})

    def get_draw(self, tournament_key, **params) -> dict:
        return self.get(METHOD_GET_DRAW, {"tournament_key": tournament_key, **params})


def client_from_env(env: Optional[dict] = None, **kwargs) -> Client:
    """Build a Client from API_TENNIS_KEY, raising a plain error naming the
    variable if it is unset. Never echoes the key."""
    if env is None:
        env = os.environ
    api_key = (env.get(ENV_API_KEY) or "").strip()
    if not api_key:
        raise ApiTennisError(f"{ENV_API_KEY} is not set")
    return Client(api_key, **kwargs)
