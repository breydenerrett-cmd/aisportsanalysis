"""The v2 ledger writer -- the ONLY place a DecisionRecord, ReviewRecord or
Scorecard is appended.

Product guard (task W10 #4): while `src.report.ranker.ENGINE2 is None`, no
module under `api/` or `web/` may import this module. This is the same
"Ranker Engine 2 stays gated" discipline `tests/test_ranker.py` already
enforces for the ranker page itself, extended to cover the v2 ledger's write
path: nothing in the product can create the appearance of a live decision
feed while there is no engine behind it.

Kept separate from `src.ledger.bridge` (verification, read-only) and
`src.ledger.chain` (the generic primitive) specifically so the import guard
in `tests/test_ranker.py` has one narrow module name to look for.

`REVIEW_LEDGER_PATH` and `SCORECARD_LEDGER_PATH` are independent chains, not
bridged to the v1 ledger the way `V2_LEDGER_PATH` is (that bridge is a
decisions-specific concept -- see src/ledger/bridge.py) -- each simply
starts its own hash chain from GENESIS_HASH on first append.
"""

from __future__ import annotations

from src.ledger.chain import HashChainLedger
from src.ledger.bridge import V2_LEDGER_PATH, ensure_genesis
from src.ledger.records import DecisionRecord, ReviewRecord, Scorecard
from src.paths import evidence_path

REVIEW_LEDGER_PATH = evidence_path("reviews_v2.jsonl")
SCORECARD_LEDGER_PATH = evidence_path("scorecards_v2.jsonl")


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


def append_review(record: ReviewRecord,
                   path: str = str(REVIEW_LEDGER_PATH)) -> dict:
    """Append one ReviewRecord to its own hash chain. `decision_key` (a
    tuple) is the join back to the DecisionRecord it reviews -- see
    `src.factory.scorecard.decision_key_for`."""
    ledger = HashChainLedger(path)
    return ledger.append(record.to_dict())


def append_scorecard(record: Scorecard,
                      path: str = str(SCORECARD_LEDGER_PATH)) -> dict:
    """Append one Scorecard row to its own hash chain -- one row per
    (system_id, window) is the convention a caller (e.g. `engine settle`)
    is expected to follow; this function does not itself deduplicate."""
    ledger = HashChainLedger(path)
    return ledger.append(record.to_dict())
