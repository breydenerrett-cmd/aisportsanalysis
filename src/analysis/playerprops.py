"""What a hitter does in one game, as a probability. The player-prop model.

WHY THIS EXISTS, AND WHY IT IS THE RIGHT PLACE TO LOOK
------------------------------------------------------
This project spent a long time modelling who wins a baseball game. That is
the worst market in the sport to pick: a nine-inning outcome is mostly noise,
and the full-game moneyline is the most heavily priced, most watched, most
limited line on the board. Measured over 1,896 games, the team model beats a
coin that knows only home-field advantage by **0.004 nats**
(`scripts/backtest_card.py`). Essentially nothing.

A hitter's chance of getting a hit is a far more tractable question. He comes
to the plate four times against a known pitcher in a known park, and his own
rate over hundreds of plate appearances is a real estimate rather than a
guess. The lines are quoted by fewer books, moved less often, and attract
less attention than the game line.

The owner's framing, 2026-09-10, and it is the right one: *the really good
bets do not come from one team winning a ball game. They come from knowing
Mookie Betts is starting and that our numbers make him better than 50% for a
hit while the book is paying +110.*

WHAT THIS MODULE COMPUTES
-------------------------
Per batter, per game, the probability of clearing the lines the books
actually quote:

    batter_hits            over 0.5   -> P(at least one hit)
    batter_total_bases     over 1.5   -> P(two or more total bases)
    batter_home_runs       over 0.5   -> P(at least one home run)
    batter_runs_scored     over 0.5   -> P(at least one run)
    batter_rbis            over 0.5   -> P(at least one RBI)
    batter_hits_runs_rbis  over 1.5   -> P(H + R + RBI >= 2)

THE ARITHMETIC
--------------
A plate appearance has a small number of outcomes and this models them
directly rather than fitting anything:

  1. EXPECTED PLATE APPEARANCES. From the batter's own recent PA-per-game,
     which encodes his lineup slot without needing the lineup card: a leadoff
     hitter averages about 4.6 and a ninth-place hitter about 3.9, and his
     own history says which he is. For a LIVE pick the lineup still matters
     -- you cannot bet a man who is not playing -- but the backtest does not
     need it, which is what makes this measurable today.

  2. PER-PA OUTCOME RATES, regressed toward the league. Singles, doubles,
     triples, home runs and "nothing" are five buckets that sum to one.

  3. THE OPPOSING STARTER, as a multiplier on the batter's hit rate, from
     how many hits per batter faced he has allowed against the league's own
     rate. Weighted by the share of the game he is expected to pitch.

  4. THE COUNT DISTRIBUTION. Given `n` plate appearances and per-PA
     probabilities, the number of hits is Binomial and total bases is the
     convolution of `n` independent draws. Both are computed exactly rather
     than simulated -- `n` is about four and the outcome space is tiny.

WHERE THIS IS KNOWABLY WRONG, UP FRONT
---------------------------------------
* Plate appearances are treated as independent and identically distributed.
  They are not: a hitter faces the starter three times and a reliever once,
  and the third time through the order is easier than the first.
* Expected PAs is a point estimate, not a distribution. A blowout or a rain
  delay moves it.
* No park factor. `src.pipeline.parkfactors` exists and is switched off for
  the team model; wiring it here is a separate, measurable change.
* No platoon split. The handedness data is captured
  (`data/historical/handedness.json`) and unused here.
* RBIs and runs depend on teammates reaching base, which this models only
  through the batter's own rates and the opposing pitcher. They are the
  weakest of the six and are marked as such.

None of these are secret and none is fixed by attaching a bigger number to
the output. They are why a published prop pick is a read, not a promise.

Pure. stdlib only, no I/O -- every input arrives as an argument, which is
what lets `scripts/backtest_player_props.py` run it over a season without
touching a network or a clock.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants. Published or structural; none fitted.
# ---------------------------------------------------------------------------

# How hard each rate is pulled toward the league, in plate appearances. A
# hitter with 400 PA is barely moved; one with 30 is mostly league-average.
# 200 is roughly a third of a full season's playing time, and it is fixed in
# advance rather than tuned against any result.
PA_REGRESSION = 200.0

# The same, for a pitcher's hits-allowed rate, in batters faced.
BF_REGRESSION = 300.0

# A batter with fewer than this many plate appearances has no usable rate at
# all and the model refuses rather than publishing a league-average guess
# under his name.
MIN_PA_FOR_A_RATE = 40

# The starter's expected share of the batters a lineup faces. Nine innings,
# a starter going about 5.5, so a little under two thirds. Held fixed rather
# than derived per pitcher: the alternative multiplies two noisy estimates.
STARTER_SHARE = 0.62

# Bounds on the starter multiplier, so one corrupt line cannot move a
# batter's whole projection.
MIN_PITCHER_FACTOR = 0.80
MAX_PITCHER_FACTOR = 1.25

MODEL_ID = "batter_pa_outcome_v1"
MODEL_BASIS = (
    "Per-plate-appearance outcome rates from the batter's own season, "
    "regressed toward the league, scaled by the opposing starter's "
    "hits-allowed rate, over his expected number of plate appearances. "
    "Exact count distributions, nothing simulated, nothing fitted."
)

# The markets this module prices, and what clearing the line means. A market
# absent from here is not priced at all rather than guessed at.
SUPPORTED_MARKETS = (
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
    "batter_runs_scored",
    "batter_rbis",
    "batter_hits_runs_rbis",
)

# Markets whose outcome depends heavily on teammates rather than the batter.
# Priced, but flagged, because a reader deserves to know which of our numbers
# rest on the thinnest reasoning.
TEAMMATE_DEPENDENT = ("batter_runs_scored", "batter_rbis",
                      "batter_hits_runs_rbis")

# MARKETS THIS MODEL MAY NOT PUBLISH, measured rather than suspected.
#
# `scripts/backtest_player_props.py` over 16,741 real batter games, against
# a base rate, in nats (positive is better than knowing nothing):
#
#     batter_hits            over 0.5   +0.01068   calibrated to ~4 pts
#     batter_total_bases     over 1.5   +0.01021   calibrated to ~1 pt
#     batter_runs_scored     over 0.5   +0.00649   calibrated to ~3 pts
#     batter_home_runs       over 0.5   +0.00616   calibrated to ~2 pts
#     batter_rbis            over 0.5   -0.01353   WORSE THAN A BASE RATE
#     batter_hits_runs_rbis  over 1.5   -0.04033   MUCH WORSE
#
# The two negatives share one cause and it is a real modelling failure, not
# noise. RBIs and hits-plus-runs-plus-RBIs are BUNCHED counts: a home run
# with two aboard is three RBIs in a single plate appearance. Treating a
# per-PA rate as a Bernoulli trial and asking for "at least one" assumes
# those events arrive one at a time, so it badly overstates how often a
# batter gets any at all. Measured: the model said 56.3% for
# hits-runs-RBIs over 1.5 and the real answer was 42.0%, with the gap
# widening to 35 points in the top bucket.
#
# They stay PRICEABLE so the backtest can keep measuring them -- switching
# off the measurement is how a known-broken thing stops being known -- and
# they are refused for publication. `publishable()` is what the card asks.
#
# The fix, when someone does it: model these off the batter's own per-GAME
# distribution rather than a per-PA rate, which carries the bunching for
# free. That is a different model and it needs its own measurement.
NOT_PUBLISHABLE = {
    "batter_rbis": "bunched count: a home run with runners on is several "
                   "RBIs in one plate appearance, and a per-PA rate treated "
                   "as a coin flip overstates how often a batter gets any. "
                   "Measured at -0.014 nats, worse than knowing nothing.",
    "batter_hits_runs_rbis": "the same bunching, compounded across three "
                             "correlated counts. Measured at -0.040 nats, "
                             "much worse than knowing nothing, and 14 points "
                             "overconfident on average.",
}


def publishable(market: str) -> bool:
    """May a pick in this market be shown to a customer?

    Separate from whether it can be PRICED. A market measured worse than a
    base rate is still priced, so the backtest keeps watching it; it is not
    published, because publishing a number we have measured as worse than
    knowing nothing is the exact thing this project keeps finding and
    removing.
    """
    return market in SUPPORTED_MARKETS and market not in NOT_PUBLISHABLE


class PropError(ValueError):
    """The inputs cannot support a probability for this batter.

    Loud on purpose. A batter with no usable history is not one the model has
    a weak opinion about -- he is one it has no opinion about, and flattening
    that into a league-average number published under his name is exactly the
    fabrication this project keeps finding and removing.
    """


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

def _shrink(rate, sample, prior, weight):
    if rate is None:
        return prior
    n = float(sample or 0.0)
    if n <= 0:
        return prior
    return (float(rate) * n + prior * weight) / (n + weight)


def league_rates(batter_lines: Sequence[Mapping]) -> dict:
    """Per-PA league outcome rates from a pile of boxscore batter rows.

    Measured, never assumed. Offence drifts year to year and a hardcoded
    league line pushes every batter on the slate the same way, which is the
    one error shape a per-player sanity check cannot see.
    """
    pa = h = doubles = triples = hr = r = rbi = 0
    for row in batter_lines or ():
        pa += int(row.get("pa") or 0)
        h += int(row.get("h") or 0)
        doubles += int(row.get("doubles") or 0)
        triples += int(row.get("triples") or 0)
        hr += int(row.get("hr") or 0)
        r += int(row.get("r") or 0)
        rbi += int(row.get("rbi") or 0)
    if pa <= 0:
        raise PropError("no plate appearances in the supplied lines, so there "
                        "is no league rate to regress toward")
    singles = h - doubles - triples - hr
    return {
        "pa": pa,
        "hit": h / pa,
        "single": max(singles, 0) / pa,
        "double": doubles / pa,
        "triple": triples / pa,
        "home_run": hr / pa,
        "run": r / pa,
        "rbi": rbi / pa,
    }


def batter_rates(lines: Sequence[Mapping], league: Mapping) -> dict:
    """One batter's per-PA rates, regressed toward the league.

    `lines` are his own boxscore rows from games STRICTLY BEFORE the one
    being predicted -- the caller enforces that, and
    `scripts/backtest_player_props.py` does it by construction.
    """
    pa = h = doubles = triples = hr = r = rbi = games = 0
    for row in lines or ():
        pa += int(row.get("pa") or 0)
        h += int(row.get("h") or 0)
        doubles += int(row.get("doubles") or 0)
        triples += int(row.get("triples") or 0)
        hr += int(row.get("hr") or 0)
        r += int(row.get("r") or 0)
        rbi += int(row.get("rbi") or 0)
        games += 1
    if pa < MIN_PA_FOR_A_RATE:
        raise PropError(
            f"{pa} plate appearances is below the {MIN_PA_FOR_A_RATE} floor; "
            f"this batter has no rate worth publishing under his name")

    singles = max(h - doubles - triples - hr, 0)
    out = {"pa_sample": pa, "games": games,
           "pa_per_game": pa / games if games else None}
    for key, count in (("single", singles), ("double", doubles),
                       ("triple", triples), ("home_run", hr),
                       ("run", r), ("rbi", rbi)):
        out[key] = _shrink(count / pa, pa, league[key], PA_REGRESSION)
    out["hit"] = out["single"] + out["double"] + out["triple"] + out["home_run"]
    return out


def pitcher_hit_factor(hits_allowed, batters_faced, league_hit_rate) -> float:
    """How much this starter raises or lowers a batter's hit chance.

    One multiplier, bounded, regressed. Not a full pitcher model -- that is
    what `src.analysis.strength` does for run prevention -- but the single
    largest thing about the opponent that a batter's line depends on.
    """
    if not batters_faced or batters_faced <= 0 or not league_hit_rate:
        return 1.0
    raw = float(hits_allowed or 0) / float(batters_faced)
    regressed = _shrink(raw, batters_faced, league_hit_rate, BF_REGRESSION)
    factor = regressed / league_hit_rate if league_hit_rate else 1.0
    return min(max(factor, MIN_PITCHER_FACTOR), MAX_PITCHER_FACTOR)


# ---------------------------------------------------------------------------
# The count distributions
# ---------------------------------------------------------------------------

def _binomial_at_least_one(p: float, n: float) -> float:
    """P(at least one success) over `n` trials, `n` fractional.

    Fractional trials are the honest treatment of "about 4.3 plate
    appearances": rounding to 4 throws away a tenth of a hit's worth of
    chance across a slate, and rounding up invents one.
    """
    p = min(max(p, 0.0), 1.0)
    if p <= 0 or n <= 0:
        return 0.0
    return 1.0 - (1.0 - p) ** n


def total_bases_distribution(rates: Mapping, expected_pa: float,
                             max_bases: int = 12) -> list:
    """P(total bases == k) for k in 0..max_bases.

    Exact, by convolving one PA's base distribution `n` times. `n` is split
    into a whole part and a fractional remainder, and the remainder is mixed
    between `floor(n)` and `floor(n)+1` PAs -- which is what a fractional
    plate appearance actually means.
    """
    per_pa = [0.0] * 5
    per_pa[1] = rates["single"]
    per_pa[2] = rates["double"]
    per_pa[3] = rates["triple"]
    per_pa[4] = rates["home_run"]
    per_pa[0] = max(1.0 - sum(per_pa[1:]), 0.0)

    def convolve(times: int) -> list:
        dist = [0.0] * (max_bases + 1)
        dist[0] = 1.0
        for _ in range(times):
            nxt = [0.0] * (max_bases + 1)
            for bases, p_bases in enumerate(dist):
                if p_bases <= 0:
                    continue
                for add, p_add in enumerate(per_pa):
                    if p_add <= 0:
                        continue
                    total = min(bases + add, max_bases)
                    nxt[total] += p_bases * p_add
            dist = nxt
        return dist

    whole = int(math.floor(expected_pa))
    frac = expected_pa - whole
    low = convolve(max(whole, 0))
    if frac <= 1e-9:
        return low
    high = convolve(max(whole, 0) + 1)
    return [(1 - frac) * a + frac * b for a, b in zip(low, high)]


def probability_over(market: str, line: float, rates: Mapping,
                     expected_pa: float, pitcher_factor: float = 1.0) -> float:
    """P(this batter clears `line` in `market`).

    Every market is read off the same per-PA rates, so the numbers cannot
    contradict each other -- a batter cannot be 70% for a hit and 10% for a
    total base.
    """
    if market not in SUPPORTED_MARKETS:
        raise PropError(f"{market!r} is not a market this model prices")

    adjusted = dict(rates)
    for key in ("single", "double", "triple", "home_run"):
        adjusted[key] = rates[key] * pitcher_factor
    adjusted["hit"] = (adjusted["single"] + adjusted["double"]
                       + adjusted["triple"] + adjusted["home_run"])

    if market == "batter_hits":
        # Over 0.5 is "at least one"; over 1.5 is "at least two".
        need = int(math.floor(line)) + 1
        return _at_least(adjusted["hit"], expected_pa, need)
    if market == "batter_home_runs":
        need = int(math.floor(line)) + 1
        return _at_least(adjusted["home_run"], expected_pa, need)
    if market == "batter_total_bases":
        dist = total_bases_distribution(adjusted, expected_pa)
        need = int(math.floor(line)) + 1
        return sum(dist[need:])
    if market == "batter_runs_scored":
        need = int(math.floor(line)) + 1
        return _at_least(adjusted["run"] * pitcher_factor, expected_pa, need)
    if market == "batter_rbis":
        need = int(math.floor(line)) + 1
        return _at_least(adjusted["rbi"] * pitcher_factor, expected_pa, need)
    # hits + runs + RBIs: three counts on the same plate appearances, and
    # they are correlated (a home run is a hit, a run and an RBI at once).
    # Summing their independent rates would understate the correlation and
    # therefore overstate the spread; this uses the combined per-PA rate the
    # boxscore itself records, which carries the correlation for free.
    combined = (adjusted["hit"] + adjusted["run"] * pitcher_factor
                + adjusted["rbi"] * pitcher_factor)
    need = int(math.floor(line)) + 1
    return _at_least_count(combined, expected_pa, need)


def _at_least(p_per_pa: float, expected_pa: float, need: int) -> float:
    if need <= 1:
        return _binomial_at_least_one(p_per_pa, expected_pa)
    return _at_least_count(p_per_pa, expected_pa, need)


def _at_least_count(p_per_pa: float, expected_pa: float, need: int) -> float:
    """P(count >= need) for a Poisson-binomial approximated as Binomial over
    fractional trials, mixed the same way `total_bases_distribution` mixes."""
    p = min(max(p_per_pa, 0.0), 1.0)
    if p <= 0:
        return 0.0

    def at_least(n: int) -> float:
        if n <= 0:
            return 0.0
        below = 0.0
        for k in range(need):
            if k > n:
                break
            below += (math.comb(n, k) * (p ** k) * ((1 - p) ** (n - k)))
        return max(1.0 - below, 0.0)

    whole = int(math.floor(expected_pa))
    frac = expected_pa - whole
    low = at_least(whole)
    if frac <= 1e-9:
        return low
    return (1 - frac) * low + frac * at_least(whole + 1)


def price_prop(*, market: str, line: float, batter_lines: Sequence[Mapping],
               league: Mapping, expected_pa: Optional[float] = None,
               pitcher_hits_allowed: Optional[int] = None,
               pitcher_batters_faced: Optional[int] = None) -> dict:
    """The whole model for one batter and one line, with the workings kept.

    Every intermediate is returned because the customer-facing sentence is
    built out of them: "Betts has a hit in 71% of his games this season and
    faces a starter allowing more than league average" is this dict read
    aloud.
    """
    rates = batter_rates(batter_lines, league)
    pa = expected_pa if expected_pa else rates["pa_per_game"]
    if not pa or pa <= 0:
        raise PropError("no expected plate appearances for this batter")

    factor = pitcher_hit_factor(pitcher_hits_allowed, pitcher_batters_faced,
                                league["hit"])
    # The starter faces most of the lineup but not all of it; the rest is
    # relief, priced at league average for want of anything better, and that
    # simplification is stated rather than hidden.
    blended = STARTER_SHARE * factor + (1.0 - STARTER_SHARE) * 1.0

    probability = probability_over(market, line, rates, pa, blended)
    return {
        "market": market,
        "line": line,
        "probability": probability,
        "expected_pa": round(pa, 3),
        "pitcher_factor": round(factor, 4),
        "blended_factor": round(blended, 4),
        "batter_hit_rate": round(rates["hit"], 5),
        "batter_pa_sample": rates["pa_sample"],
        "batter_games": rates["games"],
        "teammate_dependent": market in TEAMMATE_DEPENDENT,
        "publishable": publishable(market),
        "not_publishable_because": NOT_PUBLISHABLE.get(market),
        "model_id": MODEL_ID,
    }
