"""Does tonight's batting slot beat the batter's own season average?

THE QUESTION, AND WHY IT IS NOT OBVIOUS
----------------------------------------
`src/analysis/playerprops.py` estimates a batter's plate appearances from his
own recent PA-per-game. That number already encodes his usual lineup slot: a
man who always bats leadoff averages about 4.6 and one who always bats
eighth about 3.9, and his own history says which he is.

So knowing tonight's card only helps **when a batter moves**. If everyone
hit in the same slot every night, the lineup would add nothing to the
estimate and would matter only for the separate question of whether he is
playing at all.

That makes this a real measurement rather than an assumption, and it decides
whether the whole lineup dependency is worth taking on for the projection --
which is a genuine cost, because lineups post two to four hours before first
pitch and a props card cannot freeze until they do.

WHAT IS MEASURED
----------------
On every batter-game where a posted lineup and a boxscore both exist:

  1. How much batters actually move between slots.
  2. The league-wide slot -> plate-appearance table, point-in-time.
  3. Which predicts the batter's ACTUAL plate appearances better -- his own
     season average, or tonight's slot -- by mean absolute error.

Read-only. Descriptive. Adopts nothing.

Usage:
    python scripts/probe_lineup_slot.py [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import boxscores, lineup_store  # noqa: E402

BOX_STORE = os.path.join("data", "processed", "boxscores_2026.jsonl")

# Below this a slot's plate-appearance average is reading noise.
MIN_PER_SLOT = 30

# A batter needs this many prior games before his own average is a fair
# comparison -- the same floor `playerprops` uses in spirit.
MIN_PRIOR_GAMES = 10


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    lineups = lineup_store.read()
    if not lineups:
        print("no posted lineups stored", file=sys.stderr)
        return 1

    box = [r for r in boxscores.read(BOX_STORE) if r.get("type") == "batter"]
    by_game_player = {}
    by_player = defaultdict(list)
    for row in box:
        pk, pid = str(row.get("game_pk")), row.get("player_id")
        if pk and pid is not None:
            by_game_player[(pk, int(pid))] = row
            by_player[int(pid)].append(row)
    for lines in by_player.values():
        lines.sort(key=lambda r: str(r.get("date") or ""))

    # Join: every batter who both appeared in a posted lineup and has a
    # boxscore line for that game.
    joined = []
    for pk, card in lineups.items():
        if not isinstance(card, dict):
            continue
        date = str(card.get("date") or "")
        for side in ("away", "home"):
            for entry in card.get(side) or ():
                pid = entry.get("person_id")
                order = entry.get("order")
                if pid is None or not order:
                    continue
                row = by_game_player.get((str(pk), int(pid)))
                if row is None:
                    continue
                joined.append({
                    "date": date or str(row.get("date") or ""),
                    "player_id": int(pid),
                    "slot": int(order),
                    "pa": int(row.get("pa") or 0),
                })

    if len(joined) < 500:
        print(f"only {len(joined)} joined batter-games -- the posted-lineup "
              f"store covers {len(lineups)} games and that is too few to "
              f"measure against", file=sys.stderr)
        if args.json:
            print(json.dumps({"joined": len(joined), "games": len(lineups)}))
        return 2

    joined.sort(key=lambda r: r["date"])

    # 1. HOW MUCH DO BATTERS ACTUALLY MOVE?
    slots_by_player = defaultdict(list)
    for row in joined:
        slots_by_player[row["player_id"]].append(row["slot"])
    movers = [s for s in slots_by_player.values() if len(s) >= 3]
    spread = [max(s) - min(s) for s in movers]
    stdevs = [statistics.pstdev(s) for s in movers if len(s) >= 3]

    # 2. THE SLOT TABLE, point-in-time: each row predicted from slots seen
    #    strictly earlier.
    slot_pa = defaultdict(list)
    season_err, slot_err, both_err = [], [], []
    seen_dates = set()

    for row in joined:
        date, pid, slot = row["date"], row["player_id"], row["slot"]
        prior = [r for r in by_player[pid] if str(r.get("date") or "") < date]
        if len(prior) < MIN_PRIOR_GAMES:
            continue
        season_pa = statistics.fmean(int(r.get("pa") or 0) for r in prior)

        table_slot = slot_pa.get(slot)
        if table_slot and len(table_slot) >= MIN_PER_SLOT:
            slot_estimate = statistics.fmean(table_slot)
            # The obvious combination: the batter's own average, shifted by
            # how far tonight's slot sits from the league's average slot.
            league_mean = statistics.fmean(
                [v for vals in slot_pa.values() for v in vals])
            combined = season_pa + (slot_estimate - league_mean)
            season_err.append(abs(season_pa - row["pa"]))
            slot_err.append(abs(slot_estimate - row["pa"]))
            both_err.append(abs(combined - row["pa"]))

        slot_pa[slot].append(row["pa"])
        seen_dates.add(date)

    table = {slot: round(statistics.fmean(v), 3)
             for slot, v in sorted(slot_pa.items())
             if len(v) >= MIN_PER_SLOT}

    report = {
        "posted_lineup_games": len(lineups),
        "joined_batter_games": len(joined),
        "scored": len(season_err),
        "movement": {
            "players_with_3plus_games": len(movers),
            "median_slot_range": (round(statistics.median(spread), 2)
                                  if spread else None),
            "median_slot_stdev": (round(statistics.median(stdevs), 3)
                                  if stdevs else None),
            "share_who_never_move": (
                round(sum(1 for s in movers if max(s) == min(s)) / len(movers), 3)
                if movers else None),
        },
        "slot_to_plate_appearances": table,
        "mean_absolute_error": {
            "batter_season_average": (round(statistics.fmean(season_err), 4)
                                      if season_err else None),
            "tonights_slot_alone": (round(statistics.fmean(slot_err), 4)
                                    if slot_err else None),
            "both_combined": (round(statistics.fmean(both_err), 4)
                              if both_err else None),
        },
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"POSTED LINEUPS  {report['posted_lineup_games']} games   "
          f"{report['joined_batter_games']} batter-games joined to a boxscore")
    print(f"SCORED          {report['scored']} (batters with "
          f"{MIN_PRIOR_GAMES}+ prior games and a filled slot table)")
    print()
    m = report["movement"]
    print("HOW MUCH DO BATTERS MOVE?")
    print(f"  {m['players_with_3plus_games']} batters with 3+ starts   "
          f"median slot range {m['median_slot_range']}   "
          f"median stdev {m['median_slot_stdev']}")
    print(f"  never moved at all: {m['share_who_never_move']:.1%}"
          if m["share_who_never_move"] is not None else "")
    print()
    print("SLOT -> PLATE APPEARANCES")
    for slot, pa in report["slot_to_plate_appearances"].items():
        print(f"  {slot}: {pa}")
    print()
    e = report["mean_absolute_error"]
    print("WHICH PREDICTS TONIGHT'S PLATE APPEARANCES BETTER?")
    print(f"  the batter's own season average   {e['batter_season_average']}")
    print(f"  tonight's slot alone              {e['tonights_slot_alone']}")
    print(f"  both combined                     {e['both_combined']}")
    print()
    best = min((v, k) for k, v in e.items() if v is not None)[1]
    print(f"  lowest error: {best}")
    print()
    print("  If the season average already wins, the lineup adds nothing to")
    print("  the PROJECTION and matters only for the separate question of")
    print("  whether the batter is playing at all -- which is still a hard")
    print("  requirement for publishing a live pick.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
