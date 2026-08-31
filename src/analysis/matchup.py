"""Per-game matchup depth: the unit-vs-specific-weakness decomposition.

WHY THIS SECTION EXISTS
-----------------------
The briefing already shows who plays tonight. This section (Jacob's idea)
shows how each posted UNIT lines up against the opposing starter's SPECIFIC,
measured tendencies -- three pictures per side, each side's lineup paired with
the starter it actually faces:

  (a) handedness -- the lineup's bat-side composition and platoon share
      against the starter's own platoon split, batters-faced samples attached;
  (b) pitch mix -- the starter's most-used pitch and its usage share, and the
      posted lineup's measured line against that pitch type, pitch and PA
      counts attached;
  (c) concentration -- pooled wOBA of lineup slots 1-4 against slots 5-9,
      PA samples attached.

EVERYTHING COMES FROM THE REBUILT POINT-IN-TIME STORE
-----------------------------------------------------
Every number is an accumulation over pitch-level rows strictly before a
cutoff -- the same store, the same helpers, and the same sample floors the
research matrix (src/research/matrix.py) uses. Nothing here reaches a live
season-to-date endpoint, so nothing can quietly include tonight's game. For a
live slate the cutoff is the slate date itself: pitches before today are
exactly what is knowable today.

EVERY NUMBER CARRIES ITS SAMPLE, AND EVERY CLAIM IS AN OBSERVATION
------------------------------------------------------------------
A rate without its denominator is how a 4-for-8 ends up on a screen looking
like a read, so no value in this section travels without its sample size.
Values whose sample sits below a stated floor still render -- suppressing them
would hide the evidence -- but carry an explicit small-sample warning
sentence. And nothing here is a prediction: thirteen pre-registered
hypotheses built on these same inputs were tested against 2023-24 outcomes
and none cleared the bar (docs/RESULTS_STAGE2.md), so every sentence
describes what already happened before the cutoff, never what will happen
tonight.

NONE OVER GUESS
---------------
A picture whose input is missing -- no posted lineup, no probable starter, a
split below the floor, an empty pitch store -- is an honest absence with a
reason, never a fabricated number. The same rule the matrix and the dossier
already follow.
"""

from __future__ import annotations

from pathlib import Path

from src.pipeline import lineups as lineup_mod
from src.pipeline import rebuilt
from src.providers import statcast_pitches as sp

# The research matrix already derived per-batter all-pitch totals and the
# batting-order split; reusing its helpers (private by convention, shared by
# design) keeps this section's aggregation byte-identical to the matrix's
# rather than a near-twin that drifts.
from src.research.matrix import _batter_totals, _order

# Sample floors. The platoon (60 BF per side) and pitch-mix (50 pitches)
# floors are rebuilt's own gates, applied inside its helpers. The two lineup-
# level floors below are this section's: the same order of magnitude as the
# shared 60-unit floors everywhere else in the project (rebuilt.MIN_BF_PER_SIDE,
# lineups.MIN_LINEUP_AT_BATS) -- below sixty plate appearances a pooled rate
# is a week wearing the costume of a tendency. Unlike rebuilt's gates the
# number is still SHOWN below the floor, with an explicit warning, because at
# lineup level a thin read next to its sample is more honest than a hole the
# reader has to trust.
MIN_LINEUP_PA_VS_PITCH = 60
MIN_HALF_PA = 60

NATURE = ("Observations of play recorded before the cutoff, from pitch-level "
          "rows that already existed. Nothing in this section is a "
          "prediction.")


def build_section(acc, game, posted_lineup, handedness) -> dict:
    """The matchup-depth section for one game, from one rebuilt accumulation.

    Pure: everything it reads arrives as an argument (the same contract as
    matrix.row_for_game), so tests exercise it on tiny synthetic
    accumulations built through rebuilt's own public API.
    """
    handedness = handedness or {}
    batter_totals = _batter_totals(acc)
    section = {
        "cutoff": acc.get("cutoff"),
        "nature": NATURE,
        # Stated so a reader (or a test) can see which gates produced which
        # absences and warnings without opening the source.
        "floors": {
            "platoon_bf_per_side": rebuilt.MIN_BF_PER_SIDE,
            "pitch_mix_pitches": rebuilt.MIN_PITCHES_FOR_MIX,
            "lineup_vs_pitch_pa": MIN_LINEUP_PA_VS_PITCH,
            "half_pa": MIN_HALF_PA,
        },
    }

    # The crossing happens here and only here: a side's pictures describe its
    # LINEUP, which faces the OPPOSING probable starter -- the same single-
    # site pairing matrix.row_for_game and briefing._lineup_section use.
    for side, opposing_key in (("away", "home_probable_id"),
                               ("home", "away_probable_id")):
        slots = (posted_lineup or {}).get(side) or []
        opponent = "home" if side == "away" else "away"
        if not slots:
            section[side] = {
                "team": game.get(f"{side}_team"),
                "reason": (f"no posted {side} lineup stored, so there is no "
                           "unit to decompose"),
            }
            continue
        section[side] = _side_depth(acc, game, side, opponent, slots,
                                    game.get(opposing_key), handedness,
                                    batter_totals)
    return section


def _side_depth(acc, game, side, opponent, slots, pitcher_id, handedness,
                batter_totals) -> dict:
    throws = ((handedness.get(str(pitcher_id)) or {}).get("throws")
              if pitcher_id else None)
    return {
        "team": game.get(f"{side}_team"),
        "opposing_starter_id": str(pitcher_id) if pitcher_id else None,
        "opposing_starter_throws": throws,
        "handedness": _handedness_picture(acc, slots, pitcher_id, throws,
                                          handedness, opponent),
        "pitch_mix": _pitch_mix_picture(acc, slots, pitcher_id, opponent),
        "concentration": _concentration_picture(slots, batter_totals),
    }


# ---------------------------------------------------------------------------
# (a) handedness: lineup platoon share vs the starter's platoon split
# ---------------------------------------------------------------------------

def _handedness_picture(acc, slots, pitcher_id, throws, handedness,
                        opponent) -> dict:
    picture = {"lineup_counts": None, "lineup": None, "starter": None,
               "sentences": [], "warnings": [], "absent": []}

    # The lineup's own composition needs no pitcher and is always reportable.
    counts = lineup_mod.lineup_handedness(slots, handedness)
    picture["lineup_counts"] = counts
    picture["sentences"].append(
        f"The posted lineup bats {counts['L']}L / {counts['R']}R / "
        f"{counts['S']}S ({counts['known']} of {len(slots)} bat sides "
        "known).")

    if not pitcher_id:
        picture["absent"].append(
            f"no probable starter listed for the {opponent} side, so the "
            "platoon share and the starter's split cannot be paired with "
            "this lineup")
        return picture

    advantage = lineup_mod.platoon_advantage_share(slots, handedness, throws)
    if advantage["share"] is not None:
        picture["lineup"] = {"share": advantage["share"],
                             "advantaged": advantage["advantaged"],
                             "known": advantage["known"]}
        hand = "left" if throws == "L" else "right"
        picture["sentences"].append(
            f"{advantage['advantaged']} of the {advantage['known']} hitters "
            f"with a known bat side hold the platoon advantage against this "
            f"{hand}-handed starter ({advantage['share']:.1%}).")
    else:
        picture["absent"].append(f"lineup platoon share: {advantage['reason']}")

    # rebuilt.platoon_split applies the shared 60-BF-per-side floor and, below
    # it, returns the counts and the reason instead of a number.
    split = rebuilt.platoon_split(acc, pitcher_id)
    if split.get("usable"):
        picture["starter"] = {
            "gap": split["gap"],
            "vs_left_woba": split["vs_left_woba"],
            "vs_right_woba": split["vs_right_woba"],
            "vs_left_faced": split["vs_left_faced"],
            "vs_right_faced": split["vs_right_faced"],
            "weaker_against": split["weaker_against"],
        }
        picture["sentences"].append(
            f"That starter has allowed {split['vs_left_woba']:.3f} wOBA to "
            f"left-handed hitters ({split['vs_left_faced']} batters faced) "
            f"and {split['vs_right_woba']:.3f} to right-handed "
            f"({split['vs_right_faced']} faced) before the cutoff -- a gap "
            f"of {split['gap']:+.3f}.")
    else:
        picture["absent"].append(f"starter platoon split: {split['reason']}")
        left = split.get("vs_left_faced")
        right = split.get("vs_right_faced")
        if left is not None and (left < rebuilt.MIN_BF_PER_SIDE
                                 or right < rebuilt.MIN_BF_PER_SIDE):
            picture["warnings"].append(f"Small sample: {split['reason']}.")
    return picture


# ---------------------------------------------------------------------------
# (b) pitch mix: the starter's primary pitch, and this lineup against it
# ---------------------------------------------------------------------------

def _pitch_mix_picture(acc, slots, pitcher_id, opponent) -> dict:
    picture = {"primary": None, "lineup_vs_primary": None, "batters": [],
               "sentences": [], "warnings": [], "absent": []}
    if not pitcher_id:
        picture["absent"].append(
            f"no probable starter listed for the {opponent} side, so there "
            "is no arsenal to read this lineup against")
        return picture

    # pitch_mix applies the shared 50-pitch floor inside and sorts by usage.
    mix = rebuilt.pitch_mix(acc, str(pitcher_id))
    if not mix:
        picture["absent"].append(
            f"the starter has fewer than {rebuilt.MIN_PITCHES_FOR_MIX} "
            "pitches recorded before the cutoff, so his primary pitch is "
            "unknown")
        picture["warnings"].append(
            f"Small sample: fewer than {rebuilt.MIN_PITCHES_FOR_MIX} "
            "recorded pitches from this starter before the cutoff -- no "
            "pitch-mix read is possible.")
        return picture

    primary = mix[0]
    total_pitches = sum(row["pitches"] for row in mix)
    picture["primary"] = {
        "pitch_type": primary["pitch_type"],
        "usage_pct": primary["usage_pct"],
        "pitches": primary["pitches"],
        "total_pitches": total_pitches,
    }
    picture["sentences"].append(
        f"The opposing starter's most-used pitch before the cutoff is the "
        f"{primary['pitch_type']} at {primary['usage_pct']:.1f}% usage "
        f"({primary['pitches']} of {total_pitches} pitches).")

    # PA-weighted lineup line against the primary pitch -- the identical math
    # matrix.row_for_game uses, so a 3-PA fluke cannot swamp a 60-PA read.
    weighted, pa_total, measured = 0.0, 0, 0
    for slot in slots:
        line = rebuilt.batter_vs_pitch_type(acc, slot.get("person_id"),
                                            primary["pitch_type"])
        if line["pa"]:
            picture["batters"].append({
                "name": slot.get("name"), "order": slot.get("order"),
                "pa": line["pa"], "woba": line["woba"]})
        if line["pa"] and line["woba"] is not None:
            weighted += line["woba"] * line["pa"]
            pa_total += line["pa"]
            measured += 1
    if pa_total:
        picture["lineup_vs_primary"] = {
            "woba": round(weighted / pa_total, 4),
            "pa": pa_total,
            "batters_measured": measured,
        }
        picture["sentences"].append(
            f"This lineup has run {weighted / pa_total:.3f} wOBA against "
            f"that pitch type across {pa_total} PA ({measured} of "
            f"{len(slots)} posted hitters have a measured line).")
        if pa_total < MIN_LINEUP_PA_VS_PITCH:
            picture["warnings"].append(
                f"Small sample: the lineup's line against the "
                f"{primary['pitch_type']} rests on {pa_total} PA, below the "
                f"{MIN_LINEUP_PA_VS_PITCH}-PA floor -- treat it as noise, "
                "not a read.")
    else:
        picture["absent"].append(
            f"no posted hitter has a measured line against the "
            f"{primary['pitch_type']} before the cutoff")
    return picture


# ---------------------------------------------------------------------------
# (c) concentration: slots 1-4 against slots 5-9, all pitch types
# ---------------------------------------------------------------------------

def _concentration_picture(slots, batter_totals) -> dict:
    picture = {"top": None, "bottom": None, "gap": None,
               "sentences": [], "warnings": [], "absent": []}
    top = [s for s in slots if _order(s) is not None and 1 <= _order(s) <= 4]
    bottom = [s for s in slots if _order(s) is not None and _order(s) >= 5]
    picture["top"] = _pooled(top, batter_totals)
    picture["bottom"] = _pooled(bottom, batter_totals)

    for label, half in (("slots 1-4", picture["top"]),
                        ("slots 5-9", picture["bottom"])):
        if half is None:
            picture["absent"].append(
                f"no measured wOBA for {label} before the cutoff")
        else:
            picture["sentences"].append(
                f"Lineup {label} have run {half['woba']:.3f} wOBA across "
                f"all pitchers before the cutoff ({half['pa']} PA).")
            if half["pa"] < MIN_HALF_PA:
                picture["warnings"].append(
                    f"Small sample: {label} rest on {half['pa']} PA, below "
                    f"the {MIN_HALF_PA}-PA floor.")

    if picture["top"] and picture["bottom"]:
        picture["gap"] = round(picture["top"]["woba"]
                               - picture["bottom"]["woba"], 4)
        picture["sentences"].append(
            f"Top-minus-bottom concentration: {picture['gap']:+.3f} wOBA "
            f"({picture['top']['pa']} PA vs {picture['bottom']['pa']} PA).")
    return picture


def _pooled(slots, batter_totals):
    """Pooled wOBA for a group of slots, WITH its denominator, or None.

    Same sum-of-value over sum-of-denom as matrix._pooled_woba -- pooled, not
    a mean of per-batter rates, so a 2-PA hitter cannot count as much as a
    300-PA one -- but the PA total is kept, because in this section no number
    travels without its sample.
    """
    value, denom = 0.0, 0
    for slot in slots:
        entry = batter_totals.get(str(slot.get("person_id")))
        if entry:
            value += entry[0]
            denom += entry[1]
    if not denom:
        return None
    return {"woba": round(value / denom, 4), "pa": denom}


# ---------------------------------------------------------------------------
# Slate assembly
# ---------------------------------------------------------------------------

def depth_by_pk(games, lineups_by_pk, handedness, *, store=None,
                acc=None) -> dict:
    """Matchup-depth entries for a whole slate, keyed by game_pk.

    EVERY game gets an entry: a full section where a lineup is posted and the
    pitch store can speak, otherwise {"reason": ...} so the dossier records
    an honest absence rather than silently omitting the section.

    The accumulation is built ONCE for the slate -- one date-ordered walk of
    the pitch store, strictly before the slate's earliest game date, so no
    game's snapshot can contain any slate game's own pitches. When no game
    has a posted lineup the store is never opened at all. `store` and `acc`
    are injectable so tests run on synthetic fixtures; the default reads the
    real store.
    """
    lineups_by_pk = lineups_by_pk or {}
    out, with_lineup = {}, []
    for game in games or []:
        posted = lineups_by_pk.get(game.get("game_pk"))
        if posted and (posted.get("away") or posted.get("home")):
            with_lineup.append((game, posted))
        else:
            out[game.get("game_pk")] = {
                "reason": ("no posted lineup for this game, so there is no "
                           "unit to decompose")}
    if not with_lineup:
        return out

    if acc is None:
        target = Path(store) if store is not None else sp.DEFAULT_STORE
        dates = sorted({g.get("date") for g, _ in with_lineup if g.get("date")})
        undated_reason = ("the game carries no date, so a point-in-time "
                         "cutoff cannot be chosen")
        if not dates:
            for game, _ in with_lineup:
                out[game.get("game_pk")] = {"reason": undated_reason}
            return out
        if not sp.read_manifest(target).get("windows"):
            reason = (f"the pitch store at {target} holds no data; run the "
                      "statcast build first")
            for game, _ in with_lineup:
                out[game.get("game_pk")] = {"reason": reason}
            return out
        # The earliest game date: behind every game on the slate, never ahead
        # of any -- under-informed by at most a day, over-informed never.
        acc = rebuilt.accumulate(dates[0], store=target)
        for game, posted in with_lineup:
            if not game.get("date"):
                out[game.get("game_pk")] = {"reason": undated_reason}
            else:
                out[game.get("game_pk")] = build_section(
                    acc, game, posted, handedness)
        return out

    for game, posted in with_lineup:
        out[game.get("game_pk")] = build_section(acc, game, posted, handedness)
    return out
