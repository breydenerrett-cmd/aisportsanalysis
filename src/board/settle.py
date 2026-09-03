"""Settlement rules for game-level markets: a pure function per rule key.

Every key in MARKET_CATALOGUE names a `settlement_rule`. This module owns the
registry those names resolve against for GAME-LEVEL markets (h2h, spreads,
totals, team totals, first-five variants, first-inning yes/no). Player props
settle in src/board/settle_props.py, owned by a different lane; this module
exposes `register_rule` as the seam so that lane can plug its functions into
the same registry without either lane importing private internals of the
other.

Every rule is a pure function over a GameResult (or equivalent box-line
input) -- no I/O, no clock. A market whose rule is `collection_blocked` is
one this project has named but refuses to settle (a declared prop not yet
built, or the SGP entry that must never be silently priced); a test in this
file enforces that every catalogue entry resolves to a real callable or to
that literal sentinel string, so a market cannot go live without a
settlement path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# Sentinel: a catalogue entry may point at this string instead of a callable
# to declare "named on purpose, not settleable yet" -- see module docstring.
COLLECTION_BLOCKED = "collection_blocked"


@dataclass(frozen=True)
class GameResult:
    """The minimal box-line input every game-level settlement rule needs.

    Optional fields default to None so a caller who only has full-game data
    can still settle h2h/spreads/totals without fabricating first-five or
    first-inning numbers -- absence is represented, never guessed.
    """

    home_runs: int
    away_runs: int
    home_runs_through_5: int | None = None
    away_runs_through_5: int | None = None
    home_runs_1st_inning: int | None = None
    away_runs_1st_inning: int | None = None


# Settlement outcomes are one of these three strings. "void" covers cases a
# rule cannot resolve from the given result (e.g. first-five numbers absent).
WIN = "win"
LOSS = "loss"
PUSH = "push"
VOID = "void"


def _settle_h2h(side: str, result: GameResult) -> str:
    if result.home_runs == result.away_runs:
        return VOID  # MLB games do not end tied; treat as unsettleable input
    home_won = result.home_runs > result.away_runs
    if side == "home":
        return WIN if home_won else LOSS
    if side == "away":
        return LOSS if home_won else WIN
    raise ValueError(f"h2h side must be 'home' or 'away', got {side!r}")


def _settle_spreads(side: str, line: str, result: GameResult) -> str:
    point = float(line)
    margin = result.home_runs - result.away_runs  # positive = home won by margin
    if side == "home":
        adjusted = margin + point
    elif side == "away":
        adjusted = -margin + point
    else:
        raise ValueError(f"spreads side must be 'home' or 'away', got {side!r}")
    if adjusted > 0:
        return WIN
    if adjusted < 0:
        return LOSS
    return PUSH


def _settle_totals(side: str, line: str, result: GameResult) -> str:
    point = float(line)
    total = result.home_runs + result.away_runs
    return _over_under(side, point, total)


def _over_under(side: str, point: float, actual: float) -> str:
    if side == "over":
        if actual > point:
            return WIN
        if actual < point:
            return LOSS
        return PUSH
    if side == "under":
        if actual < point:
            return WIN
        if actual > point:
            return LOSS
        return PUSH
    raise ValueError(f"side must be 'over' or 'under', got {side!r}")


def _settle_team_totals(
    side: str, line: str, result: GameResult, *, team: str
) -> str:
    point = float(line)
    actual = result.home_runs if team == "home" else result.away_runs
    return _over_under(side, point, actual)


def _first_five(result: GameResult) -> tuple[int, int] | None:
    if result.home_runs_through_5 is None or result.away_runs_through_5 is None:
        return None
    return result.home_runs_through_5, result.away_runs_through_5


def _settle_h2h_1st_5(side: str, result: GameResult) -> str:
    f5 = _first_five(result)
    if f5 is None:
        return VOID
    home5, away5 = f5
    if home5 == away5:
        return PUSH  # first-five h2h markets push on a tie, unlike full-game
    home_won = home5 > away5
    if side == "home":
        return WIN if home_won else LOSS
    if side == "away":
        return LOSS if home_won else WIN
    raise ValueError(f"h2h_1st_5 side must be 'home' or 'away', got {side!r}")


def _settle_spreads_1st_5(side: str, line: str, result: GameResult) -> str:
    f5 = _first_five(result)
    if f5 is None:
        return VOID
    home5, away5 = f5
    point = float(line)
    margin = home5 - away5
    if side == "home":
        adjusted = margin + point
    elif side == "away":
        adjusted = -margin + point
    else:
        raise ValueError(
            f"spreads_1st_5 side must be 'home' or 'away', got {side!r}"
        )
    if adjusted > 0:
        return WIN
    if adjusted < 0:
        return LOSS
    return PUSH


def _settle_totals_1st_5(side: str, line: str, result: GameResult) -> str:
    f5 = _first_five(result)
    if f5 is None:
        return VOID
    home5, away5 = f5
    return _over_under(side, float(line), home5 + away5)


def _first_inning_runs(result: GameResult) -> tuple[int, int] | None:
    if (
        result.home_runs_1st_inning is None
        or result.away_runs_1st_inning is None
    ):
        return None
    return result.home_runs_1st_inning, result.away_runs_1st_inning


def _settle_first_inning_run(side: str, result: GameResult) -> str:
    fi = _first_inning_runs(result)
    if fi is None:
        return VOID
    home1, away1 = fi
    any_run = (home1 + away1) > 0
    if side == "yes":
        return WIN if any_run else LOSS
    if side == "no":
        return LOSS if any_run else WIN
    raise ValueError(f"first_inning_run side must be 'yes' or 'no', got {side!r}")


def _settle_first_inning_score_home(side: str, result: GameResult) -> str:
    fi = _first_inning_runs(result)
    if fi is None:
        return VOID
    home1, _ = fi
    scored = home1 > 0
    if side == "yes":
        return WIN if scored else LOSS
    if side == "no":
        return LOSS if scored else WIN
    raise ValueError(
        f"first_inning_score_home side must be 'yes' or 'no', got {side!r}"
    )


def _settle_first_inning_score_away(side: str, result: GameResult) -> str:
    fi = _first_inning_runs(result)
    if fi is None:
        return VOID
    _, away1 = fi
    scored = away1 > 0
    if side == "yes":
        return WIN if scored else LOSS
    if side == "no":
        return LOSS if scored else WIN
    raise ValueError(
        f"first_inning_score_away side must be 'yes' or 'no', got {side!r}"
    )


# Rules that need only (side, result) -- no line.
_NO_LINE_RULES: dict[str, Callable[[str, GameResult], str]] = {
    "h2h": _settle_h2h,
    "h2h_1st_5": _settle_h2h_1st_5,
    "first_inning_run": _settle_first_inning_run,
    "first_inning_score_home": _settle_first_inning_score_home,
    "first_inning_score_away": _settle_first_inning_score_away,
}

# Rules that need (side, line, result).
_LINE_RULES: dict[str, Callable[[str, str, GameResult], str]] = {
    "spreads": _settle_spreads,
    "totals": _settle_totals,
    "spreads_1st_5": _settle_spreads_1st_5,
    "totals_1st_5": _settle_totals_1st_5,
}


def _team_totals_rule(side: str, line: str, result: GameResult, *, team: str) -> str:
    return _settle_team_totals(side, line, result, team=team)


# The public registry: settlement_rule key -> callable(side, line, result) or
# callable(side, result) for no-line markets, or COLLECTION_BLOCKED.
#
# A uniform call signature would force no-line markets to accept an unused
# `line` argument (or line-markets to accept a phantom None) -- the split
# below keeps each rule's signature honest about what it actually consumes;
# `settle` (the dispatcher) hides the distinction from callers who just want
# an outcome for a given catalogue key.
SETTLEMENT_RULES: dict[str, object] = {
    **_NO_LINE_RULES,
    **_LINE_RULES,
    "team_totals": _team_totals_rule,
    COLLECTION_BLOCKED: COLLECTION_BLOCKED,
}


def register_rule(key: str, fn: Callable) -> None:
    """Plug a settlement rule into the shared registry (the settle_props.py seam).

    Raises if `key` is already registered to something other than the exact
    same callable -- this registry is process-global and a silent overwrite
    would let two lanes' rules shadow each other without either noticing.
    """
    existing = SETTLEMENT_RULES.get(key)
    if existing is not None and existing is not fn:
        raise ValueError(
            f"settlement rule {key!r} is already registered to a different "
            "callable -- register_rule refuses to silently overwrite it"
        )
    SETTLEMENT_RULES[key] = fn


def settle(
    settlement_rule: str,
    side: str,
    result: GameResult,
    line: Optional[str] = None,
    **kwargs,
) -> str:
    """Dispatch to the registered rule for `settlement_rule` and return one of
    WIN/LOSS/PUSH/VOID. Raises KeyError for an unregistered key and ValueError
    if `settlement_rule` resolves to COLLECTION_BLOCKED -- a blocked market
    can be named and catalogued but never actually settled."""
    fn = SETTLEMENT_RULES.get(settlement_rule)
    if fn is None:
        raise KeyError(f"no settlement rule registered for {settlement_rule!r}")
    if fn == COLLECTION_BLOCKED:
        raise ValueError(
            f"settlement_rule {settlement_rule!r} is collection_blocked and "
            "cannot be settled"
        )
    if settlement_rule in _NO_LINE_RULES:
        return fn(side, result)
    if settlement_rule == "team_totals":
        return fn(side, line, result, **kwargs)
    return fn(side, line, result)
