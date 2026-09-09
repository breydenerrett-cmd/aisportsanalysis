"""src/report/clv.py -- closing-line value, and everything it refuses to say.

WHAT THESE TESTS ARE FOR
-------------------------
CLV is the first number this project has ever computed that a customer would
read as evidence, so the failure mode that matters is not "the arithmetic is
off by a basis point" -- it is a number appearing where an absence belongs.
Every test below is written so that it FAILS when the guard it names is
removed: the in-play filter, the revised-first-pitch guard, the book floor,
the line match, the two degenerate decision/close orderings, the side
recovery, and the refusal to let a refused candidate count as a zero.

Numbers are PINNED, not recomputed. A test that re-derives the expected value
with the same call the module makes cannot catch a swapped side or an inverted
sign, which are precisely the two bugs that would turn this module into a
liability. The pinned values below come from
`src.core.odds.devig_two_way(-110, -130) == (0.48099, 0.51901)` after
`src.analysis.prices.snapshot`'s 5-decimal rounding.

WHAT THE SECOND HALF OF THIS FILE IS FOR
-----------------------------------------
This module's first published numbers had to be RETRACTED. Not because a
measurement was wrong -- every row above was already covered -- but because
the ROLLUPS pooled rows doctrine section 6 does not admit, and because the
statistics underneath the headline had no test at all. Those defects each
survived the whole suite, which is worse than having no suite: a green run was
taken as evidence the file was safe to publish from.

So the classes below are organised by the thing that went wrong rather than by
the function that was patched:

  ProvenanceCarriedTest / PublicationCutTest -- replay and unstamped rows
    reached a headline because `record_provenance` was never carried onto the
    measurement row, so a caller could not filter it even in principle.
  StalenessInRollupsTest -- `closing_lead_stale` was computed per row and
    thrown away by every rollup, while being correlated with the answer.
  CohortCutTest -- `by_cohort` read `DecisionRecord.cohorts`, a field
    deliberately refused by `src.ledger.records`, so the cut could never
    activate and reported the wrong reason for the right emptiness.
  MeanFilterTest / StandardErrorTest / MedianTest / SignCountTest /
    StaleThresholdTest / OneSidedConsistencyTest -- each pins one mutation
    that left all 53 earlier tests green: zero-filling a withheld number,
    `return 1.0` for the standard error, the mean in place of the median,
    an eight-hour staleness threshold, `>= 0` counted as positive CLV, and
    `abs()` around the frozen-board consistency bound.

Each of those was applied to the source, watched go red, and restored.
"""

import re
import tempfile
import unittest
from pathlib import Path

from src.analysis import families as families_mod
from src.analysis import prices
from src.board.ids import MARKET_CATALOGUE, selection_id
from src.engine import slip as slip_mod
from src.ledger import records as record_contract
from src.ledger.chain import HashChainLedger
from src.report import clv
from src.report import engine_bridge

# One capture day. First pitch at 22:00Z; two pre-game captures before it and
# one in-play capture after it.
COMMENCE = "2026-09-05T22:00:00Z"
EARLY = "2026-09-05T12:00:00+00:00"
CLOSE = "2026-09-05T21:00:00+00:00"
IN_PLAY = "2026-09-05T23:00:00+00:00"
DECIDED = "2026-09-05T10:00:00+00:00"

# Two captures either side of the 90-minute staleness threshold, written as
# LITERAL stamps rather than derived from CLOSING_LEAD_STALE_SECONDS. A
# fixture built from the constant moves with the constant and would pass at
# any threshold, which is exactly how an unpinned threshold stays unpinned.
# 20:35Z is 85 minutes before first pitch; 20:25Z is 95 minutes before.
LEAD_85_MINUTES = "2026-09-05T20:35:00+00:00"
LEAD_95_MINUTES = "2026-09-05T20:25:00+00:00"

# A board of six books all quoting away -110 / home -130. De-vigged, that is
# 0.48099 away and 0.51901 home -- pinned, see the module docstring.
CLOSE_AWAY_FAIR = 0.48099
CLOSE_HOME_FAIR = 0.51901

# A board of six books all quoting away -150 / home +130: away 0.57983.
EARLY_AWAY_FAIR = 0.57983

# An EVEN board -- six books at -110/-110 -- de-vigs to exactly 0.5 a side.
# It is the only fixture here that can produce a measurement of exactly zero,
# which is the value the sign counts and the None-filters both mishandle in
# opposite directions.
EVEN_FAIR = 0.5

# Implied probabilities of the prices these tests take. -100 is a valid
# American price (`odds._validate_american`: +/-100 is even money) and implies
# exactly 0.5, which is what makes an exact-zero CLV constructible at all.
IMPLIED_PLUS_150 = 0.4
IMPLIED_MINUS_110 = 0.5238095238095238
IMPLIED_MINUS_100 = 0.5

BOOKS = ("draftkings", "fanduel", "betmgm", "caesars", "bovada", "betrivers")

PRE_COMMITMENT = clv.PROVENANCE_PRE_COMMITMENT


def _base(observed, book, event="E1", commence=COMMENCE):
    return {"observed_utc": observed, "commence_time": commence,
            "event_id": event, "home_team": "Home Club",
            "away_team": "Away Club", "book": book}


def h2h_board(observed, away=-110, home=-130, *, books=BOOKS, event="E1",
              commence=COMMENCE):
    return [dict(_base(observed, book, event, commence),
                 away_price=away, home_price=home) for book in books]


def totals_board(observed, total="8.5", over=-110, under=-130, *, books=BOOKS,
                 event="E1", commence=COMMENCE):
    return [dict(_base(observed, book, event, commence), market="totals",
                 total=total, over_price=over, under_price=under)
            for book in books]


def spreads_board(observed, home_line="-1.5", away_line="1.5", home=-110,
                  away=-130, *, books=BOOKS, event="E1", commence=COMMENCE):
    return [dict(_base(observed, book, event, commence), market="spreads",
                 home_line=home_line, home_price=home,
                 away_line=away_line, away_price=away) for book in books]


def decision(*, market_key="h2h", side="away", line=None, price=150,
             system_id="forward_thesis_1", verdict="play", event_id="E1",
             decision_utc=DECIDED, consensus_fair=None, books_at_decision=11,
             friction=None, cohorts=(), record_provenance=PRE_COMMITMENT):
    """A decision as a plain dict -- `measure_decision` reads either shape.

    The `selection_id` is minted through `src.board.ids.selection_id`, never
    hand-written, because the whole point of `side_for_selection` is that the
    side is RECOVERED from that hash rather than carried beside it.

    `record_provenance` defaults to the publishable value so the ordinary
    fixtures exercise the path a real live decision takes; every test about
    contamination sets it explicitly. `cohorts` is retained even though
    `DecisionRecord` has no such field, so `CohortCutTest` can prove the
    rollup does NOT read it.
    """
    return {
        "system_id": system_id,
        "event_id": event_id,
        "market_key": market_key,
        "selection_id": selection_id(sport="mlb", market_key=market_key,
                                     side=side, line=line),
        "line": line,
        "price_american": price,
        "book": "draftkings",
        "verdict": verdict,
        "decision_utc": decision_utc,
        "consensus_fair": consensus_fair,
        "books_at_decision": books_at_decision,
        "friction": friction,
        "cohorts": cohorts,
        "record_provenance": record_provenance,
    }


def measured(record, rows):
    return clv.measure_decision(record, clv.pregame_index(rows))


def mrow(*, clv_bps=None, move=None, standing=None, absence=None,
         move_absence=None, event_id="E1", system_id="forward_thesis_1",
         provenance=PRE_COMMITMENT, close_stale=False, market_key="h2h",
         selection=None):
    """A measurement row in the shape `measure_decision` returns.

    Hand-built ON PURPOSE for the rollup tests. `summarise` is arithmetic over
    a list of rows, and driving it through the whole measurement pipeline
    would force every value to be whatever the fixture board happens to
    de-vig to -- which is how a rollup ends up tested only on values that
    cannot distinguish a zero from an absence. The pipeline that produces
    these rows is covered end-to-end elsewhere in this file.
    """
    return {
        "system_id": system_id,
        "system_class": engine_bridge.system_class(system_id),
        "event_id": event_id,
        "market_key": market_key,
        "selection_id": selection,
        "record_provenance": provenance,
        "closing_lead_stale": close_stale,
        "clv_bps": clv_bps,
        "consensus_move_bps": move,
        "price_standing_bps": standing,
        "absence": absence,
        "move_absence": move_absence,
    }


def slip_pick(*, rank, event_id="E1", market_key="h2h", side="away",
              line=None):
    """One published pick, shaped as `slip.SlipPick.to_dict` writes it.

    `cohorts` comes from `slip.cohorts_for_rank`, not from a hand-typed list:
    the cohort nesting is that module's rule and a fixture that restated it
    would keep passing after the rule changed.
    """
    sid = selection_id(sport="mlb", market_key=market_key, side=side,
                       line=line)
    return {
        "rank": rank,
        "cohorts": list(slip_mod.cohorts_for_rank(rank)),
        "wager_id": families_mod.wager_id(event_id, market_key, sid),
        "event_id": event_id,
        "market_key": market_key,
        "selection_id": sid,
        "line": line,
        "book": "draftkings",
        "price_american": 150,
    }


def slip_row(*, date="2026-09-05", slip_utc="2026-09-05T20:00:00+00:00",
             picks=()):
    return {
        "date": date,
        "slip_utc": slip_utc,
        "rule": slip_mod.SLIP_RULE,
        "basis": slip_mod.SLIP_BASIS,
        "cohort_cuts": dict(slip_mod.COHORT_CUTS),
        "picks": list(picks),
        "misses": [],
        "n_picks": len(picks),
        "n_misses": 0,
        "n_instrument_plays": 0,
    }


class MarketShapeTest(unittest.TestCase):
    """The one declared mapping from a market's sides onto the de-vig."""

    def test_declared_sides_match_the_market_catalogue(self):
        for market_key, shape in clv.MARKET_SHAPES.items():
            spec = MARKET_CATALOGUE[market_key]
            self.assertEqual(set(shape.sides), set(spec.sides), market_key)

    def test_each_market_maps_its_two_sides_onto_the_two_devig_slots(self):
        for market_key, shape in clv.MARKET_SHAPES.items():
            slots = sorted(s.slot for s in shape.sides.values())
            self.assertEqual(slots, ["away", "home"], market_key)

    def test_book_floor_is_the_projects_single_floor(self):
        self.assertEqual(clv.MIN_BOOKS, prices.MIN_BOOKS)


class AbsenceVocabularyTest(unittest.TestCase):
    def test_every_absence_token_has_a_reason(self):
        for token, reason in clv.ABSENCE_REASONS.items():
            self.assertTrue(reason and reason.strip(), token)

    def test_an_unnamed_absence_is_a_programming_error(self):
        with self.assertRaises(clv.ClvError):
            clv._absent("NOT_A_REAL_REASON")


class PregameIndexTest(unittest.TestCase):
    def test_an_in_play_capture_is_never_the_close(self):
        rows = h2h_board(CLOSE) + h2h_board(IN_PLAY, away=-10000, home=900)
        result = measured(decision(), rows)
        self.assertEqual(result["closing_observed_utc"], CLOSE)

    def test_a_capture_after_a_revised_earlier_first_pitch_is_dropped(self):
        # The feed later says first pitch was 20:00, not 22:00. The 21:00
        # capture passed the per-row test against the stale 22:00 it carried,
        # and is in fact post-commencement.
        rows = (h2h_board(EARLY)
                + h2h_board(CLOSE)
                + h2h_board(IN_PLAY, commence="2026-09-05T20:00:00Z"))
        result = measured(decision(), rows)
        self.assertEqual(result["closing_observed_utc"], EARLY)

    def test_a_missing_store_is_an_empty_index_not_an_exception(self):
        self.assertEqual(clv.pregame_index([]), {})

    def test_rows_with_no_event_id_are_dropped(self):
        rows = [dict(row, event_id=None) for row in h2h_board(CLOSE)]
        self.assertEqual(clv.pregame_index(rows), {})


class ClosingBoardTest(unittest.TestCase):
    def test_the_closing_instant_is_the_markets_last_pregame_capture(self):
        rows = h2h_board(EARLY, away=-150, home=130) + h2h_board(CLOSE)
        result = measured(decision(), rows)
        self.assertEqual(result["closing_observed_utc"], CLOSE)
        self.assertEqual(result["closing_probability"], CLOSE_AWAY_FAIR)

    def test_a_market_that_closed_on_another_line_is_thin_not_an_older_board(self):
        # Taken Over 8.0; the market's last pre-game board quotes 8.5 only.
        # Answering from the 8.0 board captured nine hours earlier would be
        # calling a stale board "the close" -- and would compare two bets.
        rows = totals_board(EARLY, total="8.0") + totals_board(CLOSE, total="8.5")
        result = measured(decision(market_key="totals", side="over",
                                   line="8.0"), rows)
        self.assertIsNone(result["clv_bps"])
        self.assertEqual(result["absence"], clv.CLOSING_BOARD_THIN)

    def test_a_mixed_market_store_does_not_leak_rows_across_boards(self):
        # The store has carried spreads and totals beside h2h since
        # 2026-09-03, and every one of them is written at the SAME capture
        # instant. A board reader that takes the newest row per book without
        # asking which market a row belongs to lets a book's totals row (no
        # away/home price) stand where its moneyline should be -- that is the
        # bug that made every game on /odds read "9 books, no consensus" on
        # 2026-09-07. Each of the three decisions below must see only its own
        # market's eleven-book board.
        rows = (h2h_board(CLOSE, away=-110, home=-130)
                + totals_board(CLOSE, total="8.5", over=-150, under=130)
                + spreads_board(CLOSE, home_line="-1.5", away_line="1.5",
                                home=-150, away=130))
        moneyline = measured(decision(side="away", price=150), rows)
        self.assertEqual(moneyline["closing_books"], len(BOOKS))
        self.assertEqual(moneyline["closing_probability"], CLOSE_AWAY_FAIR)

        total = measured(decision(market_key="totals", side="over",
                                  line="8.5", price=150), rows)
        self.assertEqual(total["closing_books"], len(BOOKS))
        self.assertEqual(total["closing_probability"], EARLY_AWAY_FAIR)

        spread = measured(decision(market_key="spreads", side="away",
                                   line="1.5", price=150), rows)
        self.assertEqual(spread["closing_books"], len(BOOKS))
        # away quoted +130 against home -150: the away side de-vigs to
        # 1 - 0.57983 = 0.42017.
        self.assertEqual(spread["closing_probability"], 0.42017)

    def test_a_board_below_the_book_floor_is_a_named_absence(self):
        rows = h2h_board(CLOSE, books=BOOKS[:clv.MIN_BOOKS - 1])
        result = measured(decision(), rows)
        self.assertIsNone(result["clv_bps"])
        self.assertEqual(result["absence"], clv.CLOSING_BOARD_THIN)
        self.assertIn("floor", result["absence_reason"] + str(result.get("detail")))

    def test_a_board_at_exactly_the_floor_is_measured(self):
        rows = h2h_board(CLOSE, books=BOOKS[:clv.MIN_BOOKS])
        result = measured(decision(), rows)
        self.assertEqual(result["closing_books"], clv.MIN_BOOKS)
        self.assertIsNotNone(result["clv_bps"])

    def test_an_unknown_commence_time_refuses_rather_than_guessing(self):
        entry = {"rows": h2h_board(CLOSE), "commence_time": None}
        board = clv.closing_board(entry, "h2h", "away", None)
        self.assertEqual(board["absence"], clv.COMMENCE_TIME_UNKNOWN)

    def test_lead_before_first_pitch_is_recorded(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(), rows)
        self.assertEqual(result["closing_lead_seconds"], 3600.0)
        self.assertFalse(result["closing_lead_stale"])

    def test_a_board_hours_from_first_pitch_is_flagged_but_still_the_close(self):
        rows = h2h_board(EARLY)
        result = measured(decision(), rows)
        self.assertEqual(result["closing_observed_utc"], EARLY)
        self.assertTrue(result["closing_lead_stale"])
        self.assertIsNotNone(result["clv_bps"])


class StaleThresholdTest(unittest.TestCase):
    """CLOSING_LEAD_STALE_SECONDS, pinned as a value AND as a behaviour.

    SURVIVING MUTATION THIS KILLS: moving the constant to `8 * 3600`. That
    edit left all 53 earlier tests green and, on the live ledger, took
    `close_stale` from 265 rows to zero -- every one of those rows silently
    promoted into the published cut without a single measurement changing.
    A threshold nobody's test pins is a threshold that can be tuned until the
    answer is friendly.
    """

    def test_the_threshold_is_ninety_minutes(self):
        self.assertEqual(clv.CLOSING_LEAD_STALE_SECONDS, 90 * 60)

    def test_a_board_eighty_five_minutes_before_first_pitch_is_fresh(self):
        rows = h2h_board(LEAD_85_MINUTES)
        result = measured(decision(), rows)
        self.assertEqual(result["closing_lead_seconds"], 85 * 60.0)
        self.assertFalse(result["closing_lead_stale"])
        self.assertEqual(clv.close_segment(result), clv.SEG_CLOSE_FRESH)

    def test_a_board_ninety_five_minutes_before_first_pitch_is_stale(self):
        rows = h2h_board(LEAD_95_MINUTES)
        result = measured(decision(), rows)
        self.assertEqual(result["closing_lead_seconds"], 95 * 60.0)
        self.assertTrue(result["closing_lead_stale"])
        self.assertEqual(clv.close_segment(result), clv.SEG_CLOSE_STALE)

    def test_the_flag_never_suppresses_the_measurement_itself(self):
        # Staleness decides publication, never measurability. A module that
        # dropped stale rows outright would be answering a different question
        # and would lose the evidence that they behave differently.
        stale = measured(decision(), h2h_board(LEAD_95_MINUTES))
        self.assertIsNotNone(stale["clv_bps"])
        self.assertEqual(stale["clv_bps"], 809.9)


class ClvArithmeticTest(unittest.TestCase):
    def test_positive_when_the_close_is_better_than_the_number_taken(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="away", price=150), rows)
        self.assertEqual(
            result["clv_bps"],
            round((CLOSE_AWAY_FAIR - IMPLIED_PLUS_150) * 10000, 4))
        self.assertEqual(result["clv_bps"], 809.9)

    def test_negative_clv_is_reported_as_measured_not_suppressed(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110), rows)
        self.assertEqual(
            result["clv_bps"],
            round((CLOSE_HOME_FAIR - IMPLIED_MINUS_110) * 10000, 4))
        self.assertLess(result["clv_bps"], 0)

    def test_the_side_is_recovered_from_the_selection_id_not_assumed(self):
        # Same board, same price, opposite sides. A module that read a fixed
        # slot instead of recovering the side would return the same number
        # twice.
        rows = h2h_board(CLOSE)
        away = measured(decision(side="away", price=-110), rows)
        home = measured(decision(side="home", price=-110), rows)
        self.assertEqual(away["side"], "away")
        self.assertEqual(home["side"], "home")
        self.assertEqual(away["closing_probability"], CLOSE_AWAY_FAIR)
        self.assertEqual(home["closing_probability"], CLOSE_HOME_FAIR)
        self.assertNotEqual(away["clv_bps"], home["clv_bps"])

    def test_over_and_under_are_not_swapped_onto_the_devigs_two_slots(self):
        rows = totals_board(CLOSE, total="8.5", over=-110, under=-130)
        over = measured(decision(market_key="totals", side="over",
                                 line="8.5", price=150), rows)
        under = measured(decision(market_key="totals", side="under",
                                  line="8.5", price=150), rows)
        self.assertEqual(over["closing_probability"], CLOSE_AWAY_FAIR)
        self.assertEqual(under["closing_probability"], CLOSE_HOME_FAIR)
        self.assertEqual(over["clv_bps"], 809.9)

    def test_a_spread_reads_the_board_quoting_the_line_it_took(self):
        rows = (spreads_board(CLOSE, home_line="-1.5", away_line="1.5",
                              home=-110, away=-130)
                + spreads_board(CLOSE, home_line="-2.5", away_line="2.5",
                                home=200, away=-260,
                                books=("betus", "lowvig", "espnbet")))
        result = measured(decision(market_key="spreads", side="home",
                                   line="-1.5", price=150), rows)
        # -110/-130 with home in the home slot: the home side de-vigs to
        # 0.48099 because the module maps home_price onto the home slot and
        # this board quotes home at -110.
        self.assertEqual(result["closing_probability"], CLOSE_AWAY_FAIR)
        self.assertEqual(result["closing_books"], len(BOOKS))

    def test_price_that_is_not_a_valid_american_number_is_refused(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(price=50), rows)
        self.assertIsNone(result["clv_bps"])
        self.assertEqual(result["absence"], clv.PRICE_NOT_CONVERTIBLE)

    def test_a_close_that_lands_on_the_number_taken_measures_exactly_zero(self):
        # An even board (-110/-110 -> 0.5 a side) against an even-money price
        # (-100 -> 0.5). The close agreed exactly with what we took: a real,
        # measured, middling result, and the only fixture in this file that
        # can tell a zero apart from an absence.
        rows = h2h_board(CLOSE, away=-110, home=-110)
        result = measured(decision(side="away", price=-100), rows)
        self.assertEqual(result["closing_probability"], EVEN_FAIR)
        self.assertEqual(result["clv_bps"], 0.0)
        self.assertIsNone(result.get("absence"))


class DegenerateOrderingTest(unittest.TestCase):
    """The two orderings that would turn price standing into 'CLV'."""

    def test_a_close_that_is_the_decisions_own_board_is_refused(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(decision_utc=CLOSE), rows)
        self.assertIsNone(result["clv_bps"])
        self.assertEqual(result["absence"],
                         clv.CLOSING_BOARD_IS_DECISION_BOARD)
        # The identity is still reported so a reader can see WHY it was
        # refused rather than having to trust the token.
        self.assertEqual(result["seconds_from_decision_to_close"], 0.0)

    def test_a_close_older_than_the_decision_is_refused(self):
        rows = h2h_board(EARLY)
        result = measured(decision(decision_utc=CLOSE), rows)
        self.assertIsNone(result["clv_bps"])
        self.assertEqual(result["absence"], clv.CLOSE_PRECEDES_DECISION)
        self.assertLess(result["seconds_from_decision_to_close"], 0)

    def test_a_close_one_second_after_the_decision_is_measured(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(decision_utc="2026-09-05T20:59:59+00:00"),
                          rows)
        self.assertEqual(result["seconds_from_decision_to_close"], 1.0)
        self.assertIsNotNone(result["clv_bps"])


class NotABetTest(unittest.TestCase):
    def test_a_refused_candidate_is_an_absence_never_a_zero(self):
        rows = h2h_board(CLOSE)
        for verdict in ("refused_thin", "refused_stale", "refused_vetoed"):
            result = measured(decision(verdict=verdict), rows)
            self.assertIsNone(result["clv_bps"], verdict)
            self.assertEqual(result["absence"], clv.NOT_A_BET, verdict)

    def test_a_row_with_no_price_is_an_absence_never_a_zero(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(price=None), rows)
        self.assertIsNone(result["clv_bps"])
        self.assertEqual(result["absence"], clv.NO_PRICE_TAKEN)

    def test_an_uncaptured_market_is_named_not_skipped_silently(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(market_key="h2h_1st_5_innings",
                                   side="home"), rows)
        self.assertEqual(result["absence"], clv.MARKET_NOT_CAPTURED)

    def test_an_event_absent_from_the_store_is_named(self):
        rows = h2h_board(CLOSE, event="OTHER")
        result = measured(decision(event_id="E1"), rows)
        self.assertEqual(result["absence"], clv.EVENT_NOT_IN_STORE)

    def test_a_selection_id_that_names_no_declared_side_is_named(self):
        rows = h2h_board(CLOSE)
        record = decision()
        record["selection_id"] = "0" * 16
        result = measured(record, rows)
        self.assertEqual(result["absence"], clv.SIDE_NOT_RECOVERABLE)


class VigDecompositionTest(unittest.TestCase):
    """clv_bps = consensus_move_bps + price_standing_bps, exactly."""

    def test_the_identity_holds(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.52,
                                   books_at_decision=11,
                                   friction={"dispersion": 0.05, "vig": 0.04}),
                          rows)
        self.assertAlmostEqual(
            result["clv_bps"],
            result["consensus_move_bps"] + result["price_standing_bps"],
            places=6)
        self.assertEqual(result["price_standing_bps"],
                         round((0.52 - IMPLIED_MINUS_110) * 10000, 4))
        self.assertEqual(result["consensus_move_bps"],
                         round((CLOSE_HOME_FAIR - 0.52) * 10000, 4))

    def test_the_move_is_zero_sum_across_a_two_way_market(self):
        # The de-vigged consensus of the two sides sums to 1 at both instants,
        # so whatever one side gained the other lost. A slot mix-up breaks it.
        rows = h2h_board(CLOSE)
        away = measured(decision(side="away", price=150, consensus_fair=0.45,
                                 friction={"dispersion": 0.1}), rows)
        home = measured(decision(side="home", price=-110, consensus_fair=0.55,
                                 friction={"dispersion": 0.1}), rows)
        self.assertAlmostEqual(
            away["consensus_move_bps"] + home["consensus_move_bps"], 0.0,
            places=6)

    def test_companion_withheld_when_the_decision_board_was_thin(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.52,
                                   books_at_decision=clv.MIN_BOOKS - 1), rows)
        self.assertIsNotNone(result["clv_bps"])
        self.assertIsNone(result["consensus_move_bps"])
        self.assertEqual(result["move_absence"], clv.DECISION_BOARD_THIN)

    def test_companion_withheld_when_the_decision_froze_no_consensus(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=None), rows)
        self.assertIsNotNone(result["clv_bps"])
        self.assertEqual(result["move_absence"],
                         clv.DECISION_CONSENSUS_MISSING)

    def test_companion_withheld_when_the_frozen_fields_contradict(self):
        # consensus_fair 0.70 against a -110 price implies the best number on
        # the board beat its own consensus by 1,762bps while the board's whole
        # spread was 200bps. No single board produces that.
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.70,
                                   friction={"dispersion": 0.02}), rows)
        self.assertIsNotNone(result["clv_bps"])
        self.assertIsNone(result["consensus_move_bps"])
        self.assertIsNone(result["price_standing_bps"])
        self.assertEqual(result["move_absence"],
                         clv.DECISION_CONSENSUS_INCONSISTENT)

    def test_a_standing_inside_the_boards_own_spread_is_kept(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.53,
                                   friction={"dispersion": 0.02}), rows)
        self.assertIsNotNone(result["consensus_move_bps"])
        self.assertIsNone(result["move_absence"])

    def test_an_unrunnable_consistency_check_is_not_a_failed_one(self):
        self.assertFalse(clv.standing_exceeds_frozen_board(9999.0, None))
        self.assertFalse(clv.standing_exceeds_frozen_board(9999.0, {}))
        self.assertFalse(clv.standing_exceeds_frozen_board(None,
                                                           {"dispersion": 0.0}))


class OneSidedConsistencyTest(unittest.TestCase):
    """`standing_exceeds_frozen_board` is one-sided, and that is a judgement.

    SURVIVING MUTATION THIS KILLS: `abs(price_standing_bps) > dispersion *
    BPS_PER_PROBABILITY_UNIT`. It reads like a symmetry fix and passed every
    earlier test, because every fixture that exercised the check used a
    POSITIVE standing. The bound the module derives only holds upward
    (consensus_fair <= best book's raw implied + dispersion); the mirror bound
    needs the LARGEST per-book margin and the record freezes only the mean
    one. Adding `abs()` would start withholding the vig-neutral split from an
    ordinary population of rows whose taken price simply beat its own frozen
    consensus, on the strength of a bound this record cannot support.
    """

    def test_a_large_negative_standing_is_not_a_contradiction(self):
        # -9,999bps against a 200bps board. Under `>` this is not a
        # contradiction and the split stands; under `abs(...) >` it is.
        self.assertFalse(
            clv.standing_exceeds_frozen_board(-9999.0, {"dispersion": 0.02}))

    def test_the_same_magnitude_positive_is_a_contradiction(self):
        # The mirror of the case above, so the test cannot pass by the check
        # being disabled altogether.
        self.assertTrue(
            clv.standing_exceeds_frozen_board(9999.0, {"dispersion": 0.02}))

    def test_a_standing_exactly_at_the_dispersion_is_not_a_contradiction(self):
        # The derived inequality is `standing <= dispersion`, so equality is
        # the boundary it permits. `>=` here would flag the exact case the
        # arithmetic says is legal.
        self.assertFalse(
            clv.standing_exceeds_frozen_board(200.0, {"dispersion": 0.02}))
        self.assertTrue(
            clv.standing_exceeds_frozen_board(200.0001, {"dispersion": 0.02}))

    def test_a_decision_whose_price_beat_its_frozen_consensus_keeps_its_split(self):
        # End-to-end: consensus_fair 0.30 against a -110 price implies a
        # standing of -2,238bps, far outside the frozen board's 200bps
        # dispersion on the low side. That is an ordinary row and it must keep
        # both companion numbers.
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.30,
                                   friction={"dispersion": 0.02}), rows)
        self.assertIsNone(result["move_absence"])
        self.assertEqual(result["price_standing_bps"],
                         round((0.30 - IMPLIED_MINUS_110) * 10000, 4))
        self.assertIsNotNone(result["consensus_move_bps"])


class DecisionBoardClaimTest(unittest.TestCase):
    """An unknown book count is ignorance, not a finding of a thin board.

    DEFECT THIS PINS: `DECISION_BOARD_THIN` was returned both when
    `books_at_decision` was below the floor AND when it was None, while its
    reason asserts "the decision was frozen against fewer than 6 books". On a
    row carrying no count at all that sentence is a claim about data nobody
    has, which is the same class of error as filling a missing number with a
    zero -- an invented fact wearing the clothes of a measurement.
    """

    def test_an_absent_book_count_is_named_as_unknown(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.52,
                                   books_at_decision=None), rows)
        self.assertIsNotNone(result["clv_bps"])
        self.assertIsNone(result["consensus_move_bps"])
        self.assertEqual(result["move_absence"],
                         clv.DECISION_BOOK_COUNT_UNKNOWN)

    def test_a_known_thin_board_still_reports_a_thin_board(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.52,
                                   books_at_decision=clv.MIN_BOOKS - 1), rows)
        self.assertEqual(result["move_absence"], clv.DECISION_BOARD_THIN)

    def test_a_board_exactly_at_the_floor_is_not_thin(self):
        rows = h2h_board(CLOSE)
        result = measured(decision(side="home", price=-110,
                                   consensus_fair=0.52,
                                   books_at_decision=clv.MIN_BOOKS,
                                   friction={"dispersion": 0.05}), rows)
        self.assertIsNone(result["move_absence"])

    def test_the_two_reasons_do_not_make_the_same_claim(self):
        thin = clv.ABSENCE_REASONS[clv.DECISION_BOARD_THIN]
        unknown = clv.ABSENCE_REASONS[clv.DECISION_BOOK_COUNT_UNKNOWN]
        self.assertIn("fewer than", thin)
        # The whole point of the split: the unknown case must never assert a
        # count it does not have.
        self.assertNotIn("fewer than", unknown)
        self.assertIn("unknown", unknown)


class ProvenanceCarriedTest(unittest.TestCase):
    """`record_provenance` reaches the measurement row, verbatim.

    DEFECT THIS PINS: the published version of this module ignored
    `record_provenance` entirely and did not carry it onto the row, so a
    caller could not filter replays out of a rollup even in principle. On the
    live ledger that pooled 125 replay rows -- some written up to 33 hours
    after the game -- and 818 unstamped ones into the same pool as the
    pre-commitment decisions.
    """

    def test_every_provenance_value_is_carried_verbatim(self):
        rows = h2h_board(CLOSE)
        for value in (clv.PROVENANCE_PRE_COMMITMENT,
                      clv.PROVENANCE_POST_COMMENCEMENT,
                      clv.PROVENANCE_REPLAY,
                      None):
            result = measured(decision(record_provenance=value), rows)
            self.assertEqual(result["record_provenance"], value, value)

    def test_provenance_is_carried_on_refused_rows_too(self):
        # A caller filtering a published rollup needs the field on the rows
        # this module refused as much as on the ones it measured, or the
        # absence tallies are computed over a different population than the
        # means beside them.
        rows = h2h_board(CLOSE)
        result = measured(decision(verdict="refused_thin",
                                   record_provenance=clv.PROVENANCE_REPLAY),
                          rows)
        self.assertEqual(result["absence"], clv.NOT_A_BET)
        self.assertEqual(result["record_provenance"], clv.PROVENANCE_REPLAY)

    def test_the_provenance_values_are_the_record_contracts_own(self):
        # Imported, never redeclared. A typo in a re-typed string would leave
        # the publication filter matching nothing while still looking correct.
        self.assertEqual(clv.PROVENANCE_PRE_COMMITMENT,
                         record_contract.RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT)
        self.assertEqual(clv.PROVENANCE_POST_COMMENCEMENT,
                         record_contract.RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT)
        self.assertEqual(clv.PROVENANCE_REPLAY,
                         record_contract.RECORD_PROVENANCE_REPLAY)
        self.assertEqual(
            set(clv.PROVENANCE_SEGMENTS) - {clv.PROVENANCE_UNSTAMPED},
            set(record_contract.RECORD_PROVENANCE_VALUES))

    def test_an_unstamped_row_is_not_called_a_replay(self):
        # `records.py`: a row with no stamp "carries no evidence either way".
        # Filing it as a replay would assert a backfill nobody observed.
        row = mrow(clv_bps=10.0, provenance=None)
        self.assertEqual(clv.provenance_segment(row),
                         clv.SEG_PROVENANCE_UNSTAMPED)
        self.assertNotEqual(clv.provenance_segment(row),
                            clv.SEG_PROVENANCE_REPLAY)


class PublicationCutTest(unittest.TestCase):
    """Doctrine section 6, enforced as a filter rather than as prose.

    "Only settled, published, FORWARD_TEST rows. No backtests, replays,
    unpublished positions or controls." A replay row and an unstamped row are
    both barred, and so is a pre-commitment row measured against a board that
    is not really the close.
    """

    def test_only_pre_commitment_provenance_is_publishable(self):
        self.assertEqual(clv.PUBLISHABLE_PROVENANCE,
                         frozenset({clv.PROVENANCE_PRE_COMMITMENT}))

    def test_a_replay_row_is_barred_however_fresh_its_close(self):
        row = mrow(clv_bps=500.0, provenance=clv.PROVENANCE_REPLAY,
                   close_stale=False)
        self.assertFalse(clv.is_publishable(row))

    def test_an_unstamped_row_is_barred(self):
        self.assertFalse(clv.is_publishable(
            mrow(clv_bps=500.0, provenance=None, close_stale=False)))

    def test_a_post_commencement_row_is_barred(self):
        self.assertFalse(clv.is_publishable(
            mrow(clv_bps=500.0, provenance=clv.PROVENANCE_POST_COMMENCEMENT,
                 close_stale=False)))

    def test_a_stale_close_is_barred_even_on_a_pre_commitment_row(self):
        self.assertFalse(clv.is_publishable(
            mrow(clv_bps=500.0, provenance=PRE_COMMITMENT, close_stale=True)))

    def test_a_row_with_no_close_at_all_is_barred(self):
        self.assertFalse(clv.is_publishable(
            mrow(absence=clv.NOT_A_BET, provenance=PRE_COMMITMENT,
                 close_stale=None)))

    def test_a_pre_commitment_row_with_a_fresh_close_is_publishable(self):
        self.assertTrue(clv.is_publishable(
            mrow(clv_bps=500.0, provenance=PRE_COMMITMENT, close_stale=False)))

    def test_the_published_rollup_excludes_the_contaminated_rows(self):
        # Three measurable rows, one publishable. Pooling them gives 400.0;
        # the published cut is the clean row alone at 100.0. The pooled mean
        # is what got retracted.
        group = [
            mrow(clv_bps=100.0, provenance=PRE_COMMITMENT, event_id="E1"),
            mrow(clv_bps=400.0, provenance=clv.PROVENANCE_REPLAY,
                 event_id="E2"),
            mrow(clv_bps=700.0, provenance=None, event_id="E3"),
        ]
        pooled = clv.summarise(group)
        self.assertEqual(pooled["n_measured"], 3)
        self.assertEqual(pooled["clv_bps_mean"], 400.0)
        self.assertEqual(pooled["n_publishable"], 1)

        published = clv.summarise(clv.publishable(group))
        self.assertEqual(published["n_measured"], 1)
        self.assertEqual(published["clv_bps_mean"], 100.0)

    def test_a_contaminated_group_says_so_on_the_rollup_itself(self):
        group = [mrow(clv_bps=100.0, provenance=PRE_COMMITMENT),
                 mrow(clv_bps=400.0, provenance=clv.PROVENANCE_REPLAY)]
        caveat = clv.summarise(group)["publication_caveat"]
        self.assertIsNotNone(caveat)
        self.assertIn("1 of 2", caveat)

    def test_a_clean_group_carries_no_caveat(self):
        group = [mrow(clv_bps=100.0), mrow(clv_bps=300.0)]
        summary = clv.summarise(group)
        self.assertIsNone(summary["publication_caveat"])
        self.assertEqual(summary["n_publishable"], 2)

    def test_the_report_carries_the_published_cut_and_its_rule(self):
        rows = h2h_board(CLOSE)
        report = clv.report(
            decisions=[decision(side="away", price=150),
                       decision(side="away", price=150, event_id="E1",
                                system_id="forward_thesis_2",
                                record_provenance=clv.PROVENANCE_REPLAY)],
            rows=rows, slips=[])
        self.assertEqual(report["n_published"], 1)
        self.assertEqual(report["published"]["n_measured"], 1)
        self.assertIsNone(report["published"]["publication_caveat"])
        self.assertIn("replays", report["publication_rule"])
        self.assertIsNotNone(report["overall"]["publication_caveat"])


class StalenessInRollupsTest(unittest.TestCase):
    """Staleness reaches every rollup, because every rollup goes through
    `summarise` and `summarise` segments on it.

    DEFECT THIS PINS: `closing_lead_stale` was computed on each row and then
    discarded -- `summarise` had no stale key at all -- so a headline
    published 265 rows calling a board up to 6.5 hours before first pitch
    "the close", and those rows do not carry the same mean as the fresh ones
    (-128.0 vs -102.6 bps on the live ledger).
    """

    def test_summarise_segments_the_stale_rows_from_the_fresh_ones(self):
        group = [mrow(clv_bps=-100.0, close_stale=False, event_id="E1"),
                 mrow(clv_bps=-100.0, close_stale=False, event_id="E2"),
                 mrow(clv_bps=-400.0, close_stale=True, event_id="E3")]
        summary = clv.summarise(group)
        self.assertEqual(summary["clv_bps_mean"], -200.0)
        self.assertEqual(summary["segments"][clv.SEG_CLOSE_FRESH]["n_measured"], 2)
        self.assertEqual(summary["segments"][clv.SEG_CLOSE_FRESH]["clv_bps_mean"],
                         -100.0)
        self.assertEqual(summary["segments"][clv.SEG_CLOSE_STALE]["n_measured"], 1)
        self.assertEqual(summary["segments"][clv.SEG_CLOSE_STALE]["clv_bps_mean"],
                         -400.0)

    def test_every_cut_in_the_report_carries_the_segments(self):
        rows = h2h_board(CLOSE) + h2h_board(EARLY, event="E2")
        report = clv.report(
            decisions=[decision(side="away", price=150, event_id="E1"),
                       decision(side="away", price=150, event_id="E2")],
            rows=rows, slips=[])
        cuts = [report["overall"], report["eligible"], report["published"]]
        cuts += list(report["by_system_class"].values())
        cuts += list(report["by_system"].values())
        cuts += list(report["by_market"].values())
        for summary in cuts:
            self.assertIn("segments", summary)
            self.assertIn(clv.SEG_CLOSE_STALE, summary["segments"])
            self.assertIn(clv.SEG_CLOSE_FRESH, summary["segments"])
            self.assertIn(clv.SEG_PUBLISHABLE, summary["segments"])

    def test_the_stale_row_is_the_one_measured_against_the_early_board(self):
        # End-to-end rather than hand-built: the E2 board is captured ten
        # hours before first pitch, so its row must land in the stale segment
        # and out of the published cut.
        rows = h2h_board(CLOSE) + h2h_board(EARLY, event="E2")
        report = clv.report(
            decisions=[decision(side="away", price=150, event_id="E1"),
                       decision(side="away", price=150, event_id="E2")],
            rows=rows, slips=[])
        overall = report["overall"]
        self.assertEqual(overall["n_measured"], 2)
        self.assertEqual(overall["segments"][clv.SEG_CLOSE_STALE]["n_measured"], 1)
        self.assertEqual(report["n_published"], 1)
        self.assertEqual(report["published"]["n_games"], 1)

    def test_each_axis_of_segments_partitions_the_group(self):
        # A partition can be checked; a bag of flags cannot. If a row ever
        # falls out of the accounting, these sums stop matching.
        group = [
            mrow(clv_bps=1.0, provenance=PRE_COMMITMENT, close_stale=False),
            mrow(clv_bps=2.0, provenance=clv.PROVENANCE_REPLAY,
                 close_stale=True),
            mrow(clv_bps=3.0, provenance=None, close_stale=False),
            mrow(absence=clv.NOT_A_BET,
                 provenance=clv.PROVENANCE_POST_COMMENCEMENT,
                 close_stale=None),
        ]
        seg = clv.summarise(group)["segments"]
        provenance_axis = [clv.SEG_PROVENANCE_PRE_COMMITMENT,
                           clv.SEG_PROVENANCE_POST_COMMENCEMENT,
                           clv.SEG_PROVENANCE_REPLAY,
                           clv.SEG_PROVENANCE_UNSTAMPED]
        close_axis = [clv.SEG_CLOSE_FRESH, clv.SEG_CLOSE_STALE,
                      clv.SEG_CLOSE_NOT_ESTABLISHED]
        self.assertEqual(sum(seg[n]["n_decisions"] for n in provenance_axis),
                         len(group))
        self.assertEqual(sum(seg[n]["n_decisions"] for n in close_axis),
                         len(group))
        self.assertEqual(seg[clv.SEG_PUBLISHABLE]["n_decisions"], 1)

    def test_every_segment_is_present_even_when_empty(self):
        # "This ledger holds no replays" and "this rollup forgot to look" are
        # different statements and must not render identically.
        seg = clv.summarise([mrow(clv_bps=1.0)])["segments"]
        self.assertEqual(set(seg), set(clv.SEGMENT_NOTES))
        self.assertEqual(seg[clv.SEG_PROVENANCE_REPLAY]["n_decisions"], 0)
        self.assertIsNone(seg[clv.SEG_PROVENANCE_REPLAY]["clv_bps_mean"])

    def test_every_segment_carries_the_note_saying_what_it_is(self):
        seg = clv.summarise([mrow(clv_bps=1.0)])["segments"]
        for name, block in seg.items():
            self.assertEqual(block["segment_note"], clv.SEGMENT_NOTES[name])

    def test_segments_do_not_recurse(self):
        # One level deep, deliberately: a segment of a segment is the same
        # rows again and would grow the payload without adding a fact.
        seg = clv.summarise([mrow(clv_bps=1.0)])["segments"]
        self.assertNotIn("segments", seg[clv.SEG_PUBLISHABLE])


class MeanFilterTest(unittest.TestCase):
    """Nothing is zero-filled, and nothing real is dropped for being zero.

    SURVIVING MUTATION THIS KILLS: replacing `if r.get(k) is not None` with
    `r.get(k) or 0.0`. On the live ledger that moved
    `price_standing_bps_mean` from -107.79 to -91.97 by inventing 86 numbers
    -- the module's own headline doctrinal claim, unguarded. The mirror
    mutation, `if r.get(k)`, drops a genuine zero instead. Both are tested,
    because they push the answer in opposite directions and a fixture that
    only catches one leaves the other free.
    """

    def test_a_withheld_price_standing_is_never_zero_filled(self):
        group = [mrow(clv_bps=-200.0, standing=-200.0),
                 mrow(clv_bps=-200.0, standing=None,
                      move_absence=clv.DECISION_CONSENSUS_MISSING,
                      event_id="E2")]
        summary = clv.summarise(group)
        self.assertEqual(summary["n_measured"], 2)
        self.assertEqual(summary["price_standing_bps_n"], 1)
        self.assertEqual(summary["price_standing_bps_mean"], -200.0)

    def test_a_withheld_consensus_move_is_never_zero_filled(self):
        group = [mrow(clv_bps=-200.0, move=-200.0),
                 mrow(clv_bps=-200.0, move=None,
                      move_absence=clv.DECISION_BOARD_THIN, event_id="E2")]
        summary = clv.summarise(group)
        self.assertEqual(summary["consensus_move_bps_n"], 1)
        self.assertEqual(summary["consensus_move_bps_mean"], -200.0)

    def test_a_genuine_zero_price_standing_is_counted(self):
        # Zero is a real, middling standing -- the price we took implied
        # exactly the consensus the decision froze. A truthiness filter drops
        # it and the mean then reports only the losers.
        group = [mrow(clv_bps=-200.0, standing=0.0),
                 mrow(clv_bps=-200.0, standing=-200.0, event_id="E2")]
        summary = clv.summarise(group)
        self.assertEqual(summary["price_standing_bps_n"], 2)
        self.assertEqual(summary["price_standing_bps_mean"], -100.0)

    def test_a_genuine_zero_clv_is_a_measured_row(self):
        summary = clv.summarise([mrow(clv_bps=0.0)])
        self.assertEqual(summary["n_measured"], 1)
        self.assertEqual(summary["clv_bps_mean"], 0.0)
        self.assertIsNotNone(summary["clv_bps_mean"])

    def test_a_genuine_zero_consensus_move_is_counted(self):
        group = [mrow(clv_bps=0.0, move=0.0),
                 mrow(clv_bps=-200.0, move=-200.0, event_id="E2")]
        summary = clv.summarise(group)
        self.assertEqual(summary["consensus_move_bps_n"], 2)
        self.assertEqual(summary["consensus_move_bps_mean"], -100.0)

    def test_end_to_end_a_measured_zero_survives_the_whole_pipeline(self):
        # The even board again, through `report` rather than through a
        # hand-built row, so the None-filters are exercised on values the
        # measurement code actually produced.
        rows = h2h_board(CLOSE, away=-110, home=-110)
        report = clv.report(
            decisions=[decision(side="away", price=-100, consensus_fair=0.5,
                                friction={"dispersion": 0.05})],
            rows=rows, slips=[])
        overall = report["overall"]
        self.assertEqual(overall["n_measured"], 1)
        self.assertEqual(overall["clv_bps_mean"], 0.0)
        self.assertEqual(overall["price_standing_bps_n"], 1)
        self.assertEqual(overall["price_standing_bps_mean"], 0.0)
        self.assertEqual(overall["consensus_move_bps_n"], 1)


class SignCountTest(unittest.TestCase):
    """Positive, zero and negative are three columns, not two.

    SURVIVING MUTATION THIS KILLS: `sum(1 for v in clv if v >= 0)` for
    `clv_bps_positive`. A CLV of exactly zero means the close landed on the
    number we took -- real, measured, and emphatically not evidence the
    selection carried information. Counting it as positive inflates the one
    statistic ("n of m positive") the published conclusion is stated in.
    """

    def test_a_zero_is_neither_positive_nor_negative(self):
        summary = clv.summarise([mrow(clv_bps=0.0)])
        self.assertEqual(summary["clv_bps_positive"], 0)
        self.assertEqual(summary["clv_bps_zero"], 1)
        self.assertEqual(summary["clv_bps_negative"], 0)

    def test_the_sign_counts_reconcile_with_n_measured(self):
        group = [mrow(clv_bps=5.0), mrow(clv_bps=0.0, event_id="E2"),
                 mrow(clv_bps=-5.0, event_id="E3"),
                 mrow(clv_bps=-1.0, event_id="E4")]
        summary = clv.summarise(group)
        self.assertEqual(summary["clv_bps_positive"], 1)
        self.assertEqual(summary["clv_bps_zero"], 1)
        self.assertEqual(summary["clv_bps_negative"], 2)
        self.assertEqual(
            summary["clv_bps_positive"] + summary["clv_bps_zero"]
            + summary["clv_bps_negative"],
            summary["n_measured"])

    def test_the_move_sign_counts_reconcile_too(self):
        group = [mrow(clv_bps=1.0, move=5.0),
                 mrow(clv_bps=1.0, move=0.0, event_id="E2"),
                 mrow(clv_bps=1.0, move=-5.0, event_id="E3")]
        summary = clv.summarise(group)
        self.assertEqual(summary["consensus_move_bps_positive"], 1)
        self.assertEqual(summary["consensus_move_bps_zero"], 1)
        self.assertEqual(summary["consensus_move_bps_negative"], 1)
        self.assertEqual(
            summary["consensus_move_bps_positive"]
            + summary["consensus_move_bps_zero"]
            + summary["consensus_move_bps_negative"],
            summary["consensus_move_bps_n"])

    def test_end_to_end_an_exact_zero_clv_is_not_reported_as_positive(self):
        rows = h2h_board(CLOSE, away=-110, home=-110)
        summary = clv.summarise(
            [measured(decision(side="away", price=-100), rows)])
        self.assertEqual(summary["n_measured"], 1)
        self.assertEqual(summary["clv_bps_positive"], 0)
        self.assertEqual(summary["clv_bps_zero"], 1)


class MedianTest(unittest.TestCase):
    """`_median` had no value test at all.

    SURVIVING MUTATIONS THIS KILLS: returning the MEAN instead of the median,
    and returning the UPPER of the two middle elements on an even-length list.
    The fixtures are deliberately skewed -- [1, 2, 100] rather than
    [1, 2, 3] -- because on a symmetric list the mean and the median are the
    same number and the test cannot tell the two implementations apart. CLV
    rows are skewed in exactly this way, so the mean and median disagreeing
    is the normal case and is itself reportable.
    """

    def test_the_middle_value_of_an_odd_list_not_the_mean(self):
        self.assertEqual(clv._median([1.0, 2.0, 100.0]), 2.0)

    def test_the_mean_of_the_two_middles_on_an_even_list(self):
        # Upper element would be 4.0; the mean of all four is 26.75.
        self.assertEqual(clv._median([1.0, 2.0, 4.0, 100.0]), 3.0)

    def test_an_unsorted_list_is_ordered_first(self):
        self.assertEqual(clv._median([100.0, 1.0, 4.0, 2.0]), 3.0)
        self.assertEqual(clv._median([100.0, 2.0, 1.0]), 2.0)

    def test_an_empty_list_is_none_not_zero(self):
        self.assertIsNone(clv._median([]))

    def test_a_single_value_is_itself(self):
        self.assertEqual(clv._median([7.5]), 7.5)

    def test_the_callers_list_is_not_reordered(self):
        # `summarise` builds its lists once and reads them several times; a
        # rollup that sorted its own input in place would make every later cut
        # depend on which rollup ran first.
        values = [100.0, 1.0, 4.0, 2.0]
        clv._median(values)
        self.assertEqual(values, [100.0, 1.0, 4.0, 2.0])

    def test_the_rollup_reports_a_median_that_differs_from_its_mean(self):
        group = [mrow(clv_bps=1.0), mrow(clv_bps=2.0, event_id="E2"),
                 mrow(clv_bps=100.0, event_id="E3")]
        summary = clv.summarise(group)
        self.assertEqual(summary["clv_bps_median"], 2.0)
        self.assertAlmostEqual(summary["clv_bps_mean"], 103.0 / 3.0)


class StandardErrorTest(unittest.TestCase):
    """`_stderr_naive` had NO test at all, and the published conclusion rests
    on it.

    SURVIVING MUTATIONS THIS KILLS: replacing the whole body with
    `return 1.0`; dividing by n instead of n-1; and returning the standard
    deviation instead of the standard error of the mean. None of the three
    changes a sign or raises, so none is visible in a rendered table.

    Values [1, 2, 3, 4]: mean 2.5, squared deviations 2.25 + 0.25 + 0.25 +
    2.25 = 5.0. Sample variance 5/3; SEM = sqrt((5/3)/4) = 0.6454972243679028.
    The three wrong answers are 1.0, sqrt(1.25/4) = 0.5590169943749475, and
    sqrt(5/3) = 1.2909944487358056 -- all distinct from it and from each
    other, which is what makes this fixture able to tell them apart.
    """

    VALUES = [1.0, 2.0, 3.0, 4.0]
    SEM = 0.6454972243679028
    POPULATION_VARIANCE_SEM = 0.5590169943749475
    SAMPLE_SD = 1.2909944487358056

    def test_the_standard_error_is_pinned(self):
        self.assertAlmostEqual(clv._stderr_naive(self.VALUES), self.SEM,
                               places=12)

    def test_it_is_not_the_sample_standard_deviation(self):
        self.assertNotAlmostEqual(clv._stderr_naive(self.VALUES),
                                  self.SAMPLE_SD, places=6)

    def test_it_uses_the_sample_variance_not_the_population_variance(self):
        self.assertNotAlmostEqual(clv._stderr_naive(self.VALUES),
                                  self.POPULATION_VARIANCE_SEM, places=6)

    def test_a_single_observation_has_no_standard_error(self):
        # Undefined, not zero. Zero would read as certainty from one row.
        self.assertIsNone(clv._stderr_naive([42.0]))
        self.assertIsNone(clv._stderr_naive([]))

    def test_two_observations_are_enough(self):
        # sqrt(((1-2)^2 + (3-2)^2) / 1 / 2) = 1.0 -- pinned so the n>=2 gate
        # is not silently a n>=3 gate.
        self.assertAlmostEqual(clv._stderr_naive([1.0, 3.0]), 1.0, places=12)

    def test_identical_values_have_zero_spread(self):
        self.assertEqual(clv._stderr_naive([5.0, 5.0, 5.0]), 0.0)

    def test_it_shrinks_as_the_sample_grows_at_the_same_spread(self):
        # The structural property a constant cannot have.
        small = clv._stderr_naive(self.VALUES)
        large = clv._stderr_naive(self.VALUES * 4)
        self.assertLess(large, small)

    def test_the_rollup_reports_it(self):
        group = [mrow(clv_bps=v, event_id=f"E{i}")
                 for i, v in enumerate(self.VALUES)]
        summary = clv.summarise(group)
        self.assertAlmostEqual(summary["clv_bps_stderr_naive"], self.SEM,
                               places=12)
        self.assertEqual(summary["clv_bps_mean"], 2.5)


class SummariseTest(unittest.TestCase):
    def test_an_empty_group_reports_none_not_zero(self):
        summary = clv.summarise([])
        self.assertIsNone(summary["clv_bps_mean"])
        self.assertIsNone(summary["clv_bps_median"])
        self.assertEqual(summary["n_measured"], 0)

    def test_a_group_of_pure_absences_reports_none_not_zero(self):
        rows = h2h_board(CLOSE)
        summary = clv.summarise([measured(decision(verdict="refused_thin"),
                                          rows)])
        self.assertIsNone(summary["clv_bps_mean"])
        self.assertEqual(summary["n_decisions"], 1)
        self.assertEqual(summary["absences"][clv.NOT_A_BET]["n"], 1)

    def test_only_measured_rows_feed_the_mean(self):
        rows = h2h_board(CLOSE)
        group = [measured(decision(side="away", price=150), rows),
                 measured(decision(verdict="refused_thin"), rows)]
        summary = clv.summarise(group)
        self.assertEqual(summary["n_decisions"], 2)
        self.assertEqual(summary["n_measured"], 1)
        self.assertEqual(summary["clv_bps_mean"], 809.9)

    def test_games_are_counted_beside_decisions(self):
        rows = h2h_board(CLOSE) + h2h_board(CLOSE, event="E2")
        group = [measured(decision(system_id="a"), rows),
                 measured(decision(system_id="b"), rows),
                 measured(decision(system_id="a", event_id="E2"), rows)]
        summary = clv.summarise(group)
        self.assertEqual(summary["n_measured"], 3)
        self.assertEqual(summary["n_games"], 2)
        self.assertEqual(summary["n_systems"], 2)

    def test_companion_absences_are_counted_separately_from_row_absences(self):
        rows = h2h_board(CLOSE)
        summary = clv.summarise([
            measured(decision(side="home", price=-110, consensus_fair=None),
                     rows)])
        self.assertEqual(summary["n_measured"], 1)
        self.assertEqual(summary["absences"], {})
        self.assertEqual(
            summary["move_absences"][clv.DECISION_CONSENSUS_MISSING]["n"], 1)


class CohortCutTest(unittest.TestCase):
    """Cohorts come off the published slip, never off the decision.

    DEFECT THIS PINS: `by_cohort` read `record.cohorts`. `DecisionRecord` has
    no such field and refuses one on purpose -- rank, cohort and agreement
    live on the slip ledger, which is the sole authority on them -- so the cut
    could never activate at all, and its absence token blamed the wrong thing:
    it said no decision carried a tag, when the truth was that no decision
    ever could.
    """

    SLATE = "2026-09-05"

    def setUp(self):
        self.rows = h2h_board(CLOSE)
        self.pick = slip_pick(rank=1, event_id="E1", side="away")
        self.decision = decision(side="away", price=150, event_id="E1")

    def test_no_slip_ledger_is_a_named_absence(self):
        cut = clv.by_cohort([mrow(clv_bps=1.0)], slips=[])
        self.assertEqual(cut["absence"], clv.NO_SLIP_LEDGER)
        self.assertIn("slip", cut["absence_reason"])

    def test_a_slip_whose_picks_are_not_measured_is_a_different_absence(self):
        # Slips exist; this measurement set contains none of their picks. That
        # is not the same statement as "nothing has ever been published", and
        # rendering both as empty buckets would hide which one is true.
        other = slip_pick(rank=1, event_id="E9", side="home")
        cut = clv.by_cohort([measured(self.decision, self.rows)],
                            slips=[slip_row(date=self.SLATE, picks=[other])])
        self.assertEqual(cut["absence"], clv.NO_SLIP_PICK_MEASURED)
        self.assertEqual(cut["n_slip_picks"], 1)

    def test_a_pick_carrying_no_tag_never_produces_an_empty_cut(self):
        # `slip.cohorts_for_rank` always yields at least PUBLISHED, so this
        # should be unreachable -- but an empty dict here would render as
        # "measured and found nothing", which is the one thing this module
        # must never say by accident, so it is refused explicitly.
        untagged = dict(self.pick, cohorts=[])
        cut = clv.by_cohort([measured(self.decision, self.rows)],
                            slips=[slip_row(date=self.SLATE,
                                            picks=[untagged])])
        self.assertEqual(cut["absence"], clv.NO_SLIP_PICK_MEASURED)
        self.assertEqual(cut["n_slip_picks_tagged"], 0)

    def test_a_decision_carrying_its_own_cohorts_field_does_not_make_a_cut(self):
        # The dead code path. A dict fixture can carry `cohorts`; a real
        # DecisionRecord cannot, and this rollup must not read it either way.
        tagged = decision(side="away", price=150,
                          cohorts=("TOP_3", "PUBLISHED"))
        report = clv.report(decisions=[tagged], rows=self.rows, slips=[])
        self.assertEqual(report["by_cohort"]["absence"], clv.NO_SLIP_LEDGER)

    def test_the_cut_appears_once_a_slip_publishes_the_wager(self):
        report = clv.report(decisions=[self.decision], rows=self.rows,
                            slips=[slip_row(date=self.SLATE,
                                            picks=[self.pick])])
        cut = report["by_cohort"]
        self.assertNotIn("absence", cut)
        self.assertEqual(set(cut), {"TOP_3", "TOP_5", "PUBLISHED"})
        self.assertEqual(cut["TOP_3"]["n_measured"], 1)
        self.assertEqual(cut["PUBLISHED"]["clv_bps_mean"], 809.9)

    def test_a_pick_reports_under_every_tag_it_carries(self):
        # Cohorts NEST: a rank-1 pick is in all three cuts, and filing it
        # under the tuple instead would let the Top 3 record and the published
        # record disagree about a bet they both contain.
        rank_four = slip_pick(rank=4, event_id="E2", side="away")
        rows = self.rows + h2h_board(CLOSE, event="E2")
        cut = clv.by_cohort(
            [measured(self.decision, rows),
             measured(decision(side="away", price=150, event_id="E2"), rows)],
            slips=[slip_row(date=self.SLATE, picks=[self.pick, rank_four])])
        self.assertEqual(cut["PUBLISHED"]["n_measured"], 2)
        self.assertEqual(cut["TOP_5"]["n_measured"], 2)
        self.assertEqual(cut["TOP_3"]["n_measured"], 1)

    def test_the_join_is_on_the_slips_own_wager_identity(self):
        # Same event, same market, different SIDE. `selection_id` is what
        # distinguishes them, so a join on (event, market) alone would file
        # the home bet under the away pick's cohorts.
        home = decision(side="home", price=-110, event_id="E1")
        cut = clv.by_cohort([measured(home, self.rows)],
                            slips=[slip_row(date=self.SLATE,
                                            picks=[self.pick])])
        self.assertEqual(cut["absence"], clv.NO_SLIP_PICK_MEASURED)

    def test_a_row_with_no_recoverable_identity_is_skipped_not_fatal(self):
        # `families.wager_id` refuses a partly-blank identity by raising. A
        # decision that never recovered a selection simply has no slip to join
        # to; it must not take the whole report down.
        cut = clv.by_cohort(
            [mrow(clv_bps=1.0, selection=None),
             measured(self.decision, self.rows)],
            slips=[slip_row(date=self.SLATE, picks=[self.pick])])
        self.assertEqual(cut["TOP_3"]["n_measured"], 1)

    def test_the_last_slip_written_for_a_date_is_the_authority(self):
        # Several slips per date is the design (`slip.py`): a later pass saw
        # lineups the earlier one could not. If the later slip ranks the same
        # wager 4th, it is no longer a Top 3 pick, and merging the two slips
        # would leave it tagged TOP_3 forever.
        later = slip_pick(rank=4, event_id="E1", side="away")
        cut = clv.by_cohort(
            [measured(self.decision, self.rows)],
            slips=[slip_row(date=self.SLATE, slip_utc="2026-09-05T15:00:00Z",
                            picks=[self.pick]),
                   slip_row(date=self.SLATE, slip_utc="2026-09-05T22:00:00Z",
                            picks=[later])])
        self.assertEqual(set(cut), {"TOP_5", "PUBLISHED"})
        self.assertNotIn("TOP_3", cut)

    def test_a_later_slip_for_a_different_date_does_not_override(self):
        other_day = slip_pick(rank=4, event_id="E1", side="away")
        cut = clv.by_cohort(
            [measured(self.decision, self.rows)],
            slips=[slip_row(date=self.SLATE, picks=[self.pick]),
                   slip_row(date="2026-09-06", picks=[other_day])])
        # The 09-06 slip is later in the chain but speaks for a different
        # date, so it cannot reassign 09-05's cohorts. Both slips name the
        # same wager here only because the fixture reuses E1; the point is
        # that `latest_slip_per_date` keys on the slip's own date.
        self.assertIn("TOP_5", cut)

    def test_rows_that_are_not_slip_payloads_are_ignored(self):
        # The same `rule` guard `latest_slip_for` applies -- it is what
        # separates a slip payload from any other row on the chain.
        cut = clv.by_cohort([measured(self.decision, self.rows)],
                            slips=[{"date": self.SLATE, "picks": []}])
        self.assertEqual(cut["absence"], clv.NO_SLIP_LEDGER)

    def test_it_agrees_with_the_slip_modules_own_latest_slip_for(self):
        # The two implementations answer the same question -- this one over
        # every date in one pass -- so a test pins that they cannot drift.
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "slips_v1.jsonl")
            ledger = HashChainLedger(path)
            first = slip_row(date=self.SLATE, slip_utc="2026-09-05T15:00:00Z",
                             picks=[self.pick])
            second = slip_row(date=self.SLATE, slip_utc="2026-09-05T22:00:00Z",
                              picks=[slip_pick(rank=4, event_id="E1")])
            third = slip_row(date="2026-09-06", picks=[])
            for payload in (first, second, third):
                ledger.append(payload)
            per_date = clv.latest_slip_per_date(slip_mod.read_slips(path))
            for date in (self.SLATE, "2026-09-06"):
                self.assertEqual(per_date[date],
                                 slip_mod.latest_slip_for(date, path), date)

    def test_the_cohort_cut_carries_the_publication_segments_too(self):
        # A cohort rollup is a rollup: it must be as unable to hide a replay
        # row as every other cut is.
        replayed = decision(side="away", price=150, event_id="E1",
                            system_id="forward_thesis_2",
                            record_provenance=clv.PROVENANCE_REPLAY)
        cut = clv.by_cohort(
            [measured(self.decision, self.rows), measured(replayed, self.rows)],
            slips=[slip_row(date=self.SLATE, picks=[self.pick])])
        published = cut["TOP_3"]
        self.assertEqual(published["n_measured"], 2)
        self.assertEqual(published["n_publishable"], 1)
        self.assertEqual(
            published["segments"][clv.SEG_PROVENANCE_REPLAY]["n_decisions"], 1)


class ReportCutsTest(unittest.TestCase):
    def setUp(self):
        self.rows = h2h_board(CLOSE)
        self.decisions = [
            decision(system_id="trivial_always_home", side="home", price=-110),
            decision(system_id="market_derived_consensus_h2h_away",
                     side="away", price=150),
            decision(system_id="a1b2c3", side="away", price=150),
        ]

    def test_system_classes_follow_the_engine_bridge_prefix_rules(self):
        report = clv.report(decisions=self.decisions, rows=self.rows, slips=[])
        self.assertEqual(set(report["by_system_class"]),
                         {engine_bridge.CONTROL,
                          engine_bridge.MARKET_REFERENCE,
                          engine_bridge.FORWARD_TEST})
        self.assertEqual(
            report["by_system_class"][engine_bridge.CONTROL]["n_measured"], 1)
        self.assertEqual(
            report["by_system_class"][engine_bridge.FORWARD_TEST]["clv_bps_mean"],
            809.9)

    def test_the_market_cut_separates_markets(self):
        rows = self.rows + totals_board(CLOSE, total="8.5")
        report = clv.report(
            decisions=[decision(side="away", price=150),
                       decision(market_key="totals", side="over", line="8.5",
                                price=150)],
            rows=rows, slips=[])
        self.assertEqual(set(report["by_market"]), {"h2h", "totals"})

    def test_eligible_excludes_refusals_but_not_unmeasurable_bets(self):
        report = clv.report(
            decisions=self.decisions + [decision(verdict="refused_thin"),
                                        decision(event_id="MISSING")],
            rows=self.rows, slips=[])
        self.assertEqual(report["n_ledger_rows"], 5)
        self.assertEqual(report["n_eligible"], 4)

    def test_the_published_cut_admits_forward_test_only(self):
        """`is_publishable` gained a third condition (system_class ==
        FORWARD_TEST) after PUBLICATION_RULE's own prose -- "no backtests,
        replays, unpublished positions or controls" -- turned out to name a
        promise the code did not keep: measured on the real ledger, 938
        MARKET_REFERENCE and 469 CONTROL rows outnumbered 196 genuine
        FORWARD_TEST rows 7-to-1 in what `published_by_system_class` called
        "the cut". CONTROL and MARKET_REFERENCE stay fully computed in
        `by_system_class` (the unfiltered cut, used for diagnostics like the
        calibration proof below) -- they are simply never in `published`."""
        report = clv.report(decisions=self.decisions, rows=self.rows, slips=[])
        self.assertEqual(set(report["published_by_system_class"]),
                         {engine_bridge.FORWARD_TEST})
        self.assertNotIn(engine_bridge.CONTROL, report["published_by_system_class"])
        self.assertNotIn(engine_bridge.MARKET_REFERENCE,
                         report["published_by_system_class"])
        # The unfiltered cut still separates and still carries all three --
        # nothing here is dropped, only kept out of the "published" claim.
        self.assertEqual(set(report["by_system_class"]),
                         {engine_bridge.CONTROL,
                          engine_bridge.MARKET_REFERENCE,
                          engine_bridge.FORWARD_TEST})


class CalibrationResultTest(unittest.TestCase):
    """The instrument's own calibration result must stay statable.

    A MARKET_REFERENCE system republishes the board's own de-vigged
    consensus. Against a fair closing board its vig-neutral move should land
    at 50% positive and a mean of zero -- not because it is good, but because
    it is the market, and that is the correct answer for a republisher. It is
    the evidence that this instrument measures what it claims to. A rollup
    that pooled the classes, dropped the zero column, or zero-filled a
    withheld number would all destroy the ability to say it.
    """

    def _decisions(self):
        # Two systems, two games. One system freezes a consensus 200bps below
        # the eventual close, the other 200bps above it, so the class means
        # exactly zero with an even split of signs.
        out = []
        for event in ("E1", "E2"):
            out.append(decision(system_id="market_derived_consensus_a",
                                side="away", price=150, event_id=event,
                                consensus_fair=CLOSE_AWAY_FAIR - 0.02,
                                friction={"dispersion": 0.15}))
            out.append(decision(system_id="market_derived_consensus_b",
                                side="away", price=150, event_id=event,
                                consensus_fair=CLOSE_AWAY_FAIR + 0.02,
                                friction={"dispersion": 0.15}))
        return out

    def test_a_calibrated_republisher_reads_fifty_percent_and_zero(self):
        # `by_system_class` (the unfiltered cut), not `published_by_system_
        # class`: MARKET_REFERENCE is a diagnostic, never a published claim
        # (is_publishable's system_class condition), so this calibration
        # proof has to be read from the cut that still computes it.
        rows = h2h_board(CLOSE) + h2h_board(CLOSE, event="E2")
        report = clv.report(decisions=self._decisions(), rows=rows, slips=[])
        block = report["by_system_class"][engine_bridge.MARKET_REFERENCE]
        self.assertEqual(block["consensus_move_bps_n"], 4)
        self.assertEqual(block["consensus_move_bps_positive"], 2)
        self.assertEqual(block["consensus_move_bps_negative"], 2)
        self.assertEqual(block["consensus_move_bps_zero"], 0)
        self.assertEqual(block["consensus_move_bps_mean"], 0.0)

    def test_the_negative_clv_headline_is_the_vig_not_the_verdict(self):
        # The same rows read on `clv_bps` are all negative, because that
        # subtraction still carries the book's margin. Both numbers are
        # reported; only the vig-neutral one compares systems.
        # `by_system_class`, not `published_by_system_class` -- see the note
        # on the test above.
        rows = h2h_board(CLOSE) + h2h_board(CLOSE, event="E2")
        report = clv.report(decisions=self._decisions(), rows=rows, slips=[])
        block = report["by_system_class"][engine_bridge.MARKET_REFERENCE]
        self.assertEqual(block["clv_bps_positive"], 4)
        self.assertEqual(block["consensus_move_bps_mean"], 0.0)
        self.assertNotEqual(block["clv_bps_mean"],
                            block["consensus_move_bps_mean"])


class HonestyTest(unittest.TestCase):
    """Doctrine, enforced against the payload rather than the prose."""

    FORBIDDEN_TOKENS = {"edge", "ev", "profit", "roi", "expected"}
    FORBIDDEN_SUBSTRINGS = ("win_probability", "expected_value", "p_model")

    def _keys(self, node, seen):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str):
                    seen.add(key)
                self._keys(value, seen)
        elif isinstance(node, (list, tuple)):
            for item in node:
                self._keys(item, seen)
        return seen

    def test_no_payload_key_names_an_edge_or_an_expected_value(self):
        rows = h2h_board(CLOSE)
        report = clv.report(decisions=[decision(side="away", price=150)],
                            rows=rows, slips=[])
        for key in self._keys(report, set()):
            lowered = key.lower()
            self.assertFalse(
                set(re.split(r"[^a-z]+", lowered)) & self.FORBIDDEN_TOKENS,
                f"payload key {key!r} names a quantity this project has no "
                "basis to publish")
            for banned in self.FORBIDDEN_SUBSTRINGS:
                self.assertNotIn(banned, lowered)

    def test_the_label_says_what_clv_is_not(self):
        lowered = clv.LABEL.lower()
        self.assertIn("never a profit", lowered)
        self.assertIn("edge", lowered)  # only ever in the negation

    def test_the_report_carries_the_vig_and_independence_warnings(self):
        report = clv.report(decisions=[], rows=[], slips=[])
        self.assertIn("biased negative", report["vig_note"].lower())
        self.assertIn("not independent",
                      report["independence_note"].lower())

    def test_price_standing_is_named_execution_quality_not_an_edge(self):
        self.assertIn("not an edge", clv.VIG_NOTE.lower())

    def test_the_publication_rule_names_the_doctrine_section(self):
        self.assertIn("section 6", clv.PUBLICATION_RULE)
        self.assertIn(clv.PROVENANCE_PRE_COMMITMENT, clv.PUBLICATION_RULE)

    def test_an_empty_ledger_reports_an_honest_nothing(self):
        report = clv.report(decisions=[], rows=[], slips=[])
        self.assertEqual(report["n_ledger_rows"], 0)
        self.assertEqual(report["n_published"], 0)
        self.assertIsNone(report["overall"]["clv_bps_mean"])
        self.assertIsNone(report["published"]["clv_bps_mean"])
        self.assertEqual(report["by_cohort"]["absence"], clv.NO_SLIP_LEDGER)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
