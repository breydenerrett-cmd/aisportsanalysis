"""An append-only, hash-chained JSONL ledger primitive.

WHY A CHAIN AND NOT JUST "APPEND-ONLY BY CONVENTION"
-----------------------------------------------------
`src/pipeline/ledger.py` is append-only by discipline: nothing in this
repository rewrites it, and a test proves the suite never touches it. That is
sufficient for a single trusted writer, but it cannot detect a row edited by
hand, a line deleted with `sed -i`, or a file replaced wholesale outside this
process. A hash chain closes that gap structurally: each row's `row_hash`
covers its own payload AND the previous row's hash, so any edit to any row --
including a deletion -- breaks every hash from that point forward. `verify()`
walks the file and reports the FIRST break, not just "something's wrong".

CANONICAL SERIALISATION
------------------------
The hash is computed over `json.dumps(payload, sort_keys=True,
separators=(",", ":"), ensure_ascii=True)` -- fixed key order, no incidental
whitespace, ASCII-safe -- so the same logical row hashes identically no
matter which process, platform or dict-insertion-order produced it. This is
the same "canonical bytes" discipline `src/board/ids.py` uses for
`selection_id`, applied here to whole rows instead of a field tuple.

GENESIS
-------
Row 0 of any chain has `prev_hash = GENESIS_HASH` (64 zero characters, never a
value a real hash could produce by chance) rather than `None` or `""`, so the
first row hashes through the same code path as every other row and an empty
chain is unambiguously distinct from a one-row chain whose genesis was
tampered with.

WHAT THIS FILE DOES NOT DO
---------------------------
It knows nothing about DecisionRecord, ReviewRecord or any other payload
shape -- that is `src/ledger/records.py`. This module only ever sees
JSON-serialisable dicts, plus the two internal fields it manages
(`prev_hash`, `row_hash`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

GENESIS_HASH = "0" * 64

PREV_HASH_FIELD = "prev_hash"
ROW_HASH_FIELD = "row_hash"


class ChainError(RuntimeError):
    """Raised for structural problems with the chain (bad genesis, etc.)."""


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Deterministic JSON bytes for `payload`, independent of dict order.

    Fixed key order (`sort_keys=True`), no incidental whitespace
    (`separators=(",", ":")`), ASCII-only output -- the same row hashes
    identically regardless of process, platform, or insertion order.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def row_hash(payload: Mapping[str, Any], prev_hash: str) -> str:
    """sha256 of the row's canonical payload chained to `prev_hash`.

    `payload` must NOT itself contain `row_hash` (it is being computed) but
    MAY already contain `prev_hash` -- callers that build the full row dict
    first and hash it afterward are expected to pass the same `prev_hash`
    both places; `append()` below does this for you.
    """
    if ROW_HASH_FIELD in payload:
        raise ChainError(
            f"payload must not already contain {ROW_HASH_FIELD!r} -- "
            "the hash is computed by this function, not supplied to it"
        )
    body = dict(payload)
    body[PREV_HASH_FIELD] = prev_hash
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of walking a chain end to end."""

    ok: bool
    rows_checked: int
    broken_at_line: int | None = None  # 1-indexed line number of the FIRST break
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def _read_lines(path: Path) -> Iterator[tuple[int, dict]]:
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            yield lineno, json.loads(line)


class HashChainLedger:
    """An append-only JSONL file whose rows form a sha256 hash chain.

    Every row is a dict. Two fields are reserved and managed by this class:
    `prev_hash` (the previous row's `row_hash`, or GENESIS_HASH for the first
    row) and `row_hash` (this row's own hash, covering its payload and
    `prev_hash`). Callers supply everything else.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- writing ----------------------------------------------------------

    def last_hash(self) -> str:
        """The `row_hash` of the last row, or GENESIS_HASH if the file is
        empty or does not exist yet."""
        if not self.path.exists():
            return GENESIS_HASH
        last = GENESIS_HASH
        for _, row in _read_lines(self.path):
            last = row.get(ROW_HASH_FIELD, last)
        return last

    def append(self, payload: Mapping[str, Any]) -> dict:
        """Append one row, chaining it to the current last hash.

        `payload` must not already carry `prev_hash` or `row_hash` -- those
        are computed here so a caller can never accidentally forge a link.
        Returns the full row written (payload + prev_hash + row_hash).
        """
        for reserved in (PREV_HASH_FIELD, ROW_HASH_FIELD):
            if reserved in payload:
                raise ChainError(
                    f"payload must not set {reserved!r} directly -- it is "
                    "computed by HashChainLedger.append()"
                )
        prev = self.last_hash()
        row = dict(payload)
        row[PREV_HASH_FIELD] = prev
        row[ROW_HASH_FIELD] = row_hash(payload, prev)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")
        return row

    # -- reading ------------------------------------------------------------

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [row for _, row in _read_lines(self.path)]

    def __iter__(self) -> Iterator[dict]:
        return iter(self.read())

    # -- verification -------------------------------------------------------

    def verify(self) -> VerifyResult:
        """Walk the chain and report the FIRST break, if any.

        A break is: a row missing `prev_hash`/`row_hash`; a `prev_hash` that
        does not match the previous row's `row_hash` (or GENESIS_HASH for the
        first row); or a `row_hash` that does not match the recomputed hash
        of the row's own payload. Verification stops at the first failure so
        the report always names the earliest tampering, not the last.
        """
        if not self.path.exists():
            return VerifyResult(ok=True, rows_checked=0)

        expected_prev = GENESIS_HASH
        checked = 0
        for lineno, row in _read_lines(self.path):
            checked += 1
            if PREV_HASH_FIELD not in row or ROW_HASH_FIELD not in row:
                return VerifyResult(
                    ok=False, rows_checked=checked, broken_at_line=lineno,
                    reason=f"line {lineno} is missing {PREV_HASH_FIELD!r} "
                           f"or {ROW_HASH_FIELD!r}",
                )
            actual_prev = row[PREV_HASH_FIELD]
            if actual_prev != expected_prev:
                return VerifyResult(
                    ok=False, rows_checked=checked, broken_at_line=lineno,
                    reason=(
                        f"line {lineno}: prev_hash={actual_prev!r} does not "
                        f"match the preceding row's row_hash={expected_prev!r}"
                    ),
                )
            claimed_hash = row[ROW_HASH_FIELD]
            payload = {k: v for k, v in row.items() if k != ROW_HASH_FIELD}
            recomputed = row_hash(
                {k: v for k, v in payload.items() if k != PREV_HASH_FIELD},
                actual_prev,
            )
            if recomputed != claimed_hash:
                return VerifyResult(
                    ok=False, rows_checked=checked, broken_at_line=lineno,
                    reason=(
                        f"line {lineno}: row_hash={claimed_hash!r} does not "
                        f"match the recomputed hash {recomputed!r} of its "
                        "own payload -- this row was edited after being "
                        "written"
                    ),
                )
            expected_prev = claimed_hash

        return VerifyResult(ok=True, rows_checked=checked)


def file_sha256(path: str | Path) -> str | None:
    """sha256 of a file's exact bytes, or None if it does not exist.

    Used to record (and later re-check) that an external, non-chained file --
    e.g. `evidence/forward_ledger.jsonl` -- has not been modified, without
    that file needing to know anything about hash chains itself.
    """
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
