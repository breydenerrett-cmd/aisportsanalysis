"""American odds, implied probability, and margin removal (de-vigging).

WHY THIS MODULE EXISTS
----------------------
A sportsbook's posted prices do not sum to 100% probability. A -150 / +130
moneyline implies 60.0% + 43.5% = 103.5%. That extra 3.5 points is the
bookmaker's margin (the "vig" or "overround") -- it is the house's fee, not a
statement about the game.

If you compare a model probability against RAW implied probability, you are
comparing against a number that has the house's fee baked into it. The error is
not uniform: it lands hardest on favorites, which is exactly where a betting
system is most likely to talk itself into a bad wager. Every "edge" computed
that way is overstated.

So: never compare a model probability to a raw implied probability. Remove the
margin first, then compare. Everything in this project routes through
`devig()` before any edge calculation.

All functions are pure, stdlib-only, and side-effect free.
"""

from __future__ import annotations

# Two-sided markets should sum to 1.0 after de-vigging. Floating point means
# "exactly 1.0" is not achievable, so callers verify within this tolerance.
SUM_TOLERANCE = 1e-9

# Guard rails on solver-based methods.
_SOLVER_ITERATIONS = 200
_SOLVER_TOLERANCE = 1e-12


class OddsError(ValueError):
    """Raised when an odds value or probability set is not usable."""


# ---------------------------------------------------------------------------
# American odds <-> decimal <-> implied probability
# ---------------------------------------------------------------------------

def american_to_decimal(american: float) -> float:
    """Convert American odds to decimal odds (total return per unit staked).

    >>> american_to_decimal(100)
    2.0
    >>> american_to_decimal(-200)
    1.5
    """
    a = _validate_american(american)
    if a > 0:
        return 1.0 + (a / 100.0)
    return 1.0 + (100.0 / abs(a))


def decimal_to_american(decimal: float) -> float:
    """Convert decimal odds back to American odds."""
    if decimal <= 1.0:
        raise OddsError(f"decimal odds must be > 1.0, got {decimal!r}")
    if decimal >= 2.0:
        return (decimal - 1.0) * 100.0
    return -100.0 / (decimal - 1.0)


def american_to_probability(american: float) -> float:
    """Convert American odds to RAW implied probability.

    This value INCLUDES the bookmaker's margin. It is not a fair probability
    and must not be compared against a model probability directly. Pass a full
    market through `devig()` first.
    """
    a = _validate_american(american)
    if a > 0:
        return 100.0 / (a + 100.0)
    return abs(a) / (abs(a) + 100.0)


def probability_to_american(probability: float) -> float:
    """Convert a probability to the American odds that would be fair for it.

    A fair price returns zero expected value at that probability, so this is
    the break-even line a bet must beat to be worth taking.
    """
    p = _validate_probability(probability)
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def probability_to_decimal(probability: float) -> float:
    """Convert a probability to fair decimal odds."""
    return 1.0 / _validate_probability(probability)


# ---------------------------------------------------------------------------
# Market-level margin measurement
# ---------------------------------------------------------------------------

def booksum(american_prices) -> float:
    """Total raw implied probability across every outcome in a market.

    A fair market sums to 1.0. Real markets sum above it. Returns the sum,
    sometimes called the "overround" or "book percentage".
    """
    prices = _validate_market(american_prices)
    return sum(american_to_probability(p) for p in prices)


def margin(american_prices) -> float:
    """The bookmaker's margin as a decimal fraction.

    A two-way market summing to 1.045 returns 0.045, i.e. a 4.5% margin.
    """
    return booksum(american_prices) - 1.0


def hold_percentage(american_prices) -> float:
    """The book's expected hold, as a percentage of total handle.

    This differs from `margin`. Margin is measured against a fair book (1.0);
    hold is the fraction of money wagered the book expects to keep, which is
    margin divided by the booksum.
    """
    total = booksum(american_prices)
    return (total - 1.0) / total * 100.0


# ---------------------------------------------------------------------------
# De-vigging
# ---------------------------------------------------------------------------

def devig(american_prices, method: str = "proportional"):
    """Remove the bookmaker's margin, returning fair probabilities summing to 1.

    Args:
        american_prices: iterable of American odds, one per market outcome.
            Both sides of a moneyline, both sides of a total, etc.
        method: one of "proportional", "power", "shin", "additive".

    Returns:
        list of floats summing to 1.0 (within SUM_TOLERANCE), in input order.

    The four methods differ in HOW they distribute the margin removal, and the
    choice matters most on lopsided markets:

    - "proportional" (default): scale every outcome by the same factor. Simple,
      fast, and standard. It assumes the book applies its margin evenly, which
      slightly under-corrects heavy favorites.
    - "power": raise each probability to a common exponent. Removes more margin
      from longshots, which better matches observed favorite-longshot bias.
    - "shin": models the margin as protection against better-informed bettors.
      Generally considered the most accurate for two-way markets.
    - "additive": subtract the margin equally in absolute terms. Included for
      comparison; it can produce negative probabilities on lopsided books and
      is not recommended.

    Method choice is a real modeling decision. Compute edge under more than one
    and treat any "edge" that only survives under a single method as fragile.
    """
    prices = _validate_market(american_prices)
    raw = [american_to_probability(p) for p in prices]
    total = sum(raw)

    if total <= 0:
        raise OddsError("market probabilities sum to zero")

    normalizer = {
        "proportional": _devig_proportional,
        "power": _devig_power,
        "shin": _devig_shin,
        "additive": _devig_additive,
    }.get(method)

    if normalizer is None:
        raise OddsError(
            f"unknown de-vig method {method!r}; "
            "expected proportional, power, shin, or additive"
        )

    fair = normalizer(raw, total)

    # Any method that returns a non-probability has failed, not "mostly worked".
    for p in fair:
        if not (0.0 < p < 1.0):
            raise OddsError(
                f"de-vig method {method!r} produced an invalid probability {p!r}; "
                "this market is too lopsided for that method"
            )

    drift = abs(sum(fair) - 1.0)
    if drift > SUM_TOLERANCE:
        raise OddsError(
            f"de-vig method {method!r} produced probabilities summing to "
            f"{sum(fair)!r}, off by {drift!r}"
        )
    return fair


def devig_two_way(american_a: float, american_b: float, method: str = "proportional"):
    """De-vig a two-outcome market, returning (fair_a, fair_b)."""
    fair = devig([american_a, american_b], method=method)
    return fair[0], fair[1]


def _devig_proportional(raw, total):
    return [p / total for p in raw]


def _devig_additive(raw, total):
    excess = (total - 1.0) / len(raw)
    return [p - excess for p in raw]


def _devig_power(raw, total):
    """Find exponent k such that sum(p_i ** k) == 1, by bisection.

    Since every p_i < 1, raising to a larger exponent shrinks each term, so the
    sum decreases monotonically in k. That monotonicity is what makes bisection
    safe here.
    """
    if abs(total - 1.0) <= _SOLVER_TOLERANCE:
        return list(raw)

    low, high = 1e-6, 100.0

    def total_at(k):
        return sum(p ** k for p in raw)

    # Bracket the root before solving so a failure is explicit, not silent.
    if total_at(low) < 1.0 or total_at(high) > 1.0:
        raise OddsError("power method could not bracket a solution for this market")

    for _ in range(_SOLVER_ITERATIONS):
        mid = (low + high) / 2.0
        s = total_at(mid)
        if abs(s - 1.0) <= _SOLVER_TOLERANCE:
            break
        if s > 1.0:
            low = mid
        else:
            high = mid
    k = (low + high) / 2.0
    fair = [p ** k for p in raw]
    # Bisection lands very close; normalize away the last few ulps.
    s = sum(fair)
    return [p / s for p in fair]


def _devig_shin(raw, total):
    """Shin's method: solve for the insider proportion z, then invert.

    Shin models the margin as the book protecting itself against bettors who
    know more than it does. `z` is the implied fraction of informed money.
    Solved by bisection on z in [0, 1).
    """
    if abs(total - 1.0) <= _SOLVER_TOLERANCE:
        return list(raw)

    def fair_at(z):
        if z <= 0:
            return [p / total for p in raw]
        out = []
        for p in raw:
            disc = z * z + 4.0 * (1.0 - z) * (p * p) / total
            out.append((_sqrt(disc) - z) / (2.0 * (1.0 - z)))
        return out

    low, high = 0.0, 0.9999
    for _ in range(_SOLVER_ITERATIONS):
        mid = (low + high) / 2.0
        s = sum(fair_at(mid))
        if abs(s - 1.0) <= _SOLVER_TOLERANCE:
            break
        if s > 1.0:
            low = mid
        else:
            high = mid

    fair = fair_at((low + high) / 2.0)
    s = sum(fair)
    return [p / s for p in fair]


def _sqrt(x: float) -> float:
    if x < 0:
        raise OddsError(f"negative discriminant in Shin solver: {x!r}")
    return x ** 0.5


# ---------------------------------------------------------------------------
# Edge and expected value
# ---------------------------------------------------------------------------

def expected_value(model_probability: float, american_price: float) -> float:
    """Expected profit per 1.0 unit staked, at the given price.

    Positive means the bet is profitable in the long run IF the model
    probability is correct. That conditional is the whole game -- an
    uncalibrated model produces confident, meaningless EV numbers.
    """
    p = _validate_probability(model_probability)
    decimal = american_to_decimal(american_price)
    return (p * (decimal - 1.0)) - (1.0 - p)


def edge(model_probability: float, fair_probability: float) -> float:
    """Model probability minus DE-VIGGED market probability.

    `fair_probability` must already have the margin removed. Passing a raw
    implied probability here is the single most common way a betting model
    fools itself, so this function refuses to do the de-vigging for you --
    it cannot tell whether the value it received was already corrected.
    """
    p = _validate_probability(model_probability)
    q = _validate_probability(fair_probability)
    return p - q


def break_even_probability(american_price: float) -> float:
    """The win rate required to break even at this price, ignoring margin."""
    return american_to_probability(american_price)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_american(american) -> float:
    if isinstance(american, bool) or not isinstance(american, (int, float)):
        raise OddsError(f"American odds must be numeric, got {american!r}")
    a = float(american)
    if a != a:  # NaN
        raise OddsError("American odds must not be NaN")
    # American odds between -100 and +100 exclusive are not expressible; a
    # price of exactly +/-100 is even money and is valid.
    if -100.0 < a < 100.0:
        raise OddsError(
            f"American odds must be <= -100 or >= +100, got {a!r} "
            "(values inside that range are not valid American prices)"
        )
    return a


def _validate_probability(p) -> float:
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise OddsError(f"probability must be numeric, got {p!r}")
    p = float(p)
    if p != p:
        raise OddsError("probability must not be NaN")
    if not (0.0 < p < 1.0):
        raise OddsError(f"probability must be strictly between 0 and 1, got {p!r}")
    return p


def _validate_market(american_prices):
    prices = list(american_prices)
    if len(prices) < 2:
        raise OddsError(
            f"a market needs at least 2 outcomes to de-vig, got {len(prices)}"
        )
    return [_validate_american(p) for p in prices]
