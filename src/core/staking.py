"""Stake sizing: flat, Kelly, and fractional Kelly with hard caps.

WHY FLAT IS THE DEFAULT
-----------------------
Kelly sizing is optimal only if your probabilities are correct. That is a much
stronger assumption than it sounds.

A model that is 5 points overconfident does not lose 5% more with Kelly -- it
sizes up precisely on the bets it is most wrong about, so the errors compound
instead of averaging out. Full Kelly on a slightly overconfident model loses
money faster than flat staking on the same model.

Until a model has passed a real calibration check on held-out data, flat
staking is the honest choice. This module implements Kelly because it is the
right tool once calibration is proven, but `default_sizer()` returns flat and
every Kelly path is capped.

Nothing here places a bet or talks to a sportsbook. These are arithmetic
functions that return a stake fraction.
"""

from __future__ import annotations

from src.core.odds import american_to_decimal, expected_value

# No single wager may risk more than this share of bankroll, whatever the
# formula returns. Kelly on a mispriced longshot can suggest enormous stakes;
# this is the backstop that makes that impossible.
DEFAULT_MAX_FRACTION = 0.02

# Fractional Kelly multiplier. Quarter-Kelly is the common choice among people
# who bet for a living, precisely because it tolerates probability error.
DEFAULT_KELLY_FRACTION = 0.25

# Flat stake as a share of bankroll -- one "unit".
DEFAULT_FLAT_FRACTION = 0.01


class StakingError(ValueError):
    """Raised when a stake cannot be computed from the given inputs."""


def flat_stake(bankroll: float, fraction: float = DEFAULT_FLAT_FRACTION) -> float:
    """Stake a fixed share of bankroll, ignoring the size of the edge.

    Deliberately ignores edge. When probabilities are unproven, sizing by edge
    means sizing by the model's own confidence in itself, which is circular.
    """
    _validate_bankroll(bankroll)
    if not (0.0 < fraction <= 1.0):
        raise StakingError(f"flat fraction must be in (0, 1], got {fraction!r}")
    return bankroll * fraction


def kelly_fraction(model_probability: float, american_price: float) -> float:
    """Full Kelly stake as a fraction of bankroll.

    f* = (b*p - q) / b, where b is decimal profit per unit staked, p is win
    probability and q is 1 - p.

    Returns 0.0 when the bet has no positive expectation. Kelly never suggests
    betting a negative-EV price, so a zero here means "do not bet", not
    "bet small".
    """
    p = _validate_probability(model_probability)
    b = american_to_decimal(american_price) - 1.0
    if b <= 0:
        raise StakingError(f"price {american_price!r} implies no profit")
    q = 1.0 - p
    f = ((b * p) - q) / b
    return max(0.0, f)


def fractional_kelly(
    model_probability: float,
    american_price: float,
    kelly_multiplier: float = DEFAULT_KELLY_FRACTION,
    max_fraction: float = DEFAULT_MAX_FRACTION,
) -> float:
    """Kelly scaled down and hard-capped. The only Kelly path worth using live.

    Two independent protections: the multiplier shrinks the stake to tolerate
    probability error, and `max_fraction` caps the result no matter what the
    formula produced.
    """
    if not (0.0 < kelly_multiplier <= 1.0):
        raise StakingError(
            f"kelly multiplier must be in (0, 1], got {kelly_multiplier!r}"
        )
    if not (0.0 < max_fraction <= 1.0):
        raise StakingError(f"max fraction must be in (0, 1], got {max_fraction!r}")
    full = kelly_fraction(model_probability, american_price)
    return min(full * kelly_multiplier, max_fraction)


def kelly_stake(
    bankroll: float,
    model_probability: float,
    american_price: float,
    kelly_multiplier: float = DEFAULT_KELLY_FRACTION,
    max_fraction: float = DEFAULT_MAX_FRACTION,
) -> float:
    """Fractional Kelly expressed in currency rather than as a fraction."""
    _validate_bankroll(bankroll)
    return bankroll * fractional_kelly(
        model_probability, american_price,
        kelly_multiplier=kelly_multiplier, max_fraction=max_fraction,
    )


def size_bet(
    bankroll: float,
    model_probability: float,
    american_price: float,
    method: str = "flat",
    calibrated: bool = False,
    **kwargs,
) -> dict:
    """Size one bet and explain the decision.

    `calibrated` is not decoration. If a caller asks for Kelly while the model
    is still uncalibrated, this refuses and falls back to flat, recording why
    in the returned dict. Kelly on an uncalibrated model is the single fastest
    way to lose a bankroll while believing the maths is on your side.

    Returns a dict with the stake, the method actually used, the expected
    value, and any warnings -- so a report can show why a number came out the
    way it did rather than presenting a bare figure.
    """
    _validate_bankroll(bankroll)
    p = _validate_probability(model_probability)
    ev = expected_value(p, american_price)
    warnings = []

    requested = method
    if method == "kelly" and not calibrated:
        warnings.append(
            "Kelly requested but model is UNCALIBRATED -- fell back to flat "
            "staking. Kelly assumes the probability is correct; an "
            "uncalibrated model sizes up exactly where it is most wrong."
        )
        method = "flat"

    if ev <= 0:
        return {
            "stake": 0.0, "fraction": 0.0, "method": "none",
            "requested_method": requested, "expected_value": ev,
            "warnings": warnings + ["no positive expected value at this price"],
        }

    if method == "flat":
        fraction = kwargs.get("flat_fraction", DEFAULT_FLAT_FRACTION)
        stake = flat_stake(bankroll, fraction)
    elif method == "kelly":
        fraction = fractional_kelly(
            p, american_price,
            kelly_multiplier=kwargs.get("kelly_multiplier", DEFAULT_KELLY_FRACTION),
            max_fraction=kwargs.get("max_fraction", DEFAULT_MAX_FRACTION),
        )
        stake = bankroll * fraction
    else:
        raise StakingError(f"unknown sizing method {method!r}; expected flat or kelly")

    return {
        "stake": stake, "fraction": fraction, "method": method,
        "requested_method": requested, "expected_value": ev, "warnings": warnings,
    }


def default_sizer():
    """The sizing configuration this project uses until Phase 12 says otherwise."""
    return {
        "method": "flat",
        "flat_fraction": DEFAULT_FLAT_FRACTION,
        "reason": "model is unvalidated; flat staking until calibration is proven",
    }


def _validate_bankroll(bankroll):
    if isinstance(bankroll, bool) or not isinstance(bankroll, (int, float)):
        raise StakingError(f"bankroll must be numeric, got {bankroll!r}")
    if bankroll <= 0:
        raise StakingError(f"bankroll must be positive, got {bankroll!r}")


def _validate_probability(p):
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise StakingError(f"probability must be numeric, got {p!r}")
    p = float(p)
    if p != p:
        raise StakingError("probability must not be NaN")
    if not (0.0 < p < 1.0):
        raise StakingError(f"probability must be strictly between 0 and 1, got {p!r}")
    return p
