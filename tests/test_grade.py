"""src/analysis/grade.py -- the knowledge grade, and what it is not.

The bands are pinned here so they cannot be tuned after a slate looks too
empty. And the one thing the grade must never do is rank on the price gap:
that selection was measured at -13.4% against a -9.1% control.
"""

import pytest

from src.analysis import grade
from src.analysis import prices as prices_mod


NINE = list(range(1, 10))


def _game(away_pid=101, home_pid=202):
    return {"away_team": "BOS", "home_team": "NYY", "date": "2026-09-12",
            "away_probable_id": away_pid, "home_probable_id": home_pid}


def _board(books=9, age=600, has_board=True):
    return {"has_board": has_board, "books": books, "age_seconds": age}


def _quality(**gaps):
    return {"has_market": True, "has_lineups": True, "has_starters": True,
            "has_price_board": True, "gaps": dict(gaps)}


def _lineups(away=NINE, home=NINE):
    return {"away": list(away), "home": list(home)}


def _grade(**over):
    kwargs = dict(game=_game(), data_quality=_quality(), board_summary=_board(),
                  lineups=_lineups())
    kwargs.update(over)
    return grade.knowledge_grade(**kwargs)


# --------------------------------------------------------------------------
# The bands
# --------------------------------------------------------------------------

def test_everything_known_is_an_A():
    got = _grade()
    assert got["letter"] == "A"
    assert all(got["core"].values())


def test_one_supporting_gap_is_still_an_A():
    got = _grade(data_quality=_quality(weather="not fetched"))
    assert got["letter"] == "A"
    assert got["supporting_gaps"] == ["weather"]


def test_two_supporting_gaps_drop_an_A_to_a_B():
    got = _grade(data_quality=_quality(weather="x", bullpen="y"))
    assert got["letter"] == "B"


def test_a_stale_board_is_a_B_not_an_A():
    got = _grade(board_summary=_board(age=grade.FRESH_SECONDS + 1))
    assert got["letter"] == "B"
    assert got["core"]["fresh"] is False


def test_a_thin_board_is_a_B_not_an_A():
    got = _grade(board_summary=_board(books=prices_mod.MIN_BOOKS - 1))
    assert got["letter"] == "B"
    assert got["core"]["board"] is False


def test_a_missing_lineup_is_a_C_however_good_the_board():
    got = _grade(lineups=None)
    assert got["letter"] == "C"


def test_one_lineup_of_two_is_still_a_C():
    got = _grade(lineups=_lineups(home=[]))
    assert got["letter"] == "C"
    assert got["sides_posted"] == 1


def test_an_unnamed_starter_is_a_C():
    got = _grade(game=_game(home_pid=None))
    assert got["letter"] == "C"


def test_no_board_at_all_is_a_D():
    got = _grade(board_summary=_board(has_board=False, books=None, age=None))
    assert got["letter"] == "D"


def test_neither_lineups_nor_starters_is_a_D_even_with_a_board():
    got = _grade(lineups=None, game=_game(away_pid=None, home_pid=None))
    assert got["letter"] == "D"


def test_eight_batters_is_not_a_lineup():
    got = _grade(lineups=_lineups(away=NINE[:8]))
    assert got["core"]["lineups"] is False


def test_the_lineup_section_may_carry_the_list_inside_a_dict():
    got = _grade(lineups={"away": {"batters": NINE}, "home": {"lineup": NINE}})
    assert got["core"]["lineups"] is True


# --------------------------------------------------------------------------
# The plus
# --------------------------------------------------------------------------

def test_plus_only_on_an_A_and_only_when_the_number_clears_the_price():
    a = _grade()
    assert grade.with_plus(a, model_probability=0.66, breakeven=0.64)["grade"] == "A+"
    assert grade.with_plus(a, model_probability=0.60, breakeven=0.64)["grade"] == "A"


def test_no_plus_on_a_B_however_good_the_price():
    b = _grade(board_summary=_board(age=grade.FRESH_SECONDS + 1))
    assert grade.with_plus(b, model_probability=0.90, breakeven=0.50)["grade"] == "B"


def test_a_missing_number_is_not_a_pass():
    a = _grade()
    assert grade.with_plus(a, model_probability=None, breakeven=0.60)["plus"] is False
    assert grade.with_plus(a, model_probability=0.7, breakeven=None)["plus"] is False


def test_with_plus_does_not_mutate_its_input():
    a = _grade()
    grade.with_plus(a, model_probability=0.9, breakeven=0.5)
    assert a["plus"] is False and a["grade"] == "A"


# --------------------------------------------------------------------------
# What it must never be
# --------------------------------------------------------------------------

def test_the_letter_never_depends_on_the_price_gap():
    """Two identical games with wildly different price gaps grade the same.

    The grade is knowledge, and the only place a price enters is the plus.
    """
    assert _grade()["letter"] == _grade()["letter"]
    with_gap = grade.with_plus(_grade(), model_probability=0.99, breakeven=0.10)
    without = grade.with_plus(_grade(), model_probability=0.10, breakeven=0.99)
    assert with_gap["letter"] == without["letter"] == "A"


def test_the_bands_are_the_declared_ones():
    assert grade.FRESH_SECONDS == 3600
    assert grade.LINEUP_LENGTH == 9
    assert set(grade.SUPPORTING_SECTIONS) == {"teams", "starters", "bullpen",
                                              "weather", "park"}


# --------------------------------------------------------------------------
# The sentence and the legend
# --------------------------------------------------------------------------

def test_the_sentence_names_what_is_known():
    why = _grade()["why"]
    assert why.startswith("A: ")
    assert "lineups posted" in why
    assert "both starters named" in why
    assert "9 books quoting 10 minutes ago" in why


def test_the_sentence_names_what_is_missing():
    why = _grade(lineups=None, data_quality=_quality(weather="x"))["why"]
    assert "no lineup yet" in why
    assert "missing weather" in why


def test_the_legend_says_what_the_grade_is_not():
    text = " ".join(grade.legend()).lower()
    assert "not how much we expect to win" in text
    assert "a note, not a reason" in text
