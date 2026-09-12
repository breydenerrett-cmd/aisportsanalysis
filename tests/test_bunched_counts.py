"""The per-game model for bunched counts (playerprops.empirical_over).

WHY IT EXISTS
-------------
`playerprops.NOT_PUBLISHABLE` measured two markets WORSE than knowing
nothing -- `batter_rbis` at -0.014 nats and `batter_hits_runs_rbis` at
-0.040 -- diagnosed the cause, and named the fix:

    "RBIs and hits-plus-runs-plus-RBIs are BUNCHED counts: a home run with
     runners on is several RBIs in one plate appearance, and a per-PA rate
     treated as a coin flip overstates how often a batter gets any... The
     fix, when someone does it: model these off the batter's own per-GAME
     distribution rather than a per-PA rate."

Counting how often a batter's own GAMES cleared the line makes no assumption
about how events arrive inside a game, because it never looks inside one.

NONE OF THIS MAKES THE MARKETS PUBLISHABLE. That is decided by measurement
(`scripts/backtest_player_props.py`), and NOT_PUBLISHABLE stays as it is
until a measurement says otherwise.
"""

from __future__ import annotations

import pytest

from src.analysis import playerprops


def _games(counts):
    """Box-score-shaped rows carrying a per-game RBI count."""
    return [{"rbi": c, "h": 0, "r": 0, "hits_runs_rbi": c} for c in counts]


LEAGUE = _games([0] * 60 + [1] * 25 + [2] * 10 + [3] * 5)  # 15% over 1.5


# --------------------------------------------------------------------------
# Reading the count
# --------------------------------------------------------------------------

def test_rbis_come_from_the_rbi_column():
    assert playerprops.game_count({"rbi": 3}, "batter_rbis") == 3


def test_the_combined_column_is_used_when_present():
    row = {"h": 1, "r": 1, "rbi": 1, "hits_runs_rbi": 3}
    assert playerprops.game_count(row, "batter_hits_runs_rbis") == 3


def test_older_rows_without_the_combined_column_sum_the_three():
    """Not an approximation -- it is the same quantity."""
    row = {"h": 2, "r": 1, "rbi": 3}
    assert playerprops.game_count(row, "batter_hits_runs_rbis") == 6


def test_a_row_with_nothing_to_read_is_absent_not_zero():
    """Absent is not zero. A batter with no line did not go 0-for-4; he may
    have been scratched, or the game may not be ingested."""
    assert playerprops.game_count({}, "batter_hits_runs_rbis") is None
    assert playerprops.game_count({"rbi": None}, "batter_rbis") is None


def test_an_unbunched_market_is_refused_here():
    with pytest.raises(playerprops.PropError):
        playerprops.game_count({"h": 1}, "batter_hits")


def test_absent_games_drop_out_of_the_series():
    rows = [{"rbi": 1}, {"rbi": None}, {"rbi": 2}]
    assert playerprops.game_counts(rows, "batter_rbis") == [1, 2]


# --------------------------------------------------------------------------
# The estimate
# --------------------------------------------------------------------------

def test_a_batter_who_always_clears_the_line_lands_high():
    counts = [3] * 40
    got = playerprops.empirical_over(counts, 1.5, [c["rbi"] for c in LEAGUE])
    assert got > 0.6


def test_a_batter_who_never_clears_it_lands_low():
    counts = [0] * 40
    got = playerprops.empirical_over(counts, 1.5, [c["rbi"] for c in LEAGUE])
    assert got < 0.15


def test_bunching_is_carried_for_free():
    """The whole point, as one test.

    Two batters with the SAME total RBIs. One drives in runs one at a time;
    the other does it in bursts. A per-PA Bernoulli cannot tell them apart
    and says both clear 1.5 about as often. Counting games knows the
    one-at-a-time batter almost never has a two-RBI game.
    """
    league = [c["rbi"] for c in LEAGUE]
    spread = [1] * 40                     # 40 RBIs, never two in a game
    bunched = [0] * 30 + [4] * 10         # 40 RBIs, ten multi-RBI games
    assert sum(spread) == sum(bunched)
    assert (playerprops.empirical_over(bunched, 1.5, league)
            > playerprops.empirical_over(spread, 1.5, league))


def test_a_thin_game_log_is_refused_not_guessed():
    league = [c["rbi"] for c in LEAGUE]
    with pytest.raises(playerprops.PropError):
        playerprops.empirical_over([2] * 5, 1.5, league)


def test_shrinkage_pulls_a_short_log_toward_the_league():
    """A 20-game hot streak is not a 100% batter."""
    league = [c["rbi"] for c in LEAGUE]
    short = playerprops.empirical_over([3] * 20, 1.5, league)
    long_run = playerprops.empirical_over([3] * 300, 1.5, league)
    assert short < long_run
    assert short < 1.0


def test_the_shrinkage_target_is_the_league_at_the_SAME_line():
    """Not a single league average.

    The target has to be the same quantity being estimated, or shrinkage
    pulls the answer somewhere it was never headed: the league clears 0.5
    far more often than it clears 2.5, and one number cannot stand for both.
    """
    league = [c["rbi"] for c in LEAGUE]
    neutral = [0] * 10 + [1] * 5  # exactly at the floor, no own signal
    low_line = playerprops.empirical_over(neutral, 0.5, league)
    high_line = playerprops.empirical_over(neutral, 2.5, league)
    assert low_line > high_line


def test_an_empty_league_is_refused(self=None):
    with pytest.raises(playerprops.PropError):
        playerprops.empirical_over([1] * 30, 1.5, [])


def test_the_probability_is_always_a_probability():
    league = [c["rbi"] for c in LEAGUE]
    for counts in ([0] * 30, [9] * 30, [0, 5] * 20):
        got = playerprops.empirical_over(counts, 1.5, league)
        assert 0.0 < got < 1.0


# --------------------------------------------------------------------------
# The gate is untouched until something is measured
# --------------------------------------------------------------------------

def test_the_bunched_markets_are_STILL_not_publishable():
    """Writing a better model is not the same as measuring one.

    These stay refused until scripts/backtest_player_props.py says the new
    estimator beats a base rate. Flipping the gate because the code looks
    better is exactly the move this repo keeps removing.
    """
    for market in playerprops.BUNCHED_MARKETS:
        assert not playerprops.publishable(market)
        assert market in playerprops.NOT_PUBLISHABLE


def test_the_bunched_list_matches_what_was_measured_bad():
    assert set(playerprops.BUNCHED_MARKETS) == set(
        playerprops.NOT_PUBLISHABLE)
