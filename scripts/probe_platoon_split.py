"""Is the platoon matchup worth putting in the prop model? Two questions, not one.

WHY TWO QUESTIONS
-----------------
"Add platoon splits" sounds like one piece of work. It is two, and they have
different answers and different amounts of evidence behind them.

  1. **Is there a league-wide platoon effect?** Do left-handed batters as a
     group hit right-handed pitching better than left-handed pitching? This
     is one number estimated from every plate appearance in the store, and it
     will be precise.

  2. **Does an INDIVIDUAL batter's own split predict his future split?** Is
     this batter unusually good against lefties, in a way that will persist?
     This is one number per batter from a few hundred plate appearances, and
     it may be almost entirely noise.

The distinction decides what gets built. If (1) holds and (2) does not, the
right feature is a single league coefficient applied by bat-side -- robust,
cheap, and nearly impossible to overfit. If (2) also holds, each batter needs
his own regressed split, which is a much larger and much more fragile thing.

Getting this backwards is the classic way to overfit a projection: every
batter gets a personal split fitted to a few hundred plate appearances, the
model looks sharper in sample, and it forecasts worse.

WHO PITCHED: TWO INSTRUMENTS, AND THE CONTROL SAYS WHICH ONE LIES
-------------------------------------------------------------------
Both arms are run, on purpose, because the first one was wrong and the
switch-hitter control is what said so.

  **starter** -- attribute every one of a batter's plate appearances to the
  opposing STARTER's hand. This is the only thing box scores can support, and
  it is what most public platoon numbers are built from. It has two
  confounds baked in: a starter throws maybe three of a batter's four plate
  appearances, and managers bring in relievers *specifically* to reverse the
  platoon matchup for the rest.

  **plate appearance** -- `data/processed/gameflow_2026.jsonl` records the
  actual `pitcher_id` for every at-bat. No approximation, no relief confound.
  It covers far fewer games, so it trades sample for correctness.

**Switch hitters are the control and they are not optional.** A switch hitter
bats from whichever side has the advantage, by design, so his platoon gap
must be near zero. If an arm shows switch hitters with the same gap as
everyone else, that arm is measuring something other than platoon and its
numbers for left- and right-handed batters mean nothing either.

The starter arm failed exactly that check on 2026-09-10: left-handed batters
-0.51, right-handed -0.51, switch hitters -0.85 -- all the same sign, when
left and right must be OPPOSITE. Left- and right-handed batters cannot both
hit left-handed pitching better. The column was picking up something about
which pitchers are left-handed, not about the matchup.

ONE CONFOUND SURVIVES BOTH POOLED ARMS AND IT IS WORSE THAN "MASKING"
-----------------------------------------------------------------------
I first wrote that lineup selection would merely shrink the effect. It does
not. It reversed the sign, and the data said so before the reasoning did.

Teams platoon LEFT-handed hitters heavily, because most pitchers are
right-handed: the lefty who cannot handle lefties sits when a lefty starts.
So the pool of left-handed batters facing a left-hander is *not the same
group* as the pool facing a right-hander -- it is the subset good enough to
be left in. Pooling their rates compares two different populations and
attributes the difference to the matchup.

On 2026-09-10 that produced left-handed batters apparently hitting LEFT-handed
pitching **2.08 points better**, which is backwards from the best-established
platoon fact in baseball.

THE FIX is to compare each batter with HIMSELF: compute one batter's own rate
against each hand, take the difference, and average those differences across
batters. Composition cancels, because every batter contributes to both sides
of his own subtraction. That is the `within batter` arm, and it is the only
one of the three whose number is worth anything.

Read-only. Descriptive. Adopts nothing.

Usage:
    python scripts/probe_platoon_split.py [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import boxscores  # noqa: E402

BOX_STORE = os.path.join("data", "processed", "boxscores_2026.jsonl")
GAMEFLOW = os.path.join("data", "processed", "gameflow_2026.jsonl")
PITCHER_LOGS = os.path.join("data", "historical", "pitcher_logs.jsonl")
HANDEDNESS = os.path.join("data", "historical", "handedness.json")

# A hit, for "hits per plate appearance".
HIT_EVENTS = {"single", "double", "triple", "home_run"}

# Rows that are NOT plate appearances -- baserunning outcomes recorded in the
# same stream. Counting a caught stealing as a plate appearance would put a
# guaranteed non-hit in the denominator and drag every rate down.
NOT_A_PLATE_APPEARANCE = {
    "caught_stealing_2b", "caught_stealing_3b", "caught_stealing_home",
    "pickoff_1b", "pickoff_2b", "pickoff_3b",
    "pickoff_caught_stealing_2b", "pickoff_caught_stealing_3b",
    "pickoff_caught_stealing_home", "stolen_base_2b", "stolen_base_3b",
    "stolen_base_home", "wild_pitch", "passed_ball", "balk",
    "defensive_indiff", "other_advance", "runner_double_play",
}

# Below this a batter's split against one hand is reading noise rather than
# a rate. 60 plate appearances is about a fifth of a season's exposure to
# the minority hand.
MIN_PA_PER_HAND = 60

# The reliability half needs two halves. A batter must clear the floor in
# BOTH to appear in it -- a batter who cleared it only in the first half
# would contribute a prediction with nothing to check it against.
MIN_PA_PER_HALF = 40


def _load_handedness():
    if not os.path.exists(HANDEDNESS):
        return {}
    with open(HANDEDNESS, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _starter_ids():
    """{(person_id, date): True} for appearances flagged as starts."""
    starts = set()
    if not os.path.exists(PITCHER_LOGS):
        return starts
    with open(PITCHER_LOGS, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if int(row.get("games_started") or 0) == 1:
                starts.add((int(row["person_id"]), str(row.get("date") or "")))
    return starts


def _opposing_hand_by_game_side(box, starts, hands):
    """{(game_pk, batter_side): 'L'|'R'} -- the hand the batter faced.

    The OPPOSING starter: a home batter faces the away starter. A game-side
    with no flagged starter, or a starter whose hand is unknown, is absent
    from the mapping entirely rather than defaulting to right-handed --
    right-handed is the majority and defaulting to it would manufacture
    agreement with the league average.
    """
    starters = {}
    for row in box:
        if row.get("type") != "pitcher":
            continue
        key = (row.get("game_pk"), row.get("side"))
        try:
            ident = (int(row["player_id"]), str(row.get("date") or ""))
        except (KeyError, TypeError, ValueError):
            continue
        if ident not in starts:
            continue
        if key in starters:      # two flagged starters on one side: ambiguous
            starters[key] = None
            continue
        starters[key] = row["player_id"]

    out = {}
    for (game_pk, pitcher_side), pid in starters.items():
        if pid is None:
            continue
        throws = (hands.get(str(pid)) or {}).get("throws")
        if throws not in ("L", "R"):
            continue
        batter_side = "home" if pitcher_side == "away" else "away"
        out[(game_pk, batter_side)] = throws
    return out


def _plate_appearance_rows(hands):
    """One row per plate appearance, with the hand that ACTUALLY threw it.

    `gameflow_2026.jsonl` records `pitcher_id` on every at-bat, so nothing
    here is approximated: no starter stand-in, and a reliever brought in to
    reverse the matchup is attributed to the plate appearances he really
    faced rather than to the man he replaced.
    """
    rows, dropped = [], defaultdict(int)
    if not os.path.exists(GAMEFLOW):
        return rows, {"gameflow store absent": 1}
    with open(GAMEFLOW, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                play = json.loads(raw)
            except ValueError:
                continue
            if play.get("type") != "play":
                continue
            event = play.get("event_type")
            if event in NOT_A_PLATE_APPEARANCE:
                continue
            batter, pitcher = play.get("batter_id"), play.get("pitcher_id")
            if batter is None or pitcher is None:
                dropped["play with no batter or pitcher id"] += 1
                continue
            throws = (hands.get(str(pitcher)) or {}).get("throws")
            bats = (hands.get(str(batter)) or {}).get("bats")
            if throws not in ("L", "R"):
                dropped["pitcher's throwing hand unknown"] += 1
                continue
            if bats not in ("L", "R", "S"):
                dropped["batter's bat side unknown"] += 1
                continue
            rows.append({
                "date": str(play.get("date") or ""),
                "player_id": int(batter),
                "bats": bats, "faced": throws,
                "h": 1 if event in HIT_EVENTS else 0, "pa": 1,
            })
    return rows, dict(dropped)


def _split_stats(pairs):
    """(rate_vs_L, rate_vs_R, pa_vs_L, pa_vs_R) from (hand, h, pa) rows."""
    totals = {"L": [0, 0], "R": [0, 0]}
    for hand, hits, pa in pairs:
        if hand in totals:
            totals[hand][0] += hits
            totals[hand][1] += pa
    out = {}
    for hand, (hits, pa) in totals.items():
        out[hand] = (hits / pa if pa else None, pa)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    hands = _load_handedness()
    if not hands:
        print("no handedness cache", file=sys.stderr)
        return 1

    box = boxscores.read(BOX_STORE)
    starts = _starter_ids()
    faced = _opposing_hand_by_game_side(box, starts, hands)

    batters = [r for r in box if r.get("type") == "batter"]
    game_sides = {(r.get("game_pk"), r.get("side")) for r in batters}

    # Join: every batter-game where we know the hand faced and the batter's
    # own bat side.
    rows, dropped = [], defaultdict(int)
    for row in batters:
        key = (row.get("game_pk"), row.get("side"))
        hand = faced.get(key)
        if hand is None:
            dropped["no flagged starter, or his hand is unknown"] += 1
            continue
        bats = (hands.get(str(row.get("player_id"))) or {}).get("bats")
        if bats not in ("L", "R", "S"):
            dropped["batter's bat side unknown"] += 1
            continue
        pa = int(row.get("pa") or 0)
        if pa <= 0:
            dropped["no plate appearances"] += 1
            continue
        rows.append({
            "date": str(row.get("date") or ""),
            "player_id": int(row.get("player_id")),
            "bats": bats, "faced": hand,
            "h": int(row.get("h") or 0), "pa": pa,
        })

    starter_rows, starter_dropped = rows, dict(dropped)
    pa_rows, pa_dropped = _plate_appearance_rows(hands)

    arms = {}
    for name, arm_rows, arm_dropped in (
            ("starter", starter_rows, starter_dropped),
            ("plate appearance", pa_rows, pa_dropped)):
        arms[name] = _analyse(arm_rows)
        arms[name]["dropped"] = arm_dropped
        arms[name]["units"] = len(arm_rows)

    report = {
        "game_sides_total": len(game_sides),
        "game_sides_with_a_known_starter_hand": len(faced),
        "arms": arms,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=float))
        return 0

    print("IS THE PLATOON MATCHUP WORTH PUTTING IN THE PROP MODEL?")
    print()
    print(f"  {len(faced)} of {len(game_sides)} game-sides carry a flagged "
          f"starter whose hand we know")
    print()
    for name in ("starter", "plate appearance"):
        _print_arm(name, arms[name])
    print("  ADOPTS NOTHING. A feature built from this must be measured")
    print("  against the pre-registered bar in")
    print("  docs/PREREG_MARKET_VS_MODEL.md before it counts as progress.")
    return 0


def _within_batter(rows, *, min_pa_per_hand=MIN_PA_PER_HAND):
    """Each batter against HIMSELF, then averaged across batters.

    THE POOLED COLUMN COMPARES TWO DIFFERENT POPULATIONS. Teams platoon
    left-handed hitters heavily, so the left-handed batters who face a
    left-hander are the subset good enough not to be benched against one.
    Subtracting pooled rates credits that roster decision to the matchup,
    and on this data it flipped the sign.

    Here every batter contributes to both halves of his own subtraction, so
    composition cancels exactly. What remains is his platoon gap.

    WEIGHTED BY THE HARMONIC MEAN of his two plate-appearance counts, which
    is the right weight for a difference of two rates: a batter with 400
    against righties and 12 against lefties knows almost nothing about the
    difference, and an unweighted average would let him shout as loudly as a
    batter with 200 of each.
    """
    per_batter = defaultdict(lambda: {"L": [0, 0], "R": [0, 0], "bats": None})
    for row in rows:
        entry = per_batter[row["player_id"]]
        entry["bats"] = row["bats"]
        hand = row["faced"]
        if hand in ("L", "R"):
            entry[hand][0] += row["h"]
            entry[hand][1] += row["pa"]

    out = {}
    for bats in ("L", "R", "S"):
        gaps, weights = [], []
        for entry in per_batter.values():
            if entry["bats"] != bats:
                continue
            hl, pal = entry["L"]
            hr, par = entry["R"]
            if pal < min_pa_per_hand or par < min_pa_per_hand:
                continue
            gaps.append(hr / par - hl / pal)
            weights.append(2.0 / (1.0 / pal + 1.0 / par))
        if len(gaps) < 10:
            out[bats] = {"batters": len(gaps), "advantage_pts": None,
                         "se_pts": None}
            continue
        total = sum(weights)
        mean = sum(g * w for g, w in zip(gaps, weights)) / total
        # Weighted standard error of the weighted mean.
        var = (sum(w * (g - mean) ** 2 for g, w in zip(gaps, weights))
               / total)
        effective = total ** 2 / sum(w * w for w in weights)
        out[bats] = {
            "batters": len(gaps),
            "advantage_pts": mean * 100,
            "se_pts": math.sqrt(var / effective) * 100 if effective else None,
        }
    return out


def _analyse(rows):
    """Both questions on one set of (bats, faced, h, pa) rows."""
    if len(rows) < 500:
        return {"usable": len(rows), "league_effect": None,
                "within_batter": None, "individual_reliability": None}

    # -----------------------------------------------------------------
    # QUESTION 1: the league-wide effect, by bat side.
    # -----------------------------------------------------------------
    league = {}
    for bats in ("L", "R", "S"):
        subset = [r for r in rows if r["bats"] == bats]
        stats = _split_stats([(r["faced"], r["h"], r["pa"]) for r in subset])
        vs_l, pa_l = stats["L"]
        vs_r, pa_r = stats["R"]
        # Standard error of the difference of two binomial rates.
        se = None
        if vs_l is not None and vs_r is not None and pa_l and pa_r:
            se = math.sqrt(vs_l * (1 - vs_l) / pa_l
                           + vs_r * (1 - vs_r) / pa_r)
        league[bats] = {
            "units": len(subset),
            "vs_LHP": vs_l, "pa_vs_LHP": pa_l,
            "vs_RHP": vs_r, "pa_vs_RHP": pa_r,
            "advantage_pts": ((vs_r - vs_l) * 100
                              if vs_l is not None and vs_r is not None
                              else None),
            "se_pts": se * 100 if se else None,
        }

    # -----------------------------------------------------------------
    # QUESTION 2: does an individual's split persist? First half of his
    # season predicts the second half, split-half on his OWN games so the
    # two halves are the same batter under the same conditions.
    # -----------------------------------------------------------------
    by_player = defaultdict(list)
    for row in rows:
        by_player[row["player_id"]].append(row)

    firsts, seconds, overall_firsts = [], [], []
    reliability_n = 0
    for pid, games in by_player.items():
        games.sort(key=lambda r: r["date"])
        half = len(games) // 2
        early, late = games[:half], games[half:]

        def _gap(chunk):
            stats = _split_stats([(g["faced"], g["h"], g["pa"])
                                  for g in chunk])
            vs_l, pa_l = stats["L"]
            vs_r, pa_r = stats["R"]
            if (vs_l is None or vs_r is None
                    or pa_l < MIN_PA_PER_HALF or pa_r < MIN_PA_PER_HALF):
                return None, None
            return vs_r - vs_l, (sum(g["h"] for g in chunk)
                                 / sum(g["pa"] for g in chunk))

        early_gap, early_rate = _gap(early)
        late_gap, _late_rate = _gap(late)
        if early_gap is None or late_gap is None:
            continue
        reliability_n += 1
        firsts.append(early_gap)
        seconds.append(late_gap)
        overall_firsts.append(early_rate)

    reliability = None
    if reliability_n >= 30:
        mean_a = statistics.fmean(firsts)
        mean_b = statistics.fmean(seconds)
        cov = statistics.fmean((a - mean_a) * (b - mean_b)
                               for a, b in zip(firsts, seconds))
        sd_a = statistics.pstdev(firsts)
        sd_b = statistics.pstdev(seconds)
        reliability = {
            "batters": reliability_n,
            "correlation": (cov / (sd_a * sd_b)) if sd_a and sd_b else None,
            "first_half_spread_pts": sd_a * 100,
            "second_half_spread_pts": sd_b * 100,
        }

    return {"usable": len(rows), "league_effect": league,
            "within_batter": _within_batter(rows),
            "individual_reliability": reliability}


def _print_arm(name, arm):
    print(f"  === ARM: {name.upper()} ===   {arm['units']} units")
    if arm.get("dropped"):
        print(f"      dropped: {arm['dropped']}")
    league = arm["league_effect"]
    if league is None:
        print("      too few usable rows to analyse")
        print()
        return
    print()
    print("    QUESTION 1 -- IS THERE A LEAGUE-WIDE EFFECT?")
    print(f"      {'bats':<6}{'units':>8}{'vs LHP':>9}{'vs RHP':>9}"
          f"{'RHP edge':>10}{'se':>7}")
    for bats in ("L", "R", "S"):
        v = league[bats]
        if v["vs_LHP"] is None or v["vs_RHP"] is None:
            print(f"      {bats:<6}{v['units']:>8}      -- not enough")
            continue
        print(f"      {bats:<6}{v['units']:>8}{v['vs_LHP']:>9.4f}"
              f"{v['vs_RHP']:>9.4f}{v['advantage_pts']:>+10.2f}"
              f"{v['se_pts']:>7.2f}")

    # THE CONTROL, READ OUT LOUD rather than left for the reader to notice.
    # L and R must have OPPOSITE signs and S must be near zero. Anything
    # else means the arm is measuring something other than the matchup.
    left, right, switch = (league["L"]["advantage_pts"],
                           league["R"]["advantage_pts"],
                           league["S"]["advantage_pts"])
    print()
    if left is None or right is None:
        print("      CONTROL: not computable")
    elif left > 0 > right:
        verdict = "passes"
        if switch is not None and abs(switch) > max(abs(left), abs(right)):
            verdict = ("signs are right but switch hitters move MORE than "
                       "either, which should not happen")
        print(f"      CONTROL {verdict}: left-handed batters {left:+.2f}, "
              f"right-handed {right:+.2f}, switch {switch:+.2f}")
    else:
        print(f"      CONTROL FAILS: left-handed batters {left:+.2f} and "
              f"right-handed {right:+.2f} have the SAME sign.")
        print("      Both cannot hit left-handed pitching better. This arm is")
        print("      measuring something other than the platoon matchup and")
        print("      its numbers do not support a feature.")
    # THE ARM THAT REMOVES THE COMPOSITION CONFOUND. Every batter compared
    # with himself, so the roster decision cancels instead of being credited
    # to the matchup.
    within = arm.get("within_batter")
    if within:
        print()
        print(f"    SAME QUESTION, EACH BATTER AGAINST HIMSELF "
              f"({MIN_PA_PER_HAND}+ PA vs each hand)")
        print(f"      {'bats':<6}{'batters':>9}{'RHP edge':>11}{'se':>8}")
        for bats in ("L", "R", "S"):
            v = within[bats]
            if v["advantage_pts"] is None:
                print(f"      {bats:<6}{v['batters']:>9}"
                      f"      -- too few batters")
                continue
            print(f"      {bats:<6}{v['batters']:>9}"
                  f"{v['advantage_pts']:>+11.2f}{v['se_pts']:>8.2f}")
        wl, wr = within["L"]["advantage_pts"], within["R"]["advantage_pts"]
        print()
        if wl is not None and wr is not None and wl > 0 > wr:
            print("      CONTROL PASSES here: left-handed batters gain "
                  "against right-handed")
            print("      pitching and right-handed batters lose, which is the "
                  "platoon effect")
            print("      as every baseball source describes it. The pooled "
                  "column above was")
            print("      composition, not matchup.")
        elif wl is not None and wr is not None:
            print(f"      CONTROL STILL FAILS: {wl:+.2f} and {wr:+.2f} do not "
                  f"have opposite signs.")
            print("      Removing composition did not recover the effect, so "
                  "either the")
            print("      sample is too thin or something else is wrong. No "
                  "feature from this.")
        else:
            print("      not enough batters clear the floor against both "
                  "hands to say")
    print()
    print("    QUESTION 2 -- DOES AN INDIVIDUAL BATTER'S SPLIT PERSIST?")
    r = arm["individual_reliability"]
    if r:
        print(f"      {r['batters']} batters clearing {MIN_PA_PER_HALF} plate "
              f"appearances against BOTH hands in BOTH halves")
        print(f"      first half vs second half correlation: "
              f"{r['correlation']:+.3f}")
        print(f"      spread of splits: first half "
              f"{r['first_half_spread_pts']:.2f} pts, second half "
              f"{r['second_half_spread_pts']:.2f} pts")
        print()
        print("      NEAR ZERO MEANS THE INDIVIDUAL SPLIT IS NOISE. A batter")
        print("      who looked lefty-proof in April tells you nothing about")
        print("      August, and a personal fitted split would sharpen the")
        print("      model in sample and forecast worse. The right feature")
        print("      would then be ONE league coefficient by bat side.")
    else:
        print(f"      not enough batters clear {MIN_PA_PER_HALF} plate")
        print("      appearances against both hands in both halves")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
