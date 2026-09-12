"""The card must print the number that decides the bet.

THE DEFECT
----------
Every published pick carried two percentages -- what the market makes it and
what our model makes it -- and not the third: what the PRICE requires. The
owner, 2026-09-11, holding a screenshot of the night's number-one pick:

    "Take Dodgers to win at -205 ... the market makes Dodgers a 65% bet to
     win and our own numbers agree at 51%"
    "the value just isn't there still"

He was right, and the page gave him no way to see it. -205 needs 67.2% to
break even, so 51% is not a close call -- it is a bet our own model says
loses. Both numbers on the page were true and the one that settles it was
missing.

This is presentation only. It changes no selection, no ranking and no pick
count; the card publishes exactly what it published and stops withholding
the threshold.
"""

from __future__ import annotations

from tests._unittest_bridge import approx, raises

from src.analysis import daily_card


def _pick(**over):
    base = {
        "team_name": "Dodgers", "opponent_name": "Marlins",
        "market": "moneyline", "price": -205,
        "confidence": 0.65, "market_probability": 0.65,
        "model_probability": 0.51, "model_probability_moneyline": None,
        "label": "STRONG", "agrees": True,
        "starter_name": None, "opp_starter_name": None,
        "us": {"runs_scored": 5.0, "runs_allowed": 3.8},
        "them": {"runs_scored": 4.4, "runs_allowed": 4.4},
        "alternative": None,
    }
    base.update(over)
    return base


def _sentences(pick):
    return " ".join(daily_card._why_sentences(pick))


# --------------------------------------------------------------------------
# The number itself
# --------------------------------------------------------------------------

def test_a_favourite_price_needs_more_than_half():
    assert daily_card._breakeven_pct(-205) == "67%"
    assert daily_card._breakeven_pct(-110) == "52%"


def test_an_underdog_price_needs_less_than_half():
    assert daily_card._breakeven_pct(150) == "40%"
    assert daily_card._breakeven_pct(118) == "46%"


def test_the_breakeven_is_the_STATED_price_vig_and_all():
    """Not de-vigged, deliberately.

    A reader is not being told what the market thinks -- the de-vigged
    consensus is already on the same line. They are being told what THEY
    have to be right about to come out level, and the vig is part of what
    they pay. De-vigging here would quietly lower the bar the bet has to
    clear.
    """
    # -110 de-vigged against a -110 other side is 50%; stated it is 52.4%.
    assert daily_card._breakeven_pct(-110) == "52%"


def test_an_unusable_price_returns_nothing_rather_than_a_placeholder():
    """A sentence asserting a break-even it could not compute is worse than
    one that stops early."""
    for bad in (None, 0, "", "not a price"):
        assert daily_card._breakeven_pct(bad) is None


def test_american_prices_keep_their_sign():
    assert daily_card._format_american(-205) == "-205"
    assert daily_card._format_american(118) == "+118"
    assert daily_card._format_american(None) == "—"


# --------------------------------------------------------------------------
# The sentence
# --------------------------------------------------------------------------

def test_the_owners_own_example_now_shows_what_the_price_needs():
    text = _sentences(_pick())
    assert "51%" in text
    assert "67%" in text
    assert "-205" in text
    assert "break even" in text


def test_it_appears_when_our_number_is_above_the_market_too():
    """Not only on the bad ones.

    Showing the threshold only where it looks unfavourable would make its
    presence a verdict. It is the same fact about the price either way.
    """
    text = _sentences(_pick(model_probability=0.70, confidence=0.65))
    assert "break even" in text


def test_it_appears_when_the_two_numbers_agree():
    text = _sentences(_pick(model_probability=0.655, confidence=0.65))
    assert "break even" in text


def test_a_run_line_pick_does_not_borrow_the_moneyline_sentence(self=None):
    """The sentence is about who WINS; a run-line price is a different bet.

    On a run-line pick `market_probability` and `model_probability` have
    been overwritten with COVER probabilities and `price` is the run-line
    price. Printing that break-even under the words "to win" would attach
    one bet's threshold to another bet's sentence.
    """
    text = _sentences(_pick(market="run_line", price=122))
    assert "break even" not in text


def test_the_threshold_is_stated_never_judged():
    """The reader is handed the third number, not a verdict.

    The card does not tell anyone a bet is good or bad here -- it prints
    what the price requires and lets the comparison be theirs.
    """
    text = _sentences(_pick()).lower()
    for verdict in ("bad bet", "do not take", "avoid", "negative value",
                    "-ev", "losing bet"):
        assert verdict not in text


def test_nothing_is_claimed_when_the_price_is_missing():
    text = _sentences(_pick(price=None))
    assert "break even" not in text
    # and the rest of the sentence still renders
    assert "51%" in text


# --------------------------------------------------------------------------
# It is presentation only
# --------------------------------------------------------------------------

def test_a_pick_reread_from_the_ledger_still_shows_our_percentage():
    """`model_probability_moneyline` is frozen as an explicit null.

    Nothing writes that field -- it is read in the sentence and frozen by
    card_ledger, so every pick in evidence/cards_v1.jsonl carries it as
    null. `.get(key, default)` only returns the default when the key is
    ABSENT, so a pick re-read from the ledger rendered our own number as an
    em dash: the sentence compared the market's percentage against nothing.
    """
    pick = _pick(model_probability_moneyline=None)
    text = _sentences(pick)
    assert "51%" in text
    assert "—" not in text.split("The market makes")[1].split(".")[0]


def test_the_threshold_changes_no_selection_field():
    """Guard against this quietly becoming a filter.

    Whether the card SHOULD drop picks our own model says lose is a real
    question and the owner's to answer. It is not answered by a wording
    change, and a wording change must not answer it by accident.
    """
    pick = _pick()
    before = dict(pick)
    daily_card._why_sentences(pick)
    assert pick == before


# CI runs `python -m unittest discover` on a stdlib-only interpreter; the
# bridge turns the functions above into a TestCase there and returns None
# under pytest so nothing is collected twice.
from tests._unittest_bridge import as_test_case  # noqa: E402

FunctionTests = as_test_case(globals())
