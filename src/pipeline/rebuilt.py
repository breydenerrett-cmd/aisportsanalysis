"""Splits, arsenals and matchup history, rebuilt forward from pitch-level rows.

These are the point-in-time replacements for the three LEAKY inputs. Each is a
pure accumulation over pitches with `game_date < cutoff`, which makes a cutoff a
filter rather than a re-request -- the same shape as every CLEAN input.

WOBA FROM THE FEED, NOT RECOMPUTED
----------------------------------
Statcast rows carry woba_value and woba_denom per plate-appearance-ending pitch.
Summing value over denom IS the league's wOBA construction; recomputing it from
event names would just re-derive the same weights with more places to go wrong.

SAMPLE GATES ARE THE SAME AS THE LIVE VERSIONS
----------------------------------------------
The rebuilt platoon split keeps the 60-batters-faced-per-side floor, and the
rebuilt matchup history reports at-bat counts so the debunk detector works
identically on history. A rebuilt feature that gated differently from its live
twin would make historical and forward results incomparable.
"""

from __future__ import annotations

from collections import defaultdict

from src.providers import statcast_pitches as sp

MIN_BF_PER_SIDE = 60          # mirrors lineups.MIN_BATTERS_FOR_SPLIT
MIN_PITCHES_FOR_MIX = 50      # mirrors the Savant leaderboard floor


def accumulate(cutoff, store=sp.DEFAULT_STORE) -> dict:
    """One pass over every pitch strictly before the cutoff.

    Returns the three rebuilt inputs at once -- splits, arsenals, matchup -- so a
    season's evaluation walks the data once per cutoff-month rather than three
    times per feature.
    """
    pitcher_vs = defaultdict(lambda: {"value": 0.0, "denom": 0, "bf": 0})
    arsenal = defaultdict(lambda: defaultdict(lambda: {
        "pitches": 0, "value": 0.0, "denom": 0, "whiffs": 0, "swings": 0}))
    matchup = defaultdict(lambda: {"ab": 0, "hits": 0, "k": 0, "value": 0.0,
                                   "denom": 0})
    # Batter against pitch TYPE, across every pitcher. The pitch-mix detector's
    # second half: a lineup's measured line against the one pitch tonight's
    # starter actually throws.
    batter_vs_pitch = defaultdict(lambda: {"value": 0.0, "denom": 0})

    HIT = {"single", "double", "triple", "home_run"}
    AB_EVENTS = HIT | {"strikeout", "strikeout_double_play", "field_out",
                       "grounded_into_double_play", "force_out", "field_error",
                       "double_play", "fielders_choice", "fielders_choice_out",
                       "triple_play", "other_out"}
    SWING = {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip",
             "hit_into_play", "foul_bunt", "missed_bunt"}
    WHIFF = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}

    for row in sp.iter_rows(store, before=cutoff):
        pitcher, batter = row.get("pitcher"), row.get("batter")
        stand = row.get("stand")
        if not pitcher:
            continue

        pitch_type = row.get("pitch_type")
        if pitch_type:
            slot = arsenal[pitcher][pitch_type]
            slot["pitches"] += 1
            description = row.get("description") or ""
            if description in SWING:
                slot["swings"] += 1
            if description in WHIFF:
                slot["whiffs"] += 1

        denom = row.get("woba_denom")
        if denom not in (None, "", "0"):
            value = float(row.get("woba_value") or 0)
            d = int(float(denom))
            if stand in ("L", "R"):
                key = (pitcher, stand)
                pitcher_vs[key]["value"] += value
                pitcher_vs[key]["denom"] += d
                pitcher_vs[key]["bf"] += 1
            if pitch_type:
                arsenal[pitcher][pitch_type]["value"] += value
                arsenal[pitcher][pitch_type]["denom"] += d
                if batter:
                    key = (batter, pitch_type)
                    batter_vs_pitch[key]["value"] += value
                    batter_vs_pitch[key]["denom"] += d

        event = row.get("events")
        if event and batter:
            key = (batter, pitcher)
            if event in AB_EVENTS:
                matchup[key]["ab"] += 1
                if event in HIT:
                    matchup[key]["hits"] += 1
                if event.startswith("strikeout"):
                    matchup[key]["k"] += 1
            if denom not in (None, "", "0"):
                matchup[key]["value"] += float(row.get("woba_value") or 0)
                matchup[key]["denom"] += int(float(denom))

    return {"cutoff": str(cutoff), "pitcher_vs": dict(pitcher_vs),
            "arsenal": {k: dict(v) for k, v in arsenal.items()},
            "matchup": dict(matchup),
            "batter_vs_pitch": dict(batter_vs_pitch)}


def platoon_split(acc, pitcher_id) -> dict:
    """Same contract as lineups.platoon_split, from rebuilt data.

    wOBA-against instead of OPS-against -- a better statistic and the one the
    pitch feed actually carries -- with the same both-sides sample floor.
    """
    left = acc["pitcher_vs"].get((str(pitcher_id), "L"),
                                 {"value": 0, "denom": 0, "bf": 0})
    right = acc["pitcher_vs"].get((str(pitcher_id), "R"),
                                  {"value": 0, "denom": 0, "bf": 0})
    if left["bf"] < MIN_BF_PER_SIDE or right["bf"] < MIN_BF_PER_SIDE:
        return {"usable": False,
                "reason": (f"only {left['bf']} batters faced left-handed and "
                           f"{right['bf']} right-handed before the cutoff; a "
                           f"platoon split needs {MIN_BF_PER_SIDE} each side"),
                "vs_left_faced": left["bf"], "vs_right_faced": right["bf"]}
    vs_l = left["value"] / left["denom"] if left["denom"] else None
    vs_r = right["value"] / right["denom"] if right["denom"] else None
    if vs_l is None or vs_r is None:
        return {"usable": False, "reason": "no wOBA denominator on one side"}
    gap = round(vs_l - vs_r, 4)
    return {"usable": True, "vs_left_woba": round(vs_l, 4),
            "vs_right_woba": round(vs_r, 4), "gap": gap,
            "weaker_against": "L" if gap > 0 else "R",
            "vs_left_faced": left["bf"], "vs_right_faced": right["bf"],
            "reason": None}


def pitch_mix(acc, pitcher_id) -> list:
    """Usage-ordered arsenal with whiff rate and wOBA-against, as of the cutoff."""
    slots = acc["arsenal"].get(str(pitcher_id)) or {}
    total = sum(s["pitches"] for s in slots.values())
    if total < MIN_PITCHES_FOR_MIX:
        return []
    out = []
    for pitch_type, s in slots.items():
        out.append({
            "pitch_type": pitch_type,
            "pitches": s["pitches"],
            "usage_pct": round(100.0 * s["pitches"] / total, 1),
            "whiff_pct": round(100.0 * s["whiffs"] / s["swings"], 1)
            if s["swings"] else None,
            "woba": round(s["value"] / s["denom"], 4) if s["denom"] else None,
        })
    out.sort(key=lambda r: -r["pitches"])
    return out


def batter_vs_pitcher(acc, batter_id, pitcher_id) -> dict:
    """Same shape as lineups.batter_vs_pitcher, but honest at any cutoff."""
    entry = acc["matchup"].get((str(batter_id), str(pitcher_id)),
                               {"ab": 0, "hits": 0, "k": 0, "value": 0.0,
                                "denom": 0})
    return {"at_bats": entry["ab"], "hits": entry["hits"],
            "strikeouts": entry["k"],
            "avg": round(entry["hits"] / entry["ab"], 3) if entry["ab"] else None,
            "woba": round(entry["value"] / entry["denom"], 4)
            if entry["denom"] else None}


def batter_vs_pitch_type(acc, batter_id, pitch_type) -> dict:
    """One hitter's wOBA against one pitch type, as of the cutoff."""
    entry = acc["batter_vs_pitch"].get((str(batter_id), pitch_type),
                                       {"value": 0.0, "denom": 0})
    return {"pa": entry["denom"],
            "woba": round(entry["value"] / entry["denom"], 4)
            if entry["denom"] else None}
