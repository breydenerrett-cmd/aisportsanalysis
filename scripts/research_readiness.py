#!/usr/bin/env python3
"""How close is the forward evidence to supporting the tests we cannot run yet?

WHY THIS EXISTS
----------------
Two of this project's most valuable measurements are dormant, and for the
same reason: not enough graded evidence. All 85 scorecards read
`battery_verdict: NOT_RUN`, and docs/PREREG_CLV_FEATURE_LEAD.md sits at
PENDING.

The tempting move on 2026-09-10 was to wire the falsification battery into
settlement and call the biggest dormant asset "turned on". Checking first
showed why that would have been damage rather than progress: `battery.run`
needs MIN_N graded selections PER CHECK, and the largest forward-test system
had 21. Every check would have SKIPPED, the battery would have reported
`survives=True` -- which src/research/battery.py's own docstring calls
vacuous -- and that verdict would have been written into a hash-chained,
append-only scorecard ledger. `NOT_RUN` is honest. A vacuous `survives`
reads as evidence and cannot be taken back.

So this reports the DISTANCE instead, every night, and escalates on the day
a system first crosses the line -- which is the day wiring the battery stops
being a mistake. The alternative is somebody re-checking by hand, forever,
and the whole reason this repo now has a reachability audit is that nobody
ever does.

Read-only. Writes nothing, spends no credits.
"""

from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _rows(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return out


def graded_by_system():
    """Graded selections per system, in the shape src/research/battery.py
    documents: date, won, implied.

    Joined the same way a real caller would have to -- settlement carries
    the outcome, the wager carries the selection, and only the DECISION
    carries `consensus_fair`. The battery's effect is mean(won - implied),
    so a row without the consensus is not a gradeable row at all.
    """
    wagers = {w["bet_id"]: w
              for w in _rows(REPO / "evidence" / "paper_wagers_v2.jsonl")
              if w.get("bet_id")}
    consensus = {}
    for d in _rows(REPO / "evidence" / "decisions_v2.jsonl"):
        if d.get("consensus_fair") is None:
            continue
        consensus[(d.get("event_id"), d.get("market_key"),
                   d.get("selection_id"), d.get("system_id"))] = \
            d["consensus_fair"]

    out = defaultdict(list)
    for path in glob.glob(str(REPO / "data" / "paper_accounts" / "*.jsonl")):
        for s in _rows(path):
            if s.get("outcome") not in ("win", "loss"):
                continue
            wager = wagers.get(s.get("bet_id"))
            if not wager:
                continue
            system_id = s.get("system_id") or wager.get("system_id")
            implied = consensus.get((wager.get("event_id"),
                                     wager.get("market_key"),
                                     wager.get("selection_id"), system_id))
            if implied is None:
                continue
            out[system_id].append({
                "date": (wager.get("date") or "")[:10],
                "won": s["outcome"] == "win",
                "implied": float(implied),
            })
    return out


def main() -> int:
    from src.report import engine_bridge
    from src.research import battery

    by_system = graded_by_system()
    forward = {s: v for s, v in by_system.items()
               if engine_bridge.system_class(s) == engine_bridge.FORWARD_TEST}

    ranked = sorted(((len(v), s) for s, v in forward.items()), reverse=True)
    ready = [s for n, s in ranked if n >= battery.MIN_N]

    print(f"research readiness -- {len(forward)} forward-test system(s) with "
          f"graded selections")
    print(f"  falsification battery needs {battery.MIN_N} graded selections "
          f"per system (src/research/battery.py MIN_N)")
    for n, system_id in ranked[:5]:
        short = f"{n}/{battery.MIN_N}"
        gap = battery.MIN_N - n
        note = "READY" if gap <= 0 else f"{gap} more"
        print(f"    {system_id}  {short:>7}  {note}")

    if ready:
        print(f"\nESCALATE: {len(ready)} forward-test system(s) now have "
              f"{battery.MIN_N}+ graded selections, so the falsification "
              f"battery can finally run on real evidence instead of "
              f"skipping every check. Wire src/research/battery.run into "
              f"src/engine/settle_slate.py's build_scorecard call "
              f"(research={{'battery': ...}}) -- until then every scorecard "
              f"keeps reporting NOT_RUN, which is honest but is no longer "
              f"the best available answer.")
        return 0

    best = ranked[0][0] if ranked else 0
    print(f"\n  VERDICT: NOT YET. Best system has {best}; the battery would "
          f"skip every check and report a vacuous 'survives'. NOT_RUN stays "
          f"the honest scorecard verdict.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
