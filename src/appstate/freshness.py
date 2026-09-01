"""TTL cache + serve-stale-with-flag freshness policy for the paid-beta API.

WHY THIS EXISTS
----------------
api/today.py and api/games.py each rebuild a full slate on every request: a
live schedule-provider fetch plus src.pipeline.briefing.build_slate. That is
expensive (network latency, provider credit) and pointless to repeat for
two requests a few seconds apart for the same date -- the domain data does
not change that fast. This module is the caching layer that sits in front
of those rebuilds, stdlib-only (src/ boundary; tests/test_api_boundary.py).

THREE THINGS THIS MODULE PROMISES, EACH FOR A DIFFERENT FAILURE MODE
-----------------------------------------------------------------------
1. TTL: a rebuild happens at most once per key per `ttl_s` -- everything
   else in that window is a cache hit.
2. SINGLE-FLIGHT (stampede protection): if N requests for the same
   (endpoint, date, args) key arrive while no fresh value exists, exactly
   one of them pays for the rebuild; the other N-1 block on that same
   rebuild and share its result rather than each starting their own
   provider fetch. A cache with a TTL but no single-flight lock turns
   "traffic spiked right as the entry expired" into a request pile-up on
   the most expensive code path in the app -- the opposite of what a
   cache is for.
3. SERVE-STALE-WITH-FLAG, NEVER SILENT: when a rebuild fails (provider
   down, etc.), this module never fabricates a fresh-looking payload.
     - If a last-good value exists, it is served with `stale=True` and a
       `stale_reason` naming the rebuild failure -- old-but-honest beats
       fresh-but-fake for a betting-adjacent product.
     - If no last-good value exists at all, there is nothing honest to
       serve: the original rebuild exception is re-raised so the caller's
       own error handling (api/games.py already turns a schedule-provider
       failure into a structured 502) decides what the client sees. This
       module does not invent a payload shape here; the endpoint already
       owns its error contract.

FRESHNESS IS A SEPARATE QUESTION FROM CACHE AGE
--------------------------------------------------
A payload can be well within its TTL and still carry data that is stale in
the sense a bettor cares about: an odds board captured 40 minutes ago. That
is not a caching fact, it is a fact about the data, so `FreshnessPolicy` is
evaluated on every read (hit or rebuild) against the *current* clock, not
computed once at build time and left to rot in the cached value.

WHAT THIS MODULE DOES NOT DO
--------------------------------
- No eviction/size limit: the api/ layer only ever has a handful of live
  (endpoint, date) keys at once (one date at a time, in practice), so an
  unbounded dict is the honest choice over a fake LRU that would need its
  own tests to prove correct for no real benefit here.
- No cross-process sharing: this is an in-memory, per-process cache. The
  paid-beta API runs as a single process (deploy/); a multi-process
  deployment would need a shared store, which is out of scope for this
  task.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

# Odds go stale well before a cache entry's own TTL would expire it --
# thirty minutes is long enough that a line has almost certainly moved,
# short enough that "half an hour old" is still a defensible number to
# show a bettor rather than an arbitrary one. Named and overridable per
# FreshnessPolicy instance rather than hard-coded, since a future
# endpoint may reasonably want a tighter or looser threshold.
DEFAULT_ODDS_MAX_AGE_S = 30 * 60


def _age_seconds_from_iso(observed_utc: Optional[str], *, now: datetime) -> Optional[float]:
    """Seconds between an ISO timestamp and `now`, or None if there is no
    timestamp to age. Mirrors api/today.py's `_odds_age_seconds` (same
    absence-over-fabrication rule: a missing observed_utc is never
    silently treated as "just captured").
    """
    if not observed_utc:
        return None
    try:
        observed = datetime.fromisoformat(str(observed_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max((now.astimezone(timezone.utc) - observed).total_seconds(), 0.0)


class FreshnessPolicy:
    """Decides whether an odds-bearing payload should be flagged stale on
    account of the *data*, independent of whether the cache entry holding
    it is within its own TTL.

    Kept as an object (not a bare function) because a future caller may
    want a different threshold per endpoint without this module growing a
    parameter for every call site -- construct one policy per threshold
    and pass it to a SingleFlightTTLCache.
    """

    def __init__(self, odds_max_age_s: float = DEFAULT_ODDS_MAX_AGE_S):
        self.odds_max_age_s = odds_max_age_s

    def evaluate_odds_age(self, newest_observed_utc: Optional[str], *,
                          now: datetime) -> Tuple[bool, Optional[str]]:
        """(stale, reason) from the single newest board row's timestamp.

        `None` (no odds-bearing row exists in the payload at all) is never
        stale on this basis -- "we have no odds" and "our odds are old"
        are different facts, and this policy only speaks to the second.
        """
        age_s = _age_seconds_from_iso(newest_observed_utc, now=now)
        if age_s is None:
            return False, None
        if age_s > self.odds_max_age_s:
            return True, (f"newest odds board is {age_s:.0f}s old, over the "
                          f"{self.odds_max_age_s:.0f}s freshness threshold")
        return False, None


@dataclass
class _Entry:
    """One cached value plus when it was built. No error state is kept on
    the entry itself -- a rebuild failure is a property of the *attempt*
    that just happened, evaluated fresh against `now` each time, not
    something baked into the stored value.
    """
    value: Any
    built_at: datetime


# Type of the optional hook a caller passes to report the newest
# odds-bearing board's `observed_utc` out of an already-built value, so
# FreshnessPolicy can age it against the current clock on every read.
OddsObservedExtractor = Callable[[Any], Optional[str]]


class SingleFlightTTLCache:
    """A TTL cache keyed by an arbitrary hashable key (this module's
    callers use `(endpoint, date, args_tuple)`), with a per-key lock for
    stampede protection and freshness metadata attached to every result.
    """

    def __init__(self, ttl_s: float, policy: Optional[FreshnessPolicy] = None):
        self.ttl_s = ttl_s
        self.policy = policy or FreshnessPolicy()
        self._entries: dict = {}
        self._locks: dict = {}
        # Guards only the _locks dict itself (creating/looking-up the
        # per-key lock) -- the actual rebuild work happens under the
        # per-key lock, never under this one, so unrelated keys never
        # block each other.
        self._locks_guard = threading.Lock()

    def _lock_for(self, key: Any) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _meta(self, *, served_at: datetime, built_at: Optional[datetime],
              age_s: Optional[float], stale: bool,
              stale_reason: Optional[str]) -> dict:
        return {
            "served_at": served_at.isoformat(),
            "built_at": built_at.isoformat() if built_at else None,
            "age_s": age_s,
            "stale": stale,
            "stale_reason": stale_reason,
        }

    def _odds_stale(self, value: Any, *, now: datetime,
                    odds_observed_extractor: Optional[OddsObservedExtractor]
                    ) -> Tuple[bool, Optional[str]]:
        if odds_observed_extractor is None:
            return False, None
        newest_observed = odds_observed_extractor(value)
        return self.policy.evaluate_odds_age(newest_observed, now=now)

    def get(self, key: Any, builder: Callable[[], Any], *,
           odds_observed_extractor: Optional[OddsObservedExtractor] = None
           ) -> Tuple[Any, dict]:
        """Return (value, freshness_meta) for `key`, calling `builder()` at
        most once per TTL window and at most once across any number of
        threads racing on the same cold/expired key.

        `builder` takes no arguments (callers close over whatever the
        rebuild needs -- date, fetch fn, store) and is expected to return
        the finished payload. `odds_observed_extractor`, if given, is
        called with the (possibly cached) value on every read to get the
        newest odds board's `observed_utc`, so the odds-staleness check
        always reflects the current clock rather than the clock at build
        time.

        On a rebuild failure: serves the last-good value marked stale if
        one exists; re-raises the builder's exception, untouched, if none
        does (see module docstring -- this module does not invent an error
        shape the caller doesn't already own).
        """
        now = datetime.now(timezone.utc)
        entry = self._entries.get(key)
        if entry is not None and (now - entry.built_at).total_seconds() < self.ttl_s:
            return self._serve_hit(entry, now, odds_observed_extractor)

        lock = self._lock_for(key)
        with lock:
            # Re-check inside the lock: another thread may have already
            # rebuilt this key while we were waiting to acquire it -- that
            # is the single-flight property, not a redundant check.
            now = datetime.now(timezone.utc)
            entry = self._entries.get(key)
            if entry is not None and (now - entry.built_at).total_seconds() < self.ttl_s:
                return self._serve_hit(entry, now, odds_observed_extractor)

            try:
                value = builder()
            except Exception:
                if entry is not None:
                    age_s = (now - entry.built_at).total_seconds()
                    reason = (f"rebuild failed; serving last-good value "
                             f"from {entry.built_at.isoformat()} "
                             f"({age_s:.0f}s old)")
                    return entry.value, self._meta(
                        served_at=now, built_at=entry.built_at, age_s=age_s,
                        stale=True, stale_reason=reason)
                # No last-good value to fall back on -- nothing honest to
                # serve. Let the original exception through unchanged so
                # the caller's existing error handling (e.g. api/games.py's
                # MLBError -> 502) still applies.
                raise

            self._entries[key] = _Entry(value=value, built_at=now)
            stale, reason = self._odds_stale(
                value, now=now, odds_observed_extractor=odds_observed_extractor)
            return value, self._meta(served_at=now, built_at=now, age_s=0.0,
                                     stale=stale, stale_reason=reason)

    def _serve_hit(self, entry: _Entry, now: datetime,
                   odds_observed_extractor: Optional[OddsObservedExtractor]
                   ) -> Tuple[Any, dict]:
        age_s = (now - entry.built_at).total_seconds()
        stale, reason = self._odds_stale(
            entry.value, now=now, odds_observed_extractor=odds_observed_extractor)
        return entry.value, self._meta(served_at=now, built_at=entry.built_at,
                                       age_s=age_s, stale=stale, stale_reason=reason)

    def invalidate(self, key: Any) -> None:
        """Drop one key's cached value, if any. Not used by the wired
        endpoints today (TTL expiry is enough for a 120s window) but kept
        as an escape hatch -- tests use it to force a rebuild without
        sleeping past the TTL.
        """
        self._entries.pop(key, None)
