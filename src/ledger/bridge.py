"""The v1/v2 ledger bridge: `python3 -m src.cli ledger verify`.

Bridge, not migration (task W10 #3). `evidence/forward_ledger.jsonl` (v1) is
never rewritten, never re-chained, never touched by anything here -- this
module only READS it to compute a sha256 and compares that hash against the
one recorded in the v2 chain's genesis row. `evidence/decisions_v2.jsonl` (v2)
starts empty; the FIRST call that needs a chain creates it with a genesis row
whose payload names the v1 file and its hash at that moment, so the two
ledgers are provably linked without either one knowing how to write the
other's format.

GROWTH IS NOT TAMPERING
------------------------
v1 is append-only in practice (the forward capture loop keeps writing to it
long after v2 was anchored), so its current whole-file sha256 almost never
equals the one recorded at genesis -- that mismatch alone does NOT mean the
recorded region was touched. `_classify_v1()` below distinguishes the two
by walking the CURRENT file once, hashing it incrementally line by line, and
checking the running digest against the recorded hash after every completed
line: if the recorded hash reappears as a genuine line-boundary prefix of
today's file, every byte anchored at genesis is still there unchanged and
everything after it is pure append (`"grew"`, not a failure). Only when the
recorded hash matches NO prefix of the current file -- an edit inside the
anchored region, a deleted/reordered row, truncation, or a wholesale
replacement -- is this `"tampered"`. This needs no extra bookkeeping at
genesis time (no stored row count or byte length): a genesis row written
before this fix, carrying nothing but a whole-file hash, still classifies
correctly, since the prefix walk only ever needs that one hash to search for.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.ledger.chain import GENESIS_HASH, HashChainLedger, VerifyResult, file_sha256
from src.paths import evidence_path

V1_LEDGER_PATH = evidence_path("forward_ledger.jsonl")
V2_LEDGER_PATH = evidence_path("decisions_v2.jsonl")

GENESIS_KIND = "genesis"

# `_classify_v1`'s three possible outcomes -- exported so callers (the CLI)
# never have to spell the strings out themselves.
V1_UNTOUCHED = "untouched"
V1_GREW = "grew"
V1_TAMPERED = "tampered"


def _classify_v1(path: str | Path, recorded_hash: str | None) -> dict:
    """Classify how `path`'s CURRENT bytes relate to `recorded_hash` (the
    whole-file sha256 recorded in the v2 genesis row at anchor time).

    Returns `{"status", "sha256_current", "rows_recorded", "rows_current"}`.
    `status` is one of `V1_UNTOUCHED` (current whole-file hash equals
    `recorded_hash` exactly -- not a single byte appended since genesis),
    `V1_GREW` (`recorded_hash` matches a strictly shorter line-boundary
    prefix of the current file -- every anchored byte is intact, only whole
    new lines were appended after it), or `V1_TAMPERED` (`recorded_hash`
    matches neither the whole file nor any prefix of it: something inside
    the anchored region changed, rows were removed or reordered, or the file
    shrank/was replaced). `rows_recorded` is the line count at the matched
    prefix (0 when `recorded_hash` is None, i.e. genesis anchored to a v1
    file that did not exist yet); `rows_current` is the file's line count
    now. Both are None only when `status == V1_TAMPERED`, since no matching
    prefix boundary exists to count rows at.
    """
    p = Path(path)
    if recorded_hash is None:
        # Genesis anchored before v1 existed (or was empty) -- there is
        # nothing recorded that could have been tampered with; any content
        # now is new growth, not a violation.
        if not p.exists():
            return {"status": V1_UNTOUCHED, "sha256_current": None,
                    "rows_recorded": 0, "rows_current": 0}
        with p.open("rb") as fh:
            rows_current = sum(1 for _ in fh)
        return {"status": V1_UNTOUCHED if rows_current == 0 else V1_GREW,
                "sha256_current": file_sha256(p), "rows_recorded": 0,
                "rows_current": rows_current}

    if not p.exists():
        # Recorded something at genesis, but the file is gone now -- the
        # only honest read of "the anchored bytes vanished" is tampering.
        return {"status": V1_TAMPERED, "sha256_current": None,
                "rows_recorded": None, "rows_current": 0}

    h = hashlib.sha256()
    matched_rows = 0 if h.hexdigest() == recorded_hash else None
    rows_current = 0
    with p.open("rb") as fh:
        for line in fh:
            h.update(line)
            rows_current += 1
            if matched_rows is None and h.hexdigest() == recorded_hash:
                matched_rows = rows_current
    sha256_current = h.hexdigest()

    if matched_rows is None:
        return {"status": V1_TAMPERED, "sha256_current": sha256_current,
                "rows_recorded": None, "rows_current": rows_current}
    status = V1_UNTOUCHED if matched_rows == rows_current else V1_GREW
    return {"status": status, "sha256_current": sha256_current,
            "rows_recorded": matched_rows, "rows_current": rows_current}


def ensure_genesis(v2_path: str | Path = V2_LEDGER_PATH,
                    v1_path: str | Path = V1_LEDGER_PATH) -> dict:
    """Create the v2 chain's genesis row if the chain does not exist yet.

    The genesis row records the v1 file's path and sha256 AT THIS MOMENT --
    proof that v2 started from a known, specific state of v1, without ever
    reading v1's content into the v2 chain or rewriting a byte of it. If the
    chain already has rows, this is a no-op and returns the existing genesis.
    """
    ledger = HashChainLedger(v2_path)
    existing = ledger.read()
    if existing:
        return existing[0]

    v1_hash = file_sha256(v1_path)
    return ledger.append({
        "kind": GENESIS_KIND,
        "v1_ledger_path": str(Path(v1_path)),
        "v1_ledger_sha256": v1_hash,
    })


def verify(v1_path: str | Path | None = None,
           v2_path: str | Path | None = None) -> dict:
    """Verify both ledgers and return a report; used by `ledger verify`.

    Checks, in order:
      1. v1's current bytes are classified against the hash recorded in v2's
         genesis row (`_classify_v1`): `V1_UNTOUCHED` or `V1_GREW` both pass
         -- v1 growing by pure append since it was anchored is expected,
         normal operation, never a failure; only `V1_TAMPERED` (the recorded
         region itself changed) fails this check.
      2. v2's own hash chain is intact end to end.

    Never writes to v1. Creates v2's genesis row via `ensure_genesis()` if
    the v2 chain does not exist yet, so `verify()` is safe to run as the very
    first command against a fresh checkout. `v1_path`/`v2_path` override the
    real stores -- tests only; production always calls `verify()` bare, which
    resolves the module-level constants at CALL time (not the stale defaults
    a plain keyword-argument binding would capture at import time), so a
    monkeypatch of `bridge.V1_LEDGER_PATH`/`bridge.V2_LEDGER_PATH` still
    takes effect.
    """
    v1_path = V1_LEDGER_PATH if v1_path is None else Path(v1_path)
    v2_path = V2_LEDGER_PATH if v2_path is None else Path(v2_path)

    genesis = ensure_genesis(v2_path, v1_path)
    recorded_v1_hash = genesis.get("v1_ledger_sha256")
    v1 = _classify_v1(v1_path, recorded_v1_hash)

    v2_result: VerifyResult = HashChainLedger(v2_path).verify()

    return {
        "v1_path": str(v1_path),
        "v1_status": v1["status"],
        "v1_untouched": v1["status"] != V1_TAMPERED,  # kept: "did v1 pass"
        "v1_rows_recorded": v1["rows_recorded"],
        "v1_rows_current": v1["rows_current"],
        "v1_sha256_recorded": recorded_v1_hash,
        "v1_sha256_current": v1["sha256_current"],
        "v2_path": str(v2_path),
        "v2_chain_ok": v2_result.ok,
        "v2_rows_checked": v2_result.rows_checked,
        "v2_broken_at_line": v2_result.broken_at_line,
        "v2_reason": v2_result.reason,
        "ok": v1["status"] != V1_TAMPERED and v2_result.ok,
    }
