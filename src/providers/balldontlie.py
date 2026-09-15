"""Generic BALLDONTLIE API transport: one seam, a cursor pager, and a pacer.

WHY THIS EXISTS
----------------
src/providers/tennis_results.py already talks to BALLDONTLIE for ATP/WTA
match results, but it hard-codes the tennis endpoints and a fixed 1
request/second sleep sized for the ALL-STAR tier (60 req/min). The owner
bought ALL-ACCESS on a 48-hour trial (2026-09-15) covering every sport this
vendor has (tennis, NFL, MLB, NBA, NHL) at a much higher ceiling (600
req/min per their pricing page), and scripts/balldontlie_harvest.py needs to
pull all of it before the trial ends. This module is the shared, sport-
agnostic transport that harvester uses: a single injectable HTTP seam, a
cursor-following pager, and a token-bucket pacer -- all built to be exercised
without the network in tests.

This module does NOT replace tennis_results.BallDontLieFeed (that stays as
the live results-grading path); it is the general client for bulk archival
pulls across every sport's endpoints.

SECURITY
--------
The API key is a bearer credential (raw value in the `Authorization` header,
same as tennis_results.py -- the spec's securitySchemes.ApiKeyAuth does not
document a "Bearer " prefix). It is never logged, never placed in a URL
query string, and never included in an exception message: every error raised
here carries only an HTTP status and a bare API path (no query string, no
host, no key). Callers must not do their own string-formatting of the key
into logs either.
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
from typing import Callable, Iterator, Optional

ENV_API_KEY = "BALLDONTLIE_API_KEY"
DEFAULT_HOST = "https://api.balldontlie.io"
DEFAULT_USER_AGENT = "aisportsanalysis/0.1 (stdlib urllib)"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_RATE_PER_MINUTE = 550
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 60.0
DEFAULT_PER_PAGE = 100

# Statuses the client retries with backoff. Everything else (2xx handled
# separately, 4xx other than 429) is returned to the caller as an error --
# in particular 403 (tier does not cover this endpoint) and 404 are NOT
# retried, so a harvester job fails fast and the caller can record+skip it.
_RETRYABLE_STATUS = {429}


class BallDontLieError(RuntimeError):
    """Raised for balldontlie API failures. Never carries the key or a URL query."""


class BallDontLieHTTPError(BallDontLieError):
    """An HTTP-status failure from the API (after any retries were exhausted).

    Carries the plain integer `status` so callers (the harvester) can branch
    on it -- e.g. treat 403/404 as "not entitled / not found, skip" -- without
    parsing the message string.
    """

    def __init__(self, status: int, path: str):
        self.status = status
        self.path = path
        super().__init__(f"balldontlie API returned HTTP {status} for {path}")


def _is_retryable(status: int) -> bool:
    return status in _RETRYABLE_STATUS or 500 <= status < 600


class _TokenBucketPacer:
    """Token bucket rate limiter with injectable clock and sleep.

    Default capacity is 1.0 token -- i.e. by default this behaves as a
    strict minimum-interval pacer: acquire() never returns less than
    60/rate_per_minute seconds after the previous acquire() returned. That
    makes "never exceeds the rate" a simple, exactly-testable property with
    a fake clock, rather than a statistical one. Pass a larger `capacity` to
    allow short bursts (e.g. after an idle period) while still bounding the
    long-run rate to rate_per_minute.
    """

    def __init__(self, rate_per_minute: float, clock: Callable[[], float],
                 sleep: Callable[[float], None], capacity: float = 1.0):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self._rate_per_second = rate_per_minute / 60.0
        self._capacity = max(1.0, capacity)
        self._clock = clock
        self._sleep = sleep
        self._tokens = self._capacity
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_second)

    def acquire(self) -> None:
        self._refill()
        if self._tokens < 1.0:
            deficit = 1.0 - self._tokens
            wait_seconds = deficit / self._rate_per_second
            self._sleep(wait_seconds)
            self._refill()
        self._tokens -= 1.0


@dataclass
class ClientConfig:
    host: str = DEFAULT_HOST
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    rate_per_minute: float = DEFAULT_RATE_PER_MINUTE
    bucket_capacity: float = 1.0
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_cap: float = DEFAULT_BACKOFF_CAP_SECONDS
    user_agent: str = DEFAULT_USER_AGENT


class Client:
    """Thin BALLDONTLIE HTTP client: one transport seam, cursor pager, pacer.

    `transport` is the single injectable seam: a callable
    `(path: str, params: dict, headers: dict) -> tuple[int, bytes]` returning
    (status_code, raw_body). Headers (including the real `Authorization`
    value) are always built by the Client itself and handed to the seam,
    never assembled by caller code -- so a test can assert the key reached
    the transport without the client ever formatting the key into a log or
    an f-string a test might echo back.
    """

    def __init__(self, api_key: str, *, transport: Optional[Callable[[str, dict, dict], tuple]] = None,
                 clock: Optional[Callable[[], float]] = None,
                 sleep: Optional[Callable[[float], None]] = None,
                 config: Optional[ClientConfig] = None):
        if not api_key:
            raise BallDontLieError(f"{ENV_API_KEY} is not set")
        self._api_key = api_key
        self._config = config or ClientConfig()
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._transport = transport or self._default_transport
        self._pacer = _TokenBucketPacer(
            rate_per_minute=self._config.rate_per_minute,
            clock=self._clock,
            sleep=self._sleep,
            capacity=self._config.bucket_capacity,
        )

    # -- transport -----------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": self._api_key,
            "User-Agent": self._config.user_agent,
            "Accept": "application/json",
        }

    def _default_transport(self, path: str, params: dict, headers: dict) -> tuple:
        url = f"{self._config.host}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
        request = urllib.request.Request(url, headers=headers)
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
            raise BallDontLieError(
                f"could not reach balldontlie API: {exc.reason}") from None
        except (http.client.HTTPException, ConnectionError, TimeoutError, OSError) as exc:
            raise BallDontLieError(
                f"balldontlie API connection failed: {type(exc).__name__}") from None

    # -- public API ------------------------------------------------------

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        """One request, following the pacer and retrying 429/5xx with backoff."""
        params = dict(params or {})
        attempt = 0
        while True:
            self._pacer.acquire()
            status, body = self._transport(path, params, self._headers())
            if 200 <= status < 300:
                try:
                    text = body.decode("utf-8") if isinstance(body, bytes) else body
                    return json.loads(text) if text else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise BallDontLieError(
                        f"balldontlie API returned invalid JSON for {path}") from None
            if _is_retryable(status):
                attempt += 1
                if attempt > self._config.max_retries:
                    raise BallDontLieHTTPError(status, path)
                delay = min(self._config.backoff_cap,
                            self._config.backoff_base * (2 ** (attempt - 1)))
                self._sleep(delay)
                continue
            raise BallDontLieHTTPError(status, path)

    def pages(self, path: str, params: Optional[dict] = None, *,
              page_cap: Optional[int] = None,
              start_cursor: Optional[int] = None) -> Iterator[dict]:
        """Yield each page's full JSON payload, following meta.next_cursor.

        `params` should not itself carry `cursor`; pass a resume point via
        `start_cursor` instead. Stops when a page has no data, or meta has
        no next_cursor, or `page_cap` pages have been yielded (whichever
        comes first). per_page defaults to DEFAULT_PER_PAGE if not set.
        """
        base_params = dict(params or {})
        base_params.setdefault("per_page", DEFAULT_PER_PAGE)
        cursor = start_cursor
        pages_yielded = 0
        while page_cap is None or pages_yielded < page_cap:
            call_params = dict(base_params)
            if cursor is not None:
                call_params["cursor"] = cursor
            payload = self.get(path, call_params)
            pages_yielded += 1
            yield payload

            data = payload.get("data")
            meta = payload.get("meta") or {}
            next_cursor = meta.get("next_cursor")
            if not data or next_cursor is None:
                break
            cursor = next_cursor


def client_from_env(env: Optional[dict] = None, **kwargs) -> Client:
    """Build a Client from BALLDONTLIE_API_KEY, raising a plain error if unset.

    Never echoes the key; the error names only the variable.
    """
    if env is None:
        env = os.environ
    api_key = (env.get(ENV_API_KEY) or "").strip()
    if not api_key:
        raise BallDontLieError(f"{ENV_API_KEY} is not set")
    return Client(api_key, **kwargs)
