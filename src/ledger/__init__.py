"""Ledger v2: append-only hash-chained records (W10).

Bridge, not migration. `src/pipeline/ledger.py` (evidence/forward_ledger.jsonl)
is untouched by anything in this package -- it is sacred, existing, append-only
evidence and stays exactly as it is. This package adds a second, hash-chained
ledger (`evidence/decisions_v2.jsonl`) whose genesis row records the v1 file's
own hash, so the two are provably linked without either rewriting the other.
"""
