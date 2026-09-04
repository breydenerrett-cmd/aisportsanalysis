"""One-off correction: withdraw the fabricated `edge_bps` published on every
placeholder-provenance decision BEFORE `p_model_provenance` existed (N2/
honesty fix, 2026-09-04 -- see docs/eod/2026-08-31.md's originally-published
`edge_bps=-1431`/`+996`/`+330` etc, and src/ledger/records.py's
`PROBABILITY_PROVENANCE_*` block).

WHY A SEPARATE SCRIPT, NOT A REWRITE
--------------------------------------
`evidence/decisions_v2.jsonl` is an append-only hash chain
(src/ledger/chain.py) -- nothing in this repository edits a row in place,
and doing so here would also be dishonest: the fact that
`TrivialAlwaysHomeSystem` (a fixed p_model=0.52 null control) published an
`edge_bps` on every one of its decisions IS the historical record of the
defect. This script appends one CORRECTION row per affected decision
instead, each naming the decision it corrects (the same 5-tuple
`src.factory.scorecard.decision_key_for` uses to join a DecisionRecord to
its ReviewRecord) and the withdrawal code `edge_withdrawn:
placeholder_probability`. The original row is untouched; the chain still
verifies end to end (`ledger verify`); a reader who wants the honest number
already gets it for free from `DecisionRecord.from_row()`'s legacy
backfill, which nulls `edge_bps` for exactly these rows going forward --
this script is the durable, on-the-record annotation of WHY, appended once.

USAGE
------
    python3 -m scripts.append_edge_withdrawal_corrections [--dry-run]

Idempotent: a decision that already has a correction row appended for it
(matched by `decision_key`) is skipped on a second run.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from src.ledger.bridge import V2_LEDGER_PATH
from src.ledger.chain import HashChainLedger

CORRECTION_KIND = "correction"
CORRECTION_CODE = "edge_withdrawn:placeholder_probability"


def _decision_key(row: dict) -> list:
    # Mirrors src.factory.scorecard.decision_key_for's 5-field shape exactly
    # (event_id, system_id, market_key, selection_id, decision_utc) -- JSON
    # has no tuple type, so this is a list; callers that need a tuple for a
    # dict key convert it themselves.
    return [row.get("event_id"), row.get("system_id"), row.get("market_key"),
            row.get("selection_id"), row.get("decision_utc")]


def find_affected_rows(rows) -> list:
    """Every published row whose `edge_bps` is an artifact of a
    placeholder/no p_model_provenance field at all: pre-fix rows never
    carried the field, and `p_model` is only ever non-None, pre-fix, on
    `TrivialAlwaysHomeSystem`'s fixed 0.52 -- see
    `DecisionRecord.from_row`'s own backfill docstring for the same
    reasoning applied at read time."""
    affected = []
    for row in rows:
        if row.get("kind") in ("genesis", CORRECTION_KIND):
            continue
        if row.get("p_model_provenance") is not None:
            continue  # post-fix row: already carries an honest provenance
        if row.get("edge_bps") is None:
            continue  # nothing to withdraw
        affected.append(row)
    return affected


def already_corrected_keys(rows) -> set:
    corrected = set()
    for row in rows:
        if row.get("kind") == CORRECTION_KIND:
            corrected.add(tuple(row.get("decision_key") or []))
    return corrected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be appended, write nothing")
    args = parser.parse_args()

    ledger = HashChainLedger(V2_LEDGER_PATH)
    rows = ledger.read()
    affected = find_affected_rows(rows)
    already = already_corrected_keys(rows)

    to_append = [r for r in affected
                if tuple(_decision_key(r)) not in already]

    print(f"decisions_v2.jsonl: {len(rows)} rows read, "
         f"{len(affected)} carry a fabricated (placeholder) edge_bps, "
         f"{len(to_append)} not yet corrected")

    if args.dry_run:
        for row in to_append:
            print(f"  would correct: key={_decision_key(row)} "
                 f"edge_bps={row.get('edge_bps')} "
                 f"p_model={row.get('p_model')}")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    for row in to_append:
        payload = {
            "kind": CORRECTION_KIND,
            "correction_code": CORRECTION_CODE,
            "decision_key": _decision_key(row),
            "original_edge_bps": row.get("edge_bps"),
            "original_p_model": row.get("p_model"),
            "p_model_provenance": "placeholder",
            "reason": (
                "this decision predates p_model_provenance (N2/honesty "
                "fix, 2026-09-04); its p_model came from "
                "TrivialAlwaysHomeSystem's fixed 0.52 convention, never a "
                "calibrated estimate, so the published edge_bps is purely "
                "an artifact of diffing a constant against a real price -- "
                "withdrawn, not a measured edge"
            ),
            "corrected_utc": now,
        }
        result = ledger.append(payload)
        print(f"  appended correction for key={payload['decision_key']} "
             f"row_hash={result['row_hash'][:12]}...")

    print(f"appended {len(to_append)} correction row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
