"""Compute the tier ladder from a permutation null. docs/PREREG_TIER_LADDER.md.

The rule is transcribed from that document and is not an argument here:

    NULL          per date, hold fixed which systems played and how many
                  wagers each played, and how many backers each wager
                  attracted; reassign backers to wagers at random; recompute
                  family counts through the real clustering
    STRONG        family count >= 95th percentile of the null
    BUILDING      >= 75th percentile
    THIN          above the null's median
    PERMUTATIONS  10,000, seeded
    REFUSE if     real counts are not above the null, OR the split-half
                  check disagrees by more than one family, OR fewer than 20
                  usable dates

95 and 75 were chosen before the null was computed, precisely so they could
not be chosen after it.

Read-only. Prints the ladder the rule produces and adopts nothing; changing
src/engine/slip.py is a separate deliberate edit.

Usage:
    python scripts/test_tier_ladder.py [--json] [--permutations N]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import families as families_mod  # noqa: E402
from src.report.engine_bridge import system_class  # noqa: E402

# TRANSCRIBED FROM THE PRE-REGISTRATION. Not arguments.
STRONG_PERCENTILE = 95
BUILDING_PERCENTILE = 75
THIN_PERCENTILE = 50
PERMUTATIONS = 10_000
SEED = 20260910
MIN_WAGERS_PER_DATE = 5
MIN_SYSTEMS_PER_DATE = 5
MIN_DATES = 20
MAX_SPLIT_HALF_DISAGREEMENT = 1

DECISIONS = os.path.join("evidence", "decisions_v2.jsonl")


def _percentile(sorted_values, pct):
    if not sorted_values:
        return None
    idx = min(int(pct / 100.0 * len(sorted_values)), len(sorted_values) - 1)
    return sorted_values[idx]


def _load_plays():
    """{date: {wager_id: [system_id, ...]}} for FORWARD_TEST plays only."""
    by_date = defaultdict(lambda: defaultdict(list))
    if not os.path.exists(DECISIONS):
        return by_date
    with open(DECISIONS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("verdict") != "play":
                continue
            system_id = row.get("system_id") or ""
            if system_class(system_id) != "FORWARD_TEST":
                continue
            date = (row.get("decision_utc") or "")[:10]
            if not date:
                continue
            wager = families_mod.wager_id(row.get("event_id"),
                                          row.get("market_key"),
                                          row.get("selection_id"))
            by_date[date][wager].append(system_id)
    return by_date


def _family_count(system_ids, family_of):
    """Distinct families among these systems, using the real clustering map.

    Falls back to the raw distinct-system count only when no family is known
    for a system -- and that fallback is COUNTED and reported, because
    silently degrading to a system count is the exact number the family
    discount exists to replace.
    """
    families = set()
    unknown = 0
    for system_id in set(system_ids):
        family = family_of.get(system_id)
        if family is None:
            unknown += 1
            families.add(f"__unknown__{system_id}")
        else:
            families.add(family)
    return len(families), unknown


def _null_for_date(wagers, family_of, rng, permutations):
    """Family counts a date would produce if backers were assigned at random.

    Both marginals held: each system keeps its number of plays, each wager
    keeps its number of backers.
    """
    systems = []
    for backers in wagers.values():
        systems.extend(backers)
    sizes = [len(b) for b in wagers.values()]

    counts = []
    for _ in range(permutations):
        shuffled = list(systems)
        rng.shuffle(shuffled)
        cursor = 0
        for size in sizes:
            slice_ = shuffled[cursor:cursor + size]
            cursor += size
            count, _unknown = _family_count(slice_, family_of)
            counts.append(count)
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--permutations", type=int, default=PERMUTATIONS)
    args = ap.parse_args(argv)

    by_date = _load_plays()
    usable = {d: w for d, w in by_date.items()
              if len(w) >= MIN_WAGERS_PER_DATE
              and len({s for b in w.values() for s in b}) >= MIN_SYSTEMS_PER_DATE}

    if len(usable) < MIN_DATES:
        # EXIT 0, NOT AN ERROR. A pending pre-registration is a normal state
        # and this runs nightly; treating "not yet" as a failure would train
        # everyone to ignore the one night it turns into "now".
        short = MIN_DATES - len(usable)
        message = (f"PENDING: {len(usable)} of {MIN_DATES} usable dates "
                   f"({short} more needed). The tier ladder cannot be "
                   f"recalibrated yet and EVIDENCE_STRONG stays at 3 with "
                   f"the debt recorded in "
                   f"docs/INCIDENT_2026-09-10_STRONG_TIER.md.")
        if args.json:
            print(json.dumps({"status": "pending",
                              "usable_dates": len(usable),
                              "required": MIN_DATES, "short_by": short}))
        else:
            print(message)
            print("  A date counts once it carries at least "
                  f"{MIN_WAGERS_PER_DATE} played wagers and "
                  f"{MIN_SYSTEMS_PER_DATE} playing systems.")
            print("  The minimum was fixed before the null was computed, so "
                  "a ladder could not be estimated off a handful of days and "
                  "then defended because it existed.")
        return 0

    # The real clustering, so the null is collapsed the same way the live
    # slip collapses. Built once over the whole played population.
    family_of = {}
    try:
        from src.engine import glue
        family_of = glue.family_map() if hasattr(glue, "family_map") else {}
    except Exception:  # noqa: BLE001
        family_of = {}

    rng = random.Random(SEED)
    real_counts, null_counts = [], []
    unknown_total = 0
    per_date = {}

    for date in sorted(usable):
        wagers = usable[date]
        reals = []
        for backers in wagers.values():
            count, unknown = _family_count(backers, family_of)
            unknown_total += unknown
            reals.append(count)
        nulls = _null_for_date(wagers, family_of, rng,
                               max(1, args.permutations // len(usable)))
        real_counts.extend(reals)
        null_counts.extend(nulls)
        per_date[date] = {"real": reals, "null_median": statistics.median(nulls)}

    null_sorted = sorted(null_counts)
    ladder = {
        "STRONG": _percentile(null_sorted, STRONG_PERCENTILE),
        "BUILDING": _percentile(null_sorted, BUILDING_PERCENTILE),
        "THIN": _percentile(null_sorted, THIN_PERCENTILE),
    }

    real_mean = statistics.fmean(real_counts)
    null_mean = statistics.fmean(null_counts)
    above_null = real_mean > null_mean

    # Split-half stability, on dates rather than on rows.
    dates = sorted(per_date)
    mid = len(dates) // 2
    halves = []
    for chunk in (dates[:mid], dates[mid:]):
        nulls = []
        for date in chunk:
            nulls.extend(_null_for_date(
                usable[date], family_of, random.Random(SEED),
                max(1, args.permutations // max(len(chunk), 1))))
        s = sorted(nulls)
        halves.append({"STRONG": _percentile(s, STRONG_PERCENTILE),
                       "BUILDING": _percentile(s, BUILDING_PERCENTILE)})
    disagreement = max(
        abs((halves[0][k] or 0) - (halves[1][k] or 0))
        for k in ("STRONG", "BUILDING"))

    checks = {
        "real_agreement_exceeds_the_null": above_null,
        "split_half_within_one_family":
            disagreement <= MAX_SPLIT_HALF_DISAGREEMENT,
        "enough_dates": len(usable) >= MIN_DATES,
    }
    report = {
        "usable_dates": len(usable),
        "wagers_measured": len(real_counts),
        "permutations_per_date": max(1, args.permutations // len(usable)),
        "systems_with_no_known_family": unknown_total,
        "real_mean_families": round(real_mean, 3),
        "null_mean_families": round(null_mean, 3),
        "ladder_from_the_null": ladder,
        "split_halves": halves,
        "split_half_disagreement": disagreement,
        "checks": checks,
        "ADOPT": all(checks.values()),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["ADOPT"] else 1

    print(f"USABLE DATES  {report['usable_dates']}   "
          f"wagers {report['wagers_measured']}   "
          f"{report['permutations_per_date']} permutations per date")
    if unknown_total:
        print(f"  WARNING: {unknown_total} plays had no known family and fell "
              f"back to a raw system count. That is the exact number the "
              f"family discount exists to replace -- treat the ladder below "
              f"as provisional until the clustering map is available here.")
    print()
    print(f"  real agreement   mean {report['real_mean_families']} families")
    print(f"  null agreement   mean {report['null_mean_families']} families")
    print()
    print("  LADDER THE RULE PRODUCES")
    for tier in ("STRONG", "BUILDING", "THIN"):
        print(f"    {tier:<10} families >= {ladder[tier]}")
    print(f"\n  split halves: {halves[0]} / {halves[1]}   "
          f"disagreement {disagreement}")
    print()
    for check, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    print(f"  ==> {'ADOPT THIS LADDER' if report['ADOPT'] else 'DO NOT ADOPT'}")
    print()
    print("  This script adopts nothing. Changing src/engine/slip.py is a")
    print("  separate deliberate edit, and the result goes into")
    print("  docs/PREREG_TIER_LADDER.md either way.")
    return 0 if report["ADOPT"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
