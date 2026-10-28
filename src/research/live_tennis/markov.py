"""The standard serve-hold Markov model of a tennis match (MARKOV_V1, docs/PREREG_LIVE_TENNIS.md section 4).

Pure arithmetic, no I/O, no clock. Layers, each built only from the one below:

    point   the server wins each service point with probability p, independent of every other point
    game    G(p) = p^4 (1 + 4q + 10 q^2) + 20 p^3 q^3 * p^2 / (p^2 + q^2),  q = 1 - p
    set     games alternate server; won at 6 with a lead of 2, at 7-5, or by a tiebreak at 6-6
    match   best of 3 or 5, a dynamic programme over (sets won A, sets won B, first server of the set)

Player A is the HOME team as The Odds API names it. Nothing here knows who serves first in a match,
so every price AVERAGES the two possible first servers 50/50 (the ESPN `possession` flag is never used).
In this model that average is exact, not an approximation: P(A wins a set from 0-0) does not depend on who
serves first, for any pair of serve probabilities (checked numerically in tests/test_live_tennis_markov.py), so
no set or match price does either. The serving order is still tracked exactly, because the identity is a fact
about the model to be verified, not an assumption the code should lean on.

The serving order is tracked exactly: a set's first server serves games 1, 3, 5 ...; the tiebreak counts
as one game; the next set's first server is the same player after a set of an even number of games and the
other player after an odd number (so `set_dist` returns the parity of the games played along with the
winner). The tiebreak is to 7, win by 2, the first server serving one point and then service alternating
every two points.

Simplifications, disclosed in the pre-registration: a deciding set also ends at 6-6 with a 7-point tiebreak
(no advantage final sets, no 10-point final-set tiebreak), one serve level per tour, and nothing observed in
a match except the sets-won score carries information.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional, Tuple

A, B = "A", "B"
_TB_POINT_CAP = 90          # beyond this the unresolved mass (about 1e-27) is split evenly


def _other(player: str) -> str:
    return B if player == A else A


def game_win(p: float) -> float:
    """P(the server wins a game) when they win each point with probability p."""
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"point probability must be in [0, 1], got {p!r}")
    q = 1.0 - p
    if p == 0.0:
        return 0.0
    deuce_win = p * p / (p * p + q * q)
    return p ** 4 * (1.0 + 4.0 * q + 10.0 * q * q) + 20.0 * p ** 3 * q ** 3 * deuce_win


def tiebreak_win(pa: float, pb: float, first: str) -> float:
    """P(A wins a 7-point win-by-2 tiebreak) when `first` serves the first point."""
    if first not in (A, B):
        raise ValueError("first must be 'A' or 'B'")

    def server_of(point_number: int) -> str:            # 1-indexed
        if point_number == 1:
            return first
        return _other(first) if ((point_number - 2) // 2) % 2 == 0 else first

    @lru_cache(maxsize=None)
    def win(a: int, b: int) -> float:
        if max(a, b) >= 7 and abs(a - b) >= 2:
            return 1.0 if a > b else 0.0
        if a + b >= _TB_POINT_CAP:
            return 0.5
        server = server_of(a + b + 1)
        p_a_wins_point = pa if server == A else 1.0 - pb
        return p_a_wins_point * win(a + 1, b) + (1.0 - p_a_wins_point) * win(a, b + 1)

    return win(0, 0)


def set_dist(pa: float, pb: float, first: str) -> dict:
    """Distribution of a set from 0-0: {(winner, parity): probability}, parity 'odd' or 'even' games played.

    `first` serves game 1. A 7-6 set counts 13 games (the tiebreak is one game).
    """
    if first not in (A, B):
        raise ValueError("first must be 'A' or 'B'")
    ga, gb = game_win(pa), game_win(pb)               # P(A holds when serving), P(B holds when serving)

    @lru_cache(maxsize=None)
    def dist(x: int, y: int) -> Tuple[float, float, float, float]:
        # (A odd, A even, B odd, B even)
        if (x >= 6 and x - y >= 2) or (y >= 6 and y - x >= 2):
            odd = (x + y) % 2 == 1
            if x > y:
                return (1.0, 0.0, 0.0, 0.0) if odd else (0.0, 1.0, 0.0, 0.0)
            return (0.0, 0.0, 1.0, 0.0) if odd else (0.0, 0.0, 0.0, 1.0)
        if x == 6 and y == 6:
            p_tb = tiebreak_win(pa, pb, first)       # game 13 is served by `first` (12 games played, even)
            return (p_tb, 0.0, 1.0 - p_tb, 0.0)       # 13 games, odd
        played = x + y
        server = first if played % 2 == 0 else _other(first)
        p_a_game = ga if server == A else 1.0 - gb
        won = dist(x + 1, y)
        lost = dist(x, y + 1)
        return tuple(p_a_game * w + (1.0 - p_a_game) * l for w, l in zip(won, lost))

    a_odd, a_even, b_odd, b_even = dist(0, 0)
    return {(A, "odd"): a_odd, (A, "even"): a_even, (B, "odd"): b_odd, (B, "even"): b_even}


def set_win(pa: float, pb: float, first: str) -> float:
    """P(A wins a set from 0-0) when `first` serves the first game."""
    dist = set_dist(pa, pb, first)
    return dist[(A, "odd")] + dist[(A, "even")]


def set_win_avg(pa: float, pb: float) -> float:
    """P(A wins a set from 0-0), the first server unknown (50/50)."""
    return 0.5 * (set_win(pa, pb, A) + set_win(pa, pb, B))


def match_win(pa: float, pb: float, sets_to_win: int, sets_a: int = 0, sets_b: int = 0,
              first: Optional[str] = None) -> float:
    """P(A wins the match) from `sets_a`-`sets_b` in sets with the new set at 0-0.

    `first` is who serves the first game of the new set; None averages the two 50/50.
    """
    if sets_to_win not in (2, 3):
        raise ValueError("sets_to_win must be 2 or 3")
    if sets_a < 0 or sets_b < 0 or sets_a > sets_to_win or sets_b > sets_to_win:
        raise ValueError("impossible sets-won score")
    if first is None:
        return 0.5 * (match_win(pa, pb, sets_to_win, sets_a, sets_b, A)
                      + match_win(pa, pb, sets_to_win, sets_a, sets_b, B))
    dists = {f: set_dist(pa, pb, f) for f in (A, B)}

    @lru_cache(maxsize=None)
    def go(x: int, y: int, f: str) -> float:
        if x >= sets_to_win:
            return 1.0
        if y >= sets_to_win:
            return 0.0
        total = 0.0
        for (winner, parity), prob in dists[f].items():
            if prob == 0.0:
                continue
            next_first = f if parity == "even" else _other(f)
            total += prob * (go(x + 1, y, next_first) if winner == A else go(x, y + 1, next_first))
        return total

    return go(sets_a, sets_b, first)


def solve_skill_gap(p0_home: float, serve_level: float, sets_to_win: int, bound: float) -> Optional[float]:
    """The d in [-bound, +bound] with match_win(s + d, s - d) = p0_home at 0-0 in sets, or None.

    The match-win probability is increasing in d, so the root is unique; None when p0 lies outside what
    the range can produce (or p0 is not a probability strictly between 0 and 1).
    """
    if not (0.0 < p0_home < 1.0):
        return None
    if not (0.0 < serve_level - bound and serve_level + bound < 1.0):
        raise ValueError("serve level +/- bound must stay inside (0, 1)")

    def f(d: float) -> float:
        return match_win(serve_level + d, serve_level - d, sets_to_win)

    lo, hi = -bound, bound
    f_lo, f_hi = f(lo), f(hi)
    if p0_home < f_lo or p0_home > f_hi:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if f(mid) < p0_home:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def model_prices(p0_home: float, serve_level: float, sets_to_win: int, bound: float,
                 home_sets: int, away_sets: int) -> Optional[dict]:
    """The model's prices at the start of a set, or None if the pre-match price is out of range.

    -> {d, pa, pb, p_match_home, p_set_home}: the home player's match-win probability from the
    sets-won score with the new set at 0-0, and the home player's probability of winning that set,
    both with the first server averaged. A is the home player.
    """
    d = solve_skill_gap(p0_home, serve_level, sets_to_win, bound)
    if d is None:
        return None
    pa, pb = serve_level + d, serve_level - d
    return {
        "d": d, "pa": pa, "pb": pb,
        "p_match_home": match_win(pa, pb, sets_to_win, home_sets, away_sets),
        "p_set_home": set_win_avg(pa, pb),
    }
