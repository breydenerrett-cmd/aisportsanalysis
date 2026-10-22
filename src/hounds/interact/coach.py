"""The coach of a training: the diagnosis, the AI read of it, and the one place a request keeps them between its three steps.

Send to training is now three calls from the page, so the screen can show the work as it happens and never fake it:

    POST /hounds/{id}/train/diagnose   the diagnosis table (fast, no model), cached for the next two steps
    POST /hounds/{id}/train/assess     the AI read of that table (the real wait; ``coach_ai.assess``), cached
    POST /hounds/{id}/train            the training itself, which takes the cached read instead of asking again

The cache is per process, keyed by the hound and by exactly the settled bets and rule it was computed from (a new settled bet or
an edited rule is a new key), held for ``TTL_S`` seconds. A miss is never an error: the step simply computes what it needs, so a
training that reaches a different worker than its diagnosis only re-reads. ``assess`` is single-flight per key, so two taps
cannot pay for the same read twice, and an answer is cached whether it came from the model or from the rules engine.

``Coach(rules_only=True)`` is what ``training.train`` uses when nothing is injected (every existing caller and test): no
router, no disk, the deterministic read. The live routes use ``live()``, which reads the real schedule and captured odds
(``diagnosis_live``) and asks the process's router.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Callable, Mapping, Optional, Sequence

from src.hounds import user_spec
from src.hounds.interact import coach_ai, diagnosis as D

logger = logging.getLogger("linehound.hounds.coach")

TTL_S = 1800
MAX_ENTRIES = 256


def key_for(hound_id: str, spec: Mapping, bets: Sequence) -> str:
    """The cache key: the hound, its rule, and exactly which bets settled how."""
    settled = sorted((b.bet_id, b.result) for b in bets if b.result in ("win", "loss", "push"))
    raw = "|".join([hound_id, user_spec.spec_hash(spec)] + [f"{i}:{r}" for i, r in settled])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class Coach:
    def __init__(self, *, context_factory: Optional[Callable] = None, router=None, env: Optional[Mapping] = None,
                 rules_only: bool = False, ttl_s: float = TTL_S, clock: Callable[[], float] = time.monotonic,
                 assess_fn: Optional[Callable] = None):
        self.context_factory = context_factory
        self.router = router
        self.env = env
        self.rules_only = rules_only
        self.ttl_s = ttl_s
        self.clock = clock
        self.assess_fn = assess_fn
        self._cache: dict = {}
        self._lock = threading.Lock()
        self._flight: dict = {}

    # -- the cache -----------------------------------------------------------

    def _get(self, key: str) -> Optional[dict]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if self.clock() - entry["at"] > self.ttl_s:
                del self._cache[key]
                return None
            return entry

    def _put(self, key: str, **fields) -> dict:
        with self._lock:
            entry = self._cache.setdefault(key, {"at": self.clock()})
            entry.update(fields)
            entry["at"] = self.clock()
            while len(self._cache) > MAX_ENTRIES:
                self._cache.pop(min(self._cache, key=lambda k: self._cache[k]["at"]))
            return entry

    def forget(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    # -- the steps -------------------------------------------------------------

    def diagnosis(self, inp: Mapping) -> dict:
        """Step one: the table. ``inp`` carries hound_id, bets, spec, rows, rule_index."""
        key = key_for(inp["hound_id"], inp["spec"], inp["bets"])
        hit = self._get(key)
        if hit and "diagnosis" in hit:
            return hit["diagnosis"]
        context = None if self.rules_only or self.context_factory is None else self.context_factory()
        table = D.diagnose(inp["bets"], inp["spec"], rows=inp.get("rows"), rule_index=inp.get("rule_index"), context=context)
        self._put(key, diagnosis=table)
        return table

    def read(self, inp: Mapping, entries: Sequence[Mapping], table: Mapping) -> dict:
        """Step two: the read of the table (cached; single-flight per key)."""
        key = key_for(inp["hound_id"], inp["spec"], inp["bets"])
        hit = self._get(key)
        if hit and "assessment" in hit:
            return hit["assessment"]
        with self._lock:
            gate = self._flight.setdefault(key, threading.Lock())
        with gate:
            hit = self._get(key)
            if hit and "assessment" in hit:
                return hit["assessment"]
            if self.rules_only:
                read = coach_ai.rules_read(table, status="off", why="no AI read was asked for")
            elif self.assess_fn is not None:
                read = self.assess_fn(table, entries)
            else:
                read = coach_ai.assess(table, entries, router=self.router, env=self.env)
            logger.info("training coach hound=%s source=%s status=%s cost_usd=%.6f factors=%d settled=%s",
                        inp["hound_id"], read["source"], read["status"], read.get("cost_usd") or 0.0,
                        len(table.get("rows", ())), table.get("settled"))
            self._put(key, diagnosis=table, assessment=read)
            with self._lock:
                self._flight.pop(key, None)
            return read


_LIVE: Optional[Coach] = None
_LIVE_LOCK = threading.Lock()


def live() -> Coach:
    """The process's coach for the live routes: the real schedule and captured odds, the process's router."""
    global _LIVE
    with _LIVE_LOCK:
        if _LIVE is None:
            from src.hounds.interact import diagnosis_live
            _LIVE = Coach(context_factory=diagnosis_live.live_context)
        return _LIVE


def reset_live() -> None:
    global _LIVE
    with _LIVE_LOCK:
        _LIVE = None


def public_view(table: Mapping) -> dict:
    """What the page receives of a diagnosis: the rows in screen order, the ranking and the sample-size note."""
    return {"version": table["version"], "settled": table["settled"], "overall": table["overall"], "rows": table["rows"],
            "ranked": table["ranked"], "holding": table["holding"], "meta": table["meta"], "paper_only": True}
