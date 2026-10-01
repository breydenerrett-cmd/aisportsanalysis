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
import ipaddress
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


# Upper bound on distinct keys one limiter remembers. Every key is a sha256 hex
# digest plus a two-tuple (~250 bytes), so 10,000 keys is a few MB at most. See
# FixedWindowLimiter._prune for what is dropped when it is exceeded.
MAX_TRACKED_KEYS = 10_000


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

    def _prune(self, now: float) -> None:
        """Bound the table. Called under the lock, only once the table has
        outgrown MAX_TRACKED_KEYS, so the common path stays O(1).

        Expired windows go first (a window older than `window_s` is
        indistinguishable from no window: check() would reset it anyway, so
        dropping it changes no answer). If the table is still over the cap
        because every key is live -- a flood of distinct addresses inside one
        window -- the oldest windows are dropped until it fits. That is the
        deliberate trade: memory stays bounded and the worst case is that an
        attacker rotating keys can reset the counter of the oldest keys, which
        rotating a header already lets them do (see client_ip)."""
        expired = [k for k, (start, _c) in self._windows.items()
                   if now - start >= self.window_s]
        for key in expired:
            del self._windows[key]
        overflow = len(self._windows) - MAX_TRACKED_KEYS
        if overflow > 0:
            oldest = sorted(self._windows, key=lambda k: self._windows[k][0])
            for key in oldest[:overflow]:
                del self._windows[key]

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
            if len(self._windows) > MAX_TRACKED_KEYS:
                self._prune(now)
            if count > self.limit:
                retry_after = max(self.window_s - (now - start), 0.0)
                return LimitResult(allowed=False, limit=self.limit,
                                   remaining=0, retry_after=retry_after)
            return LimitResult(allowed=True, limit=self.limit,
                               remaining=self.limit - count)


FLY_CLIENT_IP_HEADER = "fly-client-ip"
CF_CONNECTING_IP_HEADER = "cf-connecting-ip"

# Cloudflare's published proxy ranges. Source: https://www.cloudflare.com/ips/
# (ips-v4 and ips-v6), transcribed 2026-10-01. Cloudflare changes these rarely
# and announces it; if this list goes stale the failure is safe-ish -- a new
# Cloudflare address is simply not recognised, so the request falls back to
# `Fly-Client-IP` (the old shared-bucket behaviour), never to a spoofable value.
CLOUDFLARE_IP_RANGES = tuple(ipaddress.ip_network(n) for n in (
    # IPv4
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    # IPv6
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
))


def _parse_ip(value) -> Optional[ipaddress._BaseAddress]:
    """`value` as an ip_address, or None. Never raises; an IPv4-mapped IPv6
    address is unwrapped so one client has one spelling (and so a mapped
    Cloudflare address is still recognised as Cloudflare)."""
    try:
        parsed = ipaddress.ip_address((value or "").strip())
    except (ValueError, AttributeError, TypeError):
        return None
    mapped = getattr(parsed, "ipv4_mapped", None)
    return mapped if mapped is not None else parsed


def _is_cloudflare(address) -> bool:
    return any(address.version == net.version and address in net
               for net in CLOUDFLARE_IP_RANGES)


def _header(headers, name: str) -> str:
    try:
        return (headers.get(name) or "").strip()
    except Exception:  # noqa: BLE001 -- a header lookup must never 500 a route
        return ""


def client_ip(request) -> str:
    """The caller's address for rate limiting and any other per-client key.

    BEHIND FLY'S PROXY THE SOCKET PEER IS ALWAYS THE PROXY. The app runs on
    Fly, so `request.client.host` is one of Fly's edge addresses for every
    visitor on earth, and every per-IP limiter (signup 10/h, funnel 60/h,
    support, free bet checks) collapsed the whole site onto one shared bucket.
    Fly sets `Fly-Client-IP` on every request it forwards (overwriting any
    value the client sent), so that header is the real address when the
    request came to Fly directly (linehound-prod.fly.dev).

    THROUGH CLOUDFLARE (linehound.app) `Fly-Client-IP` is a Cloudflare edge
    address shared by many visitors, and the real client is in
    `CF-Connecting-IP`. So:

      1. `Fly-Client-IP` parses AND lies inside CLOUDFLARE_IP_RANGES AND
         `CF-Connecting-IP` is present and parses as an IP address
         -> `CF-Connecting-IP`;
      2. else `Fly-Client-IP` if it parses as an IP address;
      3. else the socket address;
      4. else "unknown" (a test-built scope with no client tuple -- it
         collapses those callers onto one counter, the conservative
         direction, never a bypass).

    `CF-Connecting-IP` is believed ONLY when Fly itself says the hop in front
    of it was Cloudflare, so a client hitting the Fly hostname directly cannot
    choose its bucket with that header: Fly overwrites `Fly-Client-IP` with the
    client's own (non-Cloudflare) address, and rule 1 does not fire.

    Every value is normalised through `ipaddress` before it becomes a key: a
    malformed header (garbage, an oversize string, an embedded newline) never
    raises and never becomes the limiter key verbatim; it falls through to the
    next rule.

    WHAT REMAINS TRUE. On a host that is NOT behind Fly's edge the
    `Fly-Client-IP` header is client-controlled, and a caller can rotate it to
    get a fresh bucket every request. That is an accepted limit of an
    in-process limiter, not a security boundary: this exists to stop an honest
    mistake or a lazy loop, not a determined abuser, and nothing sensitive may
    rely on it alone. (The same is true of a caller rotating real source
    addresses.)
    """
    headers = getattr(request, "headers", None)
    if headers is not None:
        fly = _parse_ip(_header(headers, FLY_CLIENT_IP_HEADER))
        if fly is not None:
            if _is_cloudflare(fly):
                real = _parse_ip(_header(headers, CF_CONNECTING_IP_HEADER))
                if real is not None:
                    return str(real)
            return str(fly)
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return host or "unknown"


# Old private name, kept so nothing importing it breaks.
_client_identity = client_ip


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
