"""Splits, arsenals and matchup history, rebuilt forward from pitch-level rows.

These are the point-in-time replacements for the three LEAKY inputs. Each is a
pure accumulation over pitches with `game_date < cutoff`, which makes a cutoff a
filter rather than a re-request -- the same shape as every CLEAN input.

Because a cutoff is a filter, a season of monthly cutoffs is one date-ordered
walk with a deep snapshot taken at each boundary (build_snapshots), not one
full re-read per cutoff: ~14 monthly cutoffs over ~2.8M rows would otherwise
re-process the same early rows fourteen times. accumulate() is deliberately
the single-cutoff case of that walk so the two can never drift -- even float
summation order is shared.

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
from datetime import datetime

from src.providers import statcast_pitches as sp

MIN_BF_PER_SIDE = 60          # mirrors lineups.MIN_BATTERS_FOR_SPLIT
MIN_PITCHES_FOR_MIX = 50      # mirrors the Savant leaderboard floor

# Fastball velocity, for the starter_velocity_gap feature. FF (four-seam)
# and SI (sinker) are the primary fastballs a velocity-decline read cares
# about; FC (cutter) is excluded because it is thrown 2-4 mph slower by
# design and a mix shift toward it would masquerade as lost velocity.
FASTBALL_TYPES = ("FF", "SI")
# A starter's recent-form window: his last N appearances before the cutoff.
# Five starts is roughly a month of work -- long enough to smooth one cold
# night, short enough that April velocity does not hide a June decline.
VELOCITY_STARTS_WINDOW = 5
# A single start is ~40-60 fastballs; 100 is about two full starts. Below
# that, per-game radar/park calibration noise (about +/-0.3 mph) and one
# amped relief cameo can swing the average more than a real decline would,
# so the feature reports None rather than a small-sample number.
MIN_FASTBALLS_FOR_VELOCITY = 100

HIT = {"single", "double", "triple", "home_run"}
AB_EVENTS = HIT | {"strikeout", "strikeout_double_play", "field_out",
                   "grounded_into_double_play", "force_out", "field_error",
                   "double_play", "fielders_choice", "fielders_choice_out",
                   "triple_play", "other_out"}
SWING = {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip",
         "hit_into_play", "foul_bunt", "missed_bunt"}
WHIFF = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}


def _new_state() -> dict:
    return {
        "pitcher_vs": defaultdict(lambda: {"value": 0.0, "denom": 0, "bf": 0}),
        "arsenal": defaultdict(lambda: defaultdict(lambda: {
            "pitches": 0, "value": 0.0, "denom": 0, "whiffs": 0, "swings": 0})),
        "matchup": defaultdict(lambda: {"ab": 0, "hits": 0, "k": 0,
                                        "value": 0.0, "denom": 0}),
        # Batter against pitch TYPE, across every pitcher. The pitch-mix
        # detector's second half: a lineup's measured line against the one
        # pitch tonight's starter actually throws.
        "batter_vs_pitch": defaultdict(lambda: {"value": 0.0, "denom": 0}),
        # Fastball velocity, kept PER GAME so an accessor can window to a
        # pitcher's last N appearances: pitcher -> (game_date, game_pk) ->
        # {sum, count}. A season is ~35 games per pitcher, so keeping every
        # game costs nothing and lets the window be applied at read time.
        "fastball_velocity": defaultdict(
            lambda: defaultdict(lambda: {"sum": 0.0, "count": 0})),
        # League-wide fastball velocity as of the cutoff, the baseline the
        # starter's recent average is compared against.
        "league_fastball": {"sum": 0.0, "count": 0},
    }


def _process_row(state, row) -> None:
    """Fold one pitch into the running state.

    The ONLY row-processing path -- accumulate and build_snapshots both call
    it, so a per-cutoff rerun and a single incremental walk cannot drift.
    """
    pitcher, batter = row.get("pitcher"), row.get("batter")
    stand = row.get("stand")
    if not pitcher:
        return

    pitch_type = row.get("pitch_type")
    if pitch_type in FASTBALL_TYPES:
        speed = row.get("release_speed")
        if speed not in (None, ""):
            try:
                mph = float(speed)
            except (TypeError, ValueError):
                mph = None  # unparseable radar reading: skip, never guess
            if mph is not None:
                game_key = (row.get("game_date") or "",
                            str(row.get("game_pk") or ""))
                slot = state["fastball_velocity"][pitcher][game_key]
                slot["sum"] += mph
                slot["count"] += 1
                state["league_fastball"]["sum"] += mph
                state["league_fastball"]["count"] += 1

    if pitch_type:
        slot = state["arsenal"][pitcher][pitch_type]
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
            state["pitcher_vs"][key]["value"] += value
            state["pitcher_vs"][key]["denom"] += d
            state["pitcher_vs"][key]["bf"] += 1
        if pitch_type:
            state["arsenal"][pitcher][pitch_type]["value"] += value
            state["arsenal"][pitcher][pitch_type]["denom"] += d
            if batter:
                key = (batter, pitch_type)
                state["batter_vs_pitch"][key]["value"] += value
                state["batter_vs_pitch"][key]["denom"] += d

    event = row.get("events")
    if event and batter:
        key = (batter, pitcher)
        if event in AB_EVENTS:
            state["matchup"][key]["ab"] += 1
            if event in HIT:
                state["matchup"][key]["hits"] += 1
            if event.startswith("strikeout"):
                state["matchup"][key]["k"] += 1
        if denom not in (None, "", "0"):
            state["matchup"][key]["value"] += float(row.get("woba_value") or 0)
            state["matchup"][key]["denom"] += int(float(denom))


def _finalize(state, cutoff) -> dict:
    """Plain-dict copy of the state, deep enough to be an independent snapshot.

    Every level down to the leaf counter dicts is a NEW container, so later
    processing of the running state can never mutate an emitted snapshot.
    """
    return {"cutoff": str(cutoff),
            "pitcher_vs": {k: dict(v)
                           for k, v in state["pitcher_vs"].items()},
            "arsenal": {p: {t: dict(s) for t, s in slots.items()}
                        for p, slots in state["arsenal"].items()},
            "matchup": {k: dict(v) for k, v in state["matchup"].items()},
            "batter_vs_pitch": {k: dict(v)
                                for k, v in state["batter_vs_pitch"].items()},
            "fastball_velocity": {p: {g: dict(s) for g, s in games.items()}
                                  for p, games
                                  in state["fastball_velocity"].items()},
            "league_fastball": dict(state["league_fastball"])}


def _gate(cutoff) -> str:
    # Same reduction iter_rows applies: str(datetime) carries a time suffix
    # that sorts AFTER the bare 'YYYY-MM-DD' date and would silently admit
    # the cutoff day's own pitches, so reduce to the calendar day first.
    if isinstance(cutoff, datetime):
        cutoff = cutoff.date()
    return str(cutoff)


def accumulate(cutoff, store=sp.DEFAULT_STORE) -> dict:
    """One pass over every pitch strictly before the cutoff.

    Returns the three rebuilt inputs at once -- splits, arsenals, matchup -- so a
    season's evaluation walks the data once per cutoff-month rather than three
    times per feature.
    """
    # The single-cutoff case of the incremental walk. Delegating (rather than
    # looping over iter_rows here) keeps the two paths byte-identical: even
    # float summation ORDER matters, and a separate loop reading rows in file
    # order would drift from the date-ordered walk by an epsilon.
    return build_snapshots([cutoff], store=store)[str(cutoff)]


def build_snapshots(cutoffs, store=sp.DEFAULT_STORE) -> dict:
    """accumulate() at every cutoff, walking the stored windows exactly once.

    A season rerun needs ~14 monthly cutoffs over millions of rows; re-reading
    the whole store per cutoff is the same accumulation fourteen times over.
    Rows arrive in game_date order (iter_rows_dated), so each cutoff's snapshot
    is taken the moment the walk first reaches a row at-or-after its date --
    the cutoff day's own rows are still strictly excluded, matching iter_rows.
    """
    pending = sorted(((_gate(c), c) for c in cutoffs), key=lambda p: p[0])
    state = _new_state()
    snapshots = {}
    index = 0
    for row in sp.iter_rows_dated(store):
        day = row.get("game_date") or "9999"
        while index < len(pending) and day >= pending[index][0]:
            gate_cutoff = pending[index][1]
            snapshots[str(gate_cutoff)] = _finalize(state, gate_cutoff)
            index += 1
        if index == len(pending):
            break  # every snapshot taken; later rows can't matter
        _process_row(state, row)
    # Cutoffs past the last stored row see everything, same as accumulate.
    while index < len(pending):
        gate_cutoff = pending[index][1]
        snapshots[str(gate_cutoff)] = _finalize(state, gate_cutoff)
        index += 1
    return snapshots


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


def fastball_velocity(acc, pitcher_id) -> dict:
    """A pitcher's average FF/SI velocity over his last N appearances.

    The window is the last VELOCITY_STARTS_WINDOW games with at least one
    measured fastball, all strictly before the accumulation's cutoff -- the
    recent-form read, not a career average. Below the
    MIN_FASTBALLS_FOR_VELOCITY floor across that window the answer is None
    with a reason, never a small-sample number.
    """
    games = (acc.get("fastball_velocity") or {}).get(str(pitcher_id)) or {}
    # Game keys are (game_date, game_pk); sorting by key IS date order, with
    # the pk as a stable tie-break for a doubleheader.
    recent = sorted(games)[-VELOCITY_STARTS_WINDOW:]
    total = sum(games[key]["count"] for key in recent)
    if total < MIN_FASTBALLS_FOR_VELOCITY:
        return {"usable": False, "avg": None, "fastballs": total,
                "games": len(recent),
                "reason": (f"only {total} measured fastballs across the "
                           f"pitcher's last {len(recent)} appearances before "
                           f"the cutoff; the velocity read needs "
                           f"{MIN_FASTBALLS_FOR_VELOCITY}")}
    speed_sum = sum(games[key]["sum"] for key in recent)
    return {"usable": True, "avg": speed_sum / total, "fastballs": total,
            "games": len(recent), "reason": None}


def league_fastball_velocity(acc):
    """League-average FF/SI velocity as of the cutoff, or None before any
    fastball has been thrown (opening week of the store's first season)."""
    league = acc.get("league_fastball") or {}
    count = league.get("count") or 0
    return league["sum"] / count if count else None
