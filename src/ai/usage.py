"""The append-only usage store: one JSON line per model call, and the aggregates read back from it.

WHY A FILE AND NOT MEMORY. The monthly dollar cap has to survive a restart, a deploy and a crash: a cap
held only in memory resets to zero every time Fly redeploys (hourly, when CI is green), which would make
it no cap at all. So every call is appended before anything else happens with its result, and the
router asks THIS store how much has been spent, never its own counter.

TWO ROW KINDS (both carry ``ts``, an ISO UTC stamp the store writes; the clock is injected):

  call      {kind, ts, day, month, provider, model, status, latency_ms, cost_usd, input_tokens,
             output_tokens, error, purpose}. ``status`` is one of ok, invalid (the model answered but
             the answer failed the schema or the semantic check), quota (429 or 402), auth (401 or 403),
             timeout, error (anything else), refused (the model declined).
  cooldown  {kind, ts, provider, until, reason}: skip this provider until ``until``. The newest row for a
             provider wins.
  batch_submit / batch_done  a Message Batches job. A batch is paid for later and reported later, so the
             money it could cost is RESERVED against the month's cap from the moment it is submitted
             (``reserved_usd``, the worst case at the 50% batch price) and released by ``batch_done``; the
             actual cost lands as ordinary ``call`` rows, one per request, written when the results are read.
             A batch that is never read keeps its reservation: the cap errs toward spending less.

MEMORY. Reading is incremental and streamed: the first call reads the file once, one line at a time, and
keeps only counters (calls and cost by day and month, status counts, the newest cooldown per provider,
the last 50 errors). Later calls read only the bytes appended since the last read, so a second process
or a hand edit is seen without re-reading the file. A torn last line (a crash mid-write) is left unread
until it completes. Production has 1 GB; nothing here ever holds the whole file.

The file is NOT a hash chain: it is operational telemetry and holds no bet. The bets and the decisions
(``src/hounds/ai_runner.py``) are the evidence; this is the meter.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Tuple

ERRORS_KEPT = 50
ERROR_TEXT_CHARS = 300          # an error line is a hint for the owner, not a copy of the provider's page


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class UsageStore:
    def __init__(self, path, *, clock: Optional[Callable[[], datetime]] = None):
        self.path = Path(path)
        self._clock = clock or _utcnow
        self._lock = threading.RLock()
        self._offset = 0
        self._calls: Dict[Tuple[str, str], int] = {}                 # (day, provider) -> calls
        self._status: Dict[Tuple[str, str, str], int] = {}           # (day, provider, status) -> calls
        self._spend: Dict[Tuple[str, str], float] = {}               # (month, provider) -> usd
        self._cooldowns: Dict[str, Tuple[datetime, str]] = {}        # provider -> (until, reason)
        self._errors: Deque[dict] = deque(maxlen=ERRORS_KEPT)
        self._last_ok: Dict[str, str] = {}
        self._open_batches: Dict[str, Tuple[str, str, float]] = {}    # batch id -> (month, provider, reserved usd)
        self._done_batches: set = set()

    # -- time ---------------------------------------------------------------

    def now(self) -> datetime:
        return self._clock()

    def today(self) -> str:
        return self.now().astimezone(timezone.utc).date().isoformat()

    def month(self) -> str:
        return self.today()[:7]

    # -- reading ------------------------------------------------------------

    def _reset(self) -> None:
        self._offset = 0
        self._calls.clear()
        self._status.clear()
        self._spend.clear()
        self._cooldowns.clear()
        self._errors.clear()
        self._last_ok.clear()
        self._open_batches.clear()
        self._done_batches.clear()

    def _apply(self, row: dict) -> None:
        kind = row.get("kind")
        provider = str(row.get("provider") or "")
        if kind == "call":
            day = str(row.get("day") or str(row.get("ts") or "")[:10])
            month = str(row.get("month") or day[:7])
            status = str(row.get("status") or "error")
            self._calls[(day, provider)] = self._calls.get((day, provider), 0) + 1
            self._status[(day, provider, status)] = self._status.get((day, provider, status), 0) + 1
            try:
                cost = float(row.get("cost_usd") or 0.0)
            except (TypeError, ValueError):
                cost = 0.0
            if cost:
                self._spend[(month, provider)] = self._spend.get((month, provider), 0.0) + cost
            if status == "ok":
                self._last_ok[provider] = str(row.get("ts") or "")
            else:
                self._errors.append({k: row.get(k) for k in
                                     ("ts", "provider", "model", "status", "error", "latency_ms", "purpose")})
        elif kind == "cooldown":
            until = _parse(row.get("until"))
            if until is not None:
                self._cooldowns[provider] = (until, str(row.get("reason") or ""))
        elif kind == "batch_submit":
            bid = str(row.get("batch_id") or "")
            if bid and bid not in self._done_batches:
                try:
                    reserved = float(row.get("reserved_usd") or 0.0)
                except (TypeError, ValueError):
                    reserved = 0.0
                self._open_batches[bid] = (str(row.get("month") or str(row.get("ts") or "")[:7]), provider, reserved)
        elif kind == "batch_done":
            bid = str(row.get("batch_id") or "")
            self._open_batches.pop(bid, None)
            self._done_batches.add(bid)

    def _sync(self) -> None:
        """Read whatever was appended since the last read. Caller holds the lock."""
        try:
            size = self.path.stat().st_size
        except OSError:
            if self._offset:
                self._reset()
            return
        if size < self._offset:
            self._reset()
        if size == self._offset:
            return
        with self.path.open("rb") as fh:
            fh.seek(self._offset)
            chunk = fh.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return                                   # a torn first line: wait for it to complete
        for raw in chunk[:end + 1].split(b"\n"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(row, dict):
                self._apply(row)
        self._offset += end + 1

    # -- writing ------------------------------------------------------------

    def _append(self, row: dict) -> None:
        line = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as fh:
            fh.write(line.encode("ascii"))
            fh.flush()

    def record_call(self, *, provider: str, model: Optional[str], status: str, latency_ms: Optional[int] = None,
                    cost_usd: float = 0.0, input_tokens: Optional[int] = None, output_tokens: Optional[int] = None,
                    error: Optional[str] = None, purpose: str = "") -> dict:
        with self._lock:
            self._sync()
            moment = self.now()
            row = {"kind": "call", "ts": _iso(moment), "day": moment.astimezone(timezone.utc).date().isoformat(),
                   "month": moment.astimezone(timezone.utc).strftime("%Y-%m"), "provider": provider, "model": model,
                   "status": status, "latency_ms": latency_ms, "cost_usd": round(float(cost_usd or 0.0), 8),
                   "input_tokens": input_tokens, "output_tokens": output_tokens,
                   "error": (str(error)[:ERROR_TEXT_CHARS] if error else None), "purpose": purpose}
            self._append(row)
            self._sync()
            return row

    def record_cooldown(self, provider: str, until: datetime, reason: str) -> dict:
        with self._lock:
            self._sync()
            row = {"kind": "cooldown", "ts": _iso(self.now()), "provider": provider, "until": _iso(until),
                   "reason": str(reason)[:ERROR_TEXT_CHARS]}
            self._append(row)
            self._sync()
            return row

    def record_batch_submit(self, *, batch_id: str, provider: str, model: Optional[str], reserved_usd: float,
                            n_requests: int, purpose: str = "") -> dict:
        with self._lock:
            self._sync()
            row = {"kind": "batch_submit", "ts": _iso(self.now()), "month": self.month(), "batch_id": batch_id,
                   "provider": provider, "model": model, "reserved_usd": round(float(reserved_usd), 8),
                   "n_requests": n_requests, "purpose": purpose}
            self._append(row)
            self._sync()
            return row

    def record_batch_done(self, *, batch_id: str, provider: str, status: str, actual_usd: float) -> dict:
        with self._lock:
            self._sync()
            row = {"kind": "batch_done", "ts": _iso(self.now()), "batch_id": batch_id, "provider": provider,
                   "status": status, "actual_usd": round(float(actual_usd), 8)}
            self._append(row)
            self._sync()
            return row

    # -- aggregates ---------------------------------------------------------

    def reserved(self, provider: str, month: Optional[str] = None) -> float:
        """Dollars held back for batches submitted this month and not yet read."""
        with self._lock:
            self._sync()
            m = month or self.month()
            return round(sum(r for (mm, p, r) in self._open_batches.values() if mm == m and p == provider), 8)

    def open_batches(self) -> List[str]:
        with self._lock:
            self._sync()
            return sorted(self._open_batches)

    def batch_done(self, batch_id: str) -> bool:
        with self._lock:
            self._sync()
            return batch_id in self._done_batches

    def calls_today(self, provider: str) -> int:
        with self._lock:
            self._sync()
            return self._calls.get((self.today(), provider), 0)

    def status_today(self, provider: str) -> Dict[str, int]:
        with self._lock:
            self._sync()
            day = self.today()
            return {s: n for (d, p, s), n in self._status.items() if d == day and p == provider}

    def month_spend(self, provider: str, month: Optional[str] = None) -> float:
        with self._lock:
            self._sync()
            return round(self._spend.get((month or self.month(), provider), 0.0), 8)

    def total_month_spend(self, month: Optional[str] = None) -> float:
        with self._lock:
            self._sync()
            m = month or self.month()
            return round(sum(v for (mm, _p), v in self._spend.items() if mm == m), 8)

    def cooldown(self, provider: str) -> Optional[Tuple[datetime, str]]:
        """``(until, reason)`` while the provider is cooling down, else None."""
        with self._lock:
            self._sync()
            hit = self._cooldowns.get(provider)
            if hit is None or hit[0] <= self.now():
                return None
            return hit

    def recent_errors(self, n: int = 10) -> List[dict]:
        with self._lock:
            self._sync()
            return list(self._errors)[-n:][::-1]

    def last_ok(self, provider: str) -> Optional[str]:
        with self._lock:
            self._sync()
            return self._last_ok.get(provider)
