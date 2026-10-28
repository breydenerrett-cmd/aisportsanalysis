"""The Markov model of LIVE_TENNIS_V1 against known values and against independent implementations.

Chain checked here, layer by layer (hold probability -> game -> set -> match):

  * the game closed form against published values (G(0.5) = 0.5, G(0.6) = 0.7357, G(0.7) = 0.9008) and against a
    point-by-point enumeration written independently of it;
  * the tiebreak against an independent recursion with a differently written serving-order formula, and a seeded
    simulation;
  * the set distribution against an exhaustive game-by-game enumeration of every set path (8,192 of them);
  * the match against an exhaustive enumeration over set outcomes that tracks serving order on its own;
  * the inversion from the pre-match price, its symmetry, its bounds and its refusals.

Everything is deterministic: no clock, no network, and the one simulation uses a fixed seed.
"""

from __future__ import annotations

import itertools
import math
import random
import unittest

from src.research.live_tennis import config, markov

A, B = markov.A, markov.B


# ---------------------------------------------------------------------------
# independent references
# ---------------------------------------------------------------------------

def game_by_points(p: float) -> float:
    """P(server wins a game): sum over every point sequence that ends the game, deuce tail in closed form."""
    q = 1.0 - p
    total = 0.0
    for lost in range(0, 3):                      # win to 15, 30, 40 (opponent has 0, 1 or 2 points)
        total += math.comb(3 + lost, lost) * p ** 4 * q ** lost
    reach_deuce = math.comb(6, 3) * p ** 3 * q ** 3
    total += reach_deuce * (p * p / (1.0 - 2.0 * p * q))
    return total


def tiebreak_reference(pa: float, pb: float, first: str) -> float:
    """An independent tiebreak: the server of 0-based point k is read from ((k + 1) // 2) % 2."""
    cache = {}

    def server(k: int) -> str:
        return first if ((k + 1) // 2) % 2 == 0 else (B if first == A else A)

    def win(a: int, b: int) -> float:
        if (a, b) in cache:
            return cache[(a, b)]
        if max(a, b) >= 7 and abs(a - b) >= 2:
            value = 1.0 if a > b else 0.0
        elif a + b >= 140:
            value = 0.5
        else:
            s = server(a + b)
            pa_point = pa if s == A else 1.0 - pb
            value = pa_point * win(a + 1, b) + (1.0 - pa_point) * win(a, b + 1)
        cache[(a, b)] = value
        return value

    return win(0, 0)


def set_by_enumeration(pa: float, pb: float, first: str) -> dict:
    """Every game path of a set from 0-0 (up to 13 games), serving order tracked independently of markov.set_dist."""
    ga, gb = markov.game_win(pa), markov.game_win(pb)
    dist = {(A, "odd"): 0.0, (A, "even"): 0.0, (B, "odd"): 0.0, (B, "even"): 0.0}
    for length in range(6, 13):
        for outcome in itertools.product((1, 0), repeat=length):
            x = y = 0
            prob = 1.0
            ended = False
            for index, a_won in enumerate(outcome):
                server_is_a = (first == A) == (index % 2 == 0)
                p_game_a = ga if server_is_a else 1.0 - gb
                prob *= p_game_a if a_won else 1.0 - p_game_a
                x, y = x + a_won, y + (1 - a_won)
                done = (x >= 6 and x - y >= 2) or (y >= 6 and y - x >= 2)
                if done:
                    ended = index == length - 1
                    break
                if x == 6 and y == 6:
                    break
            if not ended:
                continue
            dist[(A if x > y else B, "odd" if length % 2 else "even")] += prob
    # all paths that reach 6-6 (12 games): the tiebreak is game 13, served by `first`
    for outcome in itertools.product((1, 0), repeat=12):
        if sum(outcome) != 6:
            continue
        prob = 1.0
        valid = True
        x = y = 0
        for index, a_won in enumerate(outcome):
            server_is_a = (first == A) == (index % 2 == 0)
            p_game_a = ga if server_is_a else 1.0 - gb
            prob *= p_game_a if a_won else 1.0 - p_game_a
            x, y = x + a_won, y + (1 - a_won)
            if (x >= 6 and x - y >= 2) or (y >= 6 and y - x >= 2):
                valid = False
                break
        if not valid:
            continue
        p_tb = tiebreak_reference(pa, pb, first)
        dist[(A, "odd")] += prob * p_tb
        dist[(B, "odd")] += prob * (1.0 - p_tb)
    return dist


def match_by_enumeration(pa: float, pb: float, need: int, sets_a: int, sets_b: int, first: str) -> float:
    """P(A wins) summing over every sequence of set outcomes, the next first server from the games' parity."""
    sets = {f: set_by_enumeration(pa, pb, f) for f in (A, B)}

    def go(x: int, y: int, f: str) -> float:
        if x == need:
            return 1.0
        if y == need:
            return 0.0
        total = 0.0
        for (winner, parity), prob in sets[f].items():
            nf = f if parity == "even" else (B if f == A else A)
            total += prob * (go(x + 1, y, nf) if winner == A else go(x, y + 1, nf))
        return total

    return go(sets_a, sets_b, first)


def simulate_set(pa: float, pb: float, first: str, rng: random.Random):
    """One set by playing points. Returns (A won, games played)."""
    x = y = 0
    while True:
        if x == 6 and y == 6:
            a, b = 0, 0
            k = 0
            while True:
                s = first if ((k + 1) // 2) % 2 == 0 else (B if first == A else A)
                p_a_point = pa if s == A else 1.0 - pb
                if rng.random() < p_a_point:
                    a += 1
                else:
                    b += 1
                k += 1
                if max(a, b) >= 7 and abs(a - b) >= 2:
                    return a > b, 13
        server = first if (x + y) % 2 == 0 else (B if first == A else A)
        p_point = pa if server == A else pb
        pts_s = pts_r = 0
        while True:
            if rng.random() < p_point:
                pts_s += 1
            else:
                pts_r += 1
            if max(pts_s, pts_r) >= 4 and abs(pts_s - pts_r) >= 2:
                break
        server_won = pts_s > pts_r
        a_won_game = server_won if server == A else not server_won
        if a_won_game:
            x += 1
        else:
            y += 1
        if (x >= 6 and x - y >= 2) or (y >= 6 and y - x >= 2):
            return x > y, x + y


class GameTests(unittest.TestCase):
    def test_published_values(self):
        self.assertEqual(markov.game_win(0.5), 0.5)
        self.assertAlmostEqual(markov.game_win(0.6), 0.7357, places=4)
        self.assertAlmostEqual(markov.game_win(0.7), 0.9008, places=4)

    def test_matches_a_point_by_point_enumeration(self):
        for p in (0.05, 0.3, 0.5, 0.56, 0.64, 0.8, 0.95):
            self.assertAlmostEqual(markov.game_win(p), game_by_points(p), places=12)

    def test_complement_and_extremes(self):
        for p in (0.2, 0.45, 0.64):
            self.assertAlmostEqual(markov.game_win(p) + markov.game_win(1.0 - p), 1.0, places=12)
        self.assertEqual(markov.game_win(0.0), 0.0)
        self.assertEqual(markov.game_win(1.0), 1.0)
        with self.assertRaises(ValueError):
            markov.game_win(1.2)


class TiebreakTests(unittest.TestCase):
    def test_even_players_split_evenly_and_it_is_monotone(self):
        self.assertAlmostEqual(markov.tiebreak_win(0.5, 0.5, A), 0.5, places=12)
        values = [markov.tiebreak_win(0.60 + 0.02 * i, 0.60, A) for i in range(6)]
        self.assertEqual(values, sorted(values))

    def test_matches_the_independent_recursion(self):
        for pa, pb, first in ((0.66, 0.60, A), (0.66, 0.60, B), (0.55, 0.70, A), (0.9, 0.9, B)):
            self.assertAlmostEqual(markov.tiebreak_win(pa, pb, first), tiebreak_reference(pa, pb, first), places=9)

    def test_seeded_simulation_agrees(self):
        rng = random.Random(20261028)
        pa, pb = 0.66, 0.60
        wins = 0
        n = 60000
        for _ in range(n):
            a = b = k = 0
            while True:
                s = A if ((k + 1) // 2) % 2 == 0 else B
                if rng.random() < (pa if s == A else 1.0 - pb):
                    a += 1
                else:
                    b += 1
                k += 1
                if max(a, b) >= 7 and abs(a - b) >= 2:
                    wins += a > b
                    break
        self.assertAlmostEqual(wins / n, markov.tiebreak_win(pa, pb, A), delta=0.01)


class SetTests(unittest.TestCase):
    def test_distribution_sums_to_one_and_matches_exhaustive_enumeration(self):
        for pa, pb, first in ((0.64, 0.64, A), (0.70, 0.58, A), (0.70, 0.58, B), (0.52, 0.66, B)):
            got = markov.set_dist(pa, pb, first)
            want = set_by_enumeration(pa, pb, first)
            self.assertAlmostEqual(sum(got.values()), 1.0, places=12)
            for key in got:
                self.assertAlmostEqual(got[key], want[key], places=10, msg=f"{key} at {pa},{pb},{first}")

    def test_equal_players_first_server_averaged_is_even(self):
        self.assertAlmostEqual(markov.set_win_avg(0.64, 0.64), 0.5, places=12)

    def test_swapping_the_players_complements(self):
        for pa, pb in ((0.70, 0.58), (0.60, 0.66)):
            self.assertAlmostEqual(markov.set_win_avg(pa, pb) + markov.set_win_avg(pb, pa), 1.0, places=12)

    def test_who_serves_first_never_changes_a_set_or_match_price(self):
        """A property of this model, found while writing the tests: P(A wins the set) does not depend on the first
        server, for any pair of serve probabilities, so neither does any match price. The 50/50 average over the
        unknown first server in the pre-registration is therefore exact, not an approximation, and the ESPN
        `possession` flag could not have improved a price at a set start."""
        for pa, pb in ((0.70, 0.58), (0.68, 0.60), (0.55, 0.70), (0.80, 0.50), (0.62, 0.62)):
            self.assertAlmostEqual(markov.set_win(pa, pb, A), markov.set_win(pa, pb, B), places=12)
            for need, sa, sb in ((2, 0, 0), (2, 1, 0), (3, 1, 1)):
                self.assertAlmostEqual(markov.match_win(pa, pb, need, sa, sb, A),
                                       markov.match_win(pa, pb, need, sa, sb, B), places=12)
                self.assertAlmostEqual(markov.match_win(pa, pb, need, sa, sb),
                                       markov.match_win(pa, pb, need, sa, sb, A), places=12)

    def test_equal_players_are_even_whoever_serves_first_but_the_parity_is_not(self):
        for first in (A, B):
            self.assertAlmostEqual(markov.set_win(0.64, 0.64, first), 0.5, places=12)
        dist = markov.set_dist(0.64, 0.64, A)
        # the first server wins mostly on an odd number of games (7-6, 6-3, 6-1, 7-... ), the receiver on an even one;
        # this is what sets the next set's first server, so the DP must carry it
        self.assertGreater(dist[(A, "odd")], dist[(A, "even")])
        self.assertGreater(dist[(B, "even")], dist[(B, "odd")])

    def test_near_certain_holds_end_in_a_tiebreak_on_thirteen_games(self):
        dist = markov.set_dist(0.995, 0.995, A)
        self.assertGreater(dist[(A, "odd")] + dist[(B, "odd")], 0.95)

    def test_seeded_simulation_agrees_on_winner_and_parity(self):
        rng = random.Random(20261028)
        pa, pb = 0.68, 0.60
        n = 40000
        a_odd = a_even = 0
        for _ in range(n):
            a_won, games = simulate_set(pa, pb, A, rng)
            if a_won:
                if games % 2:
                    a_odd += 1
                else:
                    a_even += 1
        dist = markov.set_dist(pa, pb, A)
        self.assertAlmostEqual(a_odd / n, dist[(A, "odd")], delta=0.012)
        self.assertAlmostEqual(a_even / n, dist[(A, "even")], delta=0.012)


class MatchTests(unittest.TestCase):
    def test_matches_the_exhaustive_enumeration_from_several_scores(self):
        pa, pb = 0.68, 0.60
        for need, sa, sb in ((2, 0, 0), (2, 1, 0), (2, 0, 1), (3, 1, 1), (3, 0, 2)):
            for first in (A, B):
                self.assertAlmostEqual(markov.match_win(pa, pb, need, sa, sb, first),
                                       match_by_enumeration(pa, pb, need, sa, sb, first), places=10,
                                       msg=f"need={need} {sa}-{sb} first={first}")

    def test_decided_matches_and_bounds(self):
        self.assertEqual(markov.match_win(0.6, 0.6, 2, 2, 0, A), 1.0)
        self.assertEqual(markov.match_win(0.6, 0.6, 2, 0, 2, A), 0.0)
        with self.assertRaises(ValueError):
            markov.match_win(0.6, 0.6, 4)
        with self.assertRaises(ValueError):
            markov.match_win(0.6, 0.6, 2, 3, 0)

    def test_equal_players_are_even_before_a_ball_is_hit_and_swap_symmetric(self):
        self.assertAlmostEqual(markov.match_win(0.64, 0.64, 2), 0.5, places=12)
        self.assertAlmostEqual(markov.match_win(0.64, 0.64, 3), 0.5, places=12)
        self.assertAlmostEqual(markov.match_win(0.70, 0.60, 2) + markov.match_win(0.60, 0.70, 2), 1.0, places=12)

    def test_leading_a_set_helps_and_best_of_five_favours_the_better_player(self):
        pa, pb = 0.68, 0.62
        self.assertGreater(markov.match_win(pa, pb, 2, 1, 0), markov.match_win(pa, pb, 2, 0, 0))
        self.assertLess(markov.match_win(pa, pb, 2, 0, 1), markov.match_win(pa, pb, 2, 0, 0))
        self.assertGreater(markov.match_win(pa, pb, 3), markov.match_win(pa, pb, 2))

    def test_seeded_simulation_of_a_whole_match(self):
        rng = random.Random(20261028)
        pa, pb = 0.68, 0.62
        n = 12000
        wins = 0
        for _ in range(n):
            first = A if rng.random() < 0.5 else B
            sa = sb = 0
            while sa < 2 and sb < 2:
                a_won, games = simulate_set(pa, pb, first, rng)
                sa, sb = sa + a_won, sb + (not a_won)
                first = first if games % 2 == 0 else (B if first == A else A)
            wins += sa == 2
        self.assertAlmostEqual(wins / n, markov.match_win(pa, pb, 2), delta=0.012)


class InversionTests(unittest.TestCase):
    def test_round_trip_and_symmetry(self):
        s, bound = config.SERVE_LEVEL_ATP, config.SKILL_GAP_BOUND
        for p0 in (0.25, 0.5, 0.7, 0.9):
            d = markov.solve_skill_gap(p0, s, 2, bound)
            self.assertIsNotNone(d)
            self.assertAlmostEqual(markov.match_win(s + d, s - d, 2), p0, places=9)
            d_mirror = markov.solve_skill_gap(1.0 - p0, s, 2, bound)
            self.assertAlmostEqual(d, -d_mirror, places=9)
        self.assertAlmostEqual(markov.solve_skill_gap(0.5, s, 2, bound), 0.0, places=9)

    def test_refuses_what_it_cannot_price(self):
        s, bound = config.SERVE_LEVEL_WTA, config.SKILL_GAP_BOUND
        for p0 in (0.0, 1.0, -0.1, 1.2):
            self.assertIsNone(markov.solve_skill_gap(p0, s, 2, bound))
        self.assertIsNone(markov.solve_skill_gap(1.0 - 1e-12, s, 2, 0.01))   # a tiny range cannot reach it
        with self.assertRaises(ValueError):
            markov.solve_skill_gap(0.5, 0.9, 2, 0.15)

    def test_prices_at_a_set_start(self):
        s, bound = config.SERVE_LEVEL_ATP, config.SKILL_GAP_BOUND
        fresh = markov.model_prices(0.5, s, 2, bound, 0, 0)
        self.assertAlmostEqual(fresh["p_match_home"], 0.5, places=9)
        self.assertAlmostEqual(fresh["p_set_home"], 0.5, places=9)
        up = markov.model_prices(0.5, s, 2, bound, 1, 0)
        down = markov.model_prices(0.5, s, 2, bound, 0, 1)
        self.assertAlmostEqual(up["p_match_home"] + down["p_match_home"], 1.0, places=9)
        self.assertGreater(up["p_match_home"], 0.5)
        favourite = markov.model_prices(0.7, s, 2, bound, 0, 1)
        self.assertLess(favourite["p_match_home"], 0.7)
        self.assertGreater(favourite["p_set_home"], 0.5)
        self.assertIsNone(markov.model_prices(1.0, s, 2, bound, 0, 0))


if __name__ == "__main__":
    unittest.main()
