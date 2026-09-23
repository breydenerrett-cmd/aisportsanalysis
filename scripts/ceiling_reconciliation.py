#!/usr/bin/env python3
"""Reconcile published V2 cards against the registered ten-entry ceiling.

Reports, per publish snapshot: entries actually listed, entries the
registered cap allows, and -- had the cap been applied at admission -- which
entries would have been refused a slot instead.

Reads only. Deletes nothing, truncates nothing, publishes nothing. The
correction it demonstrates (`src.appstate.ceiling_admission`) is not wired
into the publisher and is not approved for one.

    python scripts/ceiling_reconciliation.py --date 2026-09-22
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import best_bets_card  # noqa: E402
from src.appstate import ceiling_admission  # noqa: E402
from src.pipeline import store_archive  # noqa: E402

CARD_STORE = "evidence/cards_v2.jsonl"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True)
    ap.add_argument("--card-store", default=CARD_STORE)
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output")
    args = ap.parse_args(argv)

    ceiling = best_bets_card.V2.ceiling

    snapshots = []
    for line in store_archive.iter_lines(args.card_store):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("date") != args.date:
            continue
        entries = list(row.get("all_bets") or ())
        snapshots.append({
            "published_utc": row.get("published_utc"),
            "entries": entries,
            "n_picks": row.get("n_picks"),
            "n_fills": row.get("n_fills"),
            "locked": sum(1 for e in entries if e.get("locked")),
            "stored_ceiling": ((row.get("params") or {}).get("ceiling")),
        })
    snapshots.sort(key=lambda s: s["published_utc"] or "")

    if not snapshots:
        print(f"no V2 publish rows for {args.date} in {args.card_store}")
        return 0

    walked = ceiling_admission.walk(snapshots, ceiling=ceiling)

    findings = []
    for snap, row in zip(snapshots, walked):
        if row["over_ceiling_actual"] > 0:
            findings.append((
                "ESCALATE",
                f"{row['published_utc']}: listed {row['listed_actual']} "
                f"entries against a registered ceiling of {ceiling} "
                f"({row['over_ceiling_actual']} over); "
                f"{snap['locked']} of them were locked and therefore exempt "
                f"from card_ledger._apply_ceiling_v2"))
        if row["over_ceiling_under_admission"] > 0:
            findings.append((
                "ESCALATE",
                f"{row['published_utc']}: admission-time ceiling STILL "
                f"exceeded -- this would be a bug in the proposed fix"))

    if args.json:
        print(json.dumps({
            "date": args.date,
            "ceiling": ceiling,
            "snapshots": walked,
            "findings": [{"severity": s, "message": m} for s, m in findings],
        }, indent=2))
    else:
        print(f"date {args.date}   registered ceiling {ceiling}   "
              f"stored params ceiling "
              f"{snapshots[0]['stored_ceiling']}")
        print(f"{'published (UTC)':<34}{'picks':>6}{'fills':>6}"
              f"{'locked':>7}{'listed':>7}{'allowed':>8}{'refused':>8}")
        for snap, row in zip(snapshots, walked):
            flag = "  <<< OVER" if row["over_ceiling_actual"] else ""
            print(f"{str(row['published_utc']):<34}"
                  f"{snap['n_picks']:>6}{snap['n_fills']:>6}"
                  f"{snap['locked']:>7}{row['listed_actual']:>7}"
                  f"{row['listed_under_admission']:>8}"
                  f"{row['refused_at_admission']:>8}{flag}")
        print()
        for severity, message in findings:
            print(f"{severity}: {message}")
        if not findings:
            print("OK: no published card exceeded the registered ceiling.")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
