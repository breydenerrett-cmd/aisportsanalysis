import unittest

from src.board.record import PriceObservation
from src.engine.analyze import Proposal
from src.engine.snapshot import PriceBlindSnapshot, PricedBoard
from src.engine.truncation import (
    ArrivalRecord, TruncationError, TruncationSample, diff_one_game,
    truncation_differential,
)

HOME = "aaaaaaaaaaaaaaaa"
AWAY = "bbbbbbbbbbbbbbbb"


def _po(selection_id, side, price, book="fanduel",
        observed_utc="2026-04-11T18:00:00Z"):
    return PriceObservation(
        sport="mlb", event_id="e1", game_pk=1, market_key="h2h",
        selection_id=selection_id, side=side, subject_kind=None,
        subject_id=None, line=None, book=book, price_american=price,
        observed_utc=observed_utc, book_last_update=None,
        known_at=observed_utc, known_at_grade="A",
        capture_id="c1", source="test", region="us",
        provider_market_key="h2h",
    )


def _board(t, observed_utc=None):
    # Quotes fresh AS OF `t` by default -- these tests exercise the
    # truncation differential's feature-arrival logic, not
    # PricedBoard.best/friction's own staleness bound (src/engine/snapshot
    # .py's STALE_QUOTE_SECONDS), so a board's quotes should not go stale
    # purely because `t` is hours after `t2h` in a fixture.
    observed_utc = observed_utc or t
    return PricedBoard.from_price_observations("1", t, (
        _po(HOME, "home", -150, book="a", observed_utc=observed_utc),
        _po(AWAY, "away", 130, book="a", observed_utc=observed_utc),
        _po(HOME, "home", -140, book="b", observed_utc=observed_utc),
        _po(AWAY, "away", 120, book="b", observed_utc=observed_utc),
    ))


def _snapshot(t, **features):
    return PriceBlindSnapshot(
        game_pk="1", t=t, point_class="LATE_BOARD", features=features,
        available_markets=("h2h",), books_by_market={"h2h": 2},
    )


class _EraSystem:
    """Proposes home whenever the (fixed, feature-driven) era differential
    crosses a threshold -- a stand-in for a real system whose belief can
    change between t-2h and t only because a feature value changed."""

    id = "era_system"
    version = "1"
    spec_hash = "h"
    declared_markets = ("h2h",)
    declared_inputs = ("era_diff",)
    min_grade = "D"
    expected_selection_rate = 0.0

    def propose(self, view):
        diff = view.features.get("era_diff")
        if diff is None or diff <= 0:
            return ()
        return (Proposal(
            system_id=self.id, system_version=self.version,
            market_key="h2h", side="home", p_model=0.6,
            thesis="era_diff positive", evidence=("era_diff",),
        ),)


T2H = "2026-04-11T18:00:00Z"
T = "2026-04-11T20:00:00Z"


class TestDiffOneGame(unittest.TestCase):
    def test_no_change_produces_no_diffs(self):
        sample = TruncationSample(
            game_pk="1", t2h=T2H, t=T,
            snapshot_t2h=_snapshot(T2H, era_diff=1.0),
            board_t2h=_board(T2H),
            snapshot_t=_snapshot(T, era_diff=1.0),
            board_t=_board(T),
            arrivals=(),
        )
        diffs = diff_one_game(sample, systems=[_EraSystem()])
        self.assertEqual(diffs, ())

    def test_attributable_arrival_marks_diff_attributable_and_passes_gate(self):
        arrival = ArrivalRecord(field="era_diff", observed_utc="2026-04-11T19:00:00Z")
        sample = TruncationSample(
            game_pk="1", t2h=T2H, t=T,
            snapshot_t2h=_snapshot(T2H, era_diff=-1.0),  # no play at t-2h
            board_t2h=_board(T2H),
            snapshot_t=_snapshot(T, era_diff=1.0),  # era_diff arrived -> play
            board_t=_board(T),
            arrivals=(arrival,),
        )
        diffs = diff_one_game(sample, systems=[_EraSystem()])
        self.assertEqual(len(diffs), 1)
        self.assertTrue(diffs[0].attributable)
        self.assertIn("era_diff", diffs[0].causes)

        report = truncation_differential([sample], systems=[_EraSystem()])
        self.assertTrue(report.gate_result.passed, report.gate_result.reasons)
        self.assertEqual(report.gate_result.gate, "G4")
        self.assertEqual(report.leakage_failures, ())

    def test_planted_future_field_with_no_arrival_is_a_leakage_fail(self):
        """The decision changed between t-2h and t, but NO provenance
        arrival was recorded in the window -- exactly the leakage this gate
        exists to catch (a field the t-2h run should not have been able to
        see influencing the outcome, or an unexplained divergence)."""
        sample = TruncationSample(
            game_pk="1", t2h=T2H, t=T,
            snapshot_t2h=_snapshot(T2H, era_diff=-1.0),
            board_t2h=_board(T2H),
            snapshot_t=_snapshot(T, era_diff=1.0),
            board_t=_board(T),
            arrivals=(),  # nothing recorded -- unexplained
        )
        diffs = diff_one_game(sample, systems=[_EraSystem()])
        self.assertEqual(len(diffs), 1)
        self.assertFalse(diffs[0].attributable)

        report = truncation_differential([sample], systems=[_EraSystem()])
        self.assertFalse(report.gate_result.passed)
        self.assertEqual(report.gate_result.gate, "G4")
        self.assertEqual(len(report.leakage_failures), 1)
        self.assertIn("LEAKAGE", report.gate_result.reasons[0])

    def test_arrival_outside_window_does_not_count(self):
        # Arrival happens AFTER t -- out of the (t-2h, t] window, so it
        # cannot explain a change observed at t.
        arrival = ArrivalRecord(field="era_diff", observed_utc="2026-04-11T21:00:00Z")
        sample = TruncationSample(
            game_pk="1", t2h=T2H, t=T,
            snapshot_t2h=_snapshot(T2H, era_diff=-1.0),
            board_t2h=_board(T2H),
            snapshot_t=_snapshot(T, era_diff=1.0),
            board_t=_board(T),
            arrivals=(arrival,),
        )
        report = truncation_differential([sample], systems=[_EraSystem()])
        self.assertFalse(report.gate_result.passed)

    def test_t2h_must_precede_t(self):
        sample = TruncationSample(
            game_pk="1", t2h=T, t=T2H,
            snapshot_t2h=_snapshot(T), board_t2h=_board(T),
            snapshot_t=_snapshot(T2H), board_t=_board(T2H),
        )
        with self.assertRaises(TruncationError):
            diff_one_game(sample, systems=[_EraSystem()])

    def test_empty_sample_rejected(self):
        with self.assertRaises(TruncationError):
            truncation_differential([], systems=[_EraSystem()])

    def test_gate_result_is_gate_result_compatible(self):
        arrival = ArrivalRecord(field="era_diff", observed_utc="2026-04-11T19:00:00Z")
        sample = TruncationSample(
            game_pk="1", t2h=T2H, t=T,
            snapshot_t2h=_snapshot(T2H, era_diff=1.0), board_t2h=_board(T2H),
            snapshot_t=_snapshot(T, era_diff=1.0), board_t=_board(T),
            arrivals=(arrival,),
        )
        report = truncation_differential([sample], systems=[_EraSystem()])
        gr = report.gate_result
        self.assertTrue(hasattr(gr, "gate"))
        self.assertTrue(hasattr(gr, "passed"))
        self.assertTrue(hasattr(gr, "reasons"))
        self.assertTrue(hasattr(gr, "inputs_hash"))
        self.assertEqual(bool(gr), gr.passed)


if __name__ == "__main__":
    unittest.main()
