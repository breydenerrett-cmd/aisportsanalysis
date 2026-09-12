"""The lineup signer, tested before its output is believed.

Three failures here would be silent and would each produce a plausible
number:

  * a home/away inversion, flipping every result end to end;
  * an expected lineup built from lineups that include the game being
    scored, which is a leak and would make the signer look prescient;
  * unweighted surprise, which would score a platoon player's night off
    the same as a franchise shortstop's -- the exact confusion the
    pre-registration exists to avoid.

Each has a test below that fails against the broken version.
"""

from datetime import date, datetime, timedelta, timezone

from tests._unittest_bridge import approx, raises

from scripts import probe_lineup_direction as probe


BASE = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
REGULARS = [101, 102, 103, 104, 105, 106, 107, 108, 109]


def _posting(team="ATL", day=11, lineup=None, side="home", pk=None):
    return {
        "team": team, "date": date(2026, 9, day),
        "lineup": list(lineup if lineup is not None else REGULARS),
        "side": side, "game_pk": pk or f"g{day}",
        "at": BASE + timedelta(days=day),
    }


# --------------------------------------------------------------------------
# The expected lineup
# --------------------------------------------------------------------------

def test_the_expected_nine_are_the_most_frequent_starters():
    prior = [REGULARS, REGULARS, REGULARS,
             [101, 102, 103, 104, 105, 106, 107, 108, 999]]
    expected, rate = probe._expected_lineup(prior)
    assert set(expected) == set(REGULARS)
    assert rate[109] == approx(0.75)
    assert rate[999] == approx(0.25)


def test_a_bench_player_does_not_displace_a_regular():
    prior = [REGULARS] * 9 + [[101, 102, 103, 104, 105, 106, 107, 108, 777]]
    expected, _rate = probe._expected_lineup(prior)
    assert 777 not in expected
    assert 109 in expected


def test_ties_break_on_most_recent_then_lowest_id():
    """Deterministic, and fixed in the pre-registration.

    Two players at the same rate must not be ordered by dict insertion, or
    the expected nine would depend on file ordering.
    """
    # 501 and 502 each appear once; 502 appears in the LATER lineup, so it
    # takes the ninth slot.
    prior = [
        [101, 102, 103, 104, 105, 106, 107, 108, 501],
        [101, 102, 103, 104, 105, 106, 107, 108, 502],
    ]
    expected, _rate = probe._expected_lineup(prior)
    assert expected[8] == 502


def test_the_expected_lineup_is_exactly_nine():
    prior = [[i, i + 1, i + 2, i + 3, i + 4, i + 5, i + 6, i + 7, i + 8]
             for i in range(1, 40, 9)]
    expected, _rate = probe._expected_lineup(prior)
    assert len(expected) == 9


# --------------------------------------------------------------------------
# Surprise
# --------------------------------------------------------------------------

def test_the_expected_nine_all_playing_is_zero_surprise():
    expected, rate = probe._expected_lineup([REGULARS] * 5)
    assert probe._surprise(expected, rate, REGULARS) == approx(0.0)


def test_surprise_is_weighted_by_how_reliable_the_missing_man_was():
    """An everyday starter's absence must outweigh a platoon player's.

    Unweighted counting would score "one regular out" identically whether
    the man missing started every night or half of them -- and most lineup
    churn is the second kind. That confusion is the whole reason this test
    exists.
    """
    # 109 starts every game; 888 starts a third of them.
    prior = [REGULARS, REGULARS, REGULARS,
             [101, 102, 103, 104, 105, 106, 107, 888, 109]]
    expected, rate = probe._expected_lineup(prior)

    without_everyday = [101, 102, 103, 104, 105, 106, 107, 108, 888]
    without_platoon = [101, 102, 103, 104, 105, 106, 107, 109, 888]

    everyday_gap = probe._surprise(expected, rate, without_everyday)
    platoon_gap = probe._surprise(expected, rate, without_platoon)
    assert everyday_gap > platoon_gap


def test_more_regulars_missing_is_more_surprise():
    expected, rate = probe._expected_lineup([REGULARS] * 5)
    one_out = REGULARS[:8] + [901]
    three_out = REGULARS[:6] + [901, 902, 903]
    assert (probe._surprise(expected, rate, three_out)
            > probe._surprise(expected, rate, one_out) > 0)


# --------------------------------------------------------------------------
# The sign
# --------------------------------------------------------------------------

def test_a_depleted_home_lineup_predicts_the_home_number_falling():
    assert probe.sign_of({"side": "home", "surprise": 1.4}) == -1


def test_a_depleted_AWAY_lineup_predicts_the_home_number_RISING():
    """The board tracks the HOME probability.

    A weakened away team makes the home team more likely to win. Get this
    backwards and every result inverts while still looking reasonable.
    """
    assert probe.sign_of({"side": "away", "surprise": 1.4}) == +1


def test_a_lineup_with_no_surprise_carries_no_claim():
    assert probe.sign_of({"side": "home", "surprise": 0.0}) is None
    assert probe.sign_of({"side": "away", "surprise": 0.0}) is None


# --------------------------------------------------------------------------
# Point-in-time: the leak that would make this look prescient
# --------------------------------------------------------------------------

def test_a_lineup_is_never_scored_against_itself():
    """Tonight's lineup may not inform tonight's expectation.

    If the game being scored were included in its own baseline, a scratched
    regular would drag his own appearance rate down and the surprise would
    shrink toward zero -- the signer would quietly stop seeing the very
    events it exists to catch.
    """
    weird = [101, 102, 103, 104, 105, 106, 107, 108, 555]
    rows = ([_posting(day=d) for d in (1, 2, 3, 4)]
            + [_posting(day=5, lineup=weird)])
    scored, _thin = probe.score_lineups(rows)
    last = [s for s in scored if s["date"] == date(2026, 9, 5)][0]
    # 109 was an everyday starter across all four prior games, so his
    # absence is a full point of surprise -- not diluted by tonight.
    assert last["surprise"] == approx(1.0)


def test_clubs_with_too_little_history_are_skipped_not_guessed():
    rows = [_posting(day=d) for d in (1, 2)]
    scored, thin = probe.score_lineups(rows)
    assert scored == []
    assert thin == 2


def test_history_is_per_club_not_pooled():
    """One club's regulars must never set another club's expectation."""
    rows = ([_posting(team="ATL", day=d) for d in (1, 2, 3, 4)]
            + [_posting(team="SD", day=4, lineup=[201, 202, 203, 204, 205,
                                                  206, 207, 208, 209])])
    scored, _thin = probe.score_lineups(rows)
    assert all(s["team"] == "ATL" for s in scored)


def test_a_novel_starter_is_counted():
    rows = ([_posting(day=d) for d in (1, 2, 3)]
            + [_posting(day=4, lineup=REGULARS[:8] + [4242])])
    scored, _thin = probe.score_lineups(rows)
    last = [s for s in scored if s["date"] == date(2026, 9, 4)][0]
    assert last["novel"] == 1


# --------------------------------------------------------------------------
# Row building
# --------------------------------------------------------------------------

def _event(side="home", lineup=None, pk="1"):
    return {"kind": "lineup_posted", "game_pk": pk, "at": BASE,
            "payload": {"side": side,
                        "lineup": list(lineup if lineup is not None
                                       else REGULARS)}}


def test_the_posting_side_selects_the_team():
    sides = {"1": ("ATL", "SD")}
    pitch = {"1": BASE}
    home, _d = probe._lineup_rows([_event("home")], sides, pitch)
    away, _d = probe._lineup_rows([_event("away")], sides, pitch)
    assert home[0]["team"] == "ATL"
    assert away[0]["team"] == "SD"


def test_a_short_lineup_is_dropped_not_padded():
    sides = {"1": ("ATL", "SD")}
    pitch = {"1": BASE}
    rows, dropped = probe._lineup_rows(
        [_event(lineup=[1, 2, 3])], sides, pitch)
    assert rows == []
    assert dropped["not a full nine"] == 1


def test_an_unresolvable_game_is_dropped_not_guessed():
    rows, dropped = probe._lineup_rows([_event()], {}, {"1": BASE})
    assert rows == []
    assert dropped["game not resolvable to two sides"] == 1


# --------------------------------------------------------------------------
# The sensitivity control
# --------------------------------------------------------------------------

def _obs(surprise, move, game_pk="g"):
    return {"game_pk": game_pk, "after": move, "before": None,
            "expected": 1, "surprise": surprise}


def test_dose_response_sees_bigger_moves_after_bigger_surprises():
    rows = ([_obs(0.2, 0.001, f"a{i}") for i in range(5)]
            + [_obs(3.0, 0.030, f"b{i}") for i in range(5)])
    dose = probe._dose_response(rows)
    assert dose is not None
    assert dose["ratio"] > 1.0


def test_dose_response_is_flat_when_surprise_does_not_matter():
    """A flat ratio is the signal that the instrument is blind.

    The probe must be able to reach this state and say so, rather than
    printing a direction result that cannot be interpreted.
    """
    rows = ([_obs(0.2, 0.010, f"a{i}") for i in range(5)]
            + [_obs(3.0, 0.010, f"b{i}") for i in range(5)])
    dose = probe._dose_response(rows)
    assert dose["ratio"] == approx(1.0)


def test_dose_response_ignores_direction():
    """Magnitude only -- a big move the 'wrong' way is still the instrument
    reacting to the news."""
    rows = ([_obs(0.2, 0.001, f"a{i}") for i in range(5)]
            + [_obs(3.0, -0.030, f"b{i}") for i in range(5)])
    assert probe._dose_response(rows)["ratio"] > 1.0


def test_dose_response_refuses_on_too_few_events():
    assert probe._dose_response([_obs(1.0, 0.01)]) is None


# --------------------------------------------------------------------------
# Constants the pre-registration fixed
# --------------------------------------------------------------------------

def test_the_declared_constants_match_the_preregistration():
    assert probe.MIN_PRIOR_LINEUPS == 3
    assert probe.MIN_EVENTS == 25
    assert probe.ALPHA == approx(0.05)


# CI runs `python -m unittest discover` on a stdlib-only interpreter; the
# bridge turns the functions above into a TestCase there and returns None
# under pytest so nothing is collected twice.
from tests._unittest_bridge import as_test_case  # noqa: E402

FunctionTests = as_test_case(globals())
