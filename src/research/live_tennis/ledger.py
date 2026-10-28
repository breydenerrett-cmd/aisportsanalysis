"""The paper ledger and the snapshot store of LIVE_TENNIS_V1. Both append-only and hash-chained.

`PaperLedger` is `evidence/live_tennis_v1.jsonl`: one row per event in a decision point's life, never edited.
Row kinds and what makes each unique:

    genesis      once; carries the first-capture time, the stop date, the constants fingerprint, the prereg sha256
    armed        one per dp_id: a set start seen, with everything needed to resume after a restart
    attempt      one per (dp_id, attempt_no): a decision snapshot that could not decide (a thin board)
    decision     one per dp_id: BET, NO_BET or EXCLUDED with its reason. Every loser is a row.
    reference    one per dp_id: the reference board and M1 / M2 for a bet
    no_reference one per dp_id: a bet with no valid reference, with the counted cause (exclusive with `reference`)
    outcome      one per dp_id: the match and set results and a bet's settled profit (the only place a result is read)

A second row of a kind for the same id is REFUSED (`LedgerError`), so a decision cannot be re-made after the fact.
The hash chain (`src.ledger.chain.HashChainLedger`) makes any edit or deletion detectable by `verify()`.

`SnapshotStore` is the verbatim paid boards of the tracked events (provenance for the ledger's numbers). It is
read through `recent(since)`, which reads only the tail of the file, so a long run never re-reads months of boards.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional

from src.ledger.chain import HashChainLedger
from src.research.live_tennis import board, config


class _TailChain(HashChainLedger):
    """A `HashChainLedger` whose `last_hash` reads only the END of the hot file.

    The stock `last_hash` parses every row of the file on every append, which is fine for a card ledger of a few
    hundred rows and slow for a snapshot store that grows by thousands of rows of ~10 KB. This reads the last row
    only; the bytes written are identical (same canonical row, same chain), so `verify()` and every other reader of
    the stock class work unchanged. Anything unusual (no file, an empty file, a ragged last line) falls back to the
    stock full scan.
    """

    def last_hash(self) -> str:
        try:
            size = self.path.stat().st_size
        except OSError:
            return super().last_hash()
        if size:
            with self.path.open("rb") as fh:
                window = 16384
                while True:
                    start = max(0, size - window)
                    fh.seek(start)
                    pieces = [piece for piece in fh.read().splitlines() if piece.strip()]
                    if start == 0 or len(pieces) >= 2:      # with two pieces the last one cannot be cut at the front
                        break
                    window *= 4
            if pieces:
                try:
                    found = json.loads(pieces[-1].decode("utf-8")).get("row_hash")
                except ValueError:
                    found = None
                if found:
                    return found
        return super().last_hash()

KINDS = ("genesis", "armed", "attempt", "decision", "reference", "no_reference", "outcome")
_UNIQUE_BY = {
    "genesis": lambda r: "genesis",
    "armed": lambda r: r.get("dp_id"),
    "decision": lambda r: r.get("dp_id"),
    "outcome": lambda r: r.get("dp_id"),
    "attempt": lambda r: (r.get("dp_id"), r.get("attempt_no")),
}
# reference and no_reference share one id space: a bet has one or the other, never both.
_REFERENCE_KINDS = ("reference", "no_reference")


class LedgerError(RuntimeError):
    pass


def _now_iso(now: Optional[datetime] = None) -> str:
    return board.iso_utc(now or datetime.now(timezone.utc))


class PaperLedger:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else config.ledger_path()
        self._chain = _TailChain(self.path)
        self._cache_key = None
        self._cache_rows: List[dict] = []

    # -- reading ----------------------------------------------------------

    def rows(self) -> List[dict]:
        """Every row, in order. Cached by (size, mtime) so a one-minute loop does not re-parse an unchanged file."""
        try:
            stat = self.path.stat()
            key = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            self._cache_key, self._cache_rows = None, []
            return []
        if key != self._cache_key:
            self._cache_rows = self._chain.read()
            self._cache_key = key
        return list(self._cache_rows)

    def of_kind(self, kind: str) -> List[dict]:
        return [r for r in self.rows() if r.get("kind") == kind]

    def genesis(self) -> Optional[dict]:
        found = self.of_kind("genesis")
        return found[0] if found else None

    def by_dp(self, kind: str) -> Dict[str, dict]:
        return {r["dp_id"]: r for r in self.of_kind(kind) if r.get("dp_id")}

    def verify(self):
        return self._chain.verify()

    # -- writing ----------------------------------------------------------

    def append(self, kind: str, payload: dict, now: Optional[datetime] = None) -> dict:
        if kind not in KINDS:
            raise LedgerError(f"unknown row kind {kind!r}")
        if "kind" in payload or "recorded_utc" in payload:
            raise LedgerError("payload must not set kind or recorded_utc")
        row_in = {"kind": kind, "recorded_utc": _now_iso(now), "rule_id": config.RULE_ID,
                  "schema": config.SCHEMA_VERSION, **payload}
        existing = self.rows()
        if kind in _UNIQUE_BY:
            token = _UNIQUE_BY[kind](row_in)
            if token is None or (isinstance(token, tuple) and None in token):
                raise LedgerError(f"a {kind} row needs its id fields")
            if any(r.get("kind") == kind and _UNIQUE_BY[kind](r) == token for r in existing):
                raise LedgerError(f"a {kind} row for {token!r} already exists; the ledger is append-only")
        if kind in _REFERENCE_KINDS:
            dp = row_in.get("dp_id")
            if not dp:
                raise LedgerError(f"a {kind} row needs a dp_id")
            if any(r.get("kind") in _REFERENCE_KINDS and r.get("dp_id") == dp for r in existing):
                raise LedgerError(f"{dp!r} already has a reference or a no_reference row")
        written = self._chain.append(row_in)
        try:                                    # keep the read cache current without re-parsing the whole file
            stat = self.path.stat()
            self._cache_rows = existing + [written]
            self._cache_key = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            self._cache_key = None
        return written

    def ensure_genesis(self, *, now: Optional[datetime] = None, prereg_sha256: Optional[str] = None) -> dict:
        """The first row, written once: first-capture time, stop date, constants fingerprint, prereg hash."""
        found = self.genesis()
        if found is not None:
            return found
        return self.append("genesis", {
            "first_capture_utc": _now_iso(now), "stop_date": config.STOP_DATE,
            "fingerprint": config.fingerprint(), "constants": config.constants(),
            "prereg_doc": config.PREREG_DOC, "prereg_sha256": prereg_sha256,
            "registry_id": config.REGISTRY_ID}, now=now)

    def fingerprint_problem(self) -> Optional[str]:
        """None when the code's frozen constants equal the ledger's genesis fingerprint (or there is no genesis yet)."""
        genesis = self.genesis()
        if genesis is None:
            return None
        if genesis.get("fingerprint") != config.fingerprint():
            return ("the frozen constants in config.py differ from the fingerprint written in the ledger's first row; "
                    "a threshold cannot be changed after data exists (docs/PREREG_LIVE_TENNIS.md section 13)")
        return None


class SnapshotStore:
    """Append-only, hash-chained store of paid boards. Rows: {snapshot_id, key, t_req, t_resp, purpose, events, usage}."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else config.snapshots_path()
        self._chain = _TailChain(self.path)

    def append(self, row: dict) -> dict:
        if not row.get("snapshot_id") or not row.get("t_resp"):
            raise LedgerError("a snapshot row needs snapshot_id and t_resp")
        return self._chain.append(row)

    def verify(self):
        return self._chain.verify()

    def recent(self, since: datetime, *, chunk_bytes: int = 1 << 20) -> List[dict]:
        """Snapshot rows whose t_resp is at or after `since`, oldest first, reading only the tail of the file."""
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        window = chunk_bytes
        while True:
            start = max(0, size - window)
            with self.path.open("rb") as fh:
                fh.seek(start)
                blob = fh.read()
            lines = blob.split(b"\n")
            if start > 0:
                lines = lines[1:]                      # the first line may be cut mid-row
            rows = []
            for raw in lines:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw.decode("utf-8")))
                except ValueError:
                    continue
            oldest = board.parse_utc(rows[0].get("t_resp")) if rows else None
            if start == 0 or (oldest is not None and oldest < since):
                break
            window *= 2
        out = []
        for row in rows:
            moment = board.parse_utc(row.get("t_resp"))
            if moment is not None and moment >= since:
                out.append(row)
        return out
