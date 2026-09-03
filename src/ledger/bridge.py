"""The v1/v2 ledger bridge: `python3 -m src.cli ledger verify`.

Bridge, not migration (task W10 #3). `evidence/forward_ledger.jsonl` (v1) is
never rewritten, never re-chained, never touched by anything here -- this
module only READS it to compute a sha256 and compares that hash against the
one recorded in the v2 chain's genesis row. `evidence/decisions_v2.jsonl` (v2)
starts empty; the FIRST call that needs a chain creates it with a genesis row
whose payload names the v1 file and its hash at that moment, so the two
ledgers are provably linked without either one knowing how to write the
other's format.
"""

from __future__ import annotations

from pathlib import Path

from src.ledger.chain import GENESIS_HASH, HashChainLedger, VerifyResult
from src.paths import evidence_path

V1_LEDGER_PATH = evidence_path("forward_ledger.jsonl")
V2_LEDGER_PATH = evidence_path("decisions_v2.jsonl")

GENESIS_KIND = "genesis"


def _v1_hash() -> str | None:
    from src.ledger.chain import file_sha256
    return file_sha256(V1_LEDGER_PATH)


def ensure_genesis(v2_path: str | Path = V2_LEDGER_PATH,
                    v1_path: str | Path = V1_LEDGER_PATH) -> dict:
    """Create the v2 chain's genesis row if the chain does not exist yet.

    The genesis row records the v1 file's path and sha256 AT THIS MOMENT --
    proof that v2 started from a known, specific state of v1, without ever
    reading v1's content into the v2 chain or rewriting a byte of it. If the
    chain already has rows, this is a no-op and returns the existing genesis.
    """
    from src.ledger.chain import file_sha256

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


def verify() -> dict:
    """Verify both ledgers and return a report; used by `ledger verify`.

    Checks, in order:
      1. v1's current sha256 still matches the hash recorded in v2's genesis
         row (if a genesis row exists) -- proof v1 has not been rewritten
         since v2 was anchored to it.
      2. v2's own hash chain is intact end to end.

    Never writes to v1. Creates v2's genesis row via `ensure_genesis()` if
    the v2 chain does not exist yet, so `verify()` is safe to run as the very
    first command against a fresh checkout.
    """
    genesis = ensure_genesis()
    current_v1_hash = _v1_hash()
    recorded_v1_hash = genesis.get("v1_ledger_sha256")

    v1_untouched = current_v1_hash == recorded_v1_hash
    v2_result: VerifyResult = HashChainLedger(V2_LEDGER_PATH).verify()

    return {
        "v1_path": str(V1_LEDGER_PATH),
        "v1_untouched": v1_untouched,
        "v1_sha256_recorded": recorded_v1_hash,
        "v1_sha256_current": current_v1_hash,
        "v2_path": str(V2_LEDGER_PATH),
        "v2_chain_ok": v2_result.ok,
        "v2_rows_checked": v2_result.rows_checked,
        "v2_broken_at_line": v2_result.broken_at_line,
        "v2_reason": v2_result.reason,
        "ok": v1_untouched and v2_result.ok,
    }
