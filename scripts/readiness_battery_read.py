#!/usr/bin/env python3
"""Run the falsification battery for one READY forward-test system and record
what it says, without writing to the hash-chained scorecard ledger.

WHY THIS EXISTS (2026-10-17)
-----------------------------
`scripts/research_readiness.py` escalated nightly that one forward-test
system had 30+ graded selections while its latest scorecard row still read
`battery_verdict: NOT_RUN`. The escalation assumes the settle wiring should
have written a real verdict for it. Reading both sides showed the two
counts are not the same count:

- research_readiness counts paper-account settlements joined to a decision's
  `consensus_fair` (32 rows for system 606be696ff199952);
- settle_slate's `_battery_research_for` counts decision/REVIEW pairs that
  settled WIN or LOSS (27 rows), and a review is what the settle path
  requires. Five 2026-08-31 launch-day wagers were graded in the paper
  account and never reviewed.

So the settle path was right to write NOT_RUN (27 < `battery.MIN_N` = 30),
and the escalation is firing on a premise the wiring does not share. This
script runs `battery.run` -- the battery's own entry point, unmodified -- on
the readiness rows (the rows the escalation counted), builds the scorecard
the existing builder would build from that result, and records both in a file.

IT DOES NOT APPEND TO `evidence/scorecards_v2.jsonl`. Three reasons, each
sufficient:
1. That ledger is a hash chain the hourly loop appends to; a row appended
   from a branch forks it on merge.
2. `run_settle` is its only writer, and it would not have written this row:
   it joined 27, not 32. A row from a different join is not that pipeline's
   output.
3. The result is vacuous (see `fatal_rules_judged`), and a vacuous PASS in an
   append-only ledger reads as evidence and cannot be taken back.

Usage:
    python3 scripts/readiness_battery_read.py --system ID --as-of DATE [--write]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

OUT_DIR = os.path.join(REPO, "data", "research", "battery_reads")


def judged_fatal_rules(result):
    """Which of the battery's five pre-registered FATAL rules had enough
    data to be judged at all. A skipped check, or one whose effect is null
    because the slice fell under the floor, judged nothing."""
    from src.research import battery

    judged, unjudged = [], {}
    report = result.get("report") or {}
    for name in battery.FATAL_CHECKS:
        entry = report.get(name) or {}
        if "skipped" in entry:
            unjudged[name] = entry["skipped"]
        elif name == "extreme_removal" and entry.get("effect") is None:
            unjudged[name] = ("remaining sample under the "
                              f"{battery.MIN_N}-row floor, effect not read")
        else:
            judged.append(name)
    return judged, unjudged


def perform(system_id, as_of):
    import research_readiness
    from src.engine import settle_slate
    from src.factory.scorecard import build_scorecard, decision_key_for
    from src.research import battery

    readiness_rows = [r for r in research_readiness.graded_by_system()
                      .get(system_id, ()) if r["date"] <= as_of]

    decisions = tuple(d for d in settle_slate.load_decisions()
                      if d.system_id == system_id)
    reviews = tuple(r for r in settle_slate.load_reviews()
                    if len(r.decision_key) > 1
                    and r.decision_key[1] == system_id)
    settle_rows = settle_slate._battery_rows_for_system(
        decisions, reviews, as_of)

    result = battery.run(readiness_rows)
    judged, unjudged = judged_fatal_rules(result)

    bets = settle_slate._reconstruct_settled_bets(
        system_id, None, as_of_day=as_of)
    scorecard, absent = build_scorecard(
        system_id=system_id, world="real", window=as_of,
        point_class="LATE_BOARD", market_key="h2h", bets=bets,
        decisions=decisions, reviews=reviews,
        research={"battery": result})

    return {
        "system_id": system_id,
        "as_of": as_of,
        "battery_entry_point": "src.research.battery.run",
        "battery_min_n": battery.MIN_N,
        "rows_given_to_battery": len(readiness_rows),
        "rows_source": "scripts/research_readiness.py graded_by_system(): "
                       "paper-account WIN/LOSS settlements joined to the "
                       "decision's consensus_fair",
        "rows_the_settle_path_would_give": len(settle_rows),
        "settle_path_source": "src/engine/settle_slate.py "
                              "_battery_rows_for_system(): decision/review "
                              "pairs settled WIN or LOSS",
        "settle_path_reaches_the_floor": len(settle_rows) >= battery.MIN_N,
        "battery_result": result,
        "fatal_rules_judged": judged,
        "fatal_rules_unjudged": unjudged,
        "vacuous": not judged,
        "scorecard": scorecard.to_dict(),
        "scorecard_absent_components": [str(a) for a in absent],
        "appended_to_scorecard_ledger": False,
        "not_appended_because": "the hourly loop owns the hash chain "
                                "evidence/scorecards_v2.jsonl and run_settle "
                                "is its only writer; this row came from a "
                                "different join than run_settle's, and "
                                "carries no judged fatal rule",
    }


def write(record):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(
        OUT_DIR, f"{record['system_id']}_{record['as_of']}.json")
    if os.path.exists(path):
        raise FileExistsError(f"{path} exists; a read is not overwritten")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(record, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    record = perform(args.system, args.as_of)
    if args.write:
        print("wrote " + os.path.relpath(write(record), REPO))
    else:
        print(json.dumps(record, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
