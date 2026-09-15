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

429 POLICY (2026-09-15 incident: run 35001607006)
--------------------------------------------------
The account behaves as if limited to ~5 requests/minute, well under the
ALL-ACCESS 600/min the tier is supposed to grant. The original retry policy
(5 attempts, 1/2/4/8/16s backoff, ~31s total) gave up inside a single
60-second rate window, so every job errored after its first 5 pages. A 429
now means "wait", not "give up": `get()` sleeps out each 429 (Retry-After if
present, else the reset header, else 61s -- see `_compute_429_wait`) and
retries indefinitely, bounded by three things: `max_429_wait_seconds`
(cumulative wait for one request, default 900s), `max_429_attempts`
(cumulative 429 COUNT for one request, default 50 -- independent of seconds
slept, so a computed wait of 0 can never make the retry free; see root
cause F, 2026-09-15: 188,101 zero-wait 429 retries in one run before this
existed), and an optional `deadline` (a `clock()`-scale cutoff the caller --
the harvester -- passes in so a long 429 sleep never runs past
`--max-minutes`). Hitting any bound raises a
dedicated exception (`BallDontLieRateLimitExhausted` /
`BallDontLieDeadlineExceeded`), never `BallDontLieHTTPError`, so the
harvester can tell "still worth resuming" apart from "permanently not
entitled" (403/404). Every 429 also adapts the pacer's rate down (95% of
x-ratelimit-limit if the vendor sends one, else halved with a 4/min floor)
so subsequent requests stop hammering a limit that has already been hit.
5xx keeps the original bounded exponential backoff (`max_retries`) --
that's a vendor/transport problem, not a quota one, and should still
surface as a terminal error rather than hang indefinitely.

SECURITY
--------
The API key is a bearer credential (raw value in the `Authorization` header,
same as tennis_results.py -- the spec's securitySchemes.ApiKeyAuth does not
document a "Bearer " prefix). It is never logged, never placed in a URL
query string, and never included in an exception message: every error raised
here carries only an HTTP status and a bare API path (no query string, no
host, no key). Callers must not do their own string-formatting of the key
into logs either. Response headers are treated the same way: only the
rate-limit header names this module actually reads are ever kept (see
`_RATE_LIMIT_HEADER_NAMES` / `_whitelist_headers`) -- anything else a
transport hands back (Set-Cookie, an echoed Authorization header, etc.) is
dropped before it reaches any client state or caller-visible return value.
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
DEFAULT_MAX_429_WAIT_SECONDS = 900.0
DEFAULT_MAX_429_ATTEMPTS = 50

# 429 handling constants (see module docstring's "429 POLICY").
_DEFAULT_429_WAIT_SECONDS = 61.0
# Floor for a single 429 wait (root cause F, 2026-09-15: a computed wait of
# 0 -- e.g. a malformed/zero Retry-After, or an x-ratelimit-reset already in
# the past -- let get() retry with no sleep at all, measured at 188,101
# requests / zero progress in one run because rate_limit_wait_total never
# grew). Belt-and-braces alongside DEFAULT_MAX_429_ATTEMPTS below, which is
# the actual bound: this only keeps each individual attempt from being free.
_MIN_429_WAIT_SECONDS = 1.0
_MIN_RATE_PER_MINUTE = 4.0
_ADAPTED_RATE_FRACTION_OF_LIMIT = 0.95
_EPOCH_SECONDS_THRESHOLD = 1e9  # a reset value above this is epoch time, not a delta

# Only these header names (case-insensitive) are ever read, kept, or
# returned by this module -- see the SECURITY section above.
_RATE_LIMIT_HEADER_NAMES = frozenset({
    "retry-after",
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset",
})

# Statuses the client retries with the original bounded exponential backoff.
# 429 is handled separately (see _handle_429) and is NOT in this set. 403 and
# 404 are NOT retried, so a harvester job fails fast and the caller can
# record+skip it.
_RETRYABLE_5XX = range(500, 600)


class BallDontLieError(RuntimeError):
    """Raised for balldontlie API failures. Never carries the key or a URL query."""


class BallDontLieHTTPError(BallDontLieError):
    """A terminal HTTP-status failure from the API (after any retries were
    exhausted, or immediately for a non-retryable status).

    Carries the plain integer `status` so callers (the harvester) can branch
    on it -- e.g. treat 403/404 as "not entitled / not found, skip" -- without
    parsing the message string.
    """

    def __init__(self, status: int, path: str):
        self.status = status
        self.path = path
        super().__init__(f"balldontlie API returned HTTP {status} for {path}")


class BallDontLieRateLimitExhausted(BallDontLieError):
    """A single request's cumulative 429 wait hit `max_429_wait_seconds`.

    This is NOT a terminal failure the way BallDontLieHTTPError is -- the
    account is still rate-limited, not disallowed, so the caller (the
    harvester) should treat this as resumable: save progress and try again
    later, not record a permanent error.
    """

    def __init__(self, path: str, waited_seconds: float):
        self.path = path
        self.waited_seconds = waited_seconds
        super().__init__(
            f"balldontlie API 429 wait exceeded max_429_wait_seconds for {path}")


class BallDontLieDeadlineExceeded(BallDontLieError):
    """A 429 wait would have run past the caller's `deadline`.

    Also resumable, not terminal -- the caller's time budget ran out while
    waiting on the vendor, not the vendor refusing the request.
    """

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"balldontlie API 429 wait would exceed the caller deadline for {path}")


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _whitelist_headers(headers) -> dict:
    """Keep only the rate-limit header names this client ever reads.

    Case-insensitive on the way in, lower-cased on the way out. Applied to
    every transport response regardless of transport implementation, so a
    custom/test transport that hands back a Set-Cookie or an echoed
    Authorization header can never leak it into client state or output.
    """
    if not headers:
        return {}
    out = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in _RATE_LIMIT_HEADER_NAMES:
            out[lowered] = value
    return out


class _TokenBucketPacer:
    """Token bucket rate limiter with injectable clock and sleep.

    Default capacity is 1.0 token -- i.e. by default this behaves as a
    strict minimum-interval pacer: acquire() never returns less than
    60/rate_per_minute seconds after the previous acquire() returned. That
    makes "never exceeds the rate" a simple, exactly-testable property with
    a fake clock, rather than a statistical one. Pass a larger `capacity` to
    allow short bursts (e.g. after an idle period) while still bounding the
    long-run rate to rate_per_minute.

    The rate is mutable via set_rate_per_minute -- the client calls this
    after every 429 to adapt to what the vendor is actually enforcing (see
    module docstring's "429 POLICY").
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

    def rate_per_minute(self) -> float:
        return self._rate_per_second * 60.0

    def set_rate_per_minute(self, rate_per_minute: float) -> None:
        self._refill()  # settle tokens under the OLD rate before changing it
        rate_per_minute = max(rate_per_minute, 0.0001)
        self._rate_per_second = rate_per_minute / 60.0


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
    max_429_wait_seconds: float = DEFAULT_MAX_429_WAIT_SECONDS
    # Root cause F: bounds 429 ATTEMPTS for one get() call, independent of
    # how many seconds were actually slept -- see _MIN_429_WAIT_SECONDS and
    # this file's "429 POLICY" docstring.
    max_429_attempts: int = DEFAULT_MAX_429_ATTEMPTS


class Client:
    """Thin BALLDONTLIE HTTP client: one transport seam, cursor pager, pacer.

    `transport` is the single injectable seam: a callable
    `(path: str, params: dict, headers: dict) -> tuple` returning either
    `(status_code, raw_body)` (old 2-tuple shape, still supported -- headers
    are treated as `{}`) or `(status_code, raw_body, response_headers)`
    (3-tuple; `response_headers` may be any header-name -> value mapping,
    filtered down to `_RATE_LIMIT_HEADER_NAMES` before this client keeps or
    returns any of it). Headers sent to the vendor (including the real
    `Authorization` value) are always built by the Client itself and handed
    to the seam, never assembled by caller code -- so a test can assert the
    key reached the transport without the client ever formatting the key
    into a log or an f-string a test might echo back.
    """

    def __init__(self, api_key: str, *, transport: Optional[Callable[[str, dict, dict], tuple]] = None,
                 clock: Optional[Callable[[], float]] = None,
                 sleep: Optional[Callable[[float], None]] = None,
                 now: Optional[Callable[[], float]] = None,
                 config: Optional[ClientConfig] = None):
        if not api_key:
            raise BallDontLieError(f"{ENV_API_KEY} is not set")
        self._api_key = api_key
        self._config = config or ClientConfig()
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        # Wall-clock source used ONLY to turn an epoch-seconds
        # x-ratelimit-reset into a wait duration -- separate from `clock`
        # (which the pacer/backoff treat as monotonic) because production
        # `clock` defaults to time.monotonic, which is not epoch time.
        self._now = now or time.time
        self._transport = transport or self._default_transport
        self._pacer = _TokenBucketPacer(
            rate_per_minute=self._config.rate_per_minute,
            clock=self._clock,
            sleep=self._sleep,
            capacity=self._config.bucket_capacity,
        )
        self._total_429_wait_seconds = 0.0
        self._last_rate_limit_seen: dict = {}

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
                resp_headers = dict(response.headers.items()) if response.headers else {}
                return response.status, response.read(), resp_headers
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read()
            except Exception:
                body = b""
            try:
                resp_headers = dict(exc.headers.items()) if exc.headers else {}
            except Exception:
                resp_headers = {}
            return exc.code, body, resp_headers
        except urllib.error.URLError as exc:
            raise BallDontLieError(
                f"could not reach balldontlie API: {exc.reason}") from None
        except (http.client.HTTPException, ConnectionError, TimeoutError, OSError) as exc:
            raise BallDontLieError(
                f"balldontlie API connection failed: {type(exc).__name__}") from None

    def _call_transport(self, path: str, params: dict) -> tuple:
        """Call the transport seam and return (status, body, whitelisted_headers),
        accepting either the 2-tuple or 3-tuple shape."""
        raw = self._transport(path, params, self._headers())
        if len(raw) == 3:
            status, body, raw_headers = raw
        else:
            status, body = raw
            raw_headers = {}
        return status, body, _whitelist_headers(raw_headers)

    # -- 429 handling ----------------------------------------------------

    def _compute_429_wait(self, resp_headers: dict) -> float:
        """How long to wait before retrying one 429, per the vendor's own
        headers when present, else a fixed fallback. See module docstring's
        "429 POLICY"."""
        retry_after = _to_float(resp_headers.get("retry-after"))
        if retry_after is not None:
            return max(0.0, retry_after)

        reset = resp_headers.get("x-ratelimit-reset")
        if reset is None:
            reset = resp_headers.get("ratelimit-reset")
        reset = _to_float(reset)
        if reset is not None:
            if reset > _EPOCH_SECONDS_THRESHOLD:
                return max(0.0, reset - self._now())
            return max(0.0, reset)

        return _DEFAULT_429_WAIT_SECONDS

    def _adapt_pacer_after_429(self, resp_headers: dict) -> None:
        """Lower the pacer rate after a 429: 95% of x-ratelimit-limit if the
        vendor sent one, else halve the current rate (floor 4/min). Also
        records the whitelisted values for rate_state()."""
        limit = resp_headers.get("x-ratelimit-limit")
        if limit is None:
            limit = resp_headers.get("ratelimit-limit")
        parsed_limit = _to_float(limit)

        if parsed_limit is not None and parsed_limit > 0:
            new_rate = parsed_limit * _ADAPTED_RATE_FRACTION_OF_LIMIT
            self._last_rate_limit_seen["limit"] = parsed_limit
        else:
            new_rate = max(_MIN_RATE_PER_MINUTE, self._pacer.rate_per_minute() / 2.0)
        self._pacer.set_rate_per_minute(new_rate)

        remaining = resp_headers.get("x-ratelimit-remaining", resp_headers.get("ratelimit-remaining"))
        remaining = _to_float(remaining)
        if remaining is not None:
            self._last_rate_limit_seen["remaining"] = remaining

        reset = resp_headers.get("x-ratelimit-reset", resp_headers.get("ratelimit-reset"))
        reset = _to_float(reset)
        if reset is not None:
            self._last_rate_limit_seen["reset"] = reset

    def _handle_429(self, path: str, resp_headers: dict, deadline: Optional[float],
                     rate_limit_wait_total: float) -> float:
        """Sleep out one 429, adapt the pacer, and return the updated
        running total wait for this call.

        Raises BallDontLieDeadlineExceeded if waiting the full amount would
        pass `deadline`, or BallDontLieRateLimitExhausted if it would push
        the cumulative wait for this request past
        `config.max_429_wait_seconds`. Both are resumable-not-terminal (see
        their docstrings) -- callers should catch them separately from
        BallDontLieHTTPError.
        """
        wait_seconds = self._compute_429_wait(resp_headers)
        wait_seconds = max(wait_seconds, _MIN_429_WAIT_SECONDS)

        if deadline is not None:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise BallDontLieDeadlineExceeded(path)
            wait_seconds = min(wait_seconds, remaining)

        exhausted = False
        if rate_limit_wait_total + wait_seconds >= self._config.max_429_wait_seconds:
            wait_seconds = max(0.0, self._config.max_429_wait_seconds - rate_limit_wait_total)
            exhausted = True

        if wait_seconds > 0:
            self._sleep(wait_seconds)
            rate_limit_wait_total += wait_seconds
            self._total_429_wait_seconds += wait_seconds

        # Adapt even when we're about to raise -- the next attempt (this
        # request resumed later, or the next job) should start paced down.
        self._adapt_pacer_after_429(resp_headers)

        if exhausted:
            raise BallDontLieRateLimitExhausted(path, rate_limit_wait_total)
        if deadline is not None and self._clock() >= deadline:
            raise BallDontLieDeadlineExceeded(path)

        return rate_limit_wait_total

    def rate_state(self) -> dict:
        """Read-only numeric snapshot: current pacer rate, the last-seen
        whitelisted x-ratelimit-* values (only keys actually observed so
        far), and the running total of time spent waiting out 429s across
        this client's lifetime. Never includes any header this client
        doesn't whitelist -- see `_whitelist_headers`."""
        state = {
            "rate_per_minute": self._pacer.rate_per_minute(),
            "total_429_wait_seconds": self._total_429_wait_seconds,
        }
        state.update(self._last_rate_limit_seen)
        return state

    # -- public API ------------------------------------------------------

    def get(self, path: str, params: Optional[dict] = None, *,
            deadline: Optional[float] = None) -> dict:
        """One request, following the pacer.

        429s are retried indefinitely (waiting per `_compute_429_wait` each
        time), bounded only by `config.max_429_wait_seconds` and the
        optional `deadline` -- see `_handle_429`. 5xx uses the original
        bounded exponential backoff (`config.max_retries`) and raises
        BallDontLieHTTPError once exhausted, same as any other non-2xx,
        non-429 status.
        """
        params = dict(params or {})
        attempt = 0
        rate_limit_wait_total = 0.0
        rate_limit_attempts = 0
        while True:
            self._pacer.acquire()
            status, body, resp_headers = self._call_transport(path, params)

            if 200 <= status < 300:
                try:
                    text = body.decode("utf-8") if isinstance(body, bytes) else body
                    return json.loads(text) if text else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise BallDontLieError(
                        f"balldontlie API returned invalid JSON for {path}") from None

            if status == 429:
                rate_limit_attempts += 1
                # The real bound (root cause F): independent of how many
                # seconds were actually slept, so a computed wait of 0 can
                # never turn this into an unbounded retry loop.
                if rate_limit_attempts > self._config.max_429_attempts:
                    self._adapt_pacer_after_429(resp_headers)
                    raise BallDontLieRateLimitExhausted(path, rate_limit_wait_total)
                rate_limit_wait_total = self._handle_429(
                    path, resp_headers, deadline, rate_limit_wait_total)
                continue

            if status in _RETRYABLE_5XX:
                attempt += 1
                if attempt > self._config.max_retries:
                    raise BallDontLieHTTPError(status, path)
                delay = min(self._config.backoff_cap,
                            self._config.backoff_base * (2 ** (attempt - 1)))
                self._sleep(delay)
                continue

            raise BallDontLieHTTPError(status, path)

    def probe(self, path: str, params: Optional[dict] = None) -> tuple:
        """Exactly one request, no retries, no body parsing:
        `(status, whitelisted_rate_limit_headers)`. Used by --probe to check
        the account's current rate-limit state as cheaply as possible --
        deliberately does not call `get()` (which retries 429s and parses
        JSON) since a probe wants to see the raw status, not wait it out."""
        params = dict(params or {})
        self._pacer.acquire()
        status, _body, resp_headers = self._call_transport(path, params)
        return status, resp_headers

    def pages(self, path: str, params: Optional[dict] = None, *,
              page_cap: Optional[int] = None,
              start_cursor: Optional[int] = None,
              deadline: Optional[float] = None) -> Iterator[dict]:
        """Yield each page's full JSON payload, following meta.next_cursor.

        `params` should not itself carry `cursor`; pass a resume point via
        `start_cursor` instead. Stops when a page has no data, or meta has
        no next_cursor, or `page_cap` pages have been yielded (whichever
        comes first). per_page defaults to DEFAULT_PER_PAGE if not set.
        `deadline` is forwarded to every underlying `get()` call so a 429
        wait mid-pagination still respects it.
        """
        base_params = dict(params or {})
        base_params.setdefault("per_page", DEFAULT_PER_PAGE)
        cursor = start_cursor
        pages_yielded = 0
        while page_cap is None or pages_yielded < page_cap:
            call_params = dict(base_params)
            if cursor is not None:
                call_params["cursor"] = cursor
            payload = self.get(path, call_params, deadline=deadline)
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
