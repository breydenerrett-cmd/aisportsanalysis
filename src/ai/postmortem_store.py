"""The two append-only files behind the hindsight reviews: the QUEUE (what is waiting) and the LEDGER (what was written).

WHERE THEY LIVE. Beside the app database (the Fly volume in production), never in git and never in the image, exactly like the AI
usage meter (``src/ai/usage.py``): a redeploy replaces the repo, not the volume, so a queue and a ledger held anywhere else would
reset hourly. ``default_paths`` resolves them; tests pass temp paths.

IDENTITY. A bet has no id on the contract's ``BetRow``, so ``bet_key`` makes one: a short hash of what makes a ticket THIS ticket
(hound, slate day, matchup, market, pick, line, segment, the time the row was written). It is computed from the row alone, so the
export, the record page, the queue and the ledger all derive the same key without sharing a table.

THE QUEUE is an event log, one JSON line per event, state rebuilt by replaying it (incrementally: later reads take only the bytes
appended since the last read, as ``usage.UsageStore`` does, so a second process or a hand edit is seen and nothing is ever held
whole). Events: ``epoch`` (the first scan's start line: bets graded before it are history, not backlog), ``queued``, ``skipped``
(a Learner bet the sample passed over, remembered so a re-scan does not flip the draw), ``submitted`` (a batch and its items),
``batch_closed``, ``done`` and ``failed`` (``retry: true`` puts the item back in the line with one more attempt).

THE LEDGER is one row per (bet, depth). FIRST WRITE WINS: a second append for the same bet and depth is refused and returns False,
so a replayed batch result can never overwrite a review. A fast review and a deep review of the same bet are two rows. Only a
small digest of each row is kept in memory (tags, verdict words, the lesson); the full row is read back from the file by offset.

A THIRD FILE, THE DEEP LEDGER (``DeepReviewLedger``): one append-only row per lineage-wide Deep review (``src/ai/deep_review.py``), a new
row each time and the old ones kept, with the numbers the app counted stored beside the words. Queue items carry an ``origin``: ``live``
(a bet graded after reviews began) or ``backfill`` (a past bet, or a lineage Deep review: the one-time catch-up behind its own wall).

NOTHING HERE HOLDS A PERSON. A row has hound ids and names, the bet's own facts, the review and its public URLs; no user id, no
email, no key. Paper only.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from src.ai.postmortem_parse import DEEP_LABEL, DEPTH_DEEP, DEPTH_FAST, DEPTH_LINEAGE, LABEL

TIER_MEMBER, TIER_HOUSE, TIER_LEARNER = "member", "house", "learner"
TIER_RANK = {TIER_MEMBER: 0, TIER_HOUSE: 1, TIER_LEARNER: 2}
DEPTH_RANK = {DEPTH_FAST: 0, DEPTH_DEEP: 1, DEPTH_LINEAGE: 2}
#: Where a queued item came from. ``live`` is a bet graded after reviews began (the original flow, its own $20 a month wall); ``backfill``
#: is the one-time catch-up on past bets and the lineage Deep reviews (its own one-time wall, ``postmortems.load_backfill_config``).
ORIGIN_LIVE, ORIGIN_BACKFILL = "live", "backfill"

QUEUE_FILE = "postmortem_queue_v1.jsonl"
LEDGER_FILE = "postmortems_v1.jsonl"
DEEP_FILE = "postmortem_deep_v1.jsonl"
LEDGER_VERSION = 1
DEEP_LEDGER_VERSION = 1
ENV_QUEUE, ENV_LEDGER, ENV_DEEP = "POSTMORTEM_QUEUE_PATH", "POSTMORTEM_LEDGER_PATH", "POSTMORTEM_DEEP_PATH"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(stamp: Any) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def default_paths(env: Optional[Mapping] = None) -> Tuple[Path, Path]:
    """``(queue path, ledger path)``: an env override each, else files beside the app database."""
    source = env if env is not None else os.environ
    queue, ledger = (source.get(ENV_QUEUE) or "").strip(), (source.get(ENV_LEDGER) or "").strip()
    if queue and ledger:
        return Path(queue), Path(ledger)
    from src.appstate import users as users_store
    base = users_store.db_path().parent
    return Path(queue) if queue else base / QUEUE_FILE, Path(ledger) if ledger else base / LEDGER_FILE


def default_deep_path(env: Optional[Mapping] = None) -> Path:
    """The lineage Deep reviews' ledger: an env override, else a file beside the app database like the other two."""
    source = env if env is not None else os.environ
    chosen = (source.get(ENV_DEEP) or "").strip()
    if chosen:
        return Path(chosen)
    from src.appstate import users as users_store
    return users_store.db_path().parent / DEEP_FILE


def bet_key(hound_id: Any, row: Any) -> str:
    """``pm_`` and 16 hex characters: the identity of one ticket, from fields every ``BetRow`` carries."""
    parts = [hound_id, getattr(row, "date", None), getattr(row, "event_id", None) or getattr(row, "game", None),
             getattr(row, "market", None), getattr(row, "selection", None), getattr(row, "line", None),
             getattr(row, "segment", None), getattr(row, "recorded_utc", None)]
    blob = "|".join("" if p is None else str(p) for p in parts)
    return "pm_" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _append_line(path: Path, row: dict) -> None:
    line = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as fh:
        fh.write(line.encode("ascii"))
        fh.flush()


def _read_new(path: Path, offset: int) -> Tuple[List[Tuple[int, int, dict]], int, bool]:
    """``(rows as (offset, length, row), new offset, reset)``: whole lines appended after ``offset``. A torn last line waits."""
    try:
        size = path.stat().st_size
    except OSError:
        return [], 0, offset > 0
    reset = size < offset
    if reset:
        offset = 0
    if size == offset:
        return [], offset, reset
    with path.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset, reset
    rows: List[Tuple[int, int, dict]] = []
    pos = offset
    for raw in chunk[:end + 1].split(b"\n"):
        length = len(raw) + 1
        stripped = raw.strip()
        if stripped:
            try:
                row = json.loads(stripped.decode("utf-8"))
            except ValueError:
                row = None
            if isinstance(row, dict):
                rows.append((pos, length - 1, row))
        pos += length
    return rows, offset + end + 1, reset


# ---------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------

class QueueStore:
    def __init__(self, path, *, clock: Optional[Callable[[], datetime]] = None):
        self.path = Path(path)
        self._clock = clock or _utcnow
        self._lock = threading.RLock()
        self._reset()

    def _reset(self) -> None:
        self._offset = 0
        self._since: Optional[str] = None
        self._known: set = set()
        self._items: Dict[Tuple[str, str], dict] = {}
        self._batches: Dict[str, List[Tuple[str, str]]] = {}
        self._batch_ts: Dict[str, str] = {}
        self._last_submit: Dict[str, str] = {}
        self._batch_origin: Dict[str, str] = {}
        self._seq = 0

    def now(self) -> datetime:
        return self._clock()

    def _apply(self, row: dict) -> None:
        kind = row.get("kind")
        key, depth = str(row.get("bet_key") or ""), str(row.get("depth") or DEPTH_FAST)
        if kind == "epoch":
            self._since = str(row.get("since") or "") or self._since
        elif kind == "queued" and key:
            self._seq += 1
            self._known.add(key)
            self._items[(key, depth)] = {
                "bet_key": key, "depth": depth, "tier": row.get("tier") or TIER_HOUSE, "hound_id": row.get("hound_id"),
                "bet": row.get("bet") or {}, "status": "pending", "attempts": int(row.get("attempt") or 0),
                "batch_id": None, "seq": self._seq, "queued_ts": row.get("ts"), "origin": row.get("origin") or ORIGIN_LIVE}
        elif kind == "skipped" and key:
            self._known.add(key)
        elif kind == "submitted":
            bid = str(row.get("batch_id") or "")
            pairs = [(str(a), str(b)) for a, b in (row.get("items") or ())]
            origin = row.get("origin") or ORIGIN_LIVE
            self._batches[bid] = pairs
            self._batch_ts[bid] = str(row.get("ts") or "")
            self._batch_origin[bid] = origin
            self._last_submit[origin] = str(row.get("ts") or self._last_submit.get(origin) or "")
            for pair in pairs:
                item = self._items.get(pair)
                if item is not None:
                    item["status"], item["batch_id"] = "submitted", bid
        elif kind == "batch_closed":
            bid = str(row.get("batch_id") or "")
            self._batches.pop(bid, None)
            self._batch_ts.pop(bid, None)
            self._batch_origin.pop(bid, None)
        elif kind in ("done", "failed") and key:
            item = self._items.get((key, depth))
            if item is None:
                return
            if kind == "done":
                item["status"], item["bet"] = "done", {}
            elif row.get("retry"):
                item["status"], item["batch_id"] = "pending", None
                item["attempts"] += 1
            else:
                item["status"], item["bet"] = "failed", {}
                item["reason"] = str(row.get("reason") or "")

    def _sync(self) -> None:
        rows, offset, reset = _read_new(self.path, self._offset)
        if reset:
            self._reset()
        for _pos, _length, row in rows:
            self._apply(row)
        self._offset = offset

    def _write(self, row: dict) -> None:
        self._sync()
        row = {**row, "ts": iso(self.now())}
        _append_line(self.path, row)
        self._sync()

    # -- the first scan's line -------------------------------------------------

    def since(self) -> Optional[str]:
        with self._lock:
            self._sync()
            return self._since

    def set_epoch(self, since_iso: str) -> None:
        with self._lock:
            self._sync()
            if self._since is None:
                self._write({"kind": "epoch", "since": since_iso})

    # -- adding, finishing ------------------------------------------------------

    def is_known(self, key: str) -> bool:
        with self._lock:
            self._sync()
            return key in self._known

    def known_snapshot(self) -> set:
        """A copy of every bet key the log has queued or skipped (one read for a whole scan, not one per bet)."""
        with self._lock:
            self._sync()
            return set(self._known)

    def enqueue(self, bet: Mapping, tier: str, depth: str = DEPTH_FAST, origin: str = ORIGIN_LIVE) -> bool:
        """Add one item. False (and nothing written) when this bet and depth are already in the log. A live item's line carries no
        ``origin`` (the log before the backfill read exactly so); a backfill item's does."""
        with self._lock:
            self._sync()
            key = str(bet["bet_key"])
            if (key, depth) in self._items:
                return False
            row = {"kind": "queued", "bet_key": key, "depth": depth, "tier": tier, "hound_id": bet.get("hound_id"), "bet": dict(bet)}
            if origin != ORIGIN_LIVE:
                row["origin"] = origin
            self._write(row)
            return True

    def skip(self, key: str, reason: str) -> None:
        with self._lock:
            self._sync()
            if key not in self._known:
                self._write({"kind": "skipped", "bet_key": key, "reason": reason})

    def submitted(self, batch_id: str, items: Sequence[Tuple[str, str]], origin: str = ORIGIN_LIVE) -> None:
        with self._lock:
            row = {"kind": "submitted", "batch_id": batch_id, "items": [list(p) for p in items]}
            if origin != ORIGIN_LIVE:
                row["origin"] = origin
            self._write(row)

    def batch_closed(self, batch_id: str) -> None:
        with self._lock:
            self._write({"kind": "batch_closed", "batch_id": batch_id})

    def done(self, key: str, depth: str) -> None:
        with self._lock:
            self._write({"kind": "done", "bet_key": key, "depth": depth})

    def failed(self, key: str, depth: str, reason: str, *, retry: bool) -> None:
        with self._lock:
            self._write({"kind": "failed", "bet_key": key, "depth": depth, "reason": str(reason)[:200], "retry": bool(retry)})

    # -- reading ----------------------------------------------------------------

    def get(self, key: str, depth: str) -> Optional[dict]:
        with self._lock:
            self._sync()
            item = self._items.get((key, depth))
            return dict(item) if item is not None else None

    def pending(self, origin: Optional[str] = None) -> List[dict]:
        """Items waiting for a request, in priority order. LIVE items first (they are the original flow and the month's wall): member
        hounds, then house hounds, then The Learner; fast before deep inside a tier; oldest first inside that. BACKFILL items after
        them: a lineage Deep review first (one cheap request per hound), then past bets NEWEST FIRST (owner ask 2026-10-28), a newer
        bet's deep pass ahead of an older bet's fast one. ``origin`` keeps one kind only."""
        with self._lock:
            self._sync()
            waiting = [dict(i) for i in self._items.values() if i["status"] == "pending" and origin in (None, i["origin"])]
        live = [i for i in waiting if i["origin"] != ORIGIN_BACKFILL]
        past = [i for i in waiting if i["origin"] == ORIGIN_BACKFILL]
        live.sort(key=lambda i: (TIER_RANK.get(i["tier"], 9), DEPTH_RANK.get(i["depth"], 9), i["seq"]))
        past.sort(key=lambda i: (0, TIER_RANK.get(i["tier"], 9), 0, 0, i["seq"]) if i["depth"] == DEPTH_LINEAGE
                  else (1, -recency(i["bet"]), DEPTH_RANK.get(i["depth"], 9), TIER_RANK.get(i["tier"], 9), i["seq"]))
        return live + past

    def open_batches(self) -> Dict[str, dict]:
        """{batch id: {"submitted": ts, "items": [(key, depth), ...], "origin": live | backfill}} for batches not yet read."""
        with self._lock:
            self._sync()
            return {bid: {"submitted": self._batch_ts.get(bid, ""), "items": list(pairs),
                          "origin": self._batch_origin.get(bid, ORIGIN_LIVE)} for bid, pairs in self._batches.items()}

    def last_submit(self, origin: str = ORIGIN_LIVE) -> Optional[datetime]:
        """When a batch of this origin last went out (each origin keeps its own clock, so a backfill batch never delays a live one)."""
        with self._lock:
            self._sync()
            stamp = self._last_submit.get(origin)
            return parse_iso(stamp) if stamp else None

    def counts(self, hound_id: Optional[str] = None, origin: Optional[str] = None, depth: Optional[str] = None) -> Dict[str, int]:
        with self._lock:
            self._sync()
            out = {"pending": 0, "submitted": 0, "done": 0, "failed": 0}
            for item in self._items.values():
                if ((hound_id is None or item["hound_id"] == hound_id) and (origin is None or item["origin"] == origin)
                        and (depth is None or item["depth"] == depth)):
                    out[item["status"]] = out.get(item["status"], 0) + 1
            return out

    def open_for(self, hound_id: str, depth: str) -> List[dict]:
        """Items of one hound (or lineage) and depth that are waiting or in a batch."""
        with self._lock:
            self._sync()
            return [dict(i) for i in self._items.values()
                    if i["hound_id"] == hound_id and i["depth"] == depth and i["status"] in ("pending", "submitted")]

    def pending_keys(self, hound_id: str) -> set:
        """Bet keys of this hound with a fast review still waiting or in a batch."""
        with self._lock:
            self._sync()
            return {i["bet_key"] for i in self._items.values()
                    if i["hound_id"] == hound_id and i["depth"] == DEPTH_FAST and i["status"] in ("pending", "submitted")}


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------

def recency(bet: Mapping) -> int:
    """A bet's grade time (else its slate day) as one sortable integer, 0 when it has neither: bigger is newer."""
    digits = "".join(ch for ch in str((bet or {}).get("graded_utc") or (bet or {}).get("date") or "") if ch.isdigit())
    return int((digits + "0" * 14)[:14]) if digits else 0


def _digest(row: Mapping) -> dict:
    review, bet = row.get("review") or {}, row.get("bet") or {}
    return {"bet_key": row.get("bet_key"), "depth": row.get("depth"), "hound_id": row.get("hound_id"),
            "created_utc": row.get("created_utc"), "grounded": bool(review.get("grounded")),
            "tags": list(review.get("factor_tags") or ()), "luck": review.get("luck_vs_process"),
            "relevance": review.get("reason_relevance"), "lesson": review.get("lesson"),
            "result": bet.get("result"), "date": bet.get("date"), "game": bet.get("game"),
            "selection": bet.get("selection"), "sources": len(review.get("sources") or ()),
            "lacked": list(review.get("info_hound_lacked") or ())}


class ReviewLedger:
    def __init__(self, path, *, clock: Optional[Callable[[], datetime]] = None):
        self.path = Path(path)
        self._clock = clock or _utcnow
        self._lock = threading.RLock()
        self._reset()

    def _reset(self) -> None:
        self._offset = 0
        self._pos: Dict[Tuple[str, str], Tuple[int, int]] = {}
        self._digests: Dict[Tuple[str, str], dict] = {}
        self._by_hound: Dict[str, List[Tuple[str, str]]] = {}

    def now(self) -> datetime:
        return self._clock()

    def _sync(self) -> None:
        rows, offset, reset = _read_new(self.path, self._offset)
        if reset:
            self._reset()
        for pos, length, row in rows:
            if row.get("kind") != "hindsight_review":
                continue
            ident = (str(row.get("bet_key") or ""), str(row.get("depth") or DEPTH_FAST))
            if not ident[0] or ident in self._pos:
                continue                                     # first write wins
            self._pos[ident] = (pos, length)
            self._digests[ident] = _digest(row)
            self._by_hound.setdefault(str(row.get("hound_id") or ""), []).append(ident)
        self._offset = offset

    def append(self, *, bet: Mapping, depth: str, model: str, review: Mapping, cost_usd: float, web_searches: int,
               batch_id: Optional[str]) -> bool:
        """Write one review. False when this bet and depth already have one (nothing is written)."""
        with self._lock:
            self._sync()
            key = str(bet["bet_key"])
            if (key, depth) in self._pos:
                return False
            _append_line(self.path, {
                "kind": "hindsight_review", "ledger_version": LEDGER_VERSION, "label": LABEL, "bet_key": key,
                "hound_id": bet.get("hound_id"), "depth": depth, "model": model, "created_utc": iso(self.now()),
                "bet": dict(bet), "review": dict(review), "cost_usd": round(float(cost_usd or 0.0), 8),
                "web_searches": int(web_searches or 0), "batch_id": batch_id, "paper_only": True})
            self._sync()
            return True

    def has(self, key: str, depth: str) -> bool:
        with self._lock:
            self._sync()
            return (key, depth) in self._pos

    def reviewed_keys(self) -> set:
        """Every bet key that has a review row of either depth (one read for a whole scan, not one per bet)."""
        with self._lock:
            self._sync()
            return {key for key, _depth in self._pos}

    def _read_row(self, ident: Tuple[str, str]) -> Optional[dict]:
        pos = self._pos.get(ident)
        if pos is None:
            return None
        try:
            with self.path.open("rb") as fh:
                fh.seek(pos[0])
                return json.loads(fh.read(pos[1]).decode("utf-8"))
        except (OSError, ValueError):
            return None

    def get(self, key: str) -> Dict[str, Optional[dict]]:
        """{"fast": row | None, "deep": row | None} for one bet."""
        with self._lock:
            self._sync()
            return {d: self._read_row((key, d)) for d in (DEPTH_FAST, DEPTH_DEEP)}

    def digests_for(self, hound_id: str) -> List[dict]:
        """Small digests of every review row of one hound, newest first."""
        with self._lock:
            self._sync()
            rows = [self._digests[i] for i in self._by_hound.get(hound_id, ())]
        rows.sort(key=lambda d: (d.get("created_utc") or "", d.get("bet_key") or ""), reverse=True)
        return rows

    def rows_for(self, hound_id: str, limit: int = 250) -> List[dict]:
        """The newest review rows of one hound (full rows, deep ones before fast ones for the same bet)."""
        with self._lock:
            self._sync()
            idents = sorted(self._by_hound.get(hound_id, ()), key=lambda i: self._digests[i].get("created_utc") or "", reverse=True)
            out = []
            for ident in idents[:max(0, limit)]:
                row = self._read_row(ident)
                if row is not None:
                    out.append(row)
        return out

    def count(self, hound_id: Optional[str] = None) -> int:
        with self._lock:
            self._sync()
            if hound_id is None:
                return len(self._pos)
            return len(self._by_hound.get(hound_id, ()))


# ---------------------------------------------------------------------------
# the lineage Deep reviews
# ---------------------------------------------------------------------------

class DeepReviewLedger:
    """One row per Deep review of one hound LINEAGE (every version of it together), append-only.

    A new review is a NEW row; the older ones stay, so a lineage's history of reviews is whole (owner ask 2026-10-28: records are kept
    even when they are not easy to find). FIRST WRITE WINS per ``review_key``, so a batch result read twice can never write twice.
    Each row carries the numbers the app counted (``stats``) beside the words, so the review can always be checked against them.
    Reading is incremental like ``ReviewLedger``; only a small meta record per row is held in memory, the full row is read by offset.
    NOTHING HERE HOLDS A PERSON: hound ids and names, counted figures and the review's words."""

    def __init__(self, path, *, clock: Optional[Callable[[], datetime]] = None):
        self.path = Path(path)
        self._clock = clock or _utcnow
        self._lock = threading.RLock()
        self._reset()

    def _reset(self) -> None:
        self._offset = 0
        self._pos: Dict[str, Tuple[int, int]] = {}
        self._meta: Dict[str, dict] = {}
        self._by_lineage: Dict[str, List[str]] = {}

    def now(self) -> datetime:
        return self._clock()

    def _sync(self) -> None:
        rows, offset, reset = _read_new(self.path, self._offset)
        if reset:
            self._reset()
        for pos, length, row in rows:
            key = str(row.get("review_key") or "")
            if row.get("kind") != "deep_review" or not key or key in self._pos:
                continue                                     # first write wins
            self._pos[key] = (pos, length)
            self._meta[key] = {"lineage_key": str(row.get("lineage_key") or ""), "created_utc": row.get("created_utc") or "",
                               "settled": int(row.get("settled") or 0), "seq": int(row.get("seq") or 0)}
            self._by_lineage.setdefault(self._meta[key]["lineage_key"], []).append(key)
        self._offset = offset

    def append(self, *, lineage_key: str, review_key: str, hound_ids: Sequence[str], settled: int, stats: Mapping, review: Mapping,
               model: str, cost_usd: float, batch_id: Optional[str]) -> bool:
        """Write one review. False when this review key already has a row (nothing is written)."""
        with self._lock:
            self._sync()
            if review_key in self._pos:
                return False
            _append_line(self.path, {
                "kind": "deep_review", "ledger_version": DEEP_LEDGER_VERSION, "label": DEEP_LABEL, "lineage_key": lineage_key,
                "review_key": review_key, "seq": len(self._by_lineage.get(lineage_key, ())) + 1, "created_utc": iso(self.now()),
                "model": model, "settled": int(settled), "hound_ids": list(hound_ids), "stats": dict(stats), "review": dict(review),
                "cost_usd": round(float(cost_usd or 0.0), 8), "batch_id": batch_id, "paper_only": True})
            self._sync()
            return True

    def has(self, review_key: str) -> bool:
        with self._lock:
            self._sync()
            return review_key in self._pos

    def _read_row(self, key: str) -> Optional[dict]:
        pos = self._pos.get(key)
        if pos is None:
            return None
        try:
            with self.path.open("rb") as fh:
                fh.seek(pos[0])
                return json.loads(fh.read(pos[1]).decode("utf-8"))
        except (OSError, ValueError):
            return None

    def rows_for(self, lineage_key: str, limit: int = 20) -> List[dict]:
        """The lineage's reviews, newest first (full rows)."""
        with self._lock:
            self._sync()
            keys = sorted(self._by_lineage.get(lineage_key, ()), key=lambda k: (self._meta[k]["created_utc"], self._meta[k]["seq"]),
                          reverse=True)
            out = []
            for key in keys[:max(0, limit)]:
                row = self._read_row(key)
                if row is not None:
                    out.append(row)
        return out

    def latest(self, lineage_key: str) -> Optional[dict]:
        rows = self.rows_for(lineage_key, 1)
        return rows[0] if rows else None

    def last_settled(self, lineage_key: str) -> int:
        """How many settled bets the lineage's newest review covered (0 when it has none): the next one waits for ten more."""
        with self._lock:
            self._sync()
            keys = self._by_lineage.get(lineage_key, ())
            return max((self._meta[k]["settled"] for k in keys), default=0)

    def count(self, lineage_key: Optional[str] = None) -> int:
        with self._lock:
            self._sync()
            return len(self._pos) if lineage_key is None else len(self._by_lineage.get(lineage_key, ()))
