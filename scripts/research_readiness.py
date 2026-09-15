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

2026-09-15 UPDATE -- THE WIRING NOW EXISTS
-------------------------------------------
`src/engine/settle_slate.py`'s `run_settle` now computes a real battery
verdict (via `_battery_research_for`) for every system with >= `battery.
MIN_N` point-in-time graded WIN/LOSS selections, and passes it to
`build_scorecard`; below the floor a system still gets `NOT_RUN` honestly,
and a battery that raises is translated into an `ERROR`-shaped verdict
rather than aborting settlement. So "ready" (30+ graded selections) no
longer implies "still NOT_RUN forever" -- it implies "should have a real
verdict on its books as of the most recent daily settle". This script's job
changed with it: escalating unconditionally on readiness would now be
printing a stale claim every night, forever, even after the fix landed.
Ready is no longer the finish line; a READY system's own LATEST scorecard
row reporting anything other than `NOT_RUN` is. So this reads that row
(`evidence/scorecards_v2.jsonl`, the same ledger `src.ledger.writer.
SCORECARD_LEDGER_PATH` names and `run_settle` appends to) and escalates only
on a READY system whose latest row is still `NOT_RUN` -- or has no row at
all -- which is now the behavioural question ("did the wiring actually run
for this system yet"), not the data-readiness question alone.

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

from src.ledger.writer import SCORECARD_LEDGER_PATH  # noqa: E402  (needs REPO on sys.path first)

# The verdict a scorecard row carries before the falsification battery has
# ever run for that (system, window) -- see src/factory/scorecard.py's
# `falsification_from_battery` (battery absent or `ran=False` both read as
# this string, never as a fabricated PASS).
NOT_RUN = "NOT_RUN"


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


def graded_by_system(*, wagers_path=None, decisions_path=None,
                      paper_accounts_glob=None):
    """Graded selections per system, in the shape src/research/battery.py
    documents: date, won, implied.

    Joined the same way a real caller would have to -- settlement carries
    the outcome, the wager carries the selection, and only the DECISION
    carries `consensus_fair`. The battery's effect is mean(won - implied),
    so a row without the consensus is not a gradeable row at all.

    The three source paths default to the real evidence/data stores but are
    keyword-overridable -- tests exercise the counting logic through
    `compute_readiness` directly instead (with a fabricated `forward` dict),
    so this seam mostly exists so nothing here silently resists redirection
    the way the pre-2026-09-15 version did.
    """
    wagers_path = wagers_path or (REPO / "evidence" / "paper_wagers_v2.jsonl")
    decisions_path = decisions_path or (REPO / "evidence" / "decisions_v2.jsonl")
    paper_accounts_glob = paper_accounts_glob or str(
        REPO / "data" / "paper_accounts" / "*.jsonl")

    wagers = {w["bet_id"]: w for w in _rows(wagers_path) if w.get("bet_id")}
    consensus = {}
    for d in _rows(decisions_path):
        if d.get("consensus_fair") is None:
            continue
        consensus[(d.get("event_id"), d.get("market_key"),
                   d.get("selection_id"), d.get("system_id"))] = \
            d["consensus_fair"]

    out = defaultdict(list)
    for path in glob.glob(paper_accounts_glob):
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


def latest_battery_verdicts(system_ids, scorecard_path=SCORECARD_LEDGER_PATH):
    """`{system_id: (window, battery_verdict)}` for the LATEST scorecard row
    of each id in `system_ids` -- `None` for a system with no row at all.

    "Latest" is the row with the greatest `window` (an ISO `date_str`, so
    lexicographic order is chronological order -- the same field `run_settle`
    stamps via `build_scorecard(..., window=date_str, ...)`); ties (a
    ledger that was appended to twice for the same window -- `append_scorecard`
    does not itself deduplicate, per its own docstring) resolve to whichever
    copy appears LAST in the file, i.e. append order, which is the only
    ordering this append-only ledger actually guarantees.

    Never raises on a missing or malformed ledger: a missing file, an
    unreadable one, or individual lines that are not valid JSON all degrade
    to "that row contributes nothing", never a traceback -- a scorecard
    ledger is exactly the kind of append-only evidence this project would
    rather under-report than crash a nightly readiness check over.
    """
    system_ids = set(system_ids)
    latest: dict = {}
    try:
        with open(scorecard_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = row.get("system_id")
                if sid not in system_ids:
                    continue
                window = row.get("window")
                if window is None:
                    continue
                current = latest.get(sid)
                if current is None or window >= current[0]:
                    latest[sid] = (window, row.get("battery_verdict"))
    except OSError:
        pass
    return latest


def compute_readiness(forward: dict, scorecard_path=SCORECARD_LEDGER_PATH,
                       *, min_n=None):
    """The whole readiness/escalation judgement, as data -- no I/O beyond
    reading `scorecard_path` (itself never fatal, see
    `latest_battery_verdicts`), no printing. `forward` is
    `{system_id: [graded_row, ...]}`, already restricted to forward-test
    systems -- exactly what `main()` builds from `graded_by_system()` +
    `engine_bridge.system_class`, and exactly what a test can fabricate
    directly (a list of `min_n` dummy rows per system) without touching
    evidence/ at all.

    Returns a dict: `ranked` (every system, most graded first),
    `ready` (system_ids with >= min_n), `ledger_existed` (bool),
    `latest` (system_id -> (window, verdict) for ready systems only),
    `ran` (ready systems whose latest verdict is neither absent nor
    NOT_RUN -- PASS/FAILED/ERROR/anything else all count as "ran"),
    `not_run` (ready systems still NOT_RUN, or with no scorecard row at
    all), `min_n`.
    """
    from src.research import battery
    min_n = battery.MIN_N if min_n is None else min_n

    ranked = sorted(((len(v), s) for s, v in forward.items()), reverse=True)
    ready = [s for n, s in ranked if n >= min_n]

    ledger_existed = Path(scorecard_path).exists()
    latest = latest_battery_verdicts(ready, scorecard_path) if ready else {}

    ran, not_run = [], []
    for sid in ready:
        entry = latest.get(sid)
        if entry is None or entry[1] in (None, NOT_RUN):
            not_run.append(sid)
        else:
            ran.append(sid)

    return {
        "ranked": ranked, "ready": ready, "ledger_existed": ledger_existed,
        "latest": latest, "ran": ran, "not_run": not_run, "min_n": min_n,
    }


def format_report(readiness: dict, forward_count: int,
                   scorecard_path=SCORECARD_LEDGER_PATH) -> str:
    """Render `compute_readiness`'s output as the text this script prints.
    Pure string formatting -- kept separate from `compute_readiness` so a
    test can assert on the exact ESCALATE/INFO wording without needing a
    real `forward` dict of the right shape, and separate from `main()` so
    a test never has to capture stdout to check it.
    """
    min_n = readiness["min_n"]
    ranked = readiness["ranked"]
    ready = readiness["ready"]

    lines = [
        f"research readiness -- {forward_count} forward-test system(s) with "
        f"graded selections",
        f"  falsification battery needs {min_n} graded selections per "
        f"system (src/research/battery.py MIN_N)",
    ]
    for n, system_id in ranked[:5]:
        short = f"{n}/{min_n}"
        gap = min_n - n
        note = "READY" if gap <= 0 else f"{gap} more"
        lines.append(f"    {system_id}  {short:>7}  {note}")

    if not ready:
        best = ranked[0][0] if ranked else 0
        lines.append("")
        lines.append(
            f"  VERDICT: NOT YET. Best system has {best}; the battery would "
            f"skip every check and report a vacuous 'survives'. NOT_RUN "
            f"stays the honest scorecard verdict.")
        return "\n".join(lines)

    if not readiness["ledger_existed"]:
        lines.append("")
        lines.append(
            f"  note: scorecard ledger not found at {scorecard_path}; "
            f"treating every ready system as having no scorecard row yet")

    not_run = readiness["not_run"]
    ran = readiness["ran"]
    latest = readiness["latest"]

    if not_run:
        lines.append("")
        lines.append(
            f"ESCALATE: {len(not_run)} forward-test system(s) now have "
            f"{min_n}+ graded selections, but their latest scorecard still "
            f"reports the falsification battery as {NOT_RUN} (wiring landed "
            f"2026-09-15 in src/engine/settle_slate.py's run_settle -> "
            f"build_scorecard; check that a daily settle has run for these "
            f"systems since then): {', '.join(not_run)}")
    else:
        verdicts = ", ".join(f"{sid}={latest[sid][1]}" for sid in ran)
        lines.append("")
        lines.append(
            f"INFO: battery ran on {len(ran)} of {len(ready)} ready "
            f"systems; latest verdicts: {verdicts}")

    return "\n".join(lines)


def main() -> int:
    from src.report import engine_bridge

    by_system = graded_by_system()
    forward = {s: v for s, v in by_system.items()
               if engine_bridge.system_class(s) == engine_bridge.FORWARD_TEST}

    readiness = compute_readiness(forward, SCORECARD_LEDGER_PATH)
    print(format_report(readiness, len(forward), SCORECARD_LEDGER_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
