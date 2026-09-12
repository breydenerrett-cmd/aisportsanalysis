"""src/analysis/propboard.py -- the prop board, tested before it is believed.

Four failures here would be silent and each would produce a plausible board:

  * tonight's box score leaking into tonight's estimate, which would make
    the model look prescient;
  * ranking by edge instead of probability, which is the exact selection
    measured at -13.4% and which the owner's ordering forbids;
  * measuring a gap against a raw price that still holds the book's margin,
    turning the book's vig into our "edge";
  * a home-run contract slipping through on a one-sided market.
"""

import pytest

from src.analysis import propboard


LEAGUE = {"pa": 80000, "hit": 0.22, "single": 0.145, "double": 0.042,
          "triple": 0.004, "home_run": 0.032, "run": 0.12, "rbi": 0.115}


def _box(date, *, h=1, ab=4, pa=4, doubles=0, triples=0, hr=0, r=0, rbi=0):
    return {"date": date, "type": "batter", "h": h, "ab": ab, "pa": pa,
            "doubles": doubles, "triples": triples, "hr": hr, "r": r,
            "rbi": rbi, "total_bases": h + doubles + 2 * triples + 3 * hr}


def _history(n=30, start=1, hr=0):
    return [_box(f"2026-08-{day:02d}", hr=hr) for day in range(start, start + n)]


def _quote(player, market, line, side, price, book, *,
           date="2026-09-11", stamp="2026-09-11T20:00:00Z", event="e1"):
    return {"game_date": date, "event_id": event, "player": player,
            "market": market, "line": line, "side": side, "price": price,
            "book": book, "observed_utc": stamp}


def _two_way(player="Batter A", market="batter_hits", line=0.5,
             over=-150, under=125, books=("draftkings", "fanduel"), **kw):
    rows = []
    for book in books:
        rows.append(_quote(player, market, line, "Over", over, book, **kw))
        rows.append(_quote(player, market, line, "Under", under, book, **kw))
    return rows


# --------------------------------------------------------------------------
# Which markets are allowed on at all
# --------------------------------------------------------------------------

def test_hits_and_total_bases_are_assessable():
    assert propboard.assessable("batter_hits")
    assert propboard.assessable("batter_total_bases")


def test_home_runs_are_refused_because_no_book_quotes_the_under():
    """3,351 home-run quotes in the store and zero unders.

    With one side only there is no pair to de-vig, so any gap computed there
    is measured against a price that still contains the book's whole margin.
    That margin is the book's, not ours.
    """
    assert not propboard.assessable("batter_home_runs")


def test_an_unknown_market_is_refused_not_waved_through():
    assert not propboard.assessable("batter_stolen_bases")
    assert not propboard.assessable(None)
    assert not propboard.assessable("")


# --------------------------------------------------------------------------
# Fair price
# --------------------------------------------------------------------------

def test_the_fair_probability_has_the_book_margin_removed():
    books = {"a": {"Over": -110, "Under": -110},
             "b": {"Over": -110, "Under": -110}}
    fair, best = propboard.fair_and_best(books)
    # -110 both ways is a 4.8% margin; the fair number is 0.500, not 0.524.
    assert fair == pytest.approx(0.5, abs=1e-9)
    assert best["Over"][0] == -110


def test_one_book_is_not_a_market():
    fair, best = propboard.fair_and_best({"a": {"Over": -110, "Under": -110}})
    assert fair is None
    assert best == {}


def test_a_one_sided_book_contributes_nothing():
    books = {"a": {"Over": -110}, "b": {"Over": -115}}
    fair, _best = propboard.fair_and_best(books)
    assert fair is None


def test_best_price_is_the_one_that_pays_most():
    books = {"a": {"Over": -150, "Under": 130},
             "b": {"Over": -130, "Under": 110}}
    _fair, best = propboard.fair_and_best(books)
    assert best["Over"][0] == -130      # shorter juice on the over
    assert best["Under"][0] == 130      # bigger payout on the under
    assert best["Over"][2] == "b"


# --------------------------------------------------------------------------
# Point-in-time
# --------------------------------------------------------------------------

def test_tonights_box_score_never_informs_tonights_estimate():
    """The leak that would make the model look prescient.

    A row dated the slate date itself must not reach the estimate; the
    boundary is strict, not inclusive.
    """
    rows = _history(30) + [_box("2026-09-11", h=4)]
    prior = propboard._prior_lines(rows, "2026-09-11")
    assert len(prior) == 30
    assert all(r["date"] < "2026-09-11" for r in prior)


def test_a_batter_with_no_prior_games_is_refused_not_guessed():
    board = propboard.build(
        _two_way(), date="2026-09-11",
        batters_by_name={}, league=LEAGUE)
    assert board["contracts"] == []
    assert board["refused"]["no prior box score for this batter"] == 1


def test_only_the_newest_quote_from_each_book_is_used():
    rows = (_two_way(over=-200, under=170, stamp="2026-09-11T12:00:00Z")
            + _two_way(over=-120, under=100, stamp="2026-09-11T20:00:00Z"))
    board = propboard.build(
        rows, date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    prices = {c["side"]: c["price"] for c in board["contracts"]}
    assert prices["Over"] == -120, "read the stale morning price"


def test_another_date_is_not_on_tonights_board():
    rows = _two_way(date="2026-09-10")
    board = propboard.build(
        rows, date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    assert board["contracts"] == []


# --------------------------------------------------------------------------
# The two filters, in the owner's order
# --------------------------------------------------------------------------

def _contract(probability, edge, player="X"):
    breakeven = probability - edge
    return {"player": player, "market": "batter_hits", "line": 0.5,
            "side": "Over", "probability": probability,
            "breakeven": breakeven, "gap_vs_breakeven": edge, "price": -150}


def test_the_likely_filter_keeps_only_better_than_a_coin():
    rows = [_contract(0.72, 0.01), _contract(0.49, 0.30),
            _contract(0.51, -0.05)]
    kept = propboard.most_likely(rows)
    assert [round(c["probability"], 2) for c in kept] == [0.72, 0.51]


def test_the_board_is_ranked_by_LIKELIHOOD_never_by_edge():
    """The ordering the owner asked for, and the one the evidence requires.

    A contract with a huge edge and a coin-flip chance must not outrank a
    near-certain one. Ranking by edge is the exact selection
    scripts/probe_prop_value.py measured at -13.4% against a -9.1% control.
    """
    rows = [_contract(0.55, 0.20, "big edge"),
            _contract(0.80, 0.01, "very likely")]
    kept = propboard.most_likely(rows)
    assert kept[0]["player"] == "very likely"


def test_ties_break_deterministically():
    rows = [_contract(0.70, 0.01, "Zeta"), _contract(0.70, 0.05, "Alpha")]
    assert [c["player"] for c in propboard.most_likely(rows)] == ["Alpha",
                                                                 "Zeta"]


def test_the_value_filter_runs_on_survivors_of_the_first():
    rows = [_contract(0.72, 0.04), _contract(0.72, -0.04)]
    assert len(propboard.clears_its_price(propboard.most_likely(rows))) == 1


def test_a_contract_can_be_very_likely_and_still_bad_value():
    """The whole reason both numbers are shown.

    Under 1.5 hits wins about three nights in four and is priced at -270,
    which needs 73%. Winning most nights and being worth taking are
    different questions.
    """
    likely_but_expensive = _contract(0.74, -0.02)
    assert propboard.most_likely([likely_but_expensive])
    assert not propboard.clears_its_price([likely_but_expensive])


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

def test_a_real_shaped_board_prices_both_sides():
    board = propboard.build(
        _two_way(), date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    sides = {c["side"] for c in board["contracts"]}
    assert sides == {"Over", "Under"}
    for contract in board["contracts"]:
        assert 0.0 < contract["probability"] < 1.0
        assert 0.0 < contract["breakeven"] < 1.0
        assert contract["gap_vs_breakeven"] == pytest.approx(
            contract["probability"] - contract["breakeven"])


def test_the_two_sides_probabilities_complement():
    board = propboard.build(
        _two_way(), date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    by_side = {c["side"]: c["probability"] for c in board["contracts"]}
    assert by_side["Over"] + by_side["Under"] == pytest.approx(1.0)


def test_batting_slot_is_used_when_known():
    """Slot is the most valuable input on the board.

    SLOT_PLATE_APPEARANCES runs 4.467 leading off to 3.461 batting ninth --
    about 29% more chances -- so a lineup posting changes a prop's value far
    more than it changes a moneyline's.
    """
    leadoff = propboard.build(
        _two_way(), date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE,
        slots_by_player={"Batter A": 1})
    ninth = propboard.build(
        _two_way(), date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE,
        slots_by_player={"Batter A": 9})
    over_leadoff = [c for c in leadoff["contracts"]
                    if c["side"] == "Over"][0]
    over_ninth = [c for c in ninth["contracts"] if c["side"] == "Over"][0]
    assert over_leadoff["expected_pa"] > over_ninth["expected_pa"]
    assert over_leadoff["probability"] > over_ninth["probability"]
    assert over_leadoff["expected_pa_source"] == "batting_slot"


def test_the_refusal_census_is_reported_not_swallowed():
    """A board that silently drops most of its input looks like a thin
    slate."""
    rows = _two_way(books=("draftkings",))  # one book: not a market
    board = propboard.build(
        rows, date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    assert board["contracts"] == []
    assert board["refused"]["fewer than two books quoting both sides"] == 1


# --------------------------------------------------------------------------
# Home runs: likelihood only. No under is ever quoted, so no fair price and
# no gap against the market -- only how likely we make it and what the best
# stated Over needs. The owner asked for the market by name.
# --------------------------------------------------------------------------

def _overs_only(player="Batter A", market="batter_home_runs", line=0.5,
                prices=(("draftkings", 320), ("fanduel", 350)), **kw):
    return [_quote(player, market, line, "Over", price, book, **kw)
            for book, price in prices]


def test_home_runs_are_likelihood_only_and_hits_are_not():
    assert propboard.likelihood_only("batter_home_runs")
    assert not propboard.likelihood_only("batter_hits")
    assert not propboard.likelihood_only("batter_rbis")   # not publishable
    assert not propboard.likelihood_only(None)
    # `assessable` is unchanged: a home run still has no fair price.
    assert not propboard.assessable("batter_home_runs")


def test_a_home_run_row_carries_ours_and_the_price_but_no_market_number():
    board = propboard.build(
        _overs_only(), date="2026-09-11",
        batters_by_name={"Batter A": _history(hr=0)}, league=LEAGUE)
    assert board["refused"] == {}
    assert len(board["contracts"]) == 1
    row = board["contracts"][0]
    assert row["side"] == "Over"
    assert row["market"] == "batter_home_runs"
    assert 0.0 < row["probability"] < 1.0
    assert row["market_probability"] is None
    assert "no book quotes the under" in row["market_probability_absent"]
    # The best stated Over: +350 at fanduel, break-even 1/4.5.
    assert row["price"] == 350 and row["book"] == "fanduel"
    assert row["breakeven"] == pytest.approx(1 / 4.5)


def test_a_home_run_with_no_over_at_all_is_refused_by_name():
    rows = [_quote("Batter A", "batter_home_runs", 0.5, "Under", -400, "draftkings")]
    board = propboard.build(
        rows, date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    assert board["contracts"] == []
    assert board["refused"] == {"no over quoted": 1}


def test_home_runs_rank_by_probability_alongside_everything_else():
    """One list, one rule: most likely first, never by gap -- and a home run
    is a low-probability event, so it sits below the hits rows."""
    board = propboard.build(
        _two_way() + _overs_only(), date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    likely = propboard.most_likely(board["contracts"], floor=0.0)
    probabilities = [c["probability"] for c in likely]
    assert probabilities == sorted(probabilities, reverse=True)
    assert likely[-1]["market"] == "batter_home_runs"


def test_long_shots_are_the_likelihood_only_overs_likeliest_first():
    """A home run never clears the more-likely-than-not floor, so it gets
    its own list -- same rule (probability), never the price."""
    rows = (_two_way()
            + _overs_only(player="Batter A")
            + _overs_only(player="Batter B", prices=(("draftkings", 250), ("fanduel", 260))))
    board = propboard.build(
        rows, date="2026-09-11",
        batters_by_name={"Batter A": _history(hr=0), "Batter B": _history(hr=1)},
        league=LEAGUE)
    shots = propboard.long_shots(board["contracts"])
    assert [c["market"] for c in shots] == ["batter_home_runs"] * 2
    assert all(c["side"] == "Over" for c in shots)
    # Batter B homers every game in his history; he is likelier and first.
    assert shots[0]["player"] == "Batter B"
    assert shots[0]["probability"] > shots[1]["probability"]
    # The likely list is untouched by them.
    assert all(c["market"] != "batter_home_runs"
               for c in propboard.most_likely(board["contracts"]))


def test_long_shots_are_capped():
    contracts = [{"market": "batter_home_runs", "side": "Over",
                  "probability": 0.1 + i / 1000, "player": f"P{i}"} for i in range(30)]
    assert len(propboard.long_shots(contracts)) == propboard.LONG_SHOT_LIMIT
    assert propboard.long_shots(contracts, limit=3)[0]["player"] == "P29"


def test_a_board_needs_a_date():
    with pytest.raises(propboard.PropBoardError):
        propboard.build([], date="", batters_by_name={}, league=LEAGUE)


def test_summarise_counts_both_filters():
    board = propboard.build(
        _two_way(), date="2026-09-11",
        batters_by_name={"Batter A": _history()}, league=LEAGUE)
    got = propboard.summarise(board)
    assert got["date"] == "2026-09-11"
    assert got["contracts"] == 2
    assert got["markets"] == ["batter_hits"]
    assert got["likely"] >= 1
