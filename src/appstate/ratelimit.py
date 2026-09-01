"""Fixed-window per-key rate limiting for the paid-beta API, stdlib-only.

WHY THIS EXISTS
----------------
POST /betcheck and POST /my-bets are the two authenticated write paths a
single caller can hammer without ever tripping the schedule-provider cache
in api/games.py -- both run entirely against local data (the domain path
for the former, sqlite for the latter), so nothing upstream slows a caller
down. This module is the guard: a fixed-window counter per key, refused
past its limit with a 429 and a `retry_after` telling the caller when the
window resets.

FIXED WINDOW, NOT A SLIDING ONE OR A TOKEN BUCKET
---------------------------------------------------
A fixed window (count resets to zero at each window boundary) admits a
burst of up to 2x the limit at a boundary (a full window's worth right
before it rolls over, another right after). That is a known, named
trade-off, not an oversight -- it is O(1) state per key with no background
sweep, no cross-request bookkeeping to get subtly wrong, and it is the same
shape freshness.py's TTL cache already uses (a `built_at` timestamp checked
against `now`, not a rolling log of every call). A sliding-window or
token-bucket limiter would close the boundary-burst gap at the cost of
more state and more edge cases to test, for a beta-scale abuse guard where
"can't burst more than 2x for one window" is already the useful property.

THE KEY IS HASHED, NEVER THE RAW IDENTITY
-------------------------------------------
Same rationale as src/appstate/users.py's token hashing: a per-key counter
dict is exactly the kind of thing that ends up in a heap dump or a debug
log, and a raw client IP or user id sitting in it is a fact about a real
person this codebase does not need to keep in the clear. `key_for` hashes
whatever identity a caller resolves (an authenticated user's id, a client
IP as the fallback for the admin/invite-less caller) before it is ever
used as a dict key.

IN-PROCESS, NOT DISTRIBUTED -- READ THIS BEFORE ASSUMING IT SCALES
-----------------------------------------------------------------------
Exactly the limitation freshness.py's module docstring states for its
cache: this is a per-process dict guarded by a lock, so a deployment
running more than one worker process gives each worker its own counter for
the same caller -- a client can get up to (worker_count x limit) requests
through in one window before any single worker's counter would have
refused it. The paid-beta API runs as a single process (deploy/); a
multi-process deployment would need a shared store (Redis, e.g.), which is
out of scope for this task.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    from fastapi import HTTPException, Request
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover -- this module stays importable
    HAS_FASTAPI = False


@dataclass(frozen=True)
class LimitResult:
    """The outcome of one `check()` call. `retry_after` is seconds until
    the current window rolls over, present only when `allowed` is False --
    an allowed call has nothing meaningful to retry."""
    allowed: bool
    limit: int
    remaining: int
    retry_after: Optional[float] = None


def key_for(identity: str) -> str:
    """A stable, opaque key for a raw identity (a user id, a client IP) --
    sha256, the same hash src.appstate.users already uses for tokens, so a
    counter dict never holds a fact about a real person in the clear."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class FixedWindowLimiter:
    """`limit` requests per `window_s` seconds, per key, fixed-window.

    One limiter instance is meant to be shared by every request to one
    route (module-level, same lifetime as freshness.py's caches) -- a
    limiter constructed per-request would have no memory of anything and
    would never refuse a request.
    """

    def __init__(self, limit: int, window_s: float):
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self.limit = limit
        self.window_s = window_s
        # key -> (window_start_epoch_s, count_in_window)
        self._windows: dict = {}
        self._guard = threading.Lock()

    def check(self, key: str, *, now: Optional[float] = None) -> LimitResult:
        """Record one request for `key` and say whether it is allowed.

        `now` is injectable (epoch seconds) purely for tests -- omitted, it
        is `time.time()`. Every call that returns `allowed=True` has
        already been counted; there is no separate "peek" -- a caller
        that wants to know without consuming a slot is not this module's
        use case (both wired routes gate the whole request on the result).
        """
        now = time.time() if now is None else now
        with self._guard:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= self.window_s:
                start, count = now, 0
            count += 1
            self._windows[key] = (start, count)
            if count > self.limit:
                retry_after = max(self.window_s - (now - start), 0.0)
                return LimitResult(allowed=False, limit=self.limit,
                                   remaining=0, retry_after=retry_after)
            return LimitResult(allowed=True, limit=self.limit,
                               remaining=self.limit - count)


def _client_identity(request) -> str:
    """The best identity FastAPI's Request offers with no auth resolved
    yet: the connecting client's IP, or the literal string "unknown" if
    even that is absent (e.g. a test-built ASGI scope with no client
    tuple) -- "unknown" collapses every such caller onto one shared
    counter, which is a conservative (stricter, never looser) fallback,
    not a bypass."""
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return host or "unknown"


def limiter_dependency(limiter: FixedWindowLimiter, *, user_dependency=None):
    """Build a FastAPI dependency that gates a route on `limiter`.

    Guarded by the module-level try-import: calling this without fastapi
    installed raises ImportError immediately (not a NameError deep inside
    a request), so importing this module never requires fastapi -- only
    wiring a route to it does, same seam api/betcheck.py and api/mybets.py
    already use for their own fastapi-only route decorators.

    `user_dependency`, if given, is a zero-arg-from-FastAPI's-perspective
    callable (typically api.auth.get_current_user via Depends) that
    resolves the authenticated caller; its `.id` becomes the rate-limit
    key so one user is one key regardless of which IP they call from.
    Omit it to key on the client IP instead -- the right choice for a
    route with no auth dependency of its own.
    """
    if not HAS_FASTAPI:
        raise ImportError(
            "src.appstate.ratelimit.limiter_dependency requires fastapi; "
            "this module itself does not")

    if user_dependency is not None:
        from fastapi import Depends

        def _dependency(request: Request,
                         current_user=Depends(user_dependency)) -> None:
            key = key_for(f"user:{current_user.id}")
            result = limiter.check(key)
            if not result.allowed:
                raise HTTPException(
                    status_code=429,
                    detail={"error": "rate_limited",
                           "retry_after": result.retry_after})
        return _dependency

    def _dependency(request: Request) -> None:
        key = key_for(f"ip:{_client_identity(request)}")
        result = limiter.check(key)
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail={"error": "rate_limited",
                       "retry_after": result.retry_after})
    return _dependency
