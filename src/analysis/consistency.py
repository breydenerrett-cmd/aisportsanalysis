"""Is a book's own board internally consistent? A detector that needs no model.

THE IDEA
--------
A book quoting one game quotes three things: a moneyline, a run line, and a
total. Those are not three independent opinions. They are three different
questions about ONE underlying distribution of runs, and a book that has a
coherent view of the game must answer them coherently.

So: take the book's moneyline and its total, solve for the two run means
that reproduce both, and then ask what run line those means imply. Compare
that to the run line the book is actually offering.

When they disagree, at least one of the book's own three prices is wrong
RELATIVE TO ITS OWN OTHER TWO. That is a much weaker claim than "the market
is wrong", and it is why this is worth building: it does not require our
model to be better than anyone. It requires only arithmetic, applied to
numbers the book published itself.

WHY THIS MIGHT BE SOMEWHERE TO LOOK
-----------------------------------
The full-game moneyline is the most-priced, most-limited, most-watched
market in baseball. The run line and the total get less attention, and on
many books the derivative lines are generated from the main line by a rule
rather than repriced independently. A rule that is roughly right on an
average game is systematically wrong on unusual ones -- a very high total, a
very short favourite, a game where the two clubs' scoring rates differ far
more than their win probability suggests.

If that is happening, it shows up here as a structured disagreement, not a
random one, and it shows up BEFORE anyone needs to know who won.

WHAT THIS IS NOT
----------------
It is not an edge and it is not evidence of one. A disagreement means one of
three prices is out of line with the other two; it says nothing about which,
and nothing about whether the book's whole board is closer to the truth than
our reading of it. Turning this into a bet requires a separate,
pre-registered forward test that this module deliberately does not contain.

THE SOLVE
---------
Two equations, two unknowns, and they are close to separable: the SUM of the
run means drives the total, the DIFFERENCE drives the moneyline. Alternating
one-dimensional bisections converge in a handful of passes and cannot
oscillate the way a raw 2-D Newton step can on the flat regions near a
heavy favourite.

Every probability in and out is DE-VIGGED. Comparing a book's raw quoted
probabilities would find "inconsistency" in every game on every board,
because the vig makes each pair sum above one -- the detector would be
measuring the hold and calling it a signal.

Pure. stdlib only.
"""

from __future__ import annotations

import math
from typing import Optional

from src.analysis import strength
from src.core import odds as odds_math

# Search bounds on a team's expected runs. Wider than `strength`'s own
# clamps, because this solver is fitting a BOOK's implied view and must be
# able to represent a board that is more extreme than anything the run model
# would produce on its own -- clamping here would hide exactly the games
# most likely to be mispriced.
MIN_MEAN = 0.8
MAX_MEAN = 14.0

# Convergence: probabilities are quoted to about a tenth of a point, so
# solving past 1e-5 is solving noise.
TOLERANCE = 1e-5
MAX_PASSES = 40
BISECTION_STEPS = 60

# A pair of quotes whose de-vigged probabilities cannot be read, or whose
# book sum is implausible, is dropped rather than repaired. Same floor and
# same reason as src/analysis/derivative_prices.py's.
MIN_TWO_WAY_BOOKSUM = 0.98

# The standard run line. A book quoting an alternate is answering a
# different question and is not compared here.
STANDARD_RUN_LINE = 1.5


class ConsistencyError(ValueError):
    """The three markets could not be read as one game."""


def _devig_pair(price_a, price_b, method: str = "proportional") -> Optional[tuple]:
    """De-vigged (p_a, p_b), or None when the pair is unusable.

    THE METHOD IS A PARAMETER BECAUSE IT IS A HYPOTHESIS. Proportional
    de-vigging splits the hold in proportion to each side's raw probability,
    which is the simplest rule and is known to be biased where the two
    prices are very asymmetric -- a book takes a larger margin on the
    longshot than the favourite (the favourite-longshot bias), and
    proportional splitting assumes it does not.

    A run line at -1.5 is exactly such a market. If our residual
    disagreement with the books is really a de-vig artefact rather than a
    distribution artefact, changing this argument will show it, and the
    answer matters far beyond this module: proportional is what
    `src.analysis.prices` uses for every number the product publishes.
    """
    try:
        raw = (odds_math.american_to_probability(price_a)
               + odds_math.american_to_probability(price_b))
    except (odds_math.OddsError, TypeError, ValueError, ZeroDivisionError):
        return None
    if raw < MIN_TWO_WAY_BOOKSUM:
        return None
    try:
        return odds_math.devig_two_way(price_a, price_b, method=method)
    except odds_math.OddsError:
        return None


def _p_home(sum_means: float, diff: float, dispersion=None, family=None) -> float:
    """P(home wins) for means with this sum and difference."""
    home = (sum_means + diff) / 2.0
    away = (sum_means - diff) / 2.0
    if home <= 0 or away <= 0:
        return 0.0 if home <= 0 else 1.0
    return strength.market_probabilities(
        away, home, dispersion=dispersion, family=family)["p_home"]


def _p_over(sum_means: float, diff: float, total_line: float,
            dispersion=None, family=None) -> float:
    home = (sum_means + diff) / 2.0
    away = (sum_means - diff) / 2.0
    if home <= 0 or away <= 0:
        return 0.0
    probs = strength.market_probabilities(
        away, home, totals=[total_line], dispersion=dispersion, family=family)
    return probs["p_over"][total_line]


def _solve_diff(sum_means: float, target_p_home: float,
                dispersion=None, family=None) -> float:
    """The mean difference that reproduces `target_p_home` at this sum."""
    lo, hi = -(sum_means - 2 * MIN_MEAN), (sum_means - 2 * MIN_MEAN)
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        if _p_home(sum_means, mid, dispersion, family) < target_p_home:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _solve_sum(diff: float, target_p_over: float, total_line: float,
               dispersion=None, family=None) -> float:
    """The mean sum that reproduces `target_p_over` at this difference."""
    lo, hi = max(2 * MIN_MEAN, abs(diff) + 2 * MIN_MEAN), 2 * MAX_MEAN
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        if _p_over(mid, diff, total_line, dispersion, family) < target_p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def implied_means(p_home: float, p_over: float, total_line: float,
                  dispersion=None, family=None) -> dict:
    """The two run means a book's moneyline and total imply together.

    Alternating bisection: the sum drives the total, the difference drives
    the moneyline, and each pass tightens the other. Reports whether it
    actually converged rather than returning whatever it had at the last
    pass -- a solver that quietly returns a non-solution would turn every
    hard board into a fake "inconsistency".
    """
    if not (0.0 < p_home < 1.0) or not (0.0 < p_over < 1.0):
        # Worded without field names on purpose: tests/test_customer_language.py
        # scans src/ for snake_case inside sentences, because that is how a
        # payload key ends up rendered on a page. This message is for a
        # developer and it can say the same thing in words.
        raise ConsistencyError(
            f"a probability is outside (0, 1): home win {p_home}, "
            f"over {p_over}")

    sum_means = 2 * 4.5
    diff = 0.0
    converged = False
    for _ in range(MAX_PASSES):
        new_diff = _solve_diff(sum_means, p_home, dispersion, family)
        new_sum = _solve_sum(new_diff, p_over, total_line, dispersion, family)
        if (abs(new_diff - diff) < TOLERANCE
                and abs(new_sum - sum_means) < TOLERANCE):
            diff, sum_means = new_diff, new_sum
            converged = True
            break
        diff, sum_means = new_diff, new_sum

    home = (sum_means + diff) / 2.0
    away = (sum_means - diff) / 2.0
    return {
        "home_mean": home,
        "away_mean": away,
        "sum": sum_means,
        "diff": diff,
        "converged": converged,
        # The check that matters: do these means actually reproduce the two
        # inputs? Reported so a caller can refuse a bad solve rather than
        # trust `converged` alone.
        "refit_p_home": _p_home(sum_means, diff, dispersion, family),
        "refit_p_over": _p_over(sum_means, diff, total_line, dispersion, family),
    }


def check_board(*, home_ml, away_ml, total_line, over_price, under_price,
                home_rl_price, away_rl_price, home_rl_line=-STANDARD_RUN_LINE,
                run_line: float = STANDARD_RUN_LINE,
                dispersion=None, family=None,
                devig: str = "proportional") -> Optional[dict]:
    """One book, one instant, one game: does its own board hang together?

    Returns None -- not an exception -- when any leg is unusable, because a
    partial board is the normal case and a caller sweeping a season should
    not have to catch anything.

    `disagreement_points` is the headline: the book's own de-vigged run-line
    probability minus the one its moneyline and total imply, in probability
    points. Positive means the book is pricing the favourite's run line
    CHEAPER than its own other two markets say it should be.
    """
    ml = _devig_pair(away_ml, home_ml, devig)
    tot = _devig_pair(over_price, under_price, devig)
    rl = _devig_pair(away_rl_price, home_rl_price, devig)
    if ml is None or tot is None or rl is None:
        return None
    if total_line is None:
        return None
    try:
        total_line = float(total_line)
    except (TypeError, ValueError):
        return None
    # Only the standard line. An alternate run line is a different question
    # and comparing it here would manufacture disagreement out of the line.
    try:
        if abs(abs(float(home_rl_line)) - run_line) > 1e-9:
            return None
    except (TypeError, ValueError):
        return None

    p_home_ml = ml[1]
    p_over = tot[0]
    p_home_rl_book = rl[1]

    try:
        solved = implied_means(p_home_ml, p_over, total_line,
                               dispersion=dispersion, family=family)
    except ConsistencyError:
        return None
    if not solved["converged"]:
        return None
    if (abs(solved["refit_p_home"] - p_home_ml) > 1e-3
            or abs(solved["refit_p_over"] - p_over) > 1e-3):
        # The solve did not actually reproduce the inputs. That is a failed
        # measurement, not a finding about the book.
        return None

    probs = strength.market_probabilities(
        solved["away_mean"], solved["home_mean"], run_line=run_line,
        dispersion=dispersion, family=family)
    # `home_rl_line` is negative when the home club is laying the runs.
    home_is_favourite_on_rl = float(home_rl_line) < 0
    p_home_rl_implied = (probs["p_home_minus"] if home_is_favourite_on_rl
                         else probs["p_home_plus"])

    return {
        "p_home_moneyline": p_home_ml,
        "p_over": p_over,
        "total_line": total_line,
        "p_home_runline_book": p_home_rl_book,
        "p_home_runline_implied": p_home_rl_implied,
        "disagreement_points": (p_home_rl_book - p_home_rl_implied) * 100.0,
        "implied_home_mean": solved["home_mean"],
        "implied_away_mean": solved["away_mean"],
        "implied_total": solved["sum"],
        "implied_margin": solved["diff"],
        "home_lays_the_runs": home_is_favourite_on_rl,
    }
