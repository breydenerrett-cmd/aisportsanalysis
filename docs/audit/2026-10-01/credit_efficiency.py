"""Credits spent against useful observations bought, per sport, before and
after a change to the capture cadence.

    python docs/audit/2026-10-01/credit_efficiency.py REF SPLIT_UTC [DAY]

REF is a git ref whose stores are read with `git show` (the runner's copy,
never the working tree). SPLIT_UTC is the instant the change reached the
runners, e.g. 2026-10-01T18:42. DAY (default: the split's date) limits the
report to one UTC day.

A "capture instant" is one distinct observed_utc minute in the odds store for
that sport. A credit is attributed to a caller by the drop in
`credits_remaining` between consecutive log rows, because `credits_used_last`
is zero on most rows. NFL "card-usable minutes" are the minutes in which the
newest NFL board was under 60 minutes old while some game was within six
hours of kickoff: the only minutes in which the NFL card can judge a price.
"""
from __future__ import annotations

import collections
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CREDIT_LOGS = ("data/processed/credit_log.jsonl", "data/live/credit_log_live.jsonl")
ODDS_STORE = "data/processed/odds_multibook.jsonl"
FRESH = timedelta(minutes=60)
WINDOW = timedelta(hours=6)


def show(ref: str, path: str):
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True)
    if proc.returncode:
        return []
    return proc.stdout.decode("utf-8", errors="replace").splitlines()


def rows(lines):
    for line in lines:
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def main(argv) -> int:
    ref, split_text = argv[1], argv[2]
    split = parse(split_text if len(split_text) > 16 else split_text + ":00+00:00")
    day = argv[3] if len(argv) > 3 else split.date().isoformat()

    log = sorted((r for path in CREDIT_LOGS for r in rows(show(ref, path))
                  if str(r.get("utc", "")).startswith(day) and r.get("credits_remaining") is not None),
                 key=lambda r: r["utc"])
    spent = {"before": collections.Counter(), "after": collections.Counter()}
    prev = None
    for row in log:
        left = row["credits_remaining"]
        if prev is not None and 0 < prev - left < 5000:
            side = "after" if parse(row["utc"]) >= split else "before"
            spent[side][str(row.get("caller")).split(".")[0]] += prev - left
        prev = left

    instants = collections.defaultdict(lambda: {"before": set(), "after": set()})
    row_count = collections.defaultdict(lambda: {"before": 0, "after": 0})
    kickoffs = set()
    for row in rows(show(ref, ODDS_STORE)):
        stamp = str(row.get("observed_utc") or "")
        if not stamp.startswith(day):
            continue
        sport = row.get("sport") or "mlb"
        side = "after" if parse(stamp) >= split else "before"
        instants[sport][side].add(stamp[:16])
        row_count[sport][side] += 1
        if sport == "nfl" and row.get("commence_time"):
            kickoffs.add(str(row["commence_time"]))

    first = parse(log[0]["utc"]) if log else split
    last = parse(log[-1]["utc"]) if log else split
    hours = {"before": max((split - first).total_seconds() / 3600, 0.0),
             "after": max((last - split).total_seconds() / 3600, 0.0)}

    print(f"ref {ref}  day {day}  split {split.isoformat()}")
    print(f"log covers {first.isoformat()} .. {last.isoformat()} "
          f"(before {hours['before']:.1f} h, after {hours['after']:.1f} h)")
    for side in ("before", "after"):
        total = sum(spent[side].values())
        rate = total / hours[side] if hours[side] else float("nan")
        print(f"\n{side.upper()}: {total} credits in {hours[side]:.1f} h ({rate:.1f} per hour)")
        for caller, credits in spent[side].most_common():
            print(f"  {caller:<16} {credits}")
        for sport in sorted(instants):
            n = len(instants[sport][side])
            if n:
                print(f"  {sport}: {n} capture instants, {row_count[sport][side]} rows")

    nfl_times = sorted(parse(t + ":00+00:00") for side in ("before", "after")
                       for t in instants["nfl"][side])
    starts = sorted(parse(k) for k in kickoffs)
    for side, lo, hi in (("before", first, split), ("after", split, last)):
        usable = in_window = 0
        minute = lo.replace(second=0, microsecond=0)
        while minute < hi:
            if any(timedelta(0) < s - minute <= WINDOW for s in starts):
                in_window += 1
                newest = max((t for t in nfl_times if t <= minute), default=None)
                if newest is not None and minute - newest <= FRESH:
                    usable += 1
            minute += timedelta(minutes=1)
        share = f"{usable / in_window * 100:.0f}%" if in_window else "n/a (no kickoff within 6 h)"
        nfl_credits = spent[side].get("nfl_capture", 0)
        per = f"{nfl_credits / (usable / 60):.1f} credits per card-usable hour" if usable else "no card-usable time"
        print(f"\nNFL {side}: {in_window} minutes with a kickoff within 6 h; "
              f"board under 60 min old for {usable} of them ({share}); "
              f"{nfl_credits} credits; {per}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
