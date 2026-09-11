"""Fill the handedness cache for everyone who appears in the box scores.

WHY THIS EXISTS
---------------
`data/historical/handedness.json` held 433 people on 2026-09-10, and they
were almost all position players -- of the 286 pitchers flagged as starters
in the 2026 box scores, exactly **one** had a throwing hand recorded.

That is not a bug in `lineups.fetch_handedness`, which has always captured
`throws` alongside `bats`. It is that nothing ever called it with a pitcher's
id: the only caller (`src/cli.py`) passes the posted lineup plus the two
probable starters for TONIGHT's slate, so the cache grew one day at a time
and never looked backwards.

The cost of the gap is that the platoon matchup -- which hand a batter faced
-- cannot be reconstructed for any historical game, and a platoon feature
cannot be measured, let alone built. `scripts/probe_platoon_split.py` found
28 usable batter-games out of 23,470 for exactly this reason.

WHAT IT DOES
------------
Collects every distinct `player_id` in the box-score store, batters and
pitchers alike, and asks `lineups.fetch_handedness` for the ones the cache
does not already hold. That function is already chunked and already writes
the cache; this only supplies the ids.

THE SOURCE IS FREE. It is the MLB Stats API (`people`), not the metered odds
feed, so this spends no odds credits -- see `docs/RESOURCE_POLICY.md` for why
that distinction matters. It is a read; it adds to a cache and removes
nothing.

Usage:
    python scripts/backfill_handedness.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import boxscores, lineups  # noqa: E402

BOX_STORE = os.path.join("data", "processed", "boxscores_2026.jsonl")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--box-store", default=BOX_STORE)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what is missing and fetch nothing")
    args = ap.parse_args(argv)

    if not os.path.exists(args.box_store):
        print(f"no box-score store at {args.box_store}", file=sys.stderr)
        return 1

    ids, by_type = set(), {"batter": set(), "pitcher": set()}
    for row in boxscores.read(args.box_store):
        kind = row.get("type")
        pid = row.get("player_id")
        if kind in by_type and pid is not None:
            ids.add(str(pid))
            by_type[kind].add(str(pid))

    cache_path = lineups.DEFAULT_HANDEDNESS
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)

    missing = sorted(i for i in ids if i not in cache)

    print(f"BOX SCORES   {len(ids)} distinct people "
          f"({len(by_type['batter'])} batters, "
          f"{len(by_type['pitcher'])} pitchers)")
    print(f"CACHE        {len(cache)} already held")
    print(f"MISSING      {len(missing)}")
    for kind in ("batter", "pitcher"):
        gap = len(by_type[kind] - set(cache))
        print(f"  {kind:<9} {gap} of {len(by_type[kind])} not cached")

    if not missing:
        print("nothing to fetch")
        return 0
    if args.dry_run:
        print("dry run -- fetched nothing")
        return 0

    print(f"fetching {len(missing)} from the MLB Stats API "
          f"(free; no odds credits)...")
    cache = lineups.fetch_handedness(missing, cache_path=cache_path)

    # WHAT ACTUALLY LANDED, not what was asked for. A person the API does not
    # return simply stays missing, and reporting the request count as though
    # it were the result is how a partial backfill reads as a complete one.
    still = sorted(i for i in ids if i not in cache)
    throws = sum(1 for i in by_type["pitcher"]
                 if (cache.get(i) or {}).get("throws") in ("L", "R"))
    bats = sum(1 for i in by_type["batter"]
               if (cache.get(i) or {}).get("bats") in ("L", "R", "S"))
    print(f"CACHE NOW    {len(cache)} people")
    print(f"  pitchers with a known throwing hand: "
          f"{throws} of {len(by_type['pitcher'])}")
    print(f"  batters with a known bat side:       "
          f"{bats} of {len(by_type['batter'])}")
    if still:
        print(f"  STILL MISSING {len(still)} -- the API returned nothing for "
              f"these ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
