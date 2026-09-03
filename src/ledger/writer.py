"""The v2 ledger writer -- the ONLY place a DecisionRecord is appended.

Product guard (task W10 #4): while `src.report.ranker.ENGINE2 is None`, no
module under `api/` or `web/` may import this module. This is the same
"Ranker Engine 2 stays gated" discipline `tests/test_ranker.py` already
enforces for the ranker page itself, extended to cover the v2 ledger's write
path: nothing in the product can create the appearance of a live decision
feed while there is no engine behind it.

Kept separate from `src.ledger.bridge` (verification, read-only) and
`src.ledger.chain` (the generic primitive) specifically so the import guard
in `tests/test_ranker.py` has one narrow module name to look for.
"""

from __future__ import annotations

from src.ledger.chain import HashChainLedger
from src.ledger.bridge import V2_LEDGER_PATH, ensure_genesis
from src.ledger.records import DecisionRecord


def append_decision(record: DecisionRecord,
                     path: str = str(V2_LEDGER_PATH)) -> dict:
    """Append one DecisionRecord to the v2 chain, hash-linked to whatever
    came before it (including the genesis row, created if this is the first
    write). `prev_hash`/`row_hash` on `record` are ignored -- they are
    computed fresh by the chain, never trusted from the caller."""
    ensure_genesis(v2_path=path)
    ledger = HashChainLedger(path)
    payload = record.to_dict()
    payload.pop("prev_hash", None)
    payload.pop("row_hash", None)
    return ledger.append(payload)
