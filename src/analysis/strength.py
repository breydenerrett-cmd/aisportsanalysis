"""A run-scoring model for one baseball game, written out in full.

WHY THIS EXISTS
---------------
Until now every customer-facing number in this product was derived from the
betting market itself: the de-vigged consensus, the best available price, the
gap between them. That is line-shopping. It answers "where is this bet
cheapest" and it can never answer "who should I bet", because a number
derived from the price cannot disagree with the price.

The product needs an opinion. This module is the opinion: two Poisson means,
one per team, built from things that actually happened -- how many runs each
club has scored and allowed, and how the two starting pitchers have pitched.
From those two numbers every market this product quotes falls out at once:
the moneyline, the run line, the total.

NOTHING IN HERE IS FITTED
-------------------------
Every constant below is either a published baseball constant or a quantity
measured from the point-in-time store at call time. Not one was chosen by
looking at how it scored. That is deliberate and it is the model's main
defence: a model with no free parameters cannot be overfitted, so its
out-of-sample behaviour is its only behaviour. `scripts/backtest_card.py`
measures it; whatever that measurement says is what this model is worth, and
the number is published either way.

THE ARITHMETIC, IN ORDER
------------------------
1. LEAGUE CONTEXT. `league_runs_per_game` is measured from the same
   point-in-time store the features come from -- never a hardcoded 4.5 --
   because run scoring drifts year to year and a stale constant silently
   biases every game on the slate in the same direction.

2. RUN PREVENTION IS SPLIT AT THE STARTER. A team's season
   `runs_allowed_pg` blends its rotation and its bullpen. Tonight's starter
   is not the team's average starter, so the model rebuilds the defensive
   rate as a weighted average of the two innings blocks:

       runs_allowed = share * starter_rate + (1 - share) * bullpen_rate

   `share` is the starter's own innings-per-start over nine. `starter_rate`
   is FIP put on the runs-allowed scale (see FIP_TO_RA_SCALE). `bullpen_rate`
   is the team's season rate, standing in for the relievers -- imperfect, and
   named as imperfect, but it is a real observed number and it is the only
   bullpen rate that exists point-in-time here.

3. OFFENCE MEETS DEFENCE by the odds-ratio rule that Bill James' log5 uses
   for winning percentages, applied to runs:

       expected_runs = offence * defence / league_average

   Two average clubs produce the league average; a good offence against a bad
   defence produces more than either alone. This is the standard construction
   and it is not novel here.

4. HOME FIELD is added to the home club's mean as a fixed run credit.

5. THE JOINT DISTRIBUTION is the outer product of two independent Poissons,
   summed over the outcomes each market cares about. Baseball has no ties, so
   the diagonal is redistributed to the two sides in proportion to their
   means -- the standard treatment, and the honest one, since an extra-inning
   game is decided by the same two clubs.

WHERE THIS MODEL IS WRONG, STATED UP FRONT
------------------------------------------
* Runs are overdispersed relative to Poisson: real innings cluster (a walk
  raises the chance of the next run, a Poisson does not know that). The
  practical effect is that this model puts slightly too little probability in
  the tails, so it will tend to shade blowout run lines and extreme totals
  toward the middle. `MARGIN_INFLATION` exists to name that, not to hide it.
* `bullpen_rate` is the team's whole-season allowance, which includes the
  starters. Using it for relief innings double-counts rotation quality a
  little.
* Lineups are ignored entirely. A club resting four regulars is priced as its
  season self.
* Park and weather are ignored. Coors Field is priced like Petco.

None of these are secret and none of them are fixed by the model getting a
bigger number attached to it. They are the reasons a published pick from this
model is a read and not a promise, and they belong in the customer-facing
copy as plainly as they are written here.

Pure. stdlib only, no I/O -- every input arrives as an argument, which is what
lets `scripts/backtest_card.py` run it over three seasons without touching a
network or a clock.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional

# ---------------------------------------------------------------------------
# Published constants. None fitted, each with its source.
# ---------------------------------------------------------------------------

# The home club's run credit. League-wide MLB home advantage has sat near a
# .540 home winning percentage for decades, which is a little over two tenths
# of a run per game. Held fixed rather than estimated per park, because a
# per-park estimate on one season of data is mostly noise and this is the term
# a reader is most likely to sanity-check.
HOME_FIELD_RUNS = 0.20

# FIP is published on the ERA scale (earned runs per nine). Teams allow more
# RUNS than EARNED runs -- unearned runs are roughly 8% of the total in the
# modern game -- so a FIP has to be lifted onto the runs-allowed scale before
# it can be averaged against a team's runs-allowed-per-game.
FIP_TO_RA_SCALE = 1.08

# A start is nine innings' worth of run prevention split between the starter
# and everyone after him. Nine is the divisor, not the starter's own total,
# because the remaining share has to go somewhere.
INNINGS_PER_GAME = 9.0

# A starter with a handful of innings has a FIP that is mostly noise, so the
# rate is pulled toward the league average by a fixed prior weight measured in
# innings. 50 is roughly a third of a full season's workload -- enough that an
# established starter is barely moved and an April call-up is heavily
# regressed. Fixed in advance; never tuned against results.
STARTER_REGRESSION_INNINGS = 50.0

# The same shrink for team rates, in games. A club 20 games into a season has
# a runs-scored rate that is still substantially luck.
TEAM_REGRESSION_GAMES = 25.0

# Poisson understates the spread of real run margins. This widens both means
# symmetrically before the joint is formed, which fattens the tails without
# moving the expected margin. 1.0 would be pure Poisson. Set at 1.0 -- i.e.
# OFF -- until `scripts/backtest_card.py` measures what it should be out of
# sample; a correction invented at the same time as the model is a fitted
# parameter wearing a constant's clothes.
MARGIN_INFLATION = 1.0

# The joint is summed over this many runs per side. A 25-run game is a
# once-a-decade event and the tail beyond it contributes less than 1e-9.
MAX_RUNS = 26

# Floors and ceilings on the two means, so a corrupt or absurd input can never
# produce a probability the rest of the system would treat as certainty.
MIN_TEAM_RUNS = 1.5
MAX_TEAM_RUNS = 12.0

MODEL_ID = "run_expectancy_poisson_v1"
MODEL_BASIS = (
    "Two Poisson run means -- one per club -- built from season runs scored "
    "and allowed, tonight's starting pitchers, and a fixed home-field credit. "
    "Every market is read off the same joint distribution. No parameter in it "
    "was fitted to results."
)


class StrengthError(ValueError):
    """Raised when the inputs cannot support a model line at all.

    Deliberately loud. A game with no team rates is not a game the model has
    a weak opinion about -- it is a game the model has no opinion about, and
    the difference must never be flattened into a 50/50 that then looks like
    a considered call.
    """


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def league_runs_per_game(rows) -> Optional[float]:
    """Average runs per team per game over `rows`, or None if there are none.

    `rows` are point-in-time feature dicts (anything carrying
    `away_runs_scored_pg` / `home_runs_scored_pg`). Measured rather than
    assumed: 2026 is not 2019 and a hardcoded league mean pushes every
    expected-runs figure on the slate the same way, which is the one error
    shape a slate-wide sanity check cannot see.
    """
    vals = []
    for row in rows or ():
        for key in ("away_runs_scored_pg", "home_runs_scored_pg"):
            v = row.get(key)
            if isinstance(v, (int, float)) and v > 0:
                vals.append(float(v))
    if not vals:
        return None
    return sum(vals) / len(vals)


def _shrink(rate: Optional[float], sample: Optional[float],
            prior: float, prior_weight: float) -> Optional[float]:
    """`rate` pulled toward `prior` by `prior_weight` units of imaginary
    sample. None in, None out -- a missing rate is never invented."""
    if rate is None or not isinstance(rate, (int, float)):
        return None
    n = float(sample or 0.0)
    if n <= 0:
        return prior
    return (float(rate) * n + prior * prior_weight) / (n + prior_weight)


def _starter_runs_per_nine(fip, innings, league_ra_per_nine) -> Optional[float]:
    """One starter's expected runs allowed per nine innings.

    FIP first, ERA never: FIP is built from strikeouts, walks and home runs
    and so is far less contaminated by the defence behind him, which matters
    because we are about to combine it with the team's own defensive rate and
    would otherwise count the same fielders twice.
    """
    if fip is None or not isinstance(fip, (int, float)):
        return None
    raw = float(fip) * FIP_TO_RA_SCALE
    return _shrink(raw, innings, league_ra_per_nine, STARTER_REGRESSION_INNINGS)


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def run_means(features: Mapping, *, league_rpg: float) -> dict:
    """The two Poisson means for one game, with every intermediate kept.

    `features` is a point-in-time feature dict -- `src.pipeline.features`
    output, or the equivalent `teams`/`starters` dossier sections flattened
    together. Every intermediate quantity is returned alongside the answer
    because the customer-facing sentence is built out of them: "San Diego
    scores 4.9 and allows 3.9" is this dict, read aloud.
    """
    if not league_rpg or league_rpg <= 0:
        raise StrengthError("no league run rate: the model cannot scale "
                            "offence against defence without one")

    away_off = _shrink(features.get("away_runs_scored_pg"),
                       features.get("away_games_played"),
                       league_rpg, TEAM_REGRESSION_GAMES)
    home_off = _shrink(features.get("home_runs_scored_pg"),
                       features.get("home_games_played"),
                       league_rpg, TEAM_REGRESSION_GAMES)
    away_def = _shrink(features.get("away_runs_allowed_pg"),
                       features.get("away_games_played"),
                       league_rpg, TEAM_REGRESSION_GAMES)
    home_def = _shrink(features.get("home_runs_allowed_pg"),
                       features.get("home_games_played"),
                       league_rpg, TEAM_REGRESSION_GAMES)

    if None in (away_off, home_off, away_def, home_def):
        raise StrengthError(
            "this game has no team scoring rates on either side, so there is "
            "nothing to build a run expectation from")

    # Starters, when known. `sp_known` false means no probable was posted or
    # the log is empty; the team's blended rate then stands for the whole
    # game, and `starter_known` in the result says so out loud so the
    # customer-facing sentence can decline to mention a pitcher.
    away_sp = _starter_runs_per_nine(
        features.get("away_sp_fip"), features.get("away_sp_innings"),
        league_rpg)
    home_sp = _starter_runs_per_nine(
        features.get("home_sp_fip"), features.get("home_sp_innings"),
        league_rpg)

    away_share = _innings_share(features.get("away_sp_ip_per_start"))
    home_share = _innings_share(features.get("home_sp_ip_per_start"))

    # Defence, rebuilt around tonight's starter. When the starter is unknown
    # the share collapses to zero and this is exactly the team rate.
    away_defence = _blend(away_def, away_sp, away_share)
    home_defence = _blend(home_def, home_sp, home_share)

    # Odds-ratio: offence against defence, scaled by the league.
    away_mean = away_off * home_defence / league_rpg
    home_mean = home_off * away_defence / league_rpg + HOME_FIELD_RUNS

    away_mean = min(max(away_mean, MIN_TEAM_RUNS), MAX_TEAM_RUNS)
    home_mean = min(max(home_mean, MIN_TEAM_RUNS), MAX_TEAM_RUNS)

    return {
        "away_mean": away_mean,
        "home_mean": home_mean,
        "away_offence": away_off,
        "home_offence": home_off,
        "away_defence": away_defence,
        "home_defence": home_defence,
        "away_team_defence": away_def,
        "home_team_defence": home_def,
        "away_starter_rate": away_sp,
        "home_starter_rate": home_sp,
        "away_starter_share": away_share,
        "home_starter_share": home_share,
        "away_starter_known": away_sp is not None,
        "home_starter_known": home_sp is not None,
        "league_runs_per_game": league_rpg,
        "home_field_runs": HOME_FIELD_RUNS,
        "model_id": MODEL_ID,
    }


def _innings_share(ip_per_start) -> float:
    """How much of a nine-inning game tonight's starter is expected to own.

    Zero when unknown -- which makes `_blend` return the team rate untouched,
    the correct behaviour for a game with no posted probable.
    """
    if ip_per_start is None or not isinstance(ip_per_start, (int, float)):
        return 0.0
    return min(max(float(ip_per_start) / INNINGS_PER_GAME, 0.0), 1.0)


def _blend(team_rate: float, starter_rate: Optional[float], share: float) -> float:
    if starter_rate is None or share <= 0:
        return team_rate
    return share * starter_rate + (1.0 - share) * team_rate


# ---------------------------------------------------------------------------
# The joint distribution, and every market read off it
# ---------------------------------------------------------------------------

def _poisson_pmf(mean: float, k: int) -> float:
    return math.exp(-mean + k * math.log(mean) - math.lgamma(k + 1))


def outcome_grid(away_mean: float, home_mean: float) -> list:
    """`grid[a][h]` = P(away scores a AND home scores h), ties redistributed.

    Two independent Poissons. Independence is an assumption, not a fact --
    a pitchers' duel suppresses both sides at once -- and it is the second
    place after overdispersion where this model is knowably simplified.

    THE TIE ROW IS NOT DROPPED. Baseball plays extra innings, so P(a == h)
    has to go somewhere; splitting it in proportion to the two means is the
    standard treatment and keeps the grid summing to one. Dropping it
    instead would quietly renormalise every downstream probability upward.
    """
    a_mean = away_mean * MARGIN_INFLATION
    h_mean = home_mean * MARGIN_INFLATION
    away_pmf = [_poisson_pmf(a_mean, k) for k in range(MAX_RUNS + 1)]
    home_pmf = [_poisson_pmf(h_mean, k) for k in range(MAX_RUNS + 1)]

    grid = [[a * h for h in home_pmf] for a in away_pmf]

    # Extra innings: the tie mass goes to the two clubs in proportion to their
    # means, added one run above the tie so the margin is decided by one run,
    # which is how an extra-inning game almost always ends.
    total = a_mean + h_mean
    home_share = (h_mean / total) if total > 0 else 0.5
    for k in range(MAX_RUNS + 1):
        tie = grid[k][k]
        if tie <= 0:
            continue
        grid[k][k] = 0.0
        if k + 1 <= MAX_RUNS:
            grid[k][k + 1] += tie * home_share
            grid[k + 1][k] += tie * (1.0 - home_share)
        else:  # the very top corner; keep the mass rather than lose it
            grid[k][k] = tie
    return grid


def market_probabilities(away_mean: float, home_mean: float,
                         *, run_line: float = 1.5,
                         totals: Optional[list] = None) -> dict:
    """Every market this product quotes, from one joint distribution.

    One grid, read several ways -- so the moneyline, the run line and the
    total can never disagree with each other. A product that prices those
    three separately can publish "take the favourite" and "take the underdog
    +1.5" and "take the under" on the same game with no internal
    contradiction to trip over. This cannot.
    """
    grid = outcome_grid(away_mean, home_mean)
    totals = list(totals or ())

    # FOUR RUN-LINE QUANTITIES, EACH NAMED FOR EXACTLY WHAT IT IS. An earlier
    # draft carried two -- `p_home_cover` and `p_away_cover` -- and neither
    # name said whether the side was giving the runs or getting them, which
    # is the whole question. `margin` below is HOME minus AWAY throughout.
    #
    #   home -L covers when margin >  L      (home wins by more than L)
    #   home +L covers when margin > -L      (home loses by less than L)
    #   away -L covers when margin < -L      (away wins by more than L)
    #   away +L covers when margin <  L      (away loses by less than L)
    #
    # The two complementary pairs must each sum to 1, and `market_probabilities`
    # is tested on exactly that.
    p_home = 0.0
    p_home_minus = 0.0
    p_home_plus = 0.0
    p_away_minus = 0.0
    p_away_plus = 0.0
    over = {t: 0.0 for t in totals}
    exp_total = 0.0

    for a in range(MAX_RUNS + 1):
        row = grid[a]
        for h in range(MAX_RUNS + 1):
            p = row[h]
            if p <= 0:
                continue
            margin = h - a
            if margin > 0:
                p_home += p
            if margin > run_line:
                p_home_minus += p
            if margin > -run_line:
                p_home_plus += p
            if margin < -run_line:
                p_away_minus += p
            if margin < run_line:
                p_away_plus += p
            total_runs = a + h
            exp_total += p * total_runs
            for t in totals:
                if total_runs > t:
                    over[t] += p

    return {
        "p_home": p_home,
        "p_away": 1.0 - p_home,
        "run_line": run_line,
        "p_home_minus": p_home_minus,
        "p_home_plus": p_home_plus,
        "p_away_minus": p_away_minus,
        "p_away_plus": p_away_plus,
        "expected_total": exp_total,
        "p_over": over,
        "expected_margin": home_mean - away_mean,
    }


def run_line_probability(line: Mapping, side: str, *, underdog: bool) -> float:
    """One side's chance of covering the standard run line.

    A favourite covers by winning by more than the line; an underdog covers
    by losing by less than it, or winning outright. Reading both off the same
    joint distribution is what stops a card publishing a moneyline and a run
    line that contradict each other on one game.
    """
    if side == "home":
        return line["p_home_plus"] if underdog else line["p_home_minus"]
    return line["p_away_plus"] if underdog else line["p_away_minus"]


def model_line(features: Mapping, *, league_rpg: float,
               run_line: float = 1.5, totals: Optional[list] = None) -> dict:
    """`run_means` and `market_probabilities` in one call -- the whole model.

    Raises `StrengthError` rather than returning a 50/50 when the inputs are
    not there. See that class's docstring for why the distinction is
    load-bearing.
    """
    means = run_means(features, league_rpg=league_rpg)
    probs = market_probabilities(means["away_mean"], means["home_mean"],
                                 run_line=run_line, totals=totals)
    out = dict(means)
    out.update(probs)
    return out
